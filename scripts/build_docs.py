#!/usr/bin/env python3
"""把 docs/ 下的 Markdown 文件轉成可直接用瀏覽器開的 HTML。

用意:部署手冊的讀者常常是在校內主機或機房、沒有網路的情況下讀文件。
.md 在 GitHub 網頁上看是排版好的,但把資料夾複製到本機後就只是一坨純文字;
產出的 .html 則是雙擊就開、離線可讀、附側邊目錄與深/淺色切換。

**產出的 .html 一律不要手動編輯**——改 .md 之後重跑本腳本即可。

用法:
    pip install markdown
    python scripts/build_docs.py            # 產生 / 更新全部 HTML
    python scripts/build_docs.py --check    # 只檢查是否與 .md 同步(CI 用,不寫檔)

新增一份文件時,把它加進下方 GROUPS 即可。
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import unicodedata
from pathlib import Path

try:
    import markdown
except ModuleNotFoundError:
    sys.exit("需要 markdown 套件,請先執行:pip install markdown")

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
GITHUB_BLOB = "https://github.com/begin0808/Course_Scheduling_System/blob/main/docs/"

# 側邊欄的文件清單。(相對 docs/ 的 .md 路徑, 側邊欄顯示的短標題)
GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "部署與維運手冊",
        [
            ("deploy/README.md", "總覽:從哪開始"),
            ("deploy/install.md", "安裝指南"),
            ("deploy/upgrade.md", "升級指南"),
            ("deploy/backup.md", "備份與還原"),
            ("deploy/https.md", "網域與 HTTPS"),
            ("deploy/faq.md", "常見問題 FAQ"),
        ],
    ),
    (
        "專案技術文件",
        [
            ("architecture.md", "架構設計"),
            ("roadmap.md", "路線圖"),
            ("tasks.md", "開發任務卡"),
        ],
    ),
]

# 這兩份是給開發者的規格與開發日誌,在側邊欄標示出來,免得一般使用者誤入
DEV_DOCS = {"architecture.md", "roadmap.md", "tasks.md"}

CSS = """
  :root{
    --bg:#faf6f0; --surface:#fffdfa; --surface-2:#f4ece2; --surface-3:#ebe0d3;
    --text:#241b14; --text-soft:#5c4c3f; --text-faint:#8d7a6a;
    --border:#e5d8c8; --border-strong:#d3c1ad;
    --accent:#b4531f; --accent-2:#8a3d13; --accent-soft:#fbeade; --accent-line:#e8bd99;
    --good:#5a7d2a; --warn:#9c6008; --warn-soft:#fdefd6; --danger:#b1362b; --danger-soft:#fbe3df;
    --info:#3d6485; --info-soft:#e9eef3;
    --font-sans:"PingFang TC","Microsoft JhengHei","Noto Sans TC",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --font-serif:"Noto Serif TC","Songti TC","Source Han Serif TC",Georgia,serif;
    --font-mono:"SF Mono","Cascadia Code","Consolas","Courier New",monospace;
    --maxw:800px;
  }
  @media (prefers-color-scheme:dark){
    :root:not([data-theme="light"]){
      --bg:#16110d; --surface:#1e1813; --surface-2:#29211a; --surface-3:#342a21;
      --text:#f0e7dd; --text-soft:#bcaa9a; --text-faint:#96826f;
      --border:#3b2f25; --border-strong:#4d3e31;
      --accent:#f0864a; --accent-2:#f7a877; --accent-soft:#37200f; --accent-line:#5c3a20;
      --good:#8fbf5c; --warn:#e0a53c; --warn-soft:#33260f; --danger:#ef8172; --danger-soft:#351c18;
      --info:#86a9cf; --info-soft:#1c242e;
    }
  }
  :root[data-theme="dark"]{
    --bg:#16110d; --surface:#1e1813; --surface-2:#29211a; --surface-3:#342a21;
    --text:#f0e7dd; --text-soft:#bcaa9a; --text-faint:#96826f;
    --border:#3b2f25; --border-strong:#4d3e31;
    --accent:#f0864a; --accent-2:#f7a877; --accent-soft:#37200f; --accent-line:#5c3a20;
    --good:#8fbf5c; --warn:#e0a53c; --warn-soft:#33260f; --danger:#ef8172; --danger-soft:#351c18;
    --info:#86a9cf; --info-soft:#1c242e;
  }

  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:var(--font-sans);
    line-height:1.78;font-size:16px;-webkit-font-smoothing:antialiased;letter-spacing:.01em}
  a{color:var(--accent);text-decoration:none}
  a:hover{text-decoration:underline}
  :focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}

  .shell{display:grid;grid-template-columns:292px minmax(0,1fr);max-width:1240px;margin:0 auto}

  /* ── sidebar ── */
  .side{position:sticky;top:0;align-self:start;height:100vh;overflow-y:auto;padding:26px 18px 40px;
    border-right:1px solid var(--border)}
  .brand{display:block;margin-bottom:4px}
  .brand .mark{font-family:var(--font-serif);font-weight:700;font-size:1.1rem;color:var(--accent);
    display:block}
  .brand .sub{font-size:.7rem;color:var(--text-faint);letter-spacing:.14em}
  .side .grp{margin-top:20px;font-size:.7rem;letter-spacing:.16em;color:var(--text-faint);
    text-transform:uppercase;font-family:var(--font-mono);padding:0 8px 6px}
  .side nav{display:flex;flex-direction:column;gap:1px}
  .side nav a{display:block;padding:6px 10px;border-radius:7px;color:var(--text-soft);
    font-size:.88rem;transition:background .15s,color .15s}
  .side nav a:hover{background:var(--surface-2);text-decoration:none;color:var(--text)}
  .side nav a.here{background:var(--accent-soft);color:var(--accent-2);font-weight:600}
  .side nav a .dev{font-size:.66rem;color:var(--text-faint);font-family:var(--font-mono);
    margin-left:6px;letter-spacing:.04em}

  /* 本頁目錄 */
  .side .toc{margin-top:6px;display:flex;flex-direction:column;gap:0;
    border-left:1px solid var(--border);padding-left:2px}
  .side .toc a{font-size:.82rem;padding:4px 10px;color:var(--text-soft);border-radius:0 6px 6px 0}
  .side .toc a.lv3{padding-left:24px;font-size:.78rem;color:var(--text-faint)}
  .side .toc a:hover{background:var(--surface-2);color:var(--text);text-decoration:none}
  .side .toc a.on{color:var(--accent-2);font-weight:600;box-shadow:inset 2px 0 0 var(--accent)}

  .theme-btn{margin-top:22px;width:100%;padding:8px;border:1px solid var(--border);
    background:var(--surface);color:var(--text-soft);border-radius:8px;cursor:pointer;
    font-size:.8rem;font-family:var(--font-sans)}
  .theme-btn:hover{border-color:var(--accent);color:var(--accent)}

  /* ── main ── */
  main{padding:0 clamp(20px,5vw,60px) 110px;min-width:0}
  .wrap{max-width:var(--maxw);margin:0 auto}

  .head{padding:52px 0 22px;border-bottom:1px solid var(--border);margin-bottom:8px}
  .eyebrow{font-family:var(--font-mono);font-size:.72rem;letter-spacing:.2em;text-transform:uppercase;
    color:var(--accent);margin-bottom:14px}
  h1{font-family:var(--font-serif);font-weight:700;font-size:clamp(1.8rem,4.4vw,2.5rem);line-height:1.22;
    margin:0;text-wrap:balance;letter-spacing:.01em}
  .src{margin-top:16px;font-size:.78rem;color:var(--text-faint)}
  .src code{font-size:.9em}

  h2{font-family:var(--font-serif);font-size:1.55rem;font-weight:700;margin:52px 0 12px;line-height:1.3;
    padding-bottom:8px;border-bottom:1px solid var(--border);text-wrap:balance;scroll-margin-top:16px}
  h3{font-size:1.12rem;font-weight:700;margin:34px 0 10px;letter-spacing:.01em;
    padding-left:12px;border-left:3px solid var(--accent);scroll-margin-top:16px}
  h4{font-size:1rem;font-weight:700;margin:24px 0 8px;color:var(--text);scroll-margin-top:16px}
  p{margin:14px 0}
  strong{font-weight:700;color:var(--text)}
  ul,ol{margin:14px 0;padding-left:1.4em}
  li{margin:6px 0}
  li > ul,li > ol{margin:6px 0}
  hr{border:none;border-top:1px solid var(--border);margin:34px 0}

  code{font-family:var(--font-mono);font-size:.86em;background:var(--surface-2);
    padding:2px 6px;border-radius:5px;color:var(--accent-2);word-break:break-word}
  pre{background:var(--surface-2);border:1px solid var(--border);border-radius:10px;
    padding:14px 16px;overflow-x:auto;margin:18px 0;line-height:1.6}
  pre code{background:none;padding:0;color:var(--text);font-size:.85rem;white-space:pre}

  blockquote{margin:20px 0;padding:12px 18px;border:1px solid var(--border);border-left:4px solid var(--accent);
    border-radius:10px;background:var(--accent-soft);color:var(--text-soft);font-size:.95rem}
  blockquote p{margin:6px 0}
  blockquote strong{color:var(--accent-2)}

  .tw{overflow-x:auto;margin:20px 0;border:1px solid var(--border);border-radius:10px}
  table{border-collapse:collapse;width:100%;font-size:.9rem;min-width:440px}
  th,td{text-align:left;padding:10px 14px;border-bottom:1px solid var(--border);vertical-align:top}
  thead th{background:var(--surface-2);font-weight:700;font-size:.8rem;letter-spacing:.03em;
    color:var(--text-soft);white-space:nowrap}
  tbody tr:last-child td{border-bottom:none}
  td code{white-space:nowrap}

  /* tasks.md 的任務卡核取方塊 */
  .tick{display:inline-block;width:1.15em;margin-right:.35em;font-family:var(--font-mono);font-weight:700}
  .tick.done{color:var(--good)}
  .tick.wip{color:var(--warn)}
  .tick.todo{color:var(--text-faint)}

  .foot{margin-top:70px;padding-top:24px;border-top:1px solid var(--border);color:var(--text-faint);
    font-size:.83rem}
  .foot a{color:var(--text-soft)}

  .navtoggle{display:none}
  @media (max-width:960px){
    .shell{grid-template-columns:1fr}
    .side{position:fixed;z-index:40;top:0;left:0;width:284px;transform:translateX(-100%);
      transition:transform .22s ease;background:var(--surface);height:100vh}
    .side.open{transform:none;box-shadow:0 0 40px rgba(0,0,0,.34)}
    .navtoggle{display:flex;position:fixed;z-index:50;top:14px;left:14px;gap:8px;align-items:center;
      background:var(--surface);border:1px solid var(--border-strong);border-radius:9px;padding:8px 13px;
      cursor:pointer;font-family:var(--font-sans);color:var(--text);font-size:.85rem;font-weight:600}
    .scrim{display:none;position:fixed;inset:0;z-index:39;background:rgba(0,0,0,.45)}
    .scrim.on{display:block}
    .head{padding-top:56px}
  }
  @media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
  @media print{.side,.navtoggle,.scrim{display:none}.shell{grid-template-columns:1fr}
    main{padding:0}pre,blockquote,.tw{break-inside:avoid}}
  html{scroll-behavior:smooth}
"""

JS = """
  (function(){
    var root=document.documentElement, btn=document.getElementById('themeBtn');
    // 跨頁記住深/淺色:讀者在部署手冊裡是會一頁一頁翻的
    try{var s=localStorage.getItem('csDocsTheme'); if(s)root.setAttribute('data-theme',s);}catch(e){}
    function cur(){var d=root.getAttribute('data-theme');if(d)return d;
      return matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';}
    btn.addEventListener('click',function(){
      var next=cur()==='dark'?'light':'dark';
      root.setAttribute('data-theme',next);
      try{localStorage.setItem('csDocsTheme',next);}catch(e){}
    });

    var side=document.getElementById('side'), scrim=document.getElementById('scrim'),
        tog=document.getElementById('navToggle');
    function close(){side.classList.remove('open');scrim.classList.remove('on');}
    tog.addEventListener('click',function(){side.classList.toggle('open');scrim.classList.toggle('on');});
    scrim.addEventListener('click',close);

    var links=Array.prototype.slice.call(document.querySelectorAll('.toc a'));
    links.forEach(function(a){a.addEventListener('click',function(){
      if(window.innerWidth<=960)close();});});
    var secs=links.map(function(a){return document.getElementById(
      decodeURIComponent(a.getAttribute('href').slice(1)));});
    function spy(){
      var best=-1;
      for(var i=0;i<secs.length;i++){
        if(secs[i]&&secs[i].getBoundingClientRect().top<=120)best=i;
      }
      links.forEach(function(a,i){a.classList.toggle('on',i===best);});
    }
    addEventListener('scroll',spy,{passive:true});spy();
  })();
"""


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# tasks.md 用 `### [x] M0-1 …` 在標題上標任務狀態
TICKS = {" ": ("todo", "☐"), "~": ("wip", "◐"), "x": ("done", "☑")}
TICK_RE = re.compile(r"^\[([ ~x])\]\s*")


def slugify(value: str, separator: str) -> str:
    """產生保留中文的錨點,規則比照 GitHub,好處是同一個 #錨點 在 .md 與 .html 都通。

    python-markdown 內建的 slugify 會把非 ASCII 全部丟掉,中文標題會退化成
    #_1、#_2 這種序號——一旦中間插入新章節,所有既有連結就全歪掉。
    """
    value = TICK_RE.sub("", value.strip())
    value = unicodedata.normalize("NFKC", value).lower()
    value = re.sub(r"[^\w\s-]", "", value)  # \w 在 unicode 模式下含中日韓
    return re.sub(r"\s+", separator, value.strip())


def md_to_html(text: str) -> tuple[str, str, list]:
    """回傳 (標題, 內文 HTML, TOC tokens)。第一個 # 標題抽出來當頁首,不重複出現在內文。"""
    lines = text.splitlines()
    title = ""
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            lines = lines[i + 1:]
            break
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"],
        extension_configs={"toc": {"permalink": False, "slugify": slugify}},
    )
    body = md.convert("\n".join(lines).strip())
    return title, body, md.toc_tokens


def rewrite_links(html: str) -> str:
    """把指向 .md 的相對連結改指向產生出來的 .html。外部連結不動。"""

    def sub(m: re.Match) -> str:
        href = m.group(1)
        if href.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)
        return 'href="%s"' % re.sub(r"\.md(?=$|#)", ".html", href)

    return re.sub(r'href="([^"]*)"', sub, html)


def wrap_tables(html: str) -> str:
    """表格包一層可橫向捲動的容器,窄螢幕才不會把整頁撐開。"""
    return html.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")


def render_ticks(html: str) -> str:
    """tasks.md 標題與清單上的 [ ] / [~] / [x] 任務狀態改成有顏色的記號。"""

    def sub(m: re.Match) -> str:
        cls, glyph = TICKS[m.group(2)]
        return '%s<span class="tick %s">%s</span> ' % (m.group(1), cls, glyph)

    return re.sub(r"(<(?:li|h[2-4])\b[^>]*>)\[([ ~x])\]\s*", sub, html)


def build_toc(tokens: list, out: list | None = None) -> list:
    """攤平 h2 / h3 當側邊目錄;h1 已抽成頁首,更深的層級略過免得目錄爆長。"""
    out = [] if out is None else out
    for t in tokens:
        if t["level"] in (2, 3):
            name = t["name"]
            mark = TICK_RE.match(name)
            out.append((t["level"], t["id"], TICK_RE.sub("", name), mark.group(1) if mark else None))
        if t["level"] < 3:
            build_toc(t["children"], out)
    return out


def link_to(target: str, current: str) -> str:
    """從 current 這一頁連到 target(兩者皆為相對 docs/ 的路徑)。"""
    return posixpath.relpath(target, posixpath.dirname(current)) or target


def nav_html(current: str) -> str:
    home = link_to("index.html", current)
    parts = [
        '<a class="brand" href="%s">'
        '<span class="mark">排課與調代課系統</span>'
        '<span class="sub">文件</span></a>' % home,
        '<div class="grp">給使用者</div><nav>',
        '<a href="%s">教學組長操作手冊</a>' % home,
        "</nav>",
    ]
    for group, items in GROUPS:
        parts.append('<div class="grp">%s</div><nav>' % esc(group))
        for rel, label in items:
            here = " here" if rel == current else ""
            dev = '<span class="dev">開發用</span>' if rel in DEV_DOCS else ""
            parts.append(
                '<a class="doc%s" href="%s">%s%s</a>'
                % (here, link_to(rel.replace(".md", ".html"), current), esc(label), dev)
            )
        parts.append("</nav>")
    return "\n".join(parts)


def toc_html(toc: list) -> str:
    if not toc:
        return ""
    rows = []
    for lv, tid, name, mark in toc:
        tick = ""
        if mark is not None:
            cls, glyph = TICKS[mark]
            tick = '<span class="tick %s">%s</span>' % (cls, glyph)
        rows.append(
            '<a class="%s" href="#%s">%s%s</a>'
            % ("lv3" if lv == 3 else "lv2", tid, tick, esc(name))
        )
    return '<div class="grp">本頁目錄</div><div class="toc">%s</div>' % "".join(rows)


PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{desc}">
<title>{title} · 排課與調代課系統</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='88'>{icon}</text></svg>">
<!-- 本檔由 scripts/build_docs.py 從 docs/{src} 自動產生,請勿直接編輯。 -->
<style>{css}</style>
</head>
<body>
<button class="navtoggle" id="navToggle" aria-label="開啟目錄">☰ 目錄</button>
<div class="scrim" id="scrim"></div>
<div class="shell">
  <aside class="side" id="side">
{nav}
{toc}
    <button class="theme-btn" id="themeBtn">◐ 切換深色 / 淺色</button>
  </aside>
  <main>
    <div class="wrap">
      <header class="head">
        <div class="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <div class="src">原始檔 <code>docs/{src}</code> · <a href="{blob}">在 GitHub 上檢視</a></div>
      </header>
{body}
      <div class="foot">
        本頁由 <code>docs/{src}</code> 自動產生(<code>scripts/build_docs.py</code>)。
        要修改內容請改 Markdown 原始檔,不要直接編輯這份 HTML。<br>
        排課與調代課系統 · MIT 授權 · <a href="https://github.com/begin0808/Course_Scheduling_System">GitHub</a>
      </div>
    </div>
  </main>
</div>
<script>{js}</script>
</body>
</html>
"""


def render(rel: str) -> str:
    src = DOCS / rel
    title, body, tokens = md_to_html(src.read_text(encoding="utf-8"))
    body = render_ticks(wrap_tables(rewrite_links(body)))
    body = "\n".join("      " + ln for ln in body.splitlines())
    dev = rel in DEV_DOCS
    return PAGE.format(
        title=esc(title),
        desc=esc("%s — 排課與調代課系統%s文件" % (title, "開發" if dev else "部署與維運")),
        icon="🛠" if dev else "📗",
        eyebrow="DEVELOPER DOCS" if dev else "DEPLOYMENT GUIDE",
        css=CSS,
        js=JS,
        nav=nav_html(rel),
        toc=toc_html(build_toc(tokens)),
        body=body,
        src=rel,
        blob=GITHUB_BLOB + rel,
    )


def main() -> int:
    # Windows 主控台預設 cp950,印中文與 ✓ 會炸掉
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="把 docs/ 的 Markdown 轉成 HTML")
    ap.add_argument("--check", action="store_true", help="只檢查是否同步,不寫檔(CI 用)")
    args = ap.parse_args()

    stale, written = [], []
    for _, items in GROUPS:
        for rel, _ in items:
            out = DOCS / rel.replace(".md", ".html")
            html = render(rel)
            if args.check:
                if not out.exists() or out.read_text(encoding="utf-8") != html:
                    stale.append(rel)
            else:
                if not out.exists() or out.read_text(encoding="utf-8") != html:
                    out.write_text(html, encoding="utf-8", newline="\n")
                    written.append(out.relative_to(REPO).as_posix())

    if args.check:
        if stale:
            print("以下文件的 HTML 未與 Markdown 同步:")
            for rel in stale:
                print("  - docs/%s" % rel)
            print("\n請執行 python scripts/build_docs.py 後一併提交。")
            return 1
        print("docs HTML 與 Markdown 同步 ✓")
        return 0

    print("更新 %d 份(共 %d 份)" % (len(written), sum(len(i) for _, i in GROUPS)))
    for w in written:
        print("  ✓ " + w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
