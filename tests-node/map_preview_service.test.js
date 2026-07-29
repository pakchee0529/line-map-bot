'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const sharp = require('sharp');
const {
  DEFAULT_TILE_SOURCE,
  HEIGHT,
  TILE_SOURCE_GSI_AERIAL,
  TILE_SOURCE_OSM,
  WIDTH,
  nearbyCadastralLabelKeys,
  normalizeTileSource,
  parsePreviewPoints,
  renderMapPreview,
  previewGeometry,
  serializePreviewPoints,
} = require('../map_preview_service');

test('preview points round-trip without names or secrets', () => {
  const encoded = serializePreviewPoints([
    { lat: 34.35771, lng: 135.6636 },
    { lat: 34.3575, lng: 135.66363 },
  ]);
  assert.equal(encoded, '34.357710,135.663600|34.357500,135.663630');
  assert.deepEqual(parsePreviewPoints(encoded), [
    { lat: 34.35771, lng: 135.6636 },
    { lat: 34.3575, lng: 135.66363 },
  ]);
});

test('renders a valid offline fallback PNG for a two-point span', async () => {
  const buffer = await renderMapPreview([
    { lat: 34.35771, lng: 135.6636 },
    { lat: 34.3575, lng: 135.66363 },
  ], { useTiles: false, connectPoints: true });
  const metadata = await sharp(buffer).metadata();
  assert.equal(metadata.format, 'png');
  assert.equal(metadata.width, WIDTH);
  assert.equal(metadata.height, HEIGHT);
  assert.ok(buffer.length > 1000);
});

test('renders a cadastral polygon overlay without changing output dimensions', async () => {
  const points = [
    { lat: 34.35771, lng: 135.6636 },
    { lat: 34.3575, lng: 135.66363 },
  ];
  const cadastral = {
    type: 'FeatureCollection',
    metadata: { source_date: 'test' },
    features: [{
      type: 'Feature',
      properties: { layer: 'parcel' },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [135.6634, 34.3574],
          [135.6638, 34.3574],
          [135.6638, 34.3578],
          [135.6634, 34.3578],
          [135.6634, 34.3574],
        ]],
      },
    }],
  };
  const buffer = await renderMapPreview(points, { useTiles: false, cadastral });
  const metadata = await sharp(buffer).metadata();
  assert.equal(metadata.width, WIDTH);
  assert.equal(metadata.height, HEIGHT);
  assert.ok(buffer.length > 1000);
});

test('aerial imagery is default while OSM remains selectable', () => {
  assert.equal(DEFAULT_TILE_SOURCE, TILE_SOURCE_GSI_AERIAL);
  assert.equal(normalizeTileSource('osm'), TILE_SOURCE_OSM);
  assert.equal(normalizeTileSource('unknown'), TILE_SOURCE_GSI_AERIAL);
});

test('cadastral labels are limited to the nearest label per endpoint', () => {
  const points = [
    { lat: 34.35771, lng: 135.6636 },
    { lat: 34.3575, lng: 135.66363 },
  ];
  const features = [
    {
      id: 'near-young',
      properties: { layer: 'label', label: '358' },
      geometry: { type: 'Point', coordinates: [135.66359, 34.35772] },
    },
    {
      id: 'near-old',
      properties: { layer: 'label', label: '372' },
      geometry: { type: 'Point', coordinates: [135.66364, 34.35749] },
    },
    {
      id: 'extra',
      properties: { layer: 'label', label: '999' },
      geometry: { type: 'Point', coordinates: [135.6645, 34.3585] },
    },
  ];
  assert.deepEqual(
    [...nearbyCadastralLabelKeys(features, previewGeometry(points))].sort(),
    ['near-old', 'near-young'],
  );
});

test('aerial tile failure falls back to OSM tiles', async () => {
  const originalFetch = global.fetch;
  const requestedUrls = [];
  const tile = await sharp({
    create: {
      width: 256,
      height: 256,
      channels: 3,
      background: 'white',
    },
  }).png().toBuffer();
  global.fetch = async (url) => {
    requestedUrls.push(String(url));
    const ok = String(url).includes('tile.openstreetmap.org');
    return {
      ok,
      arrayBuffer: async () => tile.buffer.slice(
        tile.byteOffset,
        tile.byteOffset + tile.byteLength,
      ),
    };
  };
  try {
    const buffer = await renderMapPreview(
      [{ lat: 34.123456, lng: 135.654321 }],
      { tileSource: TILE_SOURCE_GSI_AERIAL },
    );
    assert.ok(buffer.length > 1000);
  } finally {
    global.fetch = originalFetch;
  }
  assert.ok(requestedUrls.some((url) => url.includes('cyberjapandata.gsi.go.jp')));
  assert.ok(requestedUrls.some((url) => url.includes('tile.openstreetmap.org')));
});
