'use strict';

const BRANCH_LETTERS = 'WNESGK';
const NEAR_OFFSETS = [1, -1, 2, -2, 3, -3];
const POLE_PATTERN = new RegExp(`^(.*?)(\\d+)((?:[${BRANCH_LETTERS}]\\d+)*)$`);

function normalizeKey(value) {
  return String(value || '')
    .normalize('NFKC')
    .toUpperCase()
    .replace(/[ \u3000]+/g, '')
    .trim();
}

function splitInputLines(text) {
  return String(text || '')
    .split(/\r?\n/)
    .map(normalizeKey)
    .filter(Boolean);
}

function parsePoleName(value) {
  const match = POLE_PATTERN.exec(String(value || ''));
  if (!match) return null;
  const branches = [];
  const branchPattern = new RegExp(`([${BRANCH_LETTERS}])(\\d+)`, 'g');
  for (const branch of match[3].matchAll(branchPattern)) {
    branches.push([branch[1], Number(branch[2])]);
  }
  return { place: match[1], parent: Number(match[2]), branches };
}

function buildPoleName(place, parent, branches) {
  return `${place}${parent}${branches.map(([letter, number]) => `${letter}${number}`).join('')}`;
}

function completeBackKey(frontRaw, backRaw) {
  const front = parsePoleName(frontRaw);
  if (!front) return null;

  const backFull = parsePoleName(backRaw);
  const branchOnlyPattern = new RegExp(`^(?:[${BRANCH_LETTERS}]\\d+)+$`);
  if (backFull && backFull.place && !branchOnlyPattern.test(backRaw)) {
    return buildPoleName(backFull.place, backFull.parent, backFull.branches);
  }

  const numberMatch = new RegExp(`^(\\d+)((?:[${BRANCH_LETTERS}]\\d+)*)$`).exec(backRaw);
  if (numberMatch) {
    const branches = [];
    const branchPattern = new RegExp(`([${BRANCH_LETTERS}])(\\d+)`, 'g');
    for (const branch of numberMatch[2].matchAll(branchPattern)) {
      branches.push([branch[1], Number(branch[2])]);
    }
    return buildPoleName(front.place, Number(numberMatch[1]), branches);
  }

  const branchOnly = new RegExp(`^((?:[${BRANCH_LETTERS}]\\d+)+)$`).exec(backRaw);
  if (!branchOnly) return null;
  const backBranches = [];
  const branchPattern = new RegExp(`([${BRANCH_LETTERS}])(\\d+)`, 'g');
  for (const branch of backRaw.matchAll(branchPattern)) {
    backBranches.push([branch[1], Number(branch[2])]);
  }
  if (!backBranches.length) return null;

  const [firstLetter] = backBranches[0];
  const matchedIndex = front.branches.findIndex(
    ([letter]) => letter === firstLetter,
  );
  const prefix = matchedIndex >= 0
    ? front.branches.slice(0, matchedIndex)
    : front.branches;
  return buildPoleName(front.place, front.parent, [...prefix, ...backBranches]);
}

function createSearchKeys(line) {
  const displayName = normalizeKey(line);
  const parts = displayName.split(/[～〜~]/, 2);
  const hikikomi = displayName.includes('引込') || displayName.includes('引き込み');
  if (parts.length === 1) {
    return {
      displayName,
      isRange: false,
      hikikomi,
      frontKey: parts[0],
      backKey: null,
    };
  }
  return {
    displayName,
    isRange: true,
    hikikomi,
    frontKey: parts[0],
    backKey: completeBackKey(parts[0], parts[1]),
  };
}

function addUnique(output, seen, value) {
  if (value && !seen.has(value)) {
    seen.add(value);
    output.push(value);
  }
}

function branchNeighbors(name) {
  const parsed = parsePoleName(name);
  if (!parsed || !parsed.branches.length) return [];
  const output = [];
  const branches = parsed.branches;
  const [letter, number] = branches[branches.length - 1];
  for (const offset of NEAR_OFFSETS) {
    const nextNumber = number + offset;
    if (nextNumber <= 0) continue;
    addUnique(
      output,
      new Set(output),
      buildPoleName(
        parsed.place,
        parsed.parent,
        [...branches.slice(0, -1), [letter, nextNumber]],
      ),
    );
  }
  return output;
}

function branchReduction(name) {
  const parsed = parsePoleName(name);
  if (!parsed || !parsed.branches.length) return [];
  const output = [];
  let branches = [...parsed.branches];
  while (branches.length) {
    branches = branches.slice(0, -1);
    output.push(buildPoleName(parsed.place, parsed.parent, branches));
  }
  return output;
}

function parentOnlyCandidates(name, poleCoords) {
  const parsed = parsePoleName(name);
  if (!parsed || parsed.branches.length) return [];
  const output = [];
  const g9 = buildPoleName(parsed.place, parsed.parent, [['G', 9]]);
  const g8 = buildPoleName(parsed.place, parsed.parent, [['G', 8]]);
  const g10 = buildPoleName(parsed.place, parsed.parent, [['G', 10]]);
  if (poleCoords.has(g9) && !poleCoords.has(g8) && !poleCoords.has(g10)) {
    output.push(g9);
  }
  output.push(buildPoleName(parsed.place, parsed.parent + 1, []));
  if (parsed.parent > 1) output.push(buildPoleName(parsed.place, parsed.parent - 1, []));
  for (const letter of BRANCH_LETTERS) {
    output.push(buildPoleName(parsed.place, parsed.parent, [[letter, 1]]));
  }
  for (let delta = 2; delta <= 5; delta += 1) {
    output.push(buildPoleName(parsed.place, parsed.parent + delta, []));
    if (parsed.parent > delta) {
      output.push(buildPoleName(parsed.place, parsed.parent - delta, []));
    }
  }
  return output;
}

function generalSearchOrder(name, poleCoords) {
  const parsed = parsePoleName(name);
  if (!parsed) return [name];
  const output = [];
  const seen = new Set();
  addUnique(output, seen, name);

  if (!parsed.branches.length) {
    for (const candidate of parentOnlyCandidates(name, poleCoords)) {
      addUnique(output, seen, candidate);
    }
    return output;
  }

  const last = parsed.branches[parsed.branches.length - 1];
  if (!(last[0] === 'G' && last[1] === 9)) {
    addUnique(
      output,
      seen,
      buildPoleName(parsed.place, parsed.parent, [...parsed.branches, ['G', 9]]),
    );
  }
  for (const candidate of branchNeighbors(name)) addUnique(output, seen, candidate);
  for (const candidate of branchReduction(name)) addUnique(output, seen, candidate);
  return output;
}

function candidateReason(candidate, original) {
  if (candidate === original) return '完全一致候補';
  const parsed = parsePoleName(candidate);
  const originalParsed = parsePoleName(original);
  if (parsed && originalParsed) {
    const endsInG9 = parsed.branches.length
      && parsed.branches[parsed.branches.length - 1][0] === 'G'
      && parsed.branches[parsed.branches.length - 1][1] === 9;
    if (endsInG9) return 'G9補完候補（危険傾斜地の可能性）';
    if (parsed.parent !== originalParsed.parent) return '近い番号の候補';
    return '枝番・近傍番号の補完候補';
  }
  return '表記補正候補';
}

function warningsForKey(name) {
  const parsed = parsePoleName(name);
  if (!parsed) return [];
  const warnings = [];
  if (parsed.branches.some(([letter]) => letter === 'K')) {
    warnings.push('K枝番は仮想柱の可能性があります');
  }
  const last = parsed.branches[parsed.branches.length - 1];
  if (last && last[0] === 'G' && last[1] === 9) {
    warnings.push('G9枝番は危険傾斜地等の補正候補として扱います');
  }
  return warnings;
}

function candidateDetails(name, poleCoords, limit = 8) {
  const output = [];
  for (const candidate of generalSearchOrder(name, poleCoords)) {
    if (!poleCoords.has(candidate)) continue;
    output.push({ name: candidate, reason: candidateReason(candidate, name) });
    if (output.length >= limit) break;
  }
  return output;
}

function samePlaceSuggestions(name, poleCoords, limit = 5) {
  const parsed = parsePoleName(name);
  if (!parsed || !parsed.place) return [];
  const output = [];
  for (const key of [...poleCoords.keys()].sort()) {
    const other = parsePoleName(key);
    if (!other || other.place !== parsed.place || key === name) continue;
    output.push({ name: key, reason: '同一冠称名の候補' });
    if (output.length >= limit) break;
  }
  return output;
}

function resolveKey(name, poleCoords) {
  const candidates = candidateDetails(name, poleCoords);
  const adopted = candidates.length ? candidates[0].name : null;
  return {
    adopted,
    suggestions: candidates.length ? candidates : samePlaceSuggestions(name, poleCoords),
    warnings: [...new Set([...warningsForKey(name), ...warningsForKey(adopted)])],
  };
}

function resolveOne(line, poleCoords) {
  const info = createSearchKeys(line);
  const result = {
    found: false,
    displayName: info.displayName,
    isRange: info.isRange,
    adopted: null,
    spanPoints: [],
    warnings: [],
    candidateNotes: [],
    suggestionDetails: [],
  };

  if (info.isRange && info.backKey && !info.hikikomi) {
    const front = resolveKey(info.frontKey, poleCoords);
    const back = resolveKey(info.backKey, poleCoords);
    if (front.adopted) {
      result.spanPoints.push({ role: '若', input: info.frontKey, adopted: front.adopted });
    } else {
      result.warnings.push(`若側がGPS未登録: ${info.frontKey}`);
    }
    if (back.adopted) {
      result.spanPoints.push({ role: '老', input: info.backKey, adopted: back.adopted });
    } else {
      result.warnings.push(`老側がGPS未登録: ${info.backKey}`);
    }
    result.warnings.push(...front.warnings, ...back.warnings);
    if (front.adopted && front.adopted !== info.frontKey) {
      result.candidateNotes.push(
        `${front.adopted}: ${candidateReason(front.adopted, info.frontKey)}`,
      );
    }
    if (back.adopted && back.adopted !== info.backKey) {
      result.candidateNotes.push(
        `${back.adopted}: ${candidateReason(back.adopted, info.backKey)}`,
      );
    }
    result.adopted = back.adopted || front.adopted;
    result.suggestionDetails = back.suggestions.length
      ? back.suggestions
      : front.suggestions;
  } else {
    const resolved = resolveKey(info.frontKey, poleCoords);
    result.adopted = resolved.adopted;
    result.warnings.push(...resolved.warnings);
    result.suggestionDetails = resolved.suggestions;
    if (resolved.adopted && resolved.adopted !== info.frontKey) {
      result.candidateNotes.push(
        `${resolved.adopted}: ${candidateReason(resolved.adopted, info.frontKey)}`,
      );
    }
  }

  result.found = Boolean(result.adopted);
  result.warnings = [...new Set(result.warnings)];
  return result;
}

function loadPoleData(raw) {
  const poleCoords = new Map();
  const gpsPoints = [];
  for (const [rawName, rawValue] of Object.entries(raw)) {
    const [latText, lngText] = String(rawValue).split(',', 2);
    const lat = Number(latText);
    const lng = Number(lngText);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    const name = normalizeKey(rawName);
    poleCoords.set(name, `${latText.trim()},${lngText.trim()}`);
    gpsPoints.push({ name: rawName, searchName: name, lat, lng });
  }
  return { poleCoords, gpsPoints };
}

function findPlacePoints(placeName, gpsPoints, limit = 1000) {
  const place = normalizeKey(placeName);
  const output = [];
  const seen = new Set();
  for (const point of gpsPoints) {
    const parsed = parsePoleName(point.searchName);
    if (!parsed || parsed.place !== place) continue;
    const identity = `${point.searchName}:${point.lat.toFixed(7)}:${point.lng.toFixed(7)}`;
    if (seen.has(identity)) continue;
    seen.add(identity);
    output.push({
      name: point.searchName,
      lat: point.lat,
      lng: point.lng,
    });
    if (output.length >= limit) break;
  }
  return output;
}

module.exports = {
  createSearchKeys,
  findPlacePoints,
  loadPoleData,
  normalizeKey,
  parsePoleName,
  resolveOne,
  splitInputLines,
};
