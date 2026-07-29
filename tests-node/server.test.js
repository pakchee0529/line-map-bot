'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { app, buildSearchReply } = require('../server');

test('LINE reply includes two-point public map for a span', () => {
  const reply = buildSearchReply('木ノ原40E1S3～木ノ原40E1S4');
  assert.match(reply, /2点地図:/);
  assert.match(reply, /\/multi-map\?/);
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
});
