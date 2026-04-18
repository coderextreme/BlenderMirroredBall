import bpy
import bmesh
import math
import os
import tempfile

def clean_scene():
    """Clears the scene of all objects, meshes, materials, and collections."""
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
        
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # Deep clean data blocks
    for block in bpy.data.meshes: bpy.data.meshes.remove(block)
    for block in bpy.data.materials: bpy.data.materials.remove(block)
    for block in bpy.data.lights: bpy.data.lights.remove(block)
    for block in bpy.data.cameras: bpy.data.cameras.remove(block)

def create_material(name, color, metallic=0.0, roughness=0.5):
    """Helper to create a Principled BSDF material."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
    return mat

def write_manual_x3d(filepath, target_frame):
    """
    Manually writes a basic X3D file without using plugins.
    Captures the mesh in its deformed state (Physics) at the specific frame.
    """
    print(f"--- Exporting X3D to {filepath} at frame {target_frame} ---")
    
    # 1. Set the frame to capture the physics state
    bpy.context.scene.frame_set(target_frame)
    bpy.context.view_layer.update()
    
    # 2. Get the dependency graph (evaluated data)
    depsgraph = bpy.context.evaluated_depsgraph_get()

    with open(filepath, "w", encoding="utf-8") as f:
        # X3D Header
        f.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        f.write("<!DOCTYPE X3D PUBLIC 'ISO//Web3D//DTD X3D 3.3//EN' 'http://www.web3d.org/specifications/x3d-3.3.dtd'>\n")
        f.write("<X3D profile='Interchange' version='3.3' xmlns:xsd='http://www.w3.org/2001/XMLSchema-instance'>\n")
        f.write("  <Scene>\n")
        f.write("    <Background skyColor='0.05 0.05 0.05'/>\n") # Dark background

        # 3. Iterate through objects
        for obj in bpy.context.scene.objects:
            if obj.type not in ['MESH']:
                continue
            
            # Apply modifiers (Cloth, Hook) by getting evaluated mesh
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            
            # Determine Color
            color_str = "0.8 0.8 0.8" # Default Grey
            if len(obj.data.materials) > 0:
                try:
                    mat = obj.data.materials[0]
                    nodes = mat.node_tree.nodes
                    bsdf = nodes.get("Principled BSDF")
                    if bsdf:
                        c = bsdf.inputs["Base Color"].default_value
                        color_str = f"{c[0]:.3f} {c[1]:.3f} {c[2]:.3f}"
                except:
                    pass

            # Write Transform & Shape
            # Note: We use the object's location, but the mesh data might be deformed globally
            f.write(f"    <Transform translation='{obj.location.x:.4f} {obj.location.y:.4f} {obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write(f"        <Appearance><Material diffuseColor='{color_str}'/></Appearance>\n")
            
            # Write Faces
            f.write("        <IndexedFaceSet coordIndex='")
            for poly in mesh.polygons:
                for loop_index in poly.loop_indices:
                    v_index = mesh.loops[loop_index].vertex_index
                    f.write(f"{v_index} ")
                f.write("-1 ") # Face terminator
            f.write("'>\n")
            
            # Write Vertices
            f.write("          <Coordinate point='")
            for v in mesh.vertices:
                f.write(f"{v.co.x:.4f} {v.co.y:.4f} {v.co.z:.4f} ")
            f.write("'/>\n")
            
            f.write("        </IndexedFaceSet>\n")
            f.write("      </Shape>\n")
            f.write("    </Transform>\n")
            
            # Clean up temp mesh
            eval_obj.to_mesh_clear()

        f.write("  </Scene>\n")
        f.write("</X3D>\n")
    
    print("--- Export Complete ---")

def main():
    # -------------------------------------------------------------------------
    # 1. SETUP
    # -------------------------------------------------------------------------
    clean_scene()
    
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 120
    
    ball_radius = 1.0

    # -------------------------------------------------------------------------
    # 2. OBJECTS & MATERIALS
    # -------------------------------------------------------------------------
    
    # --- MIRROR BALL ---
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=ball_radius, 
        segments=64, 
        ring_count=32, 
        location=(0, 0, ball_radius) # Sit on floor
    )
    ball = bpy.context.object
    ball.name = "MirrorBall"
    bpy.ops.object.shade_smooth()
    
    # Chrome/Mirror Material: High Metallic, Low Roughness
    mat_mirror = create_material("Chrome", (0.9, 0.9, 0.9, 1), metallic=1.0, roughness=0.0)
    ball.data.materials.append(mat_mirror)
    
    # Collision for Ball
    bpy.ops.object.modifier_add(type='COLLISION')
    ball.modifiers["Collision"].settings.thickness_outer = 0.02

    # --- FLOOR ---
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "Floor"
    mat_floor = create_material("FloorMat", (0.1, 0.1, 0.1, 1)) # Dark grey floor
    floor.data.materials.append(mat_floor)
    
    # Collision for Floor
    bpy.ops.object.modifier_add(type='COLLISION')

    # --- WHITE SHEET ---
    # Create grid slightly above the ball
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=60, 
        y_subdivisions=60, 
        size=4, 
        location=(0, 0, ball_radius * 2.5)
    )
    cloth_obj = bpy.context.object
    cloth_obj.name = "Sheet"
    bpy.ops.object.shade_smooth()
    
    # Pure White Material
    mat_white = create_material("PureWhite", (1.0, 1.0, 1.0, 1.0), metallic=0.0, roughness=0.8)
    cloth_obj.data.materials.append(mat_white)

    # -------------------------------------------------------------------------
    # 3. PHYSICS & MECHANISM
    # -------------------------------------------------------------------------
    
    # Create Vertex Group for the "Hook" (Center of sheet)
    vg = cloth_obj.vertex_groups.new(name="PullGroup")
    
    mesh = cloth_obj.data
    center_indices = []
    # Identify center vertices
    for v in mesh.vertices:
        if (v.co.x**2 + v.co.y**2) < 0.2:
            center_indices.append(v.index)
    vg.add(center_indices, 1.0, 'REPLACE')

    # Create an Empty object to act as the "Hand"
    bpy.ops.object.empty_add(type='SPHERE', radius=0.5, location=(0, 0, ball_radius * 3))
    hook_empty = bpy.context.object
    hook_empty.name = "HookHandle"

    # Add Modifiers to Cloth
    bpy.context.view_layer.objects.active = cloth_obj
    
    # 1. Hook Modifier (Pulls the geometry)
    bpy.ops.object.modifier_add(type='HOOK')
    mod_hook = cloth_obj.modifiers["Hook"]
    mod_hook.object = hook_empty
    mod_hook.vertex_group = "PullGroup"
    
    # 2. Cloth Modifier (Simulates physics)
    bpy.ops.object.modifier_add(type='CLOTH')
    mod_cloth = cloth_obj.modifiers["Cloth"]
    
    # Cloth Settings (Blender 4.2/5.0 API safe)
    c_settings = mod_cloth.settings
    c_settings.quality = 6
    c_settings.mass = 0.3
    
    # Self Collision check
    if hasattr(c_settings, "collision_settings"):
        c_settings.collision_settings.use_self_collision = True
    elif hasattr(c_settings, "use_self_collision"):
        c_settings.use_self_collision = True

    # -------------------------------------------------------------------------
    # 4. ANIMATION
    # -------------------------------------------------------------------------
    
    # A. Animate the Pull (Hook Location)
    # Frame 1: Start position
    hook_empty.location = (0, 0, ball_radius * 2.2)
    hook_empty.keyframe_insert(data_path="location", frame=1)
    
    # Frame 30: Start pulling
    hook_empty.keyframe_insert(data_path="location", frame=30)
    
    # Frame 50: Pulled Up and to the side
    hook_empty.location = (2.5, 2.5, 5.0)
    hook_empty.keyframe_insert(data_path="location", frame=50)
    
    # B. Animate the Release (Hook Strength)
    mod_hook.strength = 1.0
    mod_hook.keyframe_insert(data_path="strength", frame=50)
    
    mod_hook.strength = 0.0 # Release the cloth to fall
    mod_hook.keyframe_insert(data_path="strength", frame=55)

    # -------------------------------------------------------------------------
    # 5. LIGHTING (Red, Green, Blue)
    # -------------------------------------------------------------------------
    light_colors = [
        (1.0, 0.0, 0.0), # RED
        (0.0, 1.0, 0.0), # GREEN
        (0.0, 0.0, 1.0)  # BLUE
    ]
    
    for i in range(3):
        angle = (i / 3) * (2 * math.pi)
        dist = 5
        x = math.cos(angle) * dist
        y = math.sin(angle) * dist
        z = 5
        
        bpy.ops.object.light_add(type='SPOT', location=(x, y, z))
        light = bpy.context.object
        light.data.energy = 3000 # Watts
        light.data.spot_size = 0.8
        light.data.color = light_colors[i] # Assign RGB color
        
        # Track light to Ball
        track = light.constraints.new(type='TRACK_TO')
        track.target = ball
        track.track_axis = 'TRACK_NEGATIVE_Z'
        track.up_axis = 'UP_Y'

    # -------------------------------------------------------------------------
    # 6. SIMULATION & EXPORT
    # -------------------------------------------------------------------------
    
    # Force scene update
    bpy.context.view_layer.update()
    
    # Define file path
    filename = "mirrored_ball_rgb_crumbled.x3d"
    export_path = os.path.join(tempfile.gettempdir(), filename)
    
    # We want the cloth to be on the ground, crumbled up.
    # This happens after the release (Frame 55). Let's pick Frame 100.
    target_export_frame = 100
    
    print("Processing Physics (This may take a moment)...")
    write_manual_x3d(export_path, target_export_frame)
    
    print(f"File exported successfully to: {export_path}")
    
    # Reset timeline for user interaction
    bpy.context.scene.frame_set(1)

if __name__ == "__main__":
    main()
