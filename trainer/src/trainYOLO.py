from ultralytics import YOLO
from dotenv import load_dotenv
import os
import comet_ml
def trainModel(): 
    #Inicializar Comet-ml, herramienta para ejecutar experimentos y mejor analisis de entrenamiento de modelos. 
    cometApiKey = os.getenv("COMET_API_KEY")
    comet_ml.init(project_name="AI-CUP", api_key=cometApiKey)

    #Ejemplo de como agregar tracks e iniciar experimentos 
    """
    experiment = comet_ml.get_global_experiment()
    experiment.add_tag("v1-dino-auto-label")
    experiment.log_parameter("dvc_dataset_hash", "a1b2c3d4")
    """

    model = YOLO("yolov8n-seg.pt")
    path = "path"
    print("modelo cargado")
    #! Revisa los datos
    model.train(
        #Configuración
        data=str(path), 
        epochs=100, 
        patience=15, 
        imgsz=640, 
        project="AI-CUP", 
        freeze=10, 
        #GPU
        device=0,
        #Aumentación de datos
        erasing=0.3, #Agrega cuadros en negro para que el modelo aprenda a diferenciar 
        hsv_v=0.015, #Varia la saturación de la imgen (cambio de brillo)
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=45, 
        translate=0.20, #Que tanto puede mover una imagen para que no se vea por completo
        shear=10, #Dobla la imagen, valores más altos que esto pueden perjudicar más que ayudar. 
        perspective=0.001,
        mosaic=1.0, 
        copy_paste=0.1,
        mixup=0.1,
        scale=0.5,
        )  #Ayuda a aprender a identificar objetos desde distintas vistas
    

    #? Si eventualmente tenemos varios GPUS agrega device=[0,n] 
    #? Si se interrumpe usa la siguiente linea
    #results = model.train(resume=True)
trainModel()