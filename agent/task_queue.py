"""
Agent task queue — parallel execution with self-healing retries.

Upgrades over the original serial queue:
  * Parallel workers (default 3, configurable via JARVIS_MAX_CONCURRENT)
  * Automatic retries with exponential backoff
  * Error classification: transient errors retry, permanent ones fail fast
  * Optional `healer` hook that can rewrite a goal between attempts
  * Per-task attempt history, queue stats, wait() and manual retry()

The public surface (TaskStatus, TaskPriority, Task, TaskQueue, get_queue)
is backwards compatible with the original module.
"""

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any


DEFAULT_MAX_CONCURRENT = 3
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_DELAY = 2.0
MAX_CONCURRENCY_LIMIT = 16

# Errors that will never succeed on retry — fail fast instead of burning time.
_PERMANENT_MARKERS = (
    "unknown tool", "unknown action", "not authorized", "unauthorized",
    "permission denied", "access denied", "invalid api key", "api key not",
    "no such file", "not found: ", "unsupported", "invalid syntax",
    "confirm=", "requires confirmation", "daily ", "limit reached",
)
_TRANSIENT_MARKERS = (
    "timeout", "timed out", "temporarily", "connection", "network",
    "rate limit", "429", "500", "502", "503", "504", "unavailable",
    "reset by peer", "eof", "try again", "busy", "locked",
)


def classify_error(error: str) -> str:
    """'transient' | 'permanent' | 'unknown'."""
    e = str(error or "").lower()
    if any(m in e for m in _PERMANENT_MARKERS):
        return "permanent"
    if any(m in e for m in _TRANSIENT_MARKERS):
        return "transient"
    return "unknown"


def default_concurrency() -> int:
    try:
        n = int(os.environ.get("JARVIS_MAX_CONCURRENT", DEFAULT_MAX_CONCURRENT))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CONCURRENT
    return max(1, min(n, MAX_CONCURRENCY_LIMIT))


class TaskStatus(Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"
    RETRYING   = "retrying"


class TaskPriority(Enum):
    LOW    = 3
    NORMAL = 2
    HIGH   = 1


@dataclass(order=True)
class Task:
    priority:    int
    created_at:  float = field(compare=False)
    task_id:     str   = field(compare=False)
    goal:        str   = field(compare=False)
    status:      TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result:      Any        = field(compare=False, default=None)
    error:       str        = field(compare=False, default="")
    speak:       Any        = field(compare=False, default=None)
    on_complete: Any        = field(compare=False, default=None)
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)
    attempts:    int        = field(compare=False, default=0)
    max_retries: int        = field(compare=False, default=DEFAULT_MAX_RETRIES)
    retry_delay: float      = field(compare=False, default=DEFAULT_RETRY_DELAY)
    next_attempt_at: float  = field(compare=False, default=0.0)
    history:     list       = field(compare=False, default_factory=list)


class TaskQueue:
    def __init__(self, max_concurrent: int | None = None,
                 max_retries: int = DEFAULT_MAX_RETRIES,
                 retry_delay: float = DEFAULT_RETRY_DELAY,
                 healer: Callable | None = None,
                 clock: Callable = time.time,
                 sleeper: Callable = time.sleep):
        self._queue:        list[Task]       = []
        self._lock:         threading.Lock   = threading.Lock()
        self._condition:    threading.Condition = threading.Condition(self._lock)
        self._tasks:        dict[str, Task]  = {}
        self._running:      bool             = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = int(max_concurrent) if max_concurrent else default_concurrency()
        self._max_concurrent = max(1, min(self._max_concurrent, MAX_CONCURRENCY_LIMIT))
        self._active_count   = 0
        self._executor       = None
        self._max_retries    = max(0, int(max_retries))
        self._retry_delay    = max(0.0, float(retry_delay))
        self._healer         = healer
        self._clock          = clock
        self._sleep          = sleeper
        self._retries_total  = 0

    # ── wiring ──────────────────────────────────────────────────────────
    def _get_executor(self):
        if self._executor is None:
            from agent.executor import AgentExecutor
            self._executor = AgentExecutor()
        return self._executor

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="AgentTaskQueue")
        self._worker_thread.start()
        print(f"[TaskQueue] ✅ Started (max {self._max_concurrent} parallel)")

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        print("[TaskQueue] 🔴 Stopped")

    # ── submission ──────────────────────────────────────────────────────
    def submit(self, goal: str, priority: TaskPriority = TaskPriority.NORMAL,
               speak: Callable | None = None, on_complete: Callable | None = None,
               max_retries: int | None = None) -> str:
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            priority=priority.value, created_at=self._clock(), task_id=task_id,
            goal=goal, speak=speak, on_complete=on_complete,
            max_retries=self._max_retries if max_retries is None else max(0, int(max_retries)),
            retry_delay=self._retry_delay,
        )
        with self._condition:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[task_id] = task
            self._condition.notify()
        print(f"[TaskQueue] 📥 Queued: [{task_id}] {goal[:60]}")
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False
            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            try:
                self._queue.remove(task)
            except ValueError:
                pass
            return True

    def retry(self, task_id: str) -> bool:
        """Manually requeue a failed/cancelled task with a fresh attempt budget."""
        with self._condition:
            task = self._tasks.get(task_id)
            if not task or task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False
            task.status = TaskStatus.PENDING
            task.error = ""
            task.attempts = 0
            task.next_attempt_at = 0.0
            task.cancel_flag.clear()
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._condition.notify()
            return True

    # ── inspection ──────────────────────────────────────────────────────
    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id, "goal": task.goal,
                "status": task.status.value, "result": task.result,
                "error": task.error, "attempts": task.attempts,
                "max_retries": task.max_retries, "history": list(task.history),
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [{"task_id": t.task_id, "goal": t.goal[:50],
                     "status": t.status.value, "attempts": t.attempts}
                    for t in self._tasks.values()]

    def get_stats(self) -> dict:
        with self._lock:
            counts = {s.value: 0 for s in TaskStatus}
            for t in self._tasks.values():
                counts[t.status.value] += 1
            return {
                "total": len(self._tasks), "active": self._active_count,
                "max_concurrent": self._max_concurrent,
                "queued": sum(1 for t in self._queue if t.status == TaskStatus.PENDING),
                "retries_total": self._retries_total, "by_status": counts,
            }

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._queue if t.status == TaskStatus.PENDING)

    def wait(self, task_id: str, timeout: float = 60.0, poll: float = 0.05) -> dict | None:
        """Block until the task settles (or timeout). Returns its status dict."""
        deadline = self._clock() + timeout
        while True:
            st = self.get_status(task_id)
            if st is None:
                return None
            if st["status"] in ("completed", "failed", "cancelled"):
                return st
            if self._clock() >= deadline:
                return st
            self._sleep(poll)

    # ── scheduling ──────────────────────────────────────────────────────
    def _worker_loop(self) -> None:
        while self._running:
            with self._condition:
                while self._running and self._next_task() is None:
                    self._condition.wait(timeout=0.2)
                task = self._next_task()
                if task:
                    task.status = TaskStatus.RUNNING
                    self._active_count += 1
                    try:
                        self._queue.remove(task)
                    except ValueError:
                        pass
            if task:
                threading.Thread(target=self._run_task, args=(task,), daemon=True,
                                 name=f"AgentTask-{task.task_id}").start()

    def _next_task(self) -> Task | None:
        if self._active_count >= self._max_concurrent:
            return None
        now = self._clock()
        for task in self._queue:
            if (task.status == TaskStatus.PENDING
                    and not task.cancel_flag.is_set()
                    and task.next_attempt_at <= now):
                return task
        return None

    # ── execution + self-healing ────────────────────────────────────────
    def _backoff(self, task: Task) -> float:
        return task.retry_delay * (2 ** max(0, task.attempts - 1))

    def _should_retry(self, task: Task, error: str) -> bool:
        if task.cancel_flag.is_set():
            return False
        if task.attempts > task.max_retries:
            return False
        return classify_error(error) != "permanent"

    def _heal(self, task: Task, error: str) -> None:
        if not self._healer:
            return
        try:
            revised = self._healer(task.goal, error, task.attempts)
            if revised and isinstance(revised, str) and revised != task.goal:
                task.history.append({"attempt": task.attempts, "from": task.goal,
                                     "to": revised, "error": error[:200]})
                task.goal = revised
        except Exception as e:
            print(f"[TaskQueue] ⚠️ healer error: {e}")

    def _run_task(self, task: Task) -> None:
        print(f"[TaskQueue] ▶️ Running: [{task.task_id}] {task.goal[:60]}")
        requeued = False
        try:
            executor = self._get_executor()
            result = executor.execute(goal=task.goal, speak=task.speak,
                                      cancel_flag=task.cancel_flag)
            with self._lock:
                self._active_count -= 1
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = result
            if task.on_complete and not task.cancel_flag.is_set():
                try:
                    task.on_complete(task.task_id, result)
                except Exception as e:
                    print(f"[TaskQueue] ⚠️ on_complete error: {e}")
            print(f"[TaskQueue] ✅ Completed: [{task.task_id}]")

        except Exception as e:
            error = str(e)
            with self._condition:
                self._active_count -= 1
                task.attempts += 1
                task.error = error
                if self._should_retry(task, error):
                    self._heal(task, error)
                    delay = self._backoff(task)
                    task.status = TaskStatus.PENDING
                    task.next_attempt_at = self._clock() + delay
                    self._queue.append(task)
                    self._queue.sort(key=lambda t: (t.priority, t.created_at))
                    self._retries_total += 1
                    requeued = True
                    self._condition.notify()
                    print(f"[TaskQueue] 🔁 Retry {task.attempts}/{task.max_retries} "
                          f"[{task.task_id}] in {delay:.1f}s — {error[:70]}")
                else:
                    task.status = TaskStatus.FAILED
                    print(f"[TaskQueue] ❌ Failed: [{task.task_id}] {error[:90]}")

        with self._condition:
            self._condition.notify()
        return requeued


_queue: TaskQueue | None = None
_queue_started = False
_queue_lock = threading.Lock()


def get_queue() -> TaskQueue:
    global _queue, _queue_started
    with _queue_lock:
        if _queue is None:
            _queue = TaskQueue()
        if not _queue_started:
            _queue.start()
            _queue_started = True
    return _queue


def task_control(parameters: dict, player=None, speak=None) -> str:
    """Tool surface for the parallel, self-healing queue.

    submit | status | list | stats | cancel | retry | wait
    """
    params = parameters or {}
    action = str(params.get("action", "stats")).lower().strip()
    try:
        if action == "stats":
            q = _queue
            if q is None:
                return (f"Task queue idle. Parallel slots: {default_concurrency()}. "
                        "Submit a task to start it.")
            s = q.get_stats()
            lines = [f"⚡ Tasks: {s['total']} total, {s['active']} running "
                     f"(of {s['max_concurrent']} slots), {s['queued']} queued",
                     f"  Auto-retries so far: {s['retries_total']}"]
            lines += [f"  {k}: {v}" for k, v in s["by_status"].items() if v]
            return "\n".join(lines)

        if action in ("submit", "add", "run"):
            goal = str(params.get("goal", "")).strip()
            if not goal:
                return "What should the task do? Give me a goal."
            prio = str(params.get("priority", "normal")).lower()
            priority = {"high": TaskPriority.HIGH, "low": TaskPriority.LOW}.get(
                prio, TaskPriority.NORMAL)
            q = get_queue()
            tid = q.submit(goal, priority)
            return (f"⚡ Queued [{tid}] ({prio} priority): {goal[:80]}\n"
                    f"Running up to {q.max_concurrent} tasks in parallel, "
                    "with automatic retries.")

        if action in ("list", "status_all"):
            q = _queue
            if q is None:
                return "No tasks submitted yet."
            rows = q.get_all_statuses()
            if not rows:
                return "No tasks submitted yet."
            return "⚡ Tasks:\n" + "\n".join(
                f"  [{r['task_id']}] {r['status']:<9} (attempt {r['attempts']}) {r['goal']}"
                for r in rows)

        if action == "status":
            tid = str(params.get("task_id", "")).strip()
            if not tid:
                return "Which task? Give me its task_id."
            q = _queue
            st = q.get_status(tid) if q else None
            if not st:
                return f"No task with id '{tid}'."
            out = (f"[{st['task_id']}] {st['status']} — {st['goal']}\n"
                   f"  Attempts: {st['attempts']} (max retries {st['max_retries']})")
            if st["error"]:
                out += f"\n  Last error: {st['error'][:160]}"
            if st["result"]:
                out += f"\n  Result: {str(st['result'])[:400]}"
            if st["history"]:
                out += f"\n  Self-healed {len(st['history'])} time(s)."
            return out

        if action == "cancel":
            tid = str(params.get("task_id", "")).strip()
            if not tid:
                return "Which task should I cancel?"
            q = _queue
            ok = q.cancel(tid) if q else False
            return f"🚫 Cancelled [{tid}]." if ok else f"Could not cancel '{tid}' (unknown or already finished)."

        if action == "retry":
            tid = str(params.get("task_id", "")).strip()
            if not tid:
                return "Which task should I retry?"
            q = _queue
            ok = q.retry(tid) if q else False
            return f"🔁 Requeued [{tid}]." if ok else f"'{tid}' isn't a failed task."

        if action == "wait":
            tid = str(params.get("task_id", "")).strip()
            if not tid:
                return "Which task should I wait for?"
            q = _queue
            if q is None:
                return f"No task with id '{tid}'."
            st = q.wait(tid, timeout=float(params.get("timeout", 60)))
            if not st:
                return f"No task with id '{tid}'."
            return f"[{st['task_id']}] {st['status']}\n{str(st['result'] or st['error'])[:400]}"

        return f"Unknown task action '{action}'. Try submit, status, list, stats, cancel, retry, wait."
    except Exception as e:
        return f"task_control '{action}' failed: {e}"
