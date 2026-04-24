import httpx
from datetime import datetime, timedelta

from config import settings

BASE = "https://api.ahrefs.com/v3"


def _recent_date() -> str:
    """Ahrefs wants a date param — use a recent date."""
    return (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")


class AhrefsClient:
    def __init__(self):
        self._key = settings.AHREFS_API_KEY

    def _headers(self):
        return {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}

    async def _get(self, path: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(f"{BASE}{path}", headers=self._headers(), params=params)
            if r.status_code >= 400:
                print(f"    [ahrefs] API error {r.status_code} on {path}: {r.text[:300]}")
            r.raise_for_status()
            return r.json()

    async def get_domain_rating(self, target: str) -> dict:
        return await self._get("/site-explorer/domain-rating", {
            "target": target, "date": _recent_date(),
        })

    async def get_backlinks_stats(self, target: str) -> dict:
        return await self._get("/site-explorer/backlinks-stats", {
            "target": target, "date": _recent_date(),
        })

    async def get_metrics(self, target: str) -> dict:
        return await self._get("/site-explorer/metrics", {
            "target": target, "date": _recent_date(),
        })

    async def get_organic_keywords(self, target: str, limit: int = 100, country: str = "us") -> list[dict]:
        data = await self._get("/site-explorer/organic-keywords", {
            "target": target, "country": country, "limit": limit,
            "select": "keyword,best_position,volume,sum_traffic,best_position_url",
            "date": _recent_date(),
        })
        # Normalize field names for downstream consumers
        keywords = data.get("keywords", [])
        for k in keywords:
            if "best_position" in k:
                k["position"] = k.pop("best_position")
            if "sum_traffic" in k:
                k["traffic"] = k.pop("sum_traffic")
            if "best_position_url" in k:
                k["url"] = k.pop("best_position_url")
        return keywords

    async def get_organic_competitors(self, target: str, limit: int = 10, country: str = "us") -> list[dict]:
        data = await self._get("/site-explorer/organic-competitors", {
            "target": target, "limit": limit, "country": country,
            "date": _recent_date(),
            "select": "competitor_domain,keywords_common,traffic,domain_rating",
        })
        competitors = data.get("competitors", [])
        return [
            {"domain": c.get("competitor_domain", ""), "common_keywords": c.get("keywords_common", 0),
             "organic_traffic": c.get("traffic", 0), "domain_rating": c.get("domain_rating", 0)}
            for c in competitors
        ]

    async def get_keyword_gap(self, target: str, competitors: list[str]) -> list[dict]:
        target_kws = await self.get_organic_keywords(target, limit=200)
        target_set = {k["keyword"].lower() for k in target_kws if "keyword" in k}

        gaps = []
        for comp in competitors[:3]:
            try:
                comp_kws = await self.get_organic_keywords(comp, limit=50)
                for k in comp_kws:
                    kw = k.get("keyword", "").lower()
                    if kw and kw not in target_set and k.get("position", 100) <= 20:
                        gaps.append({"keyword": kw, "competitor": comp,
                                     "competitor_position": k["position"], "volume": k.get("volume", 0)})
            except Exception:
                pass

        seen = {}
        for g in gaps:
            if g["keyword"] not in seen or g["competitor_position"] < seen[g["keyword"]]["competitor_position"]:
                seen[g["keyword"]] = g
        return sorted(seen.values(), key=lambda x: x.get("volume", 0), reverse=True)

    async def get_referring_domains(self, target: str, limit: int = 50) -> list[dict]:
        data = await self._get("/site-explorer/referring-domains", {
            "target": target, "date": _recent_date(), "limit": limit,
            "select": "domain,domain_rating,backlinks,first_seen,last_seen",
        })
        return data.get("refdomains", [])

    async def get_anchors(self, target: str, limit: int = 30) -> list[dict]:
        data = await self._get("/site-explorer/anchors", {
            "target": target, "date": _recent_date(), "limit": limit,
            "select": "anchor,backlinks,referring_domains",
        })
        return data.get("anchors", [])

    async def get_broken_backlinks(self, target: str, limit: int = 20) -> list[dict]:
        data = await self._get("/site-explorer/broken-backlinks", {
            "target": target, "date": _recent_date(), "limit": limit,
            "select": "url_from,url_to,anchor,http_code,first_seen",
        })
        return data.get("backlinks", [])

    async def get_top_pages(self, target: str, limit: int = 20) -> list[dict]:
        data = await self._get("/site-explorer/top-pages", {
            "target": target, "date": _recent_date(), "limit": limit,
            "select": "url,sum_traffic,keywords,best_position",
        })
        return data.get("pages", [])

    async def get_all_data(self, target: str) -> dict:
        result = {}

        for name, coro in [
            ("metrics", self.get_metrics(target)),
            ("domain_rating", self.get_domain_rating(target)),
            ("backlinks", self.get_backlinks_stats(target)),
            ("organic_keywords", self.get_organic_keywords(target)),
            ("competitors", self.get_organic_competitors(target)),
            ("referring_domains", self.get_referring_domains(target)),
            ("anchors", self.get_anchors(target)),
            ("broken_backlinks", self.get_broken_backlinks(target)),
            ("top_pages", self.get_top_pages(target)),
        ]:
            try:
                result[name] = await coro
            except Exception as e:
                print(f"    [ahrefs] {name} failed: {e}")
                result[name] = {"error": str(e)}

        comp_domains = []
        if isinstance(result.get("competitors"), list):
            comp_domains = [c["domain"] for c in result["competitors"][:3] if c.get("domain")]
        if comp_domains:
            try:
                result["keyword_gap"] = await self.get_keyword_gap(target, comp_domains)
            except Exception as e:
                print(f"    [ahrefs] keyword_gap failed: {e}")
                result["keyword_gap"] = []
        else:
            result["keyword_gap"] = []

        return result
