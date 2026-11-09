"""Render a GLB figure in a showcase scene with Blender (Cycles).

Usage:
  blender -b -P scripts/blender/figure_showcase.py -- \
      --model "models/holo/holo coffee.glb" --yaw -90 --scene studio --out renders/holo_coffee_studio.png

Scenes:
  studio  High-key catalogue shot: beige seamless backdrop,
          large soft boxes, low contrast, no base.
  desk    Cozy desk by a window: a modelled room with real blinds, so the
          morning sun falls on the desk and the figure in stripes; keyboard,
          stacked books with a plant, mug, wall shelf and lamp; light haze.

Focus is placed by ray casting onto the figure's face, so the figure is
always sharp.

The desk scene downloads CC0 assets from Poly Haven (polyhaven.com) on first
run and caches them in .cache/polyhaven.
"""

import argparse
import json
import math
import os
import statistics
import sys
import urllib.request

import bmesh
import bpy
from mathutils import Vector

FIGURE_HEIGHT = 0.15  # metres
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


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
    p.add_argument('--focus-height', type=float, default=0.72,
                   help='Focus point as a fraction of figure height (0.72 = face for most figures)')
    p.add_argument('--cache', default=os.path.join(REPO_ROOT, '.cache', 'polyhaven'),
                   help='Download cache for Poly Haven assets')
    p.add_argument('--save-blend', default=None, help='Also save the assembled scene to this .blend file')
    return p.parse_args(argv)


# --------------------------------------------------------------------------
# Poly Haven assets (CC0)
# --------------------------------------------------------------------------

USER_AGENT = 'figures-gallery-blender-showcase/1.0'


def _download(url, dest):
    if os.path.exists(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    with open(dest + '.part', 'wb') as f:
        f.write(data)
    os.replace(dest + '.part', dest)
    return dest


def _files(asset_id, cache):
    path = os.path.join(cache, asset_id, 'files.json')
    _download(f'https://api.polyhaven.com/files/{asset_id}', path)
    with open(path) as f:
        return json.load(f)


def polyhaven_model(asset_id, cache, res='1k'):
    files = _files(asset_id, cache)
    entry = files['gltf'][res]['gltf'] if 'gltf' in files else files['blend'][res]['blend']
    folder = os.path.join(cache, asset_id, res)
    for rel, info in entry.get('include', {}).items():
        _download(info['url'], os.path.join(folder, rel))
    return _download(entry['url'], os.path.join(folder, os.path.basename(entry['url'])))


def polyhaven_hdri(asset_id, cache, res='2k'):
    url = _files(asset_id, cache)['hdri'][res]['hdr']['url']
    return _download(url, os.path.join(cache, asset_id, os.path.basename(url)))


def polyhaven_texture(asset_id, cache, res='2k'):
    files = _files(asset_id, cache)
    maps = {}
    for key, name in (('Diffuse', 'diff'), ('Rough', 'rough'), ('nor_gl', 'nor')):
        url = files[key][res]['jpg']['url']
        maps[name] = _download(url, os.path.join(cache, asset_id, os.path.basename(url)))
    return maps


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


def add_area_light(name, location, target, size, power, color=(1, 1, 1), size_y=None, spread=180):
    data = bpy.data.lights.new(name, 'AREA')
    data.shape = 'RECTANGLE'
    data.size = size
    data.size_y = size_y or size
    data.energy = power
    data.color = color
    data.spread = math.radians(spread)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, target)
    return obj


def link_lights(lights, receivers):
    """Make `lights` illuminate only `receivers` (Cycles light linking)."""
    coll = bpy.data.collections.new('LightReceivers')
    for obj in receivers:
        coll.objects.link(obj)
    for light in lights:
        light.light_linking.receiver_collection = coll


def look_at(obj, target):
    direction = Vector(target) - Vector(obj.location)
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


def set_world_color(color, strength):
    world = bpy.data.worlds.new('World')
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (*color, 1.0)
    bg.inputs['Strength'].default_value = strength
    bpy.context.scene.world = world


def set_world_hdri(path, strength, rotation_z):
    world = bpy.data.worlds.new('World')
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes['Background']
    bg.inputs['Strength'].default_value = strength
    env = nt.nodes.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(path, check_existing=True)
    coord = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeMapping')
    mapping.inputs['Rotation'].default_value[2] = rotation_z
    nt.links.new(coord.outputs['Generated'], mapping.inputs['Vector'])
    nt.links.new(mapping.outputs['Vector'], env.inputs['Vector'])
    nt.links.new(env.outputs['Color'], bg.inputs['Color'])
    bpy.context.scene.world = world
    return env.image


def import_asset(path):
    before = set(bpy.data.objects)
    if path.endswith('.blend'):
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        for obj in dst.objects:
            if obj and obj.type in {'MESH', 'EMPTY'}:
                bpy.context.collection.objects.link(obj)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    imported = [o for o in bpy.data.objects if o not in before and o.users_collection]
    root = bpy.data.objects.new(os.path.splitext(os.path.basename(path))[0], None)
    bpy.context.collection.objects.link(root)
    for obj in imported:
        if obj.parent is None:
            obj.parent = root
    meshes = [o for o in imported if o.type == 'MESH']
    return root, meshes


def place(root, meshes, location, yaw_deg=0.0, scale=1.0, height=None):
    """Rotate/scale a root so its meshes sit centred on `location` (bottom at location.z)."""
    root.rotation_euler = (0, 0, math.radians(yaw_deg))
    root.scale = (scale,) * 3
    bpy.context.view_layer.update()
    if height:
        lo, hi = world_bounds(meshes)
        s = scale * height / (hi.z - lo.z)
        root.scale = (s,) * 3
        bpy.context.view_layer.update()
    lo, hi = world_bounds(meshes)
    centre = (lo + hi) / 2
    root.location += Vector(location) - Vector((centre.x, centre.y, lo.z))
    bpy.context.view_layer.update()
    return world_bounds(meshes)


def import_figure(path, height, yaw_deg, floor_z):
    root, meshes = import_asset(path)
    pvc_finish({slot.material for o in meshes for slot in o.material_slots if slot.material})
    bounds = place(root, meshes, (0, 0, floor_z), yaw_deg, height=height)
    return bounds, meshes


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

def add_camera(bounds, figure_meshes, args, azimuth_deg, elevation_deg, lens, fstop, fill, aim=0.47):
    lo, hi = bounds
    height = hi.z - lo.z
    distance = (height / fill) * lens / 24.0  # 24 mm = 3:2 frame height on a 36 mm sensor

    target = Vector((0, 0, lo.z + height * aim))
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
    bpy.context.scene.camera = cam
    bpy.context.view_layer.update()

    cam_data.dof.use_dof = True
    cam_data.dof.focus_distance = focus_distance(cam, figure_meshes, bounds, args.focus_height)
    cam_data.dof.aperture_fstop = fstop
    cam_data.dof.aperture_blades = 7
    cam_data.dof.aperture_rotation = math.radians(12)
    return cam


def focus_distance(cam, figure_meshes, bounds, focus_height):
    """Ray cast a small grid around the face and focus on the median hit distance."""
    lo, hi = bounds
    height = hi.z - lo.z
    deps = bpy.context.evaluated_depsgraph_get()
    origin = cam.matrix_world.translation
    right = cam.matrix_world.to_3x3() @ Vector((1, 0, 0))
    targets = set(figure_meshes)
    hits = []
    for dz in (-0.06, -0.03, 0.0, 0.03):
        for dx in (-0.08, -0.04, 0.0, 0.04, 0.08):
            point = Vector((0, 0, lo.z + height * (focus_height + dz))) + right * (dx * height)
            direction = (point - origin).normalized()
            start = origin.copy()
            for _ in range(8):  # step through any prop in front of the figure
                ok, loc, _n, _i, obj, _m = bpy.context.scene.ray_cast(deps, start, direction)
                if not ok:
                    break
                if obj.original in targets or obj in targets:
                    hits.append((loc - origin).length)
                    break
                start = loc + direction * 1e-4
    if not hits:
        return (Vector((0, 0, lo.z + height * focus_height)) - origin).length
    return statistics.median(hits)


# --------------------------------------------------------------------------
# Shared geometry
# --------------------------------------------------------------------------

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


def add_cyclorama(name, mat, back, radius=0.5, width=6.0, top=4.0):
    """Floor that curves up into a back wall at y=back (seamless photo backdrop)."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    profile = [(y, 0.0) for y in (-3.0, -1.0, 0.0, back)]
    for i in range(1, 16):
        t = i / 16 * math.pi / 2
        profile.append((back + math.sin(t) * radius, radius - math.cos(t) * radius))
    profile += [(back + radius, radius), (back + radius, top / 2), (back + radius, top)]
    rows = [[bm.verts.new((x, y, z)) for (y, z) in profile] for x in (-width / 2, width / 2)]
    for i in range(len(profile) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    assign(obj, mat)
    for poly in obj.data.polygons:
        poly.use_smooth = True
    return obj


def speckled_ceramic(name, color, speck='#6B5A4A'):
    mat = principled(name, color, 0.35, **{'Coat Weight': 0.5, 'Coat Roughness': 0.1})
    nt = mat.node_tree
    noise = nt.nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 400.0
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.68
    ramp.color_ramp.elements[0].color = hex_rgba(color)
    ramp.color_ramp.elements[1].position = 0.7
    ramp.color_ramp.elements[1].color = hex_rgba(speck)
    nt.links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
    return mat


# --------------------------------------------------------------------------
# Scene: studio
# --------------------------------------------------------------------------

def build_studio(args):
    """High-key catalogue shot: soft wrap-around light on a warm seamless backdrop."""
    h = args.height
    bounds, figure = import_figure(args.model, h, args.yaw, 0.0)

    backdrop = add_cyclorama('Cyclorama', principled('Backdrop', '#E4D3BC', 0.95), back=0.9, radius=0.5)

    face = (0, 0, h * 0.72)
    body = (0, 0, h * 0.5)
    # Big, close softboxes = soft shadows and low contrast, like a product catalogue.
    add_area_light('Key', (-0.55, -0.55, 0.42), face, 1.0, 14, color=(1.0, 0.96, 0.92))
    add_area_light('Fill', (0.65, -0.45, 0.22), body, 1.2, 6, color=(1.0, 0.97, 0.94))
    add_area_light('Top', (0.0, -0.05, 0.7), body, 0.8, 4)
    rim = add_area_light('Rim', (0.28, 0.32, 0.30), body, 0.12, 2.0, color=(1.0, 0.92, 0.84), size_y=0.5)
    link_lights([rim], figure)
    # Separate wash on the backdrop: bright peach on the left, falling to caramel on the right.
    wash = add_area_light('BackdropWash', (-0.9, 0.1, 0.7), (-0.6, 1.4, 0.3), 1.0, 40, color=(1.0, 0.95, 0.88))
    link_lights([wash], [backdrop])
    set_world_color((0.55, 0.5, 0.44), 0.35)

    add_camera(bounds, figure, args, args.angle if args.angle is not None else 15, 12, lens=85,
               fstop=args.fstop or 11, fill=0.8)


# --------------------------------------------------------------------------
# Scene: desk
# --------------------------------------------------------------------------

DESK_WOOD = 'oak_veneer_01'
DESK_OUTSIDE = 'autumn_forest_04'
WALL_Y = 1.0             # back wall behind the desk
LEFT_X = -0.8            # left wall, holding the window (outside the frame)
WINDOW = (-0.8, 0.45, 0.05, 1.2)     # y0, y1, z0, z1 of the window opening


def textured_material(name, maps, tile_m):
    mat = new_material(name)
    nt = mat.node_tree
    bsdf = nt.nodes['Principled BSDF']
    coord = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeMapping')
    mapping.inputs['Scale'].default_value = (1 / tile_m, 1 / tile_m, 1)
    nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])

    def tex(path, colorspace):
        node = nt.nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.load(path, check_existing=True)
        node.image.colorspace_settings.name = colorspace
        nt.links.new(mapping.outputs['Vector'], node.inputs['Vector'])
        return node

    nt.links.new(tex(maps['diff'], 'sRGB').outputs['Color'], bsdf.inputs['Base Color'])
    nt.links.new(tex(maps['rough'], 'Non-Color').outputs['Color'], bsdf.inputs['Roughness'])
    normal = nt.nodes.new('ShaderNodeNormalMap')
    nt.links.new(tex(maps['nor'], 'Non-Color').outputs['Color'], normal.inputs['Color'])
    nt.links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])
    bsdf.inputs['Coat Weight'].default_value = 0.2
    bsdf.inputs['Coat Roughness'].default_value = 0.25
    return mat


def build_room(wood, sun_dir):
    """A simple room: back wall, a left wall with a blinded window, floor and ceiling.

    The window is on the left wall, outside the frame, so the sun lights the
    figure from the front-left instead of from behind. Everything the camera
    sees is real geometry lit by the same sun, so figure and set always match.
    """
    y0, y1, z0, z1 = WINDOW
    lx = LEFT_X
    floor_z, ceil_z, right_x, front_y = -0.75, 1.9, 2.4, -2.6
    t = 0.08
    wall = principled('Plaster', '#EADFD0', 0.92)
    width = right_x - lx
    cx, cz, h_room = (lx + right_x) / 2, (ceil_z + floor_z) / 2, ceil_z - floor_z
    add_box('BackWall', (width, t, h_room), (cx, WALL_Y + t / 2, cz), wall)
    add_box('SideR', (t, WALL_Y - front_y, h_room), (right_x, (WALL_Y + front_y) / 2, cz), wall)
    add_box('Front', (width, t, h_room), (cx, front_y, cz), wall)
    add_box('Ceiling', (width, WALL_Y - front_y, t), (cx, (WALL_Y + front_y) / 2, ceil_z), wall)
    add_box('Floor', (width, WALL_Y - front_y, t), (cx, (WALL_Y + front_y) / 2, floor_z),
            principled('Floor', '#8A6A50', 0.6))
    # Left wall with the window opening.
    wx = lx - t / 2
    add_box('LeftFront', (t, y0 - front_y, h_room), (wx, (y0 + front_y) / 2, cz), wall)
    add_box('LeftBack', (t, WALL_Y - y1, h_room), (wx, (WALL_Y + y1) / 2, cz), wall)
    add_box('LeftBelow', (t, y1 - y0, z0 - floor_z), (wx, (y0 + y1) / 2, (z0 + floor_z) / 2), wall)
    add_box('LeftAbove', (t, y1 - y0, ceil_z - z1), (wx, (y0 + y1) / 2, (z1 + ceil_z) / 2), wall)

    # Window frame and horizontal blinds (real slats so sunlight comes through in stripes).
    frame = principled('Frame', '#F2ECE2', 0.5)
    fw = 0.035
    add_box('FrameF', (t + 0.01, fw, z1 - z0), (wx, y0 + fw / 2, (z0 + z1) / 2), frame)
    add_box('FrameB', (t + 0.01, fw, z1 - z0), (wx, y1 - fw / 2, (z0 + z1) / 2), frame)
    add_box('FrameT', (t + 0.01, y1 - y0, fw), (wx, (y0 + y1) / 2, z1 - fw / 2), frame)
    slat_mat = principled('Blinds', '#D9BE98', 0.55)
    pitch, depth = 0.026, 0.03
    # Tilt the slats so they block about half of the sun: crisp light/shadow stripes.
    slope = math.atan2(sun_dir.z, abs(sun_dir.x))
    tilt = slope + math.asin(min(1.0, 0.5 * pitch / depth))
    n = int((z1 - z0 - 0.04) / pitch)
    for i in range(n):
        add_box(f'Slat{i:02d}', (depth, y1 - y0 - 2 * fw, 0.0015),
                (lx + 0.03, (y0 + y1) / 2, z1 - 0.03 - i * pitch), slat_mat, rotation=(0, tilt, 0))
    add_box('BlindRail', (0.045, y1 - y0, 0.03), (lx + 0.03, (y0 + y1) / 2, z1 - 0.005), slat_mat)

    # Faint haze so the sun beams through the blinds are visible.
    haze = new_material('Haze')
    nt = haze.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    vol = nt.nodes.new('ShaderNodeVolumePrincipled')
    vol.inputs['Density'].default_value = 0.1
    vol.inputs['Color'].default_value = hex_rgba('#FFF4E6')
    vol.inputs['Anisotropy'].default_value = 0.5
    nt.links.new(vol.outputs[0], nt.nodes['Material Output'].inputs['Volume'])
    add_box('RoomHaze', (width - 0.1, WALL_Y - front_y - 0.1, h_room - 0.1),
            (cx, (WALL_Y + front_y) / 2, cz), haze)

    # Desk top against the back wall, running up to the window wall.
    add_box('Desk', (1.3 - lx, WALL_Y + 0.7, 0.03), ((lx + 1.3) / 2, (WALL_Y - 0.7) / 2, -0.015), wood, bevel=0.003)


def build_wall_shelf(cache):
    """Wooden wall shelf on the right: books, a warm lamp and a plant."""
    wood = principled('ShelfWood', '#B08356', 0.5)
    x0, x1 = 0.1, 0.85
    for z in (0.1, 0.36):
        add_box(f'Shelf{z}', (x1 - x0, 0.2, 0.02), ((x0 + x1) / 2, WALL_Y - 0.1, z), wood, bevel=0.002)
    add_box('ShelfSide', (0.02, 0.2, 0.4), (x1 + 0.01, WALL_Y - 0.1, 0.2), wood)

    covers = ['#8C5A3C', '#E3D6C0', '#4F6650', '#C2A27C', '#6B3A2E', '#D9CBB4', '#3E4E5E', '#B98A5A']
    x = 0.14
    for i, color in enumerate(covers):
        bw = 0.022 + 0.008 * ((i * 7) % 3)
        bh = 0.15 + 0.025 * ((i * 5) % 4)
        add_box(f'ShelfBook{i}', (bw, 0.15, bh), (x + bw / 2, WALL_Y - 0.1, 0.11 + bh / 2),
                principled(f'ShelfBook{i}', color, 0.6), bevel=0.002)
        x += bw + 0.004
    # Small glowing lamp.
    add_cylinder('LampBase', 0.02, 0.04, (0.5, WALL_Y - 0.1, 0.13), principled('Brass', '#B08D57', 0.3, Metallic=1.0))
    glow = new_material('LampGlow')
    nt = glow.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = hex_rgba('#FFD39A')
    em.inputs['Strength'].default_value = 6
    nt.links.new(em.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.035, location=(0.5, WALL_Y - 0.1, 0.18))
    bulb = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    assign(bulb, glow)
    # Plant on the top shelf.
    root, meshes = import_asset(polyhaven_model('potted_plant_04', cache))
    place(root, meshes, (0.65, WALL_Y - 0.1, 0.11), 30, height=0.16)


def build_desk_props(cache):
    # Keyboard, front-left.
    kb_rot = math.radians(10)
    kb = Vector((-0.3, 0.08, 0.0))
    rot = lambda v: Vector((v.x * math.cos(kb_rot) - v.y * math.sin(kb_rot),
                             v.x * math.sin(kb_rot) + v.y * math.cos(kb_rot), v.z))
    add_box('Keyboard', (0.36, 0.125, 0.02), kb + Vector((0, 0, 0.01)),
            principled('KbCase', '#55585C', 0.45), bevel=0.004, rotation=(0, 0, kb_rot))
    light_key = principled('KeyLight', '#EEEAE2', 0.4)
    dark_key = principled('KeyDark', '#A9ABAD', 0.4)
    for row in range(5):
        for col in range(15):
            local = Vector((-0.164 + col * 0.0234, -0.046 + row * 0.0234, 0.027))
            mat = dark_key if col in (0, 14) or row == 0 else light_key
            add_box(f'Key{row}_{col}', (0.019, 0.019, 0.012), kb + rot(local), mat,
                    bevel=0.002, rotation=(0, 0, kb_rot))

    # Stack of hardcover books with a plant, right.
    stack = Vector((0.32, 0.42, 0.0))
    pages = principled('Pages', '#F1E8D5', 0.8)
    z = 0.0
    for i, (w, d, tk, color, yaw) in enumerate([(0.26, 0.19, 0.042, '#7A4A35', 4),
                                                 (0.24, 0.175, 0.036, '#4F6650', -5),
                                                 (0.22, 0.165, 0.034, '#B49572', 8)]):
        cz = z + tk / 2
        add_box(f'Cover{i}', (w, d, tk), stack + Vector((0, 0, cz)), principled(f'Cover{i}', color, 0.6),
                bevel=0.003, rotation=(0, 0, math.radians(yaw)))
        add_box(f'Pages{i}', (w - 0.012, d + 0.002, tk - 0.008), stack + Vector((0.004, 0, cz)), pages,
                rotation=(0, 0, math.radians(yaw)))
        z += tk
    root, meshes = import_asset(polyhaven_model('potted_plant_04', cache))
    place(root, meshes, stack + Vector((0, 0, z)), 0, height=0.13)

    # Framed picture leaning against the back wall, left.
    root, meshes = import_asset(polyhaven_model('standing_picture_frame_01', cache))
    place(root, meshes, (-0.52, WALL_Y - 0.1, 0.0), 100, height=0.22)

    # Mug on a woven coaster, front-right.
    mug_at = Vector((0.18, 0.18, 0.0))
    add_cylinder('Coaster', 0.055, 0.005, mug_at + Vector((0, 0, 0.0025)), principled('Coaster', '#C8A77A', 0.9))
    ceramic = speckled_ceramic('Mug', '#E9DFD0')
    mug = add_cylinder('Mug', 0.038, 0.085, mug_at + Vector((0, 0, 0.0475)), ceramic, bevel=0.003)
    bm = bmesh.new()
    bm.from_mesh(mug.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context='FACES')
    bm.to_mesh(mug.data)
    bm.free()
    solid = mug.modifiers.new('Solidify', 'SOLIDIFY')
    solid.thickness = 0.004
    mug.modifiers.move(len(mug.modifiers) - 1, 0)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.022, minor_radius=0.0055,
                                     location=mug_at + Vector((0.04, 0, 0.05)), rotation=(math.radians(90), 0, 0))
    assign(bpy.context.active_object, ceramic)
    bpy.ops.object.shade_smooth()
    add_cylinder('Coffee', 0.035, 0.002, mug_at + Vector((0, 0, 0.078)), principled('Coffee', '#3A2214', 0.05))


def build_desk(args):
    """Cozy desk by a window in warm morning sun through the blinds."""
    h = args.height
    bounds, figure = import_figure(args.model, h, args.yaw, 0.0)
    y0, y1, z0, z1 = WINDOW
    # Sun comes in from the front-left through the window and lands on the figure.
    through = (Vector((LEFT_X, -0.3, 0.62)) - Vector((0, 0, h * 0.6))).normalized()
    build_room(textured_material('DeskWood', polyhaven_texture(DESK_WOOD, args.cache), 0.6), through)
    build_wall_shelf(args.cache)
    build_desk_props(args.cache)

    # Outside sky through the (off-screen) window, plus a low golden sun.
    set_world_hdri(polyhaven_hdri(DESK_OUTSIDE, args.cache), 1.2, math.radians(200))
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = 16.0
    sun_data.color = (1.0, 0.72, 0.42)
    sun_data.angle = math.radians(0.8)
    sun = bpy.data.objects.new('Sun', sun_data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = through.to_track_quat('Z', 'Y').to_euler()
    # Window portal so the sky light entering the room converges quickly.
    portal = add_area_light('WindowPortal', (LEFT_X + 0.06, (y0 + y1) / 2, (z0 + z1) / 2),
                            (LEFT_X + 2, (y0 + y1) / 2, (z0 + z1) / 2), y1 - y0, 1, size_y=z1 - z0)
    portal.data.cycles.is_portal = True
    # Warm bounce from the room behind the camera.
    add_area_light('RoomBounce', (0.4, -1.4, 0.6), (0, 0, h * 0.5), 1.5, 24, color=(1.0, 0.85, 0.7))

    bpy.context.scene.view_settings.exposure = 0.3
    add_camera(bounds, figure, args, args.angle if args.angle is not None else 10, 7, lens=35,
               fstop=args.fstop or 8, fill=0.8, aim=0.5)


# --------------------------------------------------------------------------
# Render setup
# --------------------------------------------------------------------------

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
    cam = bpy.context.scene.camera
    print(f'[showcase] focus distance {cam.data.dof.focus_distance:.3f} m, f/{cam.data.dof.aperture_fstop}')
    if args.save_blend:
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=args.save_blend, compress=True)
    bpy.ops.render.render(write_still=True)


main()
