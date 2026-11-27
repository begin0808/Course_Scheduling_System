"""抽出每段旁白中間(或指定段落結尾前 1 秒)的畫面,檢查影片用。

用法:python scripts/video/frames.py <name> [--end 段落id ...]
(v1.7.1 起改用 argparse,影片名稱只能是已有成品資料夾的;先前直接讀 sys.argv 組指令。)
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "video-out"
NAMES = sorted(p.name for p in OUT_DIR.iterdir() if p.is_dir()) if OUT_DIR.is_dir() else []

ap = argparse.ArgumentParser()
ap.add_argument("name", choices=NAMES)
ap.add_argument("--end", nargs="*", default=[], help="改抽這些段落結尾前 1 秒的畫面")
a = ap.parse_args()

os.environ["MSYS_NO_PATHCONV"] = "1"  # 從 Git Bash 執行時,別把 /w 這類容器路徑轉成 Windows 路徑
work = OUT_DIR / a.name
base = ["docker", "run", "--rm", "-v", f"{work.as_posix()}:/w", "linuxserver/ffmpeg:7.1.1"]
tl = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
off = -tl["sync"] / 1000  # 成品從對時記號那一格開始(見 build_video.py 的 sync_frame)
(work / "frames").mkdir(exist_ok=True)
for s in tl["segments"]:
    t = (s["end"] / 1000 - 1.0 if s["id"] in a.end else (s["start"] + s["end"]) / 2000) + off
    subprocess.run([*base, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", "/w/final.mp4",
                    "-frames:v", "1", "-vf", "scale=960:-1", f"/w/frames/{s['id']}.png"])
    print(s["id"], round(t, 1))
