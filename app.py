import os
from glob import glob
import cv2
import torch
from groundingdino.util.inference import load_model, load_image, predict, annotate

# 1. Configuración de rutas
CONFIG_PATH = "groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH = "weights/groundingdino_swint_ogc.pth"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Asegúrate de que esta ruta coincida EXACTAMENTE con mayúsculas y espacios
# con cómo se llama tu carpeta en el sistema de archivos.
DATASET_PATH = "datasets/Demo (Platanos)" 
images = glob(os.path.join(DATASET_PATH, "*.jpg"))

print(f"Encontradas {len(images)} imágenes para procesar.")

# 2. Cargar el modelo
model = load_model(CONFIG_PATH, WEIGHTS_PATH)

def auto_label_piece(image_path, text_prompt):
    """
    Detecta piezas usando lenguaje natural y devuelve coordenadas.
    """
    print(f"Procesando: {image_path}...")
    image_source, image = load_image(image_path)

    # box_threshold: sensibilidad de detección (bájalo si no detecta, súbelo si hay falsos positivos)
    # text_threshold: relevancia del texto
    boxes, logits, phrases = predict(
        model=model,
        image=image,
        caption=text_prompt,
        box_threshold=0.35,
        text_threshold=0.25
    )

    # Crear imagen anotada
    annotated_frame = annotate(image_source=image_source, boxes=boxes, logits=logits, phrases=phrases)
    
    # Extraer el nombre original del archivo (ej. "01.jpg") para no sobrescribir
    base_name = os.path.basename(image_path)
    output_path = f"resultado_{base_name}"
    
    cv2.imwrite(output_path, annotated_frame)
    print(f"Guardado como: {output_path}")
    
    return boxes, phrases

# 3. Bucle para probar TODAS las imágenes en la carpeta
# El prompt sugerido para Grounding DINO es el nombre del objeto en inglés seguido de un punto.

#! Esta parte debe venir en la request. 
prompt_ingles = "banana ." 

for img_path in images:
    boxes, labels = auto_label_piece(img_path, prompt_ingles)
    
    # Aquí es donde luego añadiremos el código para generar el archivo .txt de YOLO
    print(f"Cajas encontradas en la imagen: {len(boxes)}\n")