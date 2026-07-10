"""ORM models 匯總。

新增 model 時在此 import,Alembic 的 autogenerate 與 env.py 才能偵測到 metadata。
"""

from app.models.assignment import (
    AssignmentTeacher,
    BlockRule,
    CourseAssignment,
    SchedulingUnit,
    SchedulingUnitMember,
    SchedulingUnitType,
)
from app.models.audit import AuditLog
from app.models.basedata import (
    ClassTrack,
    ClassUnit,
    Room,
    RoomType,
    Subject,
    Teacher,
    TeacherRuleType,
    TeacherTimeRule,
)
from app.models.constraint import ConstraintConfig
from app.models.leave import (
    LEAVE_TYPE_CN,
    AffectedPeriod,
    AffectedStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
)
from app.models.notification import Notification, NotificationType
from app.models.period import Period, PeriodTable, PeriodType
from app.models.semester import Semester, SemesterStatus
from app.models.substitution import (
    SUBSTITUTION_TYPE_CN,
    Substitution,
    SubstitutionType,
)
from app.models.timetable import ScheduleEntry, Timetable, TimetableStatus
from app.models.user import Role, User, UserRole
from app.models.wizard import WizardState

__all__ = [
    "Role",
    "User",
    "UserRole",
    "Semester",
    "SemesterStatus",
    "PeriodTable",
    "Period",
    "PeriodType",
    "Subject",
    "Teacher",
    "TeacherTimeRule",
    "TeacherRuleType",
    "Room",
    "RoomType",
    "ClassUnit",
    "ClassTrack",
    "WizardState",
    "SchedulingUnit",
    "SchedulingUnitMember",
    "SchedulingUnitType",
    "CourseAssignment",
    "AssignmentTeacher",
    "BlockRule",
    "Timetable",
    "ScheduleEntry",
    "TimetableStatus",
    "AuditLog",
    "ConstraintConfig",
    "LeaveRequest",
    "LeaveType",
    "LeaveStatus",
    "AffectedPeriod",
    "AffectedStatus",
    "LEAVE_TYPE_CN",
    "Notification",
    "NotificationType",
    "Substitution",
    "SubstitutionType",
    "SUBSTITUTION_TYPE_CN",
]
