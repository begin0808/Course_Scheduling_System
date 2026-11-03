"""M5-1:課表匯出。Excel 以讀回比對驗證內容;HTML(PDF 來源)驗中文與版面;
全校總表/批次/RBAC。PDF/PNG 的 worker 渲染於真實環境另行驗證。
"""

import io
import zipfile

import pytest
from openpyxl import load_workbook

from app.models.user import Role
from app.services import timetable_export as tex
from tests.conftest import make_user
from tests.dates import SEM_END, SEM_START  # 日期一律由執行當日推算,不硬編
from tests.test_substitutions import _World

PW = "password123"


@pytest.fixture
def w(env):
    client, db = env
    make_user(db, "s", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 115, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    world = _World(client, db, sid)
    world.teacher("王師", ["國文"])
    world.place("王師", "國文", "701", 0)   # 週三第一節
    world.publish()
    return world


def _cells(ws) -> set[str]:
    out: set[str] = set()
    for row in ws.iter_rows(values_only=True):
        for v in row:
            if v:
                out.add(str(v))
    return out


def _xlsx(resp):
    assert resp.status_code == 200, resp.text
    assert "spreadsheetml" in resp.headers["content-type"]
    return load_workbook(io.BytesIO(resp.content))


# ── 內容一致(Excel 讀回)─────────────────────────────────────
def test_class_excel_matches_grid(w):
    cid = w.classes["701"]
    r = w.client.get(f"/api/export/timetable{w.q}&view=class&target_id={cid}&fmt=xlsx")
    wb = _xlsx(r)
    ws = wb.active
    cells = _cells(ws)
    assert "701 課表" in " ".join(cells) or any("課表" in c for c in cells)
    # 週三第一節有「國文」與「王師」
    joined = "\n".join(cells)
    assert "國文" in joined
    assert "王師" in joined
    assert "週三" in cells  # 表頭星期
    assert "第一節" in cells  # 節次名


def test_teacher_excel_shows_class_not_teacher(w):
    tid = w.teachers["王師"]
    r = w.client.get(f"/api/export/timetable{w.q}&view=teacher&target_id={tid}&fmt=xlsx")
    wb = _xlsx(r)
    joined = "\n".join(_cells(wb.active))
    assert "國文" in joined
    assert "701" in joined       # 教師視角格內顯示班級


def test_room_export_ok_even_without_room(w):
    # 建一個沒有課的場地也應匯出成功(空課表)
    rid = w.client.post(f"/api/rooms{w.q}", json={"name": "101教室"}).json()["id"]
    r = w.client.get(f"/api/export/timetable{w.q}&view=room&target_id={rid}&fmt=xlsx")
    assert r.status_code == 200


# ── HTML(PDF 來源)─────────────────────────────────────────
def test_grid_html_has_chinese_and_layout(w):
    cid = w.classes["701"]
    grid, meta = tex.build_grid(w.db, w.sid, "class", cid)
    html = tex.grid_to_html(grid, meta)
    assert "國文" in html and "王師" in html
    assert "週三" in html and "第一節" in html
    assert "A4 portrait" in html
    assert meta.school_name in html


# ── 全校總表 / 批次 ─────────────────────────────────────────
def test_school_workbook_one_sheet_per_class(w):
    # 學期已有 701 與佔位班 900 → 全校總表每班一分頁
    r = w.client.get(f"/api/export/school.xlsx{w.q}")
    wb = _xlsx(r)
    assert len(wb.sheetnames) >= 2
    assert any("701" in s for s in wb.sheetnames)


def test_batch_zip_has_per_class_files(w):
    r = w.client.get(f"/api/export/batch.zip{w.q}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert any(n.endswith(".xlsx") for n in names)
    assert any("701" in n for n in names)


# ── 邊界 / RBAC ─────────────────────────────────────────────
def test_export_unpublished_semester_404(env):
    client, db = env
    make_user(db, "s2", PW, roles=[Role.scheduler])
    client.post("/api/auth/login", json={"username": "s2", "password": PW})
    sid = client.post("/api/semesters", json={
        "academic_year": 116, "term": 1, "template_key": "junior_high",
        "start_date": SEM_START.isoformat(), "end_date": SEM_END.isoformat(),
    }).json()["id"]
    cid = client.post(f"/api/class-units?semester_id={sid}",
                      json={"grade": 7, "name": "701", "track": "junior_high"}).json()["id"]
    r = client.get(f"/api/export/timetable?semester_id={sid}&view=class&target_id={cid}&fmt=xlsx")
    assert r.status_code == 404


def test_batch_60_classes_under_60s(db):
    """驗收②:60 班批次匯出 < 60 秒(Excel 產生為 CPU-bound,與資料庫無關)。"""
    import time

    from app.models.timetable import Timetable, TimetableStatus
    from tests.fixtures import build_large_school

    fx = build_large_school(db, num_classes=60)
    db.add(Timetable(
        semester_id=fx.semester_id, name="正式課表",
        status=TimetableStatus.published.value))
    db.commit()

    t0 = time.perf_counter()
    data = tex.class_batch_zip(db, fx.semester_id)
    elapsed = time.perf_counter() - t0
    assert elapsed < 60, f"批次匯出耗時 {elapsed:.1f}s"
    z = zipfile.ZipFile(io.BytesIO(data))
    assert len(z.namelist()) == 60


# ── 全校教師課表的總表與批次(使用者回報 #22)──────────────
def test_school_workbook_teacher_view_has_a_sheet_per_teacher(w):
    """每位在職教師一個分頁;沒排到課的也要在(全校發放時不能漏人)。"""
    w.teacher("陳師", ["數學"])      # 有建教師但沒排課
    w.teacher("林師", ["英文"])
    w.client.patch(f"/api/teachers/{w.teachers['林師']}", json={"name": "林師", "is_active": False})

    r = w.client.get(f"/api/export/school.xlsx{w.q}&view=teacher")
    wb = _xlsx(r)
    titles = "|".join(wb.sheetnames)
    assert "王師" in titles and "陳師" in titles      # 有課的、沒課的都在
    assert "林師" not in titles                       # 離職的不列入
    assert len(wb.sheetnames) == 2

    # 內容:王師那張要有他週三第一節的國文
    ws = wb[next(n for n in wb.sheetnames if "王師" in n)]
    assert "國文" in " ".join(_cells(ws))


def test_batch_zip_teacher_view_has_one_file_per_teacher(w):
    w.teacher("陳師", ["數學"])
    r = w.client.get(f"/api/export/batch.zip{w.q}&view=teacher")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert sorted(names) == ["王師.xlsx", "陳師.xlsx"]


def test_school_and_batch_default_to_class_view(w):
    """沒帶 view 時維持原本的班級版(舊的呼叫方式不受影響)。"""
    wb = _xlsx(w.client.get(f"/api/export/school.xlsx{w.q}"))
    assert any("701" in n for n in wb.sheetnames)
    names = zipfile.ZipFile(io.BytesIO(
        w.client.get(f"/api/export/batch.zip{w.q}").content)).namelist()
    assert all("年" in n for n in names)


def test_export_view_param_is_validated(w):
    assert w.client.get(f"/api/export/school.xlsx{w.q}&view=room").status_code == 422


def test_teacher_can_export_single_but_not_batch(w):
    make_user(w.db, "t", PW, roles=[Role.teacher])
    w.client.post("/api/auth/logout")
    w.client.post("/api/auth/login", json={"username": "t", "password": PW})
    cid = w.classes["701"]
    single = w.client.get(f"/api/export/timetable{w.q}&view=class&target_id={cid}&fmt=xlsx")
    assert single.status_code == 200          # 單一課表全校可查可匯出
    assert w.client.get(f"/api/export/school.xlsx{w.q}").status_code == 403
    assert w.client.get(f"/api/export/batch.zip{w.q}").status_code == 403


# ── 批次 PDF / 全校總表 PDF(LINE 社群組長,v1.4.6)──────────────
# 真正的渲染在 worker(WeasyPrint + poppler),此處以替身取代,驗 api 的組合;
# 實際 PDF 由 e2e 在完整環境下載驗證。
@pytest.fixture
def fake_render(monkeypatch):
    from app.workers import queue as job_queue

    calls: list[tuple[list[str], bool]] = []

    def render(htmls, *, split, timeout=None):
        calls.append((htmls, split))
        if split:
            return [f"%PDF-{i}".encode() for i in range(len(htmls))]
        return [b"%PDF-merged"]

    monkeypatch.setattr(job_queue, "render_export_set", render)
    return calls


def test_batch_zip_pdf_has_one_pdf_per_class(w, fake_render):
    r = w.client.get(f"/api/export/batch.zip{w.q}&fmt=pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "PDF" in r.headers["content-disposition"]          # 和 Excel 版的檔名分得開
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert names and all(n.endswith(".pdf") for n in names)
    assert any("701" in n for n in names)
    htmls, split = fake_render[0]
    assert split is True and len(htmls) == len(names)          # 一次派工,不是一張一張派
    # 檔名與內容順序一致:701 那一檔就是 701 的課表
    i = next(i for i, n in enumerate(names) if "701" in n)
    assert "701" in htmls[i] and z.read(names[i]) == f"%PDF-{i}".encode()


def test_batch_zip_pdf_teacher_view(w, fake_render):
    w.teacher("陳師", ["數學"])
    r = w.client.get(f"/api/export/batch.zip{w.q}&view=teacher&fmt=pdf")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert sorted(names) == ["王師.pdf", "陳師.pdf"]


def test_school_pdf_is_one_file(w, fake_render):
    r = w.client.get(f"/api/export/school.pdf{w.q}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-merged"
    htmls, split = fake_render[0]
    assert split is False and len(htmls) >= 2                  # 701 與佔位班,一班一頁
    r = w.client.get(f"/api/export/school.pdf{w.q}&view=teacher")
    assert r.status_code == 200
    assert "%E5%85%A8%E6%A0%A1%E6%95%99%E5%B8%AB" in r.headers["content-disposition"]  # 全校教師


def test_batch_zip_defaults_to_excel_and_validates_fmt(w, fake_render):
    names = zipfile.ZipFile(io.BytesIO(
        w.client.get(f"/api/export/batch.zip{w.q}").content)).namelist()
    assert all(n.endswith(".xlsx") for n in names)
    assert fake_render == []                                   # Excel 不經 worker
    assert w.client.get(f"/api/export/batch.zip{w.q}&fmt=png").status_code == 422


def test_batch_pdf_reports_worker_failure(w, monkeypatch):
    from app.workers import queue as job_queue

    def boom(htmls, *, split, timeout=None):
        raise job_queue.RenderError("課表PDF渲染失敗:背景忙碌或逾時,請稍後再試")

    monkeypatch.setattr(job_queue, "render_export_set", boom)
    r = w.client.get(f"/api/export/batch.zip{w.q}&fmt=pdf")
    assert r.status_code == 502 and "渲染失敗" in r.json()["detail"]
    assert w.client.get(f"/api/export/school.pdf{w.q}").status_code == 502


def test_batch_pdf_without_teachers_says_why(w, fake_render):
    w.client.patch(f"/api/teachers/{w.teachers['王師']}", json={"name": "王師", "is_active": False})
    r = w.client.get(f"/api/export/school.pdf{w.q}&view=teacher")
    assert r.status_code == 404 and "沒有在職教師" in r.json()["detail"]


def test_teacher_cannot_batch_pdf(w, fake_render):
    make_user(w.db, "t2", PW, roles=[Role.teacher])
    w.client.post("/api/auth/logout")
    w.client.post("/api/auth/login", json={"username": "t2", "password": PW})
    assert w.client.get(f"/api/export/school.pdf{w.q}").status_code == 403
    assert w.client.get(f"/api/export/batch.zip{w.q}&fmt=pdf").status_code == 403


def test_same_name_teachers_get_distinct_files(w):
    w.teacher("陳師", ["數學"])
    w.teacher("陳師", ["英文"])           # 同名教師是允許的(以身分末四碼辨識)
    names = zipfile.ZipFile(io.BytesIO(
        w.client.get(f"/api/export/batch.zip{w.q}&view=teacher").content)).namelist()
    assert sorted(names) == ["王師.xlsx", "陳師(2).xlsx", "陳師.xlsx"]
