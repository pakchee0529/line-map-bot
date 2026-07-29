'use strict';

const crypto = require('crypto');
const express = require('express');
const fs = require('fs');
const line = require('@line/bot-sdk');
const nunjucks = require('nunjucks');
const path = require('path');

const {
  findPlacePoints,
  loadPoleData,
  parsePoleName,
  resolveOne,
  splitInputLines,
} = require('./node_search_core');
const {
  CadastralStore,
  ensureBundledDatabase,
} = require('./node_cadastral_store');
const { buildFlexMessage } = require('./line_flex_builder');
const {
  parsePreviewPoints,
  previewBounds,
  renderMapPreview,
  serializePreviewPoints,
} = require('./map_preview_service');

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 3000);
const BASE_URL = String(process.env.BASE_URL || 'https://line-map-bot.onrender.com')
  .replace(/\/+$/, '');
const SEARCH_ENGINE_VERSION = 'node-pc-core-v2';
const MULTI_MAP_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const FLEX_REPLY_ENABLED = String(
  process.env.LINE_FLEX_REPLY_ENABLED ?? 'true',
).toLowerCase() !== 'false';
const MAP_PREVIEW_TILES_ENABLED = String(
  process.env.MAP_PREVIEW_TILES_ENABLED ?? 'true',
).toLowerCase() !== 'false';

const config = {
  channelAccessToken: process.env.LINE_CHANNEL_ACCESS_TOKEN || '',
  channelSecret: process.env.LINE_CHANNEL_SECRET || '',
};
const client = config.channelAccessToken ? new line.Client(config) : null;
const app = express();

const templateEnvironment = nunjucks.configure(path.join(ROOT, 'templates'), {
  autoescape: true,
  express: app,
});
templateEnvironment.addFilter('tojson', (value) => JSON.stringify(value));
templateEnvironment.addGlobal('url_for', (name) => (
  name === 'cadastral_features' ? '/api/cadastral/features' : '/'
));

const gpsPath = path.join(ROOT, 'GPS.json');
const gpsBytes = fs.readFileSync(gpsPath);
const gpsRaw = JSON.parse(gpsBytes.toString('utf8'));
const { poleCoords, gpsPoints } = loadPoleData(gpsRaw);
const gpsSha256 = crypto.createHash('sha256').update(gpsBytes).digest('hex');

const cadastralPath = ensureBundledDatabase(
  ROOT,
  process.env.CADASTRAL_DATA_PATH || '',
);
const cadastralStore = new CadastralStore(
  cadastralPath,
  Number(process.env.CADASTRAL_MAX_FEATURES || 2500),
);
const cadastralEnabled = String(
  process.env.CADASTRAL_LAYER_ENABLED ?? cadastralStore.available,
).toLowerCase() !== 'false';

const multiMaps = new Map();

function parseLatLng(value) {
  const match = String(value || '').trim().match(
    /^(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)$/,
  );
  if (!match) return null;
  const lat = Number(match[1]);
  const lng = Number(match[2]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
  return { lat, lng };
}

function distanceMeters(lat1, lng1, lat2, lng2) {
  const radius = 6371000;
  const radians = (degree) => degree * Math.PI / 180;
  const dLat = radians(lat2 - lat1);
  const dLng = radians(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(radians(lat1)) * Math.cos(radians(lat2))
    * Math.sin(dLng / 2) ** 2;
  return radius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function findNearby(lat, lng, radius = 200) {
  return gpsPoints
    .map((point) => ({
      name: point.name,
      lat: point.lat,
      lng: point.lng,
      distance: distanceMeters(lat, lng, point.lat, point.lng),
    }))
    .filter((point) => point.distance <= radius)
    .sort((left, right) => left.distance - right.distance);
}

function coordinatesFor(name) {
  const value = poleCoords.get(name);
  if (!value) return null;
  const parsed = parseLatLng(value);
  return parsed ? { name, ...parsed } : null;
}

function googleMapsUrl(point) {
  return `https://www.google.com/maps?q=${point.lat},${point.lng}`;
}

function twoPointMapUrl(result) {
  if (!result || result.spanPoints.length !== 2) return '';
  const points = result.spanPoints
    .map((item) => coordinatesFor(item.adopted))
    .filter(Boolean);
  if (points.length !== 2) return '';
  const params = new URLSearchParams({
    p1n: points[0].name,
    p1: `${points[0].lat},${points[0].lng}`,
    p2n: points[1].name,
    p2: `${points[1].lat},${points[1].lng}`,
    sn: result.displayName,
  });
  return `${BASE_URL}/multi-map?${params}`;
}

function storeMultiMap(points) {
  const now = Date.now();
  for (const [id, entry] of multiMaps) {
    if (entry.expiresAt <= now) multiMaps.delete(id);
  }
  const id = crypto.randomUUID().replace(/-/g, '');
  multiMaps.set(id, { points, expiresAt: now + MULTI_MAP_TTL_MS });
  return `${BASE_URL}/multi-map?id=${id}`;
}

function mapPreviewUrl(points, { connectPoints = false } = {}) {
  const serialized = serializePreviewPoints(points);
  if (!serialized) return '';
  const params = new URLSearchParams({ points: serialized });
  if (connectPoints) params.set('connect', '1');
  return `${BASE_URL}/api/map-preview?${params}`;
}

function uniquePoints(results) {
  const output = [];
  const seen = new Set();
  for (const result of results) {
    const names = result.spanPoints.length
      ? result.spanPoints.map((item) => item.adopted)
      : [result.adopted];
    for (const name of names) {
      const point = coordinatesFor(name);
      if (!point) continue;
      const identity = `${point.name}:${point.lat}:${point.lng}`;
      if (seen.has(identity)) continue;
      seen.add(identity);
      output.push(point);
    }
  }
  return output;
}

function resultPoints(result) {
  const names = result.spanPoints.length
    ? result.spanPoints.map((item) => item.adopted)
    : [result.adopted];
  return names.map(coordinatesFor).filter(Boolean);
}

function formatResult(result) {
  const lines = [result.displayName];
  if (result.found) {
    const point = coordinatesFor(result.adopted);
    if (point) lines.push(googleMapsUrl(point));
    const spanUrl = twoPointMapUrl(result);
    if (spanUrl) lines.push(`2点地図: ${spanUrl}`);
  } else {
    lines.push('該当する電柱を特定できませんでした。');
  }
  if (result.candidateNotes.length) {
    lines.push(`補正: ${result.candidateNotes.join(' / ')}`);
  }
  if (result.warnings.length) {
    lines.push(`注意: ${result.warnings.join(' / ')}`);
  }
  if (!result.found && result.suggestionDetails.length) {
    lines.push(
      `候補: ${result.suggestionDetails.slice(0, 5).map((item) => item.name).join('、')}`,
    );
  }
  return lines.join('\n');
}

function cardForSearchResult(result) {
  const points = resultPoints(result);
  const spanUrl = twoPointMapUrl(result);
  const primaryPoint = points[points.length - 1] || null;
  let status = 'found';
  if (!result.found) {
    status = 'unresolved';
  } else if (result.isRange && result.spanPoints.length < 2) {
    status = 'partial';
  } else if (result.candidateNotes.length) {
    status = 'corrected';
  }
  const rows = result.spanPoints.length
    ? result.spanPoints.map((item) => ({
      label: `${item.role}番`,
      value: item.adopted,
    }))
    : (result.adopted ? [{ label: '採用地点', value: result.adopted }] : []);
  return {
    status,
    title: result.displayName,
    rows,
    notes: result.candidateNotes,
    warnings: result.warnings,
    primaryUrl: spanUrl || (primaryPoint ? googleMapsUrl(primaryPoint) : ''),
    primaryLabel: spanUrl ? '2点地図・地番図を開く' : 'Googleマップを開く',
    secondaryUrl: spanUrl && primaryPoint ? googleMapsUrl(primaryPoint) : '',
    secondaryLabel: '老番側をGoogleマップで開く',
    previewUrl: points.length
      ? mapPreviewUrl(points, { connectPoints: Boolean(spanUrl) })
      : '',
    suggestionText: !result.found && result.suggestionDetails.length
      ? result.suggestionDetails[0].name
      : '',
  };
}

function buildSearchResponse(rawText) {
  const lines = splitInputLines(rawText);
  if (!lines.length) {
    return {
      plainText: '電柱名または径間名を入力してください。',
      cards: [],
    };
  }

  if (lines.length === 1) {
    const latLng = parseLatLng(lines[0]);
    if (latLng) {
      const nearby = findNearby(latLng.lat, latLng.lng);
      const mapUrl = `${BASE_URL}/map?lat=${latLng.lat}&lng=${latLng.lng}`;
      const plainText = `周辺200mの電柱: ${nearby.length}件\n${mapUrl}`;
      return {
        plainText,
        cards: [{
          status: 'nearby',
          title: '半径200mの電柱',
          rows: [{ label: '検索結果', value: `${nearby.length}件` }],
          primaryUrl: mapUrl,
          primaryLabel: '周辺地図を開く',
          previewUrl: mapPreviewUrl([{ lat: latLng.lat, lng: latLng.lng }, ...nearby]),
        }],
      };
    }

    const parsed = parsePoleName(lines[0]);
    if (!parsed) {
      const placePoints = findPlacePoints(lines[0], gpsPoints);
      if (placePoints.length) {
        const mapUrl = storeMultiMap(placePoints);
        const plainText = `${lines[0]}: ${placePoints.length}件\n${mapUrl}`;
        return {
          plainText,
          cards: [{
            status: 'place',
            title: lines[0],
            rows: [{ label: '登録電柱', value: `${placePoints.length}件` }],
            primaryUrl: mapUrl,
            primaryLabel: '冠称名の地図を開く',
            previewUrl: mapPreviewUrl(placePoints),
          }],
        };
      }
    }
  }

  const results = lines.map((input) => resolveOne(input, poleCoords));
  const blocks = results.map(formatResult);
  const cards = results.map(cardForSearchResult);
  if (results.length > 1) {
    const points = uniquePoints(results);
    if (points.length) {
      const mapUrl = storeMultiMap(points);
      blocks.push(`まとめて地図: ${mapUrl}`);
      const summaryCard = {
        status: 'summary',
        title: '検索結果をまとめて表示',
        rows: [
          { label: '入力', value: `${results.length}件` },
          { label: '地図点', value: `${points.length}件` },
        ],
        primaryUrl: mapUrl,
        primaryLabel: 'まとめて地図を開く',
        previewUrl: mapPreviewUrl(points),
      };
      if (cards.length >= 12) cards.splice(11);
      cards.push(summaryCard);
    }
  }
  return {
    plainText: blocks.join('\n\n'),
    cards,
  };
}

function buildSearchReply(rawText) {
  return buildSearchResponse(rawText).plainText;
}

async function handleEvent(event) {
  if (event.type !== 'message' || event.message.type !== 'text') return null;
  if (!client) throw new Error('LINE_CHANNEL_ACCESS_TOKEN is not configured');
  let response;
  try {
    response = buildSearchResponse(event.message.text || '');
  } catch (error) {
    console.error('[search] reply generation failed', error);
    response = {
      plainText: '検索中にエラーが発生しました。入力を確認してもう一度お試しください。',
      cards: [],
    };
  }

  const textMessage = {
    type: 'text',
    text: response.plainText.slice(0, 5000),
  };
  const flexMessage = FLEX_REPLY_ENABLED ? buildFlexMessage(response) : null;
  if (!flexMessage) {
    return client.replyMessage({
      replyToken: event.replyToken,
      messages: [textMessage],
    });
  }
  try {
    return await client.replyMessage({
      replyToken: event.replyToken,
      messages: [flexMessage],
    });
  } catch (error) {
    console.error('[line] flex reply failed; retrying as text', error);
    return client.replyMessage({
      replyToken: event.replyToken,
      messages: [textMessage],
    });
  }
}

const webhookMiddleware = config.channelSecret
  ? line.middleware(config)
  : express.json();

app.post('/webhook', webhookMiddleware, async (req, res) => {
  try {
    await Promise.all((req.body.events || []).map(handleEvent));
    res.status(200).end();
  } catch (error) {
    console.error('[webhook] failed', error);
    res.status(500).end();
  }
});

app.get('/healthz', (_req, res) => {
  res.status(200).send('ok');
});

app.get('/healthz/search', (_req, res) => {
  res.json({
    search_engine: SEARCH_ENGINE_VERSION,
    flex_reply_enabled: FLEX_REPLY_ENABLED,
    map_preview_tiles_enabled: MAP_PREVIEW_TILES_ENABLED,
    revision: String(process.env.RENDER_GIT_COMMIT || '').slice(0, 12),
    gps_count: poleCoords.size,
    gps_sha256: gpsSha256,
  });
});

app.get('/healthz/search/sample', (_req, res) => {
  const result = resolveOne('木ノ原40E1S3～40E1S4', poleCoords);
  res.json({
    found: result.found,
    span_point_count: result.spanPoints.length,
    adopted: result.adopted,
  });
});

app.get('/healthz/cadastral', (_req, res) => {
  const payload = {
    enabled: cadastralEnabled,
    available: cadastralStore.available,
  };
  try {
    if (cadastralStore.available) {
      const manifest = cadastralStore.manifest();
      payload.source_date = manifest.source_date || '';
      payload.license = manifest.license || '';
    }
  } catch (error) {
    console.error('[cadastral] health check failed', error);
    payload.available = false;
  }
  res.status(cadastralEnabled && !payload.available ? 503 : 200).json(payload);
});

app.get('/api/map-preview', async (req, res) => {
  const points = parsePreviewPoints(req.query.points);
  if (!points.length) {
    return res.status(400).send('valid points are required');
  }
  try {
    let cadastral = null;
    if (cadastralEnabled && cadastralStore.available) {
      try {
        const viewport = previewBounds(points);
        cadastral = cadastralStore.query(
          viewport.bbox,
          Math.max(17, Math.min(22, viewport.zoom)),
        );
      } catch (error) {
        console.warn('[map-preview] cadastral overlay skipped', error.message);
      }
    }
    const image = await renderMapPreview(points, {
      useTiles: MAP_PREVIEW_TILES_ENABLED,
      cadastral,
      connectPoints: String(req.query.connect || '') === '1',
    });
    res.setHeader('Content-Type', 'image/png');
    res.setHeader('Cache-Control', 'public, max-age=86400');
    return res.send(image);
  } catch (error) {
    console.error('[map-preview] generation failed', error);
    return res.status(503).send('map preview generation failed');
  }
});

app.get('/api/cadastral/features', (req, res) => {
  if (!cadastralEnabled) {
    return res.status(404).json({ error: 'cadastral layer is disabled' });
  }
  if (!cadastralStore.available) {
    return res.status(503).json({ error: 'cadastral dataset is unavailable' });
  }
  try {
    const bbox = String(req.query.bbox || '').split(',').map(Number);
    const zoom = Number(req.query.zoom);
    const result = cadastralStore.query(bbox, zoom);
    res.setHeader('Cache-Control', 'public, max-age=300');
    return res.json(result);
  } catch (error) {
    if (error instanceof RangeError) {
      return res.status(400).json({ error: 'invalid bbox or zoom' });
    }
    console.error('[cadastral] query failed', error);
    return res.status(503).json({ error: 'cadastral query failed' });
  }
});

app.get('/map', (req, res) => {
  const lat = Number(req.query.lat);
  const lng = Number(req.query.lng);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return res.status(400).send('invalid lat/lng');
  }
  return res.render('map.html', {
    lat,
    lng,
    nearby: findNearby(lat, lng),
  });
});

app.get('/multi-map', (req, res) => {
  if (req.query.id) {
    const entry = multiMaps.get(String(req.query.id));
    if (!entry || entry.expiresAt <= Date.now()) {
      multiMaps.delete(String(req.query.id));
      return res.status(404).send('data expired or not found');
    }
    return res.render('multi_map.html', {
      points: entry.points,
      is_two_point_mode: false,
      cadastral_enabled: false,
    });
  }

  const first = parseLatLng(req.query.p1);
  const second = parseLatLng(req.query.p2);
  if (!first || !second) return res.status(400).send('missing id or p1/p2');
  const points = [
    {
      name: String(req.query.p1n || '若番'),
      ...first,
      google_url: googleMapsUrl(first),
    },
    {
      name: String(req.query.p2n || '老番'),
      ...second,
      google_url: googleMapsUrl(second),
    },
  ];
  return res.render('multi_map.html', {
    points,
    is_two_point_mode: true,
    cadastral_enabled: cadastralEnabled && cadastralStore.available,
  });
});

app.get('/', (_req, res) => {
  res.send('LINE pole map bot is running.');
});

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(
      `Server running on port ${PORT}; GPS=${poleCoords.size}; cadastral=${cadastralStore.available}`,
    );
  });
}

module.exports = {
  app,
  buildSearchResponse,
  buildSearchReply,
  cadastralStore,
  poleCoords,
};
