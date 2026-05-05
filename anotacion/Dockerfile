FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-devel

# Configurar CUDA
ENV DEBIAN_FRONTEND=noninteractive
ENV FORCE_CUDA="1"
ENV TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9;9.0"

# Instalar dependencias del sistema 
RUN apt-get update && apt-get install -y \
    git build-essential libgl1-mesa-glx libglib2.0-0 wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Forzar compatibilidad de versiones
RUN pip install --no-cache-dir wheel "numpy<2.0.0"

# 2. Librerias 
RUN pip install --no-cache-dir \
    opencv-python matplotlib onnxruntime-gpu \
    fastapi uvicorn python-multipart supervision \ 
    "filelock<=3.12.4" "transformers<=4.38.2" \
    comet-ml


# 3. Clonar directamente en la ruta correcta 
RUN git clone https://github.com/IDEA-Research/GroundingDINO.git /app/GroundingDINO
WORKDIR /app/GroundingDINO
RUN pip install --no-cache-dir --no-build-isolation -e .

# 4. Instalar SAM
RUN pip install git+https://github.com/facebookresearch/segment-anything.git

# 5. Volver a la raíz y preparar carpetas
WORKDIR /app
RUN mkdir -p weights Datasets outputs
RUN wget -q https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth -P weights/ && \
    wget -q https://dl.fbaipublicfiles.com/segment_anything/sam_vit_h_4b8939.pth -P weights/

# Copiar script al contenedor
RUN pip install "numpy<2.0.0" --force-reinstall
COPY dino.py /app/dino.py

CMD ["python", "dino.py"]