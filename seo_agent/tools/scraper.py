import httpx
from xml.etree import ElementTree
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

SCOUT_PATHS = ["/", "/about", "/about-us", "/team", "/doctor", "/our-doctor", "/services", "/contact"]


class PlaywrightScraper:
    def __init__(self):
        self._pw = None
        self._browser = None

    async def start(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True, args=["--no-sandbox"])

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def scrape_page(self, url: str) -> dict:
        if not self._browser:
            await self.start()

        page = await self._browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else 0
            await page.wait_for_timeout(2000)

            html = await page.content()
            title = await page.title()
            meta_desc = await page.evaluate('() => { const el = document.querySelector(\'meta[name="description"]\'); return el ? el.getAttribute("content") : null; }')
            headings = await page.evaluate("""() => {
                const r = {};
                for (let i = 1; i <= 3; i++) {
                    const els = document.querySelectorAll('h' + i);
                    if (els.length) r['h' + i] = Array.from(els).map(e => e.textContent.trim()).slice(0, 10);
                }
                return r;
            }""")

            seo_data = await page.evaluate("""(pageUrl) => {
                const hostname = new URL(pageUrl).hostname;

                // canonical
                const canonicalEl = document.querySelector('link[rel="canonical"]');
                const canonical = canonicalEl ? canonicalEl.getAttribute('href') : null;

                // robots meta
                const robotsEl = document.querySelector('meta[name="robots"]');
                const robots_meta = robotsEl ? robotsEl.getAttribute('content') : null;

                // og tags
                const og_tags = {};
                const ogMap = {title: 'og:title', description: 'og:description', image: 'og:image', type: 'og:type'};
                for (const [key, prop] of Object.entries(ogMap)) {
                    const el = document.querySelector('meta[property="' + prop + '"]');
                    og_tags[key] = el ? el.getAttribute('content') : null;
                }

                // schema JSON-LD
                const schema_json = [];
                document.querySelectorAll('script[type="application/ld+json"]').forEach(el => {
                    try { schema_json.push(JSON.parse(el.textContent)); } catch(e) {}
                });

                // images (limit 50)
                const images = Array.from(document.querySelectorAll('img')).slice(0, 50).map(img => ({
                    src: img.getAttribute('src'),
                    alt: img.getAttribute('alt') || '',
                    width: img.getAttribute('width') || img.naturalWidth || null,
                    height: img.getAttribute('height') || img.naturalHeight || null
                }));

                // links
                const internal_links = [];
                const external_links = [];
                document.querySelectorAll('a[href]').forEach(a => {
                    const href = a.getAttribute('href');
                    if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) return;
                    try {
                        const linkUrl = new URL(href, pageUrl);
                        if (linkUrl.hostname === hostname) {
                            if (internal_links.length < 100) internal_links.push(linkUrl.href);
                        } else {
                            if (external_links.length < 50) external_links.push({href: linkUrl.href, rel: a.getAttribute('rel') || ''});
                        }
                    } catch(e) {}
                });

                // word count
                const text = document.body ? document.body.innerText : '';
                const word_count = text.split(/\\s+/).filter(w => w.length > 0).length;

                // viewport meta
                const has_viewport_meta = !!document.querySelector('meta[name="viewport"]');

                // lang
                const lang = document.documentElement.getAttribute('lang') || null;

                return {
                    canonical,
                    robots_meta,
                    og_tags,
                    schema_json,
                    images,
                    internal_links,
                    external_links,
                    word_count,
                    has_viewport_meta,
                    lang
                };
            }""", url)

            return {
                "url": url,
                "status_code": status,
                "title": title,
                "meta_description": meta_desc,
                "html": html,
                "headings": headings,
                **seo_data,
            }
        except PlaywrightTimeout:
            return {"url": url, "status_code": 0, "error": "timeout"}
        except Exception as e:
            return {"url": url, "status_code": 0, "error": str(e)}
        finally:
            await page.close()

    async def scrape_site(self, base_url: str) -> list[dict]:
        base_url = base_url.rstrip("/")
        results = []
        for path in SCOUT_PATHS:
            r = await self.scrape_page(f"{base_url}{path}")
            if r.get("status_code") in (200, 301, 302):
                results.append(r)
        return results

    async def check_robots_txt(self, base_url: str) -> str | None:
        """Fetch /robots.txt via httpx. Returns text content or None if not found."""
        base_url = base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                resp = await client.get(f"{base_url}/robots.txt")
                if resp.status_code == 200:
                    return resp.text
                return None
        except Exception:
            return None

    async def check_sitemap(self, base_url: str) -> dict:
        """Fetch /sitemap.xml via httpx. Returns {exists, url_count, urls[:20]}."""
        base_url = base_url.rstrip("/")
        result = {"exists": False, "url_count": 0, "urls": []}
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                resp = await client.get(f"{base_url}/sitemap.xml")
                if resp.status_code != 200:
                    return result
            root = ElementTree.fromstring(resp.content)
            # Handle namespaced sitemaps (e.g. xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"
            urls = [loc.text for loc in root.iter(f"{ns}loc") if loc.text]
            result["exists"] = True
            result["url_count"] = len(urls)
            result["urls"] = urls[:20]
        except Exception:
            pass
        return result

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *a):
        await self.stop()
