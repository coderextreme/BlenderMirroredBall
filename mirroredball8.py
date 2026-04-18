import bpy
import bmesh
import math
import os
import tempfile

# ==============================================================================
# CONFIGURATION & HELPER FUNCTIONS
# ==============================================================================

def clean_scene():
    """Wipes the scene to ensure a fresh start."""
    if bpy.context.object:
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    # Clear orphan data
    for block in bpy.data.meshes: bpy.data.meshes.remove(block)
    for block in bpy.data.materials: bpy.data.materials.remove(block)
    for block in bpy.data.lights: bpy.data.lights.remove(block)
    for block in bpy.data.cameras: bpy.data.cameras.remove(block)

def create_pbr_material(name, color, metallic, roughness):
    """Creates a PBR material using the Principled BSDF node."""
    mat = bpy.data.materials.new(name=name)
    
    # API Safety: Check if nodes are enabled before setting (Blender 5.0/4.x compliance)
    if not mat.use_nodes:
        mat.use_nodes = True
        
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    
    if bsdf:
        bsdf.inputs['Base Color'].default_value = color
        bsdf.inputs['Metallic'].default_value = metallic
        bsdf.inputs['Roughness'].default_value = roughness
        
    return mat

def get_mesh_data_for_export(obj, depsgraph=None):
    """Extracts verts and indices from a mesh object."""
    # If depsgraph is provided, we get the evaluated mesh (modifiers applied)
    if depsgraph:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
    else:
        mesh = obj.data

    # Triangulate for X3D safety (optional but recommended)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    
    verts = [v.co[:] for v in bm.verts]
    # X3D coordIndex needs -1 delimiter, but for triangles we just list them
    # We will format this in the export loop
    indices = [[v.index for v in f.verts] for f in bm.faces]
    
    bm.free()
    if depsgraph:
        eval_obj.to_mesh_clear()
        
    return verts, indices

# ==============================================================================
# SCENE GENERATION
# ==============================================================================

def setup_scene():
    clean_scene()
    
    # 1. Materials
    mat_chrome = create_pbr_material("Chrome", (0.8, 0.8, 0.8, 1), 1.0, 0.05)
    mat_floor = create_pbr_material("DarkFloor", (0.05, 0.05, 0.05, 1), 0.2, 0.8)
    mat_sheet = create_pbr_material("WhiteSheet", (1.0, 1.0, 1.0, 1), 0.0, 0.8)

    # 2. Objects
    
    # Mirror Ball
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 1), segments=32, ring_count=16)
    ball = bpy.context.active_object
    ball.name = "MirrorBall"
    ball.data.materials.append(mat_chrome)
    bpy.ops.object.shade_smooth()
    
    # Physics: Collision for Ball
    c_mod = ball.modifiers.new(name="Collision", type='COLLISION')
    c_mod.settings.thickness_outer = 0.02

    # Floor
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    floor.data.materials.append(mat_floor)
    
    # Physics: Collision for Floor
    fc_mod = floor.modifiers.new(name="Collision", type='COLLISION')

    # Sheet (Grid)
    # 45x45 cuts results in approx 46 vertices per edge
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=45, y_subdivisions=45, size=4, location=(0, 0, 3.5))
    sheet = bpy.context.active_object
    sheet.name = "ClothSheet"
    sheet.data.materials.append(mat_sheet)
    bpy.ops.object.shade_smooth()

    # Create Vertex Group for the Hook (Center vertex)
    vg = sheet.vertex_groups.new(name="HookGroup")
    # Find center vertex index (closest to local 0,0,0)
    min_dist = 999
    center_idx = 0
    for v in sheet.data.vertices:
        dist = v.co.length
        if dist < min_dist:
            min_dist = dist
            center_idx = v.index
    vg.add([center_idx], 1.0, 'REPLACE')

    # 3. Physics: Cloth
    cloth_mod = sheet.modifiers.new(name="Cloth", type='CLOTH')
    cs = cloth_mod.settings
    cs.quality = 5
    cs.mass = 0.3
    
    # API Compliance: Handle collision settings structure
    if hasattr(cs, 'collision_settings'):
        cs.collision_settings.use_self_collision = True
        cs.collision_settings.distance_min = 0.01
    
    # 4. Animation Setup (Hook)
    
    # Create Hook Empty
    bpy.ops.object.empty_add(type='SPHERE', radius=0.2, location=(0, 0, 3.5))
    hook_empty = bpy.context.active_object
    hook_empty.name = "HookHelper"

    # Add Hook Modifier to Sheet
    bpy.context.view_layer.objects.active = sheet
    hook_mod = sheet.modifiers.new(name="Hook", type='HOOK')
    hook_mod.object = hook_empty
    hook_mod.vertex_group = "HookGroup"

    # Animate
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 180 # Extra frames to settle
    
    # Frame 1-100: Sheet settles (No movement of hook, just physics)
    # Frame 100-160: Pull up
    hook_empty.keyframe_insert(data_path="location", frame=100)
    hook_empty.location.z = 7.0 # Pull up
    hook_empty.location.x = 2.0 # Pull slightly side
    hook_empty.keyframe_insert(data_path="location", frame=160)
    
    # Frame 165: Drop (Hook strength 0)
    hook_mod.strength = 1.0
    hook_mod.keyframe_insert(data_path="strength", frame=160)
    hook_mod.strength = 0.0
    hook_mod.keyframe_insert(data_path="strength", frame=165)

    # 5. Lighting
    # Function to add spot
    def add_spot(name, loc, color):
        bpy.ops.object.light_add(type='SPOT', location=loc)
        light = bpy.context.active_object
        light.name = name
        light.data.energy = 500
        light.data.color = color
        light.data.spot_size = math.radians(45)
        
        # Track Ball
        tt = light.constraints.new(type='TRACK_TO')
        tt.target = ball
        tt.track_axis = 'TRACK_NEGATIVE_Z'
        tt.up_axis = 'UP_Y'
        
    add_spot("SpotR", (4, -2, 5), (1, 0, 0))
    add_spot("SpotG", (-4, -2, 5), (0, 1, 0))
    add_spot("SpotB", (0, 5, 5), (0, 0, 1))

    # 6. Camera
    bpy.ops.object.camera_add(location=(0, -8, 5))
    cam = bpy.context.active_object
    cam.rotation_euler = (math.radians(60), 0, 0)
    scene.camera = cam
    
    return ball, floor, sheet

# ==============================================================================
# MANUAL X3D EXPORT (X3D 4.0 / PBR / VERTEX ANIMATION)
# ==============================================================================

def export_manual_x3d(filepath, objects_to_export, anim_obj):
    """
    Manually writes an X3D file.
    anim_obj: The object that requires vertex baking (The Sheet).
    """
    print(f"Starting X3D Export to {filepath}...")
    
    scene = bpy.context.scene
    start_frame = scene.frame_start
    end_frame = scene.frame_end
    fps = scene.render.fps
    
    # Format Helpers
    def fmt_col(c): return f"{c[0]:.4f} {c[1]:.4f} {c[2]:.4f}"
    def fmt_vec(v): return f"{v[0]:.4f} {v[1]:.4f} {v[2]:.4f}"
    
    with open(filepath, 'w', encoding='utf-8') as f:
        # 1. Header (X3D 4.0)
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "http://www.web3d.org/specifications/x3d-4.0.dtd">\n')
        f.write('<X3D profile="Interchange" version="4.0" xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance" xsd:noNamespaceSchemaLocation="http://www.web3d.org/specifications/x3d-4.0.xsd">\n')
        f.write('  <head>\n')
        f.write('    <meta name="generator" content="Blender 5.0 Custom Script"/>\n')
        f.write('  </head>\n')
        f.write('  <Scene>\n')
        
        # 2. Global Transform (Blender Z-up to X3D default if needed, 
        # but here we keep Z-up logic and assume viewer handles it or we rotate root)
        # Let's rotate -90 on X to make Z up in a Y-up viewer.
        f.write('    <Transform rotation="1 0 0 -1.5708">\n')
        
        # 3. Viewpoint
        # Simple approximation of current camera
        if scene.camera:
            loc = scene.camera.location
            # Convert rotation roughly or just look at center
            f.write(f'      <Viewpoint position="{fmt_vec(loc)}" orientation="1 0 0 1.0" description="Main View" centerOfRotation="0 0 1"/>\n')

        # 4. Lights
        # Convert Blender lights to X3D lights
        for obj in bpy.data.objects:
            if obj.type == 'LIGHT' and obj.visible_get():
                l = obj.data
                color = fmt_col(l.color)
                loc = fmt_vec(obj.location)
                # Simple approximation for Spot
                f.write(f'      <SpotLight location="{loc}" color="{color}" intensity="1.0" radius="20" direction="0 0 -1" cutOffAngle="0.78"/>\n')

        # 5. Static Meshes
        depsgraph = bpy.context.evaluated_depsgraph_get()
        
        for obj in objects_to_export:
            if obj == anim_obj: continue # Handle animated object separately
            if obj.type != 'MESH': continue
            
            verts, indices = get_mesh_data_for_export(obj) # Static, no depsgraph needed strictly if no anim modifiers
            
            # Material
            mat = obj.active_material
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            base_col = fmt_col(bsdf.inputs['Base Color'].default_value)
            rough = bsdf.inputs['Roughness'].default_value
            metal = bsdf.inputs['Metallic'].default_value
            
            f.write(f'      <Transform translation="{fmt_vec(obj.location)}">\n')
            f.write('        <Shape>\n')
            f.write('          <Appearance>\n')
            # PBR Material (X3D 4.0 PhysicalMaterial)
            f.write(f'            <PhysicalMaterial baseColor="{base_col}" roughness="{rough}" metalness="{metal}"/>\n')
            f.write('          </Appearance>\n')
            
            # Geometry
            idx_str = " ".join([f"{i[0]} {i[1]} {i[2]} -1" for i in indices])
            pt_str = " ".join([fmt_vec(v) for v in verts])
            
            f.write(f'          <IndexedFaceSet coordIndex="{idx_str}" creaseAngle="3.14159">\n')
            f.write(f'            <Coordinate point="{pt_str}"/>\n')
            f.write('          </IndexedFaceSet>\n')
            f.write('        </Shape>\n')
            f.write('      </Transform>\n')

        # 6. Animated Mesh (The Sheet)
        # We need to bake vertex positions for every frame
        print("Baking vertex animation...")
        
        # Pre-calc keys
        keys = []
        key_values = []
        
        # Get topology once (indices)
        verts_static, indices_static = get_mesh_data_for_export(anim_obj) # Just for indices
        idx_str = " ".join([f"{i[0]} {i[1]} {i[2]} -1" for i in indices_static])
        
        # Loop frames
        total_frames = end_frame - start_frame + 1
        
        for frame in range(start_frame, end_frame + 1):
            scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            
            # Get evaluated mesh (Cloth applied)
            eval_obj = anim_obj.evaluated_get(depsgraph)
            # Important: Apply global transform to verts because we are baking world space 
            # (or local space if we keep the Transform node static. Cloth moves vertices in local space usually)
            # Actually, Hook moves verts in local space, but the mesh object stays at origin usually? 
            # Let's export local coords and assume object transform is static.
            
            mesh = eval_obj.to_mesh()
            
            # We must ensure vertex count matches exactly. 
            # Primitive Grid geometry shouldn't change count, just position.
            current_verts = [v.co[:] for v in mesh.vertices]
            
            # Flatten
            flat_verts = " ".join([fmt_vec(v) for v in current_verts])
            key_values.append(flat_verts)
            
            # Key fraction
            keys.append((frame - start_frame) / (end_frame - start_frame))
            
            eval_obj.to_mesh_clear()

        # Write Animated Shape
        # Mat
        mat = anim_obj.active_material
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        base_col = fmt_col(bsdf.inputs['Base Color'].default_value)
        
        f.write(f'      <Transform translation="{fmt_vec(anim_obj.location)}">\n')
        f.write('        <Shape>\n')
        f.write('          <Appearance>\n')
        f.write(f'            <PhysicalMaterial baseColor="{base_col}" roughness="0.8" metalness="0.0"/>\n')
        f.write('          </Appearance>\n')
        
        # IndexedFaceSet with DEF for routing
        f.write(f'          <IndexedFaceSet DEF="SheetGeom" coordIndex="{idx_str}" creaseAngle="3.14159">\n')
        # Initial Coordinate state
        f.write(f'            <Coordinate DEF="SheetCoords" point="{key_values[0]}"/>\n')
        f.write('          </IndexedFaceSet>\n')
        f.write('        </Shape>\n')
        f.write('      </Transform>\n')
        
        # 7. Animation Nodes (Interpolator & Timer)
        duration = total_frames / fps
        key_str = " ".join([f"{k:.4f}" for k in keys])
        
        # We write keyValues carefully. It's a massive string.
        # X3D CoordinateInterpolator: keyValue contains lists of vectors corresponding to keys.
        kv_str = "  ".join(key_values) 
        
        f.write(f'      <TimeSensor DEF="AnimTimer" cycleInterval="{duration:.2f}" loop="true"/>\n')
        f.write(f'      <CoordinateInterpolator DEF="SheetAnim" key="{key_str}" keyValue="{kv_str}"/>\n')
        
        # 8. Routing
        f.write('      <ROUTE fromNode="AnimTimer" fromField="fraction_changed" toNode="SheetAnim" toField="set_fraction"/>\n')
        f.write('      <ROUTE fromNode="SheetAnim" fromField="value_changed" toNode="SheetCoords" toField="point"/>\n')

        f.write('    </Transform>\n') # End Global Rotation
        f.write('  </Scene>\n')
        f.write('</X3D>\n')
    
    print("Export Complete.")

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

if __name__ == "__main__":
    # 1. Setup
    ball, floor, sheet = setup_scene()
    
    # 2. Run Scene to populate Physics Cache (Optional but ensures data availability)
    # Toggling frame helps initialize modifiers
    bpy.context.scene.frame_set(1)
    
    # 3. Export
    tmp_dir = tempfile.gettempdir()
    file_path = os.path.join(tmp_dir, "cloth_simulation.x3d")
    
    # Only export visual meshes, ignore helpers
    objects_to_export = [ball, floor, sheet]
    
    # Run the custom exporter
    export_manual_x3d(file_path, objects_to_export, anim_obj=sheet)
    
    print(f"X3D file saved to: {file_path}")
