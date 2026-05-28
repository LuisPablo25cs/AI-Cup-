FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Install Python 3.10 and system libraries required by OpenCV (which is used by Ultralytics)
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python

WORKDIR /app

COPY requirements.txt .

# Install PyTorch compiled for CUDA 12.1 BEFORE installing ultralytics,
# so ultralytics picks up the existing torch instead of pulling the latest (cu130)
RUN pip install --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cu121

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the pipeline orchestrator worker as a module so relative imports resolve correctly
CMD ["python", "-u", "-m", "src.modelWorker"]