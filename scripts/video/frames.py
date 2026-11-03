"""抽出每段旁白中間(或指定段落結尾前 1 秒)的畫面,檢查影片用:python scripts/video/frames.py <name> [段落id=end ...]"""
import json
import os
import subprocess
import sys
from pathlib import Path

name, opts = sys.argv[1], dict(a.split("=") for a in sys.argv[2:])
work = Path(__file__).resolve().parents[2] / "frontend" / "video-out" / name
env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
base = ["docker", "run", "--rm", "-v", f"{work.as_posix()}:/w", "linuxserver/ffmpeg:7.1.1"]
tl = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
off = -tl["sync"] / 1000  # 成品從對時記號那一格開始(見 build_video.py 的 sync_frame)
(work / "frames").mkdir(exist_ok=True)
for s in tl["segments"]:
    t = (s["end"] / 1000 - 1.0 if opts.get(s["id"]) == "end" else (s["start"] + s["end"]) / 2000) + off
    subprocess.run([*base, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", "/w/final.mp4", "-frames:v", "1",
                    "-vf", "scale=960:-1", f"/w/frames/{s['id']}.png"], env=env)
    print(s["id"], round(t, 1))
