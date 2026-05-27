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

RABBITMQ_PARAMS = pika.ConnectionParameters(
    host="rabbitmq",
    heartbeat=3600,                  # 1 hour — survives long Blender renders
    blocked_connection_timeout=7200  # 2 hours — absolute max render time
)

def connect_rabbitmq(delay=10):
    attempt = 0
    while True:
        try:
            conn = pika.BlockingConnection(RABBITMQ_PARAMS)
            print("Connected to RabbitMQ")
            return conn
        except Exception as e:
            attempt += 1
            print(f"RabbitMQ not ready (attempt {attempt}): {e} — retrying in {delay}s...")
            time.sleep(delay)

def publish_to_dino(taskId, frame, img_path):
    """
    Opens a short-lived dedicated publisher connection to send one frame
    to the grounding-sam-queue.

    Using the consumer channel for publishing inside a long-running callback
    is unreliable with pika BlockingConnection: the event loop is blocked
    inside the render loop so the write buffer never gets flushed to the socket.
    A separate connection guarantees delivery for every sin_bolsa frame.
    """
    try:
        pub_conn = pika.BlockingConnection(RABBITMQ_PARAMS)
        pub_ch   = pub_conn.channel()
        pub_ch.queue_declare(queue="grounding-sam-queue", durable=True)
        pub_ch.basic_publish(
            exchange="",
            routing_key="grounding-sam-queue",
            body=json.dumps({
                "taskId": taskId,
                "frame":  frame,
                "path":   str(img_path)
            }),
            properties=pika.BasicProperties(delivery_mode=2)  # persistent message
        )
        pub_conn.close()
        return True
    except Exception as e:
        print(f"  [!] Failed to publish frame {frame} to DINO queue: {e}", flush=True)
        return False

def autoPhotoTaker3000(ch, method, properties, body):
    task      = json.loads(body)
    taskId    = task["task_id"]
    sceneFile = task["scene_file"]
    prompt    = task["prompt"]
    bagTypes  = task.get("bag_types", [])

    # Mark task as actively rendering in Redis so /tasks reflects reality
    r.setex(f"status:{taskId}", 864000, "RENDERING")
    print(f"[{taskId}] Status -> RENDERING", flush=True)

    # NOTE: We do NOT ack here. We ack only after the render completes.
    # This ensures that if this worker crashes mid-render, RabbitMQ will
    # re-deliver the message to another healthy worker automatically.

    bag_arg = ",".join(bagTypes) if bagTypes else "none"

    task_staging = STAGING / taskId
    task_staging.mkdir(exist_ok=True)

    process = subprocess.Popen([
        "blender", "--background",
        "--python", "/app/render/renderScene.py",
        "--", sceneFile, str(task_staging), bag_arg
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    for line in process.stdout:
        # Print notable progress lines
        if any(kw in line for kw in ["blanco", "gris", "negro", "hdri", "Completado", "Modelo:", "Traceback", "Error", "Bolsa", "Simulando"]):
            print(line.strip(), flush=True)

        # Parse saved frames in real-time and route them
        if "Saved:" in line:
            try:
                # Extract the file path between single quotes
                start_idx = line.find("'") + 1
                end_idx   = line.rfind("'")
                img_path_str = line[start_idx:end_idx]
                img_path = Path(img_path_str)

                if img_path.exists():
                    frame         = img_path.stem
                    parent_folder = img_path.parent.name

                    if parent_folder.startswith("con_bolsa_"):
                        # BAGGED FRAME: store as awaiting its twin's label from DINO
                        variante = parent_folder  # e.g. "con_bolsa_clear"
                        meta_key = f"staging:{taskId}:{variante}_{frame}"
                        r.setex(meta_key, 864000, json.dumps({
                            "local_path": str(img_path),
                            "status":     "awaiting_twin_label",
                            "variante":   variante,
                            "taskId":     taskId,
                            "frame":      frame
                        }))
                        print(f"--> [Bag] Stored {variante}/{frame} — awaiting twin label", flush=True)
                    else:
                        # UNBAGGED FRAME: send to DINO via a dedicated publisher connection
                        meta_key = f"staging:{taskId}:sin_bolsa_{frame}"
                        r.setex(meta_key, 864000, json.dumps({
                            "local_path": str(img_path),
                            "status":     "pending",
                            "variante":   "sin_bolsa",
                            "taskId":     taskId,
                            "frame":      frame
                        }))
                        ok = publish_to_dino(taskId, frame, img_path)
                        if ok:
                            print(f"--> [Pipelined] Queued sin_bolsa/{frame} for DINO annotation", flush=True)
            except Exception as e:
                print(f"Error pipelining frame: {e}", flush=True)

    # Wait for render to finish and handle success / failure
    process.wait()
    if process.returncode == 0:
        r.setex(f"status:{taskId}", 864000, "DONE")
        print(f"[{taskId}] Render finished OK -> Status: DONE", flush=True)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    else:
        r.setex(f"status:{taskId}", 864000, "FAILED")
        print(f"[{taskId}] Render FAILED (exit code {process.returncode}) -> nacking", flush=True)
        # nack without requeue — prevents infinite crash loops on broken models
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


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