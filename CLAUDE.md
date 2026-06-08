# CLAUDE.md — AI Research Site

Static site of editorial "deep dive" articles distilled from short-form videos
(TikTok / YouTube / Instagram reels). Each article reverse-engineers or explains
the substance of a video in the site's own voice.

## What this is / how it serves

- Plain static files. `index.html` is the homepage; it `fetch()`es `articles.json`
  at runtime and renders one card per entry. **There is no build step** — writing
  files makes them live immediately.
- Served by `ai-research-site.service` (systemd): `python3 -m http.server 8787 --bind 127.0.0.1`,
  working dir this folder. Public via `ai-research-tunnel.service` → `ai-research.nicolod.org`.
  **Do not modify those services** (per top-level CLAUDE.md).
- Each article lives at `articles/<slug>/index.html`. The homepage links to `/articles/<slug>/`.

## articles.json (the manifest)

Array under `"articles"`, **newest first** (homepage shows them in array order).
Each entry:

```json
{
  "slug": "kebab-case-unique",
  "title": "Title Case, no trailing source",
  "description": "1–2 sentence hook shown on the card",
  "source": "tiktok | youtube | instagram",
  "sourceUrl": "https://… CANONICAL url (see dedup)",
  "sourceHandle": "@handle",
  "date": "YYYY-MM-DD",        // date ADDED to the site, not the upload date
  "tags": ["lowercase", "kebab-tags"],
  "emoji": "single emoji"       // shown before the title in card + hero
}
```

`sourceUrl` is the **dedup key**. Always store the canonical URL, never a short link.

## The URL → article workflow

### 0. Sanity check FIRST (this is the whole game — it caught a 17/17 no-op batch once)

For every input URL:

1. **Resolve short links to canonical.** TikTok `/t/XXXX/` links redirect. Resolve + liveness-check in one shot:
   ```bash
   curl -s -o /dev/null -w '%{http_code} %{url_effective}\n' -L --max-redirs 10 \
     -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" "<url>"
   ```
   `200` = live. The effective URL gives `@handle/video/<id>`.
2. **Dedup by stable video ID**, not by raw URL string. Extract the ID and compare
   against existing `sourceUrl`s in `articles.json`:
   - TikTok: `…/video/(\d+)` — the 19-digit ID (globally unique, definitive match)
   - YouTube: `youtu.be/<id>`, `watch?v=<id>`, or `shorts/<id>`
   - Instagram: `instagram.com/reel/<slug>`
   Report which inputs are NEW vs already-present (and which slug they map to).
   Only NEW ones proceed.

### 1. Transcribe

`tools/transcribe.py` extracts metadata + transcript and prints one JSON object.
It prefers yt-dlp captions and falls back to faster-whisper (small) only if needed.
Run with the obsidian venv python (has `yt_dlp` + `faster_whisper`; `ffmpeg` on PATH):

```bash
~/obsidian-vault/Dev/venv/bin/python tools/transcribe.py "<canonical-url>"
```

Output fields: `ok, source, video_id, webpage_url, title, author, author_url,
date (upload date), duration_s, description, transcript, transcript_source`.
Most TikTok/YouTube videos have captions → fast. `ok:false` means transcription
failed (skip / investigate). Whisper-small model is cached under `~/.cache/huggingface`.

### 2. Write the article (editorial deep-dive — match the house style)

These are NOT raw transcript dumps. Read the existing articles to match voice and
structure. Reuse the **exact** CSS by splicing the `<style>` block from any existing
article (don't hand-retype it):

```bash
python3 -c "import re;h=open('articles/claude-stock-analysis/index.html').read();\
open('/tmp/style_block.html','w').write(re.search(r'<style>.*?</style>',h,re.S).group(0))"
```

Page skeleton (`articles/<slug>/index.html`):
- `<head>`: `<meta charset>`, viewport, `<title>… | AI Research</title>`, then the spliced `<style>` block verbatim.
- `<a href="/" class="back-link">← Back to all articles</a>`
- `<header class="hero">`: `<h1>{emoji} {Title}</h1>`, `<p class="subtitle">…</p>`,
  `<div class="meta">{Source} {@handle} · ~{duration} · {Upload date}</div>`
- `<article>`: intro `<p>`, then `<h2>` sections. Available styled components
  (all defined in the CSS): `.highlight` (pull-quote), `.box`, `.concept-grid` +
  `.concept-card` (label/value cards), `.warning-box` (red), `.todo-box` (yellow dashed),
  `.prompt-block` (monospace), `.step-tag`. End with an `<h2>Full Transcript (summary for reference)</h2>`
  containing a `.box` of **paraphrased** bullets (a few `<p>`), not the verbatim transcript.
- `<footer>`: "Transcribed and distilled · `<a href="{canonical}" target="_blank">@handle on {Platform}</a>`"
  then a back link.

Keep it substantive and faithful to what the creator actually said; the goal is the
editorial distillation, not a rewrite that invents claims.

### 3. Register in the manifest

Append the entry to the **front** of `articles.json` `"articles"` array (newest first),
`date` = today (date added). Keep it valid JSON (`python3 -m json.tool articles.json`).

### 4. Verify

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/articles/<slug>/   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/articles.json       # 200
```

## Parallelizing across many URLs (orchestration)

When fanning out one subagent per URL, **do not let subagents edit `articles.json`
concurrently** — read-modify-write races corrupt it. Instead:

1. Orchestrator pre-transcribes each URL (sequential — avoids 6× concurrent whisper
   and surfaces dead links up front) and hands each subagent its transcript JSON.
2. Each subagent writes only `articles/<slug>/index.html` **and** `articles/<slug>/meta.json`
   (the manifest entry for that one article). It does NOT touch `articles.json`.
3. Orchestrator merges all `meta.json` sidecars into `articles.json` at the end
   (dedup by slug), then deletes the sidecars and verifies.

## Git

Repo is local (`~/clawd/ai-research-site`, git-tracked). Default: **write files only,
do not commit/push** unless asked. The site is live regardless of git state.

## Gotchas

- Match by video ID, never URL string — short links, `?si=`/`?_t=` params, and `@handle`
  casing all vary for the same video.
- `date` in the manifest is the add-date (for ordering), not the upload date; the
  upload date goes in the hero `.meta` line.
- TikTok `/@/video/<id>` (empty handle) still resolves and dedups fine by ID.
