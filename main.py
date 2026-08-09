import os
import requests
from fastapi import FastAPI, HTTPException

app = FastAPI(title="YouTube Music Bot API")

YOUTUBE_API_KEY = os.getenv("AIzaSyDDMCMrCyYAKY8A5ChCx8vay9W_AyAM2ek")

@app.get("/")
def home():
    return {"status": "online", "service": "YouTube API"}

@app.get("/search")
def search_youtube(q: str, limit: int = 5):

    if not YOUTUBE_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="YOUTUBE_API_KEY is not configured"
        )

    url = "https://www.googleapis.com/youtube/v3/search"

    params = {
        "part": "snippet",
        "q": q,
        "type": "video",
        "maxResults": min(limit, 50),
        "key": YOUTUBE_API_KEY
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    data = response.json()

    results = []

    for item in data.get("items", []):
        results.append({
            "video_id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "thumbnail": item["snippet"]["thumbnails"]["high"]["url"]
        })

    return {
        "query": q,
        "results": results
    }