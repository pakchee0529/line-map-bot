'use strict';

const MAX_CAROUSEL_BUBBLES = 12;

function clipText(value, limit) {
  const text = String(value || '').trim();
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 1))}…`;
}

function safeHttpsUrl(value) {
  const text = String(value || '').trim();
  return text.startsWith('https://') ? text : '';
}

function statusTheme(status) {
  const themes = {
    found: { label: '確認済み', color: '#0B6B3A', background: '#E8F6EE' },
    corrected: { label: '補正あり', color: '#8A4B00', background: '#FFF3D6' },
    partial: { label: '一部未解決', color: '#9A4A00', background: '#FFF0E2' },
    unresolved: { label: '候補確認', color: '#A32020', background: '#FDECEC' },
    nearby: { label: '周辺検索', color: '#155E75', background: '#E6F6FA' },
    place: { label: '冠称名検索', color: '#2F4F8F', background: '#ECF1FF' },
    summary: { label: 'まとめ', color: '#334155', background: '#EEF2F7' },
  };
  return themes[status] || themes.summary;
}

function textRow(label, value) {
  return {
    type: 'box',
    layout: 'horizontal',
    margin: 'sm',
    contents: [
      {
        type: 'text',
        text: clipText(label, 12),
        size: 'sm',
        color: '#64748B',
        flex: 2,
      },
      {
        type: 'text',
        text: clipText(value, 80),
        size: 'sm',
        color: '#172033',
        wrap: true,
        flex: 5,
      },
    ],
  };
}

function buildBody(card) {
  const theme = statusTheme(card.status);
  const contents = [
    {
      type: 'box',
      layout: 'horizontal',
      contents: [
        {
          type: 'text',
          text: theme.label,
          size: 'xs',
          weight: 'bold',
          color: theme.color,
          align: 'center',
        },
      ],
      backgroundColor: theme.background,
      cornerRadius: '12px',
      paddingAll: '6px',
      width: '92px',
    },
    {
      type: 'text',
      text: clipText(card.title, 120) || '検索結果',
      weight: 'bold',
      size: 'lg',
      wrap: true,
      margin: 'md',
      color: '#10213B',
    },
  ];

  for (const row of (card.rows || []).slice(0, 4)) {
    contents.push(textRow(row.label, row.value));
  }

  const notes = [...(card.notes || []), ...(card.warnings || [])]
    .filter(Boolean)
    .slice(0, 3);
  if (notes.length) {
    contents.push({
      type: 'separator',
      margin: 'md',
      color: '#D8E1EC',
    });
    for (const note of notes) {
      contents.push({
        type: 'text',
        text: clipText(note, 120),
        size: 'xs',
        color: '#5B6678',
        wrap: true,
        margin: 'sm',
      });
    }
  }

  return {
    type: 'box',
    layout: 'vertical',
    paddingAll: '16px',
    contents,
  };
}

function buildFooter(card) {
  const contents = [];
  const primaryUrl = safeHttpsUrl(card.primaryUrl);
  if (primaryUrl) {
    contents.push({
      type: 'button',
      style: 'primary',
      height: 'sm',
      color: '#173B67',
      action: {
        type: 'uri',
        label: clipText(card.primaryLabel || '地図を開く', 20),
        uri: primaryUrl,
      },
    });
  }

  const secondaryUrl = safeHttpsUrl(card.secondaryUrl);
  if (secondaryUrl) {
    contents.push({
      type: 'button',
      style: 'link',
      height: 'sm',
      action: {
        type: 'uri',
        label: clipText(card.secondaryLabel || 'Googleマップ', 20),
        uri: secondaryUrl,
      },
    });
  } else if (card.suggestionText) {
    contents.push({
      type: 'button',
      style: 'link',
      height: 'sm',
      action: {
        type: 'message',
        label: '候補を検索',
        text: clipText(card.suggestionText, 300),
      },
    });
  }

  if (!contents.length) return undefined;
  return {
    type: 'box',
    layout: 'vertical',
    spacing: 'sm',
    paddingAll: '12px',
    contents,
  };
}

function buildBubble(card) {
  const bubble = {
    type: 'bubble',
    size: 'kilo',
    body: buildBody(card),
  };
  const previewUrl = safeHttpsUrl(card.previewUrl);
  if (previewUrl) {
    bubble.hero = {
      type: 'image',
      url: previewUrl,
      size: 'full',
      aspectRatio: '2:1',
      aspectMode: 'cover',
      action: safeHttpsUrl(card.primaryUrl)
        ? { type: 'uri', uri: safeHttpsUrl(card.primaryUrl) }
        : undefined,
    };
  }
  const footer = buildFooter(card);
  if (footer) bubble.footer = footer;
  return bubble;
}

function buildFlexMessage(replyModel) {
  const cards = (replyModel.cards || []).filter(Boolean);
  if (!cards.length) return null;

  const visibleCards = cards.slice(0, MAX_CAROUSEL_BUBBLES);
  const contents = visibleCards.length === 1
    ? buildBubble(visibleCards[0])
    : {
      type: 'carousel',
      contents: visibleCards.map(buildBubble),
    };
  return {
    type: 'flex',
    altText: clipText(replyModel.plainText || '電柱検索結果', 1500),
    contents,
  };
}

module.exports = {
  MAX_CAROUSEL_BUBBLES,
  buildFlexMessage,
};
