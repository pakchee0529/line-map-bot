'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const sharp = require('sharp');
const {
  HEIGHT,
  WIDTH,
  parsePreviewPoints,
  renderMapPreview,
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
