import os
import torch
import cv2
import numpy as np
from glob import glob
from groundingdino.util.inference import load_model, load_image, predict, annotate
from segment_anything import sam_model_registry, SamPredictor
from scipy.ndimage import binary_dilation 
from torchvision.ops import box_convert

# Configuración inicial
torch.set_grad_enabled(False)


BASE_DATASET_PATH = "/app/datasets/testing" 

#Configurar Grounding-DINO
CONFIG_PATH = "/app/GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH = "/app/weights/groundingdino_swint_ogc.pth"

#Configurar SAM
SAM_CHECKPOINT = "/app/weights/sam_vit_h_4b8939.pth"
SAM_MODEL_TYPE = "vit_h"
sam = sam_model_registry[SAM_MODEL_TYPE](checkpoint=SAM_CHECKPOINT).to(device="cuda")
sam_predictor = SamPredictor(sam)

SUB_FOLDERS = ["train", "val", "test"]


print("Cargando modelo Grounding DINO...")
model = load_model(CONFIG_PATH, WEIGHTS_PATH)

def save_yolo_segmentation(masks, image_path, target_dir, class_id=0):
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    txt_path = os.path.join(target_dir, f"{base_name}.txt")
    
    h, w = masks.shape[1], masks.shape[2]
    
    with open(txt_path, 'w') as f:
        for mask in masks:
            mask_np = mask[0].cpu().numpy().astype(np.uint8)
            #mask_np = cv2.morphologyEx(mask_np, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))
            contours, _ = cv2.findContours(mask_np, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if len(contour) < 3: continue # Ignorar ruidos pequeños
                polygon = contour.reshape(-1, 2) / np.array([w, h])
                poly_str = " ".join([f"{coord[0]:.6f} {coord[1]:.6f}" for coord in polygon])
                f.write(f"{class_id} {poly_str}\n")
    return txt_path
def annotate_segmentation(image_source, masks, alpha=0.5):
    """
    Dibuja las máscaras de segmentación sobre la imagen original con transparencia.
    """
    annotated_image = image_source.copy()
    overlay = annotated_image.copy()
    for i, mask in enumerate(masks):
        color = np.random.randint(50, 255, size=3).tolist()
        mask_np = mask.squeeze().cpu().numpy().astype(np.uint8)
        contours, _ = cv2.findContours(mask_np, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, color, -1)
        cv2.drawContours(overlay, contours, -1, (255,255,255), 2)

    cv2.addWeighted(overlay, alpha, annotated_image, 1 - alpha, 0, annotated_image)
    
    return annotated_image

def process_folder(folder_name, class_id, prompt):
    """
    Procesa una carpeta específica (ej. train) buscando en su subcarpeta 'images'.
    """
    img_dir = os.path.join(BASE_DATASET_PATH, folder_name, "images")
    label_dir = os.path.join(BASE_DATASET_PATH, folder_name, "labels")
    
    os.makedirs(label_dir, exist_ok=True)
    
    images = glob(os.path.join(img_dir, "*.jpg"))
    print(f"\n--- Procesando {folder_name.upper()} ({len(images)} imágenes) ---")
    
    if len(images) == 0:
        print(f"No se encontraron imágenes en {img_dir}")
        return

    for img_path in images:
        if "resultado_" in img_path: continue
        
        print(f"Etiquetando: {os.path.basename(img_path)}")
        image_source, image = load_image(img_path)

        boxes, logits, phrases = predict(model, image, prompt, 0.3, 0.25)

        sam_predictor.set_image(image_source)
        h, w, _ = image_source.shape
        boxes_pixels = boxes * torch.Tensor([w, h, w, h])
        boxes_xyxy = box_convert(boxes_pixels, in_fmt="cxcywh", out_fmt="xyxy").to("cuda")

        transformed_boxes = sam_predictor.transform.apply_boxes_torch(boxes_xyxy, image_source.shape[:2])
        masks, _, _ = sam_predictor.predict_torch(
            point_coords=None, point_labels=None, 
            boxes=transformed_boxes, multimask_output=False
        )

        if len(masks) > 0:
            #Guardar anotaciones
            save_yolo_segmentation(masks, img_path, label_dir, class_id)

            #Observar imagen
            visual_frame = annotate_segmentation(image_source, masks, alpha=0.4)
            # Guardar con prefijo "seg_visual_" en la misma carpeta de imágenes
            output_img_path = os.path.join(img_dir, f"seg_visual_{os.path.basename(img_path)}")
            # OpenCV usa BGR, la imagen source suele ser RGB, convertir si los colores se ven raros
            visual_frame_bgr = cv2.cvtColor(visual_frame, cv2.COLOR_RGB2BGR)
            cv2.imwrite(output_img_path, visual_frame_bgr)
        
        # Descomentar si se quiere ver las imagenes anotadas de donde se extraen las cajas. 
        #annotated_frame = annotate(image_source=image_source, boxes=boxes, logits=logits, phrases=phrases)
        #output_img = os.path.join(img_dir, f"resultado_{os.path.basename(img_path)}")
        #cv2.imwrite(output_img, annotated_frame)

#! Esto es para probar, para mayor precisión y detectar todas las instancias se debe poner dos veces la palabra en INGLES y separadas de un punto
#Ejemplo Chair . Chair 

prompt = "banana . banana . banana" 
#! Agregar el class ID cada que se crea una nueva clase
for folder in SUB_FOLDERS:
    process_folder(folder, class_id=0, prompt=prompt)

print("Labeling terminado")