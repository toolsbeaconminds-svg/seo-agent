import json
import re
import anthropic

from config import settings
from core.prompts import ANALYST_SYSTEM_PROMPT


class AnalystAgent:
    """Takes all collected data and produces a structured analysis via Claude."""

    def __init__(self):
        self.llm = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def run(self, state: dict) -> dict:
        print("  [analyst] Synthesising all data...")

        focus_keywords = state.get("focus_keywords", [])
        focus_pages = state.get("focus_pages", [])
        special_instructions = state.get("special_instructions", "")

        payload = {
            "business_name": state.get("business_name", "Unknown"),
            "business_description": state.get("business_description", ""),
            "location": state.get("location", {}),
            "business_model": state.get("business_model", ""),
            "target_keywords": state.get("target_keywords", []),
            "competitors": state.get("competitors", []),
            "key_person": state.get("key_person", {}),
            "gsc_data": state.get("gsc_data", {}),
            "ga4_data": state.get("ga4_data", {}),
            "ahrefs_data": state.get("ahrefs_data", {}),
            "pagespeed_data": state.get("pagespeed_data", {}),
            "on_page_audit": state.get("on_page_audit", []),
            "robots_txt": state.get("robots_txt"),
            "sitemap": state.get("sitemap", {}),
            "anomalies_so_far": state.get("anomalies", []),
            "data_errors": state.get("errors", []),
        }

        # Build directive block — only included when the user supplied focus inputs
        directive_lines = []
        if focus_keywords:
            directive_lines.append(
                f"FOCUS KEYWORDS: {', '.join(focus_keywords)}\n"
                "  → Check current rankings for these terms specifically. Elevate any findings "
                "related to them. Ensure keyword_analysis.opportunities includes each one with "
                "current position and recommended action."
            )
        if focus_pages:
            pages_list = "\n  ".join(focus_pages)
            directive_lines.append(
                f"FOCUS PAGES:\n  {pages_list}\n"
                "  → Audit these URLs with extra scrutiny. Promote any issues affecting them to "
                "higher priority. Include a dedicated finding for each focus page if issues exist."
            )
        if special_instructions:
            directive_lines.append(
                f"SPECIAL INSTRUCTIONS: {special_instructions}\n"
                "  → Respect this context. Let it override general heuristics where applicable."
            )

        directive_block = ""
        if directive_lines:
            directive_block = (
                "=== USER DIRECTIVES — follow these strictly ===\n"
                + "\n\n".join(directive_lines)
                + "\n================================================\n\n"
            )

        user_msg = (
            f"{directive_block}"
            "Analyse this data and return the structured JSON analysis.\n\n"
            f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
        )

        try:
            # Use streaming to avoid SDK timeout on large payloads
            raw = ""
            stop_reason = None
            async with self.llm.messages.stream(
                model=settings.LLM_ANALYSIS_MODEL,
                max_tokens=32000,
                system=ANALYST_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                async for text in stream.text_stream:
                    raw += text
                resp = await stream.get_final_message()
                stop_reason = resp.stop_reason

            if stop_reason == "max_tokens":
                print("  [analyst] WARNING: response was truncated — increasing limit may help")

            analysis = _parse_json(raw)
            if analysis:
                state["analysis"] = analysis
                n_findings = len(analysis.get("findings", []))
                n_gaps = len(analysis.get("keyword_analysis", {}).get("keyword_gaps", []))
                print(f"  [analyst] Done — {n_findings} findings, {n_gaps} keyword gaps")
            else:
                state.setdefault("errors", []).append("Analyst: could not parse LLM response")
                print("  [analyst] ERROR: could not parse response")
                print(f"  [analyst] Raw response (first 500 chars): {raw[:500]}")
        except Exception as e:
            state.setdefault("errors", []).append(f"Analyst: {e}")
            print(f"  [analyst] ERROR: {e}")

        return state


def _parse_json(text: str) -> dict | None:
    # Try raw text first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try inside code fences
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try to find the outermost { ... } JSON object
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
