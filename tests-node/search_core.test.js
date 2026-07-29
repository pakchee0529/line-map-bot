'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const {
  findPlacePoints,
  loadPoleData,
  resolveOne,
} = require('../node_search_core');

const raw = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'GPS.json'), 'utf8'),
);
const { poleCoords, gpsPoints } = loadPoleData(raw);

test('full-width range resolves to two actual poles', () => {
  const result = resolveOne('木ノ原40E1S3～木ノ原40E1S4', poleCoords);
  assert.equal(result.found, true);
  assert.equal(result.spanPoints.length, 2);
  assert.deepEqual(
    result.spanPoints.map((item) => item.adopted),
    ['木ノ原40E1S3', '木ノ原40E1S4'],
  );
});

test('abbreviated rear endpoint inherits the front prefix', () => {
  const result = resolveOne('木ノ原40E1S3～S4', poleCoords);
  assert.equal(result.found, true);
  assert.equal(result.spanPoints.length, 2);
  assert.equal(result.spanPoints[1].adopted, '木ノ原40E1S4');
});

test('place-name search collects all poles for the place', () => {
  const points = findPlacePoints('木ノ原', gpsPoints);
  assert.ok(points.length > 2);
  assert.ok(points.every((point) => point.name.startsWith('木ノ原')));
});

test('unknown input returns suggestions instead of throwing', () => {
  const result = resolveOne('木ノ原40E1S99', poleCoords);
  assert.equal(typeof result.found, 'boolean');
  assert.ok(Array.isArray(result.suggestionDetails));
});
