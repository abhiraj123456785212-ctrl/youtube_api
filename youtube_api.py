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

# Improved yt-dlp options
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "retries": 10,
    "socket_timeout": 60,
    "extract_flat": False,
    "no_check_certificate": True,
    "prefer_insecure": True,
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
            "skip": ["hls", "dash"],
        }
    }
}

def get_video_info(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if info is None:
                logger.error(f"Failed to extract info for {video_id}")
                return None, None, None, None
        except Exception as e:
            logger.error(f"Extract error for {video_id}: {e}")
            return None, None, None, None

    audio_url = None
    video_url = None
    best_audio_bitrate = 0
    best_video_height = 0

    formats = info.get("formats", [])
    logger.info(f"Found {len(formats)} formats for {video_id}")

    for f in formats:
        # Audio only
        if f.get("acodec") != "none" and f.get("vcodec") == "none":
            bitrate = f.get("tbr", 0) or f.get("abr", 0)
            if bitrate > best_audio_bitrate:
                best_audio_bitrate = bitrate
                audio_url = f.get("url")
        
        # Video + audio, height <= 720
        if f.get("vcodec") != "none" and f.get("height"):
            height = f.get("height", 0)
            if height <= 720 and height > best_video_height:
                best_video_height = height
                video_url = f.get("url")

    # Fallback: agar video URL nahi mila to koi bhi video format le lo
    if not video_url:
        for f in formats:
            if f.get("vcodec") != "none":
                video_url = f.get("url")
                break

    # Fallback: agar audio URL nahi mila to koi bhi audio format le lo
    if not audio_url:
        for f in formats:
            if f.get("acodec") != "none":
                audio_url = f.get("url")
                break

    title = info.get("title", "Unknown")
    duration = info.get("duration", 0)
    
    if duration:
        minutes = duration // 60
        seconds = duration % 60
        duration_str = f"{minutes}:{seconds:02d}"
    else:
        duration_str = "0:00"

    logger.info(f"Success: {title} - audio: {bool(audio_url)}, video: {bool(video_url)}")
    return audio_url, video_url, title, duration_str

@app.route("/info/<video_id>", methods=["GET"])
@require_api_key
def get_info(video_id):
    if not video_id or len(video_id) != 11:
        return jsonify({"status": "error", "message": "Invalid video ID"}), 400

    try:
        audio_url, video_url, title, duration = get_video_info(video_id)
        if not audio_url and not video_url:
            return jsonify({"status": "error", "message": "No streams found for this video. Try another one."}), 404
        
        response = {
            "status": "success",
            "audio_url": audio_url,
            "video_url": video_url,
            "title": title,
            "duration": duration,
            "video_id": video_id
        }
        return jsonify(response)
    except Exception as e:
        logger.error(f"Error in /info: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "YouTube API",
        "version": "1.0.2",
        "endpoints": {
            "/info/<video_id>": "GET - Get audio/video URLs",
            "/health": "GET - Health check"
        }
    })

if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Starting YouTube API Server v1.0.2")
    logger.info(f"Host: {HOST}")
    logger.info(f"Port: {PORT}")
    logger.info(f"API Key: {VALID_API_KEY}")
    logger.info("=" * 50)
    logger.info(f"Health check: http://{HOST}:{PORT}/health")
    logger.info(f"Example: curl -H 'x-api-key: {VALID_API_KEY}' http://{HOST}:{PORT}/info/dQw4w9WgXcQ")
    logger.info("=" * 50)
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
