"""
mirror_ball_reveal.py
─────────────────────────────────────────────────────────────────────────────
Blender Python script: Mirror-ball cloth-reveal animation + X3D XML export
─────────────────────────────────────────────────────────────────────────────

HOW TO RUN
  1. Open Blender (3.6 LTS or later recommended; works in 4.x too).
  2. Switch to the "Scripting" workspace.
  3. Paste / load this file and click ▶ Run Script.
  4. Wait for the cloth bake (progress shown in terminal / Info bar).
  5. Two X3D files land in the same folder as the .blend (or ~/):
       mirror_ball_reveal_final.x3d   – sheet crumpled on ground, ball exposed
       mirror_ball_reveal_midpull.x3d – sheet mid-pull off the ball

TIMELINE  (160 frames @ 24 fps ≈ 6.7 s)
  Frames   1-40   Sheet drapes/settles under gravity (hook holds center up)
  Frames  41-110  Hook sweeps up-and-away → sheet peels off the ball
  Frames 111-160  Sheet in free-fall → crumples on ground at ball-base level
─────────────────────────────────────────────────────────────────────────────
"""

import bpy
import bmesh
import math
import mathutils
import os

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def bl_to_x3d(v):
    """Blender Z-up  →  X3D / VRML Y-up  (swap Y↔Z, negate new Z)."""
    return (v.x, v.z, -v.y)


def set_keyframe_linear(obj, data_path, frame):
    """Insert keyframe and set interpolation to LINEAR."""
    obj.keyframe_insert(data_path=data_path, frame=frame)
    for fc in obj.animation_data.action.fcurves:
        if fc.data_path == data_path:
            for kp in fc.keyframe_points:
                if kp.co[0] == frame:
                    kp.interpolation = 'LINEAR'


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENE SETUP
# ═══════════════════════════════════════════════════════════════════════════════

# ── Clear ──────────────────────────────────────────────────────────────────────
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for blk in [bpy.data.meshes, bpy.data.materials, bpy.data.cameras,
            bpy.data.lights, bpy.data.actions]:
    for item in blk:
        blk.remove(item, do_unlink=True)

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end   = 160
scene.render.engine = 'BLENDER_EEVEE'   # change to 'CYCLES' for ray-traced renders

# ── Gravity ────────────────────────────────────────────────────────────────────
scene.gravity = (0.0, 0.0, -9.81)


# ═══════════════════════════════════════════════════════════════════════════════
#  MIRROR BALL
# ═══════════════════════════════════════════════════════════════════════════════

bpy.ops.mesh.primitive_uv_sphere_add(
    radius=1.0, segments=48, ring_count=24,
    location=(0.0, 0.0, 1.05)            # rests just above ground
)
ball = bpy.context.active_object
ball.name = "MirrorBall"

mat_mirror = bpy.data.materials.new("Mirror")
mat_mirror.use_nodes = True
nt = mat_mirror.node_tree
nt.nodes.clear()
bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
bsdf.inputs['Base Color'].default_value  = (0.88, 0.92, 1.0, 1.0)
bsdf.inputs['Metallic'].default_value    = 1.0
bsdf.inputs['Roughness'].default_value   = 0.0
# Specular (IOR in Blender 4.x, Specular in 3.x)
for name in ('Specular', 'Specular IOR Level'):
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = 1.0
out_node = nt.nodes.new('ShaderNodeOutputMaterial')
nt.links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
ball.data.materials.append(mat_mirror)

# Cloth collision on the ball
ball.modifiers.new("BallCollision", 'COLLISION')
ball.modifiers["BallCollision"].settings.thickness_outer = 0.02


# ═══════════════════════════════════════════════════════════════════════════════
#  GROUND
# ═══════════════════════════════════════════════════════════════════════════════

bpy.ops.mesh.primitive_plane_add(size=14.0, location=(0.0, 0.0, 0.0))
ground = bpy.context.active_object
ground.name = "Ground"

mat_ground = bpy.data.materials.new("GroundMat")
mat_ground.use_nodes = True
nt_g = mat_ground.node_tree
bsdf_g = nt_g.nodes['Principled BSDF']
bsdf_g.inputs['Base Color'].default_value = (0.04, 0.04, 0.07, 1.0)
bsdf_g.inputs['Roughness'].default_value  = 0.95
ground.data.materials.append(mat_ground)

coll_ground = ground.modifiers.new("GroundCollision", 'COLLISION')
coll_ground.settings.thickness_outer = 0.005


# ═══════════════════════════════════════════════════════════════════════════════
#  CLOTH SHEET
# ═══════════════════════════════════════════════════════════════════════════════

# Start as a flat plane centred above the ball
bpy.ops.mesh.primitive_plane_add(size=3.4, location=(0.0, 0.0, 2.35))
sheet = bpy.context.active_object
sheet.name = "Sheet"

# Dense grid for cloth quality
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.subdivide(number_cuts=20)   # 21×21 = 441 verts / 400 quads
bpy.ops.object.mode_set(mode='OBJECT')

# ── Sheet material ─────────────────────────────────────────────────────────────
mat_sheet = bpy.data.materials.new("SheetMat")
mat_sheet.use_nodes = True
nt_s = mat_sheet.node_tree
bsdf_s = nt_s.nodes['Principled BSDF']
bsdf_s.inputs['Base Color'].default_value = (0.96, 0.96, 0.97, 1.0)
bsdf_s.inputs['Roughness'].default_value  = 0.22
for sheen_name in ('Sheen Weight', 'Sheen'):
    if sheen_name in bsdf_s.inputs:
        bsdf_s.inputs[sheen_name].default_value = 0.7
        break
sheet.data.materials.append(mat_sheet)

# ── Pin vertex-group (centre cluster – the part the hook grabs) ────────────────
pin_vg = sheet.vertex_groups.new(name="PinCenter")
for v in sheet.data.vertices:
    r = math.sqrt(v.co.x**2 + v.co.y**2)
    if r < 0.32:
        pin_vg.add([v.index], 1.0, 'REPLACE')


# ═══════════════════════════════════════════════════════════════════════════════
#  HOOK EMPTY  (animates the pinned centre)
# ═══════════════════════════════════════════════════════════════════════════════

bpy.ops.object.empty_add(type='SPHERE', location=(0.0, 0.0, 2.35))
hook_empty = bpy.context.active_object
hook_empty.name = "SheetHook"
hook_empty.empty_display_size = 0.12

# Animation: hold → sweep up-and-away
for frame, loc in [
    (1,   (0.0,  0.0,  2.35)),    # start – sheet flat above ball
    (40,  (0.0,  0.0,  2.35)),    # stay while draping under gravity
    (110, (5.5,  1.5,  6.0)),     # sweep out and up (reveal)
    (160, (6.5,  2.0,  6.5)),     # keep moving offscreen
]:
    hook_empty.location = loc
    hook_empty.keyframe_insert(data_path="location", frame=frame)

# Smooth out the animation curves
if hook_empty.animation_data and hook_empty.animation_data.action:
    for fc in hook_empty.animation_data.action.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'


# ═══════════════════════════════════════════════════════════════════════════════
#  MODIFIERS ON SHEET  (Hook BEFORE Cloth so pinned verts follow the empty)
# ═══════════════════════════════════════════════════════════════════════════════

bpy.context.view_layer.objects.active = sheet
sheet.select_set(True)

# 1. Hook modifier
hook_mod = sheet.modifiers.new("Hook", 'HOOK')
hook_mod.object       = hook_empty
hook_mod.vertex_group = "PinCenter"

# 2. Cloth modifier
cloth_mod = sheet.modifiers.new("Cloth", 'CLOTH')
cs = cloth_mod.settings
cs.quality              = 10
cs.mass                 = 0.38
cs.tension_stiffness    = 14.0
cs.compression_stiffness= 14.0
cs.shear_stiffness      = 5.0
cs.bending_stiffness    = 0.07
cs.vertex_group_mass    = "PinCenter"    # pin group follows hook
cs.pin_stiffness        = 1.0

# Collision settings
cc = cloth_mod.collision_settings
cc.use_collision      = True
cc.use_self_collision = True
try:
    cc.distance_min      = 0.005
    cc.self_distance_min = 0.005
except AttributeError:
    pass  # older API name
try:
    cc.collision_quality = 4
except AttributeError:
    pass


# ═══════════════════════════════════════════════════════════════════════════════
#  LIGHTS  (6 coloured point lights + 1 top-down white key)
# ═══════════════════════════════════════════════════════════════════════════════

light_specs = [
    # location           energy  R     G     B
    (( 3.8,  0.0, 4.5),  700,   1.00, 0.82, 0.65),   # warm amber   front-R
    ((-3.8,  0.0, 4.5),  700,   0.65, 0.82, 1.00),   # cool blue    front-L
    (( 0.0,  3.8, 4.5),  600,   1.00, 0.65, 0.85),   # magenta      back-R
    (( 0.0, -3.8, 4.5),  600,   0.75, 1.00, 0.70),   # green-lime   back-L
    (( 2.5, -2.5, 5.5),  500,   1.00, 0.90, 0.60),   # gold         side
    ((-2.5,  2.5, 5.5),  500,   0.60, 0.80, 1.00),   # sky blue     side
    (( 0.0,  0.0, 8.0),  900,   1.00, 1.00, 1.00),   # white key    top
]

for i, (loc, energy, r, g, b) in enumerate(light_specs):
    bpy.ops.object.light_add(type='POINT', location=loc)
    lt = bpy.context.active_object
    lt.name = f"Light_{i:02d}"
    lt.data.energy           = energy
    lt.data.color            = (r, g, b)
    lt.data.shadow_soft_size = 0.5
    # Point toward the ball centre
    direction = mathutils.Vector((0, 0, 1.05)) - mathutils.Vector(loc)
    lt.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


# ═══════════════════════════════════════════════════════════════════════════════
#  CAMERA
# ═══════════════════════════════════════════════════════════════════════════════

bpy.ops.object.camera_add(location=(7.0, -5.5, 5.8))
cam = bpy.context.active_object
cam.name = "Camera"
cam.data.lens = 50.0

# Track-to target at ball centre
bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 1.2))
cam_target = bpy.context.active_object
cam_target.name = "CamTarget"

bpy.context.view_layer.objects.active = cam
tt = cam.constraints.new('TRACK_TO')
tt.target     = cam_target
tt.track_axis = 'TRACK_NEGATIVE_Z'
tt.up_axis    = 'UP_Y'

bpy.context.scene.camera = cam


# ═══════════════════════════════════════════════════════════════════════════════
#  BAKE CLOTH SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

print("\n─── Baking cloth simulation (frames 1-160) … ───")
bpy.ops.ptcache.bake_all(bake=True)
print("─── Cloth bake complete! ───\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOM X3D XML EXPORTER
#  (pure Python – no addon / extension required)
# ═══════════════════════════════════════════════════════════════════════════════

def export_x3d(filepath, export_frame):
    """
    Exports the evaluated mesh state at `export_frame` to X3D 3.3 XML.
    World-space vertices are converted from Blender (Z-up) to X3D (Y-up).
    Lights, materials, and a dark background are included.
    """
    scene.frame_set(export_frame)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    lines = []

    # ── XML header ────────────────────────────────────────────────────────────
    lines += [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 3.3//EN"',
        '    "http://www.web3d.org/specifications/x3d-3.3.dtd">',
        '<X3D version="3.3" profile="Interchange"',
        '    xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance"',
        '    xsd:noNamespaceSchemaLocation='
        '"http://www.web3d.org/specifications/x3d-3.3.xsd">',
        '  <head>',
        '    <meta name="title"     content="Mirror Ball Reveal Scene"/>',
        '    <meta name="generator" content="Blender Python Script (no addon)"/>',
        f'   <meta name="description" content="Frame {export_frame} of 160"/>',
        '  </head>',
        '  <Scene>',
        '',
        '    <!-- Environment -->',
        '    <Background skyColor="0.015 0.015 0.04"/>',
        '    <NavigationInfo headlight="false" type=\'"EXAMINE" "ANY"\'/>',
        '',
    ]

    # ── Lights ────────────────────────────────────────────────────────────────
    lines.append('    <!-- Lights -->')
    for obj in scene.objects:
        if obj.type != 'LIGHT':
            continue
        ld  = obj.data
        lx, ly, lz = bl_to_x3d(obj.location)
        intensity = min(ld.energy / 800.0, 1.0)
        r, g, b   = ld.color.r, ld.color.g, ld.color.b

        if ld.type == 'POINT':
            lines.append(
                f'    <PointLight DEF="{obj.name}"'
                f' location="{lx:.3f} {ly:.3f} {lz:.3f}"'
                f' intensity="{intensity:.3f}"'
                f' color="{r:.3f} {g:.3f} {b:.3f}"'
                f' radius="60.0"'
                f' attenuation="0.0 0.0 1.0"/>'
            )
        elif ld.type == 'SPOT':
            dv = obj.matrix_world.to_3x3() @ mathutils.Vector((0, 0, -1))
            dx, dy, dz = bl_to_x3d(dv)
            ca = ld.spot_size / 2.0
            lines.append(
                f'    <SpotLight DEF="{obj.name}"'
                f' location="{lx:.3f} {ly:.3f} {lz:.3f}"'
                f' direction="{dx:.4f} {dy:.4f} {dz:.4f}"'
                f' intensity="{intensity:.3f}"'
                f' color="{r:.3f} {g:.3f} {b:.3f}"'
                f' cutOffAngle="{ca:.3f}"'
                f' radius="60.0"/>'
            )

    lines.append('')

    # ── Mesh objects ──────────────────────────────────────────────────────────
    lines.append('    <!-- Geometry -->')

    # Skip internal helpers
    SKIP = {'SheetHook', 'CamTarget'}

    for obj in scene.objects:
        if obj.type != 'MESH':
            continue
        if obj.name in SKIP or not obj.visible_get():
            continue

        # Evaluated (modifiers applied, cloth cached)
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        if mesh is None or len(mesh.polygons) == 0:
            if mesh is not None:
                obj_eval.to_mesh_clear()
            continue

        # Triangulate with bmesh for clean export
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(mesh)
        bm.free()

        mat_world = obj.matrix_world

        # ── Material ──────────────────────────────────────────────────────────
        diff  = [0.6, 0.6, 0.6]
        spec  = [0.2, 0.2, 0.2]
        shin  = 0.2
        emis  = [0.0, 0.0, 0.0]

        if obj.data.materials and obj.data.materials[0]:
            mat = obj.data.materials[0]
            if mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        bc       = node.inputs['Base Color'].default_value
                        metallic = node.inputs['Metallic'].default_value
                        roughness= node.inputs['Roughness'].default_value

                        diff = [bc[0], bc[1], bc[2]]

                        if metallic > 0.5:
                            # Mirror: nearly-black diffuse, vivid specular
                            spec  = [bc[0]*0.9, bc[1]*0.9, bc[2]*0.9]
                            diff  = [bc[0]*0.04, bc[1]*0.04, bc[2]*0.04]
                            shin  = 1.0
                        else:
                            s    = max(0.0, 1.0 - roughness)
                            spec = [s * 0.4, s * 0.4, s * 0.4]
                            shin = s * 0.8
                        break

        def fv(lst):
            return ' '.join(f'{x:.4f}' for x in lst)

        # ── Vertices (world-space, Y-up) ──────────────────────────────────────
        coord_pts = []
        for v in mesh.vertices:
            wco = mat_world @ v.co
            x, y, z = bl_to_x3d(wco)
            coord_pts.append(f'{x:.5f} {y:.5f} {z:.5f}')

        # ── Face indices ──────────────────────────────────────────────────────
        ci_parts = []
        for poly in mesh.polygons:
            ci_parts.extend(str(vi) for vi in poly.vertices)
            ci_parts.append('-1')

        obj_name_safe = obj.name.replace(' ', '_')

        lines += [
            f'',
            f'    <!-- {obj_name_safe} -->',
            f'    <Shape DEF="{obj_name_safe}">',
            f'      <Appearance>',
            f'        <Material',
            f'          diffuseColor="{fv(diff)}"',
            f'          specularColor="{fv(spec)}"',
            f'          emissiveColor="{fv(emis)}"',
            f'          shininess="{shin:.4f}"',
            f'          ambientIntensity="0.15"/>',
            f'      </Appearance>',
            f'      <IndexedFaceSet solid="false" creaseAngle="0.6"',
            f'        coordIndex="{" ".join(ci_parts)}">',
            f'        <Coordinate',
            f'          point="{", ".join(coord_pts)}"/>',
            f'      </IndexedFaceSet>',
            f'    </Shape>',
        ]

        obj_eval.to_mesh_clear()

    lines += [
        '',
        '  </Scene>',
        '</X3D>',
    ]

    with open(filepath, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines))

    print(f"  ✓  X3D written → {filepath}")


# ═══════════════════════════════════════════════════════════════════════════════
#  OUTPUT PATHS
# ═══════════════════════════════════════════════════════════════════════════════

base_dir = (bpy.path.abspath("//")
            if bpy.data.is_saved
            else os.path.expanduser("~"))

path_final   = os.path.join(base_dir, "mirror_ball_reveal_final.x3d")
path_midpull = os.path.join(base_dir, "mirror_ball_reveal_midpull.x3d")

print("\n─── Exporting X3D files … ───")
export_x3d(path_final,   export_frame=160)   # sheet crumpled on ground
export_x3d(path_midpull, export_frame=80)    # sheet mid-pull

# Restore to frame 1 for interactive preview
scene.frame_set(1)

print(f"""
╔══════════════════════════════════════════════════════════════╗
║              MIRROR BALL REVEAL — COMPLETE                  ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Blender animation  : frames 1-160  (press Space to play)   ║
║                                                              ║
║  X3D exports:                                                ║
║   • mirror_ball_reveal_final.x3d    (frame 160 – revealed)  ║
║   • mirror_ball_reveal_midpull.x3d  (frame 80  – mid-pull)  ║
║                                                              ║
║  Open .x3d files in any X3D/VRML viewer (e.g. Instant       ║
║  Reality, FreeWRL, X3DOM in a browser, or Blender itself).  ║
╚══════════════════════════════════════════════════════════════╝
""")
