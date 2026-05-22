import subprocess
import json
import redis
import pika
import time
import os
from pathlib import Path

STAGING = Path(os.environ.get("STAGING_PATH", "/staging"))
STAGING.mkdir(exist_ok=True)

r = redis.Redis(host="redis", port=6379, db=0)

def connect_rabbitmq(delay=10):
    attempt = 0
    while True:
        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host="rabbitmq",
                    heartbeat=600,
                    blocked_connection_timeout=300
                )
            )
            print("Connected to RabbitMQ")
            return conn
        except Exception as e:
            attempt += 1
            print(f"RabbitMQ not ready (attempt {attempt}): {e} — retrying in {delay}s...")
            time.sleep(delay)

def autoPhotoTaker3000(ch, method, properties, body):
    task      = json.loads(body)
    taskId    = task["task_id"]
    sceneFile = task["scene_file"]
    prompt    = task["prompt"]

    # Ack immediately so RabbitMQ's consumer_timeout (30 min)
    # doesn't kill the channel during long renders.
    ch.basic_ack(delivery_tag=method.delivery_tag)

    task_staging = STAGING / taskId
    task_staging.mkdir(exist_ok=True)

    process = subprocess.Popen([
        "blender", "--background",
        "--python", "/app/render/renderScene.py",
        "--", sceneFile, str(task_staging)
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    for line in process.stdout:
        # Print progress lines
        if "blanco" in line or "gris" in line or "negro" in line or "hdri" in line or "Completado" in line or "Modelo:" in line or "Traceback" in line or "Error" in line:
            print(line.strip(), flush=True)
            
        # Parse saved frames in real-time and pipeline them to DINO!
        if "Saved:" in line:
            try:
                # Extracts the file path between single quotes
                start_idx = line.find("'") + 1
                end_idx = line.rfind("'")
                img_path_str = line[start_idx:end_idx]
                img_path = Path(img_path_str)
                
                # Double-check file exists before queuing
                if img_path.exists():
                    frame = img_path.stem
                    meta_key = f"staging:{taskId}:{frame}"
                    r.setex(meta_key, 86400, json.dumps({
                        "local_path": str(img_path),
                        "status":     "pending",
                        "taskId":     taskId,
                        "frame":      frame
                    }))
                    ch.basic_publish(
                        exchange="",
                        routing_key="grounding-sam-queue",
                        body=json.dumps({
                            "taskId": taskId,
                            "frame":  frame,
                            "path":   str(img_path)
                        })
                    )
                    print(f"--> [Pipelined] Queued {frame} for DINO annotation", flush=True)
            except Exception as e:
                print(f"Error pipelining frame: {e}", flush=True)



while True:
    try:
        conn    = connect_rabbitmq()
        channel = conn.channel()
        channel.queue_declare(queue="blender-queue", durable=True)
        channel.queue_declare(queue="grounding-sam-queue", durable=True)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue="blender-queue", on_message_callback=autoPhotoTaker3000)
        print("Blender worker ready, waiting for jobs...")
        channel.start_consuming()
    except KeyboardInterrupt:
        print("Shutting down")
        break
    except Exception as e:
        print(f"Connection lost or failed: {e} — retrying in 10s...")
        time.sleep(10)