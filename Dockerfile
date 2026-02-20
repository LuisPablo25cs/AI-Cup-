# Imagen base con CUDA 12.1
FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-devel

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    git build-essential libgl1-mesa-glx libglib2.0-0 wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalación de librerías base
RUN pip install --no-cache-dir \
    opencv-python matplotlib onnxruntime-gpu \
    fastapi uvicorn python-multipart supervision

# --- INSTALACIÓN GROUNDING DINO ---
RUN git clone https://github.com/IDEA-Research/GroundingDINO.git .
RUN pip install -r requirements.txt
RUN pip install -e .

# --- INSTALACIÓN SAM (Segment Anything) ---
RUN pip install git+https://github.com/facebookresearch/segment-anything.git

# Crear carpetas para el flujo de trabajo
RUN mkdir -p weights datasets outputs

# Descarga de pesos para ambos modelos
RUN wget -q https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth -P weights/ && \
    wget -q https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth -P weights/

# COPIAR EL PROYECTO (Para producción)
# Nota: Durante el desarrollo usamos volúmenes, pero esto asegura que el código esté dentro
COPY . /app

CMD ["python", "app.py"]