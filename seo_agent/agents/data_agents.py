"""GSC, GA4, Ahrefs, and PageSpeed data collection agents — all in one file since they're simple."""

from tools.gsc_client import GSCClient
from tools.ga4_client import GA4Client
from tools.ahrefs_client import AhrefsClient
from tools.pagespeed_client import PageSpeedClient

SPAM_TERMS = {"casino", "gambling", "betting", "türkçe", "vaycasino", "poker", "slot"}


class GSCAgent:
    async def run(self, state: dict) -> dict:
        url = state["url"].rstrip("/")
        if not url.startswith("http"):
            url = f"https://{url}"

        print(f"  [gsc] Pulling Search Console data...")
        try:
            client = GSCClient()
            data = await client.get_all_data(url)
            state["gsc_data"] = data

            # Anomaly detection
            anomalies = state.setdefault("anomalies", [])
            for q in data.get("queries", []):
                if any(t in q.get("query", "").lower() for t in SPAM_TERMS):
                    anomalies.append("SPAM_INJECTION")
                    print(f"  [gsc] ⚠ SPAM DETECTED: {q['query']}")
                    break
            if len(data.get("pages", [])) < 10:
                anomalies.append("INDEXATION_PROBLEM")

            print(f"  [gsc] Done — {len(data.get('queries',[]))} queries, {len(data.get('pages',[]))} pages")
        except Exception as e:
            print(f"  [gsc] Failed: {e}")
            state["gsc_data"] = {"error": str(e)}
            state.setdefault("errors", []).append(f"GSC: {e}")
        return state


class GA4Agent:
    async def run(self, state: dict) -> dict:
        print(f"  [ga4] Pulling Analytics data...")
        try:
            client = GA4Client()
            data = await client.get_all_data()
            state["ga4_data"] = data

            # Anomaly detection
            anomalies = state.setdefault("anomalies", [])
            total_events = sum(e.get("event_count", 0) for e in data.get("key_events", []))
            if total_events == 0:
                anomalies.append("NO_CONVERSIONS_TRACKED")

            channels = data.get("channels", [])
            total = sum(c.get("sessions", 0) for c in channels)
            organic = sum(c.get("sessions", 0) for c in channels if "organic" in c.get("channel", "").lower())
            if total > 0 and organic / total < 0.05:
                anomalies.append("LOW_ORGANIC_TRAFFIC")

            print(f"  [ga4] Done — {len(channels)} channels, {len(data.get('key_events',[]))} events")
        except Exception as e:
            print(f"  [ga4] Failed: {e}")
            state["ga4_data"] = {"error": str(e)}
            state.setdefault("errors", []).append(f"GA4: {e}")
        return state


class AhrefsAgent:
    async def run(self, state: dict) -> dict:
        from urllib.parse import urlparse
        url = state["url"]
        p = urlparse(url if url.startswith("http") else f"https://{url}")
        domain = p.netloc or p.path.split("/")[0]

        print(f"  [ahrefs] Pulling Ahrefs data for {domain}...")
        try:
            client = AhrefsClient()
            data = await client.get_all_data(domain)
            state["ahrefs_data"] = data

            kws = len(data.get('organic_keywords', []))
            comps = len(data.get('competitors', []))
            refs = len(data.get('referring_domains', []))
            broken = len(data.get('broken_backlinks', []))
            print(f"  [ahrefs] Done — {kws} keywords, {comps} competitors, "
                  f"{refs} referring domains, {broken} broken backlinks")
        except Exception as e:
            print(f"  [ahrefs] Failed: {e}")
            state["ahrefs_data"] = {"error": str(e)}
            state.setdefault("errors", []).append(f"Ahrefs: {e}")
        return state


class PageSpeedAgent:
    async def run(self, state: dict) -> dict:
        url = state["url"]
        print(f"  [pagespeed] Running PageSpeed Insights for {url}...")
        try:
            client = PageSpeedClient()
            data = await client.get_all_data(url)
            state["pagespeed_data"] = data

            mobile = data.get("mobile", {})
            desktop = data.get("desktop", {})
            m_perf = mobile.get("performance_score", "?")
            d_perf = desktop.get("performance_score", "?")
            print(f"  [pagespeed] Done — Mobile: {m_perf}/100, Desktop: {d_perf}/100")
        except Exception as e:
            print(f"  [pagespeed] Failed: {e}")
            state["pagespeed_data"] = {"error": str(e)}
            state.setdefault("errors", []).append(f"PageSpeed: {e}")
        return state
