import json
import sqlite3
from pathlib import Path


def create_cadastral_fixture(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
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
    connection.executemany(
        "INSERT INTO dataset_manifest(key, value) VALUES (?, ?)",
        [
            ("source_date", "2026-01-01"),
            ("license", "CC BY 4.0"),
            (
                "coverage_bbox",
                "[135.6630,34.3570,135.6640,34.3580]",
            ),
        ],
    )
    parcel_geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [135.6630, 34.3570],
                [135.6640, 34.3570],
                [135.6640, 34.3580],
                [135.6630, 34.3580],
                [135.6630, 34.3570],
            ]
        ],
    }
    connection.execute(
        "INSERT INTO parcels(id, geometry) VALUES (?, ?)",
        (1, json.dumps(parcel_geometry)),
    )
    connection.execute(
        """
        INSERT INTO parcels_rtree(id, min_lng, max_lng, min_lat, max_lat)
        VALUES (1, 135.6630, 135.6640, 34.3570, 34.3580)
        """
    )
    connection.execute(
        """
        INSERT INTO parcel_labels(id, label, lng, lat, angle, size)
        VALUES (1, '123-4', 135.6635, 34.3575, 0, 1)
        """
    )
    connection.execute(
        """
        INSERT INTO parcel_labels_rtree(id, min_lng, max_lng, min_lat, max_lat)
        VALUES (1, 135.6635, 135.6635, 34.3575, 34.3575)
        """
    )
    line_geometry = {
        "type": "LineString",
        "coordinates": [[135.6634, 34.3574], [135.6635, 34.3575]],
    }
    connection.execute(
        "INSERT INTO leader_lines(id, geometry) VALUES (?, ?)",
        (1, json.dumps(line_geometry)),
    )
    connection.execute(
        """
        INSERT INTO leader_lines_rtree(id, min_lng, max_lng, min_lat, max_lat)
        VALUES (1, 135.6634, 135.6635, 34.3574, 34.3575)
        """
    )
    connection.commit()
    connection.close()
    return path
