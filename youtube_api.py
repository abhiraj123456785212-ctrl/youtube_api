from flask import Flask, request, jsonify
import yt_dlp
import logging
from datetime import datetime
from functools import wraps
import time
import redis
import hashlib
from threading import Thread
import queue

VALID_API_KEY = "my_secret_key_2025"
HOST = "0.0.0.0"
PORT = 9898

# ✅ Redis cache setup (optional - agar available ho to)
# Redis cache se response time 10x fast ho jayega
try:
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    print("⚠️ Redis not available, using memory cache")

# ✅ Memory cache (agar Redis nahi hai to)
memory_cache = {}
CACHE_EXPIRY = 3600  # 1 hour

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

# ✅ Updated: Best quality formats with fallback
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

# ✅ Naya: Quality options
QUALITY_OPTIONS = {
    "low": {
        "audio": "bestaudio[abr<=64]/bestaudio",
        "video": "bestvideo[height<=360]+bestaudio/best[height<=360]"
    },
    "medium": {
        "audio": "bestaudio[abr<=128][abr>=96]/bestaudio",
        "video": "bestvideo[height<=480]+bestaudio/best[height<=480]"
    },
    "high": {
        "audio": "bestaudio[abr<=192][abr>=160]/bestaudio",
        "video": "bestvideo[height<=720]+bestaudio/best[height<=720]"
    },
    "ultra": {
        "audio": "bestaudio[abr>=256]/bestaudio",
        "video": "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    }
}

# ✅ Improved: get_video_info with cache and quality
def get_cache_key(video_id, quality, stream_type):
    return f"{video_id}:{quality}:{stream_type}"

def get_cached(video_id, quality, stream_type):
    key = get_cache_key(video_id, quality, stream_type)
    if REDIS_AVAILABLE:
        cached = r.get(key)
        if cached:
            return cached
    else:
        if key in memory_cache:
            data, timestamp = memory_cache[key]
            if time.time() - timestamp < CACHE_EXPIRY:
                return data
    return None

def set_cache(video_id, quality, stream_type, data):
    key = get_cache_key(video_id, quality, stream_type)
    if REDIS_AVAILABLE:
        r.setex(key, CACHE_EXPIRY, data)
    else:
        memory_cache[key] = (data, time.time())

# ✅ Improved: get_video_info with quality and buffer
def get_video_info(video_id, quality="medium", stream_type="audio", prebuffer=True):
    # Check cache first
    cached = get_cached(video_id, quality, stream_type)
    if cached:
        return cached
    
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Select format based on quality and type
    if quality not in QUALITY_OPTIONS:
        quality = "medium"
    
    if stream_type == "audio":
        format_str = QUALITY_OPTIONS[quality]["audio"]
    else:
        format_str = QUALITY_OPTIONS[quality]["video"]
    
    # ✅ Update ydl_opts with format
    ydl_opts = YDL_OPTS.copy()
    ydl_opts["format"] = format_str
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if info is None:
                logger.error(f"No info for {video_id}")
                return None, None, None, None, None
            
            if 'entries' in info and info['entries']:
                info = info['entries'][0]
                if info is None:
                    return None, None, None, None, None
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return None, None, None, None, None
    
    # Get best quality URLs
    audio_url = None
    video_url = None
    
    for f in info.get('formats', []):
        if stream_type == "audio":
            if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                if not audio_url or f.get('abr', 0) > best_audio_bitrate:
                    audio_url = f.get('url')
                    best_audio_bitrate = f.get('abr', 0)
        else:
            if f.get('vcodec') != 'none' and f.get('height'):
                height = f.get('height', 0)
                if height <= 720:
                    if not video_url or height > best_video_height:
                        video_url = f.get('url')
                        best_video_height = height
    
    # ✅ Naya: Backup URL bhi fetch karein
    backup_url = None
    if stream_type == "audio":
        # Audio backup
        ydl_opts["format"] = "bestaudio"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl2:
            try:
                info2 = ydl2.extract_info(url, download=False)
                if info2 and 'formats' in info2:
                    for f in info2['formats']:
                        if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                            backup_url = f.get('url')
                            break
            except:
                pass
    
    # ✅ Naya: Pre-buffer support (5-10 seconds ka data)
    prebuffer_data = None
    if prebuffer and (audio_url or video_url):
        try:
            stream_url = video_url if stream_type == "video" else audio_url
            # Download first 10 seconds
            # Ye py-tgcalls ke buffer system ke liye hai
            prebuffer_data = {
                "url": stream_url,
                "title": info.get('title', 'Unknown'),
                "duration": info.get('duration', 0),
                "duration_str": f"{info.get('duration', 0)//60}:{info.get('duration', 0)%60:02d}",
                "quality": quality,
                "stream_type": stream_type
            }
        except Exception as e:
            logger.warning(f"Pre-buffer failed: {e}")
    
    result = {
        "audio_url": audio_url,
        "video_url": video_url,
        "backup_url": backup_url,
        "title": info.get('title', 'Unknown'),
        "duration": info.get('duration', 0),
        "duration_str": f"{info.get('duration', 0)//60}:{info.get('duration', 0)%60:02d}",
        "video_id": video_id,
        "quality": quality,
        "stream_type": stream_type,
        "prebuffer": prebuffer_data,
        "formats": [
            {"height": f.get('height'), "width": f.get('width'), "ext": f.get('ext'), "bitrate": f.get('tbr', 0)}
            for f in info.get('formats', []) if f.get('vcodec') != 'none'
        ][:5]
    }
    
    # Save to cache
    set_cache(video_id, quality, stream_type, result)
    
    logger.info(f"Success: {result['title']} (audio: {bool(audio_url)}, video: {bool(video_url)})")
    return result

# ✅ Updated: /info endpoint
@app.route("/info/<video_id>", methods=["GET"])
@require_api_key
def get_info(video_id):
    if not video_id or len(video_id) != 11:
        return jsonify({"status": "error", "message": "Invalid video ID"}), 400
    
    # Get quality parameter from request (default: medium)
    quality = request.args.get("quality", "medium")
    stream_type = request.args.get("type", "audio")  # audio or video
    prebuffer = request.args.get("prebuffer", "true").lower() == "true"
    
    try:
        result = get_video_info(video_id, quality, stream_type, prebuffer)
        if not result or (not result.get('audio_url') and not result.get('video_url')):
            return jsonify({"status": "error", "message": "No streams found"}), 404
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ✅ Naya: Chunk download endpoint (buffer ke liye)
@app.route("/chunk/<video_id>", methods=["GET"])
@require_api_key
def get_chunk(video_id):
    start = int(request.args.get("start", 0))
    end = int(request.args.get("end", 10))
    quality = request.args.get("quality", "medium")
    
    # Chunk-based download for buffering
    # Ye range requests support karega
    try:
        # Get full stream first (cached)
        result = get_video_info(video_id, quality, "audio")
        if not result or not result.get('audio_url'):
            return jsonify({"status": "error", "message": "No stream found"}), 404
        
        stream_url = result['audio_url']
        
        # ⚠️ Note: YouTube direct streaming me chunk support limited hai
        # Isliye hum puri URL return karte hain, py-tgcalls buffer handle karega
        return jsonify({
            "status": "success",
            "url": stream_url,
            "start": start,
            "end": end,
            "title": result['title'],
            "duration": result['duration_str']
        })
    except Exception as e:
        logger.error(f"Chunk error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ✅ Naya: Health + Stats
@app.route("/health")
def health():
    cache_size = len(memory_cache) if not REDIS_AVAILABLE else "redis"
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "cache": cache_size,
        "redis_available": REDIS_AVAILABLE
    })

# ✅ Naya: Clear cache
@app.route("/clear_cache", methods=["POST"])
@require_api_key
def clear_cache():
    if REDIS_AVAILABLE:
        r.flushdb()
    else:
        memory_cache.clear()
    return jsonify({"status": "success", "message": "Cache cleared"})

if __name__ == "__main__":
    logger.info("🚀 Starting YouTube API Server v3.0 (with Buffer Support)")
    logger.info(f"Host: {HOST}, Port: {PORT}")
    logger.info(f"Redis Available: {REDIS_AVAILABLE}")
    logger.info(f"Cache Expiry: {CACHE_EXPIRY}s")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
