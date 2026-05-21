FROM python:3.10-slim

# Install system dependencies for OpenCV and PyTorch/Ultralytics
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY . .

CMD ["python", "-u", "src/modelWorker.py"]
