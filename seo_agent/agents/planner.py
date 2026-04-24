"""Planner Agent — takes analysis findings and creates a prioritised, classified task list."""

import json
import re
import anthropic

from config import settings
from core.prompts import PLANNER_SYSTEM_PROMPT


class PlannerAgent:

    def __init__(self):
        self.llm = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def run(self, state: dict) -> dict:
        print("  [planner] Creating implementation task plan...")

        analysis = state.get("analysis", {})
        if not analysis:
            state.setdefault("errors", []).append("Planner: no analysis data found")
            print("  [planner] ERROR: no analysis data — run analysis first")
            return state

        # Build context for Claude
        payload = {
            "business_name": state.get("business_name", "Unknown"),
            "url": state.get("url", ""),
            "business_model": state.get("business_model", ""),
            "findings": analysis.get("findings", []),
            "quick_wins": analysis.get("quick_wins", []),
            "content_recommendations": analysis.get("content_recommendations", []),
            "keyword_gaps": analysis.get("keyword_analysis", {}).get("keyword_gaps", []),
            "wp_available": bool(settings.WP_URL),
            "gsc_available": bool(settings.GOOGLE_SERVICE_ACCOUNT_KEY_PATH),
        }

        user_msg = (
            "Create an implementation task plan for this SEO analysis.\n"
            f"WordPress API available: {payload['wp_available']}\n"
            f"GSC API available: {payload['gsc_available']}\n\n"
            f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
        )

        try:
            raw = ""
            async with self.llm.messages.stream(
                model=settings.LLM_ANALYSIS_MODEL,
                max_tokens=12000,
                temperature=0,
                system=PLANNER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            ) as stream:
                async for text in stream.text_stream:
                    raw += text
                resp = await stream.get_final_message()

            print(f"  [planner] Response length: {len(raw)} chars, stop_reason: {resp.stop_reason}")
            if resp.stop_reason == "max_tokens":
                print("  [planner] WARNING: response was truncated — may be incomplete")

            plan = _parse_json(raw)
            if plan:
                tasks = plan.get("tasks", [])
                state["task_plan"] = tasks

                auto = sum(1 for t in tasks if t.get("can_automate"))
                manual = len(tasks) - auto
                print(f"  [planner] Done — {len(tasks)} tasks ({auto} automatable, {manual} manual)")
            else:
                state.setdefault("errors", []).append("Planner: could not parse response")
                print("  [planner] ERROR: could not parse response")
                print(f"  [planner] Raw (first 800 chars): {raw[:800]}")
                print(f"  [planner] Raw (last 300 chars): {raw[-300:]}")

                # Fallback: build tasks directly from findings
                print("  [planner] Falling back to building tasks from findings...")
                findings = analysis.get("findings", [])
                state["task_plan"] = _tasks_from_findings(findings)
                print(f"  [planner] Fallback produced {len(state['task_plan'])} tasks")
        except Exception as e:
            state.setdefault("errors", []).append(f"Planner: {e}")
            print(f"  [planner] ERROR: {e}")
            import traceback
            traceback.print_exc()

            # Fallback on exception too
            findings = analysis.get("findings", [])
            if findings:
                print("  [planner] Falling back to building tasks from findings...")
                state["task_plan"] = _tasks_from_findings(findings)
                print(f"  [planner] Fallback produced {len(state['task_plan'])} tasks")

        return state


def _tasks_from_findings(findings: list[dict]) -> list[dict]:
    """Build a basic task list directly from analysis findings (fallback)."""
    category_map = {
        "technical": "technical",
        "on_page": "seo_meta",
        "content": "content",
        "backlinks": "other",
        "local_seo": "schema",
        "performance": "technical",
    }
    tasks = []
    for i, f in enumerate(findings):
        tasks.append({
            "id": f.get("id", f"task-{i}"),
            "title": f.get("title", "Untitled"),
            "finding_id": f.get("id"),
            "priority": f.get("priority", "medium"),
            "category": category_map.get(f.get("category", ""), "other"),
            "can_automate": False,
            "requires_wp_api": False,
            "requires_gsc_api": False,
            "requires_developer": f.get("owner") == "developer",
            "estimated_minutes": 15,
            "details": f.get("fix_instructions", f.get("description", "")),
            "target_url": (f.get("affected_urls") or [""])[0] if f.get("affected_urls") else None,
        })
    return tasks


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

    # Try 3: find outermost { } using proper string-aware brace matching
    start = text.find("{")
    if start != -1:
        # Find the LAST } in the text (more reliable than depth counting with strings)
        end = text.rfind("}")
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    # Try 4: depth-based brace matching (original approach)
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
