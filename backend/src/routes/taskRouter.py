from fastapi import APIRouter, HTTPException
import uuid
import json
import os
import shutil
from typing import List

from src.db import AsyncSessionLocal
from src.models.pieza import Pieza
from src.models.imagen import Imagen
from src.services.s3 import upload_imagen, upload_label
from src.core.config import r
from pydantic import BaseModel

class ImageConfirmation(BaseModel):
    frame: str
    status: str

router = APIRouter(tags=["Tasks"])

@router.get("/tasks")
async def get_all_tasks():
    # 1. Scan for all keys matching status:*
    keys = list(r.scan_iter("status:*"))
    if not keys:
        return []
    
    task_ids = []
    for key in keys:
        try:
            key_str = key.decode("utf-8")
            task_id = key_str.split(":", 1)[1]
            task_ids.append(task_id)
        except Exception:
            continue
            
    if not task_ids:
        return []
        
    # 2. Fetch all staging keys to calculate frames summary per task
    staging_keys = list(r.scan_iter("staging:*"))
    task_frames = {}
    
    if staging_keys:
        pipe = r.pipeline()
        for s_key in staging_keys:
            pipe.get(s_key)
        staging_values = pipe.execute()
        
        for s_key, s_val in zip(staging_keys, staging_values):
            if not s_val:
                continue
            try:
                s_key_str = s_key.decode("utf-8")
                parts = s_key_str.split(":")
                if len(parts) >= 3:
                    task_id = parts[1]
                    frame_data = json.loads(s_val.decode("utf-8"))
                    frame_status = frame_data.get("status", "unknown")
                    
                    if task_id not in task_frames:
                        task_frames[task_id] = {
                            "total": 0,
                            "pending": 0,
                            "pending_validation": 0,
                            "approved": 0,
                            "rejected": 0,
                            "awaiting_twin_label": 0
                        }
                    
                    task_frames[task_id]["total"] += 1
                    if frame_status in task_frames[task_id]:
                        task_frames[task_id][frame_status] += 1
            except Exception:
                continue

    # 3. Pipelined fetch for task metadata
    pipe = r.pipeline()
    for task_id in task_ids:
        pipe.get(f"status:{task_id}")
        pipe.get(f"class_id:{task_id}")
        pipe.get(f"file:{task_id}")
        pipe.get(f"prompt:{task_id}")
        pipe.get(f"bag_type:{task_id}")
        
    results = pipe.execute()
    
    tasks_list = []
    for idx, task_id in enumerate(task_ids):
        offset = idx * 5
        status_raw = results[offset]
        class_id_raw = results[offset+1]
        file_raw = results[offset+2]
        prompt_raw = results[offset+3]
        bag_type_raw = results[offset+4]
        
        status = status_raw.decode("utf-8") if status_raw else "UNKNOWN"
        class_id = class_id_raw.decode("utf-8") if class_id_raw else None
        filename = file_raw.decode("utf-8") if file_raw else None
        prompt = prompt_raw.decode("utf-8") if prompt_raw else None
        
        bag_types = []
        if bag_type_raw:
            try:
                bag_types = json.loads(bag_type_raw.decode("utf-8"))
            except Exception:
                pass
                
        tasks_list.append({
            "task_id": task_id,
            "status": status,
            "class_id": class_id,
            "filename": filename,
            "prompt": prompt,
            "bag_types": bag_types,
            "frames_summary": task_frames.get(task_id, {
                "total": 0,
                "pending": 0,
                "pending_validation": 0,
                "approved": 0,
                "rejected": 0,
                "awaiting_twin_label": 0
            })
        })
        
    return tasks_list

@router.get("/fetchImages/{taskID}")
async def fetchImages(taskID: str): 
    status = r.get(f"status:{taskID}")
    if not status: 
        raise HTTPException(status_code=404, detail="Task not found")
    status = status.decode()
 
    keys = list(r.scan_iter(f"staging:{taskID}:*"))
    if not keys:
        return {
            "task_id": taskID,
            "status": status,
            "message": "File received, validated and queued for processing"
        }
    
    pipe = r.pipeline()
    for key in keys:
        pipe.get(key)
    raw_values = pipe.execute()
    
    pending = []
    for val in raw_values:
        if val:
            data = json.loads(val)
            if data.get("status") == "pending_validation":
                pending.append(data)
                
    if len(pending) == 0: 
        return {
            "task_id": taskID,
            "status": status,
            "message": "File received, validated and queued for processing"
        }
    return pending

@router.post("/confirm/{taskID}")
async def confirm(taskID: str, imgStatus: List[ImageConfirmation]):
    status = r.get(f"status:{taskID}") 
    if not status: 
        raise HTTPException(status_code=404, detail="Task not found")
        
    pieza_id = None
    class_raw = r.get(f"class_id:{taskID}")
    if class_raw:
        try:
            pieza_id = uuid.UUID(class_raw.decode())
        except ValueError:
            pass

    if not pieza_id:
        raise HTTPException(status_code=400, detail="Task is not linked to a valid Piece ID (UUID)")

    # Verify the piece actually exists in Postgres
    async with AsyncSessionLocal() as db_session:
        pieza_exists = await db_session.get(Pieza, pieza_id)
        if not pieza_exists:
            raise HTTPException(status_code=404, detail="The linked Piece does not exist in the database")

    total = len(imgStatus)
    approved = 0
    rejected = 0
    
    # Resolve the correct Redis keys (handling variant-prefixed frames like staging:{taskID}:{variante}_{frame})
    resolved_keys = []
    for img in imgStatus:
        pattern = f"staging:{taskID}:*_{img.frame}"
        matches = list(r.scan_iter(pattern))
        if matches:
            resolved_keys.append(matches[0].decode("utf-8"))
        else:
            # Fallback to direct frame index
            resolved_keys.append(f"staging:{taskID}:{img.frame}")

    # Batch-fetch current keys to update them in a performant pipeline
    pipe = r.pipeline()
    for key in resolved_keys:
        pipe.get(key)
    raw_values = pipe.execute()
    
    update_pipe = r.pipeline()
    has_updates = False
    
    for img, key, val in zip(imgStatus, resolved_keys, raw_values):
        if not val:
            raise HTTPException(
                status_code=400,
                detail=f"Validation metadata not found for Frame {img.frame} in Redis (key: {key}). The task might have expired or been cleared."
            )
            
        data = json.loads(val)
        normalized_status = img.status.strip().lower()
        
        local_img_path = data.get("local_path")
        local_txt_path = data.get("txt_path")
        local_visual_path = data.get("visual_path")
        
        if normalized_status in ("approved", "aproved"):
            approved += 1
            data["status"] = "approved"
            update_pipe.setex(key, 864000, json.dumps(data))
            has_updates = True

            # Determine the variant from the metadata (set by DINO worker)
            variante = data.get("variante", "sin_bolsa")
            
            # S3 and Postgres logic
            if not local_img_path or not os.path.exists(local_img_path):
                raise HTTPException(
                    status_code=400,
                    detail=f"Local image file not found for Frame {img.frame} (expected path: {local_img_path}). Make sure the volume mounts are synchronized."
                )

            try:
                # 1. Read local files
                with open(local_img_path, "rb") as f_img:
                    img_bytes = f_img.read()
                
                txt_bytes = b""
                if local_txt_path and os.path.exists(local_txt_path):
                    with open(local_txt_path, "rb") as f_txt:
                        txt_bytes = f_txt.read()
                
                # 2. Upload to S3 using the frame name and variant-specific path
                bucket, key_s3 = upload_imagen(
                    img_bytes,
                    str(pieza_id),
                    frame_name=img.frame,
                    variante=variante,
                )
                
                key_s3_label = None
                if txt_bytes:
                    _, key_s3_label = upload_label(
                        txt_bytes,
                        str(pieza_id),
                        id_render_set=img.frame,
                    )
                
                # 3. Create database entry with variant tracking
                async with AsyncSessionLocal() as db_session:
                    db_img = Imagen(
                        id_pieza=pieza_id,
                        bucket=bucket,
                        key_s3=key_s3,
                        key_s3_label=key_s3_label,
                        bagType=variante
                    )
                    db_session.add(db_img)
                    await db_session.commit()
            except Exception as s3_db_err:
                import traceback
                print(f"[ERROR] Failed S3/DB upload for Frame {img.frame}: {s3_db_err}")
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to upload Frame {img.frame} to S3 or save to Database. Error: {str(s3_db_err)}"
                )
                    
                # 4. Clean up local files
                try:
                    os.remove(local_img_path)
                    if local_txt_path and os.path.exists(local_txt_path):
                        os.remove(local_txt_path)
                    if local_visual_path and os.path.exists(local_visual_path):
                        os.remove(local_visual_path)
                except Exception as err:
                    print(f"Error cleaning up staging files for Frame {img.frame}: {err}")
            
            print(f"Frame {img.frame} ({variante}) Approved and stored")

        elif normalized_status in ("rejected", "not_approved", "not_aproved"):
            rejected += 1
            data["status"] = "rejected"
            update_pipe.setex(key, 864000, json.dumps(data))
            has_updates = True
            
            # Clean up local files
            try:
                if local_img_path and os.path.exists(local_img_path):
                    os.remove(local_img_path)
                if local_txt_path and os.path.exists(local_txt_path):
                    os.remove(local_txt_path)
                if local_visual_path and os.path.exists(local_visual_path):
                    os.remove(local_visual_path)
            except Exception as err:
                print(f"Error cleaning up rejected files for Frame {img.frame}: {err}")
                
            print(f"Frame {img.frame} Rejected and cleaned")
        else:
            print(f"Inappropriate format/status for Frame {img.frame}: {img.status}")
            
    if has_updates:
        update_pipe.execute()
        
    transaction_status = True if (approved + rejected) == total else False

    # 1. Clean up staging folder (rendered frames)
    staging_dir = os.path.join("/staging", taskID)
    if os.path.exists(staging_dir):
        try:
            shutil.rmtree(staging_dir)
            print(f"Cleaned up staging folder: {staging_dir}")
        except Exception as err:
            print(f"Error cleaning up staging folder {staging_dir}: {err}")

    # 2. Clean up extracted model data (.obj/.mtl/textures)
    data_dir = os.path.join("/app/data", taskID)
    if os.path.exists(data_dir):
        try:
            shutil.rmtree(data_dir)
            print(f"Cleaned up data folder: {data_dir}")
        except Exception as err:
            print(f"Error cleaning up data folder {data_dir}: {err}")

    return {
        "task_id": taskID,
        "transaction_status": transaction_status, 
        "Amount_approved": f"{approved} / {total}"
    }
