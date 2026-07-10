"""OR-Tools CP-SAT 排課引擎(architecture.md §3)。

**架構規則(以 tests/solver/test_purity.py 強制):**
本套件不得 import `app.models` / `app.api` / `app.services`,也不得 import SQLAlchemy。
引擎只認得 `problem.py` 的純 dataclass;DB → Problem 的轉換在 `app.services.solver_data`。

- `problem.py`     問題描述(節次、教師、班級、場地、配課)與時段重疊判定(D7)
- `preflight.py`   排課前的必要條件檢查(§3.4),攔掉多數資料錯誤
- `model_builder.py`     CP-SAT 硬約束建模(M3-2)
- `conflict_explainer.py` 無解時的衝突定位(M3-5)
"""
