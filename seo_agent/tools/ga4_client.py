import asyncio

from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest

from config import settings

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _parse(response, dim_names, metric_names):
    results = []
    for row in response.rows:
        entry = {}
        for i, d in enumerate(dim_names):
            entry[d] = row.dimension_values[i].value
        for i, m in enumerate(metric_names):
            v = row.metric_values[i].value
            try:
                entry[m] = int(v)
            except ValueError:
                try:
                    entry[m] = float(v)
                except ValueError:
                    entry[m] = v
        results.append(entry)
    return results


class GA4Client:
    def __init__(self):
        self._client = None

    def _c(self):
        if not self._client:
            creds = service_account.Credentials.from_service_account_file(
                settings.GOOGLE_SERVICE_ACCOUNT_KEY_PATH, scopes=SCOPES
            )
            self._client = BetaAnalyticsDataClient(credentials=creds)
        return self._client

    def _prop(self):
        return f"properties/{settings.GA4_PROPERTY_ID}"

    def _run(self, dims, metrics, limit=50, days=180):
        return self._c().run_report(RunReportRequest(
            property=self._prop(),
            date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
            dimensions=[Dimension(name=d) for d in dims],
            metrics=[Metric(name=m) for m in metrics],
            limit=limit,
        ))

    async def get_all_data(self) -> dict:
        def _fetch():
            channels = _parse(
                self._run(["sessionDefaultChannelGroup"], ["sessions", "engagedSessions", "engagementRate", "averageSessionDuration"]),
                ["channel"], ["sessions", "engaged_sessions", "engagement_rate", "avg_duration"]
            )
            landing = _parse(
                self._run(["landingPage"], ["sessions", "engagedSessions"], limit=50),
                ["landing_page"], ["sessions", "engaged_sessions"]
            )
            events = _parse(
                self._run(["eventName"], ["eventCount"], limit=50),
                ["event_name"], ["event_count"]
            )
            countries = _parse(
                self._run(["country"], ["sessions"], limit=20),
                ["country"], ["sessions"]
            )
            cities = _parse(
                self._run(["city"], ["sessions"], limit=20),
                ["city"], ["sessions"]
            )
            return {"channels": channels, "landing_pages": landing, "key_events": events,
                    "countries": countries, "cities": cities}

        return await asyncio.to_thread(_fetch)
