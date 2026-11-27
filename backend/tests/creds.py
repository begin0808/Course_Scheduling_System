"""測試用密碼:一律在執行時隨機產生,程式碼裡不寫死任何密碼字串(v1.7.1,數發部源碼檢測)。

- `PW`:大多數測試帳號共用的密碼,每次跑測試都不同。
- `random_password(n)`:另外需要一組不同的密碼時用(改密碼、錯誤密碼等);
  n 小於系統最低長度(8)時可以拿來測「密碼太短」。
"""

import secrets
import string

_ALPHABET = string.ascii_letters + string.digits


def random_password(length: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


PW = random_password()
