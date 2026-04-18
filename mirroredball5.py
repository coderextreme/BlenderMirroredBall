import bpy
import math
import os
import tempfile

def clean_scene():
    """Clears the scene completely."""
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    for block in bpy.data.meshes: bpy.data.meshes.remove(block)
    for block in bpy.data.materials: bpy.data.materials.remove(block)
    for block in bpy.data.lights: bpy.data.lights.remove(block)
    for block in bpy.data.cameras: bpy.data.cameras.remove(block)

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

def export_animated_x3d(filepath, start_frame, end_frame, fps=24):
    """
    Exports the scene to X3D. 
    Detects the 'Sheet' object and bakes its vertices into a CoordinateInterpolator.
    """
    print(f"--- Starting X3D Export (Animation Baking) ---")
    
    # 1. Prepare Data Structures
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    
    # Identify objects
    cloth_obj = bpy.data.objects.get("Sheet")
    static_objects = [obj for obj in scene.objects if obj != cloth_obj and obj.type == 'MESH']
    lights = [obj for obj in scene.objects if obj.type == 'LIGHT']
    
    with open(filepath, "w", encoding="utf-8") as f:
        # --- HEADER ---
        f.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        f.write("<!DOCTYPE X3D PUBLIC 'ISO//Web3D//DTD X3D 3.3//EN' 'http://www.web3d.org/specifications/x3d-3.3.dtd'>\n")
        f.write("<X3D profile='Interchange' version='3.3' xmlns:xsd='http://www.w3.org/2001/XMLSchema-instance'>\n")
        f.write("  <Scene>\n")
        f.write("    <Background skyColor='0.1 0.1 0.1'/>\n")
        f.write(f"    <NavigationInfo headlight='false'/>\n") # Turn off default camera light so our RGB lights work

        # --- WRITE LIGHTS ---
        # X3D Lights are slightly different, we map Blender Area/Spot to SpotLight
        for l in lights:
            color = l.data.color
            # Intensity logic approximation
            intensity = min(l.data.energy / 1000.0, 1.0) 
            loc = l.location
            
            # Simple SpotLight pointing down/at center
            # In X3D, direction is a vector. 
            f.write(f"    <SpotLight location='{loc.x:.4f} {loc.y:.4f} {loc.z:.4f}' "
                    f"color='{color[0]:.3f} {color[1]:.3f} {color[2]:.3f}' "
                    f"intensity='{intensity:.2f}' direction='{-loc.x} {-loc.y} {-4}' "
                    f"cutOffAngle='0.7' beamWidth='0.6' radius='20' />\n")

        # --- WRITE STATIC OBJECTS (Ball, Floor) ---
        for obj in static_objects:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            
            # Material Color extraction
            color_str = "0.8 0.8 0.8"
            shiny = 0.1
            if len(obj.data.materials) > 0:
                mat = obj.data.materials[0]
                # If it's the mirror ball, make it shiny in X3D
                if "Chrome" in mat.name:
                    shiny = 1.0
                    color_str = "1 1 1" # White base for mirror
                elif "Floor" in mat.name:
                    color_str = "0.1 0.1 0.1"

            f.write(f"    <Transform translation='{obj.location.x:.4f} {obj.location.y:.4f} {obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write(f"        <Appearance><Material diffuseColor='{color_str}' specularColor='{shiny} {shiny} {shiny}' shininess='{shiny}'/></Appearance>\n")
            f.write("        <IndexedFaceSet coordIndex='")
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

        # --- WRITE ANIMATED CLOTH ---
        # We need to bake coordinates for every frame
        if cloth_obj:
            print("Baking Cloth Animation... (This may take a moment)")
            
            # Data containers
            all_frames_coords = [] # List of strings "x y z x y z..."
            keys = []
            
            # 1. Get Topology (Faces) from Frame 1
            scene.frame_set(start_frame)
            depsgraph.update()
            eval_cloth = cloth_obj.evaluated_get(depsgraph)
            ref_mesh = eval_cloth.to_mesh()
            
            # Write the Shape Definition (Geometry holder)
            f.write(f"    <Transform translation='{cloth_obj.location.x:.4f} {cloth_obj.location.y:.4f} {cloth_obj.location.z:.4f}'>\n")
            f.write("      <Shape>\n")
            f.write("        <Appearance><Material diffuseColor='1 1 1'/></Appearance>\n") # Pure White
            f.write("        <IndexedFaceSet DEF='CLOTH_GEO' coordIndex='")
            
            for poly in ref_mesh.polygons:
                for loop_index in poly.loop_indices:
                    f.write(f"{ref_mesh.loops[loop_index].vertex_index} ")
                f.write("-1 ")
            f.write("'>\n")
            
            # Write Initial Coordinate Node with a DEF name to target with Interpolator
            f.write("          <Coordinate DEF='CLOTH_COORD' point='")
            for v in ref_mesh.vertices:
                f.write(f"{v.co.x:.4f} {v.co.y:.4f} {v.co.z:.4f} ")
            f.write("'/>\n")
            
            f.write("        </IndexedFaceSet>\n")
            f.write("      </Shape>\n")
            f.write("    </Transform>\n")
            eval_cloth.to_mesh_clear()

            # 2. Iterate Frames to collect KeyValues
            total_duration = end_frame - start_frame
            
            for frame in range(start_frame, end_frame + 1):
                scene.frame_set(frame)
                depsgraph.update()
                
                # Get deformed mesh
                eval_cloth = cloth_obj.evaluated_get(depsgraph)
                mesh = eval_cloth.to_mesh()
                
                # Create giant string of coords for this frame
                # "x y z x y z ..."
                coords = []
                for v in mesh.vertices:
                    coords.append(f"{v.co.x:.3f} {v.co.y:.3f} {v.co.z:.3f}")
                
                all_frames_coords.append(" ".join(coords))
                
                # Calculate key fraction (0.0 to 1.0)
                fraction = (frame - start_frame) / total_duration
                keys.append(f"{fraction:.3f}")
                
                eval_cloth.to_mesh_clear()
                
                if frame % 10 == 0:
                    print(f"  Baking Frame {frame}/{end_frame}...")

            # 3. Write Interpolators
            print("Writing Animation Data to X3D...")
            
            # TimeSensor (The Clock)
            # Cycle interval = seconds for animation to loop
            cycle_time = total_duration / fps
            f.write(f"    <TimeSensor DEF='TIMER' cycleInterval='{cycle_time:.2f}' loop='true'/>\n")
            
            # CoordinateInterpolator (The Data)
            f.write(f"    <CoordinateInterpolator DEF='CLOTH_ANI' key='{' '.join(keys)}' \n")
            f.write(f"      keyValue='{' '.join(all_frames_coords)}' />\n")
            
            # Routing (Connecting the nodes)
            f.write("    <ROUTE fromNode='TIMER' fromField='fraction_changed' toNode='CLOTH_ANI' toField='set_fraction'/>\n")
            f.write("    <ROUTE fromNode='CLOTH_ANI' fromField='value_changed' toNode='CLOTH_COORD' toField='point'/>\n")

        f.write("  </Scene>\n")
        f.write("</X3D>\n")

    print(f"X3D Export Complete: {filepath}")

def main():
    clean_scene()
    
    # Setup Duration
    start_frame = 1
    end_frame = 100 # End frame where cloth is crumbled
    bpy.context.scene.frame_start = start_frame
    bpy.context.scene.frame_end = end_frame

    # 1. MIRROR BALL
    ball_radius = 1.0
    bpy.ops.mesh.primitive_uv_sphere_add(radius=ball_radius, segments=64, ring_count=32, location=(0, 0, ball_radius))
    ball = bpy.context.object
    ball.name = "MirrorBall"
    bpy.ops.object.shade_smooth()
    mat_mirror = create_material("Chrome", (1.0, 1.0, 1.0, 1), metallic=1.0, roughness=0.0)
    ball.data.materials.append(mat_mirror)
    
    # Physics Collision
    bpy.ops.object.modifier_add(type='COLLISION')
    ball.modifiers["Collision"].settings.thickness_outer = 0.02

    # 2. FLOOR
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "Floor"
    mat_floor = create_material("FloorMat", (0.1, 0.1, 0.1, 1))
    floor.data.materials.append(mat_floor)
    bpy.ops.object.modifier_add(type='COLLISION')

    # 3. SHEET (PURE WHITE)
    # Reducing subdivisions slightly to keep X3D file size manageable for browser playback
    # 40x40 = 1600 vertices * 100 frames = 160,000 coordinate sets.
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=40, y_subdivisions=40, size=4, location=(0, 0, ball_radius * 2.5))
    cloth_obj = bpy.context.object
    cloth_obj.name = "Sheet"
    bpy.ops.object.shade_smooth()
    
    mat_white = create_material("PureWhite", (1.0, 1.0, 1.0, 1.0), metallic=0.0, roughness=1.0)
    cloth_obj.data.materials.append(mat_white)

    # 4. HOOK MECHANISM
    vg = cloth_obj.vertex_groups.new(name="PullGroup")
    mesh = cloth_obj.data
    center_indices = [v.index for v in mesh.vertices if (v.co.x**2 + v.co.y**2) < 0.2]
    vg.add(center_indices, 1.0, 'REPLACE')

    bpy.ops.object.empty_add(type='SPHERE', radius=0.5, location=(0, 0, ball_radius * 3))
    hook_empty = bpy.context.object
    hook_empty.name = "HookHandle"

    bpy.context.view_layer.objects.active = cloth_obj
    bpy.ops.object.modifier_add(type='HOOK')
    mod_hook = cloth_obj.modifiers["Hook"]
    mod_hook.object = hook_empty
    mod_hook.vertex_group = "PullGroup"
    
    bpy.ops.object.modifier_add(type='CLOTH')
    mod_cloth = cloth_obj.modifiers["Cloth"]
    c_settings = mod_cloth.settings
    c_settings.quality = 5
    c_settings.mass = 0.3
    
    # API Compatibility
    if hasattr(c_settings, "collision_settings"):
        c_settings.collision_settings.use_self_collision = True
    elif hasattr(c_settings, "use_self_collision"):
        c_settings.use_self_collision = True

    # 5. ANIMATION KEYFRAMES
    # Hook Movement
    hook_empty.location = (0, 0, ball_radius * 2.2)
    hook_empty.keyframe_insert(data_path="location", frame=1)
    hook_empty.keyframe_insert(data_path="location", frame=30)
    hook_empty.location = (2.5, 2.5, 5.0)
    hook_empty.keyframe_insert(data_path="location", frame=50)
    
    # Hook Release
    mod_hook.strength = 1.0
    mod_hook.keyframe_insert(data_path="strength", frame=50)
    mod_hook.strength = 0.0
    mod_hook.keyframe_insert(data_path="strength", frame=55)

    # 6. RGB LIGHTS
    colors = [(1,0,0), (0,1,0), (0,0,1)]
    for i, col in enumerate(colors):
        angle = (i / 3) * (2 * math.pi)
        x, y = math.cos(angle) * 5, math.sin(angle) * 5
        bpy.ops.object.light_add(type='SPOT', location=(x, y, 5))
        light = bpy.context.object
        light.data.energy = 2000
        light.data.color = col
        light.data.spot_size = 0.8
        
        track = light.constraints.new(type='TRACK_TO')
        track.target = ball
        track.track_axis = 'TRACK_NEGATIVE_Z'
        track.up_axis = 'UP_Y'

    # 7. EXPORT
    # We must bake the physics cache before iterating, 
    # but strictly speaking, simply playing the frame via frame_set usually calculates it.
    filename = "animated_sheet_reveal.x3d"
    filepath = os.path.join(tempfile.gettempdir(), filename)
    
    export_animated_x3d(filepath, start_frame, end_frame, fps=24)
    
    # Reset
    bpy.context.scene.frame_set(1)

if __name__ == "__main__":
    main()
