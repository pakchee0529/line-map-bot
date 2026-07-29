from __future__ import annotations

from typing import Any


MAX_CAROUSEL_BUBBLES = 12


def _clip(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[: max(0, limit - 1)]}…"


def _https_url(value: object) -> str:
    text = str(value or "").strip()
    return text if text.startswith("https://") else ""


def _theme(status: str) -> dict[str, str]:
    themes = {
        "found": {
            "label": "確認済み",
            "color": "#0B6B3A",
            "background": "#E8F6EE",
        },
        "corrected": {
            "label": "補正あり",
            "color": "#8A4B00",
            "background": "#FFF3D6",
        },
        "partial": {
            "label": "一部未解決",
            "color": "#9A4A00",
            "background": "#FFF0E2",
        },
        "unresolved": {
            "label": "候補確認",
            "color": "#A32020",
            "background": "#FDECEC",
        },
        "nearby": {
            "label": "周辺検索",
            "color": "#155E75",
            "background": "#E6F6FA",
        },
        "place": {
            "label": "冠称名検索",
            "color": "#2F4F8F",
            "background": "#ECF1FF",
        },
        "summary": {
            "label": "まとめ",
            "color": "#334155",
            "background": "#EEF2F7",
        },
    }
    return themes.get(status, themes["summary"])


def _text_row(label: object, value: object) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "horizontal",
        "margin": "sm",
        "contents": [
            {
                "type": "text",
                "text": _clip(label, 12),
                "size": "sm",
                "color": "#64748B",
                "flex": 2,
            },
            {
                "type": "text",
                "text": _clip(value, 80),
                "size": "sm",
                "color": "#172033",
                "wrap": True,
                "flex": 5,
            },
        ],
    }


def _build_body(card: dict[str, Any]) -> dict[str, Any]:
    theme = _theme(str(card.get("status") or ""))
    contents: list[dict[str, Any]] = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": theme["label"],
                    "size": "xs",
                    "weight": "bold",
                    "color": theme["color"],
                    "align": "center",
                }
            ],
            "backgroundColor": theme["background"],
            "cornerRadius": "12px",
            "paddingAll": "6px",
            "width": "92px",
        },
        {
            "type": "text",
            "text": _clip(card.get("title"), 120) or "検索結果",
            "weight": "bold",
            "size": "lg",
            "wrap": True,
            "margin": "md",
            "color": "#10213B",
        },
    ]
    for row in list(card.get("rows") or [])[:4]:
        if isinstance(row, dict):
            contents.append(_text_row(row.get("label"), row.get("value")))

    notes = [
        str(item)
        for item in [
            *list(card.get("notes") or []),
            *list(card.get("warnings") or []),
        ]
        if str(item)
    ][:3]
    if notes:
        contents.append(
            {
                "type": "separator",
                "margin": "md",
                "color": "#D8E1EC",
            }
        )
        contents.extend(
            {
                "type": "text",
                "text": _clip(note, 120),
                "size": "xs",
                "color": "#5B6678",
                "wrap": True,
                "margin": "sm",
            }
            for note in notes
        )
    return {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "contents": contents,
    }


def _build_footer(card: dict[str, Any]) -> dict[str, Any] | None:
    contents: list[dict[str, Any]] = []
    primary_url = _https_url(card.get("primary_url"))
    if primary_url:
        contents.append(
            {
                "type": "button",
                "style": "primary",
                "height": "sm",
                "color": "#173B67",
                "action": {
                    "type": "uri",
                    "label": _clip(card.get("primary_label") or "地図を開く", 20),
                    "uri": primary_url,
                },
            }
        )

    secondary_url = _https_url(card.get("secondary_url"))
    if secondary_url:
        contents.append(
            {
                "type": "button",
                "style": "link",
                "height": "sm",
                "action": {
                    "type": "uri",
                    "label": _clip(
                        card.get("secondary_label") or "Googleマップ",
                        20,
                    ),
                    "uri": secondary_url,
                },
            }
        )
    elif card.get("suggestion_text"):
        contents.append(
            {
                "type": "button",
                "style": "link",
                "height": "sm",
                "action": {
                    "type": "message",
                    "label": "候補を検索",
                    "text": _clip(card.get("suggestion_text"), 300),
                },
            }
        )

    if not contents:
        return None
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "paddingAll": "12px",
        "contents": contents,
    }


def _build_bubble(card: dict[str, Any]) -> dict[str, Any]:
    bubble: dict[str, Any] = {
        "type": "bubble",
        "size": "kilo",
        "body": _build_body(card),
    }
    preview_url = _https_url(card.get("preview_url"))
    if preview_url:
        hero: dict[str, Any] = {
            "type": "image",
            "url": preview_url,
            "size": "full",
            "aspectRatio": "2:1",
            "aspectMode": "cover",
        }
        primary_url = _https_url(card.get("primary_url"))
        if primary_url:
            hero["action"] = {"type": "uri", "uri": primary_url}
        bubble["hero"] = hero
    footer = _build_footer(card)
    if footer:
        bubble["footer"] = footer
    return bubble


def build_flex_payload(response: dict[str, Any]) -> dict[str, Any] | None:
    cards = [card for card in list(response.get("cards") or []) if isinstance(card, dict)]
    if not cards:
        return None
    cards = cards[:MAX_CAROUSEL_BUBBLES]
    contents: dict[str, Any]
    if len(cards) == 1:
        contents = _build_bubble(cards[0])
    else:
        contents = {
            "type": "carousel",
            "contents": [_build_bubble(card) for card in cards],
        }
    return {
        "alt_text": _clip(response.get("plain_text") or "電柱検索結果", 1500),
        "contents": contents,
    }
