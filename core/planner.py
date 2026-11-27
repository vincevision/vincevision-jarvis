import json
import asyncio
import re


class JarvisPlanner:
    """
    Strategic AI Planner — converts high-level goals into
    multi-step executable JSON plans.
    Uses ai_router so Groq fallback works automatically.
    """

    def __init__(self, api_key: str, tool_declarations: list):
        self.api_key           = api_key
        self.tool_declarations = tool_declarations

    def _extract_json(self, text: str) -> list:
        text = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return []

    def _ask_sync(self, prompt: str, temperature: float = 0.2) -> str:
        """
        Synchronous AI call via router — Gemini first, Groq fallback.
        """
        try:
            from core.ai_router import ask_ai
            result = ask_ai(
                prompt      = prompt,
                preferred   = "gemini",
                temperature = temperature,
                max_tokens  = 8192,
            )
            if result["success"]:
                print(
                    f"[PLANNER] ✅ {result['provider']} "
                    f"({result['model']})"
                )
                return result["text"]
            else:
                print(f"[PLANNER] ❌ All providers failed: {result['error']}")
                return ""
        except Exception as e:
            print(f"[PLANNER] ❌ Router error: {e}")
            return ""

    async def create_plan(self, goal: str, context: str = "") -> list:
        """Generate a multi-step execution plan for the given goal."""

        tool_summary = "\n".join(
            f"  - {t['name']}: {t.get('description', '')[:100]}"
            for t in self.tool_declarations
        )

        prompt = f"""You are ULTRON Strategic Planner — an elite autonomous AI mission planner.

GOAL: {goal}
{f'CONTEXT: {context}' if context else ''}

AVAILABLE TOOLS:
{tool_summary}

Break this goal into a precise, ordered execution plan.
Each step must use ONLY tools from the list above.

Respond ONLY with a valid JSON array. No explanation. No markdown.

FORMAT:
[
  {{
    "step": 1,
    "tool": "tool_name_here",
    "args": {{"arg1": "value1"}},
    "reason": "Why this step is needed",
    "depends_on": [],
    "parallel": false,
    "critical": true,
    "on_failure": "continue"
  }}
]

on_failure: "stop" | "continue" | "retry"
GOAL: {goal}"""

        try:
            loop = asyncio.get_event_loop()
            raw  = await loop.run_in_executor(
                None, lambda: self._ask_sync(prompt, temperature=0.2)
            )
            if not raw:
                return []

            plan = self._extract_json(raw)
            if not plan:
                print(f"[PLANNER] ⚠️ Could not parse plan. Raw: {raw[:300]}")
                return []

            print(f"[PLANNER] ✅ Plan: {len(plan)} steps")
            return plan

        except Exception as e:
            print(f"[PLANNER] ❌ Plan creation failed: {e}")
            return []

    async def replan(
        self,
        original_goal: str,
        completed_steps: list,
        failed_step: dict,
        results_so_far: list
    ) -> list:
        """Re-plan after a failure."""
        context = (
            f"Original goal: {original_goal}\n"
            f"Completed steps: {json.dumps(completed_steps)}\n"
            f"Failed step: {json.dumps(failed_step)}\n"
            f"Generate ONLY the remaining steps needed."
        )
        return await self.create_plan(original_goal, context=context)


class ExecutionEngine:
    """
    Autonomous step-by-step execution engine.
    """

    def __init__(self, jarvis_live_instance, planner: JarvisPlanner = None):
        self.jarvis  = jarvis_live_instance
        self.planner = planner
        self.results = {}
        self.log     = []

    def _log(self, msg: str):
        print(f"[EXEC] {msg}")
        self.log.append(msg)
        try:
            self.jarvis.ui.write_log(f"[EXEC] {msg}")
        except Exception:
            pass

    class _MockFC:
        def __init__(self, name: str, args: dict, step_id: int):
            self.name = name
            self.args = args
            self.id   = f"plan_step_{step_id}"

    async def _run_step(self, step: dict) -> dict:
        step_id = step.get("step", 0)
        tool    = step.get("tool", "")
        args    = step.get("args", {})
        reason  = step.get("reason", "")

        self._log(f"▶ Step {step_id}: {tool} — {reason}")

        fc     = self._MockFC(tool, args, step_id)
        result = await self.jarvis._execute_tool(fc)

        result_text = ""
        if result and result.response:
            result_text = str(result.response.get("result", ""))

        self.results[step_id] = result_text
        self._log(f"✅ Step {step_id} done: {result_text[:120]}")

        return {
            "step":    step_id,
            "tool":    tool,
            "success": "failed" not in result_text.lower()[:50],
            "result":  result_text,
        }

    async def _wait_for_dependencies(
        self, step: dict, completed: set, running: set
    ):
        deps = step.get("depends_on", [])
        while True:
            if all(d in completed for d in deps):
                break
            await asyncio.sleep(0.5)

    async def execute_plan(
        self,
        plan: list,
        goal: str = "",
        allow_replan: bool = True
    ) -> list:
        if not plan:
            self._log("⚠️ Empty plan.")
            return []

        self._log(f"🚀 Executing plan: {len(plan)} steps")
        completed   = set()
        running     = set()
        all_results = []
        pending     = list(plan)

        while pending:
            ready = [
                s for s in pending
                if all(d in completed for d in s.get("depends_on", []))
                and s["step"] not in running
            ]

            if not ready:
                await asyncio.sleep(0.3)
                continue

            parallel_steps   = [s for s in ready if s.get("parallel", False)]
            sequential_steps = [s for s in ready if not s.get("parallel", False)]

            if parallel_steps:
                self._log(
                    f"⚡ Parallel: {[s['step'] for s in parallel_steps]}"
                )
                for s in parallel_steps:
                    running.add(s["step"])
                    pending.remove(s)

                tasks   = [self._run_step(s) for s in parallel_steps]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for step, result in zip(parallel_steps, results):
                    if isinstance(result, Exception):
                        result = {
                            "step":    step["step"],
                            "tool":    step["tool"],
                            "success": False,
                            "result":  str(result)
                        }
                    completed.add(step["step"])
                    running.discard(step["step"])
                    all_results.append(result)

                    if not result["success"]:
                        on_failure = step.get("on_failure", "continue")
                        if on_failure == "stop" and step.get("critical", False):
                            self._log(f"🛑 Critical step {step['step']} failed.")
                            if allow_replan and self.planner and goal:
                                new_plan = await self.planner.replan(
                                    goal, list(completed), step, all_results
                                )
                                if new_plan:
                                    self._log(f"🔄 Re-plan: {len(new_plan)} steps")
                                    pending.extend(new_plan)
                            else:
                                return all_results

            elif sequential_steps:
                step = sequential_steps[0]
                running.add(step["step"])
                pending.remove(step)

                result = await self._run_step(step)
                completed.add(step["step"])
                running.discard(step["step"])
                all_results.append(result)

                if not result["success"]:
                    on_failure = step.get("on_failure", "continue")
                    if on_failure == "retry":
                        self._log(f"🔁 Retrying step {step['step']}...")
                        pending.insert(0, step)
                        completed.discard(step["step"])
                    elif on_failure == "stop" and step.get("critical", False):
                        self._log(f"🛑 Critical step {step['step']} failed.")
                        if allow_replan and self.planner and goal:
                            new_plan = await self.planner.replan(
                                goal, list(completed), step, all_results
                            )
                            if new_plan:
                                self._log(f"🔄 Re-plan: {len(new_plan)} steps")
                                pending.extend(new_plan)
                        else:
                            return all_results

        self._log(f"🏁 Complete. {len(all_results)} steps.")
        return all_results

    def get_summary(self) -> str:
        lines = ["[EXECUTION SUMMARY]"]
        for entry in self.log[-20:]:
            lines.append(entry)
        return "\n".join(lines)