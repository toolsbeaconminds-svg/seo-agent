"""
SEO Agent — Minimal Web UI
Run with:  python app.py
Then open: http://localhost:5000
"""

import asyncio
import json
import os
import threading
import time
import uuid
import anthropic
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory, Response

from main import run_analysis
from config import settings

app = Flask(__name__)

# In-memory stores
jobs: dict[str, dict] = {}
chat_sessions: dict[str, dict] = {}

STATE_FILE = "output/.last_analysis_state.json"
CHAT_SESSION_FILE = "output/.chat_session.json"


def _run_job(job_id: str, url: str, ga4_id: str | None):
    """Run the analysis in a background thread."""
    logs = jobs[job_id]["logs"]

    def log_callback(msg: str):
        logs.append(msg)

    try:
        jobs[job_id]["status"] = "running"
        filepath = asyncio.run(run_analysis(url, ga4_property_id=ga4_id, log_callback=log_callback))
        jobs[job_id]["status"] = "done"
        jobs[job_id]["report_path"] = filepath

        # Read the report content for display
        with open(filepath, "r", encoding="utf-8") as f:
            jobs[job_id]["report_content"] = f.read()
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        logs.append(f"FATAL ERROR: {e}")


def _run_implement_job(job_id: str, mode: str, wp_url: str, wp_user: str, wp_pass: str):
    """Run the implementation pipeline in a background thread."""
    from agents.planner import PlannerAgent
    from agents.content_agent import ContentAgent
    from agents.wordpress_agent import WordPressAgent
    from agents.gsc_actions_agent import GSCActionsAgent
    from agents.reporter import ReporterAgent
    from agents.guide_agent import GuideAgent

    logs = jobs[job_id]["logs"]

    try:
        jobs[job_id]["status"] = "running"

        # Load analysis state
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        state.setdefault("task_plan", [])
        state.setdefault("generated_assets", [])
        state.setdefault("implementation_log", [])
        state.setdefault("dev_briefs", [])
        state.setdefault("verify_list", [])

        async def _run():
            # Step 1: Plan
            logs.append("[1/5] Planning implementation tasks...")
            planner = PlannerAgent()
            nonlocal state
            state = await planner.run(state)
            tasks = state.get("task_plan", [])
            logs.append(f"  Planner done — {len(tasks)} tasks")

            # Step 2: Generate assets
            logs.append("[2/5] Generating SEO assets...")
            content = ContentAgent()
            state = await content.run(state)
            logs.append(f"  Content done — {len(state.get('generated_assets', []))} assets")

            if mode == "auto":
                # WP mode
                settings.WP_URL = wp_url
                settings.WP_USERNAME = wp_user
                settings.WP_APP_PASSWORD = wp_pass

                logs.append("[3/5] Implementing via WordPress API...")
                wp = WordPressAgent()
                state = await wp.run(state)

                logs.append("[4/5] Executing GSC actions...")
                gsc = GSCActionsAgent()
                state = await gsc.run(state)

                logs.append("[5/5] Generating implementation report...")
                reporter = ReporterAgent()
                filepath = await reporter.run(state)

                impl_log = state.get("implementation_log", [])
                changed = sum(1 for l in impl_log if l["result"] == "CHANGED")
                logs.append(f"  Done — {changed} changes made")
                return filepath
            else:
                # Guide mode
                logs.append("[3/5] Generating implementation files...")
                guide = GuideAgent()
                guide_path = await guide.run(state)

                logs.append("[4/5] Executing GSC actions...")
                gsc = GSCActionsAgent()
                state = await gsc.run(state)

                logs.append("[5/5] Done!")
                logs.append(f"  Implementation kit: output/implementation_kit/")
                return guide_path

        filepath = asyncio.run(_run())

        # Save updated state (with task_plan, generated_assets, etc.)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

        jobs[job_id]["status"] = "done"
        jobs[job_id]["report_path"] = filepath

        if filepath and os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                jobs[job_id]["report_content"] = f.read()

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        logs.append(f"FATAL ERROR: {e}")


# ── Routes ───────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return "ok", 200


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyse", methods=["POST"])
def start_analysis():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    ga4_id = (data.get("ga4_property_id") or "").strip() or None

    if not url:
        return jsonify({"error": "URL is required"}), 400
    if not url.startswith("http"):
        url = f"https://{url}"

    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "type": "analysis",
        "url": url,
        "status": "starting",
        "logs": [],
        "report_path": None,
        "report_content": None,
        "error": None,
        "started_at": time.time(),
    }

    thread = threading.Thread(target=_run_job, args=(job_id, url, ga4_id), daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/implement", methods=["POST"])
def start_implementation():
    if not os.path.exists(STATE_FILE):
        return jsonify({"error": "No analysis found. Run an analysis first."}), 400

    data = request.get_json()
    mode = data.get("mode", "guide")  # "auto" or "guide"
    wp_url = (data.get("wp_url") or "").strip()
    wp_user = (data.get("wp_username") or "").strip()
    wp_pass = (data.get("wp_password") or "").strip()

    if mode == "auto" and (not wp_url or not wp_user or not wp_pass):
        return jsonify({"error": "WordPress credentials required for auto mode"}), 400

    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "type": "implementation",
        "mode": mode,
        "status": "starting",
        "logs": [],
        "report_path": None,
        "report_content": None,
        "error": None,
        "started_at": time.time(),
    }

    thread = threading.Thread(
        target=_run_implement_job,
        args=(job_id, mode, wp_url, wp_user, wp_pass),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/state")
def check_state():
    """Check if an analysis state exists for implementation."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        return jsonify({
            "available": True,
            "url": state.get("url", ""),
            "business_name": state.get("business_name", ""),
            "findings": len(state.get("analysis", {}).get("findings", [])),
        })
    return jsonify({"available": False})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify({
        "status": job["status"],
        "logs": job["logs"],
        "error": job["error"],
        "report_content": job["report_content"],
        "elapsed": round(time.time() - job["started_at"]),
    })


@app.route("/api/download/<job_id>")
def download_report(job_id):
    job = jobs.get(job_id)
    if not job or not job["report_path"]:
        return jsonify({"error": "Report not ready"}), 404
    return send_file(job["report_path"], as_attachment=True)


@app.route("/api/download-kit")
def download_kit():
    """Download the implementation kit as a zip."""
    import zipfile, io
    kit_dir = "output/implementation_kit"
    if not os.path.exists(kit_dir):
        return jsonify({"error": "No implementation kit found"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(kit_dir):
            for file in files:
                full = os.path.join(root, file)
                arcname = os.path.relpath(full, kit_dir)
                zf.write(full, arcname)
    buf.seek(0)

    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=implementation_kit.zip"}
    )


# ── Guide Chat API ───────────────────────────────────────────────────

def _build_guide_system_prompt(state: dict, tasks: list[dict], assets: list[dict]) -> str:
    """Build the system prompt for the interactive guide chat."""
    biz = state.get("business_name", "Unknown")
    url = state.get("url", "")
    loc = state.get("location", {})
    city = loc.get("city", "") if isinstance(loc, dict) else ""

    # Build asset file manifest
    kit_dir = "output/implementation_kit"
    file_manifest = []
    if os.path.exists(kit_dir):
        for root, dirs, files in os.walk(kit_dir):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), kit_dir)
                file_manifest.append(rel)

    # Read generated file contents for context
    file_contents = {}
    for rel in file_manifest[:30]:  # Limit to avoid token overflow
        full = os.path.join(kit_dir, rel)
        try:
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > 3000:
                content = content[:3000] + "\n... (truncated)"
            file_contents[rel] = content
        except Exception:
            pass

    return f"""You are an SEO implementation assistant guiding a WordPress user through their SEO fixes step by step.

## Context
- Business: {biz}
- URL: {url}
- Location: {city}
- CMS: WordPress (assumed)

## Task Plan ({len(tasks)} tasks)
{json.dumps(tasks, indent=2, default=str)}

## Generated Files Available
{json.dumps(file_manifest, indent=2)}

## File Contents
{json.dumps(file_contents, indent=2, default=str)}

## Your Behavior

1. **Present ONE task at a time.** Start with the highest priority task. Show its number (e.g. "Task 1 of 14").

2. **For each task, explain:**
   - What this fix does and why it matters (1-2 sentences)
   - Exact step-by-step instructions with WordPress admin navigation paths
   - Which generated file to use, and show the actual content they need to copy/paste
   - How to verify the change worked

3. **Wait for the user** before moving on. They might say:
   - "done" / "next" → move to the next task
   - "skip" → skip this task, move on
   - A question → answer it, then ask if they're ready to proceed
   - "show me the file" → show the full file content
   - "I don't understand" → explain in simpler terms

4. **Keep track of progress.** When they complete a task, briefly acknowledge it and present the next one.

5. **Be concise but precise.** Use exact WP admin paths like: "Go to Pages → All Pages → find 'Services' → click Edit → scroll to Yoast SEO box below the editor"

6. **Format nicely.** Use markdown: bold for important things, code blocks for content they need to copy, numbered lists for steps.

7. **Start the conversation** by greeting them, telling them how many tasks there are, and presenting Task 1.

8. **Adapt to skill level.** If they ask basic questions, provide more detail. If they're moving fast, be more concise.

9. **At the end**, give a summary of what was done, what was skipped, and what to verify in 48 hours."""


def _save_chat_session(session_id: str):
    """Persist the chat session to disk so it survives restarts."""
    if session_id not in chat_sessions:
        return
    data = {
        "session_id": session_id,
        "system": chat_sessions[session_id]["system"],
        "messages": chat_sessions[session_id]["messages"],
        "task_count": chat_sessions[session_id]["task_count"],
        "business": chat_sessions[session_id]["business"],
    }
    os.makedirs("output", exist_ok=True)
    with open(CHAT_SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _load_chat_session() -> str | None:
    """Load a saved chat session from disk. Returns session_id or None."""
    if not os.path.exists(CHAT_SESSION_FILE):
        return None
    try:
        with open(CHAT_SESSION_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        sid = data["session_id"]
        chat_sessions[sid] = {
            "system": data["system"],
            "messages": data["messages"],
            "task_count": data["task_count"],
            "business": data["business"],
        }
        return sid
    except Exception as e:
        print(f"  [chat] Could not load saved session: {e}")
        return None


@app.route("/api/chat/resume", methods=["GET"])
def chat_resume():
    """Check if there's a saved chat session to resume."""
    sid = _load_chat_session()
    if not sid:
        return jsonify({"has_session": False})

    session = chat_sessions[sid]
    # Get the last assistant message to show
    last_msg = ""
    for m in reversed(session["messages"]):
        if m["role"] == "assistant":
            last_msg = m["content"]
            break

    return jsonify({
        "has_session": True,
        "session_id": sid,
        "task_count": session["task_count"],
        "business": session["business"],
        "message_count": len(session["messages"]),
        "messages": session["messages"],
    })


@app.route("/api/chat/start", methods=["POST"])
def chat_start():
    """Start a new guided implementation chat session."""
    if not os.path.exists(STATE_FILE):
        return jsonify({"error": "No analysis found. Run an analysis first."}), 400

    # Load state
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    tasks = state.get("task_plan", [])
    assets = state.get("generated_assets", [])
    findings = state.get("analysis", {}).get("findings", [])

    # If no task plan, build one from findings so the chat can still work
    if not tasks and findings:
        tasks = [
            {
                "id": f.get("id", f"task-{i}"),
                "title": f.get("title", "Untitled"),
                "priority": f.get("priority", "medium"),
                "category": f.get("category", "other"),
                "details": f.get("fix_instructions", f.get("description", "")),
                "target_url": (f.get("affected_urls") or [""])[0],
                "can_automate": False,
                "requires_wp_api": False,
                "requires_gsc_api": False,
                "requires_developer": f.get("owner") == "developer",
            }
            for i, f in enumerate(findings)
        ]
        state["task_plan"] = tasks

    if not tasks:
        return jsonify({"error": "No findings or task plan found. Run analysis first."}), 400

    session_id = uuid.uuid4().hex[:8]
    system_prompt = _build_guide_system_prompt(state, tasks, assets)

    chat_sessions[session_id] = {
        "system": system_prompt,
        "messages": [],
        "task_count": len(tasks),
        "business": state.get("business_name", "Unknown"),
    }

    # Get initial greeting from Claude (with retry for overloaded errors)
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    assistant_msg = None
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=settings.LLM_ANALYSIS_MODEL,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": "Let's start. Guide me through the implementation."}],
            )
            assistant_msg = resp.content[0].text
            break
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 2:
                wait = (attempt + 1) * 5
                print(f"  [chat/start] API overloaded, retrying in {wait}s (attempt {attempt + 1}/3)...")
                time.sleep(wait)
            else:
                print(f"  [chat/start] Claude error: {e}")
                return jsonify({"error": f"AI error: {e}"}), 500
        except Exception as e:
            print(f"  [chat/start] Claude error: {e}")
            return jsonify({"error": f"AI error: {e}"}), 500

    if not assistant_msg:
        return jsonify({"error": "AI service unavailable. Try again in a moment."}), 503

    chat_sessions[session_id]["messages"] = [
        {"role": "user", "content": "Let's start. Guide me through the implementation."},
        {"role": "assistant", "content": assistant_msg},
    ]

    _save_chat_session(session_id)

    return jsonify({
        "session_id": session_id,
        "message": assistant_msg,
        "task_count": len(tasks),
    })


@app.route("/api/chat/message", methods=["POST"])
def chat_message():
    """Send a message in a guided implementation chat session."""
    data = request.get_json()
    session_id = data.get("session_id", "")
    user_msg = (data.get("message") or "").strip()

    if not session_id or session_id not in chat_sessions:
        return jsonify({"error": "Invalid session"}), 400
    if not user_msg:
        return jsonify({"error": "Message is required"}), 400

    session = chat_sessions[session_id]
    session["messages"].append({"role": "user", "content": user_msg})

    # Call Claude
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=settings.LLM_ANALYSIS_MODEL,
        max_tokens=2000,
        system=session["system"],
        messages=session["messages"],
    )
    assistant_msg = resp.content[0].text
    session["messages"].append({"role": "assistant", "content": assistant_msg})

    return jsonify({"message": assistant_msg})


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """Stream a chat response using SSE for real-time feel."""
    data = request.get_json()
    session_id = data.get("session_id", "")
    user_msg = (data.get("message") or "").strip()

    if not session_id or session_id not in chat_sessions:
        return jsonify({"error": "Invalid session"}), 400
    if not user_msg:
        return jsonify({"error": "Message is required"}), 400

    session = chat_sessions[session_id]
    session["messages"].append({"role": "user", "content": user_msg})

    def generate():
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        full_response = ""

        for attempt in range(3):
            try:
                with client.messages.stream(
                    model=settings.LLM_ANALYSIS_MODEL,
                    max_tokens=2000,
                    system=session["system"],
                    messages=session["messages"],
                ) as stream:
                    for text in stream.text_stream:
                        full_response += text
                        yield f"data: {json.dumps({'text': text})}\n\n"

                session["messages"].append({"role": "assistant", "content": full_response})
                _save_chat_session(session_id)
                break
            except anthropic.APIStatusError as e:
                if e.status_code == 529 and attempt < 2:
                    wait = (attempt + 1) * 5
                    print(f"  [chat/stream] API overloaded, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  [chat/stream] ERROR: {e}")
                    yield f"data: {json.dumps({'text': f'\\n\\n⚠️ API overloaded. Please try again in a moment.'})}\n\n"
                    break
            except Exception as e:
                print(f"  [chat/stream] ERROR: {e}")
                yield f"data: {json.dumps({'text': f'\\n\\n⚠️ Error: {e}'})}\n\n"
                break

        yield f"data: {json.dumps({'done': True})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  SEO Agent UI running at http://localhost:{port}\n")
    app.run(debug=False, host="0.0.0.0", port=port)
