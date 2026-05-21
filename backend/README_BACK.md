# AI KITTING INSPECTION - BACKEND

El desarrollo se realiza dentro de un contenedor usando Dev Containers. Al abrir el contenedor, el servidor FastAPI arranca automáticamente.

## Requisitos

- Docker Desktop
- Extensión [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) en VS Code
- NVIDIA Container Toolkit (para el servicio de anotación con GPU)

## Abrir el proyecto

1. Clona el repositorio
2. Abre VS Code en la raíz del proyecto
3. `Ctrl + Shift + P` → **Dev Containers: Reopen in Container**

El servidor FastAPI arranca automáticamente en `http://localhost:8000`.  
La documentación interactiva está en `http://localhost:8000/docs`.

## Servicios

El proyecto usa Docker Compose con los siguientes servicios:

| Servicio | Descripción | Puerto |
|---|---|---|
| `backend_server` | API FastAPI (devcontainer) | 8000 |
| `db` | PostgreSQL 16 | 5432 |
| `rabbitmq` | Message broker | 5672 / 15672 |
| `redis` | Cache y cola de tareas | 6379 |
| `ai-tool` | Worker de anotación con GPU | — |
| `blender-tool` | Renderizado automático de imágenes | — |

## Base de datos

La conexión a PostgreSQL está configurada con SQLTools. Para agregar la conexión:

1. `Ctrl + Shift + P` → **SQLTools: Add New Connection**
2. Usa estos datos:

| Campo | Valor |
|---|---|
| Connection name | kitting_db |
| Server Address | db |
| Port | 5432 |
| Database | kitting_db |
| Username | admin |
| Password | admin |

El archivo `kitting_db.sessions.sql` permite hacer queries manuales sin necesidad de tener PostgreSQL instalado localmente.

### Resetear la base de datos

Solo reiniciar el servicio (mantiene datos):
```bash
docker compose restart db
```

Borrar datos y empezar desde cero:
```bash
docker compose down -v   # -v elimina el volumen postgres_data
docker compose up -d
```

Solo borrar tablas desde código:
```python
SQLModel.metadata.drop_all(engine)
SQLModel.metadata.create_all(engine)
```

## Variables de entorno

Las variables de entorno van en un archivo `.env` en la raíz del proyecto. Ejemplo:

```env
DATABASE_URL=postgresql://admin:admin@db:5432/kitting_db
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=...
S3_BUCKET_NAME=...
```

## Comandos útiles

Reconstruir el backend después de cambiar `requirements.txt`:
```bash
docker compose up -d --build backend_server
```

Ver todos los contenedores corriendo:
```bash
docker ps
```

Ver logs de un servicio:
```bash
docker compose logs -f backend_server
```

## Funcionalidades

- Recibir imágenes a partir de una cámara
- Guardar metadata de las imágenes
- Mandar imágenes a almacenamiento en S3
- Detección de objetos vía worker de anotación (RabbitMQ + Redis)