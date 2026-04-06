"""
Composable mesh primitives with transforms and color assignment.

Every primitive returns a Mesh that can be translated, rotated, scaled,
and colored (AMS slot). Meshes can be merged together to build scenes.
"""

import math
from typing import List, Tuple

Vertex = Tuple[float, float, float]
ColorTriangle = Tuple[int, int, int, int]  # v1, v2, v3, ams_slot


class Mesh:
    """A triangle mesh with per-triangle AMS color assignments."""

    def __init__(self, vertices: List[Vertex] = None, triangles: List[ColorTriangle] = None):
        self.vertices: List[Vertex] = list(vertices or [])
        self.triangles: List[ColorTriangle] = list(triangles or [])

    def translate(self, dx: float, dy: float, dz: float) -> "Mesh":
        self.vertices = [(x + dx, y + dy, z + dz) for x, y, z in self.vertices]
        return self

    def scale(self, sx: float, sy: float = None, sz: float = None) -> "Mesh":
        if sy is None:
            sy = sx
        if sz is None:
            sz = sx
        self.vertices = [(x * sx, y * sy, z * sz) for x, y, z in self.vertices]
        return self

    def rotate_z(self, degrees: float) -> "Mesh":
        rad = math.radians(degrees)
        c, s = math.cos(rad), math.sin(rad)
        self.vertices = [(x * c - y * s, x * s + y * c, z)
                         for x, y, z in self.vertices]
        return self

    def rotate_y(self, degrees: float) -> "Mesh":
        rad = math.radians(degrees)
        c, s = math.cos(rad), math.sin(rad)
        self.vertices = [(x * c + z * s, y, -x * s + z * c)
                         for x, y, z in self.vertices]
        return self

    def rotate_x(self, degrees: float) -> "Mesh":
        rad = math.radians(degrees)
        c, s = math.cos(rad), math.sin(rad)
        self.vertices = [(x, y * c - z * s, y * s + z * c)
                         for x, y, z in self.vertices]
        return self

    def color(self, ams_slot: int) -> "Mesh":
        """Set all triangles to a single AMS color slot (0-3)."""
        self.triangles = [(v1, v2, v3, ams_slot) for v1, v2, v3, _ in self.triangles]
        return self

    def merge(self, other: "Mesh") -> "Mesh":
        """Merge another mesh into this one."""
        offset = len(self.vertices)
        self.vertices.extend(other.vertices)
        self.triangles.extend(
            (v1 + offset, v2 + offset, v3 + offset, c)
            for v1, v2, v3, c in other.triangles
        )
        return self

    def copy(self) -> "Mesh":
        return Mesh(list(self.vertices), list(self.triangles))

    def bbox(self):
        """Return ((min_x, min_y, min_z), (max_x, max_y, max_z))."""
        if not self.vertices:
            return ((0, 0, 0), (0, 0, 0))
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))

    def center_xy(self) -> "Mesh":
        """Center the mesh at the XY origin."""
        if not self.vertices:
            return self
        (mn_x, mn_y, _), (mx_x, mx_y, _) = self.bbox()
        cx = (mn_x + mx_x) / 2
        cy = (mn_y + mx_y) / 2
        self.translate(-cx, -cy, 0)
        return self

    def place_on_ground(self) -> "Mesh":
        """Shift so the lowest Z vertex sits at z=0."""
        if self.vertices:
            min_z = min(v[2] for v in self.vertices)
            if min_z != 0:
                self.translate(0, 0, -min_z)
        return self


def merge_all(*meshes: Mesh) -> Mesh:
    """Merge multiple meshes into a single mesh."""
    result = Mesh()
    for m in meshes:
        result.merge(m)
    return result


# ---------------------------------------------------------------------------
# Primitives — all centered at origin, base at z=0, default color=0
# ---------------------------------------------------------------------------

def box(width: float, depth: float, height: float, color: int = 0) -> Mesh:
    """Axis-aligned box centered on XY, base at z=0."""
    hw, hd = width / 2, depth / 2
    v = [
        (-hw, -hd, 0),      (hw, -hd, 0),      (hw, hd, 0),      (-hw, hd, 0),       # bottom
        (-hw, -hd, height), (hw, -hd, height),  (hw, hd, height),  (-hw, hd, height),  # top
    ]
    t = [
        # bottom
        (0, 2, 1, color), (0, 3, 2, color),
        # top
        (4, 5, 6, color), (4, 6, 7, color),
        # front (-y)
        (0, 1, 5, color), (0, 5, 4, color),
        # back (+y)
        (2, 3, 7, color), (2, 7, 6, color),
        # left (-x)
        (3, 0, 4, color), (3, 4, 7, color),
        # right (+x)
        (1, 2, 6, color), (1, 6, 5, color),
    ]
    return Mesh(v, t)


def cylinder(radius: float, height: float, segments: int = 24, color: int = 0) -> Mesh:
    """Cylinder centered on XY, base at z=0."""
    verts: List[Vertex] = []
    tris: List[ColorTriangle] = []

    # Bottom and top rings
    for z in [0.0, height]:
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            verts.append((radius * math.cos(angle), radius * math.sin(angle), z))

    # Side faces
    for i in range(segments):
        i_next = (i + 1) % segments
        b0, b1 = i, i_next
        t0, t1 = segments + i, segments + i_next
        tris.append((b0, b1, t1, color))
        tris.append((b0, t1, t0, color))

    # Bottom cap
    cb = len(verts)
    verts.append((0, 0, 0))
    for i in range(segments):
        tris.append((cb, (i + 1) % segments, i, color))

    # Top cap
    ct = len(verts)
    verts.append((0, 0, height))
    for i in range(segments):
        tris.append((ct, segments + i, segments + (i + 1) % segments, color))

    return Mesh(verts, tris)


def cone(radius: float, height: float, segments: int = 24, color: int = 0) -> Mesh:
    """Cone centered on XY, base at z=0, apex at z=height."""
    verts: List[Vertex] = []
    tris: List[ColorTriangle] = []

    # Base ring
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), 0.0))

    # Apex
    apex = len(verts)
    verts.append((0, 0, height))

    # Side faces
    for i in range(segments):
        tris.append((i, (i + 1) % segments, apex, color))

    # Base cap
    cb = len(verts)
    verts.append((0, 0, 0))
    for i in range(segments):
        tris.append((cb, (i + 1) % segments, i, color))

    return Mesh(verts, tris)


def truncated_cone(r_bottom: float, r_top: float, height: float,
                   segments: int = 24, color: int = 0) -> Mesh:
    """Truncated cone (frustum) centered on XY, base at z=0."""
    verts: List[Vertex] = []
    tris: List[ColorTriangle] = []

    for r, z in [(r_bottom, 0.0), (r_top, height)]:
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            verts.append((r * math.cos(angle), r * math.sin(angle), z))

    for i in range(segments):
        i_next = (i + 1) % segments
        b0, b1 = i, i_next
        t0, t1 = segments + i, segments + i_next
        tris.append((b0, b1, t1, color))
        tris.append((b0, t1, t0, color))

    # Bottom cap
    cb = len(verts)
    verts.append((0, 0, 0))
    for i in range(segments):
        tris.append((cb, (i + 1) % segments, i, color))

    # Top cap
    ct = len(verts)
    verts.append((0, 0, height))
    for i in range(segments):
        tris.append((ct, segments + i, segments + (i + 1) % segments, color))

    return Mesh(verts, tris)


def sphere(radius: float, rings: int = 12, segments: int = 24, color: int = 0) -> Mesh:
    """UV sphere centered at origin."""
    verts: List[Vertex] = []
    tris: List[ColorTriangle] = []

    # Top pole
    verts.append((0, 0, radius))

    # Intermediate rings
    for i in range(1, rings):
        phi = math.pi * i / rings
        rr = radius * math.sin(phi)
        zz = radius * math.cos(phi)
        for j in range(segments):
            theta = 2 * math.pi * j / segments
            verts.append((rr * math.cos(theta), rr * math.sin(theta), zz))

    # Bottom pole
    bottom = len(verts)
    verts.append((0, 0, -radius))

    # Top cap triangles
    for j in range(segments):
        j_next = (j + 1) % segments
        tris.append((0, 1 + j, 1 + j_next, color))

    # Middle quads
    for i in range(rings - 2):
        row = 1 + i * segments
        next_row = 1 + (i + 1) * segments
        for j in range(segments):
            j_next = (j + 1) % segments
            tris.append((row + j, next_row + j, next_row + j_next, color))
            tris.append((row + j, next_row + j_next, row + j_next, color))

    # Bottom cap triangles
    last_row = 1 + (rings - 2) * segments
    for j in range(segments):
        j_next = (j + 1) % segments
        tris.append((last_row + j, bottom, last_row + j_next, color))

    return Mesh(verts, tris)


def torus(major_r: float, minor_r: float, major_segs: int = 24,
          minor_segs: int = 12, color: int = 0) -> Mesh:
    """Torus centered at origin, lying in the XY plane."""
    verts: List[Vertex] = []
    tris: List[ColorTriangle] = []

    for i in range(major_segs):
        theta = 2 * math.pi * i / major_segs
        cx, cy = major_r * math.cos(theta), major_r * math.sin(theta)
        for j in range(minor_segs):
            phi = 2 * math.pi * j / minor_segs
            r = major_r + minor_r * math.cos(phi)
            verts.append((r * math.cos(theta), r * math.sin(theta),
                          minor_r * math.sin(phi)))

    for i in range(major_segs):
        i_next = (i + 1) % major_segs
        for j in range(minor_segs):
            j_next = (j + 1) % minor_segs
            v00 = i * minor_segs + j
            v01 = i * minor_segs + j_next
            v10 = i_next * minor_segs + j
            v11 = i_next * minor_segs + j_next
            tris.append((v00, v10, v11, color))
            tris.append((v00, v11, v01, color))

    return Mesh(verts, tris)


def hemisphere(radius: float, rings: int = 8, segments: int = 24,
               color: int = 0) -> Mesh:
    """Upper hemisphere centered at origin, flat side at z=0."""
    verts: List[Vertex] = []
    tris: List[ColorTriangle] = []

    # Top pole
    verts.append((0, 0, radius))

    # Rings from top toward equator
    for i in range(1, rings + 1):
        phi = (math.pi / 2) * i / rings  # 0 to pi/2
        rr = radius * math.sin(phi)
        zz = radius * math.cos(phi)
        for j in range(segments):
            theta = 2 * math.pi * j / segments
            verts.append((rr * math.cos(theta), rr * math.sin(theta), zz))

    # Top cap
    for j in range(segments):
        j_next = (j + 1) % segments
        tris.append((0, 1 + j, 1 + j_next, color))

    # Middle bands
    for i in range(rings - 1):
        row = 1 + i * segments
        next_row = 1 + (i + 1) * segments
        for j in range(segments):
            j_next = (j + 1) % segments
            tris.append((row + j, next_row + j, next_row + j_next, color))
            tris.append((row + j, next_row + j_next, row + j_next, color))

    # Bottom cap (flat)
    bc = len(verts)
    verts.append((0, 0, 0))
    last_row = 1 + (rings - 1) * segments
    for j in range(segments):
        j_next = (j + 1) % segments
        tris.append((bc, last_row + j_next, last_row + j, color))

    return Mesh(verts, tris)


def rounded_box(width: float, depth: float, height: float,
                bevel: float = 1.0, color: int = 0) -> Mesh:
    """A box with beveled vertical edges (octagonal cross-section)."""
    hw, hd = width / 2, depth / 2
    b = min(bevel, hw * 0.3, hd * 0.3)

    # Octagonal profile
    profile = [
        (hw, hd - b), (hw, -(hd - b)),
        (hw - b, -hd), (-(hw - b), -hd),
        (-hw, -(hd - b)), (-hw, hd - b),
        (-(hw - b), hd), (hw - b, hd),
    ]
    n = len(profile)

    verts: List[Vertex] = []
    tris: List[ColorTriangle] = []

    # Bottom and top rings
    for z in [0.0, height]:
        for px, py in profile:
            verts.append((px, py, z))

    # Sides
    for i in range(n):
        i_next = (i + 1) % n
        b0, b1 = i, i_next
        t0, t1 = n + i, n + i_next
        tris.append((b0, b1, t1, color))
        tris.append((b0, t1, t0, color))

    # Bottom cap
    bc = len(verts)
    verts.append((0, 0, 0))
    for i in range(n):
        tris.append((bc, (i + 1) % n, i, color))

    # Top cap
    tc = len(verts)
    verts.append((0, 0, height))
    for i in range(n):
        tris.append((tc, n + i, n + (i + 1) % n, color))

    return Mesh(verts, tris)
