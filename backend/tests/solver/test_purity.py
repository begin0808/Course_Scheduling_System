"""M3-1 驗收③:solver 套件不得依賴 ORM 或 Web 層。

引擎必須能獨立測試、獨立跑在 worker 容器,且不被 SQLAlchemy 的 lazy loading 拖垮。
以 AST 靜態掃描取代 import-linter(少一個 dev 依賴,規則也更明確)。
"""

import ast
from pathlib import Path

import app.solver

SOLVER_DIR = Path(app.solver.__file__).parent

# solver 只能 import 標準函式庫與自己
FORBIDDEN_PREFIXES = ("app.models", "app.api", "app.services", "app.core", "sqlalchemy", "fastapi")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_solver_imports_neither_orm_nor_web():
    offenders: list[str] = []
    for path in sorted(SOLVER_DIR.glob("*.py")):
        for module in _imported_modules(path):
            if module.startswith(FORBIDDEN_PREFIXES):
                offenders.append(f"{path.name} → {module}")
    assert not offenders, f"solver 不得 import 這些模組:{offenders}"


def test_solver_only_imports_itself_within_app():
    for path in sorted(SOLVER_DIR.glob("*.py")):
        for module in _imported_modules(path):
            if module.startswith("app.") and not module.startswith("app.solver"):
                raise AssertionError(f"{path.name} import 了 {module}")
