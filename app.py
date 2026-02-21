import os
import torch
import cv2
import numpy as np
from glob import glob

# Asegurarse de cargar las librerías limpias
from groundingdino.util.inference import load_model, load_image, predict, annotate

# Desactivar gradientes para inferencia industrial (ahorra mucha memoria)
torch.set_grad_enabled(False)

print(f"DEBUG: Versión Numpy {np.__version__}")

# --- RUTAS ABSOLUTAS EXACTAS ---
CONFIG_PATH = "/app/GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH = "/app/weights/groundingdino_swint_ogc.pth"
DATASET_PATH = "/app/datasets/demo (platanos)" 
# -------------------------------

images = glob(os.path.join(DATASET_PATH, "*.jpg"))
print(f"Encontradas {len(images)} imágenes para procesar.")

if len(images) == 0:
    print("¡ALERTA! No se encontraron imágenes. Verifica el mapeo de carpetas en docker-compose.")
    exit()

print("Cargando modelo...")
model = load_model(CONFIG_PATH, WEIGHTS_PATH)

def auto_label_piece(image_path, text_prompt):
    print(f"Procesando: {image_path}...")
    image_source, image = load_image(image_path)

    boxes, logits, phrases = predict(
        model=model,
        image=image,
        caption=text_prompt,
        box_threshold=0.35,
        text_threshold=0.25
    )

    annotated_frame = annotate(image_source=image_source, boxes=boxes, logits=logits, phrases=phrases)
    
    base_name = os.path.basename(image_path)
    # Guardar en la misma carpeta para que lo veas en tu Windows al instante
    output_path = os.path.join(DATASET_PATH, f"resultado_{base_name}")
    
    cv2.imwrite(output_path, annotated_frame)
    print(f"Guardado como: {output_path}")
    
    return boxes, phrases
def save_yolo_labels(boxes, image_path, class_id=0):
    """
    Toma las cajas de DINO y genera un archivo .txt en formato YOLO.
    """
    # Extraer el nombre base sin la extensión (ej. "01.jpg" -> "01")
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    
    # Crear la ruta del archivo .txt en la misma carpeta que la imagen
    txt_path = os.path.join(DATASET_PATH, f"{base_name}.txt")
    
    with open(txt_path, 'w') as f:
        for box in boxes:
            # DINO devuelve tensores, los pasamos a floats estándar
            cx, cy, w, h = box.tolist()
            # Escribir la línea: <class_id> <cx> <cy> <w> <h>
            f.write(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")
            
    print(f"Etiquetas YOLO guardadas en: {txt_path}")
# ¡El punto final en el prompt es vital para el modelo de lenguaje!
prompt_ingles = "banana ." 

for img_path in images:
    # Evitar procesar imágenes que ya son resultados
    if "resultado_" not in img_path:
        boxes, labels = auto_label_piece(img_path, prompt_ingles)
        print(f"Cajas encontradas: {len(boxes)}\n")
        if len(boxes) > 0:
            save_yolo_labels(boxes, img_path, class_id=0)