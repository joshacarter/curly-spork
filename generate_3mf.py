#!/usr/bin/env python3
"""
Prompt-Driven AMS Multi-Color 3MF Generator for Bambu Lab A1

A scene-based 3MF generator that composes mesh primitives into
multi-color printable models. Designed to be driven by natural
language prompts — each scene is a Python function that assembles
primitives from mesh.py.

Usage:
    python3 generate_3mf.py                          # list scenes
    python3 generate_3mf.py gnome_bar_scene          # generate a scene
    python3 generate_3mf.py gnome_bar_scene --split   # one 3mf per piece
"""

import json
import math
import os
import sys
import zipfile
from io import BytesIO
from typing import List, Optional, Tuple

from mesh import (
    Mesh, merge_all, box, cylinder, cone, truncated_cone,
    sphere, torus, hemisphere, rounded_box,
)

# Bambu Lab A1 build volume (mm)
BUILD_X = 256
BUILD_Y = 256
BUILD_Z = 256

# AMS Lite palette — 4 slots
AMS_PALETTE = [
    ("CC3333", "Red"),
    ("3366CC", "Blue"),
    ("33AA33", "Green"),
    ("FFCC00", "Yellow"),
]


def _split_mesh_by_color(mesh: Mesh) -> dict:
    """Split a mesh into separate sub-meshes, one per AMS color.

    Returns { color_index: Mesh } with re-indexed vertices (only the
    vertices actually used by that color's triangles).
    """
    color_tris = {}
    for v1, v2, v3, c in mesh.triangles:
        color_tris.setdefault(c, []).append((v1, v2, v3))

    result = {}
    for color, tris in sorted(color_tris.items()):
        # Collect unique vertex indices used by this color
        used_verts = sorted(set(v for tri in tris for v in tri))
        old_to_new = {old: new for new, old in enumerate(used_verts)}
        new_verts = [mesh.vertices[i] for i in used_verts]
        new_tris = [(old_to_new[a], old_to_new[b], old_to_new[c], color)
                    for a, b, c in tris]
        result[color] = Mesh(new_verts, new_tris)
    return result


def _mesh_to_xml(mesh: Mesh) -> str:
    """Render a mesh's vertices and triangles as 3MF XML (no color attrs)."""
    verts = "\n".join(
        f'          <vertex x="{v[0]:.4f}" y="{v[1]:.4f}" z="{v[2]:.4f}" />'
        for v in mesh.vertices
    )
    tris = "\n".join(
        f'          <triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}" />'
        for t in mesh.triangles
    )
    return f"""        <vertices>
{verts}
        </vertices>
        <triangles>
{tris}
        </triangles>"""


def _bambu_3mf_package(model_xml: str, model_settings: str,
                       project_settings: str, filename: str, palette):
    """Write the ZIP-based 3MF with Bambu metadata."""
    content_types = """\
<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml" />
  <Default Extension="config" ContentType="text/xml" />
</Types>
"""
    rels = """\
<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
                Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" />
</Relationships>
"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model_xml)
        zf.writestr("Metadata/model_settings.config", model_settings)
        zf.writestr("Metadata/project_settings.config", project_settings)

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "wb") as f:
        f.write(buf.getvalue())
    return filepath


def _project_settings_json(palette):
    """Generate Bambu Studio project settings as JSON.

    BambuStudio loads this via DynamicPrintConfig::load_from_json —
    it MUST be valid JSON, not XML, or config_loaded will be empty
    and the file gets treated as geometry-only.
    """
    filament_colours = [f"#{hexc}" for hexc, _ in palette]
    filament_types = ["PLA"] * len(palette)
    config = {
        "printer_settings_id": "Bambu Lab A1 0.4 nozzle",
        "filament_colour": filament_colours,
        "filament_type": filament_types,
        "filament_settings_id": [f"Bambu PLA Basic @BBL A1" for _ in palette],
        "print_settings_id": "0.20mm Standard @BBL A1",
        "nozzle_diameter": ["0.4"],
    }
    return json.dumps(config, indent=2)


def write_3mf(mesh: Mesh, filename: str, palette=None):
    """Package a colored mesh into a Bambu Studio-native 3MF.

    Splits the mesh by color into separate volumes (sub-objects),
    groups them under a parent object with <components>, and sets
    the extruder per volume in model_settings.config. This is how
    Bambu Studio natively handles multi-material.
    """
    if palette is None:
        palette = AMS_PALETTE

    title = os.path.splitext(filename)[0]

    # Split mesh into per-color sub-meshes
    color_meshes = _split_mesh_by_color(mesh)

    # Build 3MF objects: one sub-object per color, one parent with components
    # ID allocation: sub-objects get IDs 2..N+1, parent gets N+2
    next_id = 2
    volume_ids = {}  # color -> object_id
    objects_xml = ""

    for color, submesh in color_meshes.items():
        vid = next_id
        volume_ids[color] = vid
        next_id += 1
        mesh_xml = _mesh_to_xml(submesh)
        objects_xml += f"""
    <object id="{vid}" type="model" p:UUID="volume-{vid}">
      <mesh>
{mesh_xml}
      </mesh>
    </object>"""

    # Parent object with components
    parent_id = next_id
    components = "\n".join(
        f'        <component objectid="{vid}" />'
        for vid in volume_ids.values()
    )
    objects_xml += f"""
    <object id="{parent_id}" type="model" p:UUID="parent-{parent_id}">
      <components>
{components}
      </components>
    </object>"""

    model_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter"
       xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
       xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
       xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"
       xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">
  <metadata name="Application">BambuStudio-01.10.00.00</metadata>
  <metadata name="BambuStudio:3mfVersion">1</metadata>
  <metadata name="slic3rpe:Version3mf">1</metadata>
  <metadata name="Title">{title}</metadata>
  <metadata name="Designer">3MF Generator</metadata>
  <resources>{objects_xml}
  </resources>
  <build>
    <item objectid="{parent_id}" p:UUID="build-{parent_id}" />
  </build>
</model>
"""

    # model_settings: parent object with per-volume extruder assignments
    parts_xml = ""
    for color, vid in volume_ids.items():
        cname = palette[color][1] if color < len(palette) else f"Color{color}"
        extruder = color + 1  # AMS slots are 1-indexed
        parts_xml += f"""
    <part id="{vid}" subtype="ModelPart">
      <metadata key="name" value="{cname}" />
      <metadata key="extruder" value="{extruder}" />
    </part>"""

    model_settings = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="{parent_id}">
    <metadata key="name" value="{title}" />
    <metadata key="extruder" value="1" />{parts_xml}
  </object>
  <plate>
    <metadata key="plater_id" value="1" />
    <metadata key="plater_name" value="" />
    <metadata key="locked" value="false" />
    <model_instance>
      <metadata key="object_id" value="{parent_id}" />
      <metadata key="instance_id" value="0" />
    </model_instance>
  </plate>
</config>
"""

    filepath = _bambu_3mf_package(
        model_xml, model_settings, _project_settings_json(palette),
        filename, palette)

    used = sorted(color_meshes.keys())
    colors = ", ".join(f"AMS{i+1}={palette[i][1]}" for i in used if i < len(palette))
    total_v = sum(len(m.vertices) for m in color_meshes.values())
    total_t = sum(len(m.triangles) for m in color_meshes.values())
    print(f"  {filepath}")
    print(f"    {total_v:,} verts, {total_t:,} tris, {len(color_meshes)} volumes | {colors}")


def write_3mf_multi(plates: dict, filename: str, palette=None):
    """Write multiple plates into a single 3MF.

    plates: { plate_name: { piece_name: Mesh, ... }, ... }
    Each plate_name becomes a separate plate in Bambu Studio.
    """
    if palette is None:
        palette = AMS_PALETTE

    title = os.path.splitext(filename)[0]
    next_id = 2
    objects_xml = ""
    build_items_xml = ""
    model_settings_objects = ""
    plate_configs = ""

    for plate_idx, (plate_name, pieces) in enumerate(plates.items(), 1):
        plate_instances = ""

        for piece_name, mesh in pieces.items():
            m = mesh.copy().place_on_ground()
            color_meshes = _split_mesh_by_color(m)

            # Sub-objects (volumes)
            volume_ids = {}
            for color, submesh in color_meshes.items():
                vid = next_id
                volume_ids[color] = vid
                next_id += 1
                mesh_xml = _mesh_to_xml(submesh)
                objects_xml += f"""
    <object id="{vid}" type="model" p:UUID="volume-{vid}">
      <mesh>
{mesh_xml}
      </mesh>
    </object>"""

            # Parent object
            parent_id = next_id
            next_id += 1
            components = "\n".join(
                f'        <component objectid="{vid}" />'
                for vid in volume_ids.values()
            )
            objects_xml += f"""
    <object id="{parent_id}" type="model" p:UUID="parent-{parent_id}">
      <components>
{components}
      </components>
    </object>"""

            build_items_xml += f'\n    <item objectid="{parent_id}" p:UUID="build-{parent_id}" />'

            # Config: parent with per-volume extruder
            parts_xml = ""
            for color, vid in volume_ids.items():
                cname = palette[color][1] if color < len(palette) else f"Color{color}"
                parts_xml += f"""
    <part id="{vid}" subtype="ModelPart">
      <metadata key="name" value="{cname}" />
      <metadata key="extruder" value="{color + 1}" />
    </part>"""

            model_settings_objects += f"""
  <object id="{parent_id}">
    <metadata key="name" value="{piece_name}" />
    <metadata key="extruder" value="1" />{parts_xml}
  </object>"""

            plate_instances += f"""
    <model_instance>
      <metadata key="object_id" value="{parent_id}" />
      <metadata key="instance_id" value="0" />
    </model_instance>"""

        plate_configs += f"""
  <plate>
    <metadata key="plater_id" value="{plate_idx}" />
    <metadata key="plater_name" value="{plate_name}" />
    <metadata key="locked" value="false" />{plate_instances}
  </plate>"""

    model_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter"
       xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
       xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
       xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"
       xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">
  <metadata name="Application">BambuStudio-01.10.00.00</metadata>
  <metadata name="BambuStudio:3mfVersion">1</metadata>
  <metadata name="slic3rpe:Version3mf">1</metadata>
  <metadata name="Title">{title}</metadata>
  <metadata name="Designer">3MF Generator</metadata>
  <resources>{objects_xml}
  </resources>
  <build>{build_items_xml}
  </build>
</model>
"""

    model_settings = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<config>{model_settings_objects}{plate_configs}
</config>
"""

    filepath = _bambu_3mf_package(
        model_xml, model_settings, _project_settings_json(palette),
        filename, palette)

    total_pieces = sum(len(p) for p in plates.values())
    total_v = sum(len(m.vertices) for p in plates.values() for m in p.values())
    total_t = sum(len(m.triangles) for p in plates.values() for m in p.values())
    print(f"  {filepath}")
    print(f"    {total_pieces} objects across {len(plates)} plates")
    print(f"    {total_v:,} verts, {total_t:,} tris | all 4 AMS colors")


# ============================================================================
# SCENE BUILDERS — each function returns a dict of named Mesh pieces
# ============================================================================

def build_gnome(hat_color: int = 0, body_color: int = 1,
                skin_color: int = 3, facing: float = 0) -> Mesh:
    """A garden gnome: pointy hat, round head, tubby body, nose, arms."""
    # Body — squat truncated cone
    body = truncated_cone(8, 6, 18, segments=16, color=body_color)

    # Head — sphere sitting on body
    head = sphere(6, rings=10, segments=16, color=skin_color)
    head.translate(0, 0, 22)

    # Hat — tall cone
    hat = cone(7, 16, segments=16, color=hat_color)
    hat.translate(0, 0, 26)

    # Nose — small sphere
    nose = sphere(2, rings=6, segments=8, color=skin_color)
    nose.translate(0, -6.5, 21)

    # Belt — torus around waist
    belt = torus(7, 1.2, major_segs=16, minor_segs=8, color=hat_color)
    belt.translate(0, 0, 10)

    # Arms — small cylinders
    arm_l = cylinder(2, 10, segments=8, color=body_color)
    arm_l.rotate_y(70).translate(-9, 0, 14)

    arm_r = cylinder(2, 10, segments=8, color=body_color)
    arm_r.rotate_y(-70).translate(9, 0, 14)

    # Feet — small rounded boxes
    foot_l = rounded_box(5, 7, 3, bevel=1, color=body_color)
    foot_l.translate(-4, -1, 0)

    foot_r = rounded_box(5, 7, 3, bevel=1, color=body_color)
    foot_r.translate(4, -1, 0)

    gnome = merge_all(body, head, hat, nose, belt, arm_l, arm_r, foot_l, foot_r)
    gnome.rotate_z(facing)
    return gnome


def build_bar_counter() -> Mesh:
    """A rustic bar counter — long rounded box with a top slab."""
    # Main counter body
    base = rounded_box(100, 24, 30, bevel=2, color=2)  # green (wood stain)

    # Counter top — slightly wider slab
    top = rounded_box(106, 28, 3, bevel=1.5, color=2)
    top.translate(0, 0, 30)

    # Foot rail — cylinder along the front
    rail = cylinder(1.5, 96, segments=12, color=3)  # yellow (brass)
    rail.rotate_y(90).translate(-48, -14, 8)

    return merge_all(base, top, rail)


def build_bar_stool(color: int = 2) -> Mesh:
    """A simple round bar stool — seat disc on 4 legs."""
    seat = cylinder(7, 2.5, segments=16, color=color)
    seat.translate(0, 0, 20)

    legs = Mesh()
    for angle in [45, 135, 225, 315]:
        leg = cylinder(1.2, 20, segments=8, color=color)
        rad = math.radians(angle)
        leg.translate(4.5 * math.cos(rad), 4.5 * math.sin(rad), 0)
        legs.merge(leg)

    # Cross brace
    brace = cylinder(0.8, 12, segments=6, color=3)
    brace.rotate_y(90).translate(-6, 0, 10)

    return merge_all(seat, legs, brace)


def build_beer_mug(color: int = 3) -> Mesh:
    """A tiny beer mug — cylinder with a handle loop."""
    body = truncated_cone(3, 3.2, 6, segments=12, color=color)

    # Beer inside (slightly recessed, different color for foam)
    foam = cylinder(2.8, 1, segments=12, color=3)
    foam.translate(0, 0, 5)

    # Handle — half torus
    handle = Mesh()
    segs = 10
    hr, tr = 3.0, 0.7
    for i in range(segs + 1):
        angle = math.pi * i / segs  # half circle
        cx = 3.2 + hr * math.sin(angle)
        cz = 3 + hr * math.cos(angle)
        for j in range(6):
            ta = 2 * math.pi * j / 6
            hx = cx + tr * math.sin(angle) * math.cos(ta)
            hy = tr * math.sin(ta)
            hz = cz + tr * math.cos(angle) * math.cos(ta)
            handle.vertices.append((hx, hy, hz))

    for i in range(segs):
        for j in range(6):
            j_next = (j + 1) % 6
            v00 = i * 6 + j
            v01 = i * 6 + j_next
            v10 = (i + 1) * 6 + j
            v11 = (i + 1) * 6 + j_next
            handle.triangles.append((v00, v10, v11, color))
            handle.triangles.append((v00, v11, v01, color))

    return merge_all(body, foam, handle)


def build_bottle(body_color: int = 2, cap_color: int = 0,
                 height_scale: float = 1.0) -> Mesh:
    """A small bottle — body and cap in separate AMS colors."""
    h = 10 * height_scale
    body = truncated_cone(3, 2.8, h, segments=12, color=body_color)
    neck = truncated_cone(1.8, 1.5, 5, segments=10, color=body_color)
    neck.translate(0, 0, h)
    cap = cylinder(1.8, 1.5, segments=10, color=cap_color)
    cap.translate(0, 0, h + 5)
    label = truncated_cone(3.05, 2.85, h * 0.4, segments=12, color=cap_color)
    label.translate(0, 0, h * 0.3)
    return merge_all(body, neck, cap, label)


def build_back_wall() -> Mesh:
    """A colorful back-bar wall with two shelves and decorative trim."""
    # Back wall panel
    wall = box(110, 3, 50, color=2)
    wall.translate(0, 16, 0)

    # Accent strip along top of wall
    trim_top = box(110, 3.5, 3, color=3)
    trim_top.translate(0, 16, 50)

    # Accent strip along bottom
    trim_bot = box(110, 3.5, 2, color=3)
    trim_bot.translate(0, 16, 0)

    # Lower shelf
    shelf1 = box(104, 12, 2, color=3)
    shelf1.translate(0, 12, 15)
    # Shelf bracket left
    bk1l = box(2, 10, 2, color=0)
    bk1l.translate(-48, 12, 13)
    bk1r = box(2, 10, 2, color=0)
    bk1r.translate(48, 12, 13)

    # Upper shelf
    shelf2 = box(104, 12, 2, color=3)
    shelf2.translate(0, 12, 32)
    bk2l = box(2, 10, 2, color=0)
    bk2l.translate(-48, 12, 30)
    bk2r = box(2, 10, 2, color=0)
    bk2r.translate(48, 12, 30)

    return merge_all(wall, trim_top, trim_bot,
                     shelf1, bk1l, bk1r, shelf2, bk2l, bk2r)


# ============================================================================
# SCENES — registered by name, each builds a complete printable scene
# ============================================================================

def scene_gnome_bar() -> dict:
    """
    A garden gnome bar — furniture only, place your own gnomes!

    Includes: bar counter, 4 colorful stools, back wall with shelves,
    colorful bottles in all 4 AMS colors, beer mugs, base plate.

    AMS color mapping:
      0 = Red    (bottle accents, stool seats, brackets)
      1 = Blue   (stool seats, bottle bodies)
      2 = Green  (bar counter, wall, wood tones)
      3 = Yellow (brass rail, shelves, trim, mugs)
    """
    pieces = {}

    # --- Bar counter ---
    bar = build_bar_counter()
    pieces["bar_counter"] = bar

    # --- Back wall with shelves ---
    wall = build_back_wall()
    wall.translate(0, 5, 0)

    # --- Colorful bottles on shelves (cycling all 4 AMS colors) ---
    bottle_colors = [
        # (body_color, cap_color, height_scale)
        (0, 3, 1.0),   # red body, yellow cap
        (1, 0, 0.85),  # blue body, red cap
        (2, 3, 1.1),   # green body, yellow cap
        (0, 1, 0.9),   # red body, blue cap
        (1, 3, 1.0),   # blue body, yellow cap
        (2, 0, 0.95),  # green body, red cap
        (3, 0, 1.05),  # yellow body, red cap
        (1, 2, 0.85),  # blue body, green cap
        (0, 2, 1.0),   # red body, green cap
    ]

    bottles = Mesh()
    # Lower shelf bottles
    for i, xpos in enumerate([-40, -28, -16, -4, 8, 20, 32, 44]):
        bc, cc, hs = bottle_colors[i % len(bottle_colors)]
        b = build_bottle(body_color=bc, cap_color=cc, height_scale=hs)
        b.translate(xpos, 14, 17)
        bottles.merge(b)

    # Upper shelf bottles
    for i, xpos in enumerate([-36, -20, -4, 12, 28, 40]):
        bc, cc, hs = bottle_colors[(i + 3) % len(bottle_colors)]
        b = build_bottle(body_color=bc, cap_color=cc, height_scale=hs)
        b.translate(xpos, 14, 34)
        bottles.merge(b)

    pieces["back_wall_with_bottles"] = merge_all(wall, bottles)

    # --- 4 colorful stools (alternating seat colors) ---
    stool_seat_colors = [0, 1, 0, 1]  # red, blue, red, blue seats
    for i, xpos in enumerate([-32, -12, 12, 32]):
        stool = build_bar_stool(color=stool_seat_colors[i])
        stool.translate(xpos, -20, 0)
        pieces[f"stool_{i+1}"] = stool

    # --- Beer mugs on bar top ---
    mug_colors = [3, 0, 3, 1]  # yellow, red, yellow, blue
    for i, xpos in enumerate([-30, -10, 14, 34]):
        mug = build_beer_mug(color=mug_colors[i])
        mug.translate(xpos, -4, 33)
        pieces[f"mug_{i+1}"] = mug

    # --- Base plate ---
    base = rounded_box(140, 60, 1.5, bevel=3, color=2)
    base.translate(0, -5, 0)
    pieces["base_plate"] = base

    return pieces


# ============================================================================
# PIXEL FONT — 5x7 grid per character, rendered as extruded boxes
# ============================================================================

PIXEL_FONT = {
    'A': ["01110","10001","10001","11111","10001","10001","10001"],
    'B': ["11110","10001","10001","11110","10001","10001","11110"],
    'C': ["01110","10001","10000","10000","10000","10001","01110"],
    'D': ["11110","10001","10001","10001","10001","10001","11110"],
    'E': ["11111","10000","10000","11110","10000","10000","11111"],
    'F': ["11111","10000","10000","11110","10000","10000","10000"],
    'G': ["01110","10001","10000","10111","10001","10001","01110"],
    'H': ["10001","10001","10001","11111","10001","10001","10001"],
    'I': ["01110","00100","00100","00100","00100","00100","01110"],
    'J': ["00111","00010","00010","00010","00010","10010","01100"],
    'K': ["10001","10010","10100","11000","10100","10010","10001"],
    'L': ["10000","10000","10000","10000","10000","10000","11111"],
    'M': ["10001","11011","10101","10101","10001","10001","10001"],
    'N': ["10001","11001","10101","10011","10001","10001","10001"],
    'O': ["01110","10001","10001","10001","10001","10001","01110"],
    'P': ["11110","10001","10001","11110","10000","10000","10000"],
    'Q': ["01110","10001","10001","10001","10101","10010","01101"],
    'R': ["11110","10001","10001","11110","10100","10010","10001"],
    'S': ["01110","10001","10000","01110","00001","10001","01110"],
    'T': ["11111","00100","00100","00100","00100","00100","00100"],
    'U': ["10001","10001","10001","10001","10001","10001","01110"],
    'V': ["10001","10001","10001","10001","01010","01010","00100"],
    'W': ["10001","10001","10001","10101","10101","10101","01010"],
    'X': ["10001","10001","01010","00100","01010","10001","10001"],
    'Y': ["10001","10001","01010","00100","00100","00100","00100"],
    'Z': ["11111","00001","00010","00100","01000","10000","11111"],
    '0': ["01110","10001","10011","10101","11001","10001","01110"],
    '1': ["00100","01100","00100","00100","00100","00100","01110"],
    '2': ["01110","10001","00001","00110","01000","10000","11111"],
    '3': ["01110","10001","00001","00110","00001","10001","01110"],
    '4': ["00010","00110","01010","10010","11111","00010","00010"],
    '5': ["11111","10000","11110","00001","00001","10001","01110"],
    '6': ["01110","10001","10000","11110","10001","10001","01110"],
    '7': ["11111","00001","00010","00100","01000","01000","01000"],
    '8': ["01110","10001","10001","01110","10001","10001","01110"],
    '9': ["01110","10001","10001","01111","00001","10001","01110"],
    ' ': ["00000","00000","00000","00000","00000","00000","00000"],
    '!': ["00100","00100","00100","00100","00100","00000","00100"],
    '?': ["01110","10001","00001","00110","00100","00000","00100"],
    '"': ["01010","01010","01010","00000","00000","00000","00000"],
    "'": ["00100","00100","00100","00000","00000","00000","00000"],
    '-': ["00000","00000","00000","11111","00000","00000","00000"],
    '.': ["00000","00000","00000","00000","00000","00000","00100"],
    '/': ["00001","00010","00010","00100","01000","01000","10000"],
    # Umlaut characters
    '\u00d6': ["01010","00000","01110","10001","10001","10001","01110"],  # Ö
    '\u00f6': ["01010","00000","01110","10001","10001","10001","01110"],  # ö
}


def render_text(text: str, pixel_size: float = 1.5, depth: float = 1.5,
                color: int = 0) -> Mesh:
    """Render a string as extruded pixel-font boxes. Origin at bottom-left."""
    result = Mesh()
    cursor_x = 0.0
    char_w = 5  # pixels wide
    char_h = 7  # pixels tall
    spacing = 1  # pixel gap between chars

    for ch in text.upper():
        glyph = PIXEL_FONT.get(ch, PIXEL_FONT[' '])
        for row_idx, row in enumerate(glyph):
            y = (char_h - 1 - row_idx) * pixel_size  # top row = highest y
            for col_idx, pixel in enumerate(row):
                if pixel == '1':
                    x = cursor_x + col_idx * pixel_size
                    b = box(pixel_size * 0.95, depth, pixel_size * 0.95, color=color)
                    b.translate(x, 0, y)
                    result.merge(b)
        cursor_x += (char_w + spacing) * pixel_size

    return result


def text_width(text: str, pixel_size: float = 1.5) -> float:
    """Calculate the width of rendered text."""
    n = len(text)
    if n == 0:
        return 0
    return (n * 5 + (n - 1)) * pixel_size


# ============================================================================
# SIGN BUILDERS
# ============================================================================

def build_circular_sign(radius: float, thickness: float = 3.0,
                        border_width: float = 2.0,
                        plate_color: int = 2, border_color: int = 3,
                        segments: int = 32) -> Mesh:
    """A circular sign plate with a contrasting border ring."""
    # Main disc
    disc = cylinder(radius, thickness, segments=segments, color=plate_color)

    # Border ring
    ring = torus(radius, border_width, major_segs=segments,
                 minor_segs=8, color=border_color)
    ring.translate(0, 0, thickness / 2)

    return merge_all(disc, ring)


def build_hook(color: int = 3) -> Mesh:
    """A wall-mounting hook — cylinder peg with a flat back plate."""
    back = box(5, 1.5, 6, color=color)
    peg = cylinder(1.5, 5, segments=8, color=color)
    peg.rotate_x(-90).translate(0, -1.5, 3)
    tip = cylinder(1.5, 2, segments=8, color=color)
    tip.rotate_x(-60).translate(0, -5.5, 2)
    return merge_all(back, peg, tip)


def render_text_arched(text: str, radius: float, pixel_size: float = 1.0,
                       depth: float = 1.5, color: int = 0,
                       arc_degrees: float = 150) -> Mesh:
    """Render text arched along a circular path. Centered at origin in XZ plane.

    Text curves along the top of the circle (like a brewery logo).
    """
    result = Mesh()
    chars = text.upper()
    n = len(chars)
    if n == 0:
        return result

    char_w = 5  # pixels wide
    char_h = 7  # pixels tall

    # Angular span per character
    arc_rad = math.radians(arc_degrees)
    char_angular_width = arc_rad / max(n, 1)

    # Start angle — centered at top (90 degrees)
    start_angle = math.pi / 2 + arc_rad / 2 - char_angular_width / 2

    for ci, ch in enumerate(chars):
        glyph = PIXEL_FONT.get(ch, PIXEL_FONT.get(ch.upper(), PIXEL_FONT[' ']))
        # Center angle for this character
        char_center_angle = start_angle - ci * char_angular_width

        for row_idx, row in enumerate(glyph):
            for col_idx, pixel in enumerate(row):
                if pixel == '1':
                    # Position within character (centered)
                    local_x = (col_idx - char_w / 2) * pixel_size
                    local_z = (char_h - 1 - row_idx - char_h / 2) * pixel_size

                    # Angular offset for this pixel within the character
                    ang_offset = local_x / radius
                    ang = char_center_angle - ang_offset

                    # Radial offset (text sits at radius + local_z)
                    r = radius + local_z

                    # Place pixel box
                    px = r * math.cos(ang)
                    pz = r * math.sin(ang)

                    b = box(pixel_size * 0.9, depth, pixel_size * 0.9, color=color)
                    # Rotate box to face outward
                    b.rotate_y(-math.degrees(ang) + 90)
                    b.translate(px, 0, pz)
                    result.merge(b)

    return result


def build_owltopus_small(body_color: int = 1, eye_color: int = 3,
                         tentacle_color: int = 0) -> Mesh:
    """A small owl with octopus tentacles — sized for a ~20mm radius sign."""
    # Compact owl body
    body = sphere(3.5, rings=8, segments=12, color=body_color)
    body.scale(1, 0.6, 1.1)

    # Eyes
    eye_l = sphere(1.3, rings=5, segments=8, color=eye_color)
    eye_l.translate(-1.5, -2.5, 1.8)
    pupil_l = sphere(0.6, rings=4, segments=6, color=2)
    pupil_l.translate(-1.5, -3.3, 2)

    eye_r = sphere(1.3, rings=5, segments=8, color=eye_color)
    eye_r.translate(1.5, -2.5, 1.8)
    pupil_r = sphere(0.6, rings=4, segments=6, color=2)
    pupil_r.translate(1.5, -3.3, 2)

    # Beak
    beak = cone(0.8, 1.5, segments=6, color=eye_color)
    beak.rotate_x(-90).translate(0, -3.5, 0.3)

    # Belly
    belly = sphere(2.2, rings=5, segments=8, color=eye_color)
    belly.scale(0.7, 0.3, 0.8).translate(0, -2.8, -0.5)

    # Tentacles — smaller, fewer segments
    tentacles = Mesh()

    def make_tentacle(sx, sz, curl, segs=6):
        t = Mesh()
        x, z, y = sx, sz, -0.5
        for i in range(segs):
            f = i / segs
            r = 0.7 * (1 - f * 0.5)
            s = sphere(r, rings=3, segments=5, color=tentacle_color)
            s.translate(x, y, z)
            t.merge(s)
            x += curl * (0.6 + f * 0.3)
            z += 0.2 - f * 0.8
            y -= 0.15 * f
        return t

    tentacles.merge(make_tentacle(-0.5, 5, -0.8, 5))
    tentacles.merge(make_tentacle(-2, 4.5, -1.0, 4))
    tentacles.merge(make_tentacle(-3.5, 3, -0.6, 4))
    tentacles.merge(make_tentacle(0.5, 5, 0.8, 5))
    tentacles.merge(make_tentacle(2, 4.5, 1.0, 4))
    tentacles.merge(make_tentacle(3.5, 3, 0.6, 4))

    return merge_all(body, eye_l, pupil_l, eye_r, pupil_r, beak,
                     belly, tentacles)


def scene_quarter_plot_sign() -> dict:
    """
    Small circular 'Quarter Plot' sign with arched text and owltopus.
    ~45mm diameter. Prints flat on the bed.

    AMS: 0=Red (tentacles), 1=Blue (owl), 2=Green (disc), 3=Yellow (border/text)
    """
    radius = 22
    pieces = {}

    # Circular disc with border ring
    disc = build_circular_sign(radius, thickness=3,
                               border_width=1.5,
                               plate_color=2, border_color=3)

    # Arched "QUARTER PLOT" around the top
    text_top = render_text_arched("QUARTER", radius=radius - 5,
                                  pixel_size=0.9, depth=1.5, color=3,
                                  arc_degrees=130)
    text_top.translate(0, -1.5, 0)

    # "PLOT" arched along the bottom (flipped arc)
    text_bot = render_text_arched("PLOT", radius=radius - 5,
                                  pixel_size=0.9, depth=1.5, color=3,
                                  arc_degrees=-70)
    text_bot.translate(0, -1.5, 0)

    # Small owltopus in the center
    owltopus = build_owltopus_small(body_color=1, eye_color=3, tentacle_color=0)
    owltopus.translate(0, -2, 0)

    sign = merge_all(disc, text_top, text_bot, owltopus)
    # Lay flat — it's already flat (disc base at z=0)
    pieces["sign"] = sign

    # Two small hooks
    hook_l = build_hook(color=3)
    hook_l.translate(-12, 0, 3)
    pieces["hook_left"] = hook_l

    hook_r = build_hook(color=3)
    hook_r.translate(12, 0, 3)
    pieces["hook_right"] = hook_r

    return pieces


def scene_gnalort_sign() -> dict:
    """
    Small circular 'Gnalört' sign. ~40mm diameter.

    AMS: 0=Red (border), 1=Blue (disc), 2=Green (bottle), 3=Yellow (text)
    """
    radius = 20
    pieces = {}

    disc = build_circular_sign(radius, thickness=3,
                               border_width=1.5,
                               plate_color=1, border_color=0)

    # Arched "GNALÖRT" across the top
    text_top = render_text_arched("GNAL\u00d6RT", radius=radius - 4,
                                  pixel_size=0.85, depth=1.5, color=3,
                                  arc_degrees=130)
    text_top.translate(0, -1.5, 0)

    # Small bottle in the center
    bottle = build_bottle(body_color=2, cap_color=0, height_scale=0.5)
    bottle.scale(0.6).rotate_x(90).translate(0, -2, -2)

    sign = merge_all(disc, text_top, bottle)
    pieces["sign"] = sign

    hook_l = build_hook(color=3)
    hook_l.translate(-10, 0, 3)
    pieces["hook_left"] = hook_l

    hook_r = build_hook(color=3)
    hook_r.translate(10, 0, 3)
    pieces["hook_right"] = hook_r

    return pieces


def scene_single_gnome() -> dict:
    """A single standalone garden gnome."""
    gnome = build_gnome(hat_color=0, body_color=1, skin_color=3, facing=0)
    gnome.place_on_ground()
    base = cylinder(12, 2, segments=24, color=2)
    return {"gnome": merge_all(base, gnome.translate(0, 0, 2))}


# ============================================================================
# Scene registry
# ============================================================================

SCENES = {
    "gnome_bar_scene": {
        "fn": scene_gnome_bar,
        "desc": "Garden bar furniture — stools, back wall, colorful bottles (4 colors)",
    },
    "quarter_plot_sign": {
        "fn": scene_quarter_plot_sign,
        "desc": "'Quarter Plot' sign with owltopus mascot + hooks (4 colors)",
    },
    "gnalort_sign": {
        "fn": scene_gnalort_sign,
        "desc": "'Gnalort?' gnome Malort sign + hooks (4 colors)",
    },
    "single_gnome": {
        "fn": scene_single_gnome,
        "desc": "A standalone garden gnome on a base (3 colors)",
    },
}


def main():
    print("=" * 55)
    print("  AMS Multi-Color 3MF Scene Generator")
    print(f"  Bambu Lab A1 | {BUILD_X}x{BUILD_Y}x{BUILD_Z}mm | 4 AMS slots")
    print("=" * 55)

    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("\nAvailable scenes:")
        for name, info in SCENES.items():
            print(f"  {name:25s} {info['desc']}")
        print(f"\n  {'all':25s} Everything in one file — each scene gets its own plate")
        print(f"\nUsage: python3 {sys.argv[0]} <scene> [--split]")
        print("  --split : export each piece as a separate .3mf file")
        print(f"  python3 {sys.argv[0]} all  : single file, multiple plates")
        sys.exit(0)

    scene_name = sys.argv[1]
    split_mode = "--split" in sys.argv

    # --- ALL mode: one file, each scene on its own plate ---
    if scene_name == "all":
        print("\nBuilding ALL scenes — each on its own plate...")
        plates = {}
        for name, info in SCENES.items():
            print(f"  Plate: {name} — {info['desc']}")
            pieces = info["fn"]()
            plates[name] = pieces
        print(f"\nExporting:")
        write_3mf_multi(plates, "gnome_bar_all.3mf")
        print("\nDone! One file, multiple plates — open in Bambu Studio.")
        return

    if scene_name not in SCENES:
        print(f"\nUnknown scene: '{scene_name}'")
        print(f"Available: {', '.join(SCENES.keys())}, all")
        sys.exit(1)

    print(f"\nBuilding scene: {scene_name}")
    print(f"  {SCENES[scene_name]['desc']}")
    pieces = SCENES[scene_name]["fn"]()

    if split_mode:
        print(f"\nExporting {len(pieces)} pieces as separate files:")
        for piece_name, mesh in pieces.items():
            m = mesh.copy().place_on_ground()
            write_3mf(m, f"{scene_name}_{piece_name}.3mf")
    else:
        print(f"\nExporting as single combined file ({len(pieces)} pieces):")
        combined = Mesh()
        for mesh in pieces.values():
            combined.merge(mesh)
        combined.place_on_ground()
        write_3mf(combined, f"{scene_name}.3mf")

    print("\nDone! Open in Bambu Studio — AMS colors auto-detected.")
    print("AMS slot mapping:")
    for i, (_, name) in enumerate(AMS_PALETTE):
        print(f"  Slot {i+1}: {name}")


if __name__ == "__main__":
    main()
