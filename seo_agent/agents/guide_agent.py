"""
Guide Agent — generates all implementation files and step-by-step instructions
for users who don't have WordPress API access.

Outputs to output/implementation_kit/:
  - schema/         → JSON-LD files per page
  - meta/           → HTML snippets with title + meta tags per page
  - redirects/      → .htaccess rules or plugin-ready CSV
  - content/        → Draft HTML pages for new content
  - briefs/         → Content briefs as markdown
  - guide.md        → Step-by-step implementation guide
"""

import json
import os
import re
import anthropic

from config import settings
from core.prompts import CONTENT_AGENT_SYSTEM_PROMPT


class GuideAgent:

    def __init__(self):
        self.llm = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def run(self, state: dict, output_dir: str = "output/implementation_kit") -> str:
        print("  [guide] Generating implementation kit...")

        analysis = state.get("analysis", {})
        tasks = state.get("task_plan", [])
        assets = state.get("generated_assets", [])

        if not analysis:
            print("  [guide] ERROR: no analysis data")
            return ""

        # Create folder structure
        dirs = ["schema", "meta", "redirects", "content", "briefs"]
        for d in dirs:
            os.makedirs(os.path.join(output_dir, d), exist_ok=True)

        files_created = []

        # ── 1. Schema JSON-LD files ──────────────────────────────────
        schema_assets = [a for a in assets if a.get("asset_type") in ("schema_json", "faq_schema")]
        if schema_assets:
            print(f"  [guide] Writing {len(schema_assets)} schema files...")
            for i, a in enumerate(schema_assets):
                slug = _url_to_slug(a.get("url", f"page_{i}"))
                filepath = os.path.join(output_dir, "schema", f"{slug}.json")
                content = a.get("content", "")
                # Try to pretty-print if valid JSON
                try:
                    parsed = json.loads(content)
                    content = json.dumps(parsed, indent=2)
                except (json.JSONDecodeError, TypeError):
                    pass
                _write(filepath, content)
                files_created.append(("schema", filepath, a.get("url", "")))
        else:
            # Generate schema from findings
            print("  [guide] Generating schema markup from findings...")
            schema_assets = await self._generate_schema_files(state, output_dir)
            files_created.extend(schema_assets)

        # ── 2. Meta tag HTML snippets ────────────────────────────────
        title_assets = [a for a in assets if a.get("asset_type") == "title_tag"]
        meta_assets = [a for a in assets if a.get("asset_type") == "meta_description"]

        if title_assets or meta_assets:
            print(f"  [guide] Writing {len(title_assets) + len(meta_assets)} meta snippets...")
            # Group by URL
            meta_by_url: dict[str, dict] = {}
            for a in title_assets:
                u = a.get("url", "")
                meta_by_url.setdefault(u, {})["title"] = a.get("content", "")
            for a in meta_assets:
                u = a.get("url", "")
                meta_by_url.setdefault(u, {})["description"] = a.get("content", "")

            for url, tags in meta_by_url.items():
                slug = _url_to_slug(url)
                filepath = os.path.join(output_dir, "meta", f"{slug}.html")
                html = _build_meta_snippet(url, tags.get("title"), tags.get("description"))
                _write(filepath, html)
                files_created.append(("meta", filepath, url))
        else:
            # Generate from findings
            print("  [guide] Generating meta tags from findings...")
            meta_files = await self._generate_meta_files(state, output_dir)
            files_created.extend(meta_files)

        # ── 3. Redirect rules ────────────────────────────────────────
        redirect_tasks = [t for t in tasks if t.get("category") == "redirect"]
        if redirect_tasks:
            print(f"  [guide] Generating redirect rules for {len(redirect_tasks)} redirects...")
            redirect_files = self._generate_redirect_files(redirect_tasks, output_dir)
            files_created.extend(redirect_files)

        # ── 4. Content briefs ────────────────────────────────────────
        brief_assets = [a for a in assets if a.get("asset_type") == "content_brief"]
        if brief_assets:
            print(f"  [guide] Writing {len(brief_assets)} content briefs...")
            for i, a in enumerate(brief_assets):
                slug = _url_to_slug(a.get("url", f"brief_{i}"))
                filepath = os.path.join(output_dir, "briefs", f"{slug}.md")
                _write(filepath, a.get("content", ""))
                files_created.append(("brief", filepath, a.get("url", "")))

        # ── 5. Draft HTML pages for new content ──────────────────────
        content_recs = analysis.get("content_recommendations", [])
        new_pages = [c for c in content_recs if c.get("type", "").lower() == "new_page"]
        if new_pages:
            print(f"  [guide] Generating {len(new_pages)} draft page templates...")
            page_files = await self._generate_draft_pages(state, new_pages, output_dir)
            files_created.extend(page_files)

        # ── 6. Generate the master guide ─────────────────────────────
        print("  [guide] Writing implementation guide...")
        guide_path = await self._generate_guide(state, files_created, output_dir)

        total = len(files_created)
        print(f"  [guide] Done — {total} files created in {output_dir}/")
        print(f"  [guide] Master guide: {guide_path}")
        return guide_path

    async def _generate_schema_files(self, state: dict, output_dir: str) -> list[tuple]:
        """Generate schema JSON-LD from analysis findings."""
        findings = state.get("analysis", {}).get("findings", [])
        schema_findings = [f for f in findings
                           if any(kw in f.get("title", "").lower()
                                  for kw in ["schema", "structured data", "json-ld", "localbusiness"])]

        if not schema_findings:
            # Generate homepage schema at minimum
            schema_findings = [{"affected_urls": [state.get("url", "")],
                                "title": "Add LocalBusiness schema to homepage"}]

        context = self._business_context(state)
        pages = []
        for f in schema_findings:
            pages.extend(f.get("affected_urls", [])[:5])
        pages = list(dict.fromkeys(pages))[:10]

        prompt = (
            f"{context}\n\n"
            f"Generate valid JSON-LD schema for each of these pages. "
            f"Use appropriate schema types (LocalBusiness/Plumber for homepage, "
            f"Service for services, FAQPage for FAQ/blog pages).\n\n"
            f"Pages:\n" + "\n".join(f"- {p}" for p in pages) +
            "\n\nReturn JSON with this structure:\n"
            '{"schemas": [{"url": "...", "json_ld": {...}}]}'
        )

        files = []
        try:
            resp = await self.llm.messages.create(
                model=settings.LLM_ANALYSIS_MODEL, max_tokens=8000,
                system="You are an SEO schema markup expert. Return valid JSON only.",
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = _parse_json(resp.content[0].text)
            if parsed:
                for s in parsed.get("schemas", []):
                    url = s.get("url", "")
                    schema = s.get("json_ld", s)
                    slug = _url_to_slug(url)
                    filepath = os.path.join(output_dir, "schema", f"{slug}.json")
                    _write(filepath, json.dumps(schema, indent=2))
                    files.append(("schema", filepath, url))
        except Exception as e:
            print(f"  [guide] Schema generation error: {e}")
        return files

    async def _generate_meta_files(self, state: dict, output_dir: str) -> list[tuple]:
        """Generate title tags and meta descriptions from findings."""
        findings = state.get("analysis", {}).get("findings", [])
        pages = set()
        for f in findings:
            if f.get("category") in ("on_page", "content"):
                pages.update(f.get("affected_urls", [])[:5])

        if not pages:
            pages = {state.get("url", "")}

        pages = list(pages)[:15]
        context = self._business_context(state)

        prompt = (
            f"{context}\n\n"
            f"Generate optimised title tags (max 60 chars) and meta descriptions "
            f"(145-155 chars) for these pages:\n"
            + "\n".join(f"- {p}" for p in pages) +
            '\n\nReturn JSON: {"metas": [{"url": "...", "title": "...", "description": "..."}]}'
        )

        files = []
        try:
            resp = await self.llm.messages.create(
                model=settings.LLM_EXTRACTION_MODEL, max_tokens=4000,
                system="You are an SEO meta tag specialist. Return valid JSON only.",
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = _parse_json(resp.content[0].text)
            if parsed:
                for m in parsed.get("metas", []):
                    url = m.get("url", "")
                    slug = _url_to_slug(url)
                    filepath = os.path.join(output_dir, "meta", f"{slug}.html")
                    html = _build_meta_snippet(url, m.get("title"), m.get("description"))
                    _write(filepath, html)
                    files.append(("meta", filepath, url))
        except Exception as e:
            print(f"  [guide] Meta generation error: {e}")
        return files

    def _generate_redirect_files(self, tasks: list[dict], output_dir: str) -> list[tuple]:
        """Generate .htaccess rules and a CSV for redirect plugins."""
        htaccess_rules = []
        csv_rows = ["source,destination,type"]

        for t in tasks:
            details = t.get("details", "")
            source, dest = _parse_redirect(details)
            if source and dest:
                htaccess_rules.append(f"Redirect 301 {source} {dest}")
                csv_rows.append(f"{source},{dest},301")

        files = []

        if htaccess_rules:
            # .htaccess file
            htaccess_path = os.path.join(output_dir, "redirects", "redirect_rules.htaccess")
            content = (
                "# SEO Agent — Generated Redirect Rules\n"
                "# Add these to your .htaccess file (Apache) or convert for Nginx\n"
                "# If using WordPress, install the 'Redirection' plugin and import the CSV instead\n\n"
                + "\n".join(htaccess_rules)
            )
            _write(htaccess_path, content)
            files.append(("redirect", htaccess_path, ""))

            # CSV for plugin import
            csv_path = os.path.join(output_dir, "redirects", "redirects.csv")
            _write(csv_path, "\n".join(csv_rows))
            files.append(("redirect", csv_path, ""))

        return files

    async def _generate_draft_pages(self, state: dict, new_pages: list[dict],
                                     output_dir: str) -> list[tuple]:
        """Generate draft HTML page templates for new content recommendations."""
        context = self._business_context(state)

        prompt = (
            f"{context}\n\n"
            f"Generate HTML page templates for these new pages that need to be created. "
            f"Each page should have a complete, SEO-optimised structure with:\n"
            f"- Proper H1, H2, H3 hierarchy\n"
            f"- Placeholder content sections (marked with [WRITE: description])\n"
            f"- Internal link suggestions (marked with [LINK: /target-page])\n"
            f"- CTA sections\n"
            f"- FAQ section with 5+ questions\n\n"
            f"Pages to create:\n"
            f"```json\n{json.dumps(new_pages, indent=2, default=str)}\n```\n\n"
            f'Return JSON: {{"pages": [{{"target_keyword": "...", "slug": "...", "html": "..."}}]}}'
        )

        files = []
        try:
            resp = await self.llm.messages.create(
                model=settings.LLM_ANALYSIS_MODEL, max_tokens=12000,
                system="You are an SEO content specialist. Generate clean HTML page templates. Return valid JSON only.",
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = _parse_json(resp.content[0].text)
            if parsed:
                for p in parsed.get("pages", []):
                    slug = p.get("slug", "new-page").strip("/").replace("/", "-")
                    filepath = os.path.join(output_dir, "content", f"{slug}.html")
                    _write(filepath, p.get("html", ""))
                    files.append(("content", filepath, p.get("target_keyword", "")))
        except Exception as e:
            print(f"  [guide] Draft page generation error: {e}")
        return files

    async def _generate_guide(self, state: dict, files_created: list[tuple],
                               output_dir: str) -> str:
        """Generate the master implementation guide using Claude."""
        analysis = state.get("analysis", {})
        findings = analysis.get("findings", [])
        tasks = state.get("task_plan", [])
        biz = state.get("business_name", "Unknown")
        url = state.get("url", "")

        # Build file manifest
        manifest = []
        for ftype, fpath, furl in files_created:
            rel = os.path.relpath(fpath, output_dir)
            manifest.append({"type": ftype, "file": rel, "for_url": furl})

        prompt = (
            f"Business: {biz}\n"
            f"URL: {url}\n"
            f"CMS: WordPress (assumed)\n\n"
            f"## Analysis Findings ({len(findings)} total)\n"
            f"```json\n{json.dumps(findings, indent=2, default=str)}\n```\n\n"
            f"## Task Plan ({len(tasks)} tasks)\n"
            f"```json\n{json.dumps(tasks, indent=2, default=str)}\n```\n\n"
            f"## Generated Files\n"
            f"```json\n{json.dumps(manifest, indent=2)}\n```\n\n"
            f"Write a comprehensive step-by-step implementation guide in markdown. "
            f"For each task:\n"
            f"1. What to do (in plain English)\n"
            f"2. Where to do it (exact WP admin path, or file to edit)\n"
            f"3. Which generated file to use (reference the exact filename)\n"
            f"4. How to verify it worked\n\n"
            f"Group by priority. Include screenshots descriptions where helpful. "
            f"Assume the reader knows WordPress basics but is not a developer. "
            f"Include a section on how to add schema via a plugin (Rank Math or Yoast), "
            f"how to add redirects via the Redirection plugin, and how to update meta tags."
        )

        guide_content = f"# Implementation Guide — {biz}\n\n"

        try:
            resp = await self.llm.messages.create(
                model=settings.LLM_ANALYSIS_MODEL, max_tokens=12000,
                system=(
                    "You are a WordPress SEO implementation consultant. "
                    "Write a clear, actionable step-by-step guide that a non-developer WordPress "
                    "user can follow. Reference specific generated files by their exact paths. "
                    "Be precise about WP admin navigation paths. Use markdown formatting."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            guide_content = resp.content[0].text
        except Exception as e:
            print(f"  [guide] Guide generation error: {e}")
            guide_content += self._fallback_guide(files_created, tasks)

        guide_path = os.path.join(output_dir, "guide.md")
        _write(guide_path, guide_content)
        return guide_path

    def _fallback_guide(self, files: list[tuple], tasks: list[dict]) -> str:
        """Simple fallback guide if Claude fails."""
        lines = [
            "## Generated Files\n",
            "| Type | File | For |",
            "|------|------|-----|",
        ]
        for ftype, fpath, furl in files:
            lines.append(f"| {ftype} | `{os.path.basename(fpath)}` | {furl} |")
        lines.append("")
        lines.append("## Tasks\n")
        for i, t in enumerate(tasks, 1):
            lines.append(f"{i}. **[{t.get('priority', '').upper()}]** {t.get('title', '')}")
            lines.append(f"   {t.get('details', '')}\n")
        return "\n".join(lines)

    def _business_context(self, state: dict) -> str:
        loc = state.get("location", {})
        city = loc.get("city", "") if isinstance(loc, dict) else ""
        return (
            f"Business: {state.get('business_name', 'Unknown')}\n"
            f"URL: {state.get('url', '')}\n"
            f"Description: {state.get('business_description', '')}\n"
            f"Location: {city}\n"
            f"Business model: {state.get('business_model', '')}\n"
            f"Target keywords: {', '.join(state.get('target_keywords', []))}"
        )


# ── Helpers ──────────────────────────────────────────────────────────

def _url_to_slug(url: str) -> str:
    """Convert a URL to a safe filename slug."""
    slug = url.rstrip("/").split("/")[-1] or "homepage"
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)
    return slug[:60]


def _build_meta_snippet(url: str, title: str | None, description: str | None) -> str:
    """Build a ready-to-paste HTML snippet for meta tags."""
    lines = [
        f"<!-- SEO Meta Tags for: {url} -->",
        f"<!-- Copy these into your page's <head> section -->",
        "",
    ]
    if title:
        lines.append(f"<title>{title}</title>")
    if description:
        lines.append(f'<meta name="description" content="{description}">')
    if title:
        lines.append(f'<meta property="og:title" content="{title}">')
    if description:
        lines.append(f'<meta property="og:description" content="{description}">')

    lines.append("")
    lines.append("<!--")
    if title:
        lines.append(f"  Yoast SEO field: 'SEO Title' → {title}")
    if description:
        lines.append(f"  Yoast SEO field: 'Meta Description' → {description}")
    lines.append(f"  Or in Rank Math: Edit page → Rank Math SEO box → General tab")
    lines.append("-->")
    return "\n".join(lines)


def _parse_redirect(details: str) -> tuple[str | None, str | None]:
    """Extract source and destination from task details."""
    m = re.search(r"(/\S+)\s*(?:→|->|to)\s*(/\S+)", details)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"redirect\s+(/\S+)\s+to\s+(/\S+)", details, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _write(filepath: str, content: str):
    """Write content to a file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def _parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
    return None
