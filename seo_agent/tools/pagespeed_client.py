"""PageSpeed Insights client — Core Web Vitals and performance data."""

import httpx

PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedClient:
    def __init__(self, api_key: str | None = None):
        self._key = api_key  # Optional — works without it but rate-limited

    async def analyse(self, url: str, strategy: str = "mobile") -> dict:
        """Run PageSpeed analysis. strategy: 'mobile' or 'desktop'."""
        params = {"url": url, "strategy": strategy, "category": ["performance", "accessibility", "best-practices", "seo"]}
        if self._key:
            params["key"] = self._key

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.get(PSI_URL, params=params)
            if r.status_code >= 400:
                print(f"    [pagespeed] API error {r.status_code}: {r.text[:200]}")
                return {"error": r.text[:200]}
            data = r.json()

        result = {"url": url, "strategy": strategy}

        # Lighthouse scores (0-100)
        categories = data.get("lighthouseResult", {}).get("categories", {})
        for cat_key in ["performance", "accessibility", "best-practices", "seo"]:
            cat = categories.get(cat_key, {})
            result[f"{cat_key.replace('-', '_')}_score"] = round((cat.get("score") or 0) * 100)

        # Core Web Vitals from field data (CrUX)
        crux = data.get("loadingExperience", {}).get("metrics", {})
        vitals_map = {
            "LARGEST_CONTENTFUL_PAINT_MS": "lcp_ms",
            "FIRST_INPUT_DELAY_MS": "fid_ms",
            "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls",
            "INTERACTION_TO_NEXT_PAINT": "inp_ms",
            "FIRST_CONTENTFUL_PAINT_MS": "fcp_ms",
            "EXPERIMENTAL_TIME_TO_FIRST_BYTE": "ttfb_ms",
        }
        for api_key, result_key in vitals_map.items():
            metric = crux.get(api_key, {})
            result[result_key] = metric.get("percentile")
            result[f"{result_key}_category"] = metric.get("category")  # FAST, AVERAGE, SLOW

        # Lab data audits (key ones)
        audits = data.get("lighthouseResult", {}).get("audits", {})
        for audit_key in ["speed-index", "total-blocking-time", "server-response-time",
                          "render-blocking-resources", "unused-css-rules", "unused-javascript",
                          "uses-responsive-images", "uses-optimized-images", "uses-text-compression"]:
            audit = audits.get(audit_key, {})
            if audit:
                result[f"audit_{audit_key.replace('-', '_')}"] = {
                    "score": audit.get("score"),
                    "value": audit.get("displayValue"),
                    "description": audit.get("title"),
                }

        return result

    async def get_all_data(self, url: str) -> dict:
        """Get both mobile and desktop PageSpeed data."""
        result = {}
        for strategy in ["mobile", "desktop"]:
            try:
                result[strategy] = await self.analyse(url, strategy)
            except Exception as e:
                print(f"    [pagespeed] {strategy} failed: {e}")
                result[strategy] = {"error": str(e)}
        return result
