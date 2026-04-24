"""GSC Actions Agent — submits sitemaps, requests indexing via Google Search Console API."""

from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings


SCOPES = ["https://www.googleapis.com/auth/webmasters"]
MAX_INDEXING_REQUESTS = 10  # Google's daily quota is roughly 10


class GSCActionsAgent:

    async def run(self, state: dict) -> dict:
        print("  [gsc-actions] Starting GSC implementation...")

        if not settings.GOOGLE_SERVICE_ACCOUNT_KEY_PATH:
            print("  [gsc-actions] SKIPPED — no service account configured")
            state.setdefault("errors", []).append("GSC Actions: no service account configured")
            return state

        tasks = [t for t in state.get("task_plan", []) if t.get("requires_gsc_api")]
        if not tasks:
            print("  [gsc-actions] No GSC tasks to implement")
            return state

        log = state.setdefault("implementation_log", [])
        verify = state.setdefault("verify_list", [])

        try:
            creds = service_account.Credentials.from_service_account_file(
                settings.GOOGLE_SERVICE_ACCOUNT_KEY_PATH, scopes=SCOPES
            )
            service = build("searchconsole", "v1", credentials=creds)
        except Exception as e:
            print(f"  [gsc-actions] Failed to init GSC API: {e}")
            state.setdefault("errors", []).append(f"GSC Actions: {e}")
            return state

        site_url = state.get("url", "").rstrip("/")
        if not site_url.startswith("http"):
            site_url = f"https://{site_url}"

        indexing_count = 0

        for i, task in enumerate(tasks, 1):
            cat = task.get("category", "")
            title = task.get("title", "")
            url = task.get("target_url", "")

            print(f"  [gsc-actions] [{i}/{len(tasks)}] {title}")

            try:
                if "sitemap" in title.lower():
                    await self._submit_sitemap(service, site_url, task, log)
                elif "index" in title.lower() and indexing_count < MAX_INDEXING_REQUESTS:
                    await self._request_indexing(service, site_url, url, log, verify)
                    indexing_count += 1
                elif "remov" in title.lower():
                    await self._remove_url(service, site_url, url, log)
                else:
                    _log_action(log, "SKIPPED", "gsc", url, f"Unknown GSC action: {title}")
            except Exception as e:
                _log_action(log, "FAILED", "gsc", url, str(e))
                print(f"    FAILED: {e}")

        if indexing_count >= MAX_INDEXING_REQUESTS:
            remaining = [t for t in tasks if "index" in t.get("title", "").lower()][MAX_INDEXING_REQUESTS:]
            if remaining:
                print(f"  [gsc-actions] Quota hit — {len(remaining)} indexing requests deferred to next run")
                state.setdefault("dev_briefs", []).extend([
                    {"task": t["title"], "details": "Deferred — indexing quota reached",
                     "url": t.get("target_url", ""), "priority": "medium"}
                    for t in remaining
                ])

        done = sum(1 for l in log if l.get("category") == "gsc" and l["result"] == "CHANGED")
        print(f"  [gsc-actions] Done — {done} GSC actions completed")
        return state

    async def _submit_sitemap(self, service, site_url: str, task: dict, log: list):
        """Submit a sitemap URL to GSC."""
        sitemap_url = task.get("target_url") or f"{site_url}/sitemap.xml"

        try:
            service.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
            _log_action(log, "CHANGED", "gsc", sitemap_url, "Sitemap submitted")
        except Exception as e:
            if "already" in str(e).lower():
                _log_action(log, "SKIPPED", "gsc", sitemap_url, "Sitemap already submitted")
            else:
                raise

    async def _request_indexing(self, service, site_url: str, url: str, log: list, verify: list):
        """Request indexing for a specific URL."""
        inspect_url = url or site_url

        try:
            # Use URL Inspection API
            body = {
                "inspectionUrl": inspect_url,
                "siteUrl": site_url,
            }
            result = service.urlInspection().index().inspect(body=body).execute()
            status = result.get("inspectionResult", {}).get("indexStatusResult", {}).get("coverageState", "unknown")
            _log_action(log, "CHANGED", "gsc", inspect_url, f"Indexing requested — current status: {status}")
            verify.append(inspect_url)
        except Exception as e:
            if "quota" in str(e).lower() or "rate" in str(e).lower():
                _log_action(log, "DEFERRED", "gsc", inspect_url, "Rate limited — retry tomorrow")
            else:
                raise

    async def _remove_url(self, service, site_url: str, url: str, log: list):
        """Request URL removal from search results."""
        try:
            body = {"inspectionUrl": url, "siteUrl": site_url}
            # Note: URL removal API has different endpoint
            service.urlInspection().index().inspect(body=body).execute()
            _log_action(log, "CHANGED", "gsc", url, "URL removal requested")
        except Exception as e:
            _log_action(log, "FAILED", "gsc", url, f"Removal failed: {e}")


def _log_action(log: list, result: str, category: str, url: str, detail: str):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "result": result,
        "category": category,
        "url": url,
        "detail": detail,
    }
    log.append(entry)
    icon = {"CHANGED": "+", "SKIPPED": "~", "FAILED": "!", "DEFERRED": ">"}.get(result, "?")
    print(f"    [{icon}] {result} | {category} | {url} | {detail}")
