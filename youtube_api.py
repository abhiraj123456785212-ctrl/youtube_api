from flask import Flask, request, jsonify
import yt_dlp
import logging
import os
from datetime import datetime
from functools import wraps

VALID_API_KEY = "my_secret_key_2025"
HOST = "0.0.0.0"
PORT = 9898

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = Flask(__name__)

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("x-api-key")
        if not api_key or api_key != VALID_API_KEY:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated

YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "retries": 10,
    "socket_timeout": 60,
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}

def get_video_info(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=False)
        audio_url = None
        video_url = None
        for f in info.get("formats", []):
            if f.get("acodec") != "none" and f.get("vcodec") == "none" and not audio_url:
                audio_url = f.get("url")
            if f.get("vcodec") != "none" and f.get("acodec") != "none" and not video_url:
                if f.get("height", 0) <= 720:
                    video_url = f.get("url")
        return audio_url, video_url, info.get("title"), info.get("duration", 0)

@app.route("/info/<video_id>", methods=["GET"])
@require_api_key
def get_info(video_id):
    try:
        audio_url, video_url, title, duration = get_video_info(video_id)
        if not audio_url and not video_url:
            return jsonify({"status": "error", "message": "No streams found"}), 404
        return jsonify({"status": "success", "audio_url": audio_url, "video_url": video_url, "title": title, "duration": duration})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host=HOST, port=PORT)
