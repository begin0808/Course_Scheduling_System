"""全校教師週總表匯出 Excel(v1.4.14)。

學校原本就是用 Excel 手做這張表,匯出後可以直接再改、再印。一週一個分頁:
老師為欄、日期 × 節次為列;異動用字色與刪除線標示(與列印頁相同)。
已設成 A3 橫向、縮成一頁寬,並固定標題列與左邊兩欄,捲動時看得到是誰、哪一節。
"""

import io
from datetime import timedelta

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.services.teacher_week_sheets import (
    COVER,
    OFF,
    PENDING,
    SWAP,
    Item,
    TeacherWeekSheets,
    Week,
)

_WEEKDAYS = "一二三四五六日"
_THIN = Side(style="thin", color="000000")
_MEDIUM = Side(style="medium", color="000000")
_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

_COLOR = {OFF: "808080", PENDING: "C05800", COVER: "1F4FD8", SWAP: "D00000"}


def _rich(items: list[Item]) -> CellRichText | str | None:
    if not items:
        return None
    parts: list[str | TextBlock] = []
    for i, item in enumerate(items):
        if i:
            parts.append("\n")
        color = _COLOR.get(item.kind)
        struck = item.kind in (OFF, PENDING)
        if color is None:
            parts.append(item.text)
        else:
            parts.append(TextBlock(InlineFont(color=color, strike=struck or None), item.text))
        if item.note:
            note_color = color or "000000"
            parts.append(TextBlock(InlineFont(color=note_color, sz=9), f"\n{item.note}"))
    return CellRichText(parts)


def _lines(items: list[Item]) -> int:
    return sum(2 if x.note else 1 for x in items)


def _write_week(ws: Worksheet, sheets: TeacherWeekSheets, week: Week) -> None:
    n = len(sheets.teachers)
    last_col = n + 2
    sunday = week.monday + timedelta(days=6)
    heading = (f"{sheets.title}教師週總表　"
               f"{week.monday.month}/{week.monday.day}~{sunday.month}/{sunday.day}")
    ws.cell(row=1, column=1, value=heading).font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(last_col, 3))
    ws.cell(row=2, column=1, value=sheets.legend).font = Font(size=10)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(last_col, 3))
    ws.row_dimensions[1].height = 24

    ws.cell(row=3, column=1, value="星期")
    ws.cell(row=3, column=2, value="節次")
    for k, t in enumerate(sheets.teachers):
        ws.cell(row=3, column=3 + k, value=f"{t.name}\n{t.role}" if t.role else t.name)
    for c in range(1, last_col + 1):
        cell = ws.cell(row=3, column=c)
        cell.alignment = _CENTER
        cell.font = Font(bold=True)
        cell.border = Border(left=_THIN, right=_THIN, top=_MEDIUM, bottom=_MEDIUM)
    ws.row_dimensions[3].height = 32

    r = 4
    i = 0
    rows = week.rows
    while i < len(rows):
        day = rows[i].date
        j = i
        while j < len(rows) and rows[j].date == day:
            j += 1
        first = r
        for row in rows[i:j]:
            ws.cell(row=r, column=2, value=row.ordinal)
            for k, items in enumerate(row.cells):
                ws.cell(row=r, column=3 + k, value=_rich(items))
            lines = max([_lines(items) for items in row.cells] + [1])
            ws.row_dimensions[r].height = max(20, 14 * lines)
            for c in range(1, last_col + 1):
                cell = ws.cell(row=r, column=c)
                cell.alignment = _CENTER
                cell.border = Border(
                    left=_THIN, right=_THIN, bottom=_THIN,
                    top=_MEDIUM if r == first else _THIN)
            r += 1
        ws.cell(row=first, column=1,
                value=f"{day.month}/{day.day}\n({_WEEKDAYS[day.isoweekday() - 1]})")
        ws.merge_cells(start_row=first, start_column=1, end_row=r - 1, end_column=1)
        i = j

    ws.column_dimensions["A"].width = 7
    ws.column_dimensions["B"].width = 5
    for k in range(n):
        ws.column_dimensions[get_column_letter(3 + k)].width = 11
    ws.freeze_panes = "C4"
    ws.print_title_rows = "3:3"
    ws.print_title_cols = "A:B"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.3
    ws.page_margins.top = ws.page_margins.bottom = 0.4


def to_xlsx(sheets: TeacherWeekSheets) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for week in sheets.weeks:
        ws = wb.create_sheet(f"{week.monday.month}-{week.monday.day}週")
        _write_week(ws, sheets, week)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
