import bpy
import math
import os
import tempfile

# -----------------------------------------------------------------------------
# 1. SCENE CREATION
# -----------------------------------------------------------------------------

def clean_scene():
    """Wipes the scene clean."""
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # purge data blocks
    for block in bpy.data.meshes: bpy.data.meshes.remove(block)
    for block in bpy.data.materials: bpy.data.materials.remove(block)
    for block in bpy.data.lights: bpy.data.lights.remove(block)
    for block in bpy.data.cameras: bpy.data.cameras.remove(block)
    for block in bpy.data.objects: bpy.data.objects.remove(block)

def create_material(name, color, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
    return mat

def setup_scene():
    clean_scene()
    
    # Animation Duration
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 100
    
    ball_radius = 1.0

    # --- 1. THE MIRROR BALL ---
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=ball_radius, segments=64, ring_count=32, location=(0, 0, ball_radius)
    )
    ball = bpy.context.object
    ball.name = "MirrorBall"
    bpy.ops.object.shade_smooth()
    
    mat_mirror = create_material("Chrome", (1.0, 1.0, 1.0, 1), metallic=1.0, roughness=0.0)
    ball.data.materials.append(mat_mirror)
    
    # Collision for Physics
    bpy.ops.object.modifier_add(type='COLLISION')
    ball.modifiers["Collision"].settings.thickness_outer = 0.02

    # --- 2. THE GROUND ---
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "Floor"
    mat_floor = create_material("FloorMat", (0.1, 0.1, 0.1, 1))
    floor.data.materials.append(mat_floor)
    
    # Collision for Physics
    bpy.ops.object.modifier_add(type='COLLISION')

    # --- 3. THE SHEET (Animated) ---
    # 40x40 subdivision is a good balance for X3D file size vs physics quality
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=40, y_subdivisions=40, size=4, location=(0, 0, ball_radius * 2.5)
    )
    sheet = bpy.context.object
    sheet.name = "Sheet"
    bpy.ops.object.shade_smooth()
    
    # Pure White
    mat_white = create_material("PureWhite", (1.0, 1.0, 1.0, 1), metallic=0.0, roughness=1.0)
    sheet.data.materials.append(mat_white)

    # --- 4. PHYSICS & MECHANISM ---
    # Vertex Group for Pulling
    vg = sheet.vertex_groups.new(name="PullGroup")
    mesh = sheet.data
    center_indices = [v.index for v in mesh.vertices if (v.co.x**2 + v.co.y**2) < 0.2]
    vg.add(center_indices, 1.0, 'REPLACE')

    # Hook Handle (Empty) - Will be filtered out of Export
    bpy.ops.object.empty_add(type='SPHERE', radius=0.5, location=(0, 0, ball_radius * 3))
    hook = bpy.context.object
    hook.name = "HookHandle"

    # Modifiers
    bpy.context.view_layer.objects.active = sheet
    bpy.ops.object.modifier_add(type='HOOK')
    mod_hook = sheet.modifiers["Hook"]
    mod_hook.object = hook
    mod_hook.vertex_group = "PullGroup"
    
    bpy.ops.object.modifier_add(type='CLOTH')
    mod_cloth = sheet.modifiers["Cloth"]
    c_settings = mod_cloth.settings
    c_settings.quality = 5
    c_settings.mass = 0.3
    
    # Blender 5.0 / 4.2+ API Safe collision check
    if hasattr(c_settings, "collision_settings"):
        c_settings.collision_settings.use_self_collision = True
        c_settings.collision_settings.distance_min = 0.02
    else:
        c_settings.use_self_collision = True

    # --- 5. ANIMATION KEYFRAMES ---
    # Move Hook
    hook.location = (0, 0, ball_radius * 2.2)
    hook.keyframe_insert("location", frame=1)
    hook.keyframe_insert("location", frame=30) # Wait
    
    hook.location = (2.5, 2.5, 5.0) # Pull
    hook.keyframe_insert("location", frame=50)
    
    # Release Hook
    mod_hook.strength = 1.0
    mod_hook.keyframe_insert("strength", frame=50)
    mod_hook.strength = 0.0
    mod_hook.keyframe_insert("strength", frame=55)

    # --- 6. RGB LIGHTS ---
    colors = [(1, 0, 0), (0, 1, 0), (0, 0, 1)] # R, G, B
    for i, col in enumerate(colors):
        angle = (i / 3) * (2 * math.pi)
        dist = 6
        lx, ly = math.cos(angle) * dist, math.sin(angle) * dist
        bpy.ops.object.light_add(type='SPOT', location=(lx, ly, 6))
        light = bpy.context.object
        light.data.energy = 3000
        light.data.color = col
        light.data.spot_size = 0.8
        
        # Track Ball
        const = light.constraints.new(type='TRACK_TO')
        const.target = ball
        const.track_axis = 'TRACK_NEGATIVE_Z'
        const.up_axis = 'UP_Y'

    # --- 7. CAMERA ---
    bpy.ops.object.camera_add(location=(0, -8, 5))
    cam = bpy.context.object
    cam.name = "MainCamera"
    cam.rotation_euler = (math.radians(60), 0, 0)
    scene.camera = cam

# -----------------------------------------------------------------------------
# 2. CUSTOM X3D EXPORTER
# -----------------------------------------------------------------------------

def write_x3d_file(filepath, start_frame, end_frame, fps=24):
    print(f"--- Exporting to {filepath} ---")
    
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    # Separate objects
    sheet_obj = bpy.data.objects.get("Sheet")
    camera_obj = scene.camera
    
    # Collect static meshes (Ground, Ball) - Exclude Sheet and Helpers
    static_meshes = []
    for obj in scene.objects:
        if obj.type == 'MESH' and obj != sheet_obj:
            static_meshes.append(obj)
            
    lights = [o for o in scene.objects if o.type == 'LIGHT']

    with open(filepath, "w", encoding="utf-8") as f:
        # Header
        f.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        f.write("<!DOCTYPE X3D PUBLIC 'ISO//Web3D//DTD X3D 3.3//EN' 'http://www.web3d.org/specifications/x3d-3.3.dtd'>\n")
        f.write("<X3D profile='Interchange' version='3.3' xmlns:xsd='http://www.w3.org/2001/XMLSchema-instance'>\n")
        f.write("  <Scene>\n")
        f.write("    <Background skyColor='0.05 0.05 0.05'/>\n")
        f.write("    <NavigationInfo headlight='false'/>\n") # Disable default light so RGB lights work

        # 1. Viewpoint (Camera)
        if camera_obj:
            loc = camera_obj.location
            # Convert Blender Euler to AxisAngle roughly or just lookAt
            # X3D Viewpoint is easier to define by position and orientation
            # Simple approximation using LookAt logic logic often fails in raw export,
            # so we export current transform.
            # However, for simplicity in this script, we assume the camera is placed 
            # and rotated (X axis) as set in setup_scene.
            # Blender Z-up to X3D Y-up is handled naturally if we export coords raw? 
            # No, X3D is Y-up. Blender is Z-up. 
            # We will export Blender coordinates directly, so we need the viewer to match.
            # OR we just rotate the camera node.
            
            # Simple static Viewpoint for the specific camera setup in setup_scene
            f.write(f"    <Viewpoint description='Main View' position='0 -10 5' orientation='1 0 0 1.1'/>\n")

        # 2. Lights
        for l in lights:
            color = l.data.color
            intensity = min(l.data.energy / 1500.0, 2.0)
            loc = l.location
            # Pointing at 0,0,1 roughly
            dx, dy, dz = -loc.x, -loc.y, -loc.z + 1
            f.write(f"    <SpotLight location='{loc.x:.4f} {loc.y:.4f} {loc.z:.4f}' "
                    f"color='{color[0]:.3f} {color[1]:.3f} {color[2]:.3f}' "
                    f"intensity='{intensity:.2f}' direction='{dx:.2f} {dy:.2f} {dz:.2f}' "
                    f"cutOffAngle='0.7' beamWidth='0.6' radius='30'/>\n")

        # 3. Static Meshes
        for obj in static_meshes:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            
            # Material logic
            color_str = "0.8 0.8 0.8"
            shininess = 0.1
            if obj.data.materials:
                mat_name = obj.data.materials[0].name
                if "Chrome" in mat_name:
                    color_str = "1 1 1"
                    shininess = 1.0 # Max specular
                elif "Floor" in mat_name:
                    color_str = "0.1 0.1 0.1"
            
            f.write(f"    <Transform translation='{obj.location.x:.4f} {obj.location.y:.4f} {obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write(f"        <Appearance><Material diffuseColor='{color_str}' specularColor='{shininess} {shininess} {shininess}'/></Appearance>\n")
            
            # IndexedFaceSet with creaseAngle
            f.write(f"        <IndexedFaceSet creaseAngle='3.14159' coordIndex='")
            for poly in mesh.polygons:
                for loop_index in poly.loop_indices:
                    f.write(f"{mesh.loops[loop_index].vertex_index} ")
                f.write("-1 ")
            f.write("'>\n")
            
            f.write("          <Coordinate point='")
            for v in mesh.vertices:
                f.write(f"{v.co.x:.4f} {v.co.y:.4f} {v.co.z:.4f} ")
            f.write("'/>\n")
            
            f.write("        </IndexedFaceSet>\n")
            f.write("      </Shape>\n")
            f.write("    </Transform>\n")
            eval_obj.to_mesh_clear()

        # 4. Animated Sheet
        if sheet_obj:
            print("Baking Animation Cache...")
            
            # Get topology from start frame
            scene.frame_set(start_frame)
            depsgraph.update()
            eval_sheet = sheet_obj.evaluated_get(depsgraph)
            ref_mesh = eval_sheet.to_mesh()
            
            # Write Base Shape
            f.write(f"    <Transform translation='{sheet_obj.location.x:.4f} {sheet_obj.location.y:.4f} {sheet_obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write("        <Appearance><Material diffuseColor='1 1 1'/></Appearance>\n")
            
            # IndexedFaceSet with creaseAngle
            f.write(f"        <IndexedFaceSet DEF='SHEET_GEO' creaseAngle='3.14159' coordIndex='")
            for poly in ref_mesh.polygons:
                for loop_index in poly.loop_indices:
                    f.write(f"{ref_mesh.loops[loop_index].vertex_index} ")
                f.write("-1 ")
            f.write("'>\n")
            
            # Initial Coordinates
            f.write("          <Coordinate DEF='SHEET_COORD' point='")
            for v in ref_mesh.vertices:
                f.write(f"{v.co.x:.4f} {v.co.y:.4f} {v.co.z:.4f} ")
            f.write("'/>\n")
            
            f.write("        </IndexedFaceSet>\n")
            f.write("      </Shape>\n")
            f.write("    </Transform>\n")
            
            eval_sheet.to_mesh_clear()

            # Bake CoordinateInterpolator Data
            keys = []
            key_values = []
            
            total_duration = end_frame - start_frame
            
            for frame in range(start_frame, end_frame + 1):
                scene.frame_set(frame)
                depsgraph.update() # Force physics update
                
                eval_sheet = sheet_obj.evaluated_get(depsgraph)
                mesh = eval_sheet.to_mesh()
                
                # Flatten vertex coords to string
                frame_coords = " ".join([f"{v.co.x:.3f} {v.co.y:.3f} {v.co.z:.3f}" for v in mesh.vertices])
                key_values.append(frame_coords)
                
                fraction = (frame - start_frame) / total_duration
                keys.append(f"{fraction:.3f}")
                
                eval_sheet.to_mesh_clear()
                
                if frame % 20 == 0: print(f"  Frame {frame}/{end_frame}")
            
            # Write Animation Nodes
            cycle_time = total_duration / fps
            
            f.write(f"    <TimeSensor DEF='TIMER' cycleInterval='{cycle_time:.2f}' loop='true'/>\n")
            f.write(f"    <CoordinateInterpolator DEF='SHEET_ANIM' key='{' '.join(keys)}' \n")
            f.write(f"      keyValue='{' '.join(key_values)}' />\n")
            
            f.write("    <ROUTE fromNode='TIMER' fromField='fraction_changed' toNode='SHEET_ANIM' toField='set_fraction'/>\n")
            f.write("    <ROUTE fromNode='SHEET_ANIM' fromField='value_changed' toNode='SHEET_COORD' toField='point'/>\n")

        f.write("  </Scene>\n")
        f.write("</X3D>\n")
    
    print("Export Complete.")

# -----------------------------------------------------------------------------
# 3. MAIN EXECUTION
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    setup_scene()
    
    # Define Path
    filename = "mirrored_ball_reveal.x3d"
    filepath = os.path.join(tempfile.gettempdir(), filename)
    
    # Run Export (Bakes animation)
    write_x3d_file(filepath, start_frame=1, end_frame=100)
    
    print(f"Saved to: {filepath}")
    
    # Return to start
    bpy.context.scene.frame_set(1)
