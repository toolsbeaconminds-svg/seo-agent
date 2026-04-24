"""
SEO Agent — Implementation Pipeline

Takes the analysis output and implements fixes.
Asks the user whether they have WordPress credentials:
  - YES → collects creds → runs auto-implementation via WP REST API
  - NO  → runs the Guide Agent → generates all files + step-by-step manual

Usage:
    python implement.py [path_to_state.json]
"""

import asyncio
import json
import os
import sys
import time

from agents.planner import PlannerAgent
from agents.content_agent import ContentAgent
from agents.wordpress_agent import WordPressAgent
from agents.gsc_actions_agent import GSCActionsAgent
from agents.reporter import ReporterAgent
from agents.guide_agent import GuideAgent
from config import settings


STATE_FILE = "output/.last_analysis_state.json"


def _ask(prompt: str, default: str = "") -> str:
    """Prompt user for input."""
    suffix = f" [{default}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val or default


async def run_implementation(state_path: str | None = None) -> str:
    """Run the full implementation pipeline."""

    # ── Load saved analysis state ────────────────────────────────
    path = state_path or STATE_FILE
    if not os.path.exists(path):
        print(f"\n  ERROR: No analysis state found at '{path}'")
        print("  Run an analysis first:  python main.py <url> [ga4_property_id]")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        state = json.load(f)

    biz = state.get("business_name", "Unknown")
    url = state.get("url", "")
    n_findings = len(state.get("analysis", {}).get("findings", []))

    print(f"\n{'='*60}")
    print(f"  SEO AGENT — Implementation Pipeline")
    print(f"  Site: {url}")
    print(f"  Business: {biz}")
    print(f"  Findings to implement: {n_findings}")
    print(f"{'='*60}")

    if not state.get("analysis"):
        print("\n  ERROR: Analysis data is empty — run analysis first")
        sys.exit(1)

    # ── Ask user about WordPress access ──────────────────────────
    print()
    has_wp = _ask("Do you have WordPress credentials for this site? (y/n)", "n").lower()
    wp_mode = has_wp in ("y", "yes")

    if wp_mode:
        print()
        print("  Enter WordPress credentials:")
        wp_url = _ask("WordPress URL", url.rstrip("/"))
        wp_user = _ask("WordPress username")
        wp_pass = _ask("Application password (from WP Admin → Users → App Passwords)")

        if not wp_user or not wp_pass:
            print("\n  Missing credentials — switching to guide mode.")
            wp_mode = False
        else:
            # Override settings for this run
            settings.WP_URL = wp_url
            settings.WP_USERNAME = wp_user
            settings.WP_APP_PASSWORD = wp_pass
            print(f"\n  WordPress connected: {wp_url} as {wp_user}")

    mode_label = "AUTO-IMPLEMENT" if wp_mode else "GUIDE MODE"
    print(f"\n  Mode: {mode_label}")
    print(f"{'='*60}\n")

    start = time.time()

    # Init implementation state
    state.setdefault("task_plan", [])
    state.setdefault("generated_assets", [])
    state.setdefault("implementation_log", [])
    state.setdefault("dev_briefs", [])
    state.setdefault("verify_list", [])

    # ── Step 1: Plan ─────────────────────────────────────────────
    print("[1/5] Planning implementation tasks...")
    planner = PlannerAgent()
    state = await planner.run(state)

    tasks = state.get("task_plan", [])
    if not tasks:
        print("\n  No tasks generated. Exiting.")
        return ""

    # Show task summary
    print(f"\n  Task breakdown:")
    for priority in ["critical", "high", "medium", "low"]:
        group = [t for t in tasks if t.get("priority") == priority]
        if group:
            auto = sum(1 for t in group if t.get("can_automate"))
            print(f"    {priority.upper()}: {len(group)} tasks ({auto} automatable)")

    # ── Step 2: Generate SEO assets ──────────────────────────────
    print(f"\n[2/5] Generating SEO assets...")
    content = ContentAgent()
    state = await content.run(state)

    if wp_mode:
        # ── AUTO MODE: WordPress + GSC ───────────────────────────

        # Step 3: WordPress implementation
        print(f"\n[3/5] Implementing via WordPress API...")
        wp = WordPressAgent()
        state = await wp.run(state)

        # Step 4: GSC actions
        print(f"\n[4/5] Executing GSC actions...")
        gsc = GSCActionsAgent()
        state = await gsc.run(state)

        # Step 5: Generate report
        print(f"\n[5/5] Generating implementation report...")
        reporter = ReporterAgent()
        filepath = await reporter.run(state)

        # Summary
        impl_log = state.get("implementation_log", [])
        changed = sum(1 for l in impl_log if l["result"] == "CHANGED")
        failed = sum(1 for l in impl_log if l["result"] == "FAILED")
        assets = len(state.get("generated_assets", []))
        dev = len(state.get("dev_briefs", []))

        elapsed = time.time() - start
        print(f"\n{'='*60}")
        print(f"  IMPLEMENTATION DONE in {elapsed:.0f}s")
        print(f"  Report: {filepath}")
        print(f"  Changes made: {changed}")
        print(f"  Assets generated: {assets}")
        print(f"  Failed: {failed}")
        print(f"  Needs developer: {dev}")
        print(f"  URLs to verify: {len(set(state.get('verify_list', [])))}")
        print(f"{'='*60}\n")

    else:
        # ── GUIDE MODE: Generate files + instructions ────────────

        # Step 3: Generate all implementation files
        print(f"\n[3/5] Generating implementation files...")
        guide = GuideAgent()
        guide_path = await guide.run(state)

        # Step 4: GSC actions (if available)
        print(f"\n[4/5] Executing GSC actions...")
        gsc = GSCActionsAgent()
        state = await gsc.run(state)

        # Step 5: Summary
        elapsed = time.time() - start
        kit_dir = "output/implementation_kit"
        file_count = sum(len(f) for _, _, f in os.walk(kit_dir)) if os.path.exists(kit_dir) else 0

        filepath = guide_path

        print(f"\n{'='*60}")
        print(f"  GUIDE MODE DONE in {elapsed:.0f}s")
        print(f"  Implementation kit: {kit_dir}/")
        print(f"  Master guide: {guide_path}")
        print(f"  Assets generated: {len(state.get('generated_assets', []))}")
        print(f"")
        print(f"  What's in the kit:")
        _print_kit_contents(kit_dir)
        print(f"")
        print(f"  Next: Open {guide_path} and follow the steps!")
        print(f"{'='*60}\n")

    return filepath


def _print_kit_contents(kit_dir: str):
    """Print a summary of files in the implementation kit."""
    if not os.path.exists(kit_dir):
        print("    (no files generated)")
        return

    for subdir in ["schema", "meta", "redirects", "content", "briefs"]:
        full = os.path.join(kit_dir, subdir)
        if os.path.exists(full):
            files = os.listdir(full)
            if files:
                print(f"    {subdir}/ ({len(files)} files)")
                for f in files[:5]:
                    print(f"      - {f}")
                if len(files) > 5:
                    print(f"      ... and {len(files) - 5} more")

    guide = os.path.join(kit_dir, "guide.md")
    if os.path.exists(guide):
        print(f"    guide.md (step-by-step instructions)")


def main():
    state_path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_implementation(state_path))


if __name__ == "__main__":
    main()
