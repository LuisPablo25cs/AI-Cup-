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
    print("modelo cargado")
    #! Revisa los datos
    model.train(
        #Configuración
        data="datasets/testing/testing.yaml", 
        epochs=1, 
        imgsz=640, 
        project="AI-CUP", 
        name="test_pipeline_1",
        #GPU
        #device=0,
        #!Dockerizar esto ASAP 
        #Aumentación de datos
        erasing=0.4, #Agrega cuadros en negro para que el modelo aprenda a diferenciar 
        hsv_v=0.25, #Varia la saturación de la imgen (cambio de brillo)
        degrees=180, 
        translate=0.20, #Que tanto puede mover una imagen para que no se vea por completo
        shear=10, #Dobla la imagen, valores más altos que esto pueden perjudicar más que ayudar. 
        perspective=0.0025)  #Ayuda a aprender a identificar objetos desde distintas vistas
    

    #? Si eventualmente tenemos varios GPUS agrega device=[0,n] 
    #? Si se interrumpe usa la siguiente linea
    #results = model.train(resume=True)
trainModel()