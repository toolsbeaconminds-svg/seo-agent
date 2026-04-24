"""WordPress REST API client — handles all WP interactions."""

import json
import re
from urllib.parse import urlparse

import httpx

from config import settings


class WPClient:
    """Wraps the WordPress REST API with Application Password auth."""

    def __init__(self):
        if not all([settings.WP_URL, settings.WP_USERNAME, settings.WP_APP_PASSWORD]):
            raise RuntimeError("WordPress credentials not configured (WP_URL, WP_USERNAME, WP_APP_PASSWORD)")

        self.base = settings.WP_URL.rstrip("/")
        self.api = f"{self.base}/wp-json/wp/v2"
        self.auth = (settings.WP_USERNAME, settings.WP_APP_PASSWORD)
        self._client = httpx.AsyncClient(auth=self.auth, timeout=30, follow_redirects=True)

    async def close(self):
        await self._client.aclose()

    # ── Read operations ──────────────────────────────────────────────

    async def get_post_by_slug(self, slug: str) -> dict | None:
        """Find a post or page by its URL slug."""
        slug = slug.strip("/").split("/")[-1]
        for endpoint in ["posts", "pages"]:
            r = await self._client.get(f"{self.api}/{endpoint}", params={"slug": slug})
            if r.status_code == 200:
                items = r.json()
                if items:
                    return items[0]
        return None

    async def get_post_by_url(self, url: str) -> dict | None:
        """Find a post or page by its full URL."""
        parsed = urlparse(url)
        slug = parsed.path.strip("/").split("/")[-1]
        return await self.get_post_by_slug(slug)

    async def get_post(self, post_id: int) -> dict:
        """Get a post/page by ID."""
        r = await self._client.get(f"{self.api}/posts/{post_id}")
        if r.status_code == 200:
            return r.json()
        r = await self._client.get(f"{self.api}/pages/{post_id}")
        r.raise_for_status()
        return r.json()

    async def verify_page_status(self, url: str) -> int:
        """HTTP GET a URL and return the status code."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
                r = await c.get(url)
                return r.status_code
        except Exception:
            return 0

    # ── Write operations ─────────────────────────────────────────────

    async def update_seo_meta(self, post_id: int, title: str | None = None,
                              meta_description: str | None = None,
                              post_type: str = "posts") -> dict:
        """Update Yoast SEO title and meta description via post meta."""
        meta = {}
        if title:
            meta["_yoast_wpseo_title"] = title
        if meta_description:
            meta["_yoast_wpseo_metadesc"] = meta_description
        if not meta:
            return {"skipped": True}

        r = await self._client.post(
            f"{self.api}/{post_type}/{post_id}",
            json={"meta": meta}
        )
        r.raise_for_status()
        return r.json()

    async def update_post_canonical(self, post_id: int, canonical_url: str,
                                    post_type: str = "posts") -> dict:
        """Set the canonical URL via Yoast meta."""
        r = await self._client.post(
            f"{self.api}/{post_type}/{post_id}",
            json={"meta": {"_yoast_wpseo_canonical": canonical_url}}
        )
        r.raise_for_status()
        return r.json()

    async def set_noindex(self, post_id: int, noindex: bool = True,
                          post_type: str = "posts") -> dict:
        """Set noindex via Yoast meta."""
        r = await self._client.post(
            f"{self.api}/{post_type}/{post_id}",
            json={"meta": {"_yoast_wpseo_meta-robots-noindex": "1" if noindex else "0"}}
        )
        r.raise_for_status()
        return r.json()

    async def add_redirect(self, source: str, destination: str, redirect_type: int = 301) -> dict:
        """Add a redirect via the Redirection plugin REST API."""
        r = await self._client.post(
            f"{self.base}/wp-json/redirection/v1/redirect",
            json={
                "url": source,
                "action_data": {"url": destination},
                "action_type": "url",
                "action_code": redirect_type,
                "match_type": "url",
                "group_id": 1,
            }
        )
        if r.status_code in (200, 201):
            return r.json()
        # Redirection plugin not available — return instructions
        return {
            "error": "Redirection plugin not active",
            "manual_fix": f"Add to .htaccess: Redirect {redirect_type} {source} {destination}"
        }

    async def update_image_alt_text(self, attachment_id: int, alt_text: str) -> dict:
        """Update alt text for a media attachment."""
        r = await self._client.post(
            f"{self.api}/media/{attachment_id}",
            json={"alt_text": alt_text}
        )
        r.raise_for_status()
        return r.json()

    async def inject_schema(self, post_id: int, schema_json: str,
                            post_type: str = "posts") -> dict:
        """Inject JSON-LD schema into the post content as a Custom HTML block."""
        post = await self.get_post(post_id)
        content = post.get("content", {}).get("raw", post.get("content", {}).get("rendered", ""))

        # Remove any existing JSON-LD block
        content = re.sub(
            r'<!-- wp:html -->\s*<script type="application/ld\+json">.*?</script>\s*<!-- /wp:html -->',
            '', content, flags=re.DOTALL
        ).strip()

        # Append new schema block
        schema_block = (
            f'\n\n<!-- wp:html -->\n'
            f'<script type="application/ld+json">\n{schema_json}\n</script>\n'
            f'<!-- /wp:html -->'
        )
        content += schema_block

        r = await self._client.post(
            f"{self.api}/{post_type}/{post_id}",
            json={"content": content}
        )
        r.raise_for_status()
        return r.json()

    async def create_page(self, title: str, content: str, slug: str,
                          status: str = "draft") -> dict:
        """Create a new page as draft."""
        r = await self._client.post(
            f"{self.api}/pages",
            json={"title": title, "content": content, "slug": slug, "status": status}
        )
        r.raise_for_status()
        return r.json()

    async def list_posts(self, per_page: int = 100, post_type: str = "posts") -> list[dict]:
        """List posts or pages."""
        r = await self._client.get(f"{self.api}/{post_type}", params={"per_page": per_page})
        r.raise_for_status()
        return r.json()
