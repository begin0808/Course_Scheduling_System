"""一筆調課裡「換人上」的每一格(v1.4.20,三角調課時抽出來共用)。

- 兩人互調:兩格。甲請假那節由乙上;乙原本那節(`swap_*`)由甲回來上。
- 三角調課:三格。甲請假那節由乙上;乙原本那節(`tri_*`)由丙上;
  丙原本那節(`swap_*`)由甲回來上。

巡堂表、週課表、教師週總表、調課單、調代課紀錄、停課衝突都從這裡取,
不要各自用 `swap_*` / `tri_*` 拼——三角調課每一格的「原本是誰、誰來上、上什麼」都不一樣。

**科目怎麼寫**(與調課單相同):同班互調時科目跟著老師走(學生只是幾科前後對換);
跨班對調時去的是別人的班、上的是那一節原本的課。三角調課只限同一班,一律跟著老師走。

**back** 是「來上的這位老師自己空出來的那一節」:調課單、教師週總表的
[調月/日_星期節次] 記號指向它(乙的記號指向乙原本那節,以此類推)。
"""

from dataclasses import dataclass
from datetime import date as _Date

from app.models.leave import AffectedPeriod
from app.models.substitution import Substitution, SubstitutionType


@dataclass(frozen=True, slots=True)
class Slot:
    """課表上的某一天某一節(快照):請假那一節以配課記,其他以課表格子記。"""

    date: _Date
    period_no: int
    period_name: str
    class_names: str
    subject_name: str
    entry_id: int | None = None
    assignment_id: int | None = None


@dataclass(frozen=True, slots=True)
class Leg:
    date: _Date
    period_no: int
    period_name: str
    entry_id: int | None         # 課表格子;請假那一節為 None(以配課比對)
    assignment_id: int | None    # 請假那一節的配課;其他格為 None(要時由 entry 取)
    class_names: str
    subject_name: str            # 這一格原本的科目
    owner_id: int | None         # 課表上原本的老師
    owner_name: str
    teacher_id: int | None       # 實際來上的老師
    teacher_name: str
    subject_taught: str          # 實際上的科目
    back: Slot | None            # 來上的老師自己空出來的那一節
    absent_slot: bool = False    # 是請假(或調課未請假)的那一節

    # 給呼叫端少寫一層
    @property
    def back_date(self) -> _Date | None:
        return self.back.date if self.back else None

    @property
    def back_period_no(self) -> int | None:
        return self.back.period_no if self.back else None

    @property
    def back_period_name(self) -> str:
        return self.back.period_name if self.back else ""

    @property
    def back_entry_id(self) -> int | None:
        return self.back.entry_id if self.back else None

    @property
    def back_assignment_id(self) -> int | None:
        return self.back.assignment_id if self.back else None

    @property
    def back_class_names(self) -> str:
        return self.back.class_names if self.back else ""

    @property
    def back_subject_name(self) -> str:
        return self.back.subject_name if self.back else ""


def _name(t) -> str:
    return t.name if t is not None else ""


def _leg(slot: Slot, owner, teacher, subject_taught: str, back: Slot | None,
         absent_slot: bool = False) -> Leg:
    return Leg(
        date=slot.date, period_no=slot.period_no, period_name=slot.period_name,
        entry_id=slot.entry_id, assignment_id=slot.assignment_id,
        class_names=slot.class_names, subject_name=slot.subject_name,
        owner_id=owner.id if owner is not None else None, owner_name=_name(owner),
        teacher_id=teacher.id if teacher is not None else None, teacher_name=_name(teacher),
        subject_taught=subject_taught, back=back, absent_slot=absent_slot,
    )


def legs(ap: AffectedPeriod, sub: Substitution) -> list[Leg]:
    """這筆調課換人上的每一格,第一格一定是請假那一節。

    補課那一節資料不完整(對調的課被刪除)時只回請假那一格,back 為空。
    """
    if sub.type != SubstitutionType.swap.value:
        return []
    absent = ap.leave_request.teacher
    handler = sub.handler
    x = Slot(ap.date, ap.period_no, ap.period_name, ap.class_names, ap.subject_name,
             assignment_id=ap.course_assignment_id)
    z = None
    if sub.swap_date is not None and sub.swap_period_no is not None:
        z = Slot(sub.swap_date, sub.swap_period_no, sub.swap_period_name,
                 sub.swap_class_names, sub.swap_subject_name, entry_id=sub.swap_entry_id)

    if sub.tri_teacher_id is not None and sub.tri_date is not None \
            and sub.tri_period_no is not None:
        third = sub.tri_teacher
        y = Slot(sub.tri_date, sub.tri_period_no, sub.tri_period_name,
                 sub.tri_class_names, sub.tri_subject_name, entry_id=sub.tri_entry_id)
        out = [
            _leg(x, absent, handler, y.subject_name, y, absent_slot=True),
            _leg(y, handler, third, z.subject_name if z else "", z),
        ]
        if z is not None:
            out.append(_leg(z, third, absent, x.subject_name, x))
        return out

    if z is None:
        return [_leg(x, absent, handler, x.subject_name, None, absent_slot=True)]
    same_class = x.class_names == z.class_names
    return [
        _leg(x, absent, handler, (z.subject_name or x.subject_name) if same_class
             else x.subject_name, z, absent_slot=True),
        _leg(z, handler, absent, (x.subject_name or z.subject_name) if same_class
             else z.subject_name, x),
    ]


def slot_text(day: _Date, period_name: str) -> str:
    """「11/20 第三節」。"""
    return f"{day.month}/{day.day} {period_name}".strip()


def partner_text(ap: AffectedPeriod, sub: Substitution, leg: Leg) -> str:
    """週課表那一格的補充說明:互調寫「與 11/20 第三節對調」;三角調課寫「另兩節 …」。"""
    if sub.is_triangle:
        others = [slot_text(x.date, x.period_name) for x in legs(ap, sub)
                  if (x.date, x.period_no, x.absent_slot)
                  != (leg.date, leg.period_no, leg.absent_slot)]
        return f"另兩節 {'、'.join(others)}"
    if leg.back is None:
        return ""
    return f"與 {slot_text(leg.back.date, leg.back.period_name)}對調"
