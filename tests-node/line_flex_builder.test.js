'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  MAX_CAROUSEL_BUBBLES,
  buildFlexMessage,
} = require('../line_flex_builder');

function sampleCard(index = 1) {
  return {
    status: 'found',
    title: `木ノ原${index}`,
    rows: [{ label: '採用地点', value: `木ノ原${index}` }],
    primaryUrl: `https://example.com/map/${index}`,
    previewUrl: `https://example.com/preview/${index}.png`,
  };
}

test('builds an image-backed Flex bubble for one search result', () => {
  const message = buildFlexMessage({
    plainText: '木ノ原40E1S3～40E1S4',
    cards: [{
      ...sampleCard(),
      status: 'corrected',
      primaryLabel: '2点地図・地番図を開く',
      warnings: ['G9枝番は危険傾斜地等の補正候補として扱います'],
    }],
  });

  assert.equal(message.type, 'flex');
  assert.equal(message.contents.type, 'bubble');
  assert.equal(message.contents.hero.type, 'image');
  assert.equal(message.contents.hero.action.type, 'uri');
  assert.equal(message.contents.footer.contents[0].action.label, '2点地図・地番図を開く');
  assert.match(message.altText, /木ノ原/);
});

test('limits a Flex carousel to the LINE maximum', () => {
  const message = buildFlexMessage({
    plainText: 'multi',
    cards: Array.from({ length: 20 }, (_, index) => sampleCard(index + 1)),
  });
  assert.equal(message.contents.type, 'carousel');
  assert.equal(message.contents.contents.length, MAX_CAROUSEL_BUBBLES);
});

test('rejects non-HTTPS links from Flex actions and images', () => {
  const message = buildFlexMessage({
    plainText: 'unsafe',
    cards: [{
      ...sampleCard(),
      primaryUrl: 'http://example.com/map',
      previewUrl: 'javascript:alert(1)',
      suggestionText: '木ノ原40',
    }],
  });
  assert.equal(message.contents.hero, undefined);
  assert.equal(message.contents.footer.contents[0].action.type, 'message');
});
