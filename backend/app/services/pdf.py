"""HTML → PDF(WeasyPrint,M5-0 基礎;M5-1 課表匯出建立於此)。

WeasyPrint 的系統依賴(Pango/Cairo)與中文內嵌字型只裝在 **worker** 映像;
匯出一律走背景任務。故 `weasyprint` 為延遲匯入——api 匯入本模組不會失敗,
只有真正呼叫 `render_pdf`(在 worker)才需要那些依賴。
"""


def render_pdf(html: str, *, base_url: str | None = None) -> bytes:
    """把 HTML 字串渲染成 PDF bytes。中文由映像內嵌的 Noto CJK 字型呈現。"""
    from weasyprint import HTML  # 延遲匯入:見模組說明

    return HTML(string=html, base_url=base_url).write_pdf()


def render_pdf_set(htmls: list[str], *, split: bool) -> list[bytes]:
    """多張課表一次渲染成 PDF(批次 PDF,v1.4.6)。

    中文字型(Noto CJK)每寫一次 PDF 就要子集化、嵌入一次,單張約 4 秒;逐張渲染的話,
    全校 48 位老師要三分多鐘。改為每張各自排版(很快),併成一份**只寫一次**,48 張約 10 秒。

    split=False 回 `[合併檔]`(全校一份,每張課表從新的一頁開始);
    split=True 再依每張的頁數用 poppler 切開,回每張一檔(順序與 htmls 相同)。
    """
    import os
    import subprocess
    import tempfile

    from weasyprint import HTML  # 延遲匯入:見模組說明

    if not htmls:
        return []
    docs = [HTML(string=h).render() for h in htmls]
    merged = docs[0].copy([p for d in docs for p in d.pages]).write_pdf()
    if not split:
        return [merged]
    out: list[bytes] = []
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "all.pdf")
        with open(src, "wb") as f:
            f.write(merged)
        subprocess.run(["pdfseparate", src, os.path.join(tmp, "p-%d.pdf")], check=True)
        start = 1
        for d in docs:
            files = [os.path.join(tmp, f"p-{i}.pdf") for i in range(start, start + len(d.pages))]
            path = files[0]
            if len(files) > 1:   # 一張課表超過一頁(節次很多)時,把它的幾頁併回一檔
                path = os.path.join(tmp, f"u-{start}.pdf")
                subprocess.run(["pdfunite", *files, path], check=True)
            with open(path, "rb") as f:
                out.append(f.read())
            start += len(d.pages)
    return out
