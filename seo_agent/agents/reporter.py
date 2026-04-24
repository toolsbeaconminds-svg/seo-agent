"""Reporter Agent — generates the implementation report as markdown."""

import os
from datetime import datetime


class ReporterAgent:

    async def run(self, state: dict, output_dir: str = "output") -> str:
        print("  [reporter] Generating implementation report...")

        biz = state.get("business_name", "Unknown")
        url = state.get("url", "")
        date = datetime.utcnow().strftime("%Y-%m-%d")

        impl_log = state.get("implementation_log", [])
        dev_briefs = state.get("dev_briefs", [])
        verify_list = state.get("verify_list", [])
        assets = state.get("generated_assets", [])
        tasks = state.get("task_plan", [])

        lines = [
            f"# Implementation Report — {biz}",
            f"**Date**: {date} | **Project**: {url}",
            "",
        ]

        # ── Summary stats ────────────────────────────────────────────
        changed = [l for l in impl_log if l["result"] == "CHANGED"]
        skipped = [l for l in impl_log if l["result"] == "SKIPPED"]
        failed = [l for l in impl_log if l["result"] == "FAILED"]
        deferred = [l for l in impl_log if l["result"] == "DEFERRED"]

        lines += [
            "## Summary",
            "",
            f"- **Changes implemented**: {len(changed)}",
            f"- **Skipped (already correct)**: {len(skipped)}",
            f"- **Failed**: {len(failed)}",
            f"- **Deferred to developer**: {len(deferred) + len(dev_briefs)}",
            f"- **Assets generated**: {len(assets)}",
            f"- **URLs to verify in 48h**: {len(verify_list)}",
            "",
        ]

        # ── What was implemented ─────────────────────────────────────
        if changed:
            lines += [
                f"## What Was Implemented ({len(changed)} changes)",
                "",
                "| # | Type | URL | Result | Detail |",
                "|---|------|-----|--------|--------|",
            ]
            for i, l in enumerate(changed, 1):
                lines.append(
                    f"| {i} | {l['category']} | {l['url']} | {l['result']} | {l['detail']} |"
                )
            lines.append("")

        # ── What failed ──────────────────────────────────────────────
        if failed:
            lines += [
                f"## Failed ({len(failed)} items)",
                "",
                "| Type | URL | Error |",
                "|------|-----|-------|",
            ]
            for l in failed:
                lines.append(f"| {l['category']} | {l['url']} | {l['detail']} |")
            lines.append("")

        # ── Developer briefs ─────────────────────────────────────────
        all_dev = dev_briefs + [
            {"task": l["detail"], "url": l["url"], "details": "", "priority": "medium"}
            for l in deferred
        ]
        if all_dev:
            lines += [
                f"## What Needs a Developer ({len(all_dev)} items)",
                "",
            ]
            for i, d in enumerate(all_dev, 1):
                pri = d.get("priority", "medium").upper()
                lines.append(f"### {i}. [{pri}] {d.get('task', 'Unknown task')}")
                if d.get("url"):
                    lines.append(f"**URL**: {d['url']}")
                if d.get("details"):
                    lines.append(f"\n{d['details']}")
                lines.append("")

        # ── Generated assets ─────────────────────────────────────────
        if assets:
            lines += [
                f"## Generated SEO Assets ({len(assets)} items)",
                "",
            ]

            # Group by type
            by_type: dict[str, list] = {}
            for a in assets:
                t = a.get("asset_type", "other")
                by_type.setdefault(t, []).append(a)

            for asset_type, items in by_type.items():
                label = asset_type.replace("_", " ").title()
                lines.append(f"### {label} ({len(items)})")
                lines.append("")

                if asset_type in ("title_tag", "meta_description", "alt_text"):
                    lines.append("| URL | Content |")
                    lines.append("|-----|---------|")
                    for a in items:
                        content = a.get("content", "").replace("|", "\\|")
                        lines.append(f"| {a.get('url', '')} | {content} |")
                elif asset_type == "schema_json":
                    for a in items:
                        lines.append(f"**{a.get('url', '')}**")
                        lines.append(f"```json\n{a.get('content', '')}\n```")
                elif asset_type == "content_brief":
                    for a in items:
                        lines.append(f"**Target: {a.get('url', '')}**")
                        lines.append(f"\n{a.get('content', '')}")
                else:
                    for a in items:
                        lines.append(f"- **{a.get('url', '')}**: {a.get('content', '')[:200]}")
                lines.append("")

        # ── Verify in 48 hours ───────────────────────────────────────
        if verify_list:
            unique_urls = list(dict.fromkeys(verify_list))
            lines += [
                f"## Verify in 48 Hours ({len(unique_urls)} URLs)",
                "",
            ]
            for u in unique_urls:
                lines.append(f"- [ ] {u}")
            lines.append("")

        # ── Next steps ───────────────────────────────────────────────
        content_tasks = [t for t in tasks if t.get("category") == "content"]
        lines += [
            "## Next Steps",
            "",
        ]
        if content_tasks:
            lines.append(f"1. **Review and publish {len(content_tasks)} draft pages** created by the content agent")
        if dev_briefs:
            lines.append(f"2. **Developer to implement {len(dev_briefs)} manual tasks** listed above")
        if verify_list:
            lines.append(f"3. **Verify {len(set(verify_list))} URLs in 48 hours** to confirm changes are indexed")
        lines.append(f"4. **Schedule next audit** in 30 days to measure impact")
        lines.append("")

        # ── Full task plan reference ─────────────────────────────────
        if tasks:
            lines += [
                "## Full Task Plan Reference",
                "",
                "| # | Priority | Category | Task | Automated | Status |",
                "|---|----------|----------|------|-----------|--------|",
            ]
            for i, t in enumerate(tasks, 1):
                auto = "Yes" if t.get("can_automate") else "No"
                # Check if this task was implemented
                task_url = t.get("target_url", "")
                was_done = any(l["url"] == task_url and l["result"] == "CHANGED" for l in impl_log)
                was_failed = any(l["url"] == task_url and l["result"] == "FAILED" for l in impl_log)
                status = "Done" if was_done else ("Failed" if was_failed else "Pending")
                lines.append(
                    f"| {i} | {t.get('priority', '')} | {t.get('category', '')} | "
                    f"{t.get('title', '')} | {auto} | {status} |"
                )
            lines.append("")

        lines.append("---")
        lines.append("*Generated by SEO Agent v1 — Implementation Pipeline*")

        report = "\n".join(lines)

        # Save
        os.makedirs(output_dir, exist_ok=True)
        slug = (biz or "unknown").lower().replace(" ", "_")[:30]
        filename = f"{slug}_implementation_report_{date}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"  [reporter] Report saved to {filepath}")
        return filepath
