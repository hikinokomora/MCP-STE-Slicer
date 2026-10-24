"""Geometry analysis of a triangle mesh (numpy only, Python 3.5).

All functions work in the printer frame: X right, Y back, Z up, millimetres.
Uranium's scene frame is Y-up; use scene_to_printer / rotation_printer_to_scene
to convert between the two.
"""
import math

import numpy

P = numpy.array([[1.0, 0.0, 0.0],
                 [0.0, 0.0, -1.0],
                 [0.0, 1.0, 0.0]])

OVERHANG_COS = math.cos(math.radians(45.0))
AXES = {"X": numpy.array([1.0, 0.0, 0.0]),
        "Y": numpy.array([0.0, 1.0, 0.0]),
        "Z": numpy.array([0.0, 0.0, 1.0])}


def scene_to_printer(vertices):
    return numpy.dot(vertices, P.T)


def rotation_printer_to_scene(rotation):
    return numpy.dot(P.T, numpy.dot(rotation, P))


def triangles_from_mesh(vertices, indices=None):
    vertices = numpy.asarray(vertices, dtype=numpy.float64)
    if indices is not None and len(indices):
        return vertices[numpy.asarray(indices, dtype=numpy.int64)]
    count = (len(vertices) // 3) * 3
    return vertices[:count].reshape(-1, 3, 3)


def _face_data(tri):
    cross = numpy.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = numpy.linalg.norm(cross, axis=1)
    areas = norm / 2.0
    safe = numpy.where(norm > 1e-12, norm, 1.0)
    normals = cross / safe[:, None]
    return normals, areas


def rotation_between(a, b):
    """Rotation matrix that turns unit vector a onto unit vector b."""
    a = a / numpy.linalg.norm(a)
    b = b / numpy.linalg.norm(b)
    v = numpy.cross(a, b)
    c = float(numpy.dot(a, b))
    if c > 1.0 - 1e-9:
        return numpy.identity(3)
    if c < -1.0 + 1e-9:
        perp = numpy.cross(a, [1.0, 0.0, 0.0])
        if numpy.linalg.norm(perp) < 1e-6:
            perp = numpy.cross(a, [0.0, 1.0, 0.0])
        perp = perp / numpy.linalg.norm(perp)
        return 2.0 * numpy.outer(perp, perp) - numpy.identity(3)
    vx = numpy.array([[0.0, -v[2], v[1]], [v[2], 0.0, -v[0]], [-v[1], v[0], 0.0]])
    return numpy.identity(3) + vx + numpy.dot(vx, vx) * (1.0 / (1.0 + c))


def support_metrics(tri, normals=None, areas=None):
    if normals is None:
        normals, areas = _face_data(tri)
    zmin = tri[:, :, 2].min()
    face_min_z = tri[:, :, 2].min(axis=1)
    face_max_z = tri[:, :, 2].max(axis=1)
    down = normals[:, 2] < -OVERHANG_COS
    on_bed = face_max_z <= zmin + 0.3
    contact = float(areas[down & on_bed].sum())
    overhang = float(areas[down & ~on_bed & (face_min_z > zmin + 0.3)].sum())
    height = float(tri[:, :, 2].max() - zmin)
    return {"overhang_area_mm2": round(overhang, 1),
            "bed_contact_area_mm2": round(contact, 1),
            "height_mm": round(height, 2)}


def _slice_cv(pu, pw, hb, height_bins, sectors, cu, cw):
    """Per height bin: coefficient of variation of the max radius over angular sectors."""
    du = pu - cu
    dw = pw - cw
    r = numpy.sqrt(du * du + dw * dw)
    theta = numpy.arctan2(dw, du)
    sb = numpy.clip(((theta + math.pi) / (2 * math.pi) * sectors).astype(int), 0, sectors - 1)
    rmax = numpy.zeros((height_bins, sectors))
    numpy.maximum.at(rmax, (hb, sb), r)
    cvs = numpy.full(height_bins, numpy.nan)
    for i, row in enumerate(rmax):
        if (row > 0).sum() >= sectors * 0.25:
            cvs[i] = row.std() / max(row.mean(), 1e-6)
    return r, theta, cvs


def revolution_analysis(tri, axis_vec, height_bins=24, sectors=36):
    """How close the mesh is to a body of revolution around an axis parallel to axis_vec.

    The axis position is taken from the cross-sections that are round on their own,
    so a shaft with a cam lobe still gets its axis through the shaft.
    """
    axis_vec = axis_vec / numpy.linalg.norm(axis_vec)
    pts = numpy.concatenate([tri.reshape(-1, 3), tri.mean(axis=1)])
    helper = numpy.array([1.0, 0.0, 0.0]) if abs(axis_vec[0]) < 0.9 else numpy.array([0.0, 1.0, 0.0])
    u = numpy.cross(axis_vec, helper)
    u /= numpy.linalg.norm(u)
    w = numpy.cross(axis_vec, u)
    h = numpy.dot(pts, axis_vec)
    pu = numpy.dot(pts, u)
    pw = numpy.dot(pts, w)

    length = float(h.max() - h.min())
    if length <= 1e-6:
        return None
    hb = numpy.clip(((h - h.min()) / length * height_bins).astype(int), 0, height_bins - 1)

    centres = []
    for i in range(height_bins):
        m = hb == i
        if m.sum() < 8:
            continue
        cu = (pu[m].min() + pu[m].max()) / 2.0
        cw = (pw[m].min() + pw[m].max()) / 2.0
        _, _, cvs = _slice_cv(pu[m], pw[m], numpy.zeros(int(m.sum()), dtype=int), 1, sectors, cu, cw)
        if not numpy.isnan(cvs[0]) and cvs[0] < 0.1:
            centres.append((cu, cw))
    if centres:
        cu, cw = numpy.median(numpy.array(centres), axis=0)
    else:
        cu = (pu.min() + pu.max()) / 2.0
        cw = (pw.min() + pw.max()) / 2.0

    r, theta, cvs = _slice_cv(pu, pw, hb, height_bins, sectors, cu, cw)
    valid = cvs[~numpy.isnan(cvs)]
    if not len(valid):
        return None
    diameter = float(2.0 * r.max())

    rmin = float(r.min())
    near = r <= rmin + max(0.5, 0.05 * rmin)
    covered = len(numpy.unique(numpy.clip(((theta[near] + math.pi) / (2 * math.pi) * sectors).astype(int), 0, sectors - 1)))
    bore = 2.0 * rmin if rmin > 0.5 and covered >= sectors * 0.6 else 0.0

    centre = cu * u + cw * w
    return {
        "symmetry_score": round(max(0.0, 1.0 - float(numpy.median(valid))), 3),
        "round_fraction": round(float((valid < 0.1).sum()) / len(valid), 2),
        "length_along_axis_mm": round(length, 2),
        "outer_diameter_mm": round(diameter, 2),
        "bore_diameter_mm": round(bore, 2),
        "aspect_length_to_diameter": round(length / max(diameter, 1e-6), 3),
        "axis_point_mm": [round(float(x), 2) for x in centre],
    }


def _candidate_down_directions(normals, areas, limit=8):
    """Axis directions plus normals of the largest planar face clusters."""
    candidates = []
    for vec in AXES.values():
        candidates.append(vec)
        candidates.append(-vec)
    rounded = numpy.round(normals, 2)
    keys, inverse = numpy.unique(rounded, axis=0, return_inverse=True)
    sums = numpy.bincount(inverse, weights=areas)
    for idx in numpy.argsort(sums)[::-1][:limit]:
        n = keys[idx]
        if numpy.linalg.norm(n) > 0.5:
            candidates.append(n / numpy.linalg.norm(n))
    unique = []
    for c in candidates:
        if all(numpy.dot(c, o) < 0.999 for o in unique):
            unique.append(c)
    return unique


def best_flat_orientation(tri):
    """Pick the rotation (printer frame) that minimises overhangs and maximises bed contact."""
    normals, areas = _face_data(tri)
    total = float(areas.sum()) or 1.0
    best = None
    for down in _candidate_down_directions(normals, areas):
        rot = rotation_between(down, numpy.array([0.0, 0.0, -1.0]))
        rt = numpy.einsum("ij,nkj->nki", rot, tri)
        rn = numpy.dot(normals, rot.T)
        m = support_metrics(rt, rn, areas)
        score = (m["overhang_area_mm2"] - 0.6 * m["bed_contact_area_mm2"]) / total + 0.002 * m["height_mm"]
        if best is None or score < best[0]:
            best = (score, rot, m, down)
    return best[1], best[2], [round(float(x), 3) for x in best[3]]


def analyze(tri):
    normals, areas = _face_data(tri)
    mins = tri.reshape(-1, 3).min(axis=0)
    maxs = tri.reshape(-1, 3).max(axis=0)
    size = maxs - mins
    signed = numpy.einsum("ij,ij->i", tri[:, 0], numpy.cross(tri[:, 1], tri[:, 2])) / 6.0
    volume = abs(float(signed.sum()))
    result = {
        "triangles": int(len(tri)),
        "size_mm": {"x": round(float(size[0]), 2), "y": round(float(size[1]), 2), "z": round(float(size[2]), 2)},
        "volume_cm3": round(volume / 1000.0, 2),
        "surface_area_cm2": round(float(areas.sum()) / 100.0, 2),
        "current_orientation": support_metrics(tri, normals, areas),
    }

    revolutions = {}
    best_axis = None
    for name, vec in AXES.items():
        rev = revolution_analysis(tri, vec)
        if rev is None:
            continue
        revolutions[name] = rev
        if best_axis is None or rev["symmetry_score"] > revolutions[best_axis]["symmetry_score"]:
            best_axis = name
    result["revolution_by_axis"] = revolutions
    if best_axis is not None:
        rev = revolutions[best_axis]
        result["revolution_axis"] = best_axis
        result["is_body_of_revolution"] = rev["symmetry_score"] >= 0.85 and rev["round_fraction"] >= 0.6
        result["is_shaft_with_features"] = (not result["is_body_of_revolution"]) and rev["round_fraction"] >= 0.4
        result["has_axial_bore"] = rev["bore_diameter_mm"] >= 4.0
        r_out = rev["outer_diameter_mm"] / 2.0
        r_in = rev["bore_diameter_mm"] / 2.0
        annulus = math.pi * (r_out ** 2 - r_in ** 2) * rev["length_along_axis_mm"]
        rev["annulus_fill"] = round(volume / annulus, 2) if annulus > 0 else 0.0
        rev["wall_to_radius"] = round((r_out - r_in) / r_out, 2) if r_out > 0 else 1.0
        result["spiral_candidate"] = bool(result["is_body_of_revolution"] and result["has_axial_bore"]
                                          and rev["annulus_fill"] >= 0.8 and rev["wall_to_radius"] <= 0.25)

    rot, metrics, down = best_flat_orientation(tri)
    result["best_3d_orientation"] = {"down_direction": down, "metrics": metrics,
                                     "is_current": bool(numpy.allclose(rot, numpy.identity(3), atol=1e-3))}
    result["hints"] = _hints(result)
    return result


def _hints(r):
    hints = []
    if r.get("is_body_of_revolution"):
        rev = r["revolution_by_axis"][r["revolution_axis"]]
        text = "Тело вращения вокруг оси %s (симметрия %.2f, Ø%.1f мм, длина %.1f мм)." % (
            r["revolution_axis"], rev["symmetry_score"], rev["outer_diameter_mm"], rev["length_along_axis_mm"])
        if r.get("has_axial_bore"):
            text += " Есть осевое отверстие Ø%.1f мм — деталь можно надеть на цилиндрическое основание 5D." % rev["bore_diameter_mm"]
        hints.append(text)
    elif r.get("is_shaft_with_features"):
        rev = r["revolution_by_axis"][r["revolution_axis"]]
        hints.append("Вал вдоль оси %s: %.0f%% длины — круглые сечения, остальное — несимметричные элементы (кулачок, лопасти)." % (
            r["revolution_axis"], rev["round_fraction"] * 100))
        if not r.get("has_axial_bore") and rev["aspect_length_to_diameter"] >= 0.5:
            hints.append("Сплошной вал с кулачком/выступами — 5D (cylindrical_full): ядро диаметром основания печатается в 3D, "
                         "остальное — цилиндрическими слоями, рабочий профиль без «ступенек». Несимметричный выступ — не повод для 3D.")
    if r.get("revolution_axis"):
        rev = r["revolution_by_axis"][r["revolution_axis"]]
        if r.get("spiral_candidate"):
            hints.append("Тонкостенная втулка/труба (стенка %.0f%% радиуса, заполнение кольца %.0f%%) — кандидат на 5D Spiral (cylindrical)." % (
                rev["wall_to_radius"] * 100, rev["annulus_fill"] * 100))
        elif r.get("is_body_of_revolution") or r.get("is_shaft_with_features"):
            hints.append("Не для 5D Spiral: материал занимает %.0f%% кольца между отверстием и наружным диаметром "
                         "(лопасти, рёбра, гофры или переменный внутренний диаметр), стенка %.0f%% радиуса." % (
                             rev["annulus_fill"] * 100, rev["wall_to_radius"] * 100))
    cur = r["current_orientation"]
    if cur["overhang_area_mm2"] > 100:
        hints.append("В текущей ориентации нависания %.0f мм² — нужны поддержки или другая ориентация." % cur["overhang_area_mm2"])
    best = r["best_3d_orientation"]
    if not best["is_current"]:
        hints.append("Для 3D лучше положить деталь гранью с нормалью %s вниз (нависания %.0f мм², контакт со столом %.0f мм²)." % (
            best["down_direction"], best["metrics"]["overhang_area_mm2"], best["metrics"]["bed_contact_area_mm2"]))
    return hints


def axis_to_vertical_rotation(axis_name):
    return rotation_between(AXES[axis_name], AXES["Z"])


def plan_batches(count, part_w, part_d, bed_w, bed_d, margin=10.0, spacing=10.0, max_per_run=None):
    """How to print `count` identical 3D parts: how many fit on the bed and how to split them into equal runs.

    The footprint (part_w x part_d, mm) is packed on a grid with `spacing` between parts and `margin` from the
    bed edges. The part may be turned 90 degrees around the vertical axis if more copies fit (that does not change
    print quality). Runs are balanced (12 parts, 8 fit -> 2 runs of 6, not 8 + 4) so every run takes the same time.
    Positions are part centres relative to the bed centre (printer X right, Y back).
    """
    count = max(1, int(count))
    usable_w, usable_d = bed_w - 2 * margin, bed_d - 2 * margin
    best = None
    for rotated, (pw, pd) in ((False, (part_w, part_d)), (True, (part_d, part_w))):
        nx = int((usable_w + spacing) // (pw + spacing)) if pw <= usable_w else 0
        ny = int((usable_d + spacing) // (pd + spacing)) if pd <= usable_d else 0
        key = (nx * ny, not rotated)
        if best is None or key > best[0]:
            best = (key, rotated, pw, pd, nx, ny)
    (capacity, _), rotated, pw, pd, nx, ny = best
    if capacity == 0:
        return {"requested": count, "max_per_plate": 0}
    plate_capacity = capacity
    if max_per_run:
        capacity = max(1, min(capacity, int(max_per_run)))
    runs = int(math.ceil(count / float(capacity)))
    per_run = int(math.ceil(count / float(runs)))
    layout = None
    for cols in range(1, nx + 1):
        rows = int(math.ceil(per_run / float(cols)))
        if rows > ny:
            continue
        block_w, block_d = cols * pw + (cols - 1) * spacing, rows * pd + (rows - 1) * spacing
        score = max(block_w / usable_w, block_d / usable_d)
        if layout is None or score < layout[0]:
            layout = (score, cols, rows, block_w, block_d)
    _, cols, rows, block_w, block_d = layout
    positions = []
    for i in range(per_run):
        r, c = divmod(i, cols)
        positions.append((round(-block_w / 2 + pw / 2 + c * (pw + spacing), 2),
                          round(block_d / 2 - pd / 2 - r * (pd + spacing), 2)))
    return {"requested": count, "max_per_plate": plate_capacity, "runs": runs, "per_run": per_run,
            "last_run": count - per_run * (runs - 1), "rotated_90": rotated, "grid": [cols, rows],
            "spacing_mm": spacing, "margin_mm": margin, "positions_mm": positions}
