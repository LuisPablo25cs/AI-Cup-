import bpy
import math
import os
import sys
import random
from mathutils import Vector

# ============================================================
#  CLI ARGUMENTS
# ============================================================
argv = sys.argv
try:
    idx = argv.index("--")
    ruta_modelo = argv[idx + 1]
    output_dir  = argv[idx + 2]
    bag_arg     = argv[idx + 3] if len(argv) > idx + 3 else "none"
except (ValueError, IndexError):
    print("No se proporcionó ruta del modelo o carpeta de salida")
    print("Uso: blender -b -P renderScene.py -- /ruta/modelo.glb /ruta/salida [bag_types]")
    sys.exit(1)

if not os.path.exists(ruta_modelo):
    print(f"Archivo no encontrado: {ruta_modelo}")
    sys.exit(1)

# Parse bag types from comma-separated argument
requested_bag_types = []
if bag_arg and bag_arg != "none":
    requested_bag_types = [b.strip() for b in bag_arg.split(",") if b.strip()]

print(f"\n{'='*60}")
print(f"Modelo: {ruta_modelo}")
print(f"Salida: {output_dir}")
print(f"Bolsas: {requested_bag_types if requested_bag_types else 'Ninguna'}")
print(f"{'='*60}")

# ============================================================
#  BAG TYPE REGISTRY
#  Each entry defines the material and physics for a bag variant.
#  To add a new bag type, just add a new dictionary entry here.
# ============================================================
BAG_REGISTRY = {
    "clear": {
        # Material
        "base_color":   (0.92, 0.96, 0.95, 1.0),
        "alpha":        0.7,
        "transmission": 0.65,
        "roughness":    0.04,
        "ior":          1.47,
        "metallic":     0.0,
        "specular":     0.9,
        "noise_scale":  80.0,
        "noise_detail": 16.0,
        "noise_rough":  0.65,
        "noise_distort":0.15,
        "bump_strength":0.7,
        "bump_distance":0.001,
        # Geometry & Physics
        "scale_padding": 0.75,
        "height_extra":  1.5,
        "subdivisions":  30,
        "shrinkwrap_offset": 0.9,
        "cloth_mass":    0.02,
        "tension":       50,
        "compression":   50,
        "shear":         40,
        "bending":       1.0,
        "air_damping":   20,
        "sim_frames":    60,
    },
    "opaque": {
        "base_color":   (0.95, 0.95, 0.95, 1.0),
        "alpha":        1.0,
        "transmission": 0.0,
        "roughness":    0.15,
        "ior":          1.45,
        "metallic":     0.0,
        "specular":     0.5,
        "noise_scale":  60.0,
        "noise_detail": 12.0,
        "noise_rough":  0.5,
        "noise_distort":0.1,
        "bump_strength":0.5,
        "bump_distance":0.001,
        "scale_padding": 0.75,
        "height_extra":  1.5,
        "subdivisions":  30,
        "shrinkwrap_offset": 0.9,
        "cloth_mass":    0.03,
        "tension":       60,
        "compression":   60,
        "shear":         45,
        "bending":       1.5,
        "air_damping":   25,
        "sim_frames":    60,
    },
}

# Validate requested bag types
for bt in requested_bag_types:
    if bt not in BAG_REGISTRY:
        print(f"WARNING: Unknown bag type '{bt}' — skipping")
requested_bag_types = [bt for bt in requested_bag_types if bt in BAG_REGISTRY]

# ============================================================
#  CONFIGURATION
# ============================================================
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
#  SCENE SETUP (identical to your current renderScene.py)
# ============================================================

# --- CLEAN SCENE ---
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# --- IMPORT MODEL ---
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

# --- SELECT LARGEST MESH ---
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

# --- ORIGIN & NORMALIZATION ---
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

# --- CYCLES + GPU ---
scene.render.engine = 'CYCLES'
scene.render.use_persistent_data = True
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
        print("   Warning: Denoising disabled.")

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

# --- CAMERA ---
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

# --- LIGHTS ---
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

# ============================================================
#  PLASTIC BAG FUNCTIONS (parameterized from registry)
# ============================================================
def crear_material_plastico(config):
    mat = bpy.data.materials.new(name="_MatBolsa")
    mat.use_nodes = True
    nodos = mat.node_tree.nodes
    links = mat.node_tree.links
    nodos.clear()

    output     = nodos.new('ShaderNodeOutputMaterial')
    principled = nodos.new('ShaderNodeBsdfPrincipled')
    noise      = nodos.new('ShaderNodeTexNoise')
    bump       = nodos.new('ShaderNodeBump')

    principled.inputs['Base Color'].default_value  = config["base_color"]
    principled.inputs['Metallic'].default_value    = config["metallic"]
    principled.inputs['Roughness'].default_value   = config["roughness"]
    principled.inputs['IOR'].default_value         = config["ior"]
    principled.inputs['Alpha'].default_value       = config["alpha"]

    try:
        principled.inputs['Specular IOR Level'].default_value = config["specular"]
    except:
        pass
    try:
        principled.inputs['Transmission Weight'].default_value = config["transmission"]
    except:
        try:
            principled.inputs['Transmission'].default_value = config["transmission"]
        except:
            pass

    noise.inputs['Scale'].default_value      = config["noise_scale"]
    noise.inputs['Detail'].default_value     = config["noise_detail"]
    noise.inputs['Roughness'].default_value  = config["noise_rough"]
    noise.inputs['Distortion'].default_value = config["noise_distort"]
    bump.inputs['Strength'].default_value    = config["bump_strength"]
    bump.inputs['Distance'].default_value    = config["bump_distance"]

    links.new(noise.outputs['Fac'],       bump.inputs['Height'])
    links.new(bump.outputs['Normal'],     principled.inputs['Normal'])
    links.new(principled.outputs['BSDF'], output.inputs['Surface'])

    try:
        mat.blend_method        = 'BLEND'
        mat.shadow_method       = 'CLIP'
        mat.use_backface_culling = False
    except AttributeError:
        pass

    return mat

def crear_bolsa(obj_target, config):
    print(f"\n   Creando bolsa de plastico...")

    bbox = [obj_target.matrix_world @ Vector(c) for c in obj_target.bound_box]
    centro_obj = Vector((
        sum(v.x for v in bbox) / 8,
        sum(v.y for v in bbox) / 8,
        sum(v.z for v in bbox) / 8,
    ))
    dim_x = max(v.x for v in bbox) - min(v.x for v in bbox)
    dim_y = max(v.y for v in bbox) - min(v.y for v in bbox)
    dim_z = max(v.z for v in bbox) - min(v.z for v in bbox)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=centro_obj)
    bolsa = bpy.context.object
    bolsa.name = "_Bolsa"

    padding = config["scale_padding"]
    bolsa.scale = (
        dim_x * padding + 1.0,
        dim_y * padding + 1.0,
        dim_z * padding + config["height_extra"],
    )
    bpy.ops.object.transform_apply(scale=True)

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=config["subdivisions"])
    bpy.ops.object.mode_set(mode='OBJECT')

    mod_sw = bolsa.modifiers.new("Shrinkwrap", 'SHRINKWRAP')
    mod_sw.target      = obj_target
    mod_sw.wrap_method = 'NEAREST_SURFACEPOINT'
    mod_sw.offset      = config["shrinkwrap_offset"]
    mod_sw.wrap_mode   = 'ON_SURFACE'

    bpy.ops.object.select_all(action='DESELECT')
    bolsa.select_set(True)
    bpy.context.view_layer.objects.active = bolsa
    bpy.ops.object.modifier_apply(modifier="Shrinkwrap")

    mod_col = obj_target.modifiers.new("_Collision", 'COLLISION')
    mod_col.settings.thickness_outer = 0.005
    mod_col.settings.thickness_inner = 0.002

    mod_cloth = bolsa.modifiers.new("Cloth", 'CLOTH')
    s = mod_cloth.settings
    s.quality               = 15
    s.mass                  = config["cloth_mass"]
    s.tension_stiffness     = config["tension"]
    s.compression_stiffness = config["compression"]
    s.shear_stiffness       = config["shear"]
    s.bending_stiffness     = config["bending"]
    s.tension_damping       = 5
    s.compression_damping   = 5
    s.shear_damping         = 5
    s.bending_damping       = 1.0
    s.air_damping           = config["air_damping"]

    col = mod_cloth.collision_settings
    col.use_collision      = True
    col.distance_min       = 0.003
    col.use_self_collision = False

    sim_frames = config["sim_frames"]
    print(f"   Simulando {sim_frames} frames...")
    for frame in range(1, sim_frames + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        if frame % 15 == 0:
            print(f"   Frame {frame}/{sim_frames}...")

    print("   Fisica completada, aplicando...")

    bpy.ops.object.select_all(action='DESELECT')
    bolsa.select_set(True)
    bpy.context.view_layer.objects.active = bolsa
    for mod in list(bolsa.modifiers):
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception as e:
            print(f"   No se pudo aplicar {mod.name}: {e}")

    bpy.ops.object.modifier_add(type='SMOOTH')
    bolsa.modifiers[-1].iterations = 2
    try:
        bpy.ops.object.modifier_apply(modifier=bolsa.modifiers[-1].name)
    except:
        pass

    for mod in list(obj_target.modifiers):
        if mod.name == "_Collision":
            obj_target.modifiers.remove(mod)

    mat = crear_material_plastico(config)
    if bolsa.data.materials:
        bolsa.data.materials[0] = mat
    else:
        bolsa.data.materials.append(mat)

    try:
        scene.cycles.caustics_refractive = True
        scene.cycles.caustics_reflective = True
    except:
        pass

    scene.frame_set(1)
    print("   Bolsa lista")
    return bolsa

def eliminar_bolsa(bolsa):
    if bolsa and bolsa.name in bpy.data.objects:
        mat = bolsa.data.materials[0] if bolsa.data.materials else None
        bpy.data.objects.remove(bolsa, do_unlink=True)
        if mat and mat.name in bpy.data.materials:
            bpy.data.materials.remove(mat)
    scene.frame_set(1)

# ============================================================
#  CENTRAL RENDER FUNCTION
# ============================================================
def renderizar_todas_las_vistas(carpeta_destino, bolsa=None):
    """Renders all HDRIs + solid backgrounds into the given folder."""
    global count

    # --- PART 1: HDRIs ---
    for ruta_hdri in hdris_disponibles:
        nombre_hdri = os.path.splitext(os.path.basename(ruta_hdri))[0]
        aplicar_hdri(ruta_hdri, intensidad=1.0)
        for nombre_vista, rot_z, elevacion in vistas:
            obj.rotation_euler.z = math.radians(rot_z)
            if bolsa:
                bolsa.rotation_euler.z = math.radians(rot_z)
            posicionar_camara(elevacion)
            bpy.context.view_layer.update()
            nombre_img = f"hdri_{nombre_hdri}_{nombre_vista}.{ext}"
            scene.render.filepath = os.path.join(carpeta_destino, nombre_img)
            count += 1
            print(f"  [{count}] {nombre_img}...")
            bpy.ops.render.render(write_still=True)

    # --- PART 2: SOLID BACKGROUNDS ---
    for nombre_fondo, color_fondo, intensidad in fondos_solidos:
        aplicar_fondo_solido(color_fondo, intensidad)
        for nombre_perfil, mult, ck, cf, cr in perfiles_luz:
            actualizar_luces(mult, ck, cf, cr)
            for nombre_vista, rot_z, elevacion in vistas:
                obj.rotation_euler.z = math.radians(rot_z)
                if bolsa:
                    bolsa.rotation_euler.z = math.radians(rot_z)
                posicionar_camara(elevacion)
                bpy.context.view_layer.update()
                nombre_img = f"{nombre_fondo}_{nombre_perfil}_{nombre_vista}.{ext}"
                scene.render.filepath = os.path.join(carpeta_destino, nombre_img)
                count += 1
                print(f"  [{count}] {nombre_img}...")
                bpy.ops.render.render(write_still=True)

# ============================================================
#  LOAD HDRIs
# ============================================================
hdris_disponibles = []
if os.path.exists(carpeta_hdri):
    for f in os.listdir(carpeta_hdri):
        if f.lower().endswith(('.hdr', '.exr')):
            hdris_disponibles.append(os.path.join(carpeta_hdri, f))
    print(f"HDRIs: {len(hdris_disponibles)}")

obj.rotation_mode = 'XYZ'
count = 0

# ============================================================
#  CREATE OUTPUT DIRECTORIES
# ============================================================
carpeta_sin_bolsa = os.path.join(output_dir, "sin_bolsa")
os.makedirs(carpeta_sin_bolsa, exist_ok=True)

# ============================================================
#  RENDER PHASE 1: WITH BAG (for each requested bag type)
# ============================================================
for bag_type in requested_bag_types:
    config = BAG_REGISTRY[bag_type]
    carpeta_con_bolsa = os.path.join(output_dir, f"con_bolsa_{bag_type}")
    os.makedirs(carpeta_con_bolsa, exist_ok=True)

    print(f"\n{'='*50}")
    print(f"MODO: CON BOLSA ({bag_type})")
    print(f"{'='*50}")
    bolsa = crear_bolsa(obj, config)
    renderizar_todas_las_vistas(carpeta_con_bolsa, bolsa=bolsa)
    eliminar_bolsa(bolsa)

# ============================================================
#  RENDER PHASE 2: WITHOUT BAG (always runs)
# ============================================================
print(f"\n{'='*50}")
print("MODO: SIN BOLSA")
print(f"{'='*50}")
renderizar_todas_las_vistas(carpeta_sin_bolsa, bolsa=None)

print(f"\nCompletado: {count} renders en {output_dir}")