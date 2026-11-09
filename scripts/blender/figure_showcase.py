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
  cafe    Wooden café counter: croissant and latte beside the figure, espresso
          machine, grinder, jars, mugs and pendant lamps softly blurred behind.
  records Music corner: walnut sideboard with a turntable and plain record
          sleeves; floor lamp and a record shelf behind, warm evening light.
  fireplace
          Winter evening: candle and pine cones on a wooden table, stone
          fireplace glowing behind, sofa and a snowy window.

Focus is placed by ray casting onto the figure's face, so the figure is
always sharp.

The desk and cafe scenes download assets on first run and cache them in
.cache/: Poly Haven (polyhaven.com, CC0) and NVIDIA SimReady
(huggingface.co/datasets/nvidia/simready-assets, CC-BY 4.0).
"""

import argparse
import json
import math
import os
import statistics
import sys
import urllib.parse
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
    p.add_argument('--scene', choices=['studio', 'desk', 'cafe', 'records', 'fireplace'], default='studio')
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
    p.add_argument('--cache', default=os.path.join(REPO_ROOT, '.cache'),
                   help='Download cache for Poly Haven / NVIDIA SimReady assets')
    p.add_argument('--save-blend', default=None, help='Also save the assembled scene to this .blend file')
    return p.parse_args(argv)


# --------------------------------------------------------------------------
# Downloaded assets: Poly Haven (CC0) and NVIDIA SimReady (CC-BY 4.0)
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
    path = os.path.join(cache, 'polyhaven', asset_id, 'files.json')
    _download(f'https://api.polyhaven.com/files/{asset_id}', path)
    with open(path) as f:
        return json.load(f)


def polyhaven_model(asset_id, cache, res='1k'):
    files = _files(asset_id, cache)
    entry = files['gltf'][res]['gltf'] if 'gltf' in files else files['blend'][res]['blend']
    folder = os.path.join(cache, 'polyhaven', asset_id, res)
    for rel, info in entry.get('include', {}).items():
        _download(info['url'], os.path.join(folder, rel))
    return _download(entry['url'], os.path.join(folder, os.path.basename(entry['url'])))


def polyhaven_hdri(asset_id, cache, res='2k'):
    url = _files(asset_id, cache)['hdri'][res]['hdr']['url']
    return _download(url, os.path.join(cache, 'polyhaven', asset_id, os.path.basename(url)))


def polyhaven_texture(asset_id, cache, res='2k'):
    files = _files(asset_id, cache)
    maps = {}
    for key, name in (('Diffuse', 'diff'), ('Rough', 'rough'), ('nor_gl', 'nor')):
        url = files[key][res]['jpg']['url']
        maps[name] = _download(url, os.path.join(cache, 'polyhaven', asset_id, os.path.basename(url)))
    return maps


SIMREADY = 'https://huggingface.co/datasets/nvidia/simready-assets'


def simready_asset(name, cache):
    """Download one NVIDIA SimReady asset (OpenUSD) and return its root .usd file."""
    folder = os.path.join(cache, 'simready', name)
    listing = _download(f'https://huggingface.co/api/datasets/nvidia/simready-assets/tree/main/{name}?recursive=true',
                        os.path.join(folder, 'tree.json'))
    with open(listing) as f:
        entries = json.load(f)
    root = None
    for entry in entries:
        path = entry['path']
        if entry['type'] != 'file' or '/simready_usd/' not in path:
            continue
        if '/.thumbs/' in path or '/source_assets/' in path:
            continue
        rel = path.split('/simready_usd/', 1)[1]
        local = _download(f'{SIMREADY}/resolve/main/{urllib.parse.quote(path)}', os.path.join(folder, rel))
        if '/' not in rel and rel.endswith('.usd'):
            root = local
    return root


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
    elif path.endswith(('.usd', '.usda', '.usdc')):
        bpy.ops.wm.usd_import(filepath=path, import_guide=False, import_proxy=False, support_scene_instancing=False)
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
# Window wall: off-screen on the left, turned so the blind stripes run diagonally.
WINDOW_WALL_AT = (-0.8, -0.2)
WINDOW_WALL_ANGLE = math.radians(35)
WINDOW = (-0.6, 0.65, 0.05, 1.2)     # along-wall y0, y1 and z0, z1 of the opening


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
    """A simple room: back wall, an angled window wall on the left, floor and ceiling.

    The window wall is outside the frame and turned at an angle to the
    camera, so the sun comes in from the front-left and the blind stripes fall
    diagonally across the desk and the figure. Everything the camera sees is
    real geometry lit by the same sun, so figure and set always match.
    """
    floor_z, ceil_z, left_x, right_x, front_y = -0.75, 1.9, -2.2, 2.4, -2.6
    t = 0.08
    wall = principled('Plaster', '#EADFD0', 0.92)
    width = right_x - left_x
    cx, cz, h_room = (left_x + right_x) / 2, (ceil_z + floor_z) / 2, ceil_z - floor_z
    add_box('BackWall', (width, t, h_room), (cx, WALL_Y + t / 2, cz), wall)
    add_box('SideR', (t, WALL_Y - front_y, h_room), (right_x, (WALL_Y + front_y) / 2, cz), wall)
    add_box('Front', (width, t, h_room), (cx, front_y, cz), wall)
    add_box('Ceiling', (width, WALL_Y - front_y, t), (cx, (WALL_Y + front_y) / 2, ceil_z), wall)
    add_box('Floor', (width, WALL_Y - front_y, t), (cx, (WALL_Y + front_y) / 2, floor_z),
            principled('Floor', '#8A6A50', 0.6))

    # Window wall, built in its own frame: local x = normal into the room,
    # local y = along the wall. It is long enough to close the room.
    angle = WINDOW_WALL_ANGLE
    origin = Vector(WINDOW_WALL_AT)
    def world(lx, ly, z):
        return Vector((origin.x + lx * math.cos(angle) - ly * math.sin(angle),
                       origin.y + lx * math.sin(angle) + ly * math.cos(angle), z))
    def wall_box(name, size, lx, ly, z, mat, tilt=0.0):
        return add_box(name, size, world(lx, ly, z), mat, rotation=(0, tilt, angle))

    y0, y1, z0, z1 = WINDOW
    span = 4.0
    wx = -t / 2
    wall_box('WinWallFront', (t, y0 + span, h_room), wx, (y0 - span) / 2, cz, wall)
    wall_box('WinWallBack', (t, span - y1, h_room), wx, (y1 + span) / 2, cz, wall)
    wall_box('WinWallBelow', (t, y1 - y0, z0 - floor_z), wx, (y0 + y1) / 2, (z0 + floor_z) / 2, wall)
    wall_box('WinWallAbove', (t, y1 - y0, ceil_z - z1), wx, (y0 + y1) / 2, (z1 + ceil_z) / 2, wall)

    frame = principled('Frame', '#F2ECE2', 0.5)
    fw = 0.035
    wall_box('FrameF', (t + 0.01, fw, z1 - z0), wx, y0 + fw / 2, (z0 + z1) / 2, frame)
    wall_box('FrameB', (t + 0.01, fw, z1 - z0), wx, y1 - fw / 2, (z0 + z1) / 2, frame)
    wall_box('FrameT', (t + 0.01, y1 - y0, fw), wx, (y0 + y1) / 2, z1 - fw / 2, frame)

    # Horizontal blinds: real slats, tilted so they block about half of the
    # sun for crisp light/shadow stripes.
    slat_mat = principled('Blinds', '#D9BE98', 0.55)
    pitch, depth = 0.026, 0.03
    normal = Vector((math.cos(angle), math.sin(angle), 0))
    slope = math.atan2(sun_dir.z, abs(sun_dir.dot(normal)))
    tilt = slope + math.asin(min(1.0, 0.5 * pitch / depth))
    n = int((z1 - z0 - 0.04) / pitch)
    for i in range(n):
        wall_box(f'Slat{i:02d}', (depth, y1 - y0 - 2 * fw, 0.0015), 0.03, (y0 + y1) / 2,
                 z1 - 0.03 - i * pitch, slat_mat, tilt=tilt)
    wall_box('BlindRail', (0.045, y1 - y0, 0.03), 0.03, (y0 + y1) / 2, z1 - 0.005, slat_mat)

    # Portal over the window so the sky light entering the room converges quickly.
    centre = world(0.06, (y0 + y1) / 2, (z0 + z1) / 2)
    portal = add_area_light('WindowPortal', centre, centre + normal, y1 - y0, 1, size_y=z1 - z0)
    portal.data.cycles.is_portal = True

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

    # Desk top against the back wall.
    add_box('Desk', (3.3, WALL_Y + 0.7, 0.03), (-0.35, (WALL_Y - 0.7) / 2, -0.015), wood, bevel=0.003)


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
    kb = Vector((-0.4, 0.08, 0.0))
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
    # Sun comes in from the front-left through the window and lands on the figure.
    through = (Vector((*WINDOW_WALL_AT, 0.62)) - Vector((0, 0, h * 0.6))).normalized()
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
    # Warm bounce from the room behind the camera.
    add_area_light('RoomBounce', (0.4, -1.4, 0.6), (0, 0, h * 0.5), 1.5, 24, color=(1.0, 0.85, 0.7))

    bpy.context.scene.view_settings.exposure = 0.3
    add_camera(bounds, figure, args, args.angle if args.angle is not None else 10, 7, lens=35,
               fstop=args.fstop or 8, fill=0.8, aim=0.5)


# --------------------------------------------------------------------------
# Scene: cafe
# --------------------------------------------------------------------------

CAFE_WOOD = 'wood_table_001'


def stainless(name='Stainless'):
    return principled(name, '#A8AAAC', 0.3, Metallic=1.0)


def add_espresso_machine(at):
    """Simplified two-group espresso machine (reads as one once blurred)."""
    at = Vector(at)
    steel = stainless()
    black = principled('BlackPlastic', '#161616', 0.4)
    add_box('EspressoBody', (0.66, 0.46, 0.36), at + Vector((0, 0, 0.18)), steel, bevel=0.01)
    add_box('EspressoPanel', (0.6, 0.01, 0.12), at + Vector((0, -0.232, 0.29)), principled('Panel', '#2B2B2B', 0.3))
    add_box('CupTray', (0.66, 0.46, 0.015), at + Vector((0, 0, 0.37)), steel, bevel=0.003)
    add_box('DripTray', (0.58, 0.14, 0.03), at + Vector((0, -0.29, 0.015)), steel, bevel=0.003)
    for i, x in enumerate((-0.17, 0.17)):
        add_cylinder(f'GroupHead{i}', 0.045, 0.06, at + Vector((x, -0.27, 0.17)), steel, bevel=0.004)
        add_cylinder(f'Portafilter{i}', 0.038, 0.03, at + Vector((x, -0.27, 0.125)), steel, bevel=0.003)
        add_box(f'PortafilterHandle{i}', (0.025, 0.13, 0.025), at + Vector((x, -0.36, 0.12)), black, bevel=0.006,
                rotation=(math.radians(-8), 0, 0))
        add_cylinder(f'Gauge{i}', 0.016, 0.01, at + Vector((x * 0.5, -0.24, 0.3)),
                     principled(f'Gauge{i}', '#D8D2C6', 0.2), vertices=48).rotation_euler = (math.radians(90), 0, 0)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.006, depth=0.22, location=at + Vector((0.31, -0.28, 0.13)),
                                        rotation=(math.radians(15), 0, 0))
    assign(bpy.context.active_object, steel)


def add_grinder(at):
    at = Vector(at)
    black = principled('GrinderBody', '#1E1E1E', 0.35)
    add_box('GrinderBody', (0.14, 0.2, 0.26), at + Vector((0, 0, 0.13)), black, bevel=0.01)
    bpy.ops.mesh.primitive_cone_add(radius1=0.04, radius2=0.075, depth=0.16, location=at + Vector((0, 0.01, 0.34)),
                                    vertices=48)
    hopper = bpy.context.active_object
    assign(hopper, principled('Hopper', '#D8D2C8', 0.05, **{'Transmission Weight': 1.0}))
    bpy.ops.object.shade_smooth()
    add_cylinder('Beans', 0.05, 0.07, at + Vector((0, 0.01, 0.3)), principled('Beans', '#3B2416', 0.6))


def add_pendant(name, at, cord=0.6):
    at = Vector(at)
    copper = principled(f'{name}Shade', '#B36A3E', 0.3, Metallic=1.0)
    bpy.ops.mesh.primitive_cone_add(radius1=0.11, radius2=0.025, depth=0.12, location=at + Vector((0, 0, 0.06)),
                                    vertices=64, end_fill_type='NOTHING')
    shade = bpy.context.active_object
    shade.name = name
    solid = shade.modifiers.new('Solidify', 'SOLIDIFY')
    solid.thickness = 0.003
    assign(shade, copper)
    bpy.ops.object.shade_smooth()
    add_cylinder(f'{name}Cord', 0.003, cord, at + Vector((0, 0, 0.12 + cord / 2)), principled('Cord', '#111111', 0.5))
    glow = new_material(f'{name}Bulb')
    nt = glow.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = hex_rgba('#FFC27A')
    em.inputs['Strength'].default_value = 25
    nt.links.new(em.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.03, location=at + Vector((0, 0, 0.02)))
    assign(bpy.context.active_object, glow)
    bpy.ops.object.shade_smooth()
    data = bpy.data.lights.new(f'{name}Light', 'POINT')
    data.energy = 6
    data.color = (1.0, 0.72, 0.45)
    data.shadow_soft_size = 0.03
    light = bpy.data.objects.new(f'{name}Light', data)
    bpy.context.collection.objects.link(light)
    light.location = at + Vector((0, 0, 0.0))


def add_simready(name, cache, location, yaw=0.0, scale=1.0):
    root, meshes = import_asset(simready_asset(name, cache))
    return place(root, meshes, location, yaw, scale)


def build_cafe(args):
    """Café counter: latte and croissant beside the figure, espresso bar softly blurred behind."""
    h = args.height
    cache = args.cache
    bounds, figure = import_figure(args.model, h, args.yaw, 0.0)
    wood = textured_material('CounterWood', polyhaven_texture(CAFE_WOOD, cache), 0.8)

    # Front counter (figure stands on it) and the back bar behind the aisle.
    add_box('Counter', (3.2, 0.8, 0.05), (0, 0.15, -0.025), wood, bevel=0.004)
    back_y, back_top = 1.25, -0.02
    add_box('BackBarTop', (3.2, 0.52, 0.04), (0, back_y, back_top - 0.02), wood, bevel=0.003)
    add_box('BackBarCabinet', (3.2, 0.5, 0.9), (0, back_y, back_top - 0.49), principled('Cabinet', '#4A3020', 0.55))
    add_box('BackWall', (4.0, 0.06, 2.4), (0, 1.55, 0.6), principled('CafeWall', '#CDB497', 0.9))
    add_box('Floor', (4.0, 4.0, 0.04), (0, 0.5, -1.0), principled('CafeFloor', '#5B4636', 0.6))
    add_box('Ceiling', (4.0, 4.0, 0.04), (0, 0.5, 1.5), principled('CafeCeiling', '#EDE4D6', 0.9))

    # Back bar: espresso machine with cups on top, grinder, jars of beans.
    add_espresso_machine((0.62, back_y, back_top))
    for i, x in enumerate((0.44, 0.56, 0.68, 0.8)):
        add_simready('dishware_cup_tea_a01', cache, (x, back_y + 0.05, back_top + 0.38), 90 + i * 25, 0.75)
    add_grinder((0.12, back_y, back_top))
    for i, x in enumerate((-0.32, -0.45, -0.58)):
        add_simready('container_jar_glass_gold_a01', cache, (x, back_y + 0.06, back_top), i * 40, 0.9 - 0.1 * i)

    # Wall shelf with mugs, and a frameless-looking chalkboard (no text).
    shelf_wood = principled('ShelfWood', '#8A5E3C', 0.5)
    add_box('WallShelf', (0.9, 0.16, 0.025), (-0.45, 1.46, 0.36), shelf_wood, bevel=0.002)
    for i, (name, x) in enumerate((('kitchenware_mug_c01', -0.75), ('dishware_mug_coffee_a01', -0.58),
                                    ('kitchenware_mug_a01', -0.4), ('dishware_cup_tea_a01', -0.22))):
        add_simready(name, cache, (x, 1.46, 0.3725), 200 + i * 30, 0.9)
    add_box('Chalkboard', (0.62, 0.02, 0.46), (0.42, 1.515, 0.62), principled('Chalk', '#22282A', 0.85))
    add_box('ChalkFrame', (0.66, 0.015, 0.5), (0.42, 1.522, 0.62), shelf_wood)
    root, meshes = import_asset(polyhaven_model('potted_plant_02', cache))
    place(root, meshes, (-0.95, back_y + 0.05, back_top), 0, height=0.42)

    # Pendant lamps over the bar.
    add_pendant('PendantL', (-0.42, 0.95, 0.36))
    add_pendant('PendantR', (0.5, 1.05, 0.4))

    # Front props: croissant on a plate and a latte on a saucer, left of the figure.
    ceramic = principled('PlateCeramic', '#F4F0E8', 0.2, **{'Coat Weight': 0.5})
    plate_at = Vector((-0.21, 0.08, 0.0))
    add_cylinder('Plate', 0.085, 0.012, plate_at + Vector((0, 0, 0.006)), ceramic, bevel=0.004)
    add_simready('food_prepared_croissant_a01', cache, plate_at + Vector((0, 0, 0.012)), 100, 0.85)
    cup_at = Vector((-0.35, 0.26, 0.0))
    add_cylinder('Saucer', 0.065, 0.01, cup_at + Vector((0, 0, 0.005)), ceramic, bevel=0.004)
    lo, hi = add_simready('dishware_cup_tea_a01', cache, cup_at + Vector((0, 0, 0.01)), 200, 0.8)
    add_cylinder('Latte', 0.034, 0.002, Vector((cup_at.x, cup_at.y, hi.z - 0.012)),
                 principled('LatteFoam', '#D9B48A', 0.35))

    # Light: window off-screen on the left, warm fill from the room.
    add_area_light('Window', (-1.3, 0.1, 0.55), (0, 0.1, h * 0.6), 1.2, 70, color=(1.0, 0.93, 0.84), size_y=1.0)
    add_area_light('RoomFill', (0.7, -1.2, 0.45), (0, 0, h * 0.5), 1.2, 14, color=(1.0, 0.88, 0.75))
    set_world_color((0.3, 0.24, 0.19), 0.6)

    bpy.context.scene.view_settings.exposure = 0.2
    add_camera(bounds, figure, args, args.angle if args.angle is not None else 10, 7, lens=35,
               fstop=args.fstop or 8, fill=0.8, aim=0.5)


# --------------------------------------------------------------------------
# Shared small helpers for the living-room scenes
# --------------------------------------------------------------------------

def emission_material(name, color, strength):
    mat = new_material(name)
    nt = mat.node_tree
    nt.nodes.remove(nt.nodes['Principled BSDF'])
    em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = hex_rgba(color) if isinstance(color, str) else color
    em.inputs['Strength'].default_value = strength
    nt.links.new(em.outputs[0], nt.nodes['Material Output'].inputs['Surface'])
    return mat


def add_point_light(name, location, power, color, radius=0.02):
    data = bpy.data.lights.new(name, 'POINT')
    data.energy = power
    data.color = color
    data.shadow_soft_size = radius
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def add_blob(name, location, scale, mat, subdiv=2):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=subdiv, radius=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.shade_smooth()
    assign(obj, mat)
    return obj


def stripe_material(name, colors, scale=8.0):
    """Woven plaid / stripes for blankets and sleeves."""
    mat = principled(name, colors[0], 0.85, **{'Sheen Weight': 0.4})
    nt = mat.node_tree
    coord = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(coord.outputs['Object'], sep.inputs[0])
    waves = []
    for axis in ('X', 'Y'):
        wave = nt.nodes.new('ShaderNodeTexWave')
        wave.wave_profile = 'SAW'
        wave.inputs['Scale'].default_value = scale
        mul = nt.nodes.new('ShaderNodeMath')
        mul.operation = 'MULTIPLY'
        mul.inputs[1].default_value = 1.0
        nt.links.new(sep.outputs[axis], wave.inputs['Vector'])
        waves.append(wave)
    mix = nt.nodes.new('ShaderNodeMix')
    mix.data_type = 'FLOAT'
    mix.inputs['Factor'].default_value = 0.5
    nt.links.new(waves[0].outputs['Fac'], mix.inputs['A'])
    nt.links.new(waves[1].outputs['Fac'], mix.inputs['B'])
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.interpolation = 'CONSTANT'
    ramp.color_ramp.elements[0].color = hex_rgba(colors[0])
    ramp.color_ramp.elements[1].position = 0.55
    ramp.color_ramp.elements[1].color = hex_rgba(colors[1])
    if len(colors) > 2:
        el = ramp.color_ramp.elements.new(0.8)
        el.color = hex_rgba(colors[2])
    nt.links.new(mix.outputs['Result'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])
    return mat


def add_pine_cone(name, location, yaw_deg, length=0.07, radius=0.024):
    """Pine cone from spiralling scales, lying on its side."""
    root = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(root)
    scale_mat = principled(f'{name}Scale', '#6E4428', 0.7)
    tip_mat = principled(f'{name}Tip', '#A27247', 0.7)
    count = 140
    for i in range(count):
        t = i / (count - 1)
        r = radius * (math.sin(math.pi * min(1.0, 0.15 + t * 0.95)) ** 0.7)
        a = i * math.radians(137.5)
        z = t * length
        size = 0.4 + 0.6 * r / radius
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=1,
                                             location=(math.cos(a) * r, math.sin(a) * r, z))
        sc = bpy.context.active_object
        sc.scale = (0.008 * size, 0.0065 * size, 0.0016 * size)
        sc.rotation_euler = (0, math.radians(-40), a)
        assign(sc, scale_mat if i % 3 else tip_mat)
        bpy.ops.object.shade_smooth()
        sc.parent = root
    add_cylinder(f'{name}Core', radius * 0.35, length, (0, 0, length / 2), scale_mat).parent = root
    root.rotation_euler = (math.radians(90), 0, math.radians(yaw_deg))
    root.location = Vector(location) + Vector((0, 0, radius * 0.85))
    return root


# --------------------------------------------------------------------------
# Scene: records
# --------------------------------------------------------------------------

def add_turntable(at, yaw_deg):
    at = Vector(at)
    walnut = principled('Plinth', '#5A3521', 0.35, **{'Coat Weight': 0.6, 'Coat Roughness': 0.1})
    alu = principled('Aluminium', '#C0C2C4', 0.25, Metallic=1.0)
    root = bpy.data.objects.new('Turntable', None)
    bpy.context.collection.objects.link(root)
    parts = [
        add_box('Plinth', (0.44, 0.35, 0.08), (0, 0, 0.045), walnut, bevel=0.006),
        add_cylinder('Platter', 0.15, 0.012, (-0.04, 0, 0.091), alu, bevel=0.002),
    ]
    vinyl = principled('Vinyl', '#0B0B0C', 0.18, **{'Coat Weight': 1.0, 'Coat Roughness': 0.05})
    nt = vinyl.node_tree
    wave = nt.nodes.new('ShaderNodeTexWave')
    wave.wave_type = 'RINGS'
    wave.inputs['Scale'].default_value = 120
    bump = nt.nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.08
    nt.links.new(wave.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], nt.nodes['Principled BSDF'].inputs['Coat Normal'])
    parts.append(add_cylinder('Record', 0.15, 0.002, (-0.04, 0, 0.098), vinyl))
    parts.append(add_cylinder('Label', 0.048, 0.0025, (-0.04, 0, 0.099), principled('Label', '#B5532F', 0.6)))
    parts.append(add_cylinder('Spindle', 0.004, 0.02, (-0.04, 0, 0.105), alu))
    parts.append(add_cylinder('ArmBase', 0.022, 0.03, (0.16, 0.11, 0.1), alu, bevel=0.002))
    bpy.ops.mesh.primitive_cylinder_add(radius=0.004, depth=0.23, location=(0.12, 0.0, 0.118),
                                        rotation=(math.radians(90), 0, math.radians(-20)))
    arm = bpy.context.active_object
    assign(arm, alu)
    parts.append(arm)
    parts.append(add_box('Headshell', (0.02, 0.035, 0.008), (0.08, -0.105, 0.112), principled('Headshell', '#1B1B1B', 0.4),
                         rotation=(0, 0, math.radians(-20))))
    for x in (-0.19, 0.19):
        for y in (-0.15, 0.15):
            parts.append(add_cylinder('Foot', 0.02, 0.01, (x, y, 0.005), principled('Foot', '#222222', 0.6)))
    for p in parts:
        p.parent = root
    root.rotation_euler = (0, 0, math.radians(yaw_deg))
    root.location = at


def add_record_shelf(origin, cols=3, rows=2, cell=0.36):
    """Cube shelf full of record spines (plain colours, no text)."""
    origin = Vector(origin)
    wood = principled('RecordShelf', '#4E3324', 0.5)
    t, depth = 0.025, 0.34
    width, height = cols * cell + t, rows * cell + t
    for r in range(rows + 1):
        add_box(f'ShelfH{r}', (width, depth, t), origin + Vector((width / 2, 0, r * cell + t / 2)), wood)
    for c in range(cols + 1):
        add_box(f'ShelfV{c}', (t, depth, height), origin + Vector((c * cell + t / 2, 0, height / 2)), wood)
    add_box('ShelfBack', (width, 0.01, height), origin + Vector((width / 2, depth / 2, height / 2)), wood)
    palette = ['#2F2A26', '#8A3B2E', '#D9CDB8', '#3E5161', '#B98A4E', '#5C6B4A', '#1E1E1E', '#C9B79A', '#6B4B6E']
    k = 0
    for r in range(rows):
        for c in range(cols):
            x = origin.x + c * cell + t + 0.006
            end = origin.x + (c + 1) * cell - 0.02
            while x < end:
                th = 0.004 + 0.003 * ((k * 7) % 3)
                lean = 0.0 if x < end - 0.05 else math.radians(6)
                add_box(f'LP{k}', (th, 0.31, 0.31), (x + th / 2, origin.y - 0.005, origin.z + r * cell + t + 0.155),
                        principled(f'LP{k}', palette[(k * 5) % len(palette)], 0.55), rotation=(0, lean, 0))
                x += th + 0.0008
                k += 1


def add_floor_lamp(at, top=0.62):
    at = Vector(at)
    wood = principled('LampWood', '#8B5E3C', 0.5)
    for i in range(3):
        a = math.radians(90 + i * 120)
        foot = at + Vector((math.cos(a) * 0.22, math.sin(a) * 0.22, at.z))
        head = Vector((at.x, at.y, top - 0.12))
        mid = (foot + head) / 2
        d = head - foot
        bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=d.length, location=mid)
        leg = bpy.context.active_object
        leg.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
        assign(leg, wood)
    shade = principled('LampShade', '#F3E3C6', 0.9, **{'Transmission Weight': 0.0, 'Subsurface Weight': 0.6})
    bpy.ops.mesh.primitive_cone_add(radius1=0.24, radius2=0.19, depth=0.28, location=(at.x, at.y, top),
                                    vertices=64, end_fill_type='NOTHING')
    cone = bpy.context.active_object
    solid = cone.modifiers.new('Solidify', 'SOLIDIFY')
    solid.thickness = 0.004
    assign(cone, shade)
    bpy.ops.object.shade_smooth()
    add_point_light('LampBulb', (at.x, at.y, top - 0.02), 40, (1.0, 0.72, 0.45), radius=0.05)


def build_records(args):
    """Music corner: figure on a walnut sideboard between a turntable and record sleeves."""
    h = args.height
    cache = args.cache
    bounds, figure = import_figure(args.model, h, args.yaw, 0.0)
    floor_z = -0.75
    top = textured_material('SideboardWood', polyhaven_texture('walnut_veneer', cache), 0.7)
    add_box('Sideboard', (2.0, 0.5, 0.04), (0, 0.05, -0.02), top, bevel=0.003)
    add_box('SideboardBody', (1.96, 0.46, 0.7), (0, 0.05, -0.39), principled('SideboardBody', '#4A2E1E', 0.5))
    add_box('BackWall', (5.0, 0.06, 3.0), (0, 1.7, 0.6), principled('LoungeWall', '#D6C2A6', 0.9))
    add_box('Floor', (5.0, 5.0, 0.04), (0, 0.5, floor_z), principled('LoungeFloor', '#4D3627', 0.55))

    add_turntable((-0.42, 0.3, 0.0), 28)
    sleeve_colors = ['#E7DCC8', '#C9A982', '#F1ECE3', '#B28A64', '#DCCFB9']
    for i, color in enumerate(sleeve_colors):
        add_box(f'Sleeve{i}', (0.31, 0.31, 0.004), (0.26 + 0.006 * i, 0.16 - 0.004 * i, 0.002 + i * 0.0042),
                principled(f'Sleeve{i}', color, 0.75), rotation=(0, 0, math.radians(-8 + 4 * i)))
    root, meshes = import_asset(polyhaven_model('potted_plant_02', cache))
    place(root, meshes, (-0.8, 0.22, 0.0), 20, height=0.45)

    add_record_shelf((0.18, 1.45, floor_z + 0.55))
    add_floor_lamp(Vector((-0.6, 1.35, floor_z)), top=0.55)

    # Warm evening light: the floor lamp, a warm key from the front-left, dim room fill.
    add_area_light('LampKey', (-0.7, -0.5, 0.45), (0, 0, h * 0.6), 0.8, 22, color=(1.0, 0.8, 0.6))
    add_area_light('RoomFill', (0.7, -1.0, 0.3), (0, 0, h * 0.5), 1.2, 6, color=(1.0, 0.9, 0.8))
    set_world_color((0.18, 0.13, 0.1), 0.5)

    add_camera(bounds, figure, args, args.angle if args.angle is not None else 10, 7, lens=35,
               fstop=args.fstop or 8, fill=0.8, aim=0.5)


# --------------------------------------------------------------------------
# Scene: fireplace
# --------------------------------------------------------------------------

def add_fireplace(at, floor_z):
    """Stone fireplace with a raised hearth, logs and a glowing fire."""
    at = Vector(at)
    stone = principled('Stone', '#8C8178', 0.85)
    noise = stone.node_tree.nodes.new('ShaderNodeTexVoronoi')
    noise.inputs['Scale'].default_value = 9.0
    ramp = stone.node_tree.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = hex_rgba('#6E655E')
    ramp.color_ramp.elements[1].color = hex_rgba('#A39789')
    stone.node_tree.links.new(noise.outputs['Distance'], ramp.inputs['Fac'])
    stone.node_tree.links.new(ramp.outputs['Color'], stone.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    w, d = 1.3, 0.4
    hearth_top = floor_z + 0.25
    open_w, open_top = 0.7, hearth_top + 0.55
    add_box('Hearth', (w + 0.2, d + 0.25, 0.25), at + Vector((0, -0.12, floor_z + 0.125)), stone)
    add_box('FireL', ((w - open_w) / 2, d, 1.6), at + Vector((-(w + open_w) / 4, 0, hearth_top + 0.8)), stone)
    add_box('FireR', ((w - open_w) / 2, d, 1.6), at + Vector(((w + open_w) / 4, 0, hearth_top + 0.8)), stone)
    add_box('FireTop', (open_w, d, 1.6 - 0.55), at + Vector((0, 0, open_top + (1.6 - 0.55) / 2)), stone)
    add_box('FireBack', (open_w, 0.05, 0.55), at + Vector((0, d / 2, hearth_top + 0.275)), principled('Soot', '#1A1512', 0.9))
    add_box('Mantel', (w + 0.15, d + 0.12, 0.08), at + Vector((0, -0.04, open_top + 0.14)), principled('MantelWood', '#5C3B26', 0.5))
    bark = principled('Bark', '#3D2A1E', 0.9)
    for i, (x, rot) in enumerate(((-0.1, 15), (0.1, -10), (0.0, 80))):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.045, depth=0.42, location=at + Vector((x, 0.02, hearth_top + 0.05 + 0.05 * (i == 2))),
                                            rotation=(0, math.radians(90), math.radians(rot)))
        assign(bpy.context.active_object, bark)
    flame = emission_material('Flame', (1.0, 0.32, 0.06, 1.0), 4)
    core = emission_material('FlameCore', (1.0, 0.6, 0.2, 1.0), 7)
    for i, (x, hgt) in enumerate(((-0.15, 0.16), (-0.05, 0.24), (0.06, 0.2), (0.16, 0.14))):
        add_blob(f'Flame{i}', at + Vector((x, 0.02, hearth_top + 0.1 + hgt / 2)), (0.045, 0.03, hgt / 2), flame)
        add_blob(f'FlameCore{i}', at + Vector((x, 0.0, hearth_top + 0.09 + hgt / 4)), (0.025, 0.02, hgt / 4), core)
    add_point_light('FireLight', at + Vector((0, 0.05, hearth_top + 0.15)), 30, (1.0, 0.5, 0.18), radius=0.12)


def build_fireplace(args):
    """Winter evening: figure on a wooden table, candle and pine cones, fire glowing behind."""
    h = args.height
    cache = args.cache
    bounds, figure = import_figure(args.model, h, args.yaw, 0.0)
    floor_z = -0.45
    wood = textured_material('TableWood', polyhaven_texture('wood_table_001', cache), 0.8)
    add_box('Table', (1.6, 0.8, 0.05), (0, 0.15, -0.025), wood, bevel=0.005)
    add_box('BackWall', (5.0, 0.06, 3.0), (0, 1.9, 1.0), principled('CabinWall', '#B89B7E', 0.9))
    add_box('Floor', (5.0, 5.0, 0.04), (0, 0.5, floor_z), principled('CabinFloor', '#5A3E2B', 0.6))
    add_box('Rug', (1.6, 1.2, 0.01), (0.2, 1.0, floor_z + 0.025), stripe_material('Rug', ['#8E2F28', '#E6D8C2', '#3D2A22'], 4))

    add_fireplace((-0.8, 1.65, 0.0), floor_z)
    # Garland lights on the mantel.
    bulb = emission_material('FairyBulb', '#FFC57A', 30)
    for i in range(9):
        add_blob(f'Fairy{i}', (-1.4 + i * 0.15, 1.55, floor_z + 0.25 + 0.55 + 0.2), (0.008, 0.008, 0.008), bulb, 1)

    # Sofa with a plaid throw on the right.
    root, meshes = import_asset(polyhaven_model('sofa_02', cache))
    place(root, meshes, (0.6, 1.55, floor_z), -110)
    add_box('Throw', (0.5, 0.6, 0.03), (0.35, 1.45, floor_z + 0.5), stripe_material('Plaid', ['#7A2420', '#2E3B2C', '#D9C9A8'], 10),
            rotation=(math.radians(10), math.radians(-25), 0))
    # Snowy window, far right.
    add_box('WindowFrame', (0.8, 0.05, 0.9), (0.45, 1.86, floor_z + 0.95), principled('WinFrame', '#4A3022', 0.5))
    add_box('WindowView', (0.7, 0.02, 0.8), (0.45, 1.84, floor_z + 0.95), emission_material('SnowView', '#7F93AA', 0.5))

    # Props: pillar candle with a flame, two pine cones.
    lo, hi = place(*import_asset(simready_asset('decor_candle_a01', cache)), (-0.2, 0.22, 0.0), 0, 0.55)
    add_blob('CandleFlame', ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z + 0.012), (0.005, 0.005, 0.013),
             emission_material('CandleFlame', '#FFB25C', 40))
    add_point_light('CandleLight', ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z + 0.02), 1.2, (1.0, 0.62, 0.3), radius=0.005)
    add_pine_cone('PineCone1', (-0.12, 0.08, 0.0), 35, length=0.055, radius=0.019)
    add_pine_cone('PineCone2', (0.13, 0.13, 0.0), -60, length=0.05, radius=0.017)

    # Warm lamp key from the front-left, fire glow from behind-left, cool hint from the window.
    add_area_light('LampKey', (-0.7, -0.6, 0.5), (0, 0, h * 0.6), 0.8, 18, color=(1.0, 0.8, 0.6))
    add_area_light('RoomFill', (0.7, -1.0, 0.3), (0, 0, h * 0.5), 1.2, 5, color=(1.0, 0.9, 0.8))
    set_world_color((0.15, 0.11, 0.09), 0.5)

    bpy.context.scene.view_settings.exposure = 0.35
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
    {'studio': build_studio, 'desk': build_desk, 'cafe': build_cafe,
     'records': build_records, 'fireplace': build_fireplace}[args.scene](args)
    configure_render(args)
    cam = bpy.context.scene.camera
    print(f'[showcase] focus distance {cam.data.dof.focus_distance:.3f} m, f/{cam.data.dof.aperture_fstop}')
    if args.save_blend:
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=args.save_blend, compress=True)
    bpy.ops.render.render(write_still=True)


main()
