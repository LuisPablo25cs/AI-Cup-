import pika
import redis
import os
import torch
import cv2
import numpy as np
from groundingdino.util.inference import load_model, load_image, predict
from segment_anything import sam_model_registry, SamPredictor
from torchvision.ops import box_convert
from pathlib import Path
import json
import time

r = redis.Redis(host="redis", port=6379, db=0)

CONFIG_PATH    = "/app/GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH   = "/app/weights/groundingdino_swint_ogc.pth"
SAM_CHECKPOINT = "/app/weights/sam_vit_h_4b8939.pth"
SAM_MODEL_TYPE = "vit_h"

torch.set_grad_enabled(False)
print("Loading DINO...")
dinoModel = load_model(CONFIG_PATH, WEIGHTS_PATH)
print("Loading SAM...")
sam = sam_model_registry[SAM_MODEL_TYPE](checkpoint=SAM_CHECKPOINT).to("cuda")
sam_predictor = SamPredictor(sam)

def connect_rabbitmq(retries=10, delay=10):
    for attempt in range(retries):
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
            print(f"RabbitMQ not ready ({attempt+1}/{retries}): {e}")
            time.sleep(delay)
    raise Exception("Could not connect after retries")

def saveYoloSegmentation(masks, image_path, class_id):
    p        = Path(image_path)
    txt_path = p.with_suffix(".txt")
    h, w     = masks.shape[2], masks.shape[3]
    with open(txt_path, "w") as f:
        for mask in masks:
            mask_np    = mask[0].cpu().numpy().astype(np.uint8)  # fixed: cpu() not cpu
            contours, _ = cv2.findContours(                       # fixed: findContours not findCountours
                mask_np, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contour in contours:
                if len(contour) < 3:
                    continue
                polygon  = contour.reshape(-1, 2) / np.array([w, h])
                poly_str = " ".join(f"{c[0]:.6f} {c[1]:.6f}" for c in polygon)
                f.write(f"{class_id} {poly_str}\n")
    return str(txt_path)

def annotateAndSaveVisual(image_source, masks, image_path):
    overlay    = image_source.copy()
    background = image_source.copy()
    for mask in masks:
        color   = np.random.randint(50, 255, size=3).tolist()
        mask_np = mask.squeeze().cpu().numpy().astype(np.uint8)
        contours, _ = cv2.findContours(
            mask_np, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(overlay, contours, -1, color, -1)
        cv2.drawContours(overlay, contours, -1, (255, 255, 255), 2)
    result      = cv2.addWeighted(overlay, 0.4, background, 0.6, 0)
    p           = Path(image_path)
    visual_path = p.parent / f"seg_visual_{p.name}"
    cv2.imwrite(str(visual_path), cv2.cvtColor(result, cv2.COLOR_RGB2BGR))  # fixed color conversion
    return str(visual_path)

def annotateImage(image_path, prompt, class_id, task_id, frame):
    print(f"Annotating frame {frame} for task {task_id}")
    image_source, image = load_image(image_path)
    boxes, logits, phrases = predict(
        dinoModel, image, prompt,
        box_threshold=0.3,
        text_threshold=0.25
    )
    if len(boxes) == 0:
        print(f"No detections for frame {frame} — skipping")
        return None
    sam_predictor.set_image(image_source)
    h, w, _       = image_source.shape
    boxes_pixels  = boxes * torch.Tensor([w, h, w, h])
    boxes_xyxy    = box_convert(boxes_pixels, "cxcywh", "xyxy").to("cuda")
    transformed   = sam_predictor.transform.apply_boxes_torch(  # fixed: apply_boxes_torch not apply_boces_torch
        boxes_xyxy, image_source.shape[:2]
    )
    masks, _, _ = sam_predictor.predict_torch(
        point_coords=None, point_labels=None,
        boxes=transformed, multimask_output=False
    )
    txt_path    = saveYoloSegmentation(masks, image_path, class_id)
    visual_path = annotateAndSaveVisual(image_source, masks, image_path)
    return {"txt_path": txt_path, "visual_path": visual_path}

def onAnnotationJob(ch, method, properties, body):
    job       = json.loads(body)
    taskId    = job["taskId"]
    frame     = job["frame"]
    imagePath = job["path"]

    promptRaw = r.get(f"prompt:{taskId}")
    classRaw  = r.get(f"class_id:{taskId}")

    if not promptRaw:
        print(f"No prompt found for task {taskId} — rejecting")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    prompt  = promptRaw.decode()
    classId = classRaw.decode() if classRaw else "0"
    metaKey = f"staging:{taskId}:{frame}"

    r.setex(metaKey, 864000, json.dumps({
        "local_path": imagePath,
        "status":     "annotating",
        "task_id":    taskId,
        "frame":      frame
    }))

    res = annotateImage(imagePath, prompt, classId, taskId, frame)

    if res:
        r.setex(metaKey, 864000, json.dumps({
            "local_path":  imagePath,
            "txt_path":    res["txt_path"],
            "visual_path": res["visual_path"],
            "status":      "pending_validation",
            "task_id":     taskId,
            "frame":       frame
        }))
        ch.basic_publish(
            exchange="",
            routing_key="to-validate-imgs-queue",
            body=json.dumps({"task_id": taskId, "frame": frame})
        )
    else:
        r.setex(metaKey, 864000, json.dumps({
            "local_path": imagePath,
            "status":     "no_detection",
            "task_id":    taskId,
            "frame":      frame
        }))

    ch.basic_ack(delivery_tag=method.delivery_tag)

while True:
    try:
        conn    = connect_rabbitmq()
        channel = conn.channel()
        channel.queue_declare(queue="grounding-sam-queue", durable=True)
        channel.queue_declare(queue="to-validate-imgs-queue", durable=True)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue="grounding-sam-queue", on_message_callback=onAnnotationJob)
        print("Dino worker ready, waiting for jobs...")
        channel.start_consuming()
    except (pika.exceptions.StreamLostError,
            pika.exceptions.ConnectionClosedByBroker,
            pika.exceptions.AMQPConnectionError) as e:
        print(f"Connection lost: {e} — reconnecting in 5s...")
        time.sleep(5)
    except KeyboardInterrupt:
        print("Shutting down")
        break