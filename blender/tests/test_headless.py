import subprocess, sys

result = subprocess.run(
    ["blender", "--background", "--python-expr", 
     "import bpy; print('BLENDER_OK'); bpy.ops.wm.quit_blender()"],
    capture_output=True, text=True
)

assert "BLENDER_OK" in result.stdout, f"Blender headless failed:\n{result.stderr}"
print("Headless smoke test passed.")