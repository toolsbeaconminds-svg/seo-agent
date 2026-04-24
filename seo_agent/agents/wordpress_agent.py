"""WordPress Agent — implements SEO fixes via the WordPress REST API."""

import json
from datetime import datetime

from config import settings
from tools.wp_client import WPClient


class WordPressAgent:

    async def run(self, state: dict) -> dict:
        print("  [wordpress] Starting WordPress implementation...")

        if not all([settings.WP_URL, settings.WP_USERNAME, settings.WP_APP_PASSWORD]):
            print("  [wordpress] SKIPPED — WordPress credentials not configured")
            state.setdefault("errors", []).append(
                "WordPress: credentials not configured (WP_URL, WP_USERNAME, WP_APP_PASSWORD)"
            )
            # Move all WP tasks to dev_briefs
            wp_tasks = [t for t in state.get("task_plan", []) if t.get("requires_wp_api")]
            state.setdefault("dev_briefs", []).extend([
                {"task": t["title"], "details": t.get("details", ""), "url": t.get("target_url", "")}
                for t in wp_tasks
            ])
            return state

        client = WPClient()
        log = state.setdefault("implementation_log", [])
        dev_briefs = state.setdefault("dev_briefs", [])
        verify_list = state.setdefault("verify_list", [])

        tasks = [t for t in state.get("task_plan", []) if t.get("requires_wp_api")]
        assets = state.get("generated_assets", [])

        if not tasks:
            print("  [wordpress] No WordPress tasks to implement")
            await client.close()
            return state

        print(f"  [wordpress] {len(tasks)} tasks to implement...")

        for i, task in enumerate(tasks, 1):
            cat = task.get("category", "")
            url = task.get("target_url", "")
            title = task.get("title", "")

            print(f"  [wordpress] [{i}/{len(tasks)}] {title}")

            try:
                if cat == "seo_meta":
                    await self._implement_meta(client, task, assets, log, verify_list)
                elif cat == "schema":
                    await self._implement_schema(client, task, assets, log, verify_list)
                elif cat == "redirect":
                    await self._implement_redirect(client, task, log, verify_list)
                elif cat == "content":
                    await self._implement_content(client, task, assets, log, verify_list)
                else:
                    # Can't auto-implement — add to dev briefs
                    dev_briefs.append({
                        "task": title,
                        "details": task.get("details", ""),
                        "url": url,
                        "priority": task.get("priority", "medium"),
                    })
                    _log_action(log, "DEFERRED", cat, url, f"Moved to dev briefs: {title}")
            except Exception as e:
                _log_action(log, "FAILED", cat, url, str(e))
                print(f"    FAILED: {e}")

        await client.close()

        done = sum(1 for l in log if l["result"] == "CHANGED")
        skipped = sum(1 for l in log if l["result"] == "SKIPPED")
        failed = sum(1 for l in log if l["result"] == "FAILED")
        print(f"  [wordpress] Done — {done} changed, {skipped} skipped, {failed} failed")
        return state

    async def _implement_meta(self, client: WPClient, task: dict,
                               assets: list[dict], log: list, verify: list):
        """Update title tag and meta description for a page."""
        url = task.get("target_url", "")
        post = await client.get_post_by_url(url) if url else None

        if not post:
            _log_action(log, "FAILED", "seo_meta", url, "Could not find post in WordPress")
            return

        post_id = post["id"]
        post_type = "pages" if post.get("type") == "page" else "posts"

        # Find matching generated assets
        title_asset = _find_asset(assets, url, "title_tag")
        meta_asset = _find_asset(assets, url, "meta_description")

        new_title = title_asset.get("content") if title_asset else None
        new_meta = meta_asset.get("content") if meta_asset else None

        if not new_title and not new_meta:
            _log_action(log, "SKIPPED", "seo_meta", url, "No generated meta assets for this page")
            return

        # Check current values
        current_meta = post.get("meta", {})
        current_title = current_meta.get("_yoast_wpseo_title", "")
        current_desc = current_meta.get("_yoast_wpseo_metadesc", "")

        if new_title and current_title == new_title:
            new_title = None  # Already correct
        if new_meta and current_desc == new_meta:
            new_meta = None

        if not new_title and not new_meta:
            _log_action(log, "SKIPPED", "seo_meta", url, "Already correct")
            return

        await client.update_seo_meta(post_id, new_title, new_meta, post_type)

        changes = []
        if new_title:
            changes.append(f"title → '{new_title}'")
        if new_meta:
            changes.append(f"meta → '{new_meta[:60]}...'")
        _log_action(log, "CHANGED", "seo_meta", url, "; ".join(changes))
        verify.append(url)

    async def _implement_schema(self, client: WPClient, task: dict,
                                 assets: list[dict], log: list, verify: list):
        """Inject JSON-LD schema into a page."""
        url = task.get("target_url", "")
        post = await client.get_post_by_url(url) if url else None

        if not post:
            _log_action(log, "FAILED", "schema", url, "Could not find post in WordPress")
            return

        schema_asset = _find_asset(assets, url, "schema_json")
        if not schema_asset:
            schema_asset = _find_asset(assets, url, "faq_schema")
        if not schema_asset:
            _log_action(log, "SKIPPED", "schema", url, "No generated schema for this page")
            return

        post_id = post["id"]
        post_type = "pages" if post.get("type") == "page" else "posts"
        schema_json = schema_asset["content"]

        # Validate it's actual JSON
        try:
            json.loads(schema_json)
        except (json.JSONDecodeError, TypeError):
            _log_action(log, "FAILED", "schema", url, "Generated schema is not valid JSON")
            return

        await client.inject_schema(post_id, schema_json, post_type)
        _log_action(log, "CHANGED", "schema", url, "Injected JSON-LD schema")
        verify.append(url)

    async def _implement_redirect(self, client: WPClient, task: dict,
                                   log: list, verify: list):
        """Add a 301 redirect."""
        details = task.get("details", "")
        url = task.get("target_url", "")

        # Try to parse source/destination from details
        # Common format: "redirect /old to /new" or "/old → /new"
        source, dest = _parse_redirect(details, url)
        if not source or not dest:
            _log_action(log, "FAILED", "redirect", url, f"Could not parse redirect from: {details}")
            return

        result = await client.add_redirect(source, dest)
        if result.get("error"):
            _log_action(log, "DEFERRED", "redirect", url,
                        f"{result['error']} — {result.get('manual_fix', '')}")
        else:
            _log_action(log, "CHANGED", "redirect", source, f"301 → {dest}")
            verify.append(source)

    async def _implement_content(self, client: WPClient, task: dict,
                                  assets: list[dict], log: list, verify: list):
        """Create a new draft page from a content brief."""
        url = task.get("target_url", "")
        brief = _find_asset(assets, url, "content_brief")

        if not brief:
            _log_action(log, "SKIPPED", "content", url, "No content brief — needs manual creation")
            return

        # For new pages we only create a placeholder draft with the brief as content
        slug = url.strip("/").split("/")[-1] if url else task.get("id", "new-page")
        title = task.get("title", "New Page")

        # Check if page already exists
        existing = await client.get_post_by_slug(slug)
        if existing:
            _log_action(log, "SKIPPED", "content", url, f"Page already exists (ID {existing['id']})")
            return

        content = (
            f"<!-- SEO CONTENT BRIEF — Review and expand before publishing -->\n\n"
            f"{brief['content']}"
        )
        result = await client.create_page(title, content, slug, status="draft")
        _log_action(log, "CHANGED", "content", url,
                    f"Created draft page (ID {result['id']}) — needs human review before publishing")
        verify.append(f"{settings.WP_URL}/{slug}")


def _find_asset(assets: list[dict], url: str, asset_type: str) -> dict | None:
    """Find a generated asset matching the URL and type."""
    for a in assets:
        if a.get("asset_type") == asset_type and a.get("url", "") == url:
            return a
    # Fuzzy match — URL might have trailing slash differences
    url_clean = url.rstrip("/")
    for a in assets:
        if a.get("asset_type") == asset_type and a.get("url", "").rstrip("/") == url_clean:
            return a
    return None


def _parse_redirect(details: str, fallback_url: str) -> tuple[str | None, str | None]:
    """Try to extract source and destination from task details."""
    import re
    # Pattern: /source → /destination or /source -> /destination
    m = re.search(r"(/\S+)\s*(?:→|->|to)\s*(/\S+)", details)
    if m:
        return m.group(1), m.group(2)
    # Pattern: redirect /source to /destination
    m = re.search(r"redirect\s+(/\S+)\s+to\s+(/\S+)", details, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _log_action(log: list, result: str, category: str, url: str, detail: str):
    """Append a structured log entry."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "result": result,
        "category": category,
        "url": url,
        "detail": detail,
    }
    log.append(entry)
    icon = {"CHANGED": "+", "SKIPPED": "~", "FAILED": "!", "DEFERRED": ">"}.get(result, "?")
    print(f"    [{icon}] {result} | {category} | {url} | {detail}")
