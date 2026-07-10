"""自動排課任務的進度與控制狀態。

進度不放在 RQ 的 job meta 裡:RQ 只知道「執行中/失敗」,說不出「已找到 12 個解、
目前目標值 148」。這裡用一個獨立的 Redis hash 承載,worker 寫、API 讀。

**心跳**:worker 每 tick 更新 `heartbeat`。若 API 讀到 `running` 但心跳超過
`STALE_SECONDS` 沒更新,即判定 worker 已死——前端得到明確錯誤,而不是永遠轉圈。
"""

import enum
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

from redis import Redis

KEY_PREFIX = "solve:"
TTL_SECONDS = 24 * 60 * 60
STALE_SECONDS = 30.0  # 心跳逾時;worker 的 tick 為 2 秒
QUEUED_STALE_SECONDS = 15 * 60.0  # 排隊等待另一個任務時不算失敗


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    finished = "finished"
    failed = "failed"
    cancelled = "cancelled"


class ControlAction(enum.StrEnum):
    stop = "stop"      # 提前結束,保留當下最佳解
    cancel = "cancel"  # 取消,丟棄結果


@dataclass
class JobState:
    job_id: str
    status: str
    semester_id: int
    source_timetable_id: int
    source_name: str
    max_seconds: float
    heartbeat: float = field(default_factory=time.time)
    elapsed: float = 0.0
    solutions: int = 0
    objective: float | None = None
    result_timetable_id: int | None = None
    result_name: str | None = None
    error: str | None = None
    report: dict | None = None

    @property
    def done(self) -> bool:
        return self.status in (JobStatus.finished, JobStatus.failed, JobStatus.cancelled)


class ProgressStore(Protocol):
    def create(self, state: JobState) -> None: ...
    def get(self, job_id: str) -> JobState | None: ...
    def update(self, job_id: str, **fields: object) -> None: ...
    def request(self, job_id: str, action: ControlAction) -> None: ...
    def requested(self, job_id: str) -> ControlAction | None: ...


def _encode(value: object) -> str:
    return json.dumps(value)


def _decode(raw: bytes | str) -> object:
    return json.loads(raw)


class RedisProgressStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, job_id: str) -> str:
        return f"{KEY_PREFIX}{job_id}"

    def _control_key(self, job_id: str) -> str:
        return f"{KEY_PREFIX}{job_id}:control"

    def create(self, state: JobState) -> None:
        key = self._key(state.job_id)
        self._redis.hset(key, mapping={k: _encode(v) for k, v in asdict(state).items()})
        self._redis.expire(key, TTL_SECONDS)

    def get(self, job_id: str) -> JobState | None:
        raw = self._redis.hgetall(self._key(job_id))
        if not raw:
            return None
        fields = {
            (k.decode() if isinstance(k, bytes) else k): _decode(v) for k, v in raw.items()
        }
        return JobState(**fields)  # type: ignore[arg-type]

    def update(self, job_id: str, **fields: object) -> None:
        key = self._key(job_id)
        if not self._redis.exists(key):
            return
        self._redis.hset(key, mapping={k: _encode(v) for k, v in fields.items()})
        self._redis.expire(key, TTL_SECONDS)

    def request(self, job_id: str, action: ControlAction) -> None:
        self._redis.set(self._control_key(job_id), action.value, ex=TTL_SECONDS)

    def requested(self, job_id: str) -> ControlAction | None:
        raw = self._redis.get(self._control_key(job_id))
        if raw is None:
            return None
        value = raw.decode() if isinstance(raw, bytes) else str(raw)
        return ControlAction(value)


class InMemoryProgressStore:
    """測試用。與 Redis 版行為一致,但不需要外部服務。"""

    def __init__(self) -> None:
        self.states: dict[str, JobState] = {}
        self.controls: dict[str, ControlAction] = {}

    def create(self, state: JobState) -> None:
        self.states[state.job_id] = state

    def get(self, job_id: str) -> JobState | None:
        return self.states.get(job_id)

    def update(self, job_id: str, **fields: object) -> None:
        state = self.states.get(job_id)
        if state is None:
            return
        for key, value in fields.items():
            setattr(state, key, value)

    def request(self, job_id: str, action: ControlAction) -> None:
        self.controls[job_id] = action

    def requested(self, job_id: str) -> ControlAction | None:
        return self.controls.get(job_id)


def is_stale(state: JobState, now: float | None = None) -> bool:
    """worker 是否已失聯。排隊中的任務可能只是在等前一個排課跑完,給長一點的寬限。"""
    now = now if now is not None else time.time()
    if state.done:
        return False
    limit = QUEUED_STALE_SECONDS if state.status == JobStatus.queued else STALE_SECONDS
    return now - state.heartbeat > limit
