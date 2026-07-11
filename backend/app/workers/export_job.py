"""課表 PDF / PNG 渲染任務(worker;WeasyPrint + poppler,M5-1)。

api 沒有 WeasyPrint 的系統依賴與中文字型,故 PDF/PNG 一律在 worker 產生。
api 端以 `render_export`(阻塞式)派工並取回 bytes。
"""

import os
import subprocess
import tempfile

from app.services.pdf import render_pdf


def render_timetable_pdf(html: str) -> bytes:
    return render_pdf(html)


def render_timetable_png(html: str) -> bytes:
    """先渲成 PDF,再以 poppler 的 pdftoppm 轉單頁 PNG。"""
    pdf = render_pdf(html)
    with tempfile.TemporaryDirectory() as d:
        pdf_path = os.path.join(d, "in.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf)
        out = os.path.join(d, "out")
        subprocess.run(
            ["pdftoppm", "-png", "-r", "150", "-singlefile", pdf_path, out],
            check=True,
        )
        with open(out + ".png", "rb") as f:
            return f.read()
