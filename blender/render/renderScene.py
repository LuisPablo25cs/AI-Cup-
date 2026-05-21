import bpy
import math
import os
import sys
import random
from mathutils import Vector

# Recibe la ruta del modelo y la carpeta de salida como argumentos desde la línea de comandos
# Uso: blender -b -P renderScene.py -- /ruta/modelo.obj /ruta/salida
argv = sys.argv
try:
    idx = argv.index("--")
    ruta_modelo  = argv[idx + 1]
    output_dir   = argv[idx + 2]  # Dinámico desde el worker
except (ValueError, IndexError):
    print("No se proporcionó ruta del modelo o carpeta de salida")
    print("Uso: blender -b scene.blend -P renderScene.py -- /ruta/modelo.glb /ruta/salida")
    sys.exit(1)

if not os.path.exists(ruta_modelo):
    print(f"Archivo no encontrado: {ruta_modelo}")
    sys.exit(1)

print(f"\n{'='*60}")
print(f"Modelo: {ruta_modelo}")
print(f"Salida: {output_dir}")
print(f"{'='*60}")

# ============================================================
#  CONFIGURACIÓN
# ============================================================
# En el contenedor, la carpeta de HDRIs se monta en /scenes/hdri
carpeta_hdri    = os.environ.get("HDRI_PATH", "/scenes/hdri")
formato         = "JPEG"
ext             = 'jpg'
samples         = 128
margen_camara   = 4
ESCALA_ESTANDAR = 1.5
ENERGIA_BASE    = 50

fondos_solidos = [
    ("blanco",      (1.00, 1.00, 1.00), 0.8),
    ("gris",        (0.40, 0.40, 0.40), 0.5),
    ("negro",       (0.00, 0.00, 0.00), 0.0),
    ("azul_oscuro", (0.05, 0.05, 0.20), 0.1),
    ("beige",       (0.90, 0.85, 0.70), 0.6),
]

perfiles_luz = [
    ("neutra",    1.0,  (1.00, 1.00, 1.00), (1.00, 1.00, 1.00), (1.00, 1.00, 1.00)),
    ("brillante", 2.0,  (1.00, 1.00, 1.00), (1.00, 1.00, 1.00), (1.00, 1.00, 1.00)),
    ("calida",    1.0,  (1.00, 0.75, 0.40), (1.00, 0.85, 0.60), (1.00, 0.60, 0.20)),
    ("fria",      1.0,  (0.40, 0.60, 1.00), (0.60, 0.80, 1.00), (0.80, 0.90, 1.00)),
    ("dramatica", 1.5,  (1.00, 1.00, 1.00), (0.05, 0.05, 0.05), (1.00, 1.00, 1.00)),
]

vistas = [
    ("frente",        0,   15),
    ("frente_der",   45,   15),
    ("derecha",      90,   15),
    ("atras_der",   135,   15),
    ("atras",       180,   15),
    ("atras_izq",   225,   15),
    ("izquierda",   270,   15),
    ("frente_izq",  315,   15),
    ("alto_frente",   0,   45),
    ("alto_der",     90,   45),
    ("alto_atras",  180,   45),
    ("alto_izq",    270,   45),
    ("top",           0,   85),
    ("bajo_frente",   0,  -15),
    ("bajo_der",     90,  -15),
    ("bajo_atras",  180,  -15),
    ("bajo_izq",    270,  -15),
]
# ============================================================

# --- LIMPIAR ESCENA ---
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# --- IMPORTAR MODELO según extensión ---
extension = os.path.splitext(ruta_modelo)[1].lower()
print(f"   Importando {extension}...")

if extension == '.obj':
    bpy.ops.wm.obj_import(filepath=ruta_modelo)
elif extension in ('.glb', '.gltf'):
    bpy.ops.import_scene.gltf(filepath=ruta_modelo)
elif extension == '.fbx':
    bpy.ops.import_scene.fbx(filepath=ruta_modelo)
elif extension == '.stl':
    bpy.ops.import_mesh.stl(filepath=ruta_modelo)
elif extension == '.ply':
    bpy.ops.import_mesh.ply(filepath=ruta_modelo)
else:
    print(f"Formato no soportado: {extension}")
    sys.exit(1)

print(f"Importado")

# --- SELECCIONAR EL MESH MÁS GRANDE ---
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
if not meshes:
    print("No se encontró ningún mesh tras importar")
    sys.exit(1)

def volumen(o):
    b = [o.matrix_world @ Vector(c) for c in o.bound_box]
    d = [max(v[i] for v in b) - min(v[i] for v in b) for i in range(3)]
    return d[0]*d[1]*d[2]

obj = max(meshes, key=volumen)

print(f"Objeto  : '{obj.name}'")

# --- ORIGEN Y NORMALIZACIÓN ---
scene = bpy.context.scene
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
bpy.context.view_layer.update()

loc_original   = obj.location.copy()
scale_original = obj.scale.copy()
rot_original   = obj.rotation_euler.copy()
obj.location   = (0, 0, 0)
bpy.context.view_layer.update()

bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
max_dim_orig = max(
    max(v.x for v in bbox) - min(v.x for v in bbox),
    max(v.y for v in bbox) - min(v.y for v in bbox),
    max(v.z for v in bbox) - min(v.z for v in bbox),
)
factor = ESCALA_ESTANDAR / max_dim_orig
obj.scale = (
    scale_original.x * factor,
    scale_original.y * factor,
    scale_original.z * factor,
)
bpy.context.view_layer.update()

bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
centro = Vector((
    sum(v.x for v in bbox) / 8,
    sum(v.y for v in bbox) / 8,
    sum(v.z for v in bbox) / 8,
))
alto_obj = max(v.z for v in bbox) - min(v.z for v in bbox)
print(f"   Centro: {centro} | Alto: {alto_obj:.2f}")

#Configurar render 
scene.render.engine = 'CYCLES'
scene.render.use_persisten_data = True
cycles = scene.cycles
scene.render.image_settings.quality = 95

prefs = bpy.context.preferences
cprefs = prefs.addons['cycles'].preferences
cprefs.compute_device_type = 'CUDA'
cprefs.refresh_devices()
for d in cprefs.devices: 
    d.use = (d.type == 'CUDA')
    if d.use: 
        print(f" Activating CUDA GPU: {d.name}")
cycles.device = 'GPU'
cycles.samples = samples
 
# 2. Configurar Denoiser de manera segura y con fallback progresivo
cycles.use_denoising = True
try:
    cycles.denoiser = 'OPENIMAGEDENOISE'
    print("   Using OPENIMAGEDENOISE for denoising")
except TypeError:
    try:
        cycles.denoiser = 'OPTIX'
        print("   Using OPTIX for denoising")
    except TypeError:
        cycles.use_denoising = False
        print("   Warning: OpenImageDenoise and OptiX are not supported in this Blender build. Denoising disabled.")
res_x = 1920
res_y = 1080
scene.render.resolution_x = res_x
scene.render.resolution_y = res_y
scene.render.image_settings.file_format = formato

# --- WORLD NODES ---
world = scene.world
if world is None:
    world = bpy.data.worlds.new("World")
    scene.world = world
world.use_nodes = True
ntree = world.node_tree
ntree.nodes.clear()

node_bg     = ntree.nodes.new('ShaderNodeBackground')
node_env    = ntree.nodes.new('ShaderNodeTexEnvironment')
node_rgb    = ntree.nodes.new('ShaderNodeRGB')
node_mix    = ntree.nodes.new('ShaderNodeMixRGB')
node_output = ntree.nodes.new('ShaderNodeOutputWorld')
ntree.links.new(node_mix.outputs['Color'],     node_bg.inputs['Color'])
ntree.links.new(node_bg.outputs['Background'], node_output.inputs['Surface'])
node_bg.inputs['Strength'].default_value = 1.0

def aplicar_hdri(ruta_hdri, intensidad=1.0):
    img = bpy.data.images.load(ruta_hdri)
    node_env.image = img
    ntree.links.new(node_env.outputs['Color'], node_mix.inputs['Color2'])
    node_mix.inputs['Fac'].default_value = 1.0
    node_bg.inputs['Strength'].default_value = intensidad
    for o in bpy.data.objects:
        if o.type == 'LIGHT' and o.name.startswith('_'):
            o.hide_render = True

def aplicar_fondo_solido(color_rgb, intensidad=0.5):
    node_rgb.outputs['Color'].default_value = (*color_rgb, 1.0)
    ntree.links.new(node_rgb.outputs['Color'], node_mix.inputs['Color1'])
    node_mix.inputs['Fac'].default_value = 0.0
    node_bg.inputs['Strength'].default_value = intensidad
    for o in bpy.data.objects:
        if o.type == 'LIGHT' and o.name.startswith('_'):
            o.hide_render = False

# --- CAMARA ---
cam_obj = scene.camera
if cam_obj is None:
    bpy.ops.object.camera_add()
    cam_obj = bpy.context.object
    scene.camera = cam_obj
cam_obj.constraints.clear()

fov       = cam_obj.data.angle
distancia = (ESCALA_ESTANDAR / 2) / math.tan(fov / 2) * margen_camara

def posicionar_camara(elevacion_deg):
    elev_rad = math.radians(elevacion_deg)
    cam_obj.location = Vector((
        centro.x,
        centro.y - distancia * math.cos(elev_rad),
        centro.z + distancia * math.sin(elev_rad),
    ))
    direction = centro - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam_obj.rotation_mode  = 'XYZ'

# --- LUCES ---
for o in list(bpy.data.objects):
    if o.type == 'LIGHT':
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.lights.remove(data)

def crear_luz(nombre, offset, multiplicador, color):
    ubicacion = Vector((
        centro.x + offset[0] * ESCALA_ESTANDAR,
        centro.y + offset[1] * ESCALA_ESTANDAR,
        centro.z + offset[2] * ESCALA_ESTANDAR,
    ))
    bpy.ops.object.light_add(type='AREA', location=ubicacion)
    luz = bpy.context.object
    luz.name          = nombre
    luz.data.name     = nombre + "_data"
    luz.data.energy   = ENERGIA_BASE * multiplicador
    luz.data.size     = ESCALA_ESTANDAR * 1.5
    luz.data.color[0] = color[0]
    luz.data.color[1] = color[1]
    luz.data.color[2] = color[2]
    direction = centro - luz.location
    luz.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    return luz

luz_key  = crear_luz("_Key",  ( 1.2, -1.0,  1.5), 1.0, (1,1,1))
luz_fill = crear_luz("_Fill", (-1.2, -0.8,  0.5), 0.4, (1,1,1))
luz_rim  = crear_luz("_Rim",  ( 0.0,  1.0,  1.2), 0.6, (1,1,1))

def actualizar_luces(mult, ck, cf, cr):
    luz_key.data.energy    = ENERGIA_BASE * mult
    luz_key.data.color[0]  = ck[0]; luz_key.data.color[1]  = ck[1]; luz_key.data.color[2]  = ck[2]
    luz_fill.data.energy   = ENERGIA_BASE * mult * 0.4
    luz_fill.data.color[0] = cf[0]; luz_fill.data.color[1] = cf[1]; luz_fill.data.color[2] = cf[2]
    luz_rim.data.energy    = ENERGIA_BASE * mult * 0.6
    luz_rim.data.color[0]  = cr[0]; luz_rim.data.color[1]  = cr[1]; luz_rim.data.color[2]  = cr[2]

# --- HDRIs ---
hdris_disponibles = []
if os.path.exists(carpeta_hdri):
    for f in os.listdir(carpeta_hdri):
        if f.lower().endswith(('.hdr', '.exr')):
            hdris_disponibles.append(os.path.join(carpeta_hdri, f))
    print(f"HDRIs: {len(hdris_disponibles)}")

obj.rotation_mode = 'XYZ'
count = 0

# --- PARTE 1: HDRI ---
for ruta_hdri in hdris_disponibles:
    nombre_hdri = os.path.splitext(os.path.basename(ruta_hdri))[0]
    aplicar_hdri(ruta_hdri, intensidad=1.0)
    for nombre_vista, rot_z, elevacion in vistas:
        obj.rotation_euler.z = math.radians(rot_z)
        posicionar_camara(elevacion)
        bpy.context.view_layer.update()
        nombre_img = f"hdri_{nombre_hdri}_{nombre_vista}.{ext}"
        scene.render.filepath = os.path.join(output_dir, nombre_img)
        count += 1
        print(f"  [{count}] {nombre_img}...")
        bpy.ops.render.render(write_still=True)

# --- PARTE 2: FONDOS SÓLIDOS ---
for nombre_fondo, color_fondo, intensidad in fondos_solidos:
    aplicar_fondo_solido(color_fondo, intensidad)
    for nombre_perfil, mult, ck, cf, cr in perfiles_luz:
        actualizar_luces(mult, ck, cf, cr)
        for nombre_vista, rot_z, elevacion in vistas:
            obj.rotation_euler.z = math.radians(rot_z)
            posicionar_camara(elevacion)
            bpy.context.view_layer.update()
            nombre_img = f"{nombre_fondo}_{nombre_perfil}_{nombre_vista}.{ext}"
            scene.render.filepath = os.path.join(output_dir, nombre_img)
            count += 1
            print(f"  [{count}] {nombre_img}...")
            bpy.ops.render.render(write_still=True)

print(f"\nCompletado: {count} renders en {output_dir}")