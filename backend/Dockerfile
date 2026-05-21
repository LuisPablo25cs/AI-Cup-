FROM python:3.12-slim

# Directorio de trabajo dentro del contenedor
WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copiar primero el requirements.txt para aprovechar la caché de Docker
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del proyecto
COPY ./src ./src

# Exponer el puerto que usa Uvicorn
EXPOSE 8000

# Comando para arrancar la aplicación
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]