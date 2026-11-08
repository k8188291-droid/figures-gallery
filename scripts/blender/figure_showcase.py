"""Render a GLB figure in a simple showcase scene with Blender (Cycles).

Usage:
  blender -b -P scripts/blender/figure_showcase.py -- \
      --model "models/holo/holo coffee.glb" --scene studio --out renders/holo_coffee_studio.png

Scenes:
  studio  Glossy black acrylic base on a warm seamless backdrop, softbox key + rim light.
  desk    Light oak desk with morning sun through blinds, a few blurred props.

Both scenes use a real-world scale (figure ~15 cm tall) and a long lens with
shallow depth of field, so the focus stays on the figure and the set falls
off into bokeh.
"""

import argparse
import math
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

FIGURE_HEIGHT = 0.15  # metres


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------

def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--model', required=True, help='GLB/GLTF file to showcase')
    p.add_argument('--scene', choices=['studio', 'desk'], default='studio')
    p.add_argument('--out', required=True, help='Output image path (.png/.jpg)')
    p.add_argument('--yaw', type=float, default=0.0,
                   help='Extra rotation (deg, around Z) so the figure faces the camera. '
                        'glTF figures facing +Z need 0; e.g. holo coffee needs -90.')
    p.add_argument('--height', type=float, default=FIGURE_HEIGHT, help='Figure height in metres')
    p.add_argument('--res', default='1920x1280', help='Resolution WxH')
    p.add_argument('--samples', type=int, default=256)
    p.add_argument('--fstop', type=float, default=None, help='Override aperture f-stop (smaller = more blur)')
    p.add_argument('--angle', type=float, default=None, help='Override camera azimuth (deg, 0 = straight front)')
    p.add_argument('--save-blend', default=None, help='Also save the assembled scene to this .blend file')
    return p.parse_args(argv)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def hex_rgba(h, a=1.0):
    h = h.lstrip('#')
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, a)


def new_material(name):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:  # Blender 4.x creates materials without nodes
        mat.use_nodes = True
    return mat


def principled(name, color, roughness=0.5, **inputs):
    mat = new_material(name)
    bsdf = mat.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = hex_rgba(color) if isinstance(color, str) else color
    bsdf.inputs['Roughness'].default_value = roughness
    for key, value in inputs.items():
        bsdf.inputs[key].default_value = value
    return mat


def assign(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return obj


def smooth(obj):
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def add_box(name, size, location, mat=None, bevel=0.0, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=rotation)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        mod = obj.modifiers.new('Bevel', 'BEVEL')
        mod.width = bevel
        mod.segments = 3
        mod.limit_method = 'ANGLE'
    if mat:
        assign(obj, mat)
    return obj


def add_cylinder(name, radius, depth, location, mat=None, bevel=0.0, vertices=96):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location, vertices=vertices)
    obj = bpy.context.active_object
    obj.name = name
    if bevel:
        mod = obj.modifiers.new('Bevel', 'BEVEL')
        mod.width = bevel
        mod.segments = 4
        mod.limit_method = 'ANGLE'
    bpy.ops.object.shade_auto_smooth()
    if mat:
        assign(obj, mat)
    return obj


def add_area_light(name, location, target, size, power, color=(1, 1, 1), shape='RECTANGLE', size_y=None):
    data = bpy.data.lights.new(name, 'AREA')
    data.shape = shape
    data.size = size
    data.size_y = size_y or size
    data.energy = power
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, target)
    return obj


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def hide_from_camera(obj):
    obj.visible_camera = False
    obj.visible_glossy = False
    obj.visible_transmission = False


# --------------------------------------------------------------------------
# Figure
# --------------------------------------------------------------------------

def import_figure(path, height, yaw_deg, floor_z):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    imported = [o for o in bpy.data.objects if o not in before]

    root = bpy.data.objects.new('Figure', None)
    bpy.context.collection.objects.link(root)
    for obj in imported:
        if obj.parent is None:
            obj.parent = root

    pvc_finish({slot.material for o in imported if o.type == 'MESH' for slot in o.material_slots if slot.material})
    root.rotation_euler = (0, 0, math.radians(yaw_deg))
    bpy.context.view_layer.update()

    lo, hi = world_bounds([o for o in imported if o.type == 'MESH'])
    scale = height / (hi.z - lo.z)
    root.scale = (scale, scale, scale)
    bpy.context.view_layer.update()

    lo, hi = world_bounds([o for o in imported if o.type == 'MESH'])
    centre = (lo + hi) / 2
    root.location -= Vector((centre.x, centre.y, lo.z - floor_z))
    bpy.context.view_layer.update()
    return world_bounds([o for o in imported if o.type == 'MESH'])


def pvc_finish(materials, gamma=1.18, saturation=1.08, roughness=0.5):
    """Give scanned/generated figure textures a painted-PVC look.

    Such GLBs usually ship one albedo texture with roughness ~0.9 and no normal
    map, which reads flat and washed out under physically based light.
    """
    for mat in materials:
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if not bsdf:
            continue
        if not bsdf.inputs['Roughness'].is_linked:
            bsdf.inputs['Roughness'].default_value = min(bsdf.inputs['Roughness'].default_value, roughness)
        bsdf.inputs['Coat Weight'].default_value = 0.15
        bsdf.inputs['Coat Roughness'].default_value = 0.35
        base = bsdf.inputs['Base Color']
        if not base.is_linked:
            continue
        src = base.links[0].from_socket
        gam = nt.nodes.new('ShaderNodeGamma')
        gam.inputs['Gamma'].default_value = gamma
        hsv = nt.nodes.new('ShaderNodeHueSaturation')
        hsv.inputs['Saturation'].default_value = saturation
        nt.links.new(src, gam.inputs['Color'])
        nt.links.new(gam.outputs['Color'], hsv.inputs['Color'])
        nt.links.new(hsv.outputs['Color'], base)


def world_bounds(objects):
    deps = bpy.context.evaluated_depsgraph_get()
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    for obj in objects:
        ev = obj.evaluated_get(deps)
        for corner in ev.bound_box:
            p = ev.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


# --------------------------------------------------------------------------
# Camera
# --------------------------------------------------------------------------

def add_camera(bounds, azimuth_deg, elevation_deg, lens, fstop, fill=0.72, focus_height=0.62):
    lo, hi = bounds
    height = hi.z - lo.z
    sensor_h = 24.0
    # Distance so the figure fills `fill` of the frame height.
    distance = (height / fill) * lens / sensor_h

    target = Vector((0, 0, lo.z + height * 0.47))
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    offset = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el))) * distance

    cam_data = bpy.data.cameras.new('Camera')
    cam_data.lens = lens
    cam_data.sensor_fit = 'HORIZONTAL'
    cam_data.sensor_width = 36.0
    cam_data.clip_start = 0.01
    cam = bpy.data.objects.new('Camera', cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = target + offset
    look_at(cam, target)

    # Focus on the front of the figure around chest/face height.
    focus = bpy.data.objects.new('FocusTarget', None)
    bpy.context.collection.objects.link(focus)
    front_depth = (hi.y - lo.y) * 0.25
    focus.location = Vector((0, 0, lo.z + height * focus_height)) + offset.normalized() * front_depth
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = focus
    cam_data.dof.aperture_fstop = fstop
    cam_data.dof.aperture_blades = 7
    cam_data.dof.aperture_rotation = math.radians(12)

    bpy.context.scene.camera = cam
    return cam


# --------------------------------------------------------------------------
# Scene: studio
# --------------------------------------------------------------------------

def build_studio(args):
    base_r, base_h = 0.085, 0.012
    base = add_cylinder('AcrylicBase', base_r, base_h, (0, 0, base_h / 2), bevel=0.0025,
                        mat=principled('BlackAcrylic', '#050505', roughness=0.04,
                                       **{'Coat Weight': 1.0, 'Coat Roughness': 0.02}))

    bounds = import_figure(args.model, args.height, args.yaw, base_h)
    # Grow the base if the figure footprint is wider than expected.
    lo, hi = bounds
    need = max(abs(lo.x), abs(hi.x), abs(lo.y), abs(hi.y)) * 1.15
    if need > base_r:
        base.scale.x = base.scale.y = need / base_r

    # Seamless cyclorama: floor curving up into the back wall.
    cyc_mat = new_material('Backdrop')
    nt = cyc_mat.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = 0.75
    coord = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.3
    ramp.color_ramp.elements[0].color = hex_rgba('#D9B796')
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = hex_rgba('#7A4B32')
    nt.links.new(coord.outputs['Generated'], sep.inputs[0])
    nt.links.new(sep.outputs['X'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])

    mesh = bpy.data.meshes.new('Cyclorama')
    bm = bmesh.new()
    radius, width = 0.6, 4.0
    profile = [(y, 0.0) for y in (-2.5, -1.0, 0.0, 0.6)]
    for i in range(1, 16):
        t = i / 16 * math.pi / 2
        profile.append((0.6 + math.sin(t) * radius, radius - math.cos(t) * radius))
    profile += [(0.6 + radius, radius), (0.6 + radius, 1.5), (0.6 + radius, 3.0)]
    rows = [[bm.verts.new((x, y, z)) for (y, z) in profile] for x in (-width / 2, width / 2)]
    for i in range(len(profile) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(mesh)
    bm.free()
    cyc = bpy.data.objects.new('Cyclorama', mesh)
    bpy.context.collection.objects.link(cyc)
    smooth(assign(cyc, cyc_mat))

    centre = (0, 0, args.height * 0.55)
    # Large softbox key from front-left, rim strip from behind-right, soft fill from the right.
    add_area_light('Key', (-0.55, -0.5, 0.5), centre, 0.6, 26, color=(1.0, 0.95, 0.88))
    add_area_light('Rim', (0.35, 0.45, 0.35), (0, 0, args.height * 0.6), 0.08, 14,
                   color=(1.0, 0.85, 0.7), size_y=0.6)
    add_area_light('Fill', (0.7, -0.5, 0.15), centre, 0.8, 4, color=(0.95, 0.95, 1.0))
    add_area_light('Top', (0, 0.1, 0.9), centre, 0.5, 5)
    set_world((0.03, 0.025, 0.02), 1.0)

    add_camera(bounds, args.angle if args.angle is not None else -18, 9, lens=85,
               fstop=args.fstop or 4.0, fill=0.72)


# --------------------------------------------------------------------------
# Scene: desk
# --------------------------------------------------------------------------

def oak_material():
    mat = new_material('Oak')
    nt = mat.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = 0.42
    coord = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeMapping')
    mapping.inputs['Scale'].default_value = (1.0, 14.0, 1.0)
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 6.0
    noise.inputs['Detail'].default_value = 8.0
    wave = nt.nodes.new('ShaderNodeTexWave')
    wave.inputs['Scale'].default_value = 3.0
    wave.inputs['Distortion'].default_value = 6.0
    wave.inputs['Detail'].default_value = 4.0
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = hex_rgba('#C9A27A')
    ramp.color_ramp.elements[1].color = hex_rgba('#E3C49E')
    nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])
    nt.links.new(mapping.outputs['Vector'], wave.inputs['Vector'])
    nt.links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'FLOAT'
    mix.inputs['Factor'].default_value = 0.35
    nt.links.new(wave.outputs['Fac'], mix.inputs['A'])
    nt.links.new(noise.outputs['Fac'], mix.inputs['B'])
    nt.links.new(mix.outputs['Result'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    return mat


def build_desk(args):
    h = args.height
    bounds = import_figure(args.model, h, args.yaw, 0.0)

    desk = add_box('Desk', (2.4, 1.4, 0.04), (0, 0.35, -0.02), mat=oak_material(), bevel=0.004)
    desk.data.materials[0].node_tree.nodes['Mapping'].inputs['Rotation'].default_value[2] = math.radians(90)

    # Back wall with a bright window patch for soft background bokeh.
    wall = add_box('Wall', (4.0, 0.05, 2.2), (0, 1.25, 0.8), mat=principled('Wall', '#E9DCCB', 0.9))
    wall.visible_shadow = False
    window_mat = new_material('WindowGlow')
    window_mat.node_tree.nodes.remove(window_mat.node_tree.nodes['Principled BSDF'])
    em = window_mat.node_tree.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = hex_rgba('#FFE2B8')
    em.inputs['Strength'].default_value = 4.0
    window_mat.node_tree.links.new(em.outputs[0], window_mat.node_tree.nodes['Material Output'].inputs['Surface'])
    add_box('Window', (0.9, 0.01, 0.8), (0.05, 1.22, 0.4), mat=window_mat).visible_shadow = False
    # Blind slats over the window so the bokeh reads as a window, not a light box.
    slat_mat = principled('Slat', '#D9C2A3', 0.6)
    for i in range(14):
        slat = add_box(f'Slat{i}', (0.92, 0.03, 0.012), (0.05, 1.20, 0.03 + i * 0.054), mat=slat_mat,
                       rotation=(math.radians(-25), 0, 0))
        slat.visible_shadow = False

    # Props, kept simple and placed back so they fall into the blur.
    kb_rot = math.radians(14)
    kb_loc = Vector((-0.36, 0.26, 0.0))
    add_box('Keyboard', (0.36, 0.13, 0.022), kb_loc + Vector((0, 0, 0.011)),
            mat=principled('KbBase', '#4A4C50', 0.5), bevel=0.004, rotation=(0, 0, kb_rot))
    first_key = kb_loc + Vector((-0.162, -0.048, 0.028))
    first_key = kb_loc + (first_key - kb_loc) @ Matrix.Rotation(-kb_rot, 3, 'Z')
    keycap = add_box('Keycaps', (0.016, 0.016, 0.012), first_key, mat=principled('Keycap', '#EDE8DF', 0.45),
                     bevel=0.002, rotation=(0, 0, kb_rot))
    arr_x = keycap.modifiers.new('ArrayX', 'ARRAY')
    arr_x.count = 18
    arr_x.relative_offset_displace = (1.18, 0, 0)
    arr_y = keycap.modifiers.new('ArrayY', 'ARRAY')
    arr_y.count = 6
    arr_y.relative_offset_displace = (0, 1.18, 0)

    book_colors = ['#7A4A35', '#4F6650', '#B98A5A']
    for i, (w, d, t, rot) in enumerate([(0.24, 0.17, 0.035, 4), (0.22, 0.16, 0.03, -6), (0.2, 0.15, 0.028, 9)]):
        z = sum([0.035, 0.03, 0.028][:i]) + t / 2
        book = add_box(f'Book{i}', (w, d, t), (0.36, 0.32, z), mat=principled(f'Cover{i}', book_colors[i], 0.55),
                       bevel=0.003, rotation=(0, 0, math.radians(rot)))
        add_box(f'Pages{i}', (w - 0.012, d - 0.008, t - 0.006), (0.36 + 0.002, 0.32, z),
                mat=principled('Pages', '#F2EAD8', 0.8), rotation=(0, 0, math.radians(rot)))

    ceramic = principled('Ceramic', '#E8DED0', 0.35)
    mug = add_cylinder('Mug', 0.042, 0.095, (0.24, 0.2, 0.0475), mat=ceramic, bevel=0.003)
    solid = mug.modifiers.new('Solidify', 'SOLIDIFY')
    solid.thickness = 0.004
    bm = bmesh.new()
    bm.from_mesh(mug.data)
    top = [f for f in bm.faces if f.normal.z > 0.9]
    bmesh.ops.delete(bm, geom=top, context='FACES')
    bm.to_mesh(mug.data)
    bm.free()
    mug.modifiers.move(len(mug.modifiers) - 1, 0)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.022, minor_radius=0.006, location=(0.285, 0.2, 0.05),
                                     rotation=(math.radians(90), 0, 0))
    handle = bpy.context.active_object
    handle.name = 'MugHandle'
    smooth(assign(handle, ceramic))
    add_cylinder('Coffee', 0.038, 0.002, (0.24, 0.2, 0.08), mat=principled('Coffee', '#3B2215', 0.08))

    pot = add_cylinder('Pot', 0.05, 0.08, (0.52, 0.5, 0.04), mat=principled('Pot', '#D8CFC2', 0.7), bevel=0.004)
    leaf_mat = principled('Leaf', '#4E7A3A', 0.5, **{'Subsurface Weight': 0.15})
    for i in range(9):
        a = i * 2.4
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.028, location=(0.52 + 0.035 * math.cos(a),
                                                                     0.5 + 0.035 * math.sin(a), 0.1 + 0.012 * (i % 3)))
        leaf = bpy.context.active_object
        leaf.scale = (1.0, 0.55, 0.25)
        leaf.rotation_euler = (0.3, 0.2, a)
        smooth(assign(leaf, leaf_mat))

    # Low warm sun through blinds: an invisible slatted gobo casts the stripes.
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = 4.5
    sun_data.color = (1.0, 0.78, 0.52)
    sun_data.angle = math.radians(1.2)
    sun = bpy.data.objects.new('Sun', sun_data)
    bpy.context.collection.objects.link(sun)
    sun_dir = Vector((0.8, -0.3, -0.45)).normalized()  # direction light travels
    sun.rotation_euler = (-sun_dir).to_track_quat('Z', 'Y').to_euler()

    gobo_centre = Vector((0, 0, h * 0.5)) - sun_dir * 0.9
    gobo = bpy.data.objects.new('BlindsGobo', None)
    bpy.context.collection.objects.link(gobo)
    gobo.location = gobo_centre
    gobo.rotation_euler = (-sun_dir).to_track_quat('Z', 'X').to_euler()
    gobo_mat = principled('Gobo', '#000000', 1.0)
    for i in range(-14, 15):
        slat = add_box(f'Gobo{i}', (1.6, 0.022, 0.004), (0, i * 0.04, 0), mat=gobo_mat)
        slat.parent = gobo
        hide_from_camera(slat)

    add_area_light('Fill', (-0.6, -0.8, 0.4), (0, 0, h * 0.5), 1.0, 12, color=(1.0, 0.9, 0.8))
    add_area_light('Bounce', (0.6, -0.4, 0.05), (0, 0, h * 0.5), 0.6, 4, color=(1.0, 0.85, 0.7))
    set_world((0.35, 0.3, 0.25), 0.35)

    add_camera(bounds, args.angle if args.angle is not None else -12, 11, lens=85,
               fstop=args.fstop or 3.2, fill=0.68)


# --------------------------------------------------------------------------
# Render setup
# --------------------------------------------------------------------------

def set_world(color, strength):
    world = bpy.data.worlds.new('World')
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (*color, 1.0)
    bg.inputs['Strength'].default_value = strength
    bpy.context.scene.world = world


def configure_render(args):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = args.samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.01
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 8
    scene.cycles.blur_glossy = 0.5
    width, height = (int(v) for v in args.res.lower().split('x'))
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = 'Khronos PBR Neutral'
    scene.render.filepath = args.out
    if args.out.lower().endswith(('.jpg', '.jpeg')):
        scene.render.image_settings.file_format = 'JPEG'
        scene.render.image_settings.quality = 92
    else:
        scene.render.image_settings.file_format = 'PNG'


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    {'studio': build_studio, 'desk': build_desk}[args.scene](args)
    configure_render(args)
    if args.save_blend:
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=args.save_blend, compress=True)
    bpy.ops.render.render(write_still=True)


main()
