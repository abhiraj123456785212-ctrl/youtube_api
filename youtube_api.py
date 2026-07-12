from flask import Flask, request, jsonify
import yt_dlp
import logging
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

# Powerful yt-dlp options (matches your manual command)
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "extract_flat": False,
    "no_check_certificate": True,
    "prefer_insecure": True,
    "retries": 10,
    "socket_timeout": 60,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
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
                logger.error(f"No info for {video_id}")
                return None, None, None, None
            
            # If it's a playlist, take the first video
            if 'entries' in info and info['entries']:
                info = info['entries'][0]
                if info is None:
                    return None, None, None, None
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return None, None, None, None
    
    # Find best audio and video URLs
    audio_url = None
    video_url = None
    best_audio_bitrate = 0
    best_video_height = 0
    
    for f in info.get('formats', []):
        # Audio only
        if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
            bitrate = f.get('tbr', 0) or f.get('abr', 0)
            if bitrate > best_audio_bitrate:
                best_audio_bitrate = bitrate
                audio_url = f.get('url')
        
        # Video + audio, height <= 720
        if f.get('vcodec') != 'none' and f.get('height'):
            height = f.get('height', 0)
            if height <= 720 and height > best_video_height:
                best_video_height = height
                video_url = f.get('url')
    
    # Fallback: if no video found, take any video format
    if not video_url:
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none':
                video_url = f.get('url')
                break
    
    # Fallback: if no audio found, take any audio format
    if not audio_url:
        for f in info.get('formats', []):
            if f.get('acodec') != 'none':
                audio_url = f.get('url')
                break
    
    title = info.get('title', 'Unknown')
    duration = info.get('duration', 0)
    if duration:
        minutes = duration // 60
        seconds = duration % 60
        duration_str = f"{minutes}:{seconds:02d}"
    else:
        duration_str = "0:00"
    
    logger.info(f"Success: {title} (audio: {bool(audio_url)}, video: {bool(video_url)})")
    return audio_url, video_url, title, duration_str

@app.route("/info/<video_id>", methods=["GET"])
@require_api_key
def get_info(video_id):
    if not video_id or len(video_id) != 11:
        return jsonify({"status": "error", "message": "Invalid video ID"}), 400
    try:
        audio_url, video_url, title, duration = get_video_info(video_id)
        if not audio_url and not video_url:
            return jsonify({"status": "error", "message": "No streams found"}), 404
        return jsonify({
            "status": "success",
            "audio_url": audio_url,
            "video_url": video_url,
            "title": title,
            "duration": duration,
            "video_id": video_id
        })
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

if __name__ == "__main__":
    logger.info("Starting YouTube API Server v2.0")
    logger.info(f"Host: {HOST}, Port: {PORT}, API Key: {VALID_API_KEY}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
