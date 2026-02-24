from ultralytics import YOLO
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image
import io

app = FastAPI()
PATH_MODELO = "yolov8n-seg.pt"
def inferir(model, img): 
    model = YOLO(model)
    resultado = model(img)
    return resultado

#Endpoint para inferencia
@app.post("/find-objects")
async def find_objects(file: UploadFile = File(...)): 
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))
    res = inferir(PATH_MODELO, image)
    print(res)

#ToDo Endpoint que recibe las imagenes, entrena/re-entrena el modelo. Debe recibir un array de imagenes, el nombre de la clase ¿y el prompt?


