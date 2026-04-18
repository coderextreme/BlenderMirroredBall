import bpy
import mathutils
import math
import os
import tempfile

def clean_scene():
    """Clears the scene of all objects, meshes, and materials."""
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # Deep clean data blocks to prevent naming conflicts
    for block in bpy.data.meshes: bpy.data.meshes.remove(block)
    for block in bpy.data.materials: bpy.data.materials.remove(block)
    for block in bpy.data.lights: bpy.data.lights.remove(block)
    for block in bpy.data.cameras: bpy.data.cameras.remove(block)

def create_material(name, color, metallic=0.0, roughness=0.5):
    """Helper to create a simple material."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    
    # Safe input setting for Blender 4.0+ / 5.0
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
    return mat

def write_manual_x3d(filepath, frame_number):
    """
    Manually writes a basic X3D file without using plugins.
    It captures the mesh state at the specific frame (including modifier deformations).
    """
    print(f"Starting Manual X3D Export to {filepath}...")
    
    # Move to the desired frame to capture the 'crumbled' state
    bpy.context.scene.frame_set(frame_number)
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()

    with open(filepath, "w", encoding="utf-8") as f:
        # X3D Header
        f.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        f.write("<!DOCTYPE X3D PUBLIC 'ISO//Web3D//DTD X3D 3.3//EN' 'http://www.web3d.org/specifications/x3d-3.3.dtd'>\n")
        f.write("<X3D profile='Interchange' version='3.3' xmlns:xsd='http://www.w3.org/2001/XMLSchema-instance'>\n")
        f.write("  <Scene>\n")
        f.write("    <Background skyColor='0.05 0.05 0.05'/>\n")

        # Loop through visible objects
        for obj in bpy.context.scene.objects:
            if obj.type not in ['MESH']:
                continue
            
            # Get the mesh with modifiers applied (Cloth, etc)
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            
            # Calculate simple color (take first material or default white)
            color_str = "0.8 0.8 0.8"
            if len(obj.data.materials) > 0:
                try:
                    # Try to grab base color from node
                    mat = obj.data.materials[0]
                    nodes = mat.node_tree.nodes
                    bsdf = nodes.get("Principled BSDF")
                    c = bsdf.inputs["Base Color"].default_value
                    color_str = f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f}"
                except:
                    pass

            f.write(f"    <Transform translation='{obj.location.x:.4f} {obj.location.y:.4f} {obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write(f"        <Appearance><Material diffuseColor='{color_str}'/></Appearance>\n")
            f.write("        <IndexedFaceSet coordIndex='")
            
            # Write Face Indices
            # X3D uses -1 as a face separator
            for poly in mesh.polygons:
                for loop_index in poly.loop_indices:
                    vert_index = mesh.loops[loop_index].vertex_index
                    f.write(f"{vert_index} ")
                f.write("-1 ")
            
            f.write("'>\n")
            
            # Write Vertices
            f.write("          <Coordinate point='")
            for v in mesh.vertices:
                # Vertices in evaluated mesh are usually local to object, 
                # but if modifiers move them drastically, we rely on local coords
                # combined with the object Transform we wrote earlier.
                f.write(f"{v.co.x:.4f} {v.co.y:.4f} {v.co.z:.4f} ")
            f.write("'/>\n")
            
            f.write("        </IndexedFaceSet>\n")
            f.write("      </Shape>\n")
            f.write("    </Transform>\n")
            
            # Clean up temp mesh
            eval_obj.to_mesh_clear()

        f.write("  </Scene>\n")
        f.write("</X3D>\n")
    
    print("Export Complete.")

def main():
    clean_scene()
    
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 120
    
    # 1. MIRROR BALL
    ball_radius = 1.0
    bpy.ops.mesh.primitive_uv_sphere_add(radius=ball_radius, segments=64, ring_count=32, location=(0, 0, ball_radius))
    ball = bpy.context.object
    ball.name = "MirrorBall"
    bpy.ops.object.shade_smooth()
    
    # Add Mirror Material
    mat_mirror = create_material("Chrome", (0.8, 0.8, 0.8, 1), metallic=1.0, roughness=0.0)
    ball.data.materials.append(mat_mirror)
    
    # Physics Collision for Ball
    bpy.ops.object.modifier_add(type='COLLISION')
    ball.modifiers["Collision"].settings.thickness_outer = 0.02

    # 2. FLOOR (At level of bottom of ball Z=0)
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "Floor"
    mat_floor = create_material("FloorMat", (0.1, 0.1, 0.1, 1))
    floor.data.materials.append(mat_floor)
    
    # Physics Collision for Floor
    bpy.ops.object.modifier_add(type='COLLISION')

    # 3. CLOTH SHEET
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=60, y_subdivisions=60, size=4, location=(0, 0, ball_radius * 2.5))
    cloth_obj = bpy.context.object
    cloth_obj.name = "Sheet"
    bpy.ops.object.shade_smooth()
    
    mat_cloth = create_material("Velvet", (0.8, 0.1, 0.1, 1), metallic=0.0, roughness=1.0)
    cloth_obj.data.materials.append(mat_cloth)

    # 4. HOOK SETUP (For pulling)
    # Create Vertex Group for the center
    vg = cloth_obj.vertex_groups.new(name="PullGroup")
    
    # Logic to select center vertices
    # We must access mesh data directly
    mesh = cloth_obj.data
    center_indices = []
    for v in mesh.vertices:
        if (v.co.x**2 + v.co.y**2) < 0.15: # Small radius in center
            center_indices.append(v.index)
    vg.add(center_indices, 1.0, 'REPLACE')

    # Add Hook Empty
    bpy.ops.object.empty_add(type='SPHERE', radius=0.5, location=(0, 0, ball_radius * 3))
    hook_empty = bpy.context.object
    hook_empty.name = "HookHandle"

    # Add Modifiers to Cloth Object
    bpy.context.view_layer.objects.active = cloth_obj
    
    # Hook Modifier
    bpy.ops.object.modifier_add(type='HOOK')
    mod_hook = cloth_obj.modifiers["Hook"]
    mod_hook.object = hook_empty
    mod_hook.vertex_group = "PullGroup"
    
    # Cloth Modifier
    bpy.ops.object.modifier_add(type='CLOTH')
    mod_cloth = cloth_obj.modifiers["Cloth"]
    
    # --- FIX FOR BLENDER 5.0 / 4.2 API ---
    # use_self_collision is now often under collision_settings
    c_settings = mod_cloth.settings
    c_settings.quality = 6
    c_settings.mass = 0.3
    
    # Handle API differences for Collision settings
    if hasattr(c_settings, "collision_settings"):
        c_settings.collision_settings.use_self_collision = True
        c_settings.collision_settings.distance_min = 0.01
    elif hasattr(c_settings, "use_self_collision"):
        # Legacy fallback
        c_settings.use_self_collision = True
        
    # 5. ANIMATION
    # Animate Hook Location
    # Frame 1: Start
    hook_empty.location = (0, 0, ball_radius * 2.2)
    hook_empty.keyframe_insert(data_path="location", frame=1)
    
    # Frame 30: Still resting
    hook_empty.keyframe_insert(data_path="location", frame=30)
    
    # Frame 50: Pull Up and Away
    hook_empty.location = (2.5, 2.5, 5.0)
    hook_empty.keyframe_insert(data_path="location", frame=50)
    
    # Animate Hook Strength (Release)
    mod_hook.strength = 1.0
    mod_hook.keyframe_insert(data_path="strength", frame=50)
    
    mod_hook.strength = 0.0 # Let go
    mod_hook.keyframe_insert(data_path="strength", frame=55)

    # 6. LIGHTING
    for i in range(3):
        angle = (i / 3) * (2 * math.pi)
        dist = 5
        x = math.cos(angle) * dist
        y = math.sin(angle) * dist
        bpy.ops.object.light_add(type='SPOT', location=(x, y, 6))
        light = bpy.context.object
        light.data.energy = 4000 # Watts
        light.data.spot_size = 0.8
        
        # Track to ball
        track = light.constraints.new(type='TRACK_TO')
        track.target = ball
        track.track_axis = 'TRACK_NEGATIVE_Z'
        track.up_axis = 'UP_Y'

    # 7. RUN SIMULATION & EXPORT
    print("Scene setup complete. Running simulation to frame 100 for export...")
    
    # We set frame to 100 to let the physics calculate the 'crumpled' state
    # This might take a second in the UI
    target_frame = 100
    
    # Define file path in Temp folder
    filename = "mirrored_ball_crumbled.x3d"
    export_path = os.path.join(tempfile.gettempdir(), filename)
    
    # Run the manual exporter
    write_manual_x3d(export_path, target_frame)
    
    print(f"X3D file saved to: {export_path}")
    
    # Return to start
    bpy.context.scene.frame_set(1)

if __name__ == "__main__":
    main()
