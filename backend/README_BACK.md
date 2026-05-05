# AI KITTING INSPECTION - BACKEND

La produccion se esta realizando en un ambiente basado en el contenedor.

1. Descarga dev containers.
2. ctrl + shift + p
3. reopen in container

El servidor no se abrira automaticamente. Usa el comando:
uvicorn src.runserver:app --host 0.0.0.0 --port 8000 --reload


En caso de error comenzar revisando devcontainer.json
(Se encarga de manejar eso)

Con respecto a los contenedores, estoy considerando dividir esto en dos
uno para el servidor y otro para la base de datos (en lo que se hace deploy a esta)

## Funcionalidades

* Recibir imagenes a partir de una camara
* Guardar metadata de las imagenes
* Mandar imagenes a almacenamiento en S3



##  base de datos

### chistosadas para comprobar
Respecto a la base de datos le agregue una conexion usando SQLTools para facilitar el desarrollo.
kitting_db.sessions.sql
permitira hacer queries a mano para comprobar secciones sin necesidad de tener postgres fuera del contenedor
No se si cada quien ocupa crear su propia conexión pero la mía es de que:
1. ctrl + shift + p
2. SQLTools: Add New Connection

Connection name:  kitting_db
Server Address:   db
Port:             5432
Database:         kitting_db
Username:         admin
Use password:     Save as plaintext
Password:         admin

### reiniciar segun chat

Sí, tienes tres niveles según qué tanto quieres resetear:
Solo reiniciar el servicio (mantiene datos):
docker compose restart db

Borrar datos y empezar desde cero:
docker compose down -v   # -v elimina el volumen postgres_data
docker compose up -d

Solo borrar tablas desde tu código — con SQLModel:

SQLModel.metadata.drop_all(engine)
SQLModel.metadata.create_all(engine)

El -v es la opción clave — sin él down preserva el volumen y tus datos sobreviven.