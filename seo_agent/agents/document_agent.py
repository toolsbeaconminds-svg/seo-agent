import os
from datetime import datetime


class DocumentAgent:
    """Turns the analyst's JSON output into a comprehensive markdown report."""

    async def run(self, state: dict, output_dir: str = "output") -> str:
        print("  [document] Generating report...")

        analysis = state.get("analysis", {})
        biz = state.get("business_name", "Unknown")
        url = state.get("url", "")
        date = datetime.utcnow().strftime("%Y-%m-%d")

        lines = [
            f"# SEO Analysis — {biz}",
            f"**URL**: {url} | **Date**: {date} | **Analyst**: SEO Agent v1",
            "",
        ]

        # Executive summary
        lines += ["## Executive Summary", "", analysis.get("executive_summary", "No summary available."), ""]

        # Anomalies
        anomalies = state.get("anomalies", [])
        if anomalies:
            lines += ["## ⚠ Anomalies Detected", ""]
            for a in anomalies:
                lines.append(f"- **{a}**")
            lines.append("")

        # Traffic overview
        traffic = analysis.get("traffic_overview", {})
        if traffic:
            lines += ["## Traffic Overview", ""]
            if traffic.get("organic_sessions_monthly_avg"):
                lines.append(f"- Organic sessions (monthly avg): **{traffic['organic_sessions_monthly_avg']:,}**")
            if traffic.get("total_clicks_90d"):
                lines.append(f"- Total GSC clicks (90d): **{traffic['total_clicks_90d']:,}**")
            if traffic.get("total_impressions_90d"):
                lines.append(f"- Total impressions (90d): **{traffic['total_impressions_90d']:,}**")
            if traffic.get("top_country"):
                lines.append(f"- Top country: **{traffic['top_country']}**")
            dev = traffic.get("device_split", {})
            if dev:
                lines.append(f"- Device split: Mobile {dev.get('mobile','?')} / Desktop {dev.get('desktop','?')}")
            lines.append(f"- Conversion events configured: **{'Yes' if traffic.get('conversion_events_configured') else 'No'}**")
            lines.append("")

        # Technical health
        tech = analysis.get("technical_health", {})
        if tech:
            lines += ["## Technical Health", ""]
            lines.append(f"- robots.txt: **{tech.get('robots_txt_status', 'unknown')}**")
            for issue in tech.get("robots_txt_issues", []):
                lines.append(f"  - {issue}")
            lines.append(f"- Sitemap: **{tech.get('sitemap_status', 'unknown')}**"
                         + (f" ({tech.get('sitemap_url_count', 0)} URLs)" if tech.get('sitemap_url_count') else ""))
            lines.append(f"- HTTPS: **{'Yes' if tech.get('https') else 'No'}**")
            lines.append(f"- Mobile-friendly: **{'Yes' if tech.get('mobile_friendly') else 'No'}**")
            lines.append(f"- Pages with canonical: **{tech.get('pages_with_canonical', 0)}** / "
                         f"without: **{tech.get('pages_without_canonical', 0)}**")
            lines.append(f"- Pages with schema: **{tech.get('pages_with_schema', 0)}** "
                         f"(types: {', '.join(tech.get('schema_types_found', []))})")
            if tech.get("pages_missing_viewport"):
                lines.append(f"- ⚠ Pages missing viewport meta: **{tech['pages_missing_viewport']}**")
            for issue in tech.get("issues", []):
                lines.append(f"- ⚠ {issue}")
            lines.append("")

        # Performance / Core Web Vitals
        perf = analysis.get("performance", {})
        if perf:
            lines += ["## Performance & Core Web Vitals", ""]
            lines.append(f"| Metric | Mobile | Desktop |")
            lines.append(f"|---|---|---|")
            lines.append(f"| Performance Score | **{perf.get('mobile_score', '?')}**/100 | **{perf.get('desktop_score', '?')}**/100 |")
            if perf.get("lcp_ms"):
                lines.append(f"| LCP | {perf['lcp_ms']}ms ({perf.get('lcp_rating','?')}) | — |")
            if perf.get("cls") is not None:
                lines.append(f"| CLS | {perf['cls']} ({perf.get('cls_rating','?')}) | — |")
            if perf.get("inp_ms"):
                lines.append(f"| INP | {perf['inp_ms']}ms ({perf.get('inp_rating','?')}) | — |")
            if perf.get("fcp_ms"):
                lines.append(f"| FCP | {perf['fcp_ms']}ms | — |")
            if perf.get("ttfb_ms"):
                lines.append(f"| TTFB | {perf['ttfb_ms']}ms | — |")
            lines.append("")
            for issue in perf.get("performance_issues", []):
                lines.append(f"- ⚠ {issue}")
            lines.append("")

        # On-page analysis
        onpage = analysis.get("on_page_analysis", {})
        if onpage:
            lines += ["## On-Page Analysis", ""]
            lines.append(f"- Pages audited: **{onpage.get('pages_audited', 0)}**")
            if onpage.get("pages_missing_title"):
                lines.append(f"- ⚠ Missing title tags: {', '.join(onpage['pages_missing_title'])}")
            if onpage.get("pages_missing_meta_desc"):
                lines.append(f"- ⚠ Missing meta descriptions: {', '.join(onpage['pages_missing_meta_desc'])}")
            if onpage.get("pages_missing_h1"):
                lines.append(f"- ⚠ Missing H1: {', '.join(onpage['pages_missing_h1'])}")
            if onpage.get("thin_content_pages"):
                lines.append(f"- ⚠ Thin content pages:")
                for tp in onpage["thin_content_pages"]:
                    lines.append(f"  - {tp.get('url', '')} ({tp.get('word_count', 0)} words)")
            lines.append(f"- Images: **{onpage.get('images_total', 0)}** total, "
                         f"**{onpage.get('images_missing_alt', 0)}** missing alt text")
            lines.append(f"- Internal links (avg per page): **{onpage.get('internal_links_avg', 0)}**")
            if onpage.get("og_tags_missing"):
                lines.append(f"- ⚠ Missing OpenGraph tags: {', '.join(onpage['og_tags_missing'][:5])}")
            lines.append("")

        # Backlink profile
        bl = analysis.get("backlink_profile", {})
        if bl:
            lines += ["## Backlink Profile", ""]
            lines.append(f"- Domain Rating: **{bl.get('domain_rating', '?')}**")
            lines.append(f"- Total backlinks: **{bl.get('total_backlinks', '?')}**")
            lines.append(f"- Referring domains: **{bl.get('referring_domains', '?')}**")
            lines.append("")
            if bl.get("top_referring_domains"):
                lines += ["**Top Referring Domains:**", "", "| Domain | DR | Backlinks |", "|---|---|---|"]
                for rd in bl["top_referring_domains"][:10]:
                    lines.append(f"| {rd.get('domain','')} | {rd.get('domain_rating','')} | {rd.get('backlinks','')} |")
                lines.append("")
            if bl.get("anchor_text_distribution"):
                lines += ["**Anchor Text Distribution:**", "", "| Anchor | Backlinks | Ref Domains |", "|---|---|---|"]
                for a in bl["anchor_text_distribution"][:10]:
                    lines.append(f"| {a.get('anchor','')} | {a.get('backlinks','')} | {a.get('referring_domains','')} |")
                lines.append("")
            if bl.get("broken_backlinks"):
                lines += ["**Broken Backlinks (link juice leaking):**", ""]
                for bb in bl["broken_backlinks"][:5]:
                    lines.append(f"- {bb.get('from_url','')} → {bb.get('to_url','')} (anchor: {bb.get('anchor','')})")
                lines.append("")
            if bl.get("backlink_quality_assessment"):
                lines.append(f"**Assessment:** {bl['backlink_quality_assessment']}")
                lines.append("")
            if bl.get("link_building_opportunities"):
                lines += ["**Link Building Opportunities:**", ""]
                for opp in bl["link_building_opportunities"]:
                    lines.append(f"- {opp}")
                lines.append("")

        # Findings by priority
        findings = analysis.get("findings", [])
        for priority in ["critical", "high", "medium", "low"]:
            group = [f for f in findings if f.get("priority") == priority]
            if group:
                label = {"critical": "🔴 Critical — Fix Immediately", "high": "🟠 High Priority — Fix This Month",
                         "medium": "🟡 Medium Priority", "low": "🟢 Low Priority"}
                lines += [f"## {label.get(priority, priority.title())}", ""]
                for i, f in enumerate(group, 1):
                    lines.append(f"### {i}. {f.get('title', 'Untitled')} [{f.get('category','')}]")
                    lines.append("")
                    lines.append(f.get("description", ""))
                    urls = f.get("affected_urls", [])
                    if urls:
                        lines.append("")
                        lines.append("**Affected URLs:**")
                        for u in urls[:10]:
                            lines.append(f"- {u}")
                    fix = f.get("fix_instructions", "")
                    if fix:
                        lines.append("")
                        lines.append(f"**How to fix:** {fix}")
                    lines.append(f"**Owner:** {f.get('owner','')} | **Impact:** {f.get('estimated_impact','')}")
                    lines.append("")

        # Keyword analysis
        kw = analysis.get("keyword_analysis", {})
        if kw.get("top_performing"):
            lines += ["## Top Performing Keywords", "", "| Keyword | Clicks | Impressions | Position | URL |", "|---|---|---|---|---|"]
            for k in kw["top_performing"][:20]:
                lines.append(f"| {k.get('keyword','')} | {k.get('clicks','')} | {k.get('impressions','')} | {k.get('position','')} | {k.get('url','')} |")
            lines.append("")

        if kw.get("opportunities"):
            lines += ["## Keyword Opportunities (Striking Distance)", "", "| Keyword | Current Position | Impressions | Potential |", "|---|---|---|---|"]
            for k in kw["opportunities"][:15]:
                lines.append(f"| {k.get('keyword','')} | {k.get('current_position','')} | {k.get('impressions','')} | {k.get('potential','')} |")
            lines.append("")

        if kw.get("keyword_gaps"):
            lines += ["## Keyword Gap Analysis", "", "| Keyword | Competitor | Their Position | Volume | Action |", "|---|---|---|---|---|"]
            for g in kw["keyword_gaps"][:15]:
                lines.append(f"| {g.get('keyword','')} | {g.get('competitor','')} | {g.get('competitor_position','')} | {g.get('volume','')} | {g.get('suggested_action','')} |")
            lines.append("")

        # Competitor summary
        comps = analysis.get("competitor_summary", [])
        if comps:
            lines += ["## Competitor Overview", "", "| Domain | DR | Organic Traffic | Common KWs | Key Advantage |", "|---|---|---|---|---|"]
            for c in comps:
                lines.append(f"| {c.get('domain','')} | {c.get('domain_rating','')} | {c.get('organic_traffic','')} | {c.get('common_keywords','')} | {c.get('key_advantage','')} |")
            lines.append("")

        # Quick wins
        qw = analysis.get("quick_wins", [])
        if qw:
            lines += ["## Quick Wins", ""]
            for i, q in enumerate(qw, 1):
                lines.append(f"{i}. **{q.get('action','')}** (~{q.get('estimated_time','?')}) — {q.get('expected_outcome','')}")
            lines.append("")

        # Content recommendations
        content = analysis.get("content_recommendations", [])
        if content:
            lines += ["## Content Recommendations", ""]
            for i, c in enumerate(content, 1):
                lines.append(f"{i}. **[{c.get('type','').upper()}]** Target: _{c.get('target_keyword','')}_")
                lines.append(f"   {c.get('description','')}")
            lines.append("")

        # Data source notes
        errors = state.get("errors", [])
        if errors:
            lines += ["## Data Source Notes", ""]
            for e in errors:
                lines.append(f"- ⚠ {e}")
            lines.append("")

        lines.append("---")
        lines.append("*Generated by SEO Agent v1*")

        report = "\n".join(lines)

        # Save to file
        os.makedirs(output_dir, exist_ok=True)
        slug = (biz or "unknown").lower().replace(" ", "_")[:30]
        filename = f"{slug}_seo_analysis_{date}.md"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)

        print(f"  [document] Report saved to {filepath}")
        return filepath
