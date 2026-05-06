import bpy, sys

argv = sys.argv[sys.argv.index("--")+ 1:]
output_path = argv[0]
frame_index = int(argv[1])
total_frames = int(argv[2])

#Aqui va laS Bris cosas

bpy.context.scene.render.filepath = output_path
bpy.context.scene.render.image_settings.file_format = "PNG"
bpy.ops.render.render(write_still=True)