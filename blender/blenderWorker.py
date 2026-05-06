import pika
import redis
import os
import subprocess
import json
from pathlib import Path

STAGING = Path(os.environ["STAGING_PATH"])
STAGING.mkdir(exist_ok=True)

#Connection with rabbitmq
conn = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
#Start TCP conn with rabbitmq
channel = conn.channel()
#Declare queues 
channel.queue_declare(queue="blender-queue", durable=True)
channel.queue_declare(queue="grounding-sam-queue", durable=True)

r = redis.Redis(host=redis, port=6379, db=0)

def autoPhotoTaker3000(ch, method, properties, body):
    task = json.loads(body)
    taskId = task["task_id"]
    sceneFile = task["scene_file"]
    n_images = task.get("n_images", 8)

    for i in range(n_images): 
        out_path = STAGING / f"{taskId}_{i:04d}.png"
        subprocess.run([
            "blender", "--background", sceneFile, 
            "--python", "/app/render/renderScene.py",
            "--", str(out_path), str(i), str(n_images)
        ], check=True)

        metaKey = f"staging:{taskId}:{i}"
        r.setex(metaKey, 86400, json.dumps({
            "local_path": str(out_path),
            "status": "pending",
            "taskId": taskId,
            "frame": i
        }))

        ch.basic_public(
            exchange="", 
            routing_key="grounding-sam-queue",
            body=json.dumps({"taskId" : taskId, "frame":i, "path": str(out_path)})
        )

channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue="grounding-sam-queue", on_message_callback=autoPhotoTaker3000)
channel.start_consuming()