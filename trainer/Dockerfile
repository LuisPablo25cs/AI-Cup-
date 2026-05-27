FROM python:3.10-slim

# Install system libraries required by OpenCV (which is used by Ultralytics)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the pipeline orchestrator worker as a module so relative imports resolve correctly
CMD ["python", "-u", "-m", "src.modelWorker"]