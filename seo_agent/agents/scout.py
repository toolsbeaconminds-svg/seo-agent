import json
import re
import anthropic

from config import settings
from core.prompts import SCOUT_EXTRACTION_PROMPT
from tools.scraper import PlaywrightScraper
from tools.ahrefs_client import AhrefsClient


class ScoutAgent:
    """Scrapes the website, extracts business info, finds competitors via Ahrefs."""

    def __init__(self):
        self.llm = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.ahrefs = AhrefsClient()

    async def run(self, state: dict) -> dict:
        url = state["url"]
        print(f"  [scout] Scraping {url}...")

        # 1. Scrape
        scraper = PlaywrightScraper()
        async with scraper:
            pages = await scraper.scrape_site(url)

        if not pages:
            state.setdefault("errors", []).append("Scout: could not scrape any pages")
            return state

        # 1b. Check robots.txt and sitemap (uses httpx, not Playwright)
        base_url = url.rstrip("/")
        try:
            robots_txt = await scraper.check_robots_txt(base_url)
            state["robots_txt"] = robots_txt
            print(f"  [scout] robots.txt: {'found' if robots_txt else 'not found'}")
        except Exception as e:
            state["robots_txt"] = None
            print(f"  [scout] robots.txt check failed: {e}")

        try:
            sitemap_data = await scraper.check_sitemap(base_url)
            state["sitemap"] = sitemap_data
            print(f"  [scout] sitemap.xml: {'found' if sitemap_data.get('exists') else 'not found'}"
                  + (f" ({sitemap_data.get('url_count', 0)} URLs)" if sitemap_data.get('exists') else ""))
        except Exception as e:
            state["sitemap"] = {"exists": False, "error": str(e)}
            print(f"  [scout] sitemap check failed: {e}")

        # 1c. Store on-page SEO data from all scraped pages
        on_page_audit = []
        for p in pages:
            on_page_audit.append({
                "url": p.get("url"),
                "title": p.get("title"),
                "meta_description": p.get("meta_description"),
                "canonical": p.get("canonical"),
                "robots_meta": p.get("robots_meta"),
                "word_count": p.get("word_count", 0),
                "headings": p.get("headings", {}),
                "images_total": len(p.get("images", [])),
                "images_without_alt": sum(1 for img in p.get("images", []) if not img.get("alt")),
                "internal_links_count": len(p.get("internal_links", [])),
                "external_links_count": len(p.get("external_links", [])),
                "has_schema": bool(p.get("schema_json")),
                "schema_types": [s.get("@type", "") for s in p.get("schema_json", []) if isinstance(s, dict)],
                "has_viewport_meta": p.get("has_viewport_meta", False),
                "lang": p.get("lang"),
                "og_tags": p.get("og_tags", {}),
            })
        state["on_page_audit"] = on_page_audit

        print(f"  [scout] Scraped {len(pages)} pages, extracting business info...")

        # 2. Extract business info via Claude
        pages_text = []
        for p in pages:
            t = f"--- {p['url']} ---\nTitle: {p.get('title','')}\nMeta: {p.get('meta_description','')}\n"
            for tag, vals in p.get("headings", {}).items():
                t += f"{tag}: {', '.join(vals)}\n"
            html = p.get("html", "")[:12000]
            t += f"HTML:\n{html}\n"
            pages_text.append(t)

        resp = await self.llm.messages.create(
            model=settings.LLM_EXTRACTION_MODEL, max_tokens=2000,
            system=SCOUT_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": "\n\n".join(pages_text)}],
        )
        info = _parse_json(resp.content[0].text) or {}

        # 3. Competitors via Ahrefs
        domain = _extract_domain(url)
        competitors = []
        try:
            competitors = await self.ahrefs.get_organic_competitors(domain, limit=10)
            print(f"  [scout] Found {len(competitors)} organic competitors via Ahrefs")
        except Exception as e:
            print(f"  [scout] Ahrefs competitor lookup failed: {e}")
            state.setdefault("errors", []).append(f"Scout competitors: {e}")

        # 4. Infer keywords
        service = info.get("primary_service", "")
        city = (info.get("location") or {}).get("city", "") if isinstance(info.get("location"), dict) else ""
        keywords = []
        if service and city:
            keywords = [f"{service} {city}", f"best {service} {city}", f"{service} near me"]
        elif service:
            keywords = [service, f"best {service}", f"{service} services"]

        state["business_name"] = info.get("business_name") or "Unknown"
        state["business_description"] = info.get("business_description", "")
        state["location"] = info.get("location", {})
        state["key_person"] = info.get("key_person", {})
        state["conversion_action"] = info.get("conversion_action", "")
        state["business_model"] = info.get("business_model", "other")
        state["competitors"] = competitors
        state["target_keywords"] = keywords[:3]

        print(f"  [scout] Done — {state['business_name']}, {len(competitors)} competitors, {len(keywords)} keywords")
        return state


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url if url.startswith("http") else f"https://{url}")
    return p.netloc or p.path.split("/")[0]


def _parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    return None
