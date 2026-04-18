import bpy
import bmesh
import math
import os
import tempfile
from mathutils import Vector, Matrix

# ==============================================================================
# 1. HELPER FUNCTIONS
# ==============================================================================

def clean_scene():
    """Wipes the scene completely."""
    if bpy.context.object:
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # Deep clean data blocks
    for collection in [bpy.data.meshes, bpy.data.materials, bpy.data.lights, 
                       bpy.data.cameras, bpy.data.curves]:
        for block in collection:
            collection.remove(block)

def create_pbr_material(name, color, metallic, roughness):
    """Creates a Principled BSDF material."""
    mat = bpy.data.materials.new(name=name)
    if not mat.use_nodes:
        mat.use_nodes = True
        
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    
    if bsdf:
        bsdf.inputs['Base Color'].default_value = color
        bsdf.inputs['Metallic'].default_value = metallic
        bsdf.inputs['Roughness'].default_value = roughness
    return mat

def get_triangulated_mesh_data(obj, depsgraph=None):
    """Returns lists of vertices and indices for X3D export."""
    if depsgraph:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
    else:
        mesh = obj.data

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    
    verts = [v.co[:] for v in bm.verts]
    # X3D coordIndex format: v1 v2 v3 -1
    indices = [[v.index for v in f.verts] for f in bm.faces]
    
    bm.free()
    if depsgraph:
        eval_obj.to_mesh_clear()
        
    return verts, indices

# ==============================================================================
# 2. SCENE GENERATION
# ==============================================================================

def setup_scene():
    clean_scene()
    
    # --- Materials ---
    mat_chrome = create_pbr_material("Chrome", (0.9, 0.9, 0.9, 1), 1.0, 0.0) # High metal, low rough
    mat_floor = create_pbr_material("Floor", (0.1, 0.1, 0.1, 1), 0.1, 0.9)
    mat_sheet = create_pbr_material("Sheet", (1.0, 1.0, 1.0, 1), 0.0, 0.9)

    # --- Objects ---
    
    # 1. Chrome Ball
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0, 0, 1), segments=64, ring_count=32)
    ball = bpy.context.active_object
    ball.name = "MirrorBall"
    ball.data.materials.append(mat_chrome)
    bpy.ops.object.shade_smooth()
    
    # Ball Physics (Collision)
    c_mod = ball.modifiers.new(name="Collision", type='COLLISION')
    c_mod.settings.thickness_outer = 0.05

    # 2. Floor
    bpy.ops.mesh.primitive_plane_add(size=25, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    floor.data.materials.append(mat_floor)
    
    # Floor Physics (Collision)
    fc_mod = floor.modifiers.new(name="Collision", type='COLLISION')

    # 3. Sheet (The Grid)
    # 45 cuts
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=45, y_subdivisions=45, size=5, location=(0, 0, 3.2))
    sheet = bpy.context.active_object
    sheet.name = "ClothSheet"
    sheet.data.materials.append(mat_sheet)
    bpy.ops.object.shade_smooth()

    # --- Vertex Group with Radius Falloff ---
    # We want to grab a chunk, not just one vertex, so the sheet drags properly.
    vg = sheet.vertex_groups.new(name="HookGroup")
    
    # Radius of influence
    grab_radius = 1.2
    
    # Calculate weights based on distance from center (0,0 local)
    for v in sheet.data.vertices:
        # Distance from local origin (ignoring Z slightly if flat, but it is flat)
        dist = Vector((v.co.x, v.co.y, 0)).length
        if dist < grab_radius:
            # Linear falloff: 1.0 at center, 0.0 at edge of radius
            weight = 1.0 - (dist / grab_radius)
            vg.add([v.index], weight, 'REPLACE')

    # --- Cloth Physics ---
    cloth_mod = sheet.modifiers.new(name="Cloth", type='CLOTH')
    cs = cloth_mod.settings
    cs.quality = 6
    cs.mass = 0.5
    cs.tension_stiffness = 15.0
    cs.compression_stiffness = 15.0
    cs.shear_stiffness = 5.0
    cs.bending_stiffness = 0.5
    
    # API Safety for Collisions
    if hasattr(cs, 'collision_settings'):
        cs.collision_settings.use_self_collision = True
        cs.collision_settings.distance_min = 0.02

    # --- Hook & Animation ---
    
    # Hook Helper
    bpy.ops.object.empty_add(type='SPHERE', radius=0.3, location=(0, 0, 3.2))
    hook_empty = bpy.context.active_object
    hook_empty.name = "HookHelper"

    # Attach Hook Modifier
    bpy.context.view_layer.objects.active = sheet
    hook_mod = sheet.modifiers.new(name="Hook", type='HOOK')
    hook_mod.object = hook_empty
    hook_mod.vertex_group = "HookGroup"
    hook_mod.strength = 1.0

    # Animation Keyframes
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 175
    scene.render.fps = 24

    # 1. Settle (1-80)
    hook_empty.location = (0, 0, 3.2)
    hook_empty.keyframe_insert(data_path="location", frame=1)
    hook_empty.keyframe_insert(data_path="location", frame=80)

    # 2. Drag Off (80-140)
    # Move Up and Far Right/Back to pull it completely off the sphere
    hook_empty.location = (4.0, 4.0, 5.0) 
    hook_empty.keyframe_insert(data_path="location", frame=140)

    # 3. Drop (145)
    hook_mod.strength = 1.0
    hook_mod.keyframe_insert(data_path="strength", frame=140)
    hook_mod.strength = 0.0 # Let go
    hook_mod.keyframe_insert(data_path="strength", frame=145)

    # --- Lighting (RGB + Environment) ---
    
    def create_spot(name, color, location):
        bpy.ops.object.light_add(type='SPOT', location=location)
        light_obj = bpy.context.active_object
        light_obj.name = name
        light_obj.data.color = color
        light_obj.data.energy = 800  # High energy for visibility
        light_obj.data.spot_size = math.radians(60)
        light_obj.data.shadow_soft_size = 0.1
        
        # Track Ball
        tt = light_obj.constraints.new(type='TRACK_TO')
        tt.target = ball
        tt.track_axis = 'TRACK_NEGATIVE_Z'
        tt.up_axis = 'UP_Y'
        
        return light_obj

    lights = []
    lights.append(create_spot("SpotRed", (1, 0, 0), (5, -5, 6)))
    lights.append(create_spot("SpotGreen", (0, 1, 0), (-5, -5, 6)))
    lights.append(create_spot("SpotBlue", (0, 0, 1), (0, 6, 6)))

    # --- Camera ---
    bpy.ops.object.camera_add(location=(7, -8, 6))
    cam = bpy.context.active_object
    cam.name = "MainCamera"
    
    # Point camera at scene center
    tt_cam = cam.constraints.new(type='TRACK_TO')
    tt_cam.target = ball
    tt_cam.track_axis = 'TRACK_NEGATIVE_Z'
    tt_cam.up_axis = 'UP_Y'
    
    scene.camera = cam

    return ball, floor, sheet, lights

# ==============================================================================
# 3. CUSTOM X3D EXPORT (X3D 4.0)
# ==============================================================================

def export_x3d_custom(filepath, anim_obj, static_objs, lights):
    """
    Exports the scene to X3D 4.0 with:
    - PBR Materials
    - Environment Lighting
    - Vertex Animation Baking for Cloth
    - Correctly oriented RGB Spotlights
    """
    
    print(f"--- Starting Export: {filepath} ---")
    
    scene = bpy.context.scene
    start = scene.frame_start
    end = scene.frame_end
    
    # Helper to stringify vectors/colors
    def s_vec(v): return f"{v[0]:.4f} {v[1]:.4f} {v[2]:.4f}"
    def s_col(c): return f"{c[0]:.4f} {c[1]:.4f} {c[2]:.4f}"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        # --- Header ---
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "http://www.web3d.org/specifications/x3d-4.0.dtd">\n')
        f.write('<X3D profile="Interchange" version="4.0" xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance" xsd:noNamespaceSchemaLocation="http://www.web3d.org/specifications/x3d-4.0.xsd">\n')
        f.write('  <head>\n')
        f.write('    <meta name="generator" content="Blender 5.0 Custom Physics Exporter"/>\n')
        f.write('  </head>\n')
        f.write('  <Scene>\n')
        
        # --- Environment & Navigation ---
        # 1. Navigation Info: Turn off Headlight so our RGB lights are dominant
        f.write('    <NavigationInfo headlight="false" type=\'"EXAMINE" "ANY"\'/>\n')
        
        # 2. Background: Dark grey sky
        f.write('    <Background skyColor="0.05 0.05 0.05"/>\n')
        
        # 3. Environment Light: Essential for Chrome Reflection
        f.write('    <EnvironmentLight intensity="0.8" ambientIntensity="0.4" color="1 1 1"/>\n')

        # 4. Viewpoint (Camera)
        cam = scene.camera
        # We assume Z-up in X3D to match Blender.
        # Apply TrackTo constraint visually to get actual matrix
        bpy.context.view_layer.update() 
        cam_loc = cam.matrix_world.translation
        # Look at center (0,0,1) roughly
        f.write(f'    <Viewpoint position="{s_vec(cam_loc)}" orientation="0 0 1 0" description="Main View" centerOfRotation="0 0 1"/>\n')

        # --- Lights (RGB) ---
        for l_obj in lights:
            l_data = l_obj.data
            color = s_col(l_data.color)
            loc = s_vec(l_obj.matrix_world.translation)
            
            # Calculate Direction Vector from Rotation Matrix
            # Blender Light points -Z. Apply rotation matrix to (0,0,-1)
            direction = l_obj.matrix_world.to_3x3() @ Vector((0, 0, -1))
            dir_str = s_vec(direction)
            
            # Attenuation (1 0 0 is none, 0 0 1 is quadratic falloff)
            # Using low attenuation to ensure they reach the ball strongly
            f.write(f'    <SpotLight location="{loc}" direction="{dir_str}" color="{color}" intensity="1.5" beamWidth="0.8" cutOffAngle="1.0" radius="50" attenuation="1 0 0"/>\n')

        # --- Static Geometry (Ball, Floor) ---
        for obj in static_objs:
            # Material Data
            mat = obj.active_material
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            base_col = s_col(bsdf.inputs['Base Color'].default_value)
            met = bsdf.inputs['Metallic'].default_value
            rough = bsdf.inputs['Roughness'].default_value
            
            # Mesh Data
            verts, indices = get_triangulated_mesh_data(obj)
            coord_idx = " ".join([f"{i[0]} {i[1]} {i[2]} -1" for i in indices])
            points = " ".join([s_vec(v) for v in verts])
            
            f.write(f'    <Transform translation="{s_vec(obj.location)}">\n')
            f.write('      <Shape>\n')
            f.write('        <Appearance>\n')
            f.write(f'          <PhysicalMaterial baseColor="{base_col}" metallic="{met}" roughness="{rough}"/>\n')
            f.write('        </Appearance>\n')
            f.write(f'        <IndexedFaceSet coordIndex="{coord_idx}" creaseAngle="3.14159">\n')
            f.write(f'          <Coordinate point="{points}"/>\n')
            f.write('        </IndexedFaceSet>\n')
            f.write('      </Shape>\n')
            f.write('    </Transform>\n')

        # --- Animated Geometry (The Sheet) ---
        print("Baking vertex animation for Sheet...")
        
        # 1. Get Topology (Index list doesn't change)
        _, anim_indices = get_triangulated_mesh_data(anim_obj) # Get static topology
        anim_idx_str = " ".join([f"{i[0]} {i[1]} {i[2]} -1" for i in anim_indices])
        
        # 2. Bake Frames
        key_fractions = []
        key_values = [] # Big list of point lists
        
        depsgraph = bpy.context.evaluated_depsgraph_get()
        
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            
            # Get Deformed Mesh
            eval_obj = anim_obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            
            # Flatten vertices
            # Note: We export in Object Space, assuming the wrapper Transform stays at origin.
            # But the Cloth Mod moves verts relative to object origin. 
            # The Object location itself (0,0,3.2) is static.
            current_points = " ".join([s_vec(v.co) for v in mesh.vertices])
            key_values.append(current_points)
            
            # Calculate Time Fraction (0.0 to 1.0)
            frac = (frame - start) / (end - start)
            key_fractions.append(f"{frac:.4f}")
            
            eval_obj.to_mesh_clear()

        # 3. Write Animated Shape
        mat = anim_obj.active_material
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        base_col = s_col(bsdf.inputs['Base Color'].default_value)
        
        f.write(f'    <Transform translation="{s_vec(anim_obj.location)}">\n')
        f.write('      <Shape>\n')
        f.write('        <Appearance>\n')
        # Cloth usually has low metallic, high roughness, double-sided (solid=false)
        f.write(f'          <PhysicalMaterial baseColor="{base_col}" metallic="0.0" roughness="0.9"/>\n')
        f.write('        </Appearance>\n')
        
        # IndexedFaceSet with solid="false" to render both sides
        f.write(f'        <IndexedFaceSet DEF="SheetGeo" coordIndex="{anim_idx_str}" solid="false" creaseAngle="3.14159">\n')
        f.write(f'          <Coordinate DEF="SheetCoord" point="{key_values[0]}"/>\n')
        f.write('        </IndexedFaceSet>\n')
        f.write('      </Shape>\n')
        
        # 4. Interpolators
        total_time = (end - start) / scene.render.fps
        keys_str = " ".join(key_fractions)
        # Use delimiter for readability in file, though spaces work
        key_vals_str = "  ".join(key_values)
        
        f.write(f'      <TimeSensor DEF="Clock" cycleInterval="{total_time:.2f}" loop="true"/>\n')
        f.write(f'      <CoordinateInterpolator DEF="SheetInterp" key="{keys_str}" keyValue="{key_vals_str}"/>\n')
        
        # 5. Routes
        f.write('      <ROUTE fromNode="Clock" fromField="fraction_changed" toNode="SheetInterp" toField="set_fraction"/>\n')
        f.write('      <ROUTE fromNode="SheetInterp" fromField="value_changed" toNode="SheetCoord" toField="point"/>\n')
        
        f.write('    </Transform>\n')

        f.write('  </Scene>\n')
        f.write('</X3D>\n')
        
    print("Export Complete.")

# ==============================================================================
# 4. EXECUTION
# ==============================================================================

if __name__ == "__main__":
    # Setup
    ball, floor, sheet, lights = setup_scene()
    
    # Bake Physics Cache (Run through timeline once to ensure modifiers are valid)
    print("Simulating physics frame by frame...")
    for f in range(1, 176, 10):
        bpy.context.scene.frame_set(f)
    bpy.context.scene.frame_set(1)
    
    # Define Path
    tmp_dir = tempfile.gettempdir()
    x3d_path = os.path.join(tmp_dir, "cloth_sim_rgb.x3d")
    
    # Export
    export_x3d_custom(x3d_path, sheet, [ball, floor], lights)
    
    print(f"\nSUCCESS: X3D file generated at:\n{x3d_path}")
