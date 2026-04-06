#!/usr/bin/env python3
"""
AMS Multi-Color 3MF Generator for Bambu Lab A1

Generates decorative 3D printable objects as .3mf files with per-triangle
color assignments mapped to AMS filament slots (up to 4 colors).

The Bambu Lab A1 + AMS Lite supports 4 filament slots. Each triangle in
the mesh is assigned to an AMS slot via the 3MF basematerials extension,
so Bambu Studio automatically maps colors to the correct extruder.

Models included:
  - twisted_vase     : Gradient-colored twisted vase (2 colors)
  - color_sphere     : Multi-color faceted icosphere desk toy (4 colors)
  - star_ornament    : Two-tone star with contrasting loop (2 colors)
  - hex_planter      : Hexagonal planter with accent rim (3 colors)
  - striped_cylinder : Simple striped cylinder (4 colors)

Usage:
    python3 generate_3mf.py                     # Generate all models
    python3 generate_3mf.py twisted_vase        # Generate one model
    python3 generate_3mf.py star_ornament hex_planter  # Generate multiple
"""

import math
import os
import sys
import zipfile
from io import BytesIO
from typing import Dict, List, Optional, Tuple

# Bambu Lab A1 build volume (mm)
BUILD_X = 256
BUILD_Y = 256
BUILD_Z = 256

Vertex = Tuple[float, float, float]
# (v1, v2, v3, material_index) — material_index maps to AMS slot 0-3
ColorTriangle = Tuple[int, int, int, int]

# Default AMS color palette (RRGGBB hex, matching common Bambu filaments)
DEFAULT_PALETTE = [
    ("FF4444", "Red"),
    ("4488FF", "Blue"),
    ("44DD44", "Green"),
    ("FFCC00", "Yellow"),
]


def make_3mf(
    vertices: List[Vertex],
    triangles: List[ColorTriangle],
    filename: str,
    palette: Optional[List[Tuple[str, str]]] = None,
):
    """Package a colored triangle mesh into a valid 3MF file with AMS materials."""
    if palette is None:
        palette = DEFAULT_PALETTE

    # Determine which material indices are actually used
    used_materials = sorted(set(t[3] for t in triangles))

    # Build basematerials XML
    mat_lines = []
    for idx in range(len(palette)):
        color_hex, name = palette[idx]
        mat_lines.append(
            f'        <base name="{name}" displaycolor="#{color_hex}" />'
        )
    materials_xml = "\n".join(mat_lines)

    # Build vertices XML
    vert_lines = "\n".join(
        f'          <vertex x="{v[0]:.6f}" y="{v[1]:.6f}" z="{v[2]:.6f}" />'
        for v in vertices
    )

    # Build triangles XML with per-triangle material (pid=1 references basematerials id="1")
    tri_lines = "\n".join(
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
{materials_xml}
    </basematerials>
    <object id="2" type="model">
      <mesh>
        <vertices>
{vert_lines}
        </vertices>
        <triangles>
{tri_lines}
        </triangles>
      </mesh>
    </object>
  </resources>
  <build>
    <item objectid="2" />
  </build>
</model>
"""

    content_types_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml" />
</Types>
"""

    rels_xml = """\
<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0"
                Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" />
</Relationships>
"""

    # Write the ZIP-based 3MF file
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("3D/3dmodel.model", model_xml)

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "wb") as f:
        f.write(buf.getvalue())

    color_summary = ", ".join(
        f"AMS{idx+1}={palette[idx][1]}" for idx in used_materials if idx < len(palette)
    )
    print(f"  Created: {filepath}")
    print(f"    Vertices: {len(vertices):,}  Triangles: {len(triangles):,}")
    print(f"    AMS colors: {color_summary}")


# ---------------------------------------------------------------------------
# Model generators — each returns (vertices, colored_triangles)
# ---------------------------------------------------------------------------

def generate_twisted_vase():
    """A twisted vase with gradient color bands (2 AMS colors)."""
    print("\nGenerating twisted vase (2-color gradient)...")
    segments = 48
    layers = 80
    height = 120.0
    base_radius = 35.0
    twist_total = math.radians(180)

    vertices: List[Vertex] = []
    triangles: List[ColorTriangle] = []

    for j in range(layers + 1):
        t = j / layers
        z = t * height
        twist = t * twist_total
        r = base_radius * (0.6 + 0.4 * math.sin(t * math.pi))
        for i in range(segments):
            angle = 2 * math.pi * i / segments + twist
            wave = 1.0 + 0.08 * math.sin(6 * angle + t * 4 * math.pi)
            x = r * wave * math.cos(angle)
            y = r * wave * math.sin(angle)
            vertices.append((x, y, z))

    # Side faces with alternating color bands
    for j in range(layers):
        color = 0 if (j // 10) % 2 == 0 else 1  # alternate every 10 layers
        for i in range(segments):
            i_next = (i + 1) % segments
            v00 = j * segments + i
            v10 = j * segments + i_next
            v01 = (j + 1) * segments + i
            v11 = (j + 1) * segments + i_next
            triangles.append((v00, v10, v11, color))
            triangles.append((v00, v11, v01, color))

    # Bottom cap
    center_bottom = len(vertices)
    vertices.append((0.0, 0.0, 0.0))
    for i in range(segments):
        i_next = (i + 1) % segments
        triangles.append((center_bottom, i_next, i, 0))

    # Top cap
    center_top = len(vertices)
    top_start = layers * segments
    vertices.append((0.0, 0.0, height))
    for i in range(segments):
        i_next = (i + 1) % segments
        triangles.append((center_top, top_start + i, top_start + i_next, 1))

    make_3mf(vertices, triangles, "twisted_vase.3mf")


def generate_color_sphere():
    """A 4-color icosphere desk toy — each quadrant a different AMS color."""
    print("\nGenerating 4-color icosphere desk toy...")
    radius = 40.0
    subdivisions = 2

    phi = (1 + math.sqrt(5)) / 2
    raw = [
        (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
        (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
        (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1),
    ]
    verts = []
    for v in raw:
        length = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
        verts.append((v[0]/length, v[1]/length, v[2]/length))

    faces = [
        (0,11,5),(0,5,1),(0,1,7),(0,7,10),(0,10,11),
        (1,5,9),(5,11,4),(11,10,2),(10,7,6),(7,1,8),
        (3,9,4),(3,4,2),(3,2,6),(3,6,8),(3,8,9),
        (4,9,5),(2,4,11),(6,2,10),(8,6,7),(9,8,1),
    ]

    mid_cache: Dict[Tuple[int, int], int] = {}

    def get_middle(i1, i2):
        key = (min(i1, i2), max(i1, i2))
        if key in mid_cache:
            return mid_cache[key]
        v1, v2 = verts[i1], verts[i2]
        mid = ((v1[0]+v2[0])/2, (v1[1]+v2[1])/2, (v1[2]+v2[2])/2)
        length = math.sqrt(mid[0]**2 + mid[1]**2 + mid[2]**2)
        mid = (mid[0]/length, mid[1]/length, mid[2]/length)
        idx = len(verts)
        verts.append(mid)
        mid_cache[key] = idx
        return idx

    for _ in range(subdivisions):
        new_faces = []
        mid_cache = {}
        for tri in faces:
            a, b, c = tri
            ab = get_middle(a, b)
            bc = get_middle(b, c)
            ca = get_middle(c, a)
            new_faces.extend([(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)])
        faces = new_faces

    # Position sphere on build plate
    sphere_center_z = radius + 3.5
    vertices: List[Vertex] = [
        (v[0] * radius, v[1] * radius, v[2] * radius + sphere_center_z)
        for v in verts
    ]

    # Color by quadrant: use centroid of each triangle to pick AMS slot
    triangles: List[ColorTriangle] = []
    for a, b, c in faces:
        cx = (verts[a][0] + verts[b][0] + verts[c][0]) / 3
        cy = (verts[a][1] + verts[b][1] + verts[c][1]) / 3
        # 4 quadrants based on x/y sign of the unit-sphere centroid
        if cx >= 0 and cy >= 0:
            color = 0
        elif cx < 0 and cy >= 0:
            color = 1
        elif cx < 0 and cy < 0:
            color = 2
        else:
            color = 3
        triangles.append((a, b, c, color))

    # Cylindrical base (single color)
    base_r = 20.0
    base_h = 3.0
    base_segs = 32
    base_start = len(vertices)

    for i in range(base_segs):
        angle = 2 * math.pi * i / base_segs
        vertices.append((base_r * math.cos(angle), base_r * math.sin(angle), 0.0))
    for i in range(base_segs):
        angle = 2 * math.pi * i / base_segs
        vertices.append((base_r * math.cos(angle), base_r * math.sin(angle), base_h))

    for i in range(base_segs):
        i_next = (i + 1) % base_segs
        b0, b1 = base_start + i, base_start + i_next
        t0, t1 = base_start + base_segs + i, base_start + base_segs + i_next
        triangles.append((b0, b1, t1, 0))
        triangles.append((b0, t1, t0, 0))

    cb = len(vertices)
    vertices.append((0.0, 0.0, 0.0))
    for i in range(base_segs):
        triangles.append((cb, base_start + (i+1) % base_segs, base_start + i, 0))

    ct = len(vertices)
    vertices.append((0.0, 0.0, base_h))
    for i in range(base_segs):
        triangles.append((ct, base_start + base_segs + i,
                          base_start + base_segs + (i+1) % base_segs, 0))

    make_3mf(vertices, triangles, "color_sphere.3mf")


def generate_star_ornament():
    """A two-tone star ornament — star body in color 0, hanging loop in color 1."""
    print("\nGenerating 2-color star ornament...")
    vertices: List[Vertex] = []
    triangles: List[ColorTriangle] = []

    points = 5
    outer_r = 50.0
    inner_r = 22.0
    thickness = 8.0
    half_t = thickness / 2

    star_pts_2d = []
    for i in range(points * 2):
        angle = math.pi / 2 + i * math.pi / points
        r = outer_r if i % 2 == 0 else inner_r
        star_pts_2d.append((r * math.cos(angle), r * math.sin(angle)))

    n_pts = len(star_pts_2d)

    front_start = len(vertices)
    for px, py in star_pts_2d:
        vertices.append((px, py, half_t))

    back_start = len(vertices)
    for px, py in star_pts_2d:
        vertices.append((px, py, -half_t))

    front_center = len(vertices)
    vertices.append((0.0, 0.0, half_t))
    back_center = len(vertices)
    vertices.append((0.0, 0.0, -half_t))

    for i in range(n_pts):
        i_next = (i + 1) % n_pts
        triangles.append((front_center, front_start + i, front_start + i_next, 0))

    for i in range(n_pts):
        i_next = (i + 1) % n_pts
        triangles.append((back_center, back_start + i_next, back_start + i, 0))

    for i in range(n_pts):
        i_next = (i + 1) % n_pts
        f0, f1 = front_start + i, front_start + i_next
        b0, b1 = back_start + i, back_start + i_next
        triangles.append((f0, f1, b1, 0))
        triangles.append((f0, b1, b0, 0))

    # Hanging loop — color 1
    loop_center_y = outer_r + 8.0
    loop_outer_r = 8.0
    loop_inner_r = 4.0
    loop_segs = 24

    for ring_r in [loop_outer_r, loop_inner_r]:
        ring_start = len(vertices)
        for i in range(loop_segs):
            angle = 2 * math.pi * i / loop_segs
            cy = loop_center_y + ring_r * math.sin(angle)
            cz = ring_r * math.cos(angle)
            vertices.append((half_t, cy, cz))
            vertices.append((-half_t, cy, cz))
        if ring_r == loop_outer_r:
            outer_ring_start = ring_start
        else:
            inner_ring_start = ring_start

    for i in range(loop_segs):
        i_next = (i + 1) % loop_segs
        of0 = outer_ring_start + i * 2
        of1 = outer_ring_start + i * 2 + 1
        on0 = outer_ring_start + i_next * 2
        on1 = outer_ring_start + i_next * 2 + 1
        triangles.append((of0, on0, on1, 1))
        triangles.append((of0, on1, of1, 1))

        inf0 = inner_ring_start + i * 2
        inf1 = inner_ring_start + i * 2 + 1
        inn0 = inner_ring_start + i_next * 2
        inn1 = inner_ring_start + i_next * 2 + 1
        triangles.append((inf0, inn1, inn0, 1))
        triangles.append((inf0, inf1, inn1, 1))

        triangles.append((of0, inf0, inn0, 1))
        triangles.append((of0, inn0, on0, 1))
        triangles.append((of1, inn1, inf1, 1))
        triangles.append((of1, on1, inn1, 1))

    # Shift so bottom rests on bed
    min_z = min(v[2] for v in vertices)
    vertices = [(v[0], v[1], v[2] - min_z) for v in vertices]

    make_3mf(vertices, triangles, "star_ornament.3mf")


def generate_hex_planter():
    """A hexagonal planter: body=color0, rim=color1, floor=color2."""
    print("\nGenerating 3-color hexagonal planter...")
    vertices: List[Vertex] = []
    triangles: List[ColorTriangle] = []

    sides = 6
    bottom_radius = 35.0
    top_radius = 45.0
    height = 70.0
    wall_thickness = 3.0
    floor_thickness = 4.0

    def hex_ring(radius, z):
        pts = []
        for i in range(sides):
            angle = 2 * math.pi * i / sides + math.radians(30)
            pts.append((radius * math.cos(angle), radius * math.sin(angle), z))
        return pts

    ob_start = len(vertices)
    vertices.extend(hex_ring(bottom_radius, 0.0))
    ot_start = len(vertices)
    vertices.extend(hex_ring(top_radius, height))
    ib_start = len(vertices)
    vertices.extend(hex_ring(bottom_radius - wall_thickness, floor_thickness))
    it_start = len(vertices)
    vertices.extend(hex_ring(top_radius - wall_thickness, height))

    # Outer sides — color 0 (body)
    for i in range(sides):
        i_next = (i + 1) % sides
        triangles.append((ob_start + i, ob_start + i_next, ot_start + i_next, 0))
        triangles.append((ob_start + i, ot_start + i_next, ot_start + i, 0))

    # Inner sides — color 0 (body)
    for i in range(sides):
        i_next = (i + 1) % sides
        triangles.append((ib_start + i, it_start + i_next, ib_start + i_next, 0))
        triangles.append((ib_start + i, it_start + i, it_start + i_next, 0))

    # Top rim — color 1 (accent)
    for i in range(sides):
        i_next = (i + 1) % sides
        triangles.append((ot_start + i, ot_start + i_next, it_start + i_next, 1))
        triangles.append((ot_start + i, it_start + i_next, it_start + i, 1))

    # Bottom face — color 0
    bc = len(vertices)
    vertices.append((0.0, 0.0, 0.0))
    for i in range(sides):
        triangles.append((bc, ob_start + (i+1) % sides, ob_start + i, 0))

    # Floor — color 2
    fc = len(vertices)
    vertices.append((0.0, 0.0, floor_thickness))
    for i in range(sides):
        triangles.append((fc, ib_start + i, ib_start + (i+1) % sides, 2))

    # Bottom wall edge — color 0
    for i in range(sides):
        i_next = (i + 1) % sides
        triangles.append((ob_start + i, ob_start + i_next, ib_start + i_next, 0))
        triangles.append((ob_start + i, ib_start + i_next, ib_start + i, 0))

    make_3mf(vertices, triangles, "hex_planter.3mf")


def generate_striped_cylinder():
    """A simple cylinder with 4-color horizontal stripes — great AMS test print."""
    print("\nGenerating 4-color striped cylinder (AMS test)...")
    radius = 30.0
    height = 60.0
    segments = 48
    bands = 8  # number of color bands

    vertices: List[Vertex] = []
    triangles: List[ColorTriangle] = []

    layers = bands * 4  # 4 layers per band for smooth geometry
    for j in range(layers + 1):
        z = height * j / layers
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            vertices.append((radius * math.cos(angle), radius * math.sin(angle), z))

    # Side faces
    for j in range(layers):
        color = (j // (layers // bands)) % 4
        for i in range(segments):
            i_next = (i + 1) % segments
            v00 = j * segments + i
            v10 = j * segments + i_next
            v01 = (j + 1) * segments + i
            v11 = (j + 1) * segments + i_next
            triangles.append((v00, v10, v11, color))
            triangles.append((v00, v11, v01, color))

    # Bottom cap
    cb = len(vertices)
    vertices.append((0.0, 0.0, 0.0))
    for i in range(segments):
        triangles.append((cb, (i+1) % segments, i, 0))

    # Top cap
    ct = len(vertices)
    top_start = layers * segments
    vertices.append((0.0, 0.0, height))
    for i in range(segments):
        triangles.append((ct, top_start + i, top_start + (i+1) % segments, 3))

    make_3mf(vertices, triangles, "striped_cylinder.3mf")


# ---------------------------------------------------------------------------
# Registry & main
# ---------------------------------------------------------------------------

MODELS = {
    "twisted_vase": generate_twisted_vase,
    "color_sphere": generate_color_sphere,
    "star_ornament": generate_star_ornament,
    "hex_planter": generate_hex_planter,
    "striped_cylinder": generate_striped_cylinder,
}


def main():
    print("=" * 50)
    print("AMS Multi-Color 3MF Generator for Bambu Lab A1")
    print(f"Build volume: {BUILD_X}x{BUILD_Y}x{BUILD_Z}mm")
    print(f"AMS slots: {len(DEFAULT_PALETTE)} colors")
    print("=" * 50)

    if len(sys.argv) > 1:
        names = sys.argv[1:]
    else:
        names = list(MODELS.keys())

    for name in names:
        if name not in MODELS:
            print(f"\nUnknown model: '{name}'")
            print(f"Available models: {', '.join(MODELS.keys())}")
            sys.exit(1)
        MODELS[name]()

    print("\n" + "=" * 50)
    print("Done! Open the .3mf files in Bambu Studio.")
    print("The AMS color assignments will be auto-detected.")
    print("=" * 50)


if __name__ == "__main__":
    main()
