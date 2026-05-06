from flask import Flask, request, jsonify
import yt_dlp
import logging
import os
import json
from datetime import datetime
from functools import wraps
import time

# ============================================
# कॉन्फ़िगरेशन – यहाँ अपनी सेटिंग्स डालें
# ============================================
VALID_API_KEY = os.getenv("YT_API_KEY", "my_secret_key_2025")
HOST = os.getenv("API_HOST", "0.0.0.0")
PORT = int(os.getenv("API_PORT", "9898"))
DEBUG = os.getenv("API_DEBUG", "False").lower() == "true"
# ============================================

# लॉगिंग सेट करें
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# API Key चेक करने वाला decorator
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("x-api-key")
        if not api_key:
            return jsonify({"status": "error", "message": "Missing x-api-key header"}), 401
        if api_key != VALID_API_KEY:
            return jsonify({"status": "error", "message": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated

# yt-dlp options – Production ready
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": False,
    "ignoreerrors": True,
    "no_check_certificate": True,
    "prefer_insecure": True,
    "retries": 10,
    "socket_timeout": 60,
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web"],
            "skip": ["hls", "dash"],
        }
    }
}

def get_video_info(video_id: str):
    """Get audio and video URLs for a YouTube video"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if info is None:
                return None, None, None, None, None
        except Exception as e:
            logger.error(f"Extract failed for {video_id}: {str(e)}")
            return None, None, None, None, None
    
    audio_url = None
    video_url = None
    best_audio_bitrate = 0
    best_video_height = 0
    
    formats = info.get("formats", [])
    logger.info(f"Found {len(formats)} formats for {video_id}")
    
    for f in formats:
        # Audio only format
        if f.get("acodec") != "none" and f.get("vcodec") == "none":
            bitrate = f.get("tbr", 0) or f.get("abr", 0)
            if bitrate > best_audio_bitrate:
                best_audio_bitrate = bitrate
                audio_url = f.get("url")
        
        # Video format with audio (height <= 720)
        if f.get("vcodec") != "none" and f.get("height"):
            height = f.get("height", 0)
            if height <= 720 and height > best_video_height:
                best_video_height = height
                video_url = f.get("url")
    
    # Fallback: agar video URL nahi mila
    if not video_url:
        for f in formats:
            if f.get("vcodec") != "none":
                if not video_url:
                    video_url = f.get("url")
    
    # Fallback: agar audio URL nahi mila
    if not audio_url:
        for f in formats:
            if f.get("acodec") != "none":
                if not audio_url:
                    audio_url = f.get("url")
    
    title = info.get("title", "Unknown")
    duration = info.get("duration", 0)
    if duration:
        minutes = duration // 60
        seconds = duration % 60
        duration_str = f"{minutes}:{seconds:02d}"
    else:
        duration_str = "0:00"
    
    thumbnail = None
    thumbnails = info.get("thumbnails", [])
    if thumbnails:
        thumbnail = thumbnails[-1].get("url")
    
    return audio_url, video_url, title, duration_str, thumbnail

@app.route("/info/<video_id>", methods=["GET"])
@require_api_key
def get_info(video_id):
    if not video_id or len(video_id) != 11:
        return jsonify({"status": "error", "message": "Invalid video ID"}), 400
    
    logger.info(f"Processing request for video_id: {video_id}")
    start_time = time.time()
    
    try:
        audio_url, video_url, title, duration, thumbnail = get_video_info(video_id)
        
        if not audio_url and not video_url:
            return jsonify({
                "status": "error",
                "message": "No streams found for this video"
            }), 404
        
        response = {
            "status": "success",
            "audio_url": audio_url,
            "video_url": video_url,
            "title": title,
            "duration": duration,
            "thumbnail": thumbnail,
            "video_id": video_id,
            "response_time": f"{round((time.time() - start_time) * 1000)}ms"
        }
        
        logger.info(f"Success for {video_id} - {title[:50]} ({response['response_time']})")
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error processing {video_id}: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.2"
    })

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "YouTube API",
        "version": "1.0.2",
        "endpoints": {
            "/info/<video_id>": "GET - Get audio/video URLs (需要 x-api-key header)",
            "/health": "GET - Health check (不需要 API key)"
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
    
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)
