from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
os.environ["PATH"] += os.pathsep + r"D:\ffmpeg\bin"
import uuid
import requests
import hashlib
import glob
import shutil

app = Flask(__name__)

# Base directory using /tmp (Render free plan uses ephemeral storage)
BASE_TEMP_DIR = "/tmp"

# Directory for storing temporary download files (will be cleared after each request)
TEMP_DOWNLOAD_DIR = os.path.join(BASE_TEMP_DIR, "download")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

# Directory for storing cached audio files (persists until container restart)
CACHE_DIR = os.path.join(BASE_TEMP_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Directory for storing cached video files separately
CACHE_VIDEO_DIR = os.path.join(BASE_TEMP_DIR, "cache_video")
os.makedirs(CACHE_VIDEO_DIR, exist_ok=True)

# Maximum cache size in bytes. High-resolution video files can be several
# hundred MB each, so keep enough room for multiple requested qualities.
MAX_CACHE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

# Path to your cookies file (if needed)
COOKIES_FILE = "cookies.txt"  # Replace with your actual cookies file path if required

# Search API URL (used both for regular searches and Spotify link resolution)
SEARCH_API_URL = "https://odd-block-a945.tenopno.workers.dev/search?title="

# API key required to use the /download endpoint
API_KEY = "yuvibotes"

# Optional: route yt-dlp requests through a proxy (helps when the host's own IP
# is rate-limited/blocked by YouTube, which is common on shared cloud hosts).
# Set this in your platform's environment variables, e.g.:
#   PROXY_URL=http://username:password@proxy-host:port
PROXY_URL = os.environ.get("PROXY_URL")


def get_cache_key(video_url):
    """Generate a cache key from the video URL."""
    return hashlib.md5(video_url.encode('utf-8')).hexdigest()


def get_directory_size(directory):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total_size += os.path.getsize(fp)
    return total_size


def check_cache_size_and_cleanup(preserve_paths=None):
    """Trim caches without deleting files needed by the current response."""
    preserve_paths = {
        os.path.abspath(path) for path in (preserve_paths or set())
    }
    total_size = get_directory_size(CACHE_DIR) + get_directory_size(CACHE_VIDEO_DIR)
    if total_size > MAX_CACHE_SIZE:
        for cache_dir in [CACHE_DIR, CACHE_VIDEO_DIR]:
            for file in os.listdir(cache_dir):
                file_path = os.path.join(cache_dir, file)
                if os.path.abspath(file_path) in preserve_paths:
                    continue
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error deleting file {file_path}: {e}")


def normalize_video_url(url):
    """
    Accepts either a full YouTube URL or a bare video ID and
    returns a full YouTube watch URL. Spotify links are left as-is
    (resolved separately by resolve_spotify_link).
    """
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    # Treat as a bare video ID
    return f"https://www.youtube.com/watch?v={url}"


def _extract_and_download(video_url, base_opts):
    """
    Try downloading with a sequence of client/cookie strategies, since a single
    strategy can get blocked depending on the video and the server's IP:

    1. yt-dlp's default client, WITH cookies — this client currently exposes
       the most complete format list and can solve YouTube's current checks.
    2. android + ios, WITHOUT cookies — works for public videos when the
       server IP is not blocked.
    3. web + mweb, WITH cookies — final fallback for videos requiring those
       clients.

    Returns (info, downloaded_file_path) from whichever attempt succeeds.
    Raises the last error if every strategy fails.
    """
    strategies = [
        # This embedded client currently works with the supplied cookies even
        # when the default/web clients trigger YouTube's bot-check page.
        {'player_client': ['web_embedded'], 'cookiefile': COOKIES_FILE},
        {'cookiefile': COOKIES_FILE},
        {'player_client': ['android', 'ios']},
        {'player_client': ['web', 'mweb'], 'cookiefile': COOKIES_FILE},
    ]

    last_error = None
    for strategy in strategies:
        opts = dict(base_opts)
        if 'player_client' in strategy:
            opts['extractor_args'] = {'youtube': {'player_client': strategy['player_client']}}
        if 'cookiefile' in strategy:
            opts['cookiefile'] = strategy['cookiefile']
        if PROXY_URL:
            opts['proxy'] = PROXY_URL

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                downloaded_file = ydl.prepare_filename(info)
                return info, downloaded_file
        except Exception as e:
            last_error = e
            continue

    raise last_error


def download_audio(video_url):
    """
    Download audio from the given YouTube video URL with caching.
    If the audio file was previously downloaded, return the cached file.
    """
    # Keep audio and video caches separate so a previously cached progressive
    # video can never be returned from an audio request.
    # The version suffix invalidates files cached by the previous selector,
    # which could contain a progressive video instead of audio.
    cache_key = hashlib.md5((video_url + "_audio_v3").encode('utf-8')).hexdigest()
    cached_files = glob.glob(os.path.join(CACHE_DIR, f"{cache_key}.*"))
    cached_file = next(
        (path for path in cached_files if os.path.isfile(path) and os.path.getsize(path) > 0),
        None,
    )
    if cached_file:
        return cached_file

    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")
    base_opts = {
        # Prefer a pure audio-only stream, but fall back to the best overall
        # stream (which may include video) instead of hard-failing. Some
        # client/video combinations never expose an audio-only format, and
        # a bare 'bestaudio' selector raises "Requested format is not
        # available" in that case.
        'format': 'bestaudio/best',
        # Guarantee audio-only output even when the 'best' fallback above
        # picks a combined video+audio stream.
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
        }],
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'max_memory': 450000,
        # yt-dlp needs a JavaScript runtime to solve YouTube's current
        # signature challenges and receive the full format list. The
        # container only ships Deno (see Dockerfile / nixpacks.toml), so
        # this must match — asking for 'node' when it isn't installed
        # silently disables signature solving and shrinks the available
        # format list, which is what was causing this error.
        # 'js_runtimes': {'node': {}},
    }

    try:
        info, downloaded_file = _extract_and_download(video_url, base_opts)
        # FFmpegExtractAudio can change the extension (e.g. a video-only
        # source gets extracted to .m4a/.opus), so the pre-postprocessing
        # filename/ext from prepare_filename()/info can be stale. Pick the
        # actual file that landed on disk instead.
        downloaded_candidates = glob.glob(
            os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.*")
        )
        final_file = next(
            (path for path in downloaded_candidates if os.path.isfile(path)),
            downloaded_file,
        )
        ext = os.path.splitext(final_file)[1].lstrip(".") or info.get("ext", "m4a")
        cached_file_path = os.path.join(CACHE_DIR, f"{cache_key}.{ext}")
        shutil.move(final_file, cached_file_path)
        check_cache_size_and_cleanup(preserve_paths={cached_file_path})
        return cached_file_path
    except Exception as e:
        raise Exception(f"Error downloading audio: {e}")


def download_video(video_url, quality=360):
    """
    Download video with audio at up to the requested quality.

    ``quality`` is a height in pixels (for example 144, 360, 720, 1080,
    or 2160). If the exact quality is not available, yt-dlp selects the
    best available quality below the requested maximum.
    """
    # Include the requested quality in the cache key so a 360p request can
    # never return a file cached for a different quality.
    cache_key = hashlib.md5(
        (f"{video_url}_video_quality_{quality}_v3").encode('utf-8')
    ).hexdigest()
    cached_files = glob.glob(os.path.join(CACHE_VIDEO_DIR, f"{cache_key}.*"))
    cached_file = next(
        (path for path in cached_files if os.path.isfile(path) and os.path.getsize(path) > 0),
        None,
    )
    if cached_file:
        return cached_file

    unique_id = str(uuid.uuid4())
    output_template = os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.%(ext)s")
    base_opts = {
        # Higher qualities are normally separate video/audio streams, so
        # download both and let FFmpeg merge them into an MP4 file.
        'format': (
            f'bestvideo[height<={quality}]+bestaudio/'
            f'best[height<={quality}][vcodec!=none][acodec!=none]'
        ),
        'merge_output_format': 'mp4',
        'outtmpl': output_template,
        'noplaylist': True,
        'quiet': True,
        'socket_timeout': 60,
        'max_memory': 300000,
        # Download large progressive streams in ranges so a throttled YouTube
        # connection can recover instead of leaving the request stuck.
        'http_chunk_size': 10 * 1024 * 1024,
        'retries': 3,
        'fragment_retries': 3,
        # See the note in download_audio(): the container ships Deno, not
        # Node, so this must say 'deno' or signature solving silently fails.
        'js_runtimes': {'deno': {}},
    }

    try:
        info, downloaded_file = _extract_and_download(video_url, base_opts)
        # After a video/audio merge, yt-dlp's prepared filename can refer to
        # the pre-merge extension. Prefer the final MP4 output if present.
        downloaded_candidates = glob.glob(
            os.path.join(TEMP_DOWNLOAD_DIR, f"{unique_id}.*")
        )
        merged_file = next(
            (
                path for path in downloaded_candidates
                if os.path.splitext(path)[1].lower() == ".mp4"
            ),
            downloaded_file,
        )
        cached_file_path = os.path.join(CACHE_VIDEO_DIR, f"{cache_key}.mp4")
        shutil.move(merged_file, cached_file_path)
        check_cache_size_and_cleanup(preserve_paths={cached_file_path})
        return cached_file_path
    except Exception as e:
        raise Exception(f"Error downloading video: {e}")


def resolve_spotify_link(url):
    """
    If the URL is a Spotify link, use the search API to find the corresponding YouTube link.
    Otherwise, return the URL unchanged.
    """
    if "spotify.com" in url:
        response = requests.get(SEARCH_API_URL + url)
        if response.status_code != 200:
            raise Exception("Failed to fetch search results for the Spotify link")
        search_result = response.json()
        if not search_result or 'link' not in search_result:
            raise Exception("No YouTube link found for the given Spotify link")
        return search_result['link']
    return url


@app.route('/search', methods=['GET'])
def search_video():
    """
    Search for a YouTube video using the external API.
    """
    try:
        query = request.args.get('title')
        if not query:
            return jsonify({"error": "The 'title' parameter is required"}), 400

        response = requests.get(SEARCH_API_URL + query)
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch search results"}), 500

        search_result = response.json()
        if not search_result or 'link' not in search_result:
            return jsonify({"error": "No videos found for the given query"}), 404

        return jsonify({
            "title": search_result["title"],
            "url": search_result["link"],
            "duration": search_result.get("duration"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/download', methods=['GET'])
def download_endpoint():
    """
    Unified download endpoint.

    GET /download?url=VIDEO_ID&type=audio&api_key=KEY
    GET /download?url=VIDEO_ID&type=video&api_key=KEY

    - url: full YouTube/Spotify URL or a bare YouTube video ID
    - type: "audio" (default) or "video"
    - quality: maximum video height in pixels for video downloads (default 360)
    - api_key: must match the configured API_KEY
    """
    try:
        # 1. Validate API key
        api_key = request.args.get('api_key')
        if api_key != API_KEY:
            return jsonify({"error": "Invalid or missing api_key"}), 401

        # 2. Resolve the video URL (by url param, or by title search)
        video_url = request.args.get('url')
        video_title = request.args.get('title')
        download_type = (request.args.get('type') or 'audio').lower()
        quality_value = request.args.get('quality', '360')

        if download_type not in ('audio', 'video'):
            return jsonify({"error": "'type' must be either 'audio' or 'video'"}), 400

        try:
            quality = int(quality_value)
            if quality < 144:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({
                "error": "'quality' must be a whole number of at least 144"
            }), 400

        if not video_url and not video_title:
            return jsonify({"error": "Either 'url' or 'title' parameter is required"}), 400

        if video_title and not video_url:
            response = requests.get(SEARCH_API_URL + video_title)
            if response.status_code != 200:
                return jsonify({"error": "Failed to fetch search results"}), 500
            search_result = response.json()
            if not search_result or 'link' not in search_result:
                return jsonify({"error": "No videos found for the given query"}), 404
            video_url = search_result['link']

        video_url = normalize_video_url(video_url)

        if video_url and "spotify.com" in video_url:
            video_url = resolve_spotify_link(video_url)

        # 3. Download based on requested type
        if download_type == 'video':
            cached_file_path = download_video(video_url, quality)
        else:
            cached_file_path = download_audio(video_url)

        return send_file(
            cached_file_path,
            as_attachment=True,
            download_name=os.path.basename(cached_file_path)
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean up temporary download files only (not the caches)
        for file in os.listdir(TEMP_DOWNLOAD_DIR):
            file_path = os.path.join(TEMP_DOWNLOAD_DIR, file)
            try:
                os.remove(file_path)
            except Exception as cleanup_error:
                print(f"Error deleting file {file_path}: {cleanup_error}")


@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>YouTube Downloader API</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap');
            
            :root {
                --bg-color: #0f172a;
                --card-bg: rgba(30, 41, 59, 0.7);
                --primary: #3b82f6;
                --primary-hover: #2563eb;
                --accent: #ec4899;
                --text-main: #f8fafc;
                --text-muted: #cbd5e1;
            }

            body {
                font-family: 'Outfit', sans-serif;
                background: var(--bg-color);
                background-image: 
                    radial-gradient(circle at 15% 50%, rgba(59, 130, 246, 0.15), transparent 25%),
                    radial-gradient(circle at 85% 30%, rgba(236, 72, 153, 0.15), transparent 25%);
                color: var(--text-main);
                margin: 0;
                padding: 0;
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                overflow-x: hidden;
            }

            .container {
                max-width: 800px;
                width: 90%;
                margin: 2rem auto;
                background: var(--card-bg);
                backdrop-filter: blur(16px);
                -webkit-backdrop-filter: blur(16px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 24px;
                padding: 3rem;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
                animation: slideUp 0.8s cubic-bezier(0.16, 1, 0.3, 1);
            }

            @keyframes slideUp {
                0% { transform: translateY(40px); opacity: 0; }
                100% { transform: translateY(0); opacity: 1; }
            }

            h1 {
                font-size: 3rem;
                font-weight: 800;
                margin-bottom: 1rem;
                background: linear-gradient(to right, #60a5fa, #f472b6);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                text-align: center;
            }

            p.subtitle {
                text-align: center;
                color: var(--text-muted);
                font-size: 1.1rem;
                margin-bottom: 3rem;
            }

            h2 {
                font-size: 1.8rem;
                font-weight: 600;
                margin-top: 2rem;
                margin-bottom: 1rem;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }

            .endpoint {
                background: rgba(15, 23, 42, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 1.5rem;
                transition: transform 0.3s ease, box-shadow 0.3s ease;
            }

            .endpoint:hover {
                transform: translateY(-2px);
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
                border-color: rgba(255, 255, 255, 0.1);
            }

            .badge {
                background: var(--primary);
                color: white;
                padding: 0.3rem 0.8rem;
                border-radius: 20px;
                font-size: 0.85rem;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                margin-right: 10px;
            }

            .badge.get { background: #10b981; }

            code {
                font-family: 'Fira Code', monospace;
                background: rgba(0, 0, 0, 0.3);
                padding: 0.2rem 0.5rem;
                border-radius: 6px;
                color: #93c5fd;
                font-size: 0.95em;
            }

            .example-block {
                margin-top: 1rem;
            }

            .example-item {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                margin-bottom: 1rem;
                padding-bottom: 1rem;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }

            .example-item:last-child {
                border-bottom: none;
                margin-bottom: 0;
                padding-bottom: 0;
            }

            .example-label {
                color: var(--text-muted);
                font-size: 0.9rem;
                font-weight: 600;
            }

            .example-code {
                background: #0f172a;
                padding: 1rem;
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 0.05);
                overflow-x: auto;
                color: #e2e8f0;
                font-size: 0.9rem;
                white-space: nowrap;
            }

            /* Floating Telegram Button */
            .telegram-fab {
                position: fixed;
                bottom: 30px;
                right: 30px;
                background: linear-gradient(135deg, #0088cc, #005f8e);
                color: white;
                width: 60px;
                height: 60px;
                border-radius: 50%;
                display: flex;
                justify-content: center;
                align-items: center;
                text-decoration: none;
                box-shadow: 0 10px 25px rgba(0, 136, 204, 0.4);
                transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                z-index: 1000;
            }

            .telegram-fab:hover {
                transform: scale(1.1) translateY(-5px);
                box-shadow: 0 15px 35px rgba(0, 136, 204, 0.6);
            }

            .telegram-fab svg {
                width: 30px;
                height: 30px;
                fill: currentColor;
                transform: translateX(-1px) translateY(1px); /* optical alignment */
            }

            .telegram-tooltip {
                position: absolute;
                right: 80px;
                background: white;
                color: #0f172a;
                padding: 0.5rem 1rem;
                border-radius: 8px;
                font-size: 0.9rem;
                font-weight: 600;
                opacity: 0;
                visibility: hidden;
                transition: all 0.3s ease;
                white-space: nowrap;
                box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            }

            .telegram-tooltip::after {
                content: '';
                position: absolute;
                top: 50%;
                right: -6px;
                transform: translateY(-50%);
                border-width: 6px 0 6px 6px;
                border-style: solid;
                border-color: transparent transparent transparent white;
            }

            .telegram-fab:hover .telegram-tooltip {
                opacity: 1;
                visibility: visible;
                right: 75px;
            }

            @media (max-width: 768px) {
                .container {
                    padding: 2rem;
                    width: 95%;
                }
                h1 { font-size: 2.2rem; }
                .telegram-fab {
                    bottom: 20px;
                    right: 20px;
                    width: 50px;
                    height: 50px;
                }
                .telegram-fab svg { width: 24px; height: 24px; }
                .telegram-tooltip { display: none; }
            }
        </style>
    </head>
    <body>

        <div class="container">
            <h1>🎵 YouTube Downloader API</h1>
            <p class="subtitle">A lightning-fast REST API to search and extract high-quality audio & video from YouTube and Spotify.</p>

            <h2>🚀 Available Endpoints</h2>

            <div class="endpoint">
                <h3><span class="badge get">GET</span> /search</h3>
                <p style="color: var(--text-muted); margin-top: 0.5rem;">Search for a video on YouTube by its title.</p>
                <div style="margin-top: 1rem;">
                    <strong>Parameters:</strong>
                    <ul style="color: var(--text-muted); margin-top: 0.5rem; line-height: 1.6;">
                        <li><code>title</code> (required): The search query.</li>
                    </ul>
                </div>
                <div class="example-block">
                    <div class="example-item">
                        <span class="example-label">Example Request</span>
                        <div class="example-code">/search?title=Your%20Favorite%20Song</div>
                    </div>
                </div>
            </div>

            <div class="endpoint">
                <h3><span class="badge get">GET</span> /download</h3>
                <p style="color: var(--text-muted); margin-top: 0.5rem;">Download processed audio or video directly.</p>
                <div style="margin-top: 1rem;">
                    <strong>Parameters:</strong>
                    <ul style="color: var(--text-muted); margin-top: 0.5rem; line-height: 1.6;">
                        <li><code>url</code>: Video ID, YouTube URL, or Spotify URL.</li>
                        <li><code>title</code>: Search query (if <code>url</code> is omitted).</li>
                        <li><code>type</code>: <code>audio</code> (default) or <code>video</code>.</li>
                        <li><code>quality</code>: Max height in pixels (e.g., <code>720</code>) for video.</li>
                        <li><code>api_key</code> (required): Your API access key.</li>
                    </ul>
                </div>
                <div class="example-block">
                    <div class="example-item">
                        <span class="example-label">Download Audio by ID</span>
                        <div class="example-code">/download?url=dQw4w9WgXcQ&amp;type=audio&amp;api_key=yuvibotes</div>
                    </div>
                    <div class="example-item">
                        <span class="example-label">Download Video by ID (720p)</span>
                        <div class="example-code">/download?url=dQw4w9WgXcQ&amp;type=video&amp;quality=720&amp;api_key=yuvibotes</div>
                    </div>
                    <div class="example-item">
                        <span class="example-label">Download Audio by Search Title</span>
                        <div class="example-code">/download?title=Your%20Favorite%20Song&amp;type=audio&amp;api_key=yuvibotes</div>
                    </div>
                    <div class="example-item">
                        <span class="example-label">Download Audio from Spotify Link</span>
                        <div class="example-code">/download?url=https://open.spotify.com/track/...&amp;type=audio&amp;api_key=yuvibotes</div>
                    </div>
                </div>
            </div>
        </div>

        <a href="https://t.me/yuvi_botes" target="_blank" class="telegram-fab" aria-label="Contact on Telegram">
            <span class="telegram-tooltip">Chat with @yuvi_botes</span>
            <svg viewBox="0 0 24 24">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69.01-.03.01-.14-.07-.19-.08-.05-.19-.02-.27 0-.12.03-1.98 1.25-5.58 3.68-.53.36-1.01.54-1.44.53-.47-.01-1.38-.27-2.06-.49-.83-.27-1.49-.42-1.43-.89.03-.25.38-.51 1.03-.78 4.04-1.76 6.74-2.92 8.09-3.48 3.85-1.6 4.64-1.88 5.17-1.89.11 0 .37.03.5.17.11.12.13.28.14.41-.01.07-.01.17-.02.21z"/>
            </svg>
        </a>

    </body>
    </html>
    """


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
