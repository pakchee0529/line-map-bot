'use strict';

const sharp = require('sharp');

const WIDTH = 1024;
const HEIGHT = 512;
const TILE_SIZE = 256;
const MAX_POINTS = 20;
const MAX_CACHE_ENTRIES = 100;
const TILE_SOURCE_GSI_AERIAL = 'gsi_aerial';
const TILE_SOURCE_OSM = 'osm';
const DEFAULT_TILE_SOURCE = TILE_SOURCE_GSI_AERIAL;
const cache = new Map();

function parsePreviewPoints(raw) {
  const points = [];
  for (const pair of String(raw || '').split('|')) {
    if (!pair.trim()) continue;
    const [latText, lngText] = pair.split(',', 2);
    const lat = Number(latText);
    const lng = Number(lngText);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    if (Math.abs(lat) > 90 || Math.abs(lng) > 180) continue;
    points.push({ lat, lng });
    if (points.length >= MAX_POINTS) break;
  }
  return points;
}

function serializePreviewPoints(points) {
  return (points || [])
    .filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lng))
    .slice(0, MAX_POINTS)
    .map((point) => `${point.lat.toFixed(6)},${point.lng.toFixed(6)}`)
    .join('|');
}

function worldPoint(point, zoom) {
  const scale = TILE_SIZE * (2 ** zoom);
  const sin = Math.sin(point.lat * Math.PI / 180);
  const clamped = Math.min(0.9999, Math.max(-0.9999, sin));
  return {
    x: (point.lng + 180) / 360 * scale,
    y: (0.5 - Math.log((1 + clamped) / (1 - clamped)) / (4 * Math.PI)) * scale,
  };
}

function chooseZoom(points) {
  if (points.length <= 1) return 17;
  for (let zoom = 18; zoom >= 6; zoom -= 1) {
    const projected = points.map((point) => worldPoint(point, zoom));
    const xs = projected.map((point) => point.x);
    const ys = projected.map((point) => point.y);
    if (
      Math.max(...xs) - Math.min(...xs) <= WIDTH * 0.62
      && Math.max(...ys) - Math.min(...ys) <= HEIGHT * 0.56
    ) {
      return zoom;
    }
  }
  return 6;
}

function previewGeometry(points) {
  const zoom = chooseZoom(points);
  const projected = points.map((point) => worldPoint(point, zoom));
  const center = {
    x: projected.reduce((sum, point) => sum + point.x, 0) / projected.length,
    y: projected.reduce((sum, point) => sum + point.y, 0) / projected.length,
  };
  const left = center.x - WIDTH / 2;
  const top = center.y - HEIGHT / 2;
  return {
    zoom,
    left,
    top,
    screenPoints: projected.map((point) => ({
      x: point.x - left,
      y: point.y - top,
    })),
  };
}

function previewBounds(points) {
  const geometry = previewGeometry(points);
  const scale = TILE_SIZE * (2 ** geometry.zoom);
  const toLng = (x) => x / scale * 360 - 180;
  const toLat = (y) => {
    const mercator = Math.PI - (2 * Math.PI * y) / scale;
    return 180 / Math.PI * Math.atan(Math.sinh(mercator));
  };
  return {
    bbox: [
      toLng(geometry.left),
      toLat(geometry.top + HEIGHT),
      toLng(geometry.left + WIDTH),
      toLat(geometry.top),
    ],
    zoom: geometry.zoom,
  };
}

function wrapTileX(x, zoom) {
  const count = 2 ** zoom;
  return ((x % count) + count) % count;
}

function normalizeTileSource(value) {
  return String(value || '').trim().toLowerCase() === TILE_SOURCE_OSM
    ? TILE_SOURCE_OSM
    : TILE_SOURCE_GSI_AERIAL;
}

async function fetchTile(zoom, x, y, tileSource) {
  if (y < 0 || y >= 2 ** zoom) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  const tileX = wrapTileX(x, zoom);
  const url = tileSource === TILE_SOURCE_OSM
    ? `https://tile.openstreetmap.org/${zoom}/${tileX}/${y}.png`
    : `https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/${zoom}/${tileX}/${y}.jpg`;
  try {
    const response = await fetch(url, {
      headers: {
        'User-Agent': 'line-map-bot/1.0 (LINE field map preview)',
      },
      signal: controller.signal,
    });
    if (!response.ok) return null;
    return Buffer.from(await response.arrayBuffer());
  } catch (_error) {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

function overlaySvg(
  screenPoints,
  hasCadastral,
  connectPoints,
  renderedTileSource,
) {
  const line = connectPoints && screenPoints.length === 2
    ? `<polyline points="${screenPoints.map((p) => `${p.x},${p.y}`).join(' ')}"
         fill="none" stroke="#173B67" stroke-width="8"
         stroke-linecap="round" stroke-linejoin="round"/>`
    : '';
  const numbered = connectPoints && screenPoints.length === 2;
  const pins = screenPoints.map((point, index) => numbered
    ? `
      <g transform="translate(${point.x},${point.y})">
        <circle r="25" fill="#FFFFFF" stroke="#173B67" stroke-width="7"/>
        <circle r="17" fill="${index === 0 ? '#D99100' : '#D94A4A'}"/>
        <text x="0" y="8" text-anchor="middle"
          font-family="Arial, sans-serif" font-size="24" font-weight="700"
          fill="#FFFFFF">${index + 1}</text>
      </g>
    `
    : `
      <g transform="translate(${point.x},${point.y})">
        <circle r="${screenPoints.length === 1 ? 22 : 10}"
          fill="#D94A4A" stroke="#FFFFFF"
          stroke-width="${screenPoints.length === 1 ? 7 : 4}"/>
      </g>
    `).join('');
  let attribution = '';
  if (renderedTileSource === TILE_SOURCE_GSI_AERIAL) {
    attribution = 'Source: GSI Japan aerial imagery';
  } else if (renderedTileSource === TILE_SOURCE_OSM) {
    attribution = '© OpenStreetMap contributors';
  }
  if (hasCadastral) {
    attribution += `${attribution ? ' / ' : ''}Cadastral: Gojo City CC BY 4.0`;
  }
  return Buffer.from(`
    <svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg">
      <rect width="100%" height="100%" fill="none"/>
      ${line}
      ${pins}
      <rect x="0" y="${HEIGHT - 30}" width="${WIDTH}" height="30"
        fill="#FFFFFF" fill-opacity="0.82"/>
      <text x="${WIDTH - 12}" y="${HEIGHT - 9}" text-anchor="end"
        font-family="Arial, sans-serif" font-size="16" fill="#334155">
        ${attribution}
      </text>
    </svg>
  `);
}

function escapeXml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function nearbyCadastralLabelKeys(features, geometry, maxDistance = 180) {
  const project = (coordinate) => {
    const point = worldPoint({
      lng: Number(coordinate[0]),
      lat: Number(coordinate[1]),
    }, geometry.zoom);
    return {
      x: point.x - geometry.left,
      y: point.y - geometry.top,
    };
  };
  const candidates = features
    .map((feature, index) => ({ feature, index }))
    .filter(({ feature }) => (
      feature.properties?.layer === 'label'
      && feature.geometry?.type === 'Point'
    ))
    .map(({ feature, index }) => ({
      key: String(feature.id ?? `label-${index}`),
      point: project(feature.geometry.coordinates),
    }));
  const selected = new Set();
  const maxDistanceSquared = maxDistance ** 2;
  for (const screenPoint of geometry.screenPoints.slice(0, 2)) {
    const nearest = [...candidates].sort((left, right) => (
      ((left.point.x - screenPoint.x) ** 2 + (left.point.y - screenPoint.y) ** 2)
      - ((right.point.x - screenPoint.x) ** 2 + (right.point.y - screenPoint.y) ** 2)
    ));
    for (const candidate of nearest) {
      const distanceSquared = (candidate.point.x - screenPoint.x) ** 2
        + (candidate.point.y - screenPoint.y) ** 2;
      if (distanceSquared > maxDistanceSquared) break;
      if (selected.has(candidate.key)) continue;
      selected.add(candidate.key);
      break;
    }
  }
  return selected;
}

function cadastralOverlaySvg(featureCollection, geometry) {
  const features = featureCollection && Array.isArray(featureCollection.features)
    ? featureCollection.features
    : [];
  if (!features.length) return null;

  const project = (coordinate) => {
    const point = worldPoint({ lng: Number(coordinate[0]), lat: Number(coordinate[1]) }, geometry.zoom);
    return {
      x: point.x - geometry.left,
      y: point.y - geometry.top,
    };
  };
  const pathForLine = (coordinates, close = false) => {
    const projected = coordinates.map(project).filter(
      (point) => Number.isFinite(point.x) && Number.isFinite(point.y),
    );
    if (!projected.length) return '';
    return `M ${projected.map((point) => `${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' L ')}${close ? ' Z' : ''}`;
  };
  const selectedLabelKeys = nearbyCadastralLabelKeys(features, geometry);

  const shapes = [];
  const labels = [];
  features.forEach((feature, index) => {
    const layer = feature.properties && feature.properties.layer;
    const geometryValue = feature.geometry || {};
    if (layer === 'label' && geometryValue.type === 'Point') {
      const key = String(feature.id ?? `label-${index}`);
      if (!selectedLabelKeys.has(key)) return;
      const point = project(geometryValue.coordinates);
      const angle = Number(feature.properties.angle) || 0;
      labels.push(`
        <text x="${point.x}" y="${point.y}" text-anchor="middle"
          transform="rotate(${angle} ${point.x} ${point.y})"
          font-family="Arial, sans-serif" font-size="16" font-weight="700"
          fill="#8A2D0A" stroke="#FFFFFF" stroke-width="3"
          paint-order="stroke">${escapeXml(feature.properties.label)}</text>
      `);
      return;
    }

    const paths = [];
    if (geometryValue.type === 'Polygon') {
      for (const ring of geometryValue.coordinates || []) paths.push(pathForLine(ring, true));
    } else if (geometryValue.type === 'MultiPolygon') {
      for (const polygon of geometryValue.coordinates || []) {
        for (const ring of polygon) paths.push(pathForLine(ring, true));
      }
    } else if (geometryValue.type === 'LineString') {
      paths.push(pathForLine(geometryValue.coordinates || []));
    } else if (geometryValue.type === 'MultiLineString') {
      for (const line of geometryValue.coordinates || []) paths.push(pathForLine(line));
    }
    const pathData = paths.filter(Boolean).join(' ');
    if (!pathData) return;
    const leader = layer === 'leader';
    shapes.push(`
      <path d="${pathData}" fill="none"
        stroke="${leader ? '#9A3412' : '#F97316'}"
        stroke-width="${leader ? '1' : '2'}"
        stroke-opacity="${leader ? '0.45' : '0.53'}"/>
    `);
  });

  return Buffer.from(`
    <svg width="${WIDTH}" height="${HEIGHT}" xmlns="http://www.w3.org/2000/svg">
      ${shapes.join('')}
      ${labels.join('')}
    </svg>
  `);
}

async function tileComposites(geometry, tileSource) {
  const minTileX = Math.floor(geometry.left / TILE_SIZE);
  const maxTileX = Math.floor((geometry.left + WIDTH) / TILE_SIZE);
  const minTileY = Math.floor(geometry.top / TILE_SIZE);
  const maxTileY = Math.floor((geometry.top + HEIGHT) / TILE_SIZE);
  const jobs = [];
  for (let tileY = minTileY; tileY <= maxTileY; tileY += 1) {
    for (let tileX = minTileX; tileX <= maxTileX; tileX += 1) {
      jobs.push((async () => {
        const tile = await fetchTile(geometry.zoom, tileX, tileY, tileSource);
        if (!tile) return null;
        const rawLeft = Math.round(tileX * TILE_SIZE - geometry.left);
        const rawTop = Math.round(tileY * TILE_SIZE - geometry.top);
        const cropLeft = Math.max(0, -rawLeft);
        const cropTop = Math.max(0, -rawTop);
        const left = Math.max(0, rawLeft);
        const top = Math.max(0, rawTop);
        const width = Math.min(TILE_SIZE - cropLeft, WIDTH - left);
        const height = Math.min(TILE_SIZE - cropTop, HEIGHT - top);
        if (width <= 0 || height <= 0) return null;
        const input = (cropLeft || cropTop || width < TILE_SIZE || height < TILE_SIZE)
          ? await sharp(tile).extract({
            left: cropLeft,
            top: cropTop,
            width,
            height,
          }).toBuffer()
          : tile;
        return { input, left, top };
      })());
    }
  }
  return (await Promise.all(jobs)).filter(Boolean);
}

async function renderMapPreview(points, {
  useTiles = true,
  cadastral = null,
  connectPoints = false,
  tileSource = DEFAULT_TILE_SOURCE,
} = {}) {
  if (!Array.isArray(points) || !points.length) {
    throw new RangeError('at least one valid point is required');
  }
  const cadastralFeatures = cadastral && Array.isArray(cadastral.features)
    ? cadastral.features
    : [];
  const cadastralVersion = cadastralFeatures.length
    ? `${cadastralFeatures.length}:${String(cadastral.metadata?.source_date || '')}`
    : 'none';
  const requestedTileSource = normalizeTileSource(tileSource);
  const cacheKey = `${useTiles ? requestedTileSource : 'plain'}:${connectPoints ? 'line' : 'pins'}:${serializePreviewPoints(points)}:${cadastralVersion}`;
  if (cache.has(cacheKey)) return cache.get(cacheKey);

  const geometry = previewGeometry(points);
  const base = sharp({
    create: {
      width: WIDTH,
      height: HEIGHT,
      channels: 3,
      background: { r: 238, g: 243, b: 247 },
    },
  });
  const composites = [];
  let renderedTileSource = '';

  if (useTiles) {
    let tileLayers = await tileComposites(geometry, requestedTileSource);
    if (tileLayers.length) {
      renderedTileSource = requestedTileSource;
    } else if (requestedTileSource !== TILE_SOURCE_OSM) {
      tileLayers = await tileComposites(geometry, TILE_SOURCE_OSM);
      if (tileLayers.length) renderedTileSource = TILE_SOURCE_OSM;
    }
    composites.push(...tileLayers);
  }

  const cadastralOverlay = cadastralOverlaySvg(cadastral, geometry);
  if (cadastralOverlay) {
    composites.push({ input: cadastralOverlay, left: 0, top: 0 });
  }
  composites.push({
    input: overlaySvg(
      geometry.screenPoints,
      cadastralFeatures.length > 0,
      connectPoints,
      renderedTileSource,
    ),
    left: 0,
    top: 0,
  });
  const buffer = await base
    .composite(composites)
    .png({ compressionLevel: 8 })
    .toBuffer();

  cache.set(cacheKey, buffer);
  if (cache.size > MAX_CACHE_ENTRIES) {
    cache.delete(cache.keys().next().value);
  }
  return buffer;
}

module.exports = {
  DEFAULT_TILE_SOURCE,
  HEIGHT,
  TILE_SOURCE_GSI_AERIAL,
  TILE_SOURCE_OSM,
  WIDTH,
  nearbyCadastralLabelKeys,
  normalizeTileSource,
  parsePreviewPoints,
  previewGeometry,
  previewBounds,
  renderMapPreview,
  serializePreviewPoints,
};
