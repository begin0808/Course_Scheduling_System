"""停課日 schema(v1.4.19)。"""

from datetime import date

from pydantic import BaseModel, Field

_Date = date


class SuspensionIn(BaseModel):
    start_date: date
    end_date: _Date
    whole_school: bool = True
    # 不是全校時的班級(年級在畫面上一次勾整個年級的班)
    class_ids: list[int] = Field(default_factory=list)
    all_day: bool = True
    from_ordinal: int | None = Field(default=None, ge=1, le=20)   # 第幾節(只數一般課)
    to_ordinal: int | None = Field(default=None, ge=1, le=20)
    reason: str = Field(default="", max_length=64)


class SuspensionOut(BaseModel):
    id: int
    start_date: _Date
    end_date: _Date
    whole_school: bool
    class_ids: list[int]
    all_day: bool
    from_ordinal: int | None = None
    to_ordinal: int | None = None
    reason: str
    target_text: str      # 「全校」「七年級」「801、802」
    period_text: str      # 「整天」「第 5~7 節」
    created_by_name: str = ""


class SuspensionSaved(BaseModel):
    item: SuspensionOut
    # 停課時段裡已經安排好的請假節次、調課補課、代導;組長要自己撤回或改成「不處理」
    conflicts: list[str] = Field(default_factory=list)
