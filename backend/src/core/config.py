import os
import redis

# Shared Redis connection
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
r = redis.Redis(host=REDIS_HOST, port=6379, db=0)

# Shared file types for validation
fileTypes = [
    "model/gltf-binary",        # .glb MIME type
    "application/octet-stream", # fallback some clients send for .glb
    "application/zip",
    "application/x-zip-compressed",
]

AVAILABLE_BAG_TYPES = ["clear", "opaque"]
