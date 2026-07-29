from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path


class CadastralError(RuntimeError):
    pass


class CadastralQueryError(ValueError):
    pass


class CadastralStore:
    MIN_ZOOM = 17
    MAX_ZOOM = 22
    MAX_BBOX_SPAN = 0.08

    def __init__(self, database_path: Path, max_features: int = 2500):
        self.database_path = Path(database_path)
        self.max_features = max(100, int(max_features))

    @property
    def available(self) -> bool:
        return self.database_path.is_file()

    def _connect(self) -> sqlite3.Connection:
        if not self.available:
            raise CadastralError("cadastral dataset is not available")
        uri = self.database_path.resolve().as_uri() + "?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def manifest(self) -> dict[str, str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT key, value FROM dataset_manifest ORDER BY key"
            ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def _validate(
        self, bbox: tuple[float, float, float, float], zoom: int
    ) -> tuple[float, float, float, float]:
        west, south, east, north = bbox
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise CadastralQueryError("invalid bbox")
        if east - west > self.MAX_BBOX_SPAN or north - south > self.MAX_BBOX_SPAN:
            raise CadastralQueryError("bbox is too large")
        if not self.MIN_ZOOM <= zoom <= self.MAX_ZOOM:
            raise CadastralQueryError("zoom is outside the supported range")
        return west, south, east, north

    def query(
        self, bbox: tuple[float, float, float, float], zoom: int
    ) -> dict:
        west, south, east, north = self._validate(bbox, zoom)
        params = (west, east, south, north)
        features: list[dict] = []
        truncated = False

        def remaining() -> int:
            return max(0, self.max_features - len(features))

        with closing(self._connect()) as connection:
            parcel_limit = remaining() + 1
            parcel_rows = connection.execute(
                f"""
                SELECT parcel.id, parcel.geometry
                FROM parcels AS parcel
                JOIN parcels_rtree AS bounds ON bounds.id = parcel.id
                WHERE bounds.max_lng >= ?
                  AND bounds.min_lng <= ?
                  AND bounds.max_lat >= ?
                  AND bounds.min_lat <= ?
                LIMIT ?
                """,
                (*params, parcel_limit),
            ).fetchall()
            if len(parcel_rows) > remaining():
                truncated = True
                parcel_rows = parcel_rows[: remaining()]
            for row in parcel_rows:
                features.append(
                    {
                        "type": "Feature",
                        "id": f"parcel-{row['id']}",
                        "properties": {"layer": "parcel"},
                        "geometry": json.loads(row["geometry"]),
                    }
                )

            if zoom >= 18 and remaining() > 0:
                label_limit = remaining() + 1
                label_rows = connection.execute(
                    """
                    SELECT label.id, label.label, label.lng, label.lat,
                           label.angle, label.size
                    FROM parcel_labels AS label
                    JOIN parcel_labels_rtree AS bounds ON bounds.id = label.id
                    WHERE bounds.max_lng >= ?
                      AND bounds.min_lng <= ?
                      AND bounds.max_lat >= ?
                      AND bounds.min_lat <= ?
                    LIMIT ?
                    """,
                    (*params, label_limit),
                ).fetchall()
                if len(label_rows) > remaining():
                    truncated = True
                    label_rows = label_rows[: remaining()]
                for row in label_rows:
                    features.append(
                        {
                            "type": "Feature",
                            "id": f"label-{row['id']}",
                            "properties": {
                                "layer": "label",
                                "label": row["label"],
                                "angle": row["angle"],
                                "size": row["size"],
                            },
                            "geometry": {
                                "type": "Point",
                                "coordinates": [row["lng"], row["lat"]],
                            },
                        }
                    )

            if zoom >= 19 and remaining() > 0:
                line_limit = remaining() + 1
                line_rows = connection.execute(
                    """
                    SELECT line.id, line.geometry
                    FROM leader_lines AS line
                    JOIN leader_lines_rtree AS bounds ON bounds.id = line.id
                    WHERE bounds.max_lng >= ?
                      AND bounds.min_lng <= ?
                      AND bounds.max_lat >= ?
                      AND bounds.min_lat <= ?
                    LIMIT ?
                    """,
                    (*params, line_limit),
                ).fetchall()
                if len(line_rows) > remaining():
                    truncated = True
                    line_rows = line_rows[: remaining()]
                for row in line_rows:
                    features.append(
                        {
                            "type": "Feature",
                            "id": f"leader-{row['id']}",
                            "properties": {"layer": "leader"},
                            "geometry": json.loads(row["geometry"]),
                        }
                    )

            manifest_rows = connection.execute(
                """
                SELECT key, value
                FROM dataset_manifest
                WHERE key IN ('source_date', 'license', 'coverage_bbox')
                """
            ).fetchall()

        manifest = {
            str(row["key"]): str(row["value"]) for row in manifest_rows
        }
        outside_coverage = False
        try:
            coverage_west, coverage_south, coverage_east, coverage_north = (
                float(value)
                for value in json.loads(manifest.get("coverage_bbox", "[]"))
            )
            outside_coverage = (
                east < coverage_west
                or west > coverage_east
                or north < coverage_south
                or south > coverage_north
            )
        except (TypeError, ValueError):
            outside_coverage = False
        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "source_date": manifest.get("source_date", ""),
                "license": manifest.get("license", "CC BY 4.0"),
                "truncated": truncated,
                "outside_coverage": outside_coverage,
            },
        }
