import bpy
import math
import os
import tempfile

# -----------------------------------------------------------------------------
# 1. SCENE SETUP
# -----------------------------------------------------------------------------

def clean_scene():
    """Wipes the scene clean of objects and data."""
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # Purge data blocks to prevent name collision and memory bloat
    for block in bpy.data.meshes: bpy.data.meshes.remove(block)
    for block in bpy.data.materials: bpy.data.materials.remove(block)
    for block in bpy.data.lights: bpy.data.lights.remove(block)
    for block in bpy.data.cameras: bpy.data.cameras.remove(block)
    # Recursively remove empty objects just in case
    for block in bpy.data.objects: bpy.data.objects.remove(block)

def create_material(name, color, metallic=0.0, roughness=0.5):
    """Creates a Principled BSDF material."""
    mat = bpy.data.materials.new(name=name)
    
    # Fix for DeprecationWarning: Only set use_nodes if it's False
    if not mat.use_nodes:
        mat.use_nodes = True
        
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
    return mat

def setup_scene(end_frame):
    clean_scene()
    
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = end_frame
    
    ball_radius = 1.0

    # --- 1. THE MIRRORED BALL ---
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=ball_radius, segments=64, ring_count=32, location=(0, 0, ball_radius)
    )
    ball = bpy.context.object
    ball.name = "MirrorBall"
    bpy.ops.object.shade_smooth()
    
    # Chrome Material
    mat_mirror = create_material("Chrome", (1.0, 1.0, 1.0, 1), metallic=1.0, roughness=0.0)
    ball.data.materials.append(mat_mirror)
    
    # Collision Physics (Ball)
    bpy.ops.object.modifier_add(type='COLLISION')
    ball.modifiers["Collision"].settings.thickness_outer = 0.02

    # --- 2. THE GROUND ---
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "Floor"
    mat_floor = create_material("FloorMat", (0.1, 0.1, 0.1, 1))
    floor.data.materials.append(mat_floor)
    
    # Collision Physics (Floor)
    bpy.ops.object.modifier_add(type='COLLISION')

    # --- 3. THE SHEET ---
    # 45x45 Grid
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=45, y_subdivisions=45, size=4.5, location=(0, 0, ball_radius * 2.2)
    )
    sheet = bpy.context.object
    sheet.name = "Sheet"
    bpy.ops.object.shade_smooth()
    
    # Pure White Material
    mat_white = create_material("PureWhite", (1.0, 1.0, 1.0, 1), metallic=0.0, roughness=0.8)
    sheet.data.materials.append(mat_white)

    # --- 4. PHYSICS & HOOK MECHANISM ---
    # Create Vertex Group for Pulling (Center of sheet)
    vg = sheet.vertex_groups.new(name="PullGroup")
    mesh = sheet.data
    # Select center vertices
    center_indices = [v.index for v in mesh.vertices if (v.co.x**2 + v.co.y**2) < 0.2]
    vg.add(center_indices, 1.0, 'REPLACE')

    # Create Hook Helper Object
    bpy.ops.object.empty_add(type='SPHERE', radius=0.5, location=(0, 0, ball_radius * 2.5))
    hook = bpy.context.object
    hook.name = "HookHandle"

    # Add Modifiers to Sheet
    bpy.context.view_layer.objects.active = sheet
    
    # 1. Hook (Pulls the geometry)
    bpy.ops.object.modifier_add(type='HOOK')
    mod_hook = sheet.modifiers["Hook"]
    mod_hook.object = hook
    mod_hook.vertex_group = "PullGroup"
    
    # 2. Cloth (Simulates physics)
    bpy.ops.object.modifier_add(type='CLOTH')
    mod_cloth = sheet.modifiers["Cloth"]
    c_settings = mod_cloth.settings
    c_settings.quality = 6
    c_settings.mass = 0.3
    c_settings.tension_stiffness = 15
    c_settings.compression_stiffness = 15
    c_settings.shear_stiffness = 5
    c_settings.bending_stiffness = 0.5
    
    # --- FIX FOR BLENDER 5.0 API ERROR ---
    # Collision settings are now a substruct of settings
    if hasattr(c_settings, "collision_settings"):
        c_settings.collision_settings.use_self_collision = True
        c_settings.collision_settings.distance_min = 0.015
    else:
        # Fallback for older Blender versions just in case
        try:
            c_settings.use_self_collision = True
        except:
            print("Warning: Could not set self collision.")

    # --- 5. ANIMATION KEYFRAMES ---
    # A. Hook Movement (The Pull)
    # Frame 1: Start position (draped over ball)
    hook.location = (0, 0, ball_radius * 1.8) 
    hook.keyframe_insert("location", frame=1)
    
    # Frame 100: Still draped (Start of Pull)
    hook.keyframe_insert("location", frame=100) 
    
    # Frame 160: Fully Pulled Away (Up and to the side)
    hook.location = (3.0, 3.0, 5.0) 
    hook.keyframe_insert("location", frame=160)
    
    # B. Hook Strength (The Drop)
    # Hold tight until frame 160
    mod_hook.strength = 1.0
    mod_hook.keyframe_insert("strength", frame=160)
    
    # Release to drop/crumble
    mod_hook.strength = 0.0
    mod_hook.keyframe_insert("strength", frame=165)

    # --- 6. RGB LIGHTS ---
    colors = [(1, 0, 0), (0, 1, 0), (0, 0, 1)] # Red, Green, Blue
    for i, col in enumerate(colors):
        angle = (i / 3) * (2 * math.pi)
        dist = 7
        lx, ly = math.cos(angle) * dist, math.sin(angle) * dist
        bpy.ops.object.light_add(type='SPOT', location=(lx, ly, 7))
        light = bpy.context.object
        light.data.energy = 4000
        light.data.color = col
        light.data.spot_size = 0.8
        
        # Track Ball
        const = light.constraints.new(type='TRACK_TO')
        const.target = ball
        const.track_axis = 'TRACK_NEGATIVE_Z'
        const.up_axis = 'UP_Y'

    # --- 7. CAMERA ---
    bpy.ops.object.camera_add(location=(0, -9, 6))
    cam = bpy.context.object
    cam.name = "MainCamera"
    # Point roughly at origin
    cam.rotation_euler = (math.radians(60), 0, 0)
    scene.camera = cam

# -----------------------------------------------------------------------------
# 2. X3D EXPORTER (MANUAL BAKE)
# -----------------------------------------------------------------------------

def write_x3d_file(filepath, start_frame, end_frame, fps=24):
    print(f"--- Exporting X3D Animation to {filepath} ---")
    
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    sheet_obj = bpy.data.objects.get("Sheet")
    
    # Identify objects to export (Exclude Sheet and Hook)
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
        f.write("    <NavigationInfo headlight='false'/>\n") 

        # 1. Viewpoint
        # Hardcoded for simplicity to match camera position
        f.write("    <Viewpoint description='Main View' position='0 -10 6' orientation='1 0 0 1.05'/>\n")

        # 2. Lights
        for l in lights:
            color = l.data.color
            intensity = min(l.data.energy / 2000.0, 2.0)
            loc = l.location
            # Calculate direction roughly to origin (0,0,1)
            dx, dy, dz = -loc.x, -loc.y, -loc.z + 1
            f.write(f"    <SpotLight location='{loc.x:.4f} {loc.y:.4f} {loc.z:.4f}' "
                    f"color='{color[0]:.3f} {color[1]:.3f} {color[2]:.3f}' "
                    f"intensity='{intensity:.2f}' direction='{dx:.2f} {dy:.2f} {dz:.2f}' "
                    f"cutOffAngle='0.7' beamWidth='0.6' radius='40'/>\n")

        # 3. Static Meshes (Ground, Ball)
        for obj in static_meshes:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            
            # Determine Material properties
            diffuse = "0.8 0.8 0.8"
            specular = "0.1 0.1 0.1"
            shininess = "0.1"
            
            if obj.data.materials:
                mat_name = obj.data.materials[0].name
                if "Chrome" in mat_name:
                    diffuse = "0.6 0.6 0.6" # Base for mirror
                    specular = "1 1 1"
                    shininess = "1.0"
                elif "Floor" in mat_name:
                    diffuse = "0.1 0.1 0.1"
            
            f.write(f"    <Transform translation='{obj.location.x:.4f} {obj.location.y:.4f} {obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write(f"        <Appearance><Material diffuseColor='{diffuse}' specularColor='{specular}' shininess='{shininess}'/></Appearance>\n")
            
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

        # 4. Animated Sheet (Baking Vertex Cache)
        if sheet_obj:
            print("Baking Sheet Animation (frames {} to {})...".format(start_frame, end_frame))
            
            # Get Topology from Start Frame
            scene.frame_set(start_frame)
            depsgraph.update()
            eval_sheet = sheet_obj.evaluated_get(depsgraph)
            ref_mesh = eval_sheet.to_mesh()
            
            # Write Base Shape
            f.write(f"    <Transform translation='{sheet_obj.location.x:.4f} {sheet_obj.location.y:.4f} {sheet_obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write("        <Appearance><Material diffuseColor='1 1 1'/></Appearance>\n") # Pure White
            
            f.write(f"        <IndexedFaceSet DEF='SHEET_GEO' creaseAngle='3.14159' coordIndex='")
            for poly in ref_mesh.polygons:
                for loop_index in poly.loop_indices:
                    f.write(f"{ref_mesh.loops[loop_index].vertex_index} ")
                f.write("-1 ")
            f.write("'>\n")
            
            # Initial Coordinate Node
            f.write("          <Coordinate DEF='SHEET_COORD' point='")
            for v in ref_mesh.vertices:
                f.write(f"{v.co.x:.4f} {v.co.y:.4f} {v.co.z:.4f} ")
            f.write("'/>\n")
            
            f.write("        </IndexedFaceSet>\n")
            f.write("      </Shape>\n")
            f.write("    </Transform>\n")
            eval_sheet.to_mesh_clear()

            # Bake CoordinateInterpolator
            keys = []
            key_values = []
            
            total_duration = end_frame - start_frame
            
            for frame in range(start_frame, end_frame + 1):
                scene.frame_set(frame)
                depsgraph.update()
                
                eval_sheet = sheet_obj.evaluated_get(depsgraph)
                mesh = eval_sheet.to_mesh()
                
                # Convert vertex coords to long string
                coords = []
                for v in mesh.vertices:
                    coords.append(f"{v.co.x:.3f} {v.co.y:.3f} {v.co.z:.3f}")
                key_values.append(" ".join(coords))
                
                # Time Fraction (0.0 to 1.0)
                fraction = (frame - start_frame) / total_duration
                keys.append(f"{fraction:.4f}")
                
                eval_sheet.to_mesh_clear()
                
                if frame % 20 == 0: 
                    print(f"  Processed frame {frame}")

            # Write Interpolator Nodes
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
# 3. EXECUTION
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Settings
    end_frame = 200 # Long enough to pull (160) and settle
    
    setup_scene(end_frame)
    
    # Force scene update
    bpy.context.view_layer.update()
    
    # Export
    filename = "mirrored_ball_reveal2.x3d"
    filepath = os.path.join(tempfile.gettempdir(), filename)
    
    # Note: We start export at 1 and go to 200 to capture the whole sequence
    write_x3d_file(filepath, start_frame=1, end_frame=end_frame, fps=24)
    
    print(f"X3D File saved to: {filepath}")
    
    # Reset
    bpy.context.scene.frame_set(1)
