from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import math
import threading
import urllib.request

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1024
HEIGHT = 512
TILE_SIZE = 256
MAX_POINTS = 20
MAX_CACHE_ENTRIES = 100
TILE_SOURCE_GSI_AERIAL = "gsi_aerial"
TILE_SOURCE_OSM = "osm"
DEFAULT_TILE_SOURCE = TILE_SOURCE_GSI_AERIAL

_cache: OrderedDict[str, bytes] = OrderedDict()
_cache_lock = threading.Lock()


def parse_preview_points(raw: object) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    for pair in str(raw or "").split("|"):
        if not pair.strip():
            continue
        try:
            lat_text, lng_text = pair.split(",", 1)
            lat = float(lat_text)
            lng = float(lng_text)
        except (TypeError, ValueError):
            continue
        if abs(lat) > 90 or abs(lng) > 180:
            continue
        points.append({"lat": lat, "lng": lng})
        if len(points) >= MAX_POINTS:
            break
    return points


def serialize_preview_points(points: list[dict]) -> str:
    output = []
    for point in points[:MAX_POINTS]:
        try:
            lat = float(point["lat"])
            lng = float(point["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        if abs(lat) <= 90 and abs(lng) <= 180:
            output.append(f"{lat:.6f},{lng:.6f}")
    return "|".join(output)


def _world_point(point: dict[str, float], zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2**zoom)
    sin_lat = math.sin(math.radians(point["lat"]))
    clamped = min(0.9999, max(-0.9999, sin_lat))
    x = (point["lng"] + 180) / 360 * scale
    y = (
        0.5
        - math.log((1 + clamped) / (1 - clamped)) / (4 * math.pi)
    ) * scale
    return x, y


def _choose_zoom(points: list[dict[str, float]]) -> int:
    if len(points) <= 1:
        return 17
    for zoom in range(18, 5, -1):
        projected = [_world_point(point, zoom) for point in points]
        xs = [point[0] for point in projected]
        ys = [point[1] for point in projected]
        if max(xs) - min(xs) <= WIDTH * 0.62 and max(ys) - min(ys) <= HEIGHT * 0.56:
            return zoom
    return 6


def _geometry(points: list[dict[str, float]]) -> dict:
    zoom = _choose_zoom(points)
    projected = [_world_point(point, zoom) for point in points]
    center_x = sum(point[0] for point in projected) / len(projected)
    center_y = sum(point[1] for point in projected) / len(projected)
    left = center_x - WIDTH / 2
    top = center_y - HEIGHT / 2
    return {
        "zoom": zoom,
        "left": left,
        "top": top,
        "screen_points": [
            (point[0] - left, point[1] - top) for point in projected
        ],
    }


def preview_bounds(points: list[dict[str, float]]) -> tuple[tuple[float, ...], int]:
    geometry = _geometry(points)
    scale = TILE_SIZE * (2 ** geometry["zoom"])

    def to_lng(x: float) -> float:
        return x / scale * 360 - 180

    def to_lat(y: float) -> float:
        mercator = math.pi - (2 * math.pi * y) / scale
        return math.degrees(math.atan(math.sinh(mercator)))

    return (
        (
            to_lng(geometry["left"]),
            to_lat(geometry["top"] + HEIGHT),
            to_lng(geometry["left"] + WIDTH),
            to_lat(geometry["top"]),
        ),
        geometry["zoom"],
    )


def _font(size: int):
    for name in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def normalize_tile_source(value: object) -> str:
    source = str(value or "").strip().lower()
    if source == TILE_SOURCE_OSM:
        return TILE_SOURCE_OSM
    return TILE_SOURCE_GSI_AERIAL


def _fetch_tile(
    zoom: int,
    x: int,
    y: int,
    tile_source: str,
) -> Image.Image | None:
    tile_count = 2**zoom
    if y < 0 or y >= tile_count:
        return None
    wrapped_x = x % tile_count
    if tile_source == TILE_SOURCE_OSM:
        url = f"https://tile.openstreetmap.org/{zoom}/{wrapped_x}/{y}.png"
    else:
        url = (
            "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/"
            f"{zoom}/{wrapped_x}/{y}.jpg"
        )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "line-map-bot/1.0 (LINE field map preview)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return Image.open(BytesIO(response.read())).convert("RGB")
    except Exception:
        return None


def _project_coordinate(coordinate, geometry: dict) -> tuple[float, float]:
    lng, lat = float(coordinate[0]), float(coordinate[1])
    x, y = _world_point({"lat": lat, "lng": lng}, geometry["zoom"])
    return x - geometry["left"], y - geometry["top"]


def _nearby_label_features(
    cadastral: dict | None,
    geometry: dict,
    screen_points: list[tuple[float, float]],
    *,
    max_distance: float = 180,
) -> list[dict]:
    labels = [
        feature
        for feature in list((cadastral or {}).get("features") or [])
        if (feature.get("properties") or {}).get("layer") == "label"
        and (feature.get("geometry") or {}).get("type") == "Point"
    ]
    candidates = []
    for feature in labels:
        coordinate = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinate) < 2:
            continue
        x, y = _project_coordinate(coordinate, geometry)
        candidates.append((feature, x, y))

    selected = []
    selected_ids = set()
    max_distance_squared = max_distance**2
    for point_x, point_y in screen_points[:2]:
        nearest = sorted(
            candidates,
            key=lambda item: (item[1] - point_x) ** 2 + (item[2] - point_y) ** 2,
        )
        for feature, label_x, label_y in nearest:
            feature_id = str(feature.get("id") or id(feature))
            distance_squared = (label_x - point_x) ** 2 + (label_y - point_y) ** 2
            if distance_squared > max_distance_squared:
                break
            if feature_id in selected_ids:
                continue
            selected.append(feature)
            selected_ids.add(feature_id)
            break
    return selected


def _draw_cadastral(
    image: Image.Image,
    cadastral: dict | None,
    geometry: dict,
    screen_points: list[tuple[float, float]],
) -> int:
    features = list((cadastral or {}).get("features") or [])
    if not features:
        return 0
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    label_font = _font(16)
    selected_labels = {
        str(feature.get("id") or id(feature))
        for feature in _nearby_label_features(
            cadastral,
            geometry,
            screen_points,
        )
    }

    def draw_line(coordinates, *, fill, width, closed=False):
        points = [_project_coordinate(coordinate, geometry) for coordinate in coordinates]
        if len(points) < 2:
            return
        if closed:
            points.append(points[0])
        draw.line(points, fill=fill, width=width, joint="curve")

    for feature in features:
        properties = feature.get("properties") or {}
        layer = properties.get("layer")
        geometry_value = feature.get("geometry") or {}
        geometry_type = geometry_value.get("type")
        coordinates = geometry_value.get("coordinates") or []
        if layer == "label" and geometry_type == "Point":
            if str(feature.get("id") or id(feature)) not in selected_labels:
                continue
            point = _project_coordinate(coordinates, geometry)
            label = str(properties.get("label") or "")
            if label:
                draw.text(
                    point,
                    label,
                    fill=(138, 45, 10, 235),
                    font=label_font,
                    anchor="mm",
                    stroke_width=3,
                    stroke_fill=(255, 255, 255, 235),
                )
            continue
        color = (154, 52, 18, 115) if layer == "leader" else (249, 115, 22, 135)
        width = 1 if layer == "leader" else 2
        if geometry_type == "Polygon":
            for ring in coordinates:
                draw_line(ring, fill=color, width=width, closed=True)
        elif geometry_type == "MultiPolygon":
            for polygon in coordinates:
                for ring in polygon:
                    draw_line(ring, fill=color, width=width, closed=True)
        elif geometry_type == "LineString":
            draw_line(coordinates, fill=color, width=width)
        elif geometry_type == "MultiLineString":
            for line in coordinates:
                draw_line(line, fill=color, width=width)
    image.alpha_composite(overlay)
    return len(features)


def _paste_tiles(
    image: Image.Image,
    geometry: dict,
    tile_source: str,
) -> int:
    loaded = 0
    min_tile_x = math.floor(geometry["left"] / TILE_SIZE)
    max_tile_x = math.floor((geometry["left"] + WIDTH) / TILE_SIZE)
    min_tile_y = math.floor(geometry["top"] / TILE_SIZE)
    max_tile_y = math.floor((geometry["top"] + HEIGHT) / TILE_SIZE)
    coordinates = [
        (tile_x, tile_y)
        for tile_y in range(min_tile_y, max_tile_y + 1)
        for tile_x in range(min_tile_x, max_tile_x + 1)
    ]

    def fetch(coordinate):
        tile_x, tile_y = coordinate
        return (
            tile_x,
            tile_y,
            _fetch_tile(geometry["zoom"], tile_x, tile_y, tile_source),
        )

    with ThreadPoolExecutor(max_workers=min(8, len(coordinates))) as executor:
        tiles = executor.map(fetch, coordinates)
        for tile_x, tile_y, tile in tiles:
            if tile is None:
                continue
            left = round(tile_x * TILE_SIZE - geometry["left"])
            top = round(tile_y * TILE_SIZE - geometry["top"])
            image.paste(tile, (left, top))
            loaded += 1
    return loaded


def render_map_preview(
    points: list[dict[str, float]],
    *,
    use_tiles: bool = True,
    cadastral: dict | None = None,
    connect_points: bool = False,
    tile_source: str = DEFAULT_TILE_SOURCE,
) -> bytes:
    if not points:
        raise ValueError("at least one valid point is required")
    cadastral_features = list((cadastral or {}).get("features") or [])
    source_date = str(((cadastral or {}).get("metadata") or {}).get("source_date") or "")
    requested_tile_source = normalize_tile_source(tile_source)
    cache_key = (
        f"{requested_tile_source if use_tiles else 'plain'}:"
        f"{'line' if connect_points else 'pins'}:"
        f"{serialize_preview_points(points)}:"
        f"{len(cadastral_features)}:{source_date}"
    )
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached is not None:
            _cache.move_to_end(cache_key)
            return cached

    geometry = _geometry(points)
    image = Image.new("RGBA", (WIDTH, HEIGHT), "#EEF3F7")
    rendered_tile_source = ""
    if use_tiles:
        if _paste_tiles(image, geometry, requested_tile_source):
            rendered_tile_source = requested_tile_source
        elif requested_tile_source != TILE_SOURCE_OSM:
            if _paste_tiles(image, geometry, TILE_SOURCE_OSM):
                rendered_tile_source = TILE_SOURCE_OSM

    draw = ImageDraw.Draw(image)
    screen_points = geometry["screen_points"]
    cadastral_count = _draw_cadastral(
        image,
        cadastral,
        geometry,
        screen_points,
    )
    draw = ImageDraw.Draw(image)
    numbered = connect_points and len(screen_points) == 2
    if numbered:
        draw.line(screen_points, fill="#173B67", width=8, joint="curve")
    number_font = _font(24)
    for index, (x, y) in enumerate(screen_points):
        if numbered:
            draw.ellipse((x - 28, y - 28, x + 28, y + 28), fill="white", outline="#173B67", width=7)
            color = "#D99100" if index == 0 else "#D94A4A"
            draw.ellipse((x - 17, y - 17, x + 17, y + 17), fill=color)
            draw.text((x, y), str(index + 1), fill="white", font=number_font, anchor="mm")
        else:
            radius = 22 if len(screen_points) == 1 else 10
            draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill="#D94A4A",
                outline="white",
                width=7 if len(screen_points) == 1 else 4,
            )

    draw.rectangle((0, HEIGHT - 30, WIDTH, HEIGHT), fill=(255, 255, 255))
    attribution = ""
    if rendered_tile_source == TILE_SOURCE_GSI_AERIAL:
        attribution = "Source: GSI Japan aerial imagery"
    elif rendered_tile_source == TILE_SOURCE_OSM:
        attribution = "© OpenStreetMap contributors"
    if cadastral_count:
        attribution += (
            " / " if attribution else ""
        ) + "Cadastral: Gojo City CC BY 4.0"
    draw.text(
        (WIDTH - 12, HEIGHT - 15),
        attribution,
        fill="#334155",
        font=_font(16),
        anchor="rm",
    )

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    result = output.getvalue()
    with _cache_lock:
        _cache[cache_key] = result
        _cache.move_to_end(cache_key)
        while len(_cache) > MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)
    return result
