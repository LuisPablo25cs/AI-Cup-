import bpy
import math
import os
import sys
from mathutils import Vector

argv = sys.argv
try:
    idx = argv.index("--")
    ruta_modelo  = argv[idx + 1]
    output_dir   = argv[idx + 2]   # staging dir passed by worker
except (ValueError, IndexError):
    print("Usage: blender -b scene.blend -P renderScene.py -- /path/model.glb /path/output/")
    sys.exit(1)

if not os.path.exists(ruta_modelo):
    print(f"Model not found: {ruta_modelo}")
    sys.exit(1)

os.makedirs(output_dir, exist_ok=True)

# ── Config ────────────────────────────────────────────────────
ESCALA_ESTANDAR = 1.5
ENERGIA_BASE    = 50
samples         = 64        # lower than 128 for speed in pipeline
margen_camara   = 4

fondos_solidos = [
    ("blanco", (1.00, 1.00, 1.00), 0.8),
    ("gris",   (0.40, 0.40, 0.40), 0.5),
    ("negro",  (0.00, 0.00, 0.00), 0.0),
]

perfiles_luz = [
    ("neutra",    1.0, (1,1,1), (1,1,1), (1,1,1)),
    ("brillante", 2.0, (1,1,1), (1,1,1), (1,1,1)),
]

vistas = [
    ("frente",      0,  15),
    ("derecha",    90,  15),
    ("atras",     180,  15),
    ("izquierda", 270,  15),
    ("alto",        0,  85),
    ("bajo",        0, -15),
]

# ── Clean scene ───────────────────────────────────────────────
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── Import model ──────────────────────────────────────────────
ext = os.path.splitext(ruta_modelo)[1].lower()
if ext in ('.glb', '.gltf'):
    bpy.ops.import_scene.gltf(filepath=ruta_modelo)
elif ext == '.obj':
    bpy.ops.wm.obj_import(filepath=ruta_modelo)
elif ext == '.fbx':
    bpy.ops.import_scene.fbx(filepath=ruta_modelo)
elif ext == '.stl':
    bpy.ops.import_mesh.stl(filepath=ruta_modelo)
else:
    print(f"Unsupported format: {ext}")
    sys.exit(1)

# ── Select largest mesh ───────────────────────────────────────
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
if not meshes:
    print("No mesh found after import")
    sys.exit(1)

def volumen(o):
    b = [o.matrix_world @ Vector(c) for c in o.bound_box]
    d = [max(v[i] for v in b) - min(v[i] for v in b) for i in range(3)]
    return d[0]*d[1]*d[2]

obj = max(meshes, key=volumen)

# ── Normalize ─────────────────────────────────────────────────
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
bpy.context.view_layer.update()

scale_original = obj.scale.copy()
obj.location = (0, 0, 0)
bpy.context.view_layer.update()

bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
max_dim = max(
    max(v.x for v in bbox) - min(v.x for v in bbox),
    max(v.y for v in bbox) - min(v.y for v in bbox),
    max(v.z for v in bbox) - min(v.z for v in bbox),
)
factor = ESCALA_ESTANDAR / max_dim
obj.scale = (scale_original.x * factor, scale_original.y * factor, scale_original.z * factor)
bpy.context.view_layer.update()

bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
centro = Vector((
    sum(v.x for v in bbox) / 8,
    sum(v.y for v in bbox) / 8,
    sum(v.z for v in bbox) / 8,
))

# ── Render config ─────────────────────────────────────────────
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'GPU'
scene.cycles.samples = samples
scene.cycles.use_denoising = True
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.image_settings.file_format = 'PNG'

# GPU setup
prefs  = bpy.context.preferences
cprefs = prefs.addons['cycles'].preferences
cprefs.refresh_devices()
for tipo in ['OPTIX', 'CUDA']:
    try:
        cprefs.compute_device_type = tipo
        cprefs.refresh_devices()
        gpus = [d for d in cprefs.devices if d.type == tipo]
        if gpus:
            for d in cprefs.devices:
                d.use = (d.type == tipo)
            break
    except:
        continue

# ── World / background ────────────────────────────────────────
world = scene.world or bpy.data.worlds.new("World")
scene.world = world
world.use_nodes = True
ntree = world.node_tree
ntree.nodes.clear()

node_bg     = ntree.nodes.new('ShaderNodeBackground')
node_rgb    = ntree.nodes.new('ShaderNodeRGB')
node_mix    = ntree.nodes.new('ShaderNodeMixRGB')
node_output = ntree.nodes.new('ShaderNodeOutputWorld')
ntree.links.new(node_mix.outputs['Color'],     node_bg.inputs['Color'])
ntree.links.new(node_bg.outputs['Background'], node_output.inputs['Surface'])

def aplicar_fondo_solido(color_rgb, intensidad):
    node_rgb.outputs['Color'].default_value = (*color_rgb, 1.0)
    ntree.links.new(node_rgb.outputs['Color'], node_mix.inputs['Color1'])
    node_mix.inputs['Fac'].default_value = 0.0
    node_bg.inputs['Strength'].default_value = intensidad

# ── Camera ────────────────────────────────────────────────────
if not scene.camera:
    bpy.ops.object.camera_add()
    scene.camera = bpy.context.object
cam_obj = scene.camera
cam_obj.constraints.clear()

fov       = cam_obj.data.angle
distancia = (ESCALA_ESTANDAR / 2) / math.tan(fov / 2) * margen_camara

def posicionar_camara(rot_z_deg, elevacion_deg):
    elev_rad = math.radians(elevacion_deg)
    cam_obj.location = Vector((
        centro.x,
        centro.y - distancia * math.cos(elev_rad),
        centro.z + distancia * math.sin(elev_rad),
    ))
    obj.rotation_euler.z = math.radians(rot_z_deg)
    direction = centro - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()

# ── Lights ────────────────────────────────────────────────────
for o in list(bpy.data.objects):
    if o.type == 'LIGHT':
        bpy.data.objects.remove(o, do_unlink=True)

def crear_luz(nombre, offset, energy, color):
    bpy.ops.object.light_add(type='AREA', location=Vector((
        centro.x + offset[0] * ESCALA_ESTANDAR,
        centro.y + offset[1] * ESCALA_ESTANDAR,
        centro.z + offset[2] * ESCALA_ESTANDAR,
    )))
    luz = bpy.context.object
    luz.name = nombre
    luz.data.energy = energy
    luz.data.size   = ESCALA_ESTANDAR * 1.5
    luz.data.color  = color
    luz.rotation_euler = (centro - luz.location).to_track_quat('-Z','Y').to_euler()
    return luz

luz_key  = crear_luz("Key",  ( 1.2, -1.0,  1.5), ENERGIA_BASE,       (1,1,1))
luz_fill = crear_luz("Fill", (-1.2, -0.8,  0.5), ENERGIA_BASE * 0.4, (1,1,1))
luz_rim  = crear_luz("Rim",  ( 0.0,  1.0,  1.2), ENERGIA_BASE * 0.6, (1,1,1))

def actualizar_luces(mult, ck, cf, cr):
    luz_key.data.energy  = ENERGIA_BASE * mult
    luz_key.data.color   = ck
    luz_fill.data.energy = ENERGIA_BASE * mult * 0.4
    luz_fill.data.color  = cf
    luz_rim.data.energy  = ENERGIA_BASE * mult * 0.6
    luz_rim.data.color   = cr

# ── Render loop ───────────────────────────────────────────────
obj.rotation_mode = 'XYZ'
count = 0

for nombre_fondo, color_fondo, intensidad in fondos_solidos:
    aplicar_fondo_solido(color_fondo, intensidad)
    for nombre_perfil, mult, ck, cf, cr in perfiles_luz:
        actualizar_luces(mult, ck, cf, cr)
        for nombre_vista, rot_z, elevacion in vistas:
            posicionar_camara(rot_z, elevacion)
            nombre_img = f"{nombre_fondo}_{nombre_perfil}_{nombre_vista}.png"
            scene.render.filepath = os.path.join(output_dir, nombre_img)
            count += 1
            print(f"[{count}] Rendering {nombre_img}...")
            bpy.ops.render.render(write_still=True)

print(f"Done: {count} renders in {output_dir}")