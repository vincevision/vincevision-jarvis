# VINCEVISION Brain 2.0

Upgrade to the agent's planning, execution, and memory.

## What changed

| Area | Before | After |
|------|--------|-------|
| LLM calls | Legacy `genai.configure` / `GenerativeModel` via the new-SDK import — always raised, silently falling back | Routed through `core.ai_router.ask_ai` (correct `google.genai.Client`, Gemini → Groq fallback) |
| Planning | Max 5 independent steps; every task collapsed to one `web_search` | Up to 8 steps with **data flow** and `success_criteria` |
| Data flow | Crude "dump all results into a file" hack | `{{stepN}}` placeholders resolved recursively in any parameter |
| Verification | None — "Done." was always success | Self-verification against `success_criteria`, corrective replan when unmet |
| Memory | Private local module only; fresh clones crashed on import | Persistent SQLite + FTS5 store (`core/long_term_memory.py`), import fallback, voice `recall_memory` tool |
| Learning | None | Every finished task recorded; relevant memories feed the planner |
| Reliability | No tests / CI | Offline pytest suite + GitHub Actions on every push |

## Data flow between steps

A plan step can consume an earlier step's output:

```json
{
  "steps": [
    {"step": 1, "tool": "weather_report", "parameters": {"city": "Nairobi"}},
    {"step": 2, "tool": "send_message",
     "parameters": {"receiver": "John", "platform": "WhatsApp",
                    "message_text": "Nairobi weather: {{step1}}"}}
  ]
}
```

`{{step1}}` is replaced with step 1's real result before step 2 runs.
Only backward references are allowed; self/forward refs are stripped during
plan normalization. Outputs are capped at 6000 chars per reference.

## Long-term memory

- Stored in `memory/long_term.db` (gitignored — never leaves the machine).
- `remember()`, `recall()`, `get_preferences()`, `recent()`, `learn_from_task()`.
- Voice tools: `save_memory` now dual-writes; new `recall_memory` searches it.
- Relevant memories + preferences are injected into the live system prompt.
- A compatibility shim (`load_memory` / `update_memory` /
  `format_memory_for_prompt`) keeps fresh clones running even though the
  original private `memory/` package is not in the repo.

## Self-verification

After all steps succeed, the executor asks the model whether the
`success_criteria` was actually met. If not, it replans with the verifier's
feedback (bounded by `MAX_REPLAN_ATTEMPTS`). Verification fails *open* — an
LLM outage never blocks a completed task.

## Tests

```bash
python -m pytest -q tests/test_brain.py
```

Offline: no API keys, network, PyQt6, or audio needed. CI runs them on
Python 3.11 and 3.12 for every push and pull request.
