"""產生操作示範影片:旁白語音 → 自動錄影 → 合成 MP4(含燒入字幕)與 .srt。

用法(在專案根目錄):
    python scripts/video/build_video.py leave-substitute [--base http://localhost:8120] [--out <資料夾>]

成品預設放在 docs/影片/(.gitignore 已排除,不進版本庫)。

需要:
  - pip install edge-tts(微軟 Edge 線上語音;非官方介面,服務若變動再換別種)
  - Docker(用 linuxserver/ffmpeg 映像量長度與合成,電腦不必另裝 ffmpeg)
  - 一個全新的示範站(同 manual-shots:docker compose -p manual,ADMIN_PASSWORD=DemoSetup2026!)

講稿在 frontend/e2e/video/<name>.json(text 是字幕,say 是念法,沒寫就念 text);
錄影腳本在 frontend/e2e/video/<name>.video.ts。
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
FFMPEG_IMAGE = "linuxserver/ffmpeg:7.1.1"
FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
SUB_MAX = 22          # 一行字幕最多幾個字
SUB_FONT = "Microsoft JhengHei"
FULLWIDTH = str.maketrans({",": "，", ";": "；", ":": "：", "!": "！", "?": "？"})  # 字幕用全形標點


def docker(args: list[str], work: Path, entry: str = "ffmpeg") -> str:
    cmd = ["docker", "run", "--rm", "--entrypoint", entry,
           "-v", f"{work.as_posix()}:/w", "-v", f"{FONTS_DIR.as_posix()}:/fonts:ro",
           FFMPEG_IMAGE, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "MSYS_NO_PATHCONV": "1"})
    if r.returncode != 0:
        sys.exit(f"ffmpeg 失敗:\n{r.stderr[-3000:]}")
    return r.stdout


def duration(work: Path, name: str) -> float:
    out = docker(["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f"/w/{name}"],
                 work, entry="ffprobe")
    return float(out.strip())


# ── 1. 旁白語音 ──────────────────────────────────────────────
async def tts(script: dict, work: Path) -> None:
    import edge_tts

    voice, rate = script.get("voice", "zh-TW-HsiaoChenNeural"), script.get("rate", "+0%")
    for seg in script["segments"]:
        comm = edge_tts.Communicate(seg.get("say", seg["text"]), voice, rate=rate)
        sentences = []
        with open(work / f"{seg['id']}.mp3", "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
                    sentences.append({"type": chunk["type"], "offset": chunk["offset"] / 1e7,
                                      "duration": chunk["duration"] / 1e7, "text": chunk["text"]})
        (work / f"{seg['id']}.boundaries.json").write_text(
            json.dumps(sentences, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  語音 {seg['id']}")


# ── 2. 字幕 ─────────────────────────────────────────────────
def chunks(text: str) -> list[str]:
    """把一段旁白切成一行一行的字幕:先依句號分句,太長再依逗號、分號切。"""
    out: list[str] = []
    for sent in [s for s in re.split(r"(?<=[。!?])", text) if s.strip()]:
        if len(sent) <= SUB_MAX:
            out.append(sent)
            continue
        line = ""
        for part in [p for p in re.split(r"(?<=[,;:、])", sent) if p]:
            if line and len(line) + len(part) > SUB_MAX:
                out.append(line)
                line = ""
            line += part
        if line:
            out.append(line)
    return [c.strip() for c in out]


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_srt(script: dict, starts: dict[str, float], durs: dict[str, float]) -> str:
    """每段的字幕依字數比例分配這段語音的時間(標點處停頓也算進去)。"""
    lines, n = [], 1
    for seg in script["segments"]:
        parts = chunks(seg["text"])
        weight = [len(re.sub(r"[「」]", "", p)) + 2 for p in parts]
        total, t = sum(weight), starts[seg["id"]]
        for p, w in zip(parts, weight, strict=True):
            span = durs[seg["id"]] * w / total
            text = p.rstrip(",;、。").translate(FULLWIDTH)
            lines.append(f"{n}\n{srt_time(t)} --> {srt_time(t + span)}\n{text}\n")
            n, t = n + 1, t + span
    return "\n".join(lines)


# ── 3. 合成 ─────────────────────────────────────────────────
def mux(script: dict, work: Path, out_mp4: Path) -> None:
    timeline = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
    durs = json.loads((work / "durations.json").read_text(encoding="utf-8"))
    video_len = duration(work, "screen.webm")
    # 錄影從建立頁面就開始,比計時零點早一點;用總長度差補回來
    offset = max(0.0, video_len - timeline["end"] / 1000)
    starts = {s["id"]: s["start"] / 1000 + offset for s in timeline["segments"]}
    srt = build_srt(script, starts, durs)
    (work / "subs.srt").write_text(srt, encoding="utf-8")

    segs = script["segments"]
    inputs = ["-i", "/w/screen.webm"]
    for s in segs:
        inputs += ["-i", f"/w/{s['id']}.mp3"]
    delays = ";".join(
        f"[{i + 1}:a]adelay={int(starts[s['id']] * 1000)}:all=1[a{i}]" for i, s in enumerate(segs))
    mix = "".join(f"[a{i}]" for i in range(len(segs)))
    # SRT 轉成字幕時的座標高度是 288:FontSize 15 ≈ 720p 畫面上 37px;BorderStyle 3 = 半透明底框
    style = (f"FontName={SUB_FONT},FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H8C000000,"
             "BorderStyle=3,Outline=5,Shadow=0,MarginV=10,Spacing=0.3")
    graph = (f"{delays};{mix}amix=inputs={len(segs)}:normalize=0[aout];"
             f"[0:v]fps=30,subtitles=/w/subs.srt:fontsdir=/fonts:force_style='{style}'[vout]")
    docker(["-y", *inputs, "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-t", f"{video_len:.2f}", "-movflags", "+faststart",
            "/w/final.mp4"], work)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(work / "final.mp4", out_mp4)
    shutil.copy(work / "subs.srt", out_mp4.with_suffix(".srt"))
    print(f"完成:{out_mp4}({video_len:.0f} 秒)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--base", default="http://localhost:8120")
    ap.add_argument("--out", default=str(ROOT / "docs" / "影片"))
    ap.add_argument("--skip-tts", action="store_true")
    ap.add_argument("--skip-record", action="store_true")
    a = ap.parse_args()

    script = json.loads((FRONTEND / "e2e" / "video" / f"{a.name}.json").read_text(encoding="utf-8"))
    work = FRONTEND / "video-out" / a.name
    work.mkdir(parents=True, exist_ok=True)

    if not a.skip_tts:
        print("1/3 產生旁白語音")
        asyncio.run(tts(script, work))
        durs = {s["id"]: duration(work, f"{s['id']}.mp3") for s in script["segments"]}
        (work / "durations.json").write_text(json.dumps(durs, indent=1), encoding="utf-8")
        print(f"  旁白共 {sum(durs.values()):.0f} 秒")

    if not a.skip_record:
        print("2/3 錄影")
        env = {**os.environ, "VIDEO_OUT": str(work), "E2E_BASE_URL": a.base}
        r = subprocess.run(["npx", "playwright", "test", "--project=video", f"e2e/video/{a.name}.video.ts"],
                           cwd=FRONTEND, env=env, shell=True)
        if r.returncode != 0:
            sys.exit("錄影失敗")

    print("3/3 合成")
    title = script.get("title", a.name)
    mux(script, work, Path(a.out) / f"{title}.mp4")


if __name__ == "__main__":
    main()
