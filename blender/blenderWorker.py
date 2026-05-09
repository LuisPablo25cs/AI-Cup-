import pika
import redis
import os
import subprocess
import json
from pathlib import Path
import time

def connect_rabbitmq(retries=5, delay=5):
    for attempt in range(retries):
        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(host="rabbitmq")
            )
            print("Connected to RabbitMQ")
            return conn
        except Exception as e:
            print(f"RabbitMQ not ready ({attempt+1}/{retries}): {e}")
            time.sleep(delay)
    raise Exception("Could not connect to RabbitMQ after retries")



#Connection with rabbitmq
conn = connect_rabbitmq()

STAGING = Path(os.environ["STAGING_PATH"])
STAGING.mkdir(exist_ok=True)


#Start TCP conn with rabbitmq
channel = conn.channel()
#Declare queues 
channel.queue_declare(queue="blender-queue", durable=True)
channel.queue_declare(queue="grounding-sam-queue", durable=True)

r = redis.Redis(host="redis", port=6379, db=0)

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

        ch.basic_publish(
            exchange="", 
            routing_key="grounding-sam-queue",
            body=json.dumps({"taskId" : taskId, "frame":i, "path": str(out_path)})
        )
        ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue="blender-queue", on_message_callback=autoPhotoTaker3000)
channel.start_consuming()