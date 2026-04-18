import bpy
import bmesh
import math
import os
import tempfile

def create_scene():
    # -------------------------------------------------------------------------
    # 1. SETUP & CLEANUP
    # -------------------------------------------------------------------------
    # Switch to Object mode if not already
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Clear all objects, meshes, and materials
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    
    for block in bpy.data.meshes: bpy.data.meshes.remove(block)
    for block in bpy.data.materials: bpy.data.materials.remove(block)
    for block in bpy.data.lights: bpy.data.lights.remove(block)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = 120
    
    # Enable the X3D Addon if not already enabled (Standard built-in)
    addon_name = "io_scene_x3d"
    if addon_name not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module=addon_name)
        except Exception as e:
            print(f"Could not enable X3D addon: {e}")

    # -------------------------------------------------------------------------
    # 2. CREATE THE MIRROR BALL
    # -------------------------------------------------------------------------
    ball_radius = 1.0
    # Position ball so bottom touches Z=0
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=ball_radius, 
        segments=64, 
        ring_count=32, 
        location=(0, 0, ball_radius)
    )
    ball = bpy.context.object
    ball.name = "MirrorBall"
    bpy.ops.object.shade_smooth()
    
    # Add Collision Modifier to Ball (so cloth hits it)
    bpy.ops.object.modifier_add(type='COLLISION')
    ball.modifiers["Collision"].settings.thickness_outer = 0.02

    # Create Mirror Material
    mat_mirror = bpy.data.materials.new(name="Chrome")
    mat_mirror.use_nodes = True
    nodes = mat_mirror.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    
    # Blender 4.0+ API safe input access
    bsdf.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1)
    bsdf.inputs["Metallic"].default_value = 1.0
    bsdf.inputs["Roughness"].default_value = 0.0
    
    ball.data.materials.append(mat_mirror)

    # -------------------------------------------------------------------------
    # 3. CREATE THE GROUND (FLOOR)
    # -------------------------------------------------------------------------
    # The floor is at Z=0 (Level of the bottom of the ball)
    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "Floor"
    
    # Add Collision to Floor
    bpy.ops.object.modifier_add(type='COLLISION')
    
    # Optional: Hide floor from render if you only want the crumbled cloth visible
    # But useful for physics. We will make it visible for context.
    mat_floor = bpy.data.materials.new(name="FloorMat")
    mat_floor.use_nodes = True
    mat_floor.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.1, 0.1, 0.1, 1)
    floor.data.materials.append(mat_floor)

    # -------------------------------------------------------------------------
    # 4. CREATE THE CLOTH SHEET
    # -------------------------------------------------------------------------
    # Create grid above the ball
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=80, 
        y_subdivisions=80, 
        size=4, 
        location=(0, 0, ball_radius * 2.5)
    )
    cloth_obj = bpy.context.object
    cloth_obj.name = "Sheet"
    bpy.ops.object.shade_smooth()

    # Create a material for the sheet
    mat_cloth = bpy.data.materials.new(name="Velvet")
    mat_cloth.use_nodes = True
    c_nodes = mat_cloth.node_tree.nodes
    c_bsdf = c_nodes.get("Principled BSDF")
    c_bsdf.inputs["Base Color"].default_value = (0.8, 0.1, 0.1, 1) # Red sheet
    c_bsdf.inputs["Roughness"].default_value = 1.0
    cloth_obj.data.materials.append(mat_cloth)

    # Create a Vertex Group for the "Hook" (Top center part of sheet)
    # This allows us to pull it.
    vg = cloth_obj.vertex_groups.new(name="PullGroup")
    
    # Select center vertices to hook
    bm = bmesh.new()
    bm.from_mesh(cloth_obj.data)
    bm.verts.ensure_lookup_table()
    
    center_verts = []
    for v in bm.verts:
        # Select vertices near the center
        if v.co.x**2 + v.co.y**2 < 0.2:
            center_verts.append(v.index)
            
    vg.add(center_verts, 1.0, 'REPLACE')
    bm.free()

    # Add Cloth Modifier
    bpy.ops.object.modifier_add(type='CLOTH')
    c_settings = cloth_obj.modifiers["Cloth"].settings
    c_settings.quality = 5
    c_settings.mass = 0.3
    c_settings.tension_stiffness = 15
    c_settings.compression_stiffness = 15
    c_settings.shear_stiffness = 5
    c_settings.bending_stiffness = 0.5
    
    # Enable Self Collision
    c_settings.use_self_collision = True
    
    # -------------------------------------------------------------------------
    # 5. ANIMATION & HOOK MECHANIC
    # -------------------------------------------------------------------------
    # Create an Empty to act as the "Hand" pulling the sheet
    bpy.ops.object.empty_add(type='SPHERE', radius=0.5, location=(0, 0, ball_radius * 3))
    hook_empty = bpy.context.object
    hook_empty.name = "HookHandle"

    # Select Cloth and add Hook Modifier targeting the Empty
    bpy.context.view_layer.objects.active = cloth_obj
    bpy.ops.object.modifier_add(type='HOOK')
    mod_hook = cloth_obj.modifiers["Hook"]
    mod_hook.object = hook_empty
    mod_hook.vertex_group = "PullGroup"
    
    # Move Hook modifier *before* Cloth modifier so the pull happens before physics
    bpy.ops.object.modifier_move_up(modifier="Hook")

    # --- Animate the Hook Handle (The Pull) ---
    # Frame 1-30: Static (let cloth settle on ball slightly)
    hook_empty.location = (0, 0, ball_radius * 2.2) # Start slightly lower to drape
    hook_empty.keyframe_insert(data_path="location", frame=1)
    hook_empty.keyframe_insert(data_path="location", frame=30)

    # Frame 50: Pull Up and Away
    hook_empty.location = (2, 2, 5) # Pull to side and up
    hook_empty.keyframe_insert(data_path="location", frame=50)

    # --- Animate the Hook Modifier Strength (The Release) ---
    # We want to hold the cloth, then let go so it crumbles
    mod_hook.strength = 1.0
    mod_hook.keyframe_insert(data_path="strength", frame=50)
    
    mod_hook.strength = 0.0 # Let go
    mod_hook.keyframe_insert(data_path="strength", frame=55)

    # -------------------------------------------------------------------------
    # 6. LIGHTING
    # -------------------------------------------------------------------------
    # Create 3 lights in a circle pointing at the ball
    for i in range(3):
        angle = (i / 3) * (2 * math.pi)
        dist = 5
        x = math.cos(angle) * dist
        y = math.sin(angle) * dist
        z = 4
        
        bpy.ops.object.light_add(type='AREA', location=(x, y, z))
        light = bpy.context.object
        light.data.energy = 500
        
        # Add Track To constraint
        track = light.constraints.new(type='TRACK_TO')
        track.target = ball
        track.track_axis = 'TRACK_NEGATIVE_Z'
        track.up_axis = 'UP_Y'

    # -------------------------------------------------------------------------
    # 7. EXPORT LOGIC
    # -------------------------------------------------------------------------
    # Note: Standard X3D export usually exports the static mesh state.
    # To get the crumbled state, we must be at that frame.
    
    print("Scene generated.")
    print("Please play animation (Spacebar) to see the physics.")
    
    # Set current frame to end to prepare for export (crumbled state)
    bpy.context.scene.frame_set(100)
    
    # Define export path (Temporary directory)
    filename = "mirrored_ball_reveal.x3d"
    export_path = os.path.join(tempfile.gettempdir(), filename)
    
    try:
        # Select what to export
        bpy.ops.object.select_all(action='SELECT')
        
        # Note: X3D export in Blender typically creates a static snapshot 
        # of the current frame or transforms. It does not natively support 
        # baking Vertex Cache (cloth sim) to X3D animation nodes without plugins.
        bpy.ops.export_scene.x3d(
            filepath=export_path, 
            use_selection=True
        )
        print(f"Successfully exported X3D to: {export_path}")
    except Exception as e:
        print(f"Export failed (Check if X3D addon is enabled): {e}")

    # Reset frame to 1 for user convenience
    bpy.context.scene.frame_set(1)

if __name__ == "__main__":
    create_scene()
