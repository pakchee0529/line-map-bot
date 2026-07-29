'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { app, buildSearchReply, buildSearchResponse } = require('../server');

test('LINE reply includes two-point public map for a span', () => {
  const reply = buildSearchReply('木ノ原40E1S3～木ノ原40E1S4');
  assert.match(reply, /2点地図:/);
  assert.match(reply, /\/multi-map\?/);
});

test('two-point search builds a Flex-ready card with a map preview', () => {
  const response = buildSearchResponse('木ノ原40E1S3～木ノ原40E1S4');
  assert.equal(response.cards.length, 1);
  assert.equal(response.cards[0].status, 'found');
  assert.equal(response.cards[0].rows.length, 2);
  assert.match(response.cards[0].primaryUrl, /\/multi-map\?/);
  assert.match(response.cards[0].previewUrl, /\/api\/map-preview\?/);
  assert.match(response.cards[0].previewUrl, /connect=1/);
});

test('single pole Flex card keeps its nearby 200m context', () => {
  const response = buildSearchResponse('木ノ原40E1S3');
  assert.equal(response.cards.length, 1);
  assert.equal(response.cards[0].status, 'found');
  assert.match(response.cards[0].primaryUrl, /\/map\?lat=/);
  assert.equal(response.cards[0].primaryLabel, '近くの電柱を見る');
  assert.match(response.cards[0].secondaryUrl, /google\.com\/maps/);
  assert.equal(response.cards[0].secondaryLabel, 'Googleマップで地点確認');
  assert.ok(response.cards[0].rows.some((row) => row.label === '近隣電柱'));
  assert.match(response.cards[0].previewUrl, /%7C/);
  assert.doesNotMatch(response.cards[0].previewUrl, /connect=1/);
});

test('place-name preview uses independent pins without a fabricated route', () => {
  const response = buildSearchResponse('木ノ原');
  assert.equal(response.cards.length, 1);
  assert.equal(response.cards[0].status, 'place');
  assert.doesNotMatch(response.cards[0].previewUrl, /connect=1/);
});

test('unknown input keeps candidate guidance in a Flex-ready card', () => {
  const response = buildSearchResponse('木ノ原99999');
  assert.equal(response.cards.length, 1);
  assert.equal(response.cards[0].status, 'unresolved');
  assert.ok(response.cards[0].suggestionText);
  assert.match(response.plainText, /候補:/);
});

test('multi-line search reserves the final carousel card for a combined map', () => {
  const inputs = Array.from({ length: 14 }, (_, index) => `木ノ原${40 + index}`).join('\n');
  const response = buildSearchResponse(inputs);
  assert.equal(response.cards.length, 12);
  assert.equal(response.cards.at(-1).status, 'summary');
  assert.match(response.cards.at(-1).primaryUrl, /\/multi-map\?id=/);
});

test('public health and two-point map routes render', async (context) => {
  const server = app.listen(0);
  context.after(() => server.close());
  await new Promise((resolve) => server.once('listening', resolve));
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}`;

  const health = await fetch(`${base}/healthz/search`);
  assert.equal(health.status, 200);
  const payload = await health.json();
  assert.equal(payload.search_engine, 'node-pc-core-v2');
  assert.equal(payload.flex_reply_enabled, true);
  assert.ok(payload.gps_count > 100000);

  const sample = await fetch(`${base}/healthz/search/sample`);
  assert.equal(sample.status, 200);
  assert.deepEqual(await sample.json(), {
    found: true,
    span_point_count: 2,
    adopted: '木ノ原40E1S4',
  });

  const map = await fetch(
    `${base}/multi-map?p1n=A&p1=34.35771,135.6636&p2n=B&p2=34.3575,135.66363`,
  );
  assert.equal(map.status, 200);
  assert.match(await map.text(), /cadastral-toggle/);

  const preview = await fetch(
    `${base}/api/map-preview?points=34.35771%2C135.6636%7C34.3575%2C135.66363`,
  );
  assert.equal(preview.status, 200);
  assert.equal(preview.headers.get('content-type'), 'image/png');
  assert.ok((await preview.arrayBuffer()).byteLength > 1000);
});
