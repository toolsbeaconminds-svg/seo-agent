"""
SEO Agent — run a full SEO analysis on any website.

Usage:
    python main.py https://example.com
"""

import asyncio
import json
import os
import sys
import time

from agents.scout import ScoutAgent
from agents.data_agents import GSCAgent, GA4Agent, AhrefsAgent, PageSpeedAgent
from agents.analyst import AnalystAgent
from agents.document_agent import DocumentAgent
from config import override_ga4_property

STATE_FILE = "output/.last_analysis_state.json"


async def run_analysis(url: str, ga4_property_id: str | None = None, log_callback=None) -> str:
    """Run the full analysis pipeline and return the report filepath."""
    # Override GA4 property ID if provided
    override_ga4_property(ga4_property_id)

    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    state = {"url": url, "errors": [], "anomalies": []}

    print(f"\n{'='*60}")
    print(f"  SEO AGENT — Analysing {url}")
    print(f"{'='*60}\n")
    start = time.time()

    # Step 1: Scout — scrape site + extract business info + find competitors
    print("[1/5] Scouting website...")
    scout = ScoutAgent()
    state = await scout.run(state)

    # Check for critical anomalies
    if "SPAM_INJECTION" in state.get("anomalies", []):
        print("\n⚠⚠⚠  SPAM/HACK DETECTED — proceeding with caution  ⚠⚠⚠\n")

    # Step 2: Data collection — GSC, GA4, Ahrefs, PageSpeed in parallel
    print("\n[2/5] Collecting data (GSC + GA4 + Ahrefs + PageSpeed in parallel)...")
    gsc, ga4, ahrefs, pagespeed = GSCAgent(), GA4Agent(), AhrefsAgent(), PageSpeedAgent()

    # Give each agent a clean copy with fresh error/anomaly lists
    errors_before = list(state.get("errors", []))
    anomalies_before = list(state.get("anomalies", []))

    gsc_input = {**state, "errors": [], "anomalies": []}
    ga4_input = {**state, "errors": [], "anomalies": []}
    ahrefs_input = {**state, "errors": [], "anomalies": []}
    ps_input = {**state, "errors": [], "anomalies": []}

    gsc_state, ga4_state, ahrefs_state, ps_state = await asyncio.gather(
        gsc.run(gsc_input),
        ga4.run(ga4_input),
        ahrefs.run(ahrefs_input),
        pagespeed.run(ps_input),
        return_exceptions=True,
    )

    # Merge results — only new errors/anomalies from each agent
    state["errors"] = errors_before
    state["anomalies"] = anomalies_before
    for s, name in [(gsc_state, "gsc"), (ga4_state, "ga4"), (ahrefs_state, "ahrefs"), (ps_state, "pagespeed")]:
        if isinstance(s, Exception):
            print(f"  [{name}] FAILED: {s}")
            state[f"{name}_data"] = {"error": str(s)}
            state["errors"].append(f"{name.upper()}: {s}")
        else:
            state[f"{name}_data"] = s.get(f"{name}_data", {})
            state["anomalies"].extend(s.get("anomalies", []))
            state["errors"].extend(s.get("errors", []))

    # Deduplicate
    state["anomalies"] = list(set(state["anomalies"]))
    state["errors"] = list(dict.fromkeys(state["errors"]))

    # Step 3: Analysis — synthesise everything with Claude
    print("\n[3/5] Analysing data with Claude...")
    analyst = AnalystAgent()
    state = await analyst.run(state)

    # Step 4: Generate report
    print("\n[4/5] Generating report...")
    doc = DocumentAgent()
    filepath = await doc.run(state)

    # Save state for implementation pipeline
    os.makedirs("output", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"  DONE in {elapsed:.0f}s")
    print(f"  Report: {filepath}")
    print(f"  Findings: {len(state.get('analysis', {}).get('findings', []))}")
    print(f"  Errors: {len(state.get('errors', []))}")
    print(f"  State saved to {STATE_FILE}")
    print(f"  Run implementation: python implement.py")
    print(f"{'='*60}\n")

    return filepath


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <url> [ga4_property_id]")
        print("Example: python main.py https://example.com 504669409")
        sys.exit(1)

    url = sys.argv[1]
    if not url.startswith("http"):
        url = f"https://{url}"

    ga4_id = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(run_analysis(url, ga4_property_id=ga4_id))


if __name__ == "__main__":
    main()
