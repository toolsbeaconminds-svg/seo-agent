import asyncio
from datetime import datetime, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import settings

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def _date_ago(n: int) -> str:
    return (datetime.utcnow() - timedelta(days=n)).strftime("%Y-%m-%d")


def _parse_rows(response: dict, dim: str) -> list[dict]:
    return [
        {dim: r["keys"][0], "clicks": r["clicks"], "impressions": r["impressions"],
         "ctr": round(r["ctr"], 4), "position": round(r["position"], 1)}
        for r in response.get("rows", [])
    ]


class GSCClient:
    def __init__(self):
        self._service = None

    def _svc(self):
        if not self._service:
            creds = service_account.Credentials.from_service_account_file(
                settings.GOOGLE_SERVICE_ACCOUNT_KEY_PATH, scopes=SCOPES
            )
            self._service = build("searchconsole", "v1", credentials=creds)
        return self._service

    def _query(self, site_url, dims, days=90, limit=500):
        return self._svc().searchanalytics().query(
            siteUrl=site_url,
            body={"startDate": _date_ago(days), "endDate": _date_ago(1),
                  "dimensions": dims, "rowLimit": limit, "dataState": "final"}
        ).execute()

    async def get_all_data(self, site_url: str) -> dict:
        def _fetch():
            queries = _parse_rows(self._query(site_url, ["query"], limit=500), "query")
            pages = _parse_rows(self._query(site_url, ["page"], limit=200), "page")
            countries = _parse_rows(self._query(site_url, ["country"]), "country")
            devices = _parse_rows(self._query(site_url, ["device"]), "device")

            sitemaps_resp = self._svc().sitemaps().list(siteUrl=site_url).execute()
            sitemaps = [
                {"path": s.get("path"), "lastSubmitted": s.get("lastSubmitted"), "errors": s.get("errors", 0)}
                for s in sitemaps_resp.get("sitemap", [])
            ]

            return {"queries": queries, "pages": pages, "countries": countries,
                    "devices": devices, "sitemaps": sitemaps}

        return await asyncio.to_thread(_fetch)
