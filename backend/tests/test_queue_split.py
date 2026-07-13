"""M6-2:背景任務佇列拆分(default = 排課 / ops = 匯出、備份、還原、寄信、定時)。

驗的是「派工去了正確的佇列」與「升級不會讓每日備份靜默斷裂」——真正的隔離效果
(排課進行中匯出仍秒回)必須在 docker 全棧實測,單元測試證不了。
"""

import pytest
from rq.registry import ScheduledJobRegistry

from app.workers import queue as q
from app.workers import scheduler as sched
from app.workers import worker as worker_mod


class _FakeQueue:
    """記下 enqueue 到哪條佇列、派了什麼函式。"""

    def __init__(self, name):
        self.name = name
        self.calls: list[str] = []

    def _record(self, func):
        self.calls.append(getattr(func, "__name__", str(func)))
        return _FakeJob()

    def enqueue(self, func, *a, **k):
        return self._record(func)

    def enqueue_in(self, _delta, func, **k):
        return self._record(func)

    def enqueue_at(self, _when, func, **k):
        return self._record(func)


class _FakeJob:
    def latest_result(self):
        return None

    def cancel(self):
        pass


@pytest.fixture
def queues(monkeypatch):
    default, ops = _FakeQueue("default"), _FakeQueue("ops")
    for mod in (q, sched):
        monkeypatch.setattr(mod, "default_queue", default, raising=False)
        monkeypatch.setattr(mod, "ops_queue", ops, raising=False)
    return default, ops


# ── 派工路由 ─────────────────────────────────────────────────
def test_auto_schedule_goes_to_default(queues):
    default, ops = queues
    q.enqueue_solve("job-1", 1, 60.0, 1, None, "u")
    assert default.calls == ["run_auto_schedule"]
    assert ops.calls == [], "排課絕不能進 ops:它一跑數分鐘,會把匯出/備份全堵住"


def test_email_goes_to_ops(queues):
    default, ops = queues
    q.enqueue_email("a@b.c", "主旨", "內文")
    assert (ops.calls, default.calls) == (["send_notification_email"], [])


@pytest.mark.parametrize(("call", "error", "expected"), [
    (lambda: q.render_export("<html></html>", "png", timeout=1), q.RenderError,
     "render_timetable_png"),
    (lambda: q.run_backup("manual", timeout=1), q.BackupJobError, "create_backup_job"),
    (lambda: q.run_restore("x.dump", timeout=1), q.BackupJobError, "restore_job"),
])
def test_blocking_ops_work_goes_to_ops_queue(queues, call, error, expected):
    """匯出/備份/還原一律走 ops——正是排課那幾分鐘裡組長會按的東西。

    這些是阻塞式派工,假佇列不會回結果,必然以逾時作收;此處只在意「派去哪條佇列」。
    """
    default, ops = queues
    with pytest.raises(error):
        call()
    assert (ops.calls, default.calls) == ([expected], [])


def test_scheduled_jobs_go_to_ops(queues):
    """定時任務(每日備份、心跳)是維運工作,排進 ops;排課 worker 不跑排程器。"""
    _default, ops = queues
    sched.schedule_daily_backup()
    sched._schedule_next()
    assert ops.calls == ["daily_backup_job", "heartbeat"]


# ── worker 進入點 ────────────────────────────────────────────
def test_worker_defaults_to_the_solve_queue_without_scheduler(monkeypatch):
    started: dict = {}

    class _W:
        def __init__(self, queues, connection):
            started["queues"] = [x.name for x in queues]

        def work(self, with_scheduler):
            started["scheduler"] = with_scheduler

    monkeypatch.setattr(worker_mod, "Worker", _W)
    monkeypatch.setattr(worker_mod, "ensure_scheduled", lambda: started.setdefault("ensured", True))

    worker_mod.main([])
    assert started["queues"] == ["default"]
    # 排課 worker 一忙就是好幾分鐘,不該負責「準時」的事
    assert started["scheduler"] is False
    assert "ensured" not in started


def test_ops_worker_runs_the_scheduler(monkeypatch):
    started: dict = {}

    class _W:
        def __init__(self, queues, connection):
            started["queues"] = [x.name for x in queues]

        def work(self, with_scheduler):
            started["scheduler"] = with_scheduler

    monkeypatch.setattr(worker_mod, "Worker", _W)
    monkeypatch.setattr(worker_mod, "ensure_scheduled", lambda: started.setdefault("ensured", True))

    worker_mod.main(["ops"])
    assert started["queues"] == ["ops"]
    assert started["scheduler"] is True
    assert started["ensured"] is True


def test_worker_rejects_an_unknown_queue_name(monkeypatch):
    monkeypatch.setattr(worker_mod, "Worker", lambda *a, **k: pytest.fail("不該走到這"))
    with pytest.raises(SystemExit, match="未知的佇列名稱"):
        worker_mod.main(["solver"])


# ── 升級路徑:舊版排在 default 的定時任務要清掉 ───────────────
def test_legacy_default_schedules_are_dropped_on_upgrade(monkeypatch):
    """M6-2 之前每日備份排在 default;排程器改看 ops 後,舊的那筆再也沒人撈——
    不清掉的話備份鏈就靜默斷了(而備份最怕的正是靜默斷裂)。"""
    removed: list[str] = []

    class _Registry:
        def __init__(self, queue):
            self.queue = queue

        def get_job_ids(self):
            if self.queue.name == "default":
                return [sched.HEARTBEAT_JOB_ID, sched.DAILY_BACKUP_JOB_ID, "some-other-job"]
            return []

        def remove(self, job_id, delete_job=False):
            removed.append(job_id)

    default, ops = _FakeQueue("default"), _FakeQueue("ops")
    monkeypatch.setattr(sched, "default_queue", default)
    monkeypatch.setattr(sched, "ops_queue", ops)
    monkeypatch.setattr(sched, "ScheduledJobRegistry", _Registry)

    sched.ensure_scheduled()

    assert removed == [sched.HEARTBEAT_JOB_ID, sched.DAILY_BACKUP_JOB_ID]
    assert "some-other-job" not in removed, "只動自己的固定 job_id,別人的排程不碰"
    # 清完之後,兩個定時任務在 ops 上重新排好
    assert ops.calls == ["heartbeat", "daily_backup_job"]


def test_registry_helper_is_wired_to_the_real_rq_registry():
    """避免上面的假 Registry 把真實接線測沒了。"""
    assert sched.ScheduledJobRegistry is ScheduledJobRegistry
