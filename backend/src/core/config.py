import redis

# Shared Redis connection
r = redis.Redis(host="redis", port=6379, db=0)

# Shared file types for validation
fileTypes = [
    "model/gltf-binary",        # .glb MIME type
    "application/octet-stream", # fallback some clients send for .glb
    "application/zip",
    "application/x-zim-compressed",
]

AVAILABLE_BAG_TYPES = ["clear", "opaque"]
