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


def write_3mf(mesh: Mesh, filename: str, palette=None):
    """Package a colored triangle mesh into a valid 3MF file with AMS materials."""
    if palette is None:
        palette = AMS_PALETTE

    vertices = mesh.vertices
    triangles = mesh.triangles
    used = sorted(set(t[3] for t in triangles))

    mat_lines = "\n".join(
        f'        <base name="{name}" displaycolor="#{hexc}" />'
        for hexc, name in palette
    )
    vert_xml = "\n".join(
        f'          <vertex x="{v[0]:.4f}" y="{v[1]:.4f}" z="{v[2]:.4f}" />'
        for v in vertices
    )
    tri_xml = "\n".join(
        f'          <triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}" pid="1" p1="{t[3]}" />'
        for t in triangles
    )

    model_xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter"
       xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
       xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
  <metadata name="Application">BambuLab3MFGenerator</metadata>
  <metadata name="Title">{os.path.splitext(filename)[0]}</metadata>
  <resources>
    <basematerials id="1">
{mat_lines}
    </basematerials>
    <object id="2" type="model">
      <mesh>
        <vertices>
{vert_xml}
        </vertices>
        <triangles>
{tri_xml}
        </triangles>
      </mesh>
    </object>
  </resources>
  <build>
    <item objectid="2" />
  </build>
</model>
"""

    content_types = """\
<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml" />
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

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "wb") as f:
        f.write(buf.getvalue())

    colors = ", ".join(f"AMS{i+1}={palette[i][1]}" for i in used if i < len(palette))
    print(f"  {filepath}")
    print(f"    {len(vertices):,} verts, {len(triangles):,} tris | {colors}")


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


def build_bottle(color: int = 2) -> Mesh:
    """A small bottle — for behind the bar."""
    body = truncated_cone(3, 3, 10, segments=12, color=color)
    neck = truncated_cone(1.8, 1.5, 5, segments=10, color=color)
    neck.translate(0, 0, 10)
    cap = cylinder(1.8, 1.5, segments=10, color=0)
    cap.translate(0, 0, 15)
    return merge_all(body, neck, cap)


def build_shelf() -> Mesh:
    """A back-bar shelf for bottles."""
    # Back wall
    wall = box(100, 3, 40, color=2)
    wall.translate(0, 16, 0)

    # Shelves
    shelf1 = box(96, 10, 1.5, color=2)
    shelf1.translate(0, 12, 15)

    shelf2 = box(96, 10, 1.5, color=2)
    shelf2.translate(0, 12, 30)

    return merge_all(wall, shelf1, shelf2)


# ============================================================================
# SCENES — registered by name, each builds a complete printable scene
# ============================================================================

def scene_gnome_bar() -> dict:
    """
    A bar scene with gnomes for a garden.

    AMS color mapping:
      0 = Red    (gnome hats, accents)
      1 = Blue   (gnome coats)
      2 = Green  (bar/furniture — wood)
      3 = Yellow (skin, brass, beer)
    """
    pieces = {}

    # --- Bar counter (centered) ---
    bar = build_bar_counter()
    pieces["bar_counter"] = bar

    # --- Back shelf with bottles ---
    shelf = build_shelf()
    shelf.translate(0, 5, 0)  # behind bar
    bottles_on_shelf = Mesh()
    for i, xpos in enumerate([-36, -24, -12, 0, 12, 24, 36]):
        b = build_bottle(color=2 if i % 2 == 0 else 0)
        b.translate(xpos, 14, 16.5)
        bottles_on_shelf.merge(b)
    pieces["back_shelf"] = merge_all(shelf, bottles_on_shelf)

    # --- Bar stools ---
    for i, xpos in enumerate([-32, -12, 12, 32]):
        stool = build_bar_stool(color=2)
        stool.translate(xpos, -20, 0)
        pieces[f"stool_{i+1}"] = stool

    # --- Gnomes sitting at the bar ---
    # Gnome 1 — at stool 1, facing bar
    g1 = build_gnome(hat_color=0, body_color=1, skin_color=3, facing=0)
    g1.translate(-32, -20, 22)
    pieces["gnome_patron_1"] = g1

    # Gnome 2 — at stool 2
    g2 = build_gnome(hat_color=0, body_color=1, skin_color=3, facing=15)
    g2.translate(-12, -20, 22)
    pieces["gnome_patron_2"] = g2

    # Gnome 3 — at stool 4, leaning in
    g3 = build_gnome(hat_color=0, body_color=1, skin_color=3, facing=-10)
    g3.translate(32, -20, 22)
    pieces["gnome_patron_3"] = g3

    # --- Bartender gnome (behind bar) ---
    bartender = build_gnome(hat_color=0, body_color=2, skin_color=3, facing=180)
    bartender.translate(0, 8, 0)
    pieces["gnome_bartender"] = bartender

    # --- Beer mugs on bar top ---
    for i, xpos in enumerate([-30, -10, 14, 34]):
        mug = build_beer_mug(color=3)
        mug.translate(xpos, -4, 33)
        pieces[f"mug_{i+1}"] = mug

    # --- Base plate (optional — helps adhesion) ---
    base = rounded_box(130, 60, 1.5, bevel=3, color=2)
    base.translate(0, -5, 0)
    pieces["base_plate"] = base

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
        "desc": "A bar scene with gnomes for a garden (4 colors)",
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
        print(f"\nUsage: python3 {sys.argv[0]} <scene> [--split]")
        print("  --split : export each piece as a separate .3mf file")
        sys.exit(0)

    scene_name = sys.argv[1]
    split_mode = "--split" in sys.argv

    if scene_name not in SCENES:
        print(f"\nUnknown scene: '{scene_name}'")
        print(f"Available: {', '.join(SCENES.keys())}")
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
