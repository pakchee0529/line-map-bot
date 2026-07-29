'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { DatabaseSync } = require('node:sqlite');

const MIN_ZOOM = 17;
const MAX_ZOOM = 22;
const MAX_BBOX_SPAN = 0.08;

function ensureBundledDatabase(rootDir, configuredPath) {
  const databasePath = configuredPath || path.join(rootDir, 'data', 'cadastral', 'gojo_chiban.sqlite');
  if (fs.existsSync(databasePath)) return databasePath;
  const bundlePath = path.join(rootDir, 'data', 'cadastral', 'gojo_chiban.sqlite.gz');
  if (!fs.existsSync(bundlePath)) return databasePath;
  fs.mkdirSync(path.dirname(databasePath), { recursive: true });
  const temporaryPath = `${databasePath}.tmp`;
  fs.writeFileSync(temporaryPath, zlib.gunzipSync(fs.readFileSync(bundlePath)));
  fs.renameSync(temporaryPath, databasePath);
  return databasePath;
}

class CadastralStore {
  constructor(databasePath, maxFeatures = 2500) {
    this.databasePath = databasePath;
    this.maxFeatures = Math.max(100, Number(maxFeatures) || 2500);
  }

  get available() {
    return fs.existsSync(this.databasePath);
  }

  connect() {
    if (!this.available) throw new Error('cadastral dataset is unavailable');
    return new DatabaseSync(this.databasePath, { readOnly: true });
  }

  manifest() {
    const database = this.connect();
    try {
      return Object.fromEntries(
        database.prepare('SELECT key, value FROM dataset_manifest ORDER BY key').all()
          .map((row) => [String(row.key), String(row.value)]),
      );
    } finally {
      database.close();
    }
  }

  validate(bbox, zoom) {
    if (!Array.isArray(bbox) || bbox.length !== 4 || bbox.some((value) => !Number.isFinite(value))) {
      throw new RangeError('invalid bbox');
    }
    const [west, south, east, north] = bbox;
    if (!(west >= -180 && west < east && east <= 180
      && south >= -90 && south < north && north <= 90)) {
      throw new RangeError('invalid bbox');
    }
    if (east - west > MAX_BBOX_SPAN || north - south > MAX_BBOX_SPAN) {
      throw new RangeError('bbox is too large');
    }
    if (!Number.isInteger(zoom) || zoom < MIN_ZOOM || zoom > MAX_ZOOM) {
      throw new RangeError('unsupported zoom');
    }
  }

  query(bbox, zoom) {
    this.validate(bbox, zoom);
    const [west, south, east, north] = bbox;
    const database = this.connect();
    const features = [];
    let truncated = false;
    const remaining = () => Math.max(0, this.maxFeatures - features.length);
    const params = [west, east, south, north];

    try {
      let rows = database.prepare(`
        SELECT parcel.id, parcel.geometry
        FROM parcels AS parcel
        JOIN parcels_rtree AS bounds ON bounds.id = parcel.id
        WHERE bounds.max_lng >= ?
          AND bounds.min_lng <= ?
          AND bounds.max_lat >= ?
          AND bounds.min_lat <= ?
        LIMIT ?
      `).all(...params, remaining() + 1);
      if (rows.length > remaining()) {
        truncated = true;
        rows = rows.slice(0, remaining());
      }
      for (const row of rows) {
        features.push({
          type: 'Feature',
          id: `parcel-${row.id}`,
          properties: { layer: 'parcel' },
          geometry: JSON.parse(row.geometry),
        });
      }

      if (zoom >= 18 && remaining() > 0) {
        rows = database.prepare(`
          SELECT label.id, label.label, label.lng, label.lat, label.angle, label.size
          FROM parcel_labels AS label
          JOIN parcel_labels_rtree AS bounds ON bounds.id = label.id
          WHERE bounds.max_lng >= ?
            AND bounds.min_lng <= ?
            AND bounds.max_lat >= ?
            AND bounds.min_lat <= ?
          LIMIT ?
        `).all(...params, remaining() + 1);
        if (rows.length > remaining()) {
          truncated = true;
          rows = rows.slice(0, remaining());
        }
        for (const row of rows) {
          features.push({
            type: 'Feature',
            id: `label-${row.id}`,
            properties: {
              layer: 'label',
              label: row.label,
              angle: row.angle,
              size: row.size,
            },
            geometry: {
              type: 'Point',
              coordinates: [row.lng, row.lat],
            },
          });
        }
      }

      if (zoom >= 19 && remaining() > 0) {
        rows = database.prepare(`
          SELECT line.id, line.geometry
          FROM leader_lines AS line
          JOIN leader_lines_rtree AS bounds ON bounds.id = line.id
          WHERE bounds.max_lng >= ?
            AND bounds.min_lng <= ?
            AND bounds.max_lat >= ?
            AND bounds.min_lat <= ?
          LIMIT ?
        `).all(...params, remaining() + 1);
        if (rows.length > remaining()) {
          truncated = true;
          rows = rows.slice(0, remaining());
        }
        for (const row of rows) {
          features.push({
            type: 'Feature',
            id: `leader-${row.id}`,
            properties: { layer: 'leader' },
            geometry: JSON.parse(row.geometry),
          });
        }
      }

      const manifest = Object.fromEntries(
        database.prepare(`
          SELECT key, value
          FROM dataset_manifest
          WHERE key IN ('source_date', 'license', 'coverage_bbox')
        `).all().map((row) => [String(row.key), String(row.value)]),
      );
      let outsideCoverage = false;
      try {
        const [cw, cs, ce, cn] = JSON.parse(manifest.coverage_bbox || '[]').map(Number);
        outsideCoverage = east < cw || west > ce || north < cs || south > cn;
      } catch {
        outsideCoverage = false;
      }
      return {
        type: 'FeatureCollection',
        features,
        metadata: {
          source_date: manifest.source_date || '',
          license: manifest.license || 'CC BY 4.0',
          truncated,
          outside_coverage: outsideCoverage,
        },
      };
    } finally {
      database.close();
    }
  }
}

module.exports = { CadastralStore, ensureBundledDatabase };
