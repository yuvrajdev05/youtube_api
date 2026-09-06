# 🎶 Artistbots Music Api

A lightweight Flask API to **search YouTube** and **download audio/video** from YouTube (and Spotify links, resolved via search) — powered by [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) and `ffmpeg`. Built for easy deployment on Render, Railway, or Replit.

## ✨ Features

- 🔍 **Search** YouTube videos by title
- 🎧 **Audio download** — always returns a clean audio-only file (auto-extracted via `ffmpeg` if needed)
- 🎬 **Video download** — with a configurable max quality (`144`–`2160`p), auto-merged with audio
- 🎵 **Spotify link support** — a Spotify track URL is automatically resolved to its YouTube match before downloading
- 🔑 **API key protected** `/download` endpoint
- 🍪 **Cookie support** (`cookies.txt`) to get past YouTube bot-checks
- 🌐 **Multi-strategy extraction** — automatically retries with different YouTube player clients (`web_embedded`, `android`, `ios`, `web`, `mweb`) if one gets blocked
- ⚡ **Caching** — audio/video already downloaded once is served instantly from disk on repeat requests
- 🧹 **Auto cleanup** — temp files are cleared after every request; cache is trimmed once it crosses 2GB

## 🧱 Tech Stack

| Component | Purpose |
|---|---|
| Flask + Gunicorn | Web server |
| yt-dlp | YouTube/media extraction & download |
| ffmpeg | Audio extraction / audio+video merging |
| Deno | External JS runtime yt-dlp uses to solve YouTube's signature challenges |
| requests | Calls the external search API |

## 📡 API Endpoints

### `GET /search`
Search for a YouTube video by title.

| Param | Required | Description |
|---|---|---|
| `title` | ✅ | Search query |

```
GET /search?title=Shape%20of%20You
```

```json
{
  "title": "Ed Sheeran - Shape of You",
  "url": "https://www.youtube.com/watch?v=...",
  "duration": 233
}
```

### `GET /download`
Download audio or video for a YouTube video, a bare video ID, or a Spotify track link.

| Param | Required | Default | Description |
|---|---|---|---|
| `url` | one of `url`/`title` | — | Full YouTube/Spotify URL, or a bare YouTube video ID |
| `title` | one of `url`/`title` | — | Search by title instead of passing a URL |
| `type` | ❌ | `audio` | `audio` or `video` |
| `quality` | ❌ | `360` | Max video height in pixels (video only) — e.g. `144`, `360`, `720`, `1080`, `2160` |
| `api_key` | ✅ | — | Must match the server's configured `API_KEY` |

**Examples**

```
GET /download?url=dQw4w9WgXcQ&type=audio&api_key=yuvibotes
GET /download?url=dQw4w9WgXcQ&type=video&api_key=yuvibotes      #fix
GET /download?url=dQw4w9WgXcQ&type=video&quality=720&api_key=yuvibotes
GET /download?title=Shape%20of%20You&type=audio&api_key=yuvibotes
GET /download?url=https://open.spotify.com/track/xxxx&type=audio&api_key=yuvibotes
```

Returns the media file as a downloadable attachment. On failure, returns:

```json
{ "error": "reason for failure" }
```

## ⚙️ Environment Variables

| Variable | Required | Description |
|---|---|---|
| `PROXY_URL` | ❌ | Route yt-dlp requests through a proxy (`http://user:pass@host:port`) — useful if the host's IP gets rate-limited by YouTube |
| `PORT` | ❌ | Port the server binds to (defaults per platform config) |

> The API key and cookies path are currently set directly in `app.py` (`API_KEY`, `COOKIES_FILE`) — move these to environment variables if you plan to make the repo public.

## 🚀 Deployment

### Docker (Render / Railway / any container host)

The included `Dockerfile` installs `ffmpeg`, `deno`, and all Python dependencies.

```bash
docker build -t artistbots-music-api .
docker run -p 10000:10000 artistbots-music-api
```

### Railway / Nixpacks

`nixpacks.toml` is already set up to install `ffmpeg` and `deno` and run the app with Gunicorn — just connect the repo and deploy.

### Replit

```bash
gunicorn --bind 0.0.0.0:5000 --reuse-port --timeout 600 --workers 2 app:app
```
Configured via `.replit` for both the dev workflow and Autoscale deployment.

## 🧑‍💻 Local Setup

```bash
pip install -r requirements.txt
python app.py
```
Server runs on `http://localhost:5000`.

## 🍪 Cookies

Some videos (age-restricted, region-locked, or when YouTube throws up a bot-check) need a logged-in session. Export your YouTube cookies in Netscape format into `cookies.txt` at the project root — the app already wires this in as a fallback strategy.

## ⚠️ Notes

- **JS runtime matters**: `app.py` tells yt-dlp to use **Deno** (`js_runtimes: {'deno': {}}`) to solve YouTube's signature/n-challenges. This must match whatever runtime is actually installed in the container (see `Dockerfile` / `nixpacks.toml`) — a mismatch silently shrinks the available format list and can cause `Requested format is not available` errors.
- This project depends on YouTube's undocumented internal APIs via `yt-dlp`; behavior can change if YouTube updates its systems. Keep `yt-dlp` updated (`pip install -U yt-dlp`).
- Use responsibly and in accordance with YouTube's Terms of Service and applicable copyright law.

## 📄 License

No license specified — add one (e.g. MIT) if you plan to open-source this.

## 💬 Credit & Support

Built and maintained by **Artistbots**.
For support, questions, or feedback, reach out on Telegram: **[t.me/Artistbots](https://t.me/Artistbots)**
