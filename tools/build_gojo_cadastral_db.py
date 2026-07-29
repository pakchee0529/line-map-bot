from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import shapefile
    from pyproj import Transformer
except ImportError as exc:
    raise SystemExit(
        "build dependencies are missing: "
        "python -m pip install -r tools/requirements-cadastral-build.txt"
    ) from exc


SOURCE_DATE = "2026-01-01"
SOURCE_PAGE = "https://www.city.gojo.lg.jp/soshiki/zeimu/chibanzu/19460.html"
TERMS_URL = "https://www.city.gojo.lg.jp/material/files/group/7/0508riyoukiyaku.pdf"
SOURCE_URLS = {
    "chiban": "https://www.city.gojo.lg.jp/material/files/group/8/chiban_shape.zip",
    "leaders": (
        "https://www.city.gojo.lg.jp/material/files/group/8/"
        "tochi_chibanhikidashi_shape.zip"
    ),
    "polygon_shp": (
        "https://www.city.gojo.lg.jp/material/files/group/8/fugepolygon1_shape.zip"
    ),
    "polygon_sidecars": (
        "https://www.city.gojo.lg.jp/material/files/group/8/fudepolygon2_shape.zip"
    ),
    "boundary": "https://www.city.gojo.lg.jp/material/files/group/8/kyoukai_shape.zip",
}

TRANSFORMER = Transformer.from_crs("EPSG:2448", "EPSG:4326", always_xy=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only SQLite dataset from Gojo cadastral open data."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/cadastral/gojo_chiban.sqlite"),
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "ippatsu" / "gojo-cadastral",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Download official ZIP files again even when cached.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_sources(cache_dir: Path, force: bool) -> dict[str, dict[str, str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, str]] = {}
    for name, url in SOURCE_URLS.items():
        target = cache_dir / f"{name}.zip"
        if force or not target.exists():
            temp_target = target.with_suffix(".zip.part")
            print(f"download: {url}")
            with urllib.request.urlopen(url, timeout=120) as response:
                with temp_target.open("wb") as output:
                    shutil.copyfileobj(response, output)
            temp_target.replace(target)
        manifest[name] = {
            "url": url,
            "sha256": sha256_file(target),
            "bytes": str(target.stat().st_size),
        }
    return manifest


def extract_sources(cache_dir: Path, work_dir: Path) -> dict[str, Path]:
    extracted: dict[str, Path] = {}
    for name in SOURCE_URLS:
        destination = work_dir / name
        destination.mkdir(parents=True, exist_ok=True)
        # The official ZIPs use CP932 member names without the UTF-8 flag.
        with zipfile.ZipFile(
            cache_dir / f"{name}.zip",
            metadata_encoding="cp932",
        ) as archive:
            archive.extractall(destination)
        extracted[name] = destination

    polygon_dir = work_dir / "polygon"
    polygon_dir.mkdir(parents=True, exist_ok=True)
    for source_name in ("polygon_shp", "polygon_sidecars"):
        for source in extracted[source_name].rglob("*"):
            if source.is_file():
                shutil.copy2(source, polygon_dir / source.name)
    extracted["polygon"] = polygon_dir
    return extracted


def find_one(root: Path, pattern: str) -> Path:
    matches = list(root.rglob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern} under {root}, found {len(matches)}")
    return matches[0]


def transform_coordinates(value):
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        lng, lat = TRANSFORMER.transform(value[0], value[1])
        return [round(lng, 8), round(lat, 8)]
    return [transform_coordinates(item) for item in value]


def transform_geometry(shape) -> dict:
    geometry = shape.__geo_interface__
    return {
        "type": geometry["type"],
        "coordinates": transform_coordinates(geometry["coordinates"]),
    }


def geometry_bbox(geometry: dict) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []

    def collect(value):
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[0]), float(value[1])))
            return
        for item in value:
            collect(item)

    collect(geometry["coordinates"])
    if not points:
        raise ValueError("geometry has no coordinates")
    lngs = [point[0] for point in points]
    lats = [point[1] for point in points]
    return min(lngs), min(lats), max(lngs), max(lats)


def json_compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;

        CREATE TABLE dataset_manifest (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE parcels (
            id INTEGER PRIMARY KEY,
            geometry TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE parcels_rtree USING rtree(
            id, min_lng, max_lng, min_lat, max_lat
        );

        CREATE TABLE parcel_labels (
            id INTEGER PRIMARY KEY,
            label TEXT NOT NULL,
            lng REAL NOT NULL,
            lat REAL NOT NULL,
            angle REAL,
            size REAL
        );
        CREATE VIRTUAL TABLE parcel_labels_rtree USING rtree(
            id, min_lng, max_lng, min_lat, max_lat
        );

        CREATE TABLE leader_lines (
            id INTEGER PRIMARY KEY,
            geometry TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE leader_lines_rtree USING rtree(
            id, min_lng, max_lng, min_lat, max_lat
        );

        CREATE TABLE oaza_boundaries (
            id INTEGER PRIMARY KEY,
            name TEXT,
            geometry TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE oaza_boundaries_rtree USING rtree(
            id, min_lng, max_lng, min_lat, max_lat
        );
        """
    )


def reader_for(shp_path: Path) -> shapefile.Reader:
    return shapefile.Reader(str(shp_path), encoding="cp932", encodingErrors="strict")


def import_parcels(connection: sqlite3.Connection, shp_path: Path) -> int:
    reader = reader_for(shp_path)
    fields = [field[0] for field in reader.fields[1:]]
    visible_index = fields.index("VISIBLE")
    imported = 0
    for shape_record in reader.iterShapeRecords():
        if int(shape_record.record[visible_index] or 0) != 1:
            continue
        geometry = transform_geometry(shape_record.shape)
        min_lng, min_lat, max_lng, max_lat = geometry_bbox(geometry)
        imported += 1
        connection.execute(
            "INSERT INTO parcels(id, geometry) VALUES (?, ?)",
            (imported, json_compact(geometry)),
        )
        connection.execute(
            """
            INSERT INTO parcels_rtree(id, min_lng, max_lng, min_lat, max_lat)
            VALUES (?, ?, ?, ?, ?)
            """,
            (imported, min_lng, max_lng, min_lat, max_lat),
        )
        if imported % 5000 == 0:
            print(f"parcels: {imported}")
    return imported


def import_labels(connection: sqlite3.Connection, shp_path: Path) -> int:
    reader = reader_for(shp_path)
    fields = [field[0] for field in reader.fields[1:]]
    field_indexes = {name: fields.index(name) for name in ("LABEL", "VISIBLE")}
    angle_index = fields.index("ANGLE") if "ANGLE" in fields else None
    size_index = fields.index("SIZE") if "SIZE" in fields else None
    imported = 0
    for shape_record in reader.iterShapeRecords():
        record = shape_record.record
        if int(record[field_indexes["VISIBLE"]] or 0) != 1:
            continue
        label = str(record[field_indexes["LABEL"]] or "").strip()
        if not label:
            continue
        x, y = shape_record.shape.points[0]
        lng, lat = TRANSFORMER.transform(x, y)
        imported += 1
        connection.execute(
            """
            INSERT INTO parcel_labels(id, label, lng, lat, angle, size)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                imported,
                label,
                round(lng, 8),
                round(lat, 8),
                record[angle_index] if angle_index is not None else None,
                record[size_index] if size_index is not None else None,
            ),
        )
        connection.execute(
            """
            INSERT INTO parcel_labels_rtree(id, min_lng, max_lng, min_lat, max_lat)
            VALUES (?, ?, ?, ?, ?)
            """,
            (imported, lng, lng, lat, lat),
        )
    return imported


def import_line_layer(
    connection: sqlite3.Connection,
    shp_path: Path,
    table_name: str,
    rtree_name: str,
) -> int:
    reader = reader_for(shp_path)
    fields = [field[0] for field in reader.fields[1:]]
    visible_index = fields.index("VISIBLE") if "VISIBLE" in fields else None
    imported = 0
    for shape_record in reader.iterShapeRecords():
        if visible_index is not None:
            if int(shape_record.record[visible_index] or 0) != 1:
                continue
        geometry = transform_geometry(shape_record.shape)
        min_lng, min_lat, max_lng, max_lat = geometry_bbox(geometry)
        imported += 1
        connection.execute(
            f"INSERT INTO {table_name}(id, geometry) VALUES (?, ?)",
            (imported, json_compact(geometry)),
        )
        connection.execute(
            f"""
            INSERT INTO {rtree_name}(id, min_lng, max_lng, min_lat, max_lat)
            VALUES (?, ?, ?, ?, ?)
            """,
            (imported, min_lng, max_lng, min_lat, max_lat),
        )
    return imported


def import_oaza_boundaries(connection: sqlite3.Connection, shp_path: Path) -> int:
    reader = reader_for(shp_path)
    fields = [field[0] for field in reader.fields[1:]]
    name_index = fields.index("NAME") if "NAME" in fields else None
    imported = 0
    for shape_record in reader.iterShapeRecords():
        geometry = transform_geometry(shape_record.shape)
        min_lng, min_lat, max_lng, max_lat = geometry_bbox(geometry)
        imported += 1
        name = (
            str(shape_record.record[name_index] or "").strip()
            if name_index is not None
            else ""
        )
        connection.execute(
            "INSERT INTO oaza_boundaries(id, name, geometry) VALUES (?, ?, ?)",
            (imported, name, json_compact(geometry)),
        )
        connection.execute(
            """
            INSERT INTO oaza_boundaries_rtree(
                id, min_lng, max_lng, min_lat, max_lat
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (imported, min_lng, max_lng, min_lat, max_lat),
        )
    return imported


def store_manifest(
    connection: sqlite3.Connection,
    source_manifest: dict[str, dict[str, str]],
    counts: dict[str, int],
    coverage_bbox: tuple[float, float, float, float],
) -> None:
    values = {
        "source_date": SOURCE_DATE,
        "source_page": SOURCE_PAGE,
        "terms_url": TERMS_URL,
        "license": "CC BY 4.0",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_files": json_compact(source_manifest),
        "counts": json_compact(counts),
        "source_crs": "EPSG:2448",
        "output_crs": "EPSG:4326",
        "coverage_bbox": json_compact(coverage_bbox),
    }
    connection.executemany(
        "INSERT INTO dataset_manifest(key, value) VALUES (?, ?)",
        values.items(),
    )


def build_database(output: Path, cache_dir: Path, force_download: bool) -> None:
    source_manifest = download_sources(cache_dir, force_download)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gojo-cadastral-build-") as temp_name:
        work_dir = Path(temp_name)
        extracted = extract_sources(cache_dir, work_dir)
        temp_output = work_dir / "gojo_chiban.sqlite"
        connection = sqlite3.connect(temp_output)
        try:
            create_schema(connection)
            counts = {
                "parcels": import_parcels(
                    connection, find_one(extracted["polygon"], "筆ポリゴン.shp")
                ),
                "labels": import_labels(
                    connection, find_one(extracted["chiban"], "地番.shp")
                ),
                "leader_lines": import_line_layer(
                    connection,
                    find_one(extracted["leaders"], "地番引出線.shp"),
                    "leader_lines",
                    "leader_lines_rtree",
                ),
                "oaza_boundaries": import_oaza_boundaries(
                    connection, find_one(extracted["boundary"], "大字界.shp")
                ),
            }
            coverage_row = connection.execute(
                """
                SELECT MIN(min_lng), MIN(min_lat), MAX(max_lng), MAX(max_lat)
                FROM parcels_rtree
                """
            ).fetchone()
            coverage_bbox = tuple(float(value) for value in coverage_row)
            store_manifest(
                connection,
                source_manifest,
                counts,
                coverage_bbox,
            )
            connection.commit()
            connection.execute("ANALYZE")
            connection.execute("VACUUM")
        finally:
            connection.close()
        temp_output.replace(output)

    print(f"output: {output.resolve()}")
    print(f"sha256: {sha256_file(output)}")
    print(f"bytes: {output.stat().st_size}")


def main() -> None:
    args = parse_args()
    build_database(args.output, args.cache_dir, args.force_download)


if __name__ == "__main__":
    main()
