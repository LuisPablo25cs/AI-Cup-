# AI Kitting Inspection

Sistema de inspección visual automatizada de kits industriales. Permite verificar que los kits de ensamble contengan las piezas correctas usando visión artificial, reduciendo errores en línea de producción.

## ¿Cómo funciona?

Los usuarios interactúan con una interfaz web para gestionar piezas y kits. Las cámaras capturan imágenes de los kits en la línea de producción, que se envían al servidor principal vía REST. El sistema procesa las imágenes con modelos de detección de objetos y retorna una validación de aprobado o denegado.

Para el entrenamiento de modelos, las imágenes de referencia se generan sintéticamente con renders de Blender (Fotrotrón3000), evitando la necesidad de fotografiar manualmente cada pieza.

```
Usuarios / Cámaras
       │
       │ REST
       ▼
  Server Principal          ──► Server Anotación (GroundingDINO + SAM)
  (FastAPI / Async)         ──► Server Entrenamiento
       │                    ──► Fotrotrón3000 (Blender)
       ├── Base de Datos (PostgreSQL)
       ├── Cache (Redis)
       └── Almacenamiento (AWS S3)
```

## Funcionalidades

- Seleccionar un kit y visualizar resultado de inspección (aprobado / denegado)
- Registrar nuevas piezas y kits
- Entrenamiento de nuevos modelos de detección
- Generación sintética de imágenes de entrenamiento vía Blender
- Visualización de KPIs de inspección

## Servicios

| Servicio | Descripción | Tecnología |
|---|---|---|
| `backend_server` | API principal y lógica de negocio | FastAPI + PostgreSQL |
| `db` | Base de datos relacional | PostgreSQL 16 |
| `rabbitmq` | Cola de mensajes entre servicios | RabbitMQ |
| `redis` | Cache y estado compartido | Redis |
| `ai-tool` | Worker de detección y anotación | GroundingDINO + SAM |
| `blender-tool` | Generación sintética de imágenes | Blender (Fototrón3000) |


## Requisitos

- Docker Desktop
- NVIDIA Container Toolkit (para el servicio de anotación)
- VS Code con extensión [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

## Levantar el proyecto

```bash
docker compose up -d
```

Para desarrollo del backend, abre VS Code en la raíz y usa:

`Ctrl + Shift + P` → **Dev Containers: Reopen in Container**

El servidor FastAPI estará disponible en `http://localhost:8000`  
Documentación interactiva en `http://localhost:8000/docs`  
Panel de RabbitMQ en `http://localhost:15672` (guest / guest)

## Variables de entorno

Crea un archivo `.env` en la raíz con las siguientes variables (nunca subas este archivo al repositorio):

```env
DATABASE_URL=postgresql://admin:admin@db:5432/kitting_db
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=...
S3_BUCKET_NAME=...
```

## Documentación por servicio

Cada servicio tiene su propio README con instrucciones específicas de desarrollo:

- [`backend/README.md`](./backend/README.md) — API, base de datos, devcontainer
