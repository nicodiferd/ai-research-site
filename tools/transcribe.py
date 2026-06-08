#!/usr/bin/env python3
"""
transcribe.py — extract metadata + transcript for one TikTok / YouTube / Instagram URL.

Outputs a single JSON object to stdout:
  { ok, source, video_id, webpage_url, title, author, author_url,
    date (YYYY-MM-DD), duration_s, description, transcript, transcript_source }

Strategy: yt-dlp metadata + auto/manual captions first; if no usable captions,
download bestaudio and transcribe with faster-whisper (small). Mirrors the logic
in ~/obsidian-vault/Dev/Scripts/tiktok_processor.py but emits clean JSON instead
of writing an Obsidian note (no LLM call — the article is written by the agent).

Run with the obsidian venv python, which has yt_dlp + faster_whisper:
  ~/obsidian-vault/Dev/venv/bin/python tools/transcribe.py <url>
"""
import json, re, sys, os, tempfile, urllib.request
from pathlib import Path

import yt_dlp


def source_of(url):
    if any(d in url for d in ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com")):
        return "tiktok"
    if "instagram.com" in url:
        return "instagram"
    if "youtu.be" in url or "youtube.com" in url:
        return "youtube"
    return "unknown"


def fetch_meta(url):
    opts = {"quiet": True, "no_warnings": True, "extract_flat": False,
            "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en"]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    d = info.get("upload_date", "") or ""
    date = f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else ""
    caps = {}
    for key in ("subtitles", "automatic_captions"):
        caps.update(info.get(key, {}) or {})
    return {
        "video_id": info.get("id", ""),
        "webpage_url": info.get("webpage_url", url),
        "title": info.get("title", "") or "",
        "author": info.get("uploader", info.get("creator", "")) or "",
        "author_url": info.get("uploader_url", info.get("channel_url", "")) or "",
        "date": date,
        "duration_s": info.get("duration", 0) or 0,
        "description": info.get("description", "") or "",
        "_captions": caps,
    }


def transcript_from_captions(caps):
    if not caps:
        return None
    cap_list = None
    for lang in ("en", "en-US", "en-GB"):
        if lang in caps:
            cap_list = caps[lang]
            break
    if cap_list is None:
        cap_list = next(iter(caps.values()))
    text_url = None
    for fmt in cap_list:
        if fmt.get("ext") in ("json3", "vtt", "srt", "srv3"):
            text_url = fmt.get("url")
            if text_url:
                break
    if not text_url and cap_list:
        text_url = cap_list[0].get("url")
    if not text_url:
        return None
    try:
        with urllib.request.urlopen(text_url) as r:
            data = r.read().decode("utf-8")
    except Exception:
        return None
    # json3
    try:
        parsed = json.loads(data)
        segs = []
        for ev in parsed.get("events", []):
            t = "".join(s.get("utf8", "") for s in ev.get("segs", [])).strip()
            if t:
                segs.append(t)
        if segs:
            return " ".join(segs)
    except (json.JSONDecodeError, KeyError):
        pass
    # vtt/srt fallback
    lines = []
    for line in data.splitlines():
        line = line.strip()
        if "-->" in line or line.startswith("WEBVTT") or not line or line.isdigit():
            continue
        clean = re.sub(r"<[^>]+>", "", line)
        if clean:
            lines.append(clean)
    return " ".join(lines) if lines else None


def transcript_from_whisper(url, model_size="small"):
    from faster_whisper import WhisperModel
    with tempfile.TemporaryDirectory() as tmp:
        opts = {"quiet": True, "no_warnings": True, "format": "bestaudio/best",
                "outtmpl": os.path.join(tmp, "a.%(ext)s"),
                "postprocessors": [{"key": "FFmpegExtractAudio",
                                    "preferredcodec": "mp3", "preferredquality": "128"}]}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            return None, f"audio download failed: {e}"
        files = list(Path(tmp).glob("a.*"))
        if not files:
            return None, "no audio file produced"
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(files[0]), language="en")
        text = " ".join(s.text.strip() for s in segments).strip()
        return (text or None), None


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: transcribe.py <url>"}))
        sys.exit(2)
    url = sys.argv[1]
    out = {"ok": False, "source": source_of(url)}
    try:
        meta = fetch_meta(url)
    except Exception as e:
        out["error"] = f"metadata fetch failed: {e}"
        print(json.dumps(out)); sys.exit(1)
    caps = meta.pop("_captions")
    out.update(meta)
    tr = transcript_from_captions(caps)
    out["transcript_source"] = "captions" if tr else None
    if not tr or len(tr) < 40:
        wtr, werr = transcript_from_whisper(url)
        if wtr:
            tr = wtr
            out["transcript_source"] = "whisper"
        elif werr and not tr:
            out["error"] = werr
    out["transcript"] = tr or ""
    out["ok"] = bool(tr)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
