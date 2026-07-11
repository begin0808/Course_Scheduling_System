"""HTML → PDF(WeasyPrint,M5-0 基礎;M5-1 課表匯出建立於此)。

WeasyPrint 的系統依賴(Pango/Cairo)與中文內嵌字型只裝在 **worker** 映像;
匯出一律走背景任務。故 `weasyprint` 為延遲匯入——api 匯入本模組不會失敗,
只有真正呼叫 `render_pdf`(在 worker)才需要那些依賴。
"""


def render_pdf(html: str, *, base_url: str | None = None) -> bytes:
    """把 HTML 字串渲染成 PDF bytes。中文由映像內嵌的 Noto CJK 字型呈現。"""
    from weasyprint import HTML  # 延遲匯入:見模組說明

    return HTML(string=html, base_url=base_url).write_pdf()
