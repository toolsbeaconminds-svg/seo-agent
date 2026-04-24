"""Content Agent — generates SEO assets: title tags, meta descriptions, schema JSON-LD, content briefs."""

import json
import re
import anthropic

from config import settings
from core.prompts import CONTENT_AGENT_SYSTEM_PROMPT


class ContentAgent:

    def __init__(self):
        self.llm = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def run(self, state: dict) -> dict:
        print("  [content] Generating SEO assets...")

        analysis = state.get("analysis", {})
        tasks = state.get("task_plan", [])

        if not analysis and not tasks:
            print("  [content] No analysis or task plan — skipping")
            return state

        # Identify pages that need assets
        findings = analysis.get("findings", [])
        content_recs = analysis.get("content_recommendations", [])

        # Group: pages needing meta fixes, schema, new content
        meta_pages = []
        schema_pages = []
        new_pages = []
        update_pages = []

        for f in findings:
            cat = f.get("category", "")
            urls = f.get("affected_urls", [])
            title = f.get("title", "").lower()

            if any(kw in title for kw in ["title tag", "meta description", "seo meta", "duplicate"]):
                meta_pages.extend(urls)
            if any(kw in title for kw in ["schema", "structured data", "json-ld"]):
                schema_pages.extend(urls)

        for c in content_recs:
            ctype = c.get("type", "").lower()
            if ctype == "new_page":
                new_pages.append(c)
            elif ctype in ("update", "merge"):
                update_pages.append(c)

        # Also generate meta/schema for pages from task plan
        for t in tasks:
            cat = t.get("category", "")
            url = t.get("target_url")
            if not url:
                continue
            if cat == "seo_meta" and url not in meta_pages:
                meta_pages.append(url)
            if cat == "schema" and url not in schema_pages:
                schema_pages.append(url)

        # If no pages found for meta/schema, add homepage and all affected URLs
        if not meta_pages and not schema_pages:
            url = state.get("url", "")
            if url:
                meta_pages.append(url)
                schema_pages.append(url)
            # Add all affected URLs from findings
            for f in findings:
                for u in (f.get("affected_urls") or []):
                    if u and u not in meta_pages:
                        meta_pages.append(u)

        # Deduplicate
        meta_pages = list(dict.fromkeys(meta_pages))
        schema_pages = list(dict.fromkeys(schema_pages))

        print(f"  [content] Pages: {len(meta_pages)} meta, {len(schema_pages)} schema, "
              f"{len(new_pages)} new, {len(update_pages)} updates")

        all_assets = []

        # ── Batch 1: Title tags + Meta descriptions ──────────────────
        if meta_pages:
            print(f"  [content] Generating title tags & meta descriptions for {len(meta_pages)} pages...")
            assets = await self._generate_meta(state, meta_pages)
            all_assets.extend(assets)
            print(f"  [content] Generated {len(assets)} meta assets")

        # ── Batch 2: Schema JSON-LD ──────────────────────────────────
        if schema_pages:
            print(f"  [content] Generating schema markup for {len(schema_pages)} pages...")
            assets = await self._generate_schema(state, schema_pages)
            all_assets.extend(assets)
            print(f"  [content] Generated {len(assets)} schema assets")

        # ── Batch 3: Content briefs for new pages & keyword gaps ─────
        gaps = analysis.get("keyword_analysis", {}).get("keyword_gaps", [])
        brief_items = new_pages + [{"target_keyword": g["keyword"], "type": "keyword_gap",
                                     "description": g.get("suggested_action", "")}
                                    for g in gaps[:5]]
        if brief_items:
            print(f"  [content] Generating {len(brief_items)} content briefs...")
            assets = await self._generate_briefs(state, brief_items)
            all_assets.extend(assets)
            print(f"  [content] Generated {len(assets)} content briefs")

        state["generated_assets"] = all_assets
        print(f"  [content] Done — {len(all_assets)} total assets generated")
        return state

    async def _generate_meta(self, state: dict, urls: list[str]) -> list[dict]:
        """Generate title tags and meta descriptions in a single batch."""
        context = self._business_context(state)
        user_msg = (
            f"{context}\n\n"
            f"Generate optimised title tags and meta descriptions for these pages:\n"
            + "\n".join(f"- {u}" for u in urls[:20])
            + "\n\nReturn 2 assets per page (one title_tag, one meta_description)."
        )
        return await self._call_llm(user_msg, model=settings.LLM_EXTRACTION_MODEL, max_tokens=4000)

    async def _generate_schema(self, state: dict, urls: list[str]) -> list[dict]:
        """Generate JSON-LD schema markup."""
        context = self._business_context(state)
        findings = state.get("analysis", {}).get("findings", [])
        schema_findings = [f for f in findings if "schema" in f.get("title", "").lower()]

        user_msg = (
            f"{context}\n\n"
            f"Related findings:\n{json.dumps(schema_findings, indent=2, default=str)}\n\n"
            f"Generate appropriate JSON-LD schema for these pages:\n"
            + "\n".join(f"- {u}" for u in urls[:15])
            + "\n\nUse LocalBusiness/Plumber for homepage, Service schema for service pages, "
            "FAQPage for FAQ/blog pages. Return asset_type as 'schema_json'."
        )
        return await self._call_llm(user_msg, model=settings.LLM_ANALYSIS_MODEL, max_tokens=8000)

    async def _generate_briefs(self, state: dict, items: list[dict]) -> list[dict]:
        """Generate content briefs for new pages and keyword gaps."""
        context = self._business_context(state)
        user_msg = (
            f"{context}\n\n"
            f"Generate detailed content briefs for these items:\n"
            f"```json\n{json.dumps(items, indent=2, default=str)}\n```\n\n"
            f"Each brief should include: target keyword, search intent, recommended word count, "
            f"H1 + H2 outline, internal links to add, schema type, CTA, and E-E-A-T elements. "
            f"Return asset_type as 'content_brief'."
        )
        return await self._call_llm(user_msg, model=settings.LLM_ANALYSIS_MODEL, max_tokens=8000)

    async def _call_llm(self, user_msg: str, model: str = None, max_tokens: int = 4000) -> list[dict]:
        """Call Claude and parse the assets list from the response."""
        try:
            raw = ""
            async with self.llm.messages.stream(
                model=model or settings.LLM_ANALYSIS_MODEL,
                max_tokens=max_tokens,
                temperature=0,
                system=CONTENT_AGENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                async for text in stream.text_stream:
                    raw += text
                resp = await stream.get_final_message()

            if resp.stop_reason == "max_tokens":
                print(f"  [content] WARNING: response truncated ({len(raw)} chars)")
            parsed = _parse_json(raw)
            if parsed:
                return parsed.get("assets", [])
            else:
                print(f"  [content] Could not parse response (first 300 chars): {raw[:300]}")
        except Exception as e:
            print(f"  [content] LLM error: {e}")
            import traceback
            traceback.print_exc()
        return []

    def _business_context(self, state: dict) -> str:
        """Build business context string for prompts."""
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


def _parse_json(text: str) -> dict | None:
    # Try 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try 2: fenced code block
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try 3: outermost braces (first { to last })
    start = text.find("{")
    if start != -1:
        end = text.rfind("}")
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    # Try 4: depth-based brace matching
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
