"""輕量欄位驗證工具(不引入 email-validator 依賴)。"""

import re

# 務實的 Email 格式檢查:本地部分@網域.頂級,不含空白;不追求 RFC 5322 完整性
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))
