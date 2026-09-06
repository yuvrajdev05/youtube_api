FROM python:3.11-slim

# Bring in the deno binary. yt-dlp needs a real JS runtime to solve YouTube's
# signature/n-challenges — without it you get "Signature/n challenge solving
# failed" warnings and end up with no usable audio/video formats.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# ffmpeg is required to merge separate video+audio streams (used by the
# /download?type=video endpoint).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt

COPY . .

ENV PORT=10000
EXPOSE 10000

CMD gunicorn --timeout 150 --workers 2 --bind 0.0.0.0:${PORT} app:app
