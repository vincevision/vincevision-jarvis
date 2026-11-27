"""
executor.py — VINCEVISION Brain 2.0
───────────────────────────────────
Plan → execute → verify → learn.

Upgrade over the original executor:
  * {{stepN}} data-flow: later steps receive earlier steps' real outputs.
  * Self-verification against the plan's success_criteria, with corrective
    replanning when the goal was not actually achieved.
  * Long-term memory: relevant memories feed the planner; every finished task
    is recorded so future plans can reuse experience.
  * All LLM calls go through core.ai_router (correct SDK + Gemini→Groq
    fallback) instead of the broken legacy-API calls.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision
from core.ai_router      import ask_ai


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()

_REF_RE = re.compile(r"\{\{\s*step\s*(\d+)\s*\}\}", re.IGNORECASE)
MAX_REF_CHARS = 6000


# ════════════════════════════════════════════════════════════════
# Data flow (pure, unit-tested offline)
# ════════════════════════════════════════════════════════════════

def _resolve_refs(params, step_results: dict):
    """Replace {{stepN}} placeholders with earlier step outputs, recursively."""
    def subst(s: str) -> str:
        def repl(m):
            n = int(m.group(1))
            return str(step_results.get(n, ""))[:MAX_REF_CHARS]
        return _REF_RE.sub(repl, s)

    if isinstance(params, str):
        return subst(params)
    if isinstance(params, dict):
        return {k: _resolve_refs(v, step_results) for k, v in params.items()}
    if isinstance(params, list):
        return [_resolve_refs(v, step_results) for v in params]
    return params


def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    """Legacy fallback: fill an empty file-write with prior results."""
    if not step_results:
        return params
    params = dict(params)
    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                params["content"] = _translate_to_goal_language(combined, goal)
                print("[Executor] 💉 Injected + translated content")
    return params


# ════════════════════════════════════════════════════════════════
# LLM helpers (routed through ai_router)
# ════════════════════════════════════════════════════════════════

def _detect_language(text: str) -> str:
    res = ask_ai(
        "What language is this text written in? Reply with ONLY the language "
        "name in English (e.g. Turkish, English, French).\n\n"
        f"Text: {text[:200]}",
        preferred="gemini", temperature=0.0, max_tokens=32,
    )
    return res["text"].strip() if res["success"] and res["text"] else "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    target_lang = _detect_language(goal)
    print(f"[Executor] 🌐 Translating to: {target_lang}")
    res = ask_ai(
        "You are a professional translator. Translate the following text into "
        f"{target_lang}.\n"
        "IMPORTANT:\n"
        "- Translate EVERYTHING, leave nothing in English\n"
        "- Keep all facts, numbers, and data intact\n"
        "- Keep the structure and formatting\n"
        "- Output ONLY the translated text, nothing else\n\n"
        f"Text to translate:\n{content[:4000]}",
        preferred="gemini", temperature=0.2, max_tokens=4096,
    )
    if res["success"] and res["text"]:
        print(f"[Executor] ✅ Translation done ({target_lang})")
        return res["text"].strip()
    print(f"[Executor] ⚠️ Translation failed: {res['error']}")
    return content


def _run_generated_code(description: str, speak: Callable | None = None) -> str:
    if speak:
        speak("Writing custom code for this task, sir.")

    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"

    if not desktop.exists():
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            )
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass

    res = ask_ai(
        f"Write Python code to accomplish this task:\n\n{description}",
        system=(
            "You are an expert Python developer. Write clean, complete, working "
            "Python code. Use standard library + common packages. Install missing "
            "packages with subprocess + pip if needed. Return ONLY the Python "
            "code. No explanation, no markdown, no backticks.\n\n"
            f"SYSTEM PATHS:\n  Desktop   = r'{desktop}'\n"
            f"  Downloads = r'{downloads}'\n  Documents = r'{documents}'\n"
            f"  Home      = r'{home}'\n"
        ),
        preferred="gemini", temperature=0.2, max_tokens=8192,
    )
    if not res["success"]:
        raise RuntimeError(f"Generated code failed: {res['error']}")

    code = re.sub(r"```(?:python)?", "", res["text"]).strip().rstrip("`").strip()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        tmp_path = f.name

    print(f"[Executor] 🐍 Running generated code: {tmp_path}")
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=120, cwd=str(Path.home()),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Generated code timed out after 120 seconds.")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    output = result.stdout.strip()
    error  = result.stderr.strip()
    if result.returncode == 0 and output:
        return output
    if result.returncode == 0:
        return "Task completed successfully."
    if error:
        raise RuntimeError(f"Code error: {error[:400]}")
    return "Completed."


# ════════════════════════════════════════════════════════════════
# Tool dispatch
# ════════════════════════════════════════════════════════════════

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:
    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."
    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."
    elif tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak) or "Done."
    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Done."
    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."
    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."
    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."
    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Screen captured and analyzed."
    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."
    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."
    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."
    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."
    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."
    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."
    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."
    elif tool == "generated_code":
        description = parameters.get("description", "")
        if not description:
            raise ValueError("generated_code requires a 'description' parameter.")
        return _run_generated_code(description, speak=speak)
    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."
    else:
        print(f"[Executor] ⚠️ Unknown tool '{tool}' — falling back to generated_code")
        return _run_generated_code(f"Accomplish this task: {parameters}", speak=speak)


# ════════════════════════════════════════════════════════════════
# Executor
# ════════════════════════════════════════════════════════════════

VERIFIER_PROMPT = """You are the verification module of VINCEVISION.
Decide whether the user's goal was actually achieved, based on the step outputs.
Generic confirmations like "Done." count as success unless an output clearly
contradicts the goal. Be pragmatic, not pedantic.
Return ONLY valid JSON: {"satisfied": true, "missing": ""}
If not satisfied, "missing" is one short sentence describing what is still needed."""


class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2

    # ── memory hooks ────────────────────────────────────────────
    def _memory_context(self, goal: str) -> str:
        try:
            from core.long_term_memory import recall, get_preferences, format_for_prompt
            items = recall(goal, limit=4) + get_preferences(limit=6)
            return format_for_prompt(items)
        except Exception:
            return ""

    def _learn(self, goal: str, steps: list, outcome: str, success: bool) -> None:
        try:
            from core.long_term_memory import learn_from_task
            learn_from_task(goal, steps, outcome, success=success)
        except Exception:
            pass

    # ── self-verification ───────────────────────────────────────
    def _verify_goal(self, goal: str, plan: dict, step_results: dict) -> dict:
        criteria = plan.get("success_criteria") or goal
        results_text = "\n".join(
            f"Step {k}: {str(v)[:500]}" for k, v in sorted(step_results.items(), key=lambda x: str(x[0]))
        ) or "(no outputs)"
        res = ask_ai(
            f"User goal: {goal}\nSuccess criteria: {criteria}\n\n"
            f"Step outputs:\n{results_text}\n\nWas the goal achieved?",
            system=VERIFIER_PROMPT, preferred="gemini",
            temperature=0.0, max_tokens=256,
        )
        if not res["success"]:
            return {"satisfied": True, "missing": ""}  # fail open
        try:
            from agent.planner import _extract_json
            verdict = _extract_json(res["text"])
            return {
                "satisfied": bool(verdict.get("satisfied", True)),
                "missing":   str(verdict.get("missing", "")),
            }
        except Exception:
            return {"satisfied": True, "missing": ""}

    # ── main loop ───────────────────────────────────────────────
    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Executor] 🎯 Goal: {goal}")

        replan_attempts = 0
        completed_steps = []
        step_results    = {}
        plan            = create_plan(goal, context=self._memory_context(goal))

        while True:
            steps = plan.get("steps", [])
            if not steps:
                msg = "I couldn't create a valid plan for this task, sir."
                if speak: speak(msg)
                self._learn(goal, completed_steps, msg, False)
                return msg

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Task cancelled, sir.")
                    return "Task cancelled."

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _resolve_refs(params, step_results)
                params = _inject_context(params, tool, step_results, goal=goal)

                print(f"\n[Executor] ▶️ Step {step_num}: [{tool}] {desc}")

                attempt = 1
                step_ok = False

                while attempt <= 3:
                    if cancel_flag and cancel_flag.is_set():
                        break
                    try:
                        result = _call_tool(tool, params, speak)
                        try:
                            key = int(step_num)
                        except (TypeError, ValueError):
                            key = step_num
                        step_results[key] = result
                        completed_steps.append(step)
                        print(f"[Executor] ✅ Step {step_num} done: {str(result)[:100]}")
                        step_ok = True
                        break

                    except Exception as e:
                        error_msg = str(e)
                        print(f"[Executor] ❌ Step {step_num} attempt {attempt} failed: {error_msg}")

                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")
                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            attempt += 1
                            import time; time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Executor] ⏭️ Skipping step {step_num}")
                            completed_steps.append(step)
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Task aborted, sir. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            self._learn(goal, completed_steps, msg, False)
                            return msg

                        else:  # REPLAN
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion and tool != "generated_code":
                                try:
                                    fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                    if speak: speak("Trying an alternative approach, sir.")
                                    res = _call_tool(
                                        fixed_step["tool"],
                                        _resolve_refs(fixed_step["parameters"], step_results),
                                        speak,
                                    )
                                    try:
                                        key = int(step_num)
                                    except (TypeError, ValueError):
                                        key = step_num
                                    step_results[key] = res
                                    completed_steps.append(step)
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    print(f"[Executor] ⚠️ Fix failed: {fix_err}")

                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False

                if not success:
                    break

            # ── self-verification before declaring success ──────
            feedback = ""
            if success:
                verdict = self._verify_goal(goal, plan, step_results)
                if verdict.get("satisfied", True):
                    summary = self._summarize(goal, completed_steps, speak)
                    self._learn(goal, completed_steps, summary, True)
                    return summary

                if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                    summary = self._summarize(goal, completed_steps, speak)
                    self._learn(goal, completed_steps, summary, False)
                    return summary

                feedback     = f"Verification: {verdict.get('missing') or 'goal not satisfied'}"
                failed_step  = steps[-1]
                failed_error = feedback
                success      = False
                if speak: speak("That didn't fully achieve the goal, sir. Refining my approach.")

            if replan_attempts >= self.MAX_REPLAN_ATTEMPTS:
                msg = f"Task failed after {replan_attempts} replan attempts, sir."
                if speak: speak(msg)
                self._learn(goal, completed_steps, msg, False)
                return msg

            if speak and not feedback: speak("Adjusting my approach, sir.")

            replan_attempts += 1
            plan = replan(goal, completed_steps, failed_step, failed_error, feedback=feedback)

    def _summarize(self, goal: str, completed_steps: list, speak: Callable | None) -> str:
        fallback = f"All done, sir. Completed {len(completed_steps)} steps for: {goal[:60]}."
        steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)
        res = ask_ai(
            f'User goal: "{goal}"\nCompleted steps:\n{steps_str}\n\n'
            "Write a single natural sentence summarizing what was accomplished. "
            "Address the user as 'sir'. Be direct and positive.",
            preferred="gemini", temperature=0.4, max_tokens=256,
        )
        summary = res["text"].strip() if res["success"] and res["text"] else fallback
        if speak: speak(summary)
        return summary
