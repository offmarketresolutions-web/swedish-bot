"""Pure-python service-area geometry + postcode geocoding (plan S5 / D2).

No PostGIS, no shapely — the DB is plain postgres:16. GeoJSON polygons are
stored as JSONField on ServiceArea; all math here operates directly on
[lng, lat] pairs (GeoJSON coordinate order) to avoid silent axis-swap bugs.

check_service_area() is the single entry point the conversation/dashboard call;
everything else is a building block for it.
"""
from __future__ import annotations

import math

# Rough Sweden bounding box (lat, lng) — used only to WARN (never reject) when
# a pasted polygon looks like it has swapped lat/lng, since both axes can be
# individually "in range" (lat 55-69 looks like a plausible lng too).
SWEDEN_BBOX = {"lat_min": 54.0, "lat_max": 70.0, "lng_min": 10.0, "lng_max": 25.0}

MAX_VERTICES = 5000
EARTH_RADIUS_KM = 6371.0088


# ── Point-in-polygon (ray casting) ─────────────────────────────────────────

def point_in_ring(point: tuple[float, float], ring: list[list[float]]) -> bool:
    """Ray-cast point-in-polygon test for a single ring. point=(lng,lat);
    ring=[[lng,lat], ...]. Standard even-odd rule."""
    x, y = point
    inside = False
    n = len(ring)
    if n < 3:
        return False
    x1, y1 = ring[-1]
    for i in range(n):
        x2, y2 = ring[i]
        if (y1 > y) != (y2 > y):
            x_intersect = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_intersect:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def _polygons(geometry: dict) -> list[list[list[list[float]]]]:
    """Normalize a Polygon or MultiPolygon geometry dict to a list of polygons,
    each polygon a list of rings (ring[0]=outer, ring[1:]=holes)."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if gtype == "Polygon":
        return [coords]
    if gtype == "MultiPolygon":
        return coords
    return []


def point_in_polygon(point: tuple[float, float], geometry: dict) -> bool:
    """True if point is inside the geometry (Polygon or MultiPolygon), honoring
    holes (any ring after the first in a polygon is subtracted)."""
    for poly in _polygons(geometry):
        if not poly:
            continue
        if not point_in_ring(point, poly[0]):
            continue
        in_hole = any(point_in_ring(point, hole) for hole in poly[1:])
        if not in_hole:
            return True
    return False


# ── Distance to nearest edge (equirectangular approximation) ──────────────

def _project_km(lng: float, lat: float, lat0: float) -> tuple[float, float]:
    """Equirectangular flattening centered on lat0, in km. Fine at the ~10-50km
    scale this feature operates at; not for antimeridian/pole-crossing shapes."""
    x = math.radians(lng) * math.cos(math.radians(lat0)) * EARTH_RADIUS_KM
    y = math.radians(lat) * EARTH_RADIUS_KM
    return x, y


def _point_segment_distance_km(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def distance_to_edge_km(point: tuple[float, float], geometry: dict) -> float:
    """Minimum distance (km) from point to the nearest edge segment of any ring
    in the geometry. Used for border-review and outside-area reporting."""
    lng, lat = point
    px, py = _project_km(lng, lat, lat)
    best = math.inf
    for poly in _polygons(geometry):
        for ring in poly:
            n = len(ring)
            for i in range(n):
                a = ring[i]
                b = ring[(i + 1) % n]
                ax, ay = _project_km(a[0], a[1], lat)
                bx, by = _project_km(b[0], b[1], lat)
                d = _point_segment_distance_km(px, py, ax, ay, bx, by)
                if d < best:
                    best = d
    return best if best != math.inf else math.inf


# ── GeoJSON validation (fail-closed) ───────────────────────────────────────

def _valid_ring(ring) -> bool:
    if not isinstance(ring, list) or len(ring) < 3:
        return False
    for pt in ring:
        if not (isinstance(pt, list) and len(pt) == 2):
            return False
        lng, lat = pt
        if not isinstance(lng, (int, float)) or not isinstance(lat, (int, float)):
            return False
        if not (-180.0 <= lng <= 180.0) or not (-90.0 <= lat <= 90.0):
            return False
    return True


def _close_ring(ring: list[list[float]]) -> list[list[float]]:
    if ring and ring[0] != ring[-1]:
        return ring + [list(ring[0])]
    return ring


def clean_polygon(data) -> tuple[dict | None, bool, str | None]:
    """Fail-closed GeoJSON validator. Accepts a bare geometry, a Feature, or a
    FeatureCollection (first feature's geometry is used). Returns
    (clean_geometry, sweden_bbox_warning, error) — geometry is None iff error is set.
    """
    if not isinstance(data, dict):
        return None, False, "GeoJSON must be an object"

    geometry = data
    if data.get("type") == "FeatureCollection":
        features = data.get("features")
        if not isinstance(features, list) or not features:
            return None, False, "FeatureCollection has no features"
        geometry = features[0].get("geometry")
    elif data.get("type") == "Feature":
        geometry = data.get("geometry")

    if not isinstance(geometry, dict):
        return None, False, "no geometry found"

    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype not in ("Polygon", "MultiPolygon"):
        return None, False, "geometry must be Polygon or MultiPolygon"
    if not isinstance(coords, list) or not coords:
        return None, False, "coordinates must be a non-empty list"

    polygons = [coords] if gtype == "Polygon" else coords
    total_vertices = 0
    clean_polys = []
    for poly in polygons:
        if not isinstance(poly, list) or not poly:
            return None, False, "polygon must be a non-empty list of rings"
        clean_rings = []
        for ring in poly:
            if not _valid_ring(ring):
                return None, False, "invalid ring: needs >=3 [lng,lat] float pairs in range"
            ring = _close_ring([list(pt) for pt in ring])
            total_vertices += len(ring)
            if total_vertices > MAX_VERTICES:
                return None, False, f"too many vertices (max {MAX_VERTICES})"
            clean_rings.append(ring)
        clean_polys.append(clean_rings)

    clean_geometry = {"type": gtype, "coordinates": clean_polys if gtype == "MultiPolygon" else clean_polys[0]}

    # Sweden-bbox warning: flag (never reject) if NO vertex falls inside the rough
    # Sweden bbox — likely a lat/lng swap or the wrong country's coordinates.
    any_in_sweden = False
    for poly in clean_polys:
        for ring in poly:
            for lng, lat in ring:
                if (SWEDEN_BBOX["lat_min"] <= lat <= SWEDEN_BBOX["lat_max"]
                        and SWEDEN_BBOX["lng_min"] <= lng <= SWEDEN_BBOX["lng_max"]):
                    any_in_sweden = True
                    break
            if any_in_sweden:
                break
        if any_in_sweden:
            break

    return clean_geometry, (not any_in_sweden), None


# ── Geocoding (offline GeoNames postcode table) ────────────────────────────

def geocode_postcode(code: str):
    """Look up a 5-digit Swedish postcode in crm.PostcodeArea. Returns the row
    or None (unknown postcode — never raises)."""
    from crm.models import PostcodeArea

    code = (code or "").strip().replace(" ", "")
    if not code:
        return None
    return PostcodeArea.objects.filter(code=code).first()


# ── Service-area check ─────────────────────────────────────────────────────

def check_service_area(postcode: str, category_slug: str | None = None, *, ignore_enabled: bool = False) -> dict:
    """Returns {"status", "area_name", "distance_km", "city"}.

    status: inside_area | border_review | outside_area | unknown_postcode | not_configured

    ignore_enabled=True runs the check regardless of GeoSettings.enabled — used by the
    dashboard test box so staff can validate polygons before flipping the feature on.
    """
    from crm.models import GeoSettings, ServiceArea

    empty = {"status": "not_configured", "area_name": None, "distance_km": None, "city": None}

    cfg = GeoSettings.load()
    if not cfg.enabled and not ignore_enabled:
        return empty

    areas = ServiceArea.objects.filter(is_active=True)
    if category_slug:
        areas = areas.filter(models_q_categories(category_slug))
    areas = list(areas)
    if not areas:
        return empty

    area_row = geocode_postcode(postcode)
    if area_row is None:
        return {"status": "unknown_postcode", "area_name": None, "distance_km": None, "city": None}

    point = (area_row.lng, area_row.lat)
    city = area_row.city

    border_best = None  # (name, distance)
    outside_best = None  # (name, distance)

    for area in areas:
        geometry = area.polygon
        inside = point_in_polygon(point, geometry)
        if inside and area.kind == "inside":
            return {"status": "inside_area", "area_name": area.name, "distance_km": 0.0, "city": city}
        if inside:  # extension polygon, inside it -> border review
            dist = 0.0
        else:
            dist = distance_to_edge_km(point, geometry)

        if inside or dist <= area.border_km:
            if border_best is None or dist < border_best[1]:
                border_best = (area.name, dist)
        if outside_best is None or dist < outside_best[1]:
            outside_best = (area.name, dist)

    if border_best is not None:
        return {"status": "border_review", "area_name": border_best[0],
                "distance_km": round(border_best[1], 1), "city": city}

    name, dist = outside_best
    return {"status": "outside_area", "area_name": name, "distance_km": round(dist, 1), "city": city}


def models_q_categories(category_slug: str):
    """Q object: ServiceArea rows with no category restriction (applies to all)
    OR explicitly listing this category."""
    from django.db.models import Q

    return Q(categories__isnull=True) | Q(categories__slug=category_slug)


# ── Read-only SVG preview (no map library) ─────────────────────────────────

# The corridor's named reference cities (plan S5 owner spec), for the preview only.
_PREVIEW_CITIES = [
    ("Örnsköldsvik", 63.29, 18.72), ("Härnösand", 62.63, 17.94), ("Sundsvall", 62.39, 17.31),
    ("Hudiksvall", 61.73, 17.10), ("Söderhamn", 61.30, 17.06), ("Gävle", 60.67, 17.14),
    ("Älvkarleby", 60.57, 17.45), ("Uppsala", 59.86, 17.64),
    ("Sollefteå", 63.17, 17.27), ("Ånge", 62.53, 15.66),
]

def check_with_override(result: dict, installer_text: str) -> dict:
    """Upgrade an outside_area/border_review result to inside when the customer
    names a previous installer from GeoSettings.previous_installer_names
    (case-insensitive substring match, either direction — 'nordland' matches
    'Nordland VVS AB' and vice versa)."""
    from crm.models import GeoSettings

    if result.get("status") not in ("outside_area", "border_review"):
        return result
    text = (installer_text or "").strip().lower()
    if not text:
        return result

    cfg = GeoSettings.load()
    for name in cfg.previous_installer_names or []:
        n = name.strip().lower()
        if not n:
            continue
        if n in text or text in n:
            upgraded = dict(result)
            upgraded["status"] = "inside_area"
            upgraded["override"] = True
            upgraded["area_name"] = upgraded.get("area_name") or name
            return upgraded
    return result
