"""Render a GLB figure in a showcase scene with Blender (Cycles).

Usage:
  blender -b -P scripts/blender/figure_showcase.py -- \
      --model "models/holo/holo coffee.glb" --yaw -90 --scene studio --out renders/holo_coffee_studio.png

Scenes:
  studio  Black acrylic base on a dark warm seamless backdrop. Low-key product
          lighting: side softbox, two rim strips and a background glow.
  desk    Wooden desk by a sunny window (real interior HDRI), with a laptop,
          books, a plant, stationery and a mug around the figure.

Both scenes use real-world scale (figure ~15 cm), an 85 mm lens and shallow
depth of field. Focus is placed by ray casting onto the figure's face, so the
figure is sharp and the set falls off into bokeh.

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


def add_spot_light(name, location, target, power, size_deg, radius=0.05, blend=0.8, color=(1, 1, 1)):
    data = bpy.data.lights.new(name, 'SPOT')
    data.energy = power
    data.spot_size = math.radians(size_deg)
    data.spot_blend = blend
    data.shadow_soft_size = radius
    data.color = color
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


def brightest_direction(image):
    """Azimuth/elevation (radians, Blender world space) of the brightest area of an equirect HDRI."""
    import numpy as np
    w, h = image.size
    px = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    lum = (px.reshape(h, w, 4)[..., :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))
    # Downsample to find the brightest region rather than a single hot pixel.
    f = 16
    small = lum[:h // f * f, :w // f * f].reshape(h // f, f, w // f, f).mean(axis=(1, 3))
    small[: small.shape[0] // 2 - 1] = 0  # ignore the lower hemisphere (floor bounce)
    row, col = np.unravel_index(np.argmax(small), small.shape)
    u = (col + 0.5) / small.shape[1]
    v = (row + 0.5) / small.shape[0]
    # Blender equirect: u = 0.5 - atan2(dy, -dx) / 2pi, v = 0.5 + elevation / pi (rows stored bottom-up)
    phi = (0.5 - u) * 2 * math.pi
    elevation = (v - 0.5) * math.pi
    direction = Vector((-math.cos(phi), math.sin(phi), 0))
    return math.atan2(direction.y, direction.x), elevation


# --------------------------------------------------------------------------
# Figure and props
# --------------------------------------------------------------------------

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
# Scene: studio
# --------------------------------------------------------------------------

def build_studio(args):
    base_r, base_h = 0.085, 0.012
    base = add_cylinder('AcrylicBase', base_r, base_h, (0, 0, base_h / 2), bevel=0.0025,
                        mat=principled('BlackAcrylic', '#050505', roughness=0.03,
                                       **{'Coat Weight': 1.0, 'Coat Roughness': 0.02}))

    bounds, figure = import_figure(args.model, args.height, args.yaw, base_h)
    lo, hi = bounds
    need = max(abs(lo.x), abs(hi.x), abs(lo.y), abs(hi.y)) * 1.15
    if need > base_r:
        base.scale.x = base.scale.y = need / base_r
    h = args.height

    # Seamless cyclorama, set well back so it melts into a soft gradient.
    cyc_mat = principled('Backdrop', '#4A3B31', 0.85)
    mesh = bpy.data.meshes.new('Cyclorama')
    bm = bmesh.new()
    radius, width, back = 0.5, 6.0, 1.1
    profile = [(y, 0.0) for y in (-3.0, -1.0, 0.0, back)]
    for i in range(1, 16):
        t = i / 16 * math.pi / 2
        profile.append((back + math.sin(t) * radius, radius - math.cos(t) * radius))
    profile += [(back + radius, radius), (back + radius, 2.0), (back + radius, 4.0)]
    rows = [[bm.verts.new((x, y, z)) for (y, z) in profile] for x in (-width / 2, width / 2)]
    for i in range(len(profile) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(mesh)
    bm.free()
    cyc = bpy.data.objects.new('Cyclorama', mesh)
    bpy.context.collection.objects.link(cyc)
    assign(cyc, cyc_mat)
    for poly in cyc.data.polygons:
        poly.use_smooth = True

    face = (0, 0, base_h + h * 0.7)
    body = (0, 0, base_h + h * 0.5)
    # Key: medium softbox high on the left, narrow spread so it shapes the
    # figure instead of flooding the set. No front fill: the right side falls
    # into shadow for depth.
    add_area_light('Key', (-0.45, -0.22, 0.40), face, 0.6, 2.8, color=(1.0, 0.98, 0.95), spread=26)
    # Rim strips behind both sides to separate hair and tail from the backdrop.
    # They are light-linked to the figure only, so they do not spill onto the floor.
    rims = [
        add_area_light('RimL', (-0.30, 0.32, 0.26), body, 0.04, 2.0, color=(1.0, 0.93, 0.86), size_y=0.4, spread=35),
        add_area_light('RimR', (0.32, 0.28, 0.22), body, 0.04, 2.5, color=(1.0, 0.93, 0.86), size_y=0.4, spread=40),
    ]
    link_lights(rims, figure)
    # Faint bounce from the right so shadows are not crushed.
    add_area_light('Bounce', (0.5, -0.35, 0.05), body, 0.5, 0.8, color=(1.0, 0.9, 0.8))
    # Warm glow on the backdrop behind the figure, falling off to dark edges.
    add_spot_light('BackdropGlow', (0.2, 0.5, 0.1), (0.6, back + 0.35, 0.14), 60, 60, blend=1.0,
                   color=(1.0, 0.8, 0.6))
    set_world_color((0.02, 0.015, 0.012), 1.0)

    add_camera(bounds, figure, args, args.angle if args.angle is not None else -20, 7, lens=85,
               fstop=args.fstop or 5.6, fill=0.7)


# --------------------------------------------------------------------------
# Scene: desk
# --------------------------------------------------------------------------

DESK_HDRI = 'photo_studio_loft_hall'
DESK_WOOD = 'oak_veneer_01'
# (asset id, location on the desk, yaw in degrees, scale)
DESK_PROPS = [
    ('classic_laptop', (0.42, 0.55, 0.0), -30, 1.0),
    ('decorative_book_set_01', (-0.40, 0.62, 0.0), 12, 1.0),
    ('potted_plant_04', (0.32, 0.40, 0.0), 0, 0.55),
    ('stationery_supplies', (0.02, 0.50, 0.0), 10, 1.0),
]


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
    bsdf.inputs['Coat Weight'].default_value = 0.25
    bsdf.inputs['Coat Roughness'].default_value = 0.2
    return mat


def build_desk(args):
    h = args.height
    bounds, figure = import_figure(args.model, h, args.yaw, 0.0)

    # Desk top.
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0.35, 0))
    desk = bpy.context.active_object
    desk.name = 'Desk'
    desk.scale = (2.2, 1.5, 1)
    bpy.ops.object.transform_apply(scale=True)
    assign(desk, textured_material('DeskWood', polyhaven_texture(DESK_WOOD, args.cache), 0.6))

    for asset_id, location, yaw, scale in DESK_PROPS:
        root, meshes = import_asset(polyhaven_model(asset_id, args.cache))
        place(root, meshes, location, yaw, scale)

    # Mug (simple, but with a proper rim and coffee).
    ceramic = principled('Ceramic', '#EFE7DA', 0.25, **{'Coat Weight': 0.6})
    mug = add_cylinder('Mug', 0.04, 0.09, (0.17, 0.17, 0.045), mat=ceramic, bevel=0.003)
    bm = bmesh.new()
    bm.from_mesh(mug.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.z > 0.9], context='FACES')
    bm.to_mesh(mug.data)
    bm.free()
    solid = mug.modifiers.new('Solidify', 'SOLIDIFY')
    solid.thickness = 0.004
    mug.modifiers.move(len(mug.modifiers) - 1, 0)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.022, minor_radius=0.0055, location=(0.17 + 0.042, 0.17, 0.048),
                                     rotation=(math.radians(90), 0, 0))
    handle = bpy.context.active_object
    assign(handle, ceramic)
    bpy.ops.object.shade_smooth()
    add_cylinder('Coffee', 0.037, 0.002, (0.17, 0.17, 0.075), mat=principled('Coffee', '#2E1A10', 0.05))

    # Interior HDRI: rotate it so its window sits behind-left of the figure,
    # then add a sun from the same direction for crisp, natural shadows.
    image = set_world_hdri(polyhaven_hdri(DESK_HDRI, args.cache), 1.0, 0.0)
    light_az, light_el = brightest_direction(image)
    want_az = math.radians(165)  # window on the left, slightly behind (camera looks along +Y)
    bpy.context.scene.world.node_tree.nodes['Mapping'].inputs['Rotation'].default_value[2] = light_az - want_az
    sun_el = max(light_el, math.radians(28))
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = 4.0
    sun_data.color = (1.0, 0.86, 0.68)
    sun_data.angle = math.radians(2.5)
    sun = bpy.data.objects.new('Sun', sun_data)
    bpy.context.collection.objects.link(sun)
    to_light = Vector((math.cos(want_az) * math.cos(sun_el), math.sin(want_az) * math.cos(sun_el), math.sin(sun_el)))
    sun.rotation_euler = to_light.to_track_quat('Z', 'Y').to_euler()
    # Soft fill from the camera side, like light bouncing off a white wall.
    add_area_light('WallBounce', (-0.2, -0.8, 0.3), (0, 0, h * 0.6), 0.8, 3, color=(1.0, 0.95, 0.9))

    add_camera(bounds, figure, args, args.angle if args.angle is not None else -16, 13, lens=85,
               fstop=args.fstop or 4.0, fill=0.62)


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
