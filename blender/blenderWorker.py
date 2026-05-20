import subprocess
import json
def autoPhotoTaker3000(ch, method, properties, body):
    task     = json.loads(body)
    taskId   = task["task_id"]
    sceneFile = task["scene_file"]   # /app/data/model.glb
    prompt   = task["prompt"]

    # Each task gets its own staging subfolder
    task_staging = STAGING / taskId
    task_staging.mkdir(exist_ok=True)

    subprocess.run([
        "blender", "--background",
        "--python", "/app/render/renderScene.py",
        "--", sceneFile, str(task_staging)
    ], check=True)

    # Now publish one message per rendered image
    for img_path in task_staging.glob("*.png"):
        frame = img_path.stem   # filename without extension as frame id
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

    ch.basic_ack(delivery_tag=method.delivery_tag)