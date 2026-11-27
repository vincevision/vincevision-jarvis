"""Offline tests for the parallel, self-healing task queue.

The executor is faked, and a virtual clock/sleeper make retry timing
deterministic. One test exercises real worker threads to prove parallelism.
"""

import threading
import time

import pytest

from agent import task_queue as tq


class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


class FakeExecutor:
    """Fails the first `fail_times` calls, then succeeds."""

    def __init__(self, fail_times=0, error="Connection timeout"):
        self.fail_times = fail_times
        self.error = error
        self.calls = []

    def execute(self, goal, speak=None, cancel_flag=None):
        self.calls.append(goal)
        if len(self.calls) <= self.fail_times:
            raise RuntimeError(self.error)
        return f"done: {goal}"


def make_queue(monkeypatch, executor, **kw):
    clock = FakeClock()
    q = tq.TaskQueue(max_concurrent=kw.pop("max_concurrent", 3),
                     clock=clock.time, sleeper=clock.sleep, **kw)
    monkeypatch.setattr(q, "_get_executor", lambda: executor)
    return q, clock


# ── error classification ────────────────────────────────────────────────────

@pytest.mark.parametrize("err", ["Connection timeout", "rate limit hit", "HTTP 503",
                                 "network unreachable", "resource busy"])
def test_classify_transient(err):
    assert tq.classify_error(err) == "transient"


@pytest.mark.parametrize("err", ["Unknown tool 'foo'", "Permission denied",
                                 "Invalid API key", "Daily upload limit reached",
                                 "requires confirmation"])
def test_classify_permanent(err):
    assert tq.classify_error(err) == "permanent"


def test_classify_unknown():
    assert tq.classify_error("something odd") == "unknown"
    assert tq.classify_error("") == "unknown"


def test_default_concurrency(monkeypatch):
    monkeypatch.delenv("JARVIS_MAX_CONCURRENT", raising=False)
    assert tq.default_concurrency() == tq.DEFAULT_MAX_CONCURRENT


def test_concurrency_env(monkeypatch):
    monkeypatch.setenv("JARVIS_MAX_CONCURRENT", "7")
    assert tq.default_concurrency() == 7


def test_concurrency_clamped(monkeypatch):
    monkeypatch.setenv("JARVIS_MAX_CONCURRENT", "999")
    assert tq.default_concurrency() == tq.MAX_CONCURRENCY_LIMIT
    monkeypatch.setenv("JARVIS_MAX_CONCURRENT", "0")
    assert tq.default_concurrency() == 1


def test_concurrency_bad_env(monkeypatch):
    monkeypatch.setenv("JARVIS_MAX_CONCURRENT", "abc")
    assert tq.default_concurrency() == tq.DEFAULT_MAX_CONCURRENT


# ── submission / status ─────────────────────────────────────────────────────

def test_submit_and_status(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("do a thing")
    st = q.get_status(tid)
    assert st["status"] == "pending" and st["goal"] == "do a thing"
    assert q.pending_count() == 1


def test_status_unknown(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    assert q.get_status("nope") is None


def test_priority_order(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    low = q.submit("low", tq.TaskPriority.LOW)
    high = q.submit("high", tq.TaskPriority.HIGH)
    assert q._next_task().task_id == high
    assert low != high


def test_cancel(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("x")
    assert q.cancel(tid)
    assert q.get_status(tid)["status"] == "cancelled"
    assert q.pending_count() == 0
    assert not q.cancel(tid)


def test_cancel_unknown(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    assert not q.cancel("nope")


# ── execution + retries ─────────────────────────────────────────────────────

def test_success_path(monkeypatch):
    ex = FakeExecutor()
    q, _ = make_queue(monkeypatch, ex)
    tid = q.submit("goal")
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert task.status == tq.TaskStatus.COMPLETED
    assert task.result == "done: goal"
    assert q._active_count == 0


def test_transient_error_requeues(monkeypatch):
    ex = FakeExecutor(fail_times=1, error="Connection timeout")
    q, clock = make_queue(monkeypatch, ex, retry_delay=2.0)
    tid = q.submit("goal")
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert task.status == tq.TaskStatus.PENDING
    assert task.attempts == 1
    assert task.next_attempt_at == clock.time() + 2.0
    assert q._retries_total == 1
    assert task in q._queue


def test_permanent_error_fails_fast(monkeypatch):
    ex = FakeExecutor(fail_times=5, error="Unknown tool 'bogus'")
    q, _ = make_queue(monkeypatch, ex)
    tid = q.submit("goal")
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert task.status == tq.TaskStatus.FAILED
    assert task.attempts == 1
    assert q._retries_total == 0


def test_retries_exhausted(monkeypatch):
    ex = FakeExecutor(fail_times=99, error="timeout")
    q, _ = make_queue(monkeypatch, ex, max_retries=2, retry_delay=1.0)
    tid = q.submit("goal")
    task = q._tasks[tid]
    for _ in range(3):
        if task in q._queue:
            q._queue.remove(task)
        q._active_count = 1
        task.next_attempt_at = 0.0
        q._run_task(task)
    assert task.status == tq.TaskStatus.FAILED
    assert task.attempts == 3          # initial + 2 retries


def test_exponential_backoff(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor(), retry_delay=2.0)
    tid = q.submit("g")
    task = q._tasks[tid]
    task.attempts = 1
    assert q._backoff(task) == 2.0
    task.attempts = 2
    assert q._backoff(task) == 4.0
    task.attempts = 3
    assert q._backoff(task) == 8.0


def test_retry_waits_for_backoff(monkeypatch):
    q, clock = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("g")
    q._tasks[tid].next_attempt_at = clock.time() + 10
    assert q._next_task() is None
    clock.t += 11
    assert q._next_task() is not None


def test_healer_rewrites_goal(monkeypatch):
    seen = []

    def healer(goal, error, attempt):
        seen.append((goal, error, attempt))
        return goal + " (retry with fallback)"

    ex = FakeExecutor(fail_times=1, error="timeout")
    q, _ = make_queue(monkeypatch, ex, healer=healer)
    tid = q.submit("original")
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert task.goal == "original (retry with fallback)"
    assert task.history and task.history[0]["from"] == "original"
    assert seen[0][2] == 1


def test_healer_exception_is_safe(monkeypatch):
    def bad(goal, error, attempt):
        raise ValueError("healer broke")

    ex = FakeExecutor(fail_times=1, error="timeout")
    q, _ = make_queue(monkeypatch, ex, healer=bad)
    tid = q.submit("g")
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert task.status == tq.TaskStatus.PENDING     # still retried
    assert task.goal == "g"


def test_cancelled_task_not_retried(monkeypatch):
    ex = FakeExecutor(fail_times=9, error="timeout")
    q, _ = make_queue(monkeypatch, ex)
    tid = q.submit("g")
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    task.cancel_flag.set()
    q._run_task(task)
    assert task.status == tq.TaskStatus.FAILED
    assert q._retries_total == 0


def test_on_complete_callback(monkeypatch):
    got = []
    q, _ = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("g", on_complete=lambda i, r: got.append((i, r)))
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert got and got[0][1] == "done: g"


def test_on_complete_error_is_safe(monkeypatch):
    def bad(i, r):
        raise RuntimeError("callback broke")

    q, _ = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("g", on_complete=bad)
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert task.status == tq.TaskStatus.COMPLETED


# ── manual retry / stats / wait ─────────────────────────────────────────────

def test_manual_retry(monkeypatch):
    ex = FakeExecutor(fail_times=99, error="Unknown tool")
    q, _ = make_queue(monkeypatch, ex)
    tid = q.submit("g")
    task = q._tasks[tid]
    q._queue.remove(task)
    q._active_count = 1
    q._run_task(task)
    assert task.status == tq.TaskStatus.FAILED
    assert q.retry(tid)
    assert task.status == tq.TaskStatus.PENDING and task.attempts == 0
    assert not q.retry("nope")


def test_retry_rejects_running(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("g")
    assert not q.retry(tid)


def test_stats(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor(), max_concurrent=4)
    q.submit("a")
    q.submit("b")
    s = q.get_stats()
    assert s["total"] == 2 and s["queued"] == 2
    assert s["max_concurrent"] == 4
    assert s["by_status"]["pending"] == 2


def test_get_all_statuses(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    q.submit("a")
    assert len(q.get_all_statuses()) == 1


def test_wait_settled(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("g")
    q._tasks[tid].status = tq.TaskStatus.COMPLETED
    assert q.wait(tid, timeout=1)["status"] == "completed"


def test_wait_timeout(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    tid = q.submit("g")
    st = q.wait(tid, timeout=0.2)
    assert st["status"] == "pending"


def test_wait_unknown(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    assert q.wait("nope", timeout=0.1) is None


def test_max_concurrent_respected(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor(), max_concurrent=1)
    q.submit("a")
    q.submit("b")
    first = q._next_task()
    q._active_count = 1
    assert q._next_task() is None
    assert first is not None


# ── real parallelism ────────────────────────────────────────────────────────

def test_real_parallel_execution():
    """Three blocking tasks must run at once with max_concurrent=3."""
    # 3 workers + the main thread all rendezvous here.
    started = threading.Barrier(4, timeout=10)
    release = threading.Event()

    class BlockingExecutor:
        def execute(self, goal, speak=None, cancel_flag=None):
            started.wait()          # all three must arrive together
            release.wait(timeout=10)
            return goal

    q = tq.TaskQueue(max_concurrent=3)
    q._executor = BlockingExecutor()
    q.start()
    try:
        ids = [q.submit(f"task{i}") for i in range(3)]
        started.wait(timeout=10)    # proves 3 ran concurrently
        assert q.get_stats()["active"] == 3
        release.set()
        for tid in ids:
            st = q.wait(tid, timeout=10)
            assert st["status"] == "completed"
    finally:
        release.set()
        q.stop()


def test_control_stats_idle(monkeypatch):
    monkeypatch.setattr(tq, "_queue", None)
    assert "idle" in tq.task_control({"action": "stats"})


def test_control_submit_and_list(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    monkeypatch.setattr(tq, "_queue", q)
    monkeypatch.setattr(tq, "get_queue", lambda: q)
    out = tq.task_control({"action": "submit", "goal": "research quantum", "priority": "high"})
    assert "Queued [" in out and "high" in out
    assert "research quantum" in tq.task_control({"action": "list"})
    assert "1 total" in tq.task_control({"action": "stats"})


def test_control_submit_needs_goal(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    monkeypatch.setattr(tq, "_queue", q)
    monkeypatch.setattr(tq, "get_queue", lambda: q)
    assert "What should the task do" in tq.task_control({"action": "submit"})


def test_control_status_and_unknown(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    monkeypatch.setattr(tq, "_queue", q)
    monkeypatch.setattr(tq, "get_queue", lambda: q)
    tid = q.submit("g")
    assert tid in tq.task_control({"action": "status", "task_id": tid})
    assert "No task with id" in tq.task_control({"action": "status", "task_id": "zzz"})
    assert "Which task" in tq.task_control({"action": "status"})


def test_control_cancel_and_retry(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    monkeypatch.setattr(tq, "_queue", q)
    tid = q.submit("g")
    assert "Cancelled" in tq.task_control({"action": "cancel", "task_id": tid})
    assert "Requeued" in tq.task_control({"action": "retry", "task_id": tid})
    assert "Which task" in tq.task_control({"action": "cancel"})
    assert "Which task" in tq.task_control({"action": "retry"})


def test_control_wait(monkeypatch):
    q, _ = make_queue(monkeypatch, FakeExecutor())
    monkeypatch.setattr(tq, "_queue", q)
    tid = q.submit("g")
    q._tasks[tid].status = tq.TaskStatus.COMPLETED
    q._tasks[tid].result = "all done"
    assert "all done" in tq.task_control({"action": "wait", "task_id": tid})
    assert "Which task" in tq.task_control({"action": "wait"})


def test_control_list_empty(monkeypatch):
    monkeypatch.setattr(tq, "_queue", None)
    assert "No tasks submitted" in tq.task_control({"action": "list"})


def test_control_unknown_action(monkeypatch):
    assert "Unknown task action" in tq.task_control({"action": "zzz"})


def test_serial_when_one_slot():
    """With max_concurrent=1 a second task must not start early."""
    gate = threading.Event()
    seen = []

    class SlowExecutor:
        def execute(self, goal, speak=None, cancel_flag=None):
            seen.append(goal)
            gate.wait(timeout=5)
            return goal

    q = tq.TaskQueue(max_concurrent=1)
    q._executor = SlowExecutor()
    q.start()
    try:
        a = q.submit("first")
        b = q.submit("second")
        deadline = time.time() + 5
        while not seen and time.time() < deadline:
            time.sleep(0.01)
        assert seen == ["first"]
        assert q.get_status(b)["status"] == "pending"
        gate.set()
        q.wait(a, timeout=5)
        q.wait(b, timeout=5)
    finally:
        gate.set()
        q.stop()
