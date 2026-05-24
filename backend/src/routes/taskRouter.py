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
    
    # Batch-fetch current keys to update them in a performant pipeline
    pipe = r.pipeline()
    for img in imgStatus:
        metaKey = f"staging:{taskID}:{img.frame}"
        pipe.get(metaKey)
    raw_values = pipe.execute()
    
    update_pipe = r.pipeline()
    has_updates = False
    
    for img, val in zip(imgStatus, raw_values):
        if not val:
            continue
            
        data = json.loads(val)
        normalized_status = img.status.strip().lower()
        
        local_img_path = data.get("local_path")
        local_txt_path = data.get("txt_path")
        local_visual_path = data.get("visual_path")
        
        if normalized_status in ("approved", "aproved"):
            approved += 1
            data["status"] = "approved"
            update_pipe.setex(f"staging:{taskID}:{img.frame}", 864000, json.dumps(data))
            has_updates = True

            # Determine the variant from the metadata (set by DINO worker)
            variante = data.get("variante", "sin_bolsa")
            
            # S3 and Postgres logic
            if local_img_path and os.path.exists(local_img_path):
                # 1. Read local files
                with open(local_img_path, "rb") as f_img:
                    img_bytes = f_img.read()
                
                txt_bytes = b""
                if local_txt_path and os.path.exists(local_txt_path):
                    with open(local_txt_path, "rb") as f_txt:
                        txt_bytes = f_txt.read()
                
                # 2. Upload to S3 using variant-specific subfolder
                img_uuid = str(uuid.uuid4())
                bucket, key_s3 = upload_imagen(img_bytes, str(pieza_id), filename_uuid=img_uuid, variante=variante)
                
                key_s3_label = None
                if txt_bytes:
                    _, key_s3_label = upload_label(txt_bytes, str(pieza_id), filename_uuid=img_uuid, variante=variante)
                
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
            update_pipe.setex(f"staging:{taskID}:{img.frame}", 864000, json.dumps(data))
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
