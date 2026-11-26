"""產生「源碼檢測用」的程式碼壓縮檔(v1.7.0,數發部公共程式平臺上架審查用)。

只打包會進入正式映像、或部署時會用到的檔案;測試程式、開發工具、文件、CI 設定排除,
並在壓縮檔裡附上 SCAN_EXCLUSIONS.md,逐項說明排除了什麼、為什麼。

    python scripts/make_scan_bundle.py v1.7.0             # 從版本標籤打包
    python scripts/make_scan_bundle.py v1.7.0 --verify    # 另外用解開的內容實際建置三個映像

內容一律取自 git 的版本標籤(git archive),不會混入工作目錄裡沒提交的檔案,
所以任何人用同一個標籤都能產生相同內容。輸出放在 dist-scan/(已列入 .gitignore)。
"""

import argparse
import fnmatch
import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dist-scan"

# (樣式, 說明)。樣式以 / 結尾代表整個資料夾;其他用 fnmatch 比對完整路徑。
EXCLUDES: list[tuple[str, str]] = [
    ("backend/tests/", "後端自動化測試(pytest)。只在開發與 CI 執行;"
     "backend/.dockerignore 排除 tests/,正式映像不含。測試資料裡的帳號密碼都是假的;"
     "建立端對端測試帳號的 seed_e2e.py 也在這裡,由開發者從主機送進測試用容器執行。"),
    ("frontend/e2e/", "前端端對端測試(Playwright)與手冊截圖、示範影片的錄製腳本。"
     "只在開發與 CI 執行,不會建置進網頁。"),
    ("frontend/src/**.test.ts", "前端單元測試(Vitest)。vite build 不會打包 *.test.ts。"),
    ("frontend/playwright.config.ts", "端對端測試的設定檔。"),
    ("frontend/eslint.config.js", "程式碼風格檢查(ESLint)的設定檔,開發工具。"),
    ("frontend/*.tsbuildinfo", "TypeScript 編譯快取,非原始碼。"),
    ("frontend/Dockerfile.dev", "開發用前端容器(熱重載),正式部署不使用。"),
    ("docker-compose.dev.yml", "開發用的容器編排設定,正式部署使用 docker-compose.yml。"),
    ("scripts/", "開發者工具:產生使用手冊、製作操作示範影片、更新套件版本、產生本壓縮檔。"
     "只在開發者電腦上執行,不在正式映像裡。"),
    ("docs/", "使用手冊與部署文件(HTML/Markdown),不含執行程式。"),
    (".github/", "GitHub Actions 的 CI 設定。測試用資料庫的密碼每次執行隨機產生,與正式部署無關。"),
    (".pre-commit-config.yaml", "提交前的程式碼檢查設定,開發工具。"),
]


def excluded_by(path: str) -> str | None:
    for pattern, _ in EXCLUDES:
        if pattern.endswith("/"):
            if path.startswith(pattern):
                return pattern
        elif "**" in pattern:
            head, tail = pattern.split("**", 1)
            if path.startswith(head) and fnmatch.fnmatch(path.rsplit("/", 1)[-1], "*" + tail):
                return pattern
        elif fnmatch.fnmatch(path, pattern):
            return pattern
    return None


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def exclusions_doc(ref: str, sha: str, kept: int, counts: dict[str, int]) -> str:
    rows = "\n".join(
        f"| `{p}` | {counts.get(p, 0)} | {why} |" for p, why in EXCLUDES if counts.get(p, 0)
    )
    return f"""# 檢測用程式碼:排除清單與說明

- 專案:排課與調代課系統(https://github.com/begin0808/Course_Scheduling_System)
- 版本:{ref}(commit `{sha}`)
- 授權:AGPL-3.0-only
- 本壓縮檔包含 {kept} 個檔案,由 `python scripts/make_scan_bundle.py {ref}` 從版本標籤產生;
  同一個標籤重新產生的內容相同,可與 GitHub 上的原始碼逐檔核對。

## 包含的內容

正式部署會用到的全部檔案:

- `backend/`:後端 API 與背景工作程式(Python)、資料庫結構遷移、Dockerfile 與進入點
- `frontend/`:前端網頁原始碼(Vue/TypeScript)、`package.json` 與 `package-lock.json`(第三方元件清單)、
  `stubs/`(以 npm overrides 取代未使用的間接相依)
- `Dockerfile.web`、`web-entrypoint.sh`、`Caddyfile`:網頁伺服器映像
- `docker-compose.yml`、`docker-compose.limits.yml`、`.env.example`:部署設定
- `install.sh`、`install.ps1`:一鍵安裝程式
- `LICENSE`、`README.md`、`SECURITY.md`、`THIRD-PARTY-NOTICES.md`、`CHANGELOG.md` 等說明文件

## 排除的內容

以下檔案只用於開發與測試,不會進入學校部署的正式映像,也不會在學校主機上執行:

| 路徑 | 檔案數 | 說明 |
|---|---|---|
{rows}

## 驗證

排除後的內容可以獨立建置出全部三個正式映像(api、worker、web),
產生時以 `--verify` 實際建置確認過。
"""


def build_bundle(ref: str) -> Path:
    sha = git("rev-parse", f"{ref}^{{commit}}").decode().strip()
    tar_bytes = git("archive", "--format=tar", sha)
    counts: dict[str, int] = {}
    kept: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            hit = excluded_by(member.name)
            if hit:
                counts[hit] = counts.get(hit, 0) + 1
                continue
            f = tar.extractfile(member)
            assert f is not None
            kept.append((member, f.read()))

    OUT_DIR.mkdir(exist_ok=True)
    name = f"Course_Scheduling_System-{ref}-scan"
    out = OUT_DIR / f"{name}.zip"
    # 固定時間戳與順序,同一個標籤每次產生的壓縮檔內容一致
    stamp = (2020, 1, 1, 0, 0, 0)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for member, data in sorted(kept, key=lambda x: x[0].name):
            info = zipfile.ZipInfo(f"{name}/{member.name}", stamp)
            info.external_attr = (member.mode & 0o777 | 0o100000) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        doc = exclusions_doc(ref, sha, len(kept), counts)
        info = zipfile.ZipInfo(f"{name}/SCAN_EXCLUSIONS.md", stamp)
        info.external_attr = 0o100644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, doc.encode("utf-8"))

    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    print(f"版本 {ref}(commit {sha[:12]})")
    print(f"包含 {len(kept)} 個檔案;排除:")
    for pattern, _ in EXCLUDES:
        if counts.get(pattern):
            print(f"  {pattern}  {counts[pattern]} 個")
    print(f"輸出:{out}")
    print(f"SHA-256:{digest}")
    return out


def verify(bundle: Path) -> None:
    """解開壓縮檔,用裡面的內容實際建置三個正式映像。"""
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(bundle) as z:
            z.extractall(tmp)
        src = next(Path(tmp).iterdir())
        builds = [
            ("api", ["-f", "backend/Dockerfile", "--target", "base", "backend"]),
            ("worker", ["-f", "backend/Dockerfile", "--target", "worker", "backend"]),
            ("web", ["-f", "Dockerfile.web", "."]),
        ]
        for label, args in builds:
            print(f"建置 {label} 映像...", flush=True)
            r = subprocess.run(
                ["docker", "build", "-q", "-t", f"cs-scan-verify:{label}", *args],
                cwd=src, capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(r.stderr[-3000:], file=sys.stderr)
                sys.exit(f"{label} 映像建置失敗")
            print(f"  {label} 建置成功")
    print("三個映像都能用壓縮檔的內容建置。")


def main() -> None:
    parser = argparse.ArgumentParser(description="產生源碼檢測用的程式碼壓縮檔")
    parser.add_argument("ref", help="版本標籤或 commit,例如 v1.7.0")
    parser.add_argument("--verify", action="store_true", help="用解開的內容實際建置三個映像")
    args = parser.parse_args()
    bundle = build_bundle(args.ref)
    if args.verify:
        verify(bundle)


if __name__ == "__main__":
    main()
