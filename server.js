const express = require('express');
const line = require('@line/bot-sdk');
const fs = require('fs');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

const config = {
  channelAccessToken: process.env.LINE_CHANNEL_ACCESS_TOKEN,
  channelSecret: process.env.LINE_CHANNEL_SECRET,
};

const client = new line.Client(config);

const gpsPath = path.join(__dirname, 'GPS.json');
const raw = JSON.parse(fs.readFileSync(gpsPath, 'utf8'));
const gpsMap = new Map(Object.entries(raw));
const gpsKeys = new Set(gpsMap.keys());

function existingKey(name) {
  const adjusted = applyG9Rule(name);
  return canonicalToActual.get(adjusted) || null;
}

function pushCandidate(list, seen, name) {
  if (!name || seen.has(name)) return;
  seen.add(name);
  list.push(name);
}

function expandRootCandidates(parsed, list, seen) {
  const root = { place: parsed.place, parent: parsed.parent, branches: [] };
  pushCandidate(list, seen, formatParsedPole(root));

  for (let delta = 1; delta <= 4; delta += 1) {
    const plus = { place: parsed.place, parent: parsed.parent + delta, branches: [] };
    pushCandidate(list, seen, formatParsedPole(plus));
    const minusParent = parsed.parent - delta;
    if (minusParent > 0) {
      const minus = { place: parsed.place, parent: minusParent, branches: [] };
      pushCandidate(list, seen, formatParsedPole(minus));
    }

    if (delta === 1) {
      ['W', 'E', 'N', 'S', 'G'].forEach((type) => {
        const b = { place: parsed.place, parent: parsed.parent, branches: [{ type, num: 1 }] };
        pushCandidate(list, seen, formatParsedPole(b));
      });
    }
  }
}

function generateNearCandidates(name) {
  const parsed = parsePoleName(name);
  if (!parsed) return [];

  const list = [];
  const seen = new Set();

  pushCandidate(list, seen, formatParsedPole(parsed));

  if (parsed.branches.length > 0) {
    const lastIdx = parsed.branches.length - 1;
    const last = parsed.branches[lastIdx];
    const deltas = [1, -1, 2, -2, 3, -3];
    deltas.forEach((delta) => {
      const nextNum = last.num + delta;
      if (nextNum > 0) {
        const p = cloneParsed(parsed);
        p.branches[lastIdx].num = nextNum;
        pushCandidate(list, seen, formatParsedPole(p));
      }
    });

    for (let depth = parsed.branches.length - 1; depth >= 0; depth -= 1) {
      const reduced = cloneParsed(parsed);
      reduced.branches = reduced.branches.slice(0, depth);
      pushCandidate(list, seen, formatParsedPole(reduced));

      if (reduced.branches.length > 0) {
        const sibIdx = reduced.branches.length - 1;
        const sib = reduced.branches[sibIdx];
        for (let add = 1; add <= 3; add += 1) {
          const s = cloneParsed(reduced);
          s.branches[sibIdx].num = sib.num + add;
          pushCandidate(list, seen, formatParsedPole(s));
        }
      } else {
        expandRootCandidates(reduced, list, seen);
      }
    }
  } else {
    expandRootCandidates(parsed, list, seen);
  }

  return list;
}

function completeRearKey(frontKey, rearRaw) {
  const front = parsePoleName(frontKey);
  if (!front) return null;

  if (/^.+?\d/.test(rearRaw) && !/^[\dWNESG]/.test(rearRaw)) {
    return rearRaw;
  }

  if (/^\d/.test(rearRaw)) {
    return `${front.place}${rearRaw}`;
  }

  if (/^[WNESG]/.test(rearRaw)) {
    const branchMatches = [...rearRaw.matchAll(/([WNESG])(\d+)/g)].map((m) => ({ type: m[1], num: Number(m[2]) }));
    if (branchMatches.length === 0) return `${front.place}${front.parent}${rearRaw}`;

    const firstType = branchMatches[0].type;
    const firstIndex = front.branches.findIndex((b) => b.type === firstType);
    const prefix = firstIndex >= 0 ? front.branches.slice(0, firstIndex) : front.branches;
    return `${front.place}${front.parent}${prefix.map((b) => `${b.type}${b.num}`).join('')}${rearRaw}`;
  }

  return `${front.place}${rearRaw}`;
}

function buildSpanKeys(normalized) {
  const parts = normalized.split(/[～〜~]/);
  const front = parts[0] || '';
  const rearRaw = parts[1] || '';
  const hasSpan = parts.length >= 2;
  const displayName = normalized;
  const isDrop = /引込|引き込み/.test(normalized);

  let rear = null;
  if (hasSpan && !isDrop) {
    rear = completeRearKey(front, rearRaw);
  }

  return {
    displayName,
    frontKey: front,
    rearKey: rear,
    hasSpan,
    isDrop,
  };
}

function findPoleForKey(searchKey) {
  const exact = existingKey(searchKey);
  if (exact) return { matchedKey: exact, noteKey: exact, isExact: exact === searchKey };

  const candidates = generateNearCandidates(searchKey);
  for (const candidate of candidates) {
    const hit = existingKey(candidate);
    if (hit) return { matchedKey: hit, noteKey: hit, isExact: hit === searchKey };
  }
  return null;
}

function lookupSpan(line) {
  const normalized = normalizeInputLine(line);
  if (!normalized) return null;

  const { displayName, frontKey, rearKey, hasSpan, isDrop } = buildSpanKeys(normalized);
  let chosen = null;
  let searchedOriginal = null;

  if (hasSpan && !isDrop && rearKey) {
    chosen = findPoleForKey(rearKey);
    if (chosen) searchedOriginal = rearKey;
  }

  if (!chosen && frontKey) {
    chosen = findPoleForKey(frontKey);
    if (chosen) searchedOriginal = frontKey;
  }

  if (!chosen) {
    return {
      displayName,
      url: '見つかりませんでした',
      note: null,
    };
  }

  const coord = gpsMap.get(chosen.matchedKey);
  const url = `https://www.google.com/maps?q=${coord}`;
  let note = null;
  if (chosen.matchedKey !== searchedOriginal) {
    note = `（${displayName} → ${chosen.matchedKey}）`;
  }

  return { displayName, url, note };
}

function formatSpanResults(lines) {
  const results = lines.map(lookupSpan).filter(Boolean);
  const output = [];
  for (const result of results) {
    output.push(result.displayName);
    output.push(result.url);
    if (result.note) output.push(result.note);
  }
  return output.join('\n');
}

app.post('/webhook', line.middleware(config), async (req, res) => {
  try {
    const events = req.body.events || [];
    await Promise.all(events.map(handleEvent));
    res.status(200).end();
  } catch (err) {
    console.error(err);
    res.status(500).end();
  }
});

async function handleEvent(event) {
  if (event.type !== 'message' || event.message.type !== 'text') return null;

  const rawText = event.message.text || '';
  const lines = splitLines(rawText);
  if (lines.length === 0) return null;

  if (lines.length === 1) {
    const latLng = parseLatLng(lines[0]);
    if (latLng) {
      const nearby = findNearbyPoles(latLng.lat, latLng.lng, 200);
      const mapUrl = `${process.env.BASE_URL}/map?lat=${encodeURIComponent(latLng.lat)}&lng=${encodeURIComponent(latLng.lng)}`;
      const text = nearby.length > 0
        ? `周辺200mの電柱地図です\n件数: ${nearby.length}件\n${mapUrl}`
        : `200m以内に電柱が見つかりませんでした\n地図はこちら\n${mapUrl}`;
      return client.replyMessage({
        replyToken: event.replyToken,
        messages: [{ type: 'text', text }],
      });
    }
  }

  const replyText = formatSpanResults(lines);
  return client.replyMessage({
    replyToken: event.replyToken,
    messages: [{ type: 'text', text: replyText }],
  });
}

app.get('/map', (req, res) => {
  const lat = Number(req.query.lat);
  const lng = Number(req.query.lng);

  if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
    return res.status(400).send('invalid lat/lng');
  }

  const nearby = findNearbyPoles(lat, lng, 200);

  res.setHeader('Content-Type', 'text/html; charset=utf-8');
  res.send(`<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <title>周辺電柱マップ</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html, body, #map { height: 100%; margin: 0; padding: 0; }
    .info {
      position: absolute; top: 10px; left: 10px; z-index: 1000;
      background: rgba(255,255,255,0.96); padding: 6px 10px; border-radius: 8px;
      font-size: 13px; box-shadow: 0 2px 8px rgba(0,0,0,.2); line-height: 1.4;
    }
    .leaflet-tooltip.pole-tooltip { background: transparent; border: none; box-shadow: none; padding: 0; }
    .pole-label {
      display: inline-block; background: rgba(255,255,255,0.92); border: 1px solid #666;
      border-radius: 4px; padding: 1px 4px; font-size: 11px; font-weight: bold; color: #111;
      white-space: nowrap; box-shadow: 0 1px 3px rgba(0,0,0,.25);
    }
    .my-div-icon { background: transparent; border: none; }
    .pole-pin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff; box-sizing: border-box; box-shadow: 0 0 0 1px rgba(0,0,0,0.35); }
    .pole-pin.normal { background: #2563eb; }
    .pole-pin.nearest { width: 14px; height: 14px; background: #ef4444; box-shadow: 0 0 0 1px rgba(0,0,0,0.45), 0 0 6px rgba(239,68,68,0.45); }
    .pole-pin.center { width: 14px; height: 14px; background: #16a34a; box-shadow: 0 0 0 1px rgba(0,0,0,0.45), 0 0 6px rgba(22,163,74,0.35); }
  </style>
</head>
<body>
  <div class="info">電柱: ${nearby.length}件<br>緑: 現在地 / 赤: 最寄り / 青: その他</div>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const center = [${lat}, ${lng}];
    const nearby = ${JSON.stringify(nearby)};
    const map = L.map('map').setView(center, 18);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    function createDotIcon(type = 'normal') {
      const size = (type === 'nearest' || type === 'center') ? 14 : 12;
      const anchor = (type === 'nearest' || type === 'center') ? 7 : 6;
      return L.divIcon({ className: 'my-div-icon', html: '<div class="pole-pin ' + type + '"></div>', iconSize: [size, size], iconAnchor: [anchor, anchor], popupAnchor: [0, -8] });
    }
    L.marker(center, { icon: createDotIcon('center') }).addTo(map).bindPopup('現在地');
    const nearestName = nearby.length > 0 ? nearby[0].name : null;
    nearby.forEach((p) => {
      const isNearest = p.name === nearestName;
      L.marker([p.lat, p.lng], { icon: createDotIcon(isNearest ? 'nearest' : 'normal') })
        .addTo(map)
        .bindPopup(p.name + '<br>' + Math.round(p.distance) + 'm')
        .bindTooltip('<span class="pole-label">' + p.name + (isNearest ? ' ★' : '') + '</span>', {
          permanent: true,
          direction: 'top',
          offset: [0, -8],
          className: 'pole-tooltip'
        });
    });
  </script>
</body>
</html>`);
});

app.get('/', (req, res) => {
  res.send('LINE pole map bot is running.');
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
