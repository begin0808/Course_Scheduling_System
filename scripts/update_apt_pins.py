"""更新 backend/Dockerfile 裡釘住的 Debian 套件版本(v1.7.0)。

為什麼要釘版本:數發部源碼檢測把 `apt-get install curl`(沒寫版本)列為「未固定相依版本」。
代價是 Debian 釋出安全更新後,舊版本會從套件庫移除,建置就會失敗。發版前執行這支:

    python scripts/update_apt_pins.py           # 只列出哪些套件有新版本
    python scripts/update_apt_pins.py --write   # 直接改寫 Dockerfile

做法:用 Dockerfile 的基底映像(FROM)各開一個 amd64、arm64 容器查 apt 的候選版本;
兩個架構版本不同時停下來(正式映像兩個架構都要建得起來),不會改寫。
需要 Docker;arm64 靠 Docker Desktop 內建的模擬執行,第一次會比較慢。
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parent.parent / "backend" / "Dockerfile"
PIN = re.compile(r"^(?P<indent>\s+)(?P<pkg>[a-z0-9][a-z0-9.+-]*)=(?P<ver>\S+)(?P<tail>\s*\\?)$")
PLATFORMS = ("linux/amd64", "linux/arm64")


def pinned(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        m = PIN.match(line)
        if m:
            found[m["pkg"]] = m["ver"]
    return found


def base_image(text: str) -> str:
    m = re.search(r"^FROM\s+(\S+)", text, re.MULTILINE)
    if not m:
        sys.exit("找不到 Dockerfile 的 FROM")
    return m.group(1)


def candidates(image: str, platform: str, pkgs: list[str]) -> dict[str, str]:
    script = (
        "apt-get update -qq >/dev/null 2>&1 && "
        'for p in "$@"; do printf "%s %s\\n" "$p" '
        "\"$(apt-cache policy \"$p\" | awk '/Candidate/{print $2}')\"; done"
    )
    out = subprocess.run(
        ["docker", "run", "--rm", "--platform", platform, image, "sh", "-c", script, "sh", *pkgs],
        check=True, capture_output=True, text=True,
    ).stdout
    return dict(line.split(" ", 1) for line in out.strip().splitlines())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="把新版本寫回 Dockerfile")
    args = parser.parse_args()

    text = DOCKERFILE.read_text(encoding="utf-8")
    pins = pinned(text)
    image = base_image(text)
    print(f"基底映像 {image},釘住 {len(pins)} 個套件")
    subprocess.run(["docker", "pull", "-q", image], check=True, capture_output=True)

    per_platform = {p: candidates(image, p, sorted(pins)) for p in PLATFORMS}
    latest: dict[str, str] = {}
    mismatch = False
    for pkg in sorted(pins):
        versions = {p: per_platform[p].get(pkg, "") for p in PLATFORMS}
        if len(set(versions.values())) != 1 or "(none)" in versions.values():
            mismatch = True
            print(f"  ! {pkg}:兩個架構的版本不同或找不到 {versions}")
            continue
        latest[pkg] = next(iter(versions.values()))
        mark = "" if latest[pkg] == pins[pkg] else f"  ← 目前 {pins[pkg]}"
        print(f"  {pkg}={latest[pkg]}{mark}")

    changed = {k: v for k, v in latest.items() if v != pins[k]}
    if mismatch:
        sys.exit("有套件兩個架構版本不同,沒有改寫;請人工確認。")
    if not changed:
        print("全部都是最新版本。")
        return
    if not args.write:
        print(f"有 {len(changed)} 個套件可更新;加 --write 改寫 Dockerfile。")
        return

    def repl(m: re.Match[str]) -> str:
        ver = changed.get(m["pkg"], m["ver"])
        return f"{m['indent']}{m['pkg']}={ver}{m['tail']}"

    lines = [PIN.sub(repl, line) for line in text.split("\n")]
    DOCKERFILE.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"已更新 {len(changed)} 個套件:{'、'.join(sorted(changed))}")


if __name__ == "__main__":
    main()
