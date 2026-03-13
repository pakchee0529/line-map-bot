from flask import Flask, request, abort, render_template, jsonify
import json
import os
import unicodedata
import re
import math
from urllib.parse import urlencode

from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    LocationMessage,
)
from linebot.exceptions import InvalidSignatureError

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

with open("coords.json", "r", encoding="utf-8") as f:
    coords = json.load(f)

# 高速検索用の前処理
pole_points = []
for pole_name, latlon in coords.items():
    try:
        lat_str, lng_str = latlon.split(",")
        lat = float(lat_str)
        lng = float(lng_str)
        pole_points.append({
            "name": pole_name,
            "lat": lat,
            "lng": lng,
            "latlon": latlon,
        })
    except Exception:
        continue

NEAR_OFFSETS = [1, -1, 2, -2, 3, -3]
RANGE_PATTERN = re.compile(r"[～~]")
POLE_PATTERN = re.compile(r"^(.*?)(\d+)((?:[WNESG]\d+)*)$")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.upper()
    return text


def remove_spaces(text: str) -> str:
    return re.sub(r"[ \u3000]+", "", text)


def normalize_input_line(text: str) -> str:
    return remove_spaces(normalize_text(text.strip()))


def split_input_lines(text: str):
    lines = [normalize_input_line(line) for line in text.splitlines()]
    return [line for line in lines if line]


def make_display_name(text: str) -> str:
    return remove_spaces(normalize_text(text))


def has_hikikomi(text: str) -> bool:
    return "引込" in text or "引き込み" in text


def google_maps_url(latlon: str) -> str:
    return f"https://www.google.com/maps?q={latlon}"


def parse_pole_name(name: str):
    m = POLE_PATTERN.match(name)
    if not m:
        return None

    place = m.group(1)
    parent = int(m.group(2))
    branch_str = m.group(3)

    branches = []
    for letter, num in re.findall(r"([WNESG])(\d+)", branch_str):
        branches.append((letter, int(num)))

    return {
        "place": place,
        "parent": parent,
        "branches": branches
    }


def build_pole_name(place: str, parent: int, branches):
    s = f"{place}{parent}"
    for letter, num in branches:
        s += f"{letter}{num}"
    return s


def is_hazard_g9_candidate(place: str, parent: int, prefix_branches=None) -> bool:
    """
    親番号のみ検索時の G9 特例
    例:
      葛川25 が無い
      葛川25G9 がある
      葛川25G8 / 葛川25G10 が無い
      -> 葛川25G9 を優先候補にする
    """
    if prefix_branches is None:
        prefix_branches = []

    g9 = build_pole_name(place, parent, prefix_branches + [("G", 9)])
    g8 = build_pole_name(place, parent, prefix_branches + [("G", 8)])
    g10 = build_pole_name(place, parent, prefix_branches + [("G", 10)])

    if g9 not in coords:
        return False
    if g8 in coords or g10 in coords:
        return False
    return True


def hazard_g9_name(place: str, parent: int, prefix_branches=None):
    if prefix_branches is None:
        prefix_branches = []
    return build_pole_name(place, parent, prefix_branches + [("G", 9)])


def complete_back_key(front_raw: str, back_raw: str):
    """
    例:
      葛川25～26 -> 葛川26
      葛川17W2～17W3 -> 葛川17W3
      那智合12N1G1～12N2 -> 那智合12N2
      大日川1N9E1G1～E1G2 -> 大日川1N9E1G2
    """
    front = parse_pole_name(front_raw)
    if not front:
        return None

    back_full = parse_pole_name(back_raw)
    if back_full and back_full["place"]:
        return build_pole_name(back_full["place"], back_full["parent"], back_full["branches"])

    m_num = re.match(r"^(\d+)((?:[WNESG]\d+)*)$", back_raw)
    if m_num:
        parent = int(m_num.group(1))
        branch_str = m_num.group(2)
        branches = [(l, int(n)) for l, n in re.findall(r"([WNESG])(\d+)", branch_str)]
        return build_pole_name(front["place"], parent, branches)

    m_branch_only = re.match(r"^((?:[WNESG]\d+)+)$", back_raw)
    if m_branch_only:
        back_branches = [(l, int(n)) for l, n in re.findall(r"([WNESG])(\d+)", back_raw)]
        front_branches = front["branches"]

        if not back_branches:
            return None

        first_back_letter = back_branches[0][0]
        first_back_num = back_branches[0][1]

        prefix = []
        matched_index = None

        for i, (fl, fn) in enumerate(front_branches):
            if fl == first_back_letter and fn == first_back_num:
                matched_index = i
                break

        if matched_index is not None:
            prefix = front_branches[:matched_index]
        else:
            prefix = front_branches

        return build_pole_name(front["place"], front["parent"], prefix + back_branches)

    return None


def create_search_keys(line: str):
    display_name = make_display_name(line)
    hikikomi = has_hikikomi(display_name)

    parts = RANGE_PATTERN.split(display_name, maxsplit=1)
    if len(parts) == 1:
        front_key = parts[0]
        return {
            "display_name": display_name,
            "is_range": False,
            "hikikomi": hikikomi,
            "front_key": front_key,
            "back_key": None,
        }

    front_raw = parts[0]
    back_raw = parts[1]

    front_key = front_raw
    back_key = complete_back_key(front_raw, back_raw)

    return {
        "display_name": display_name,
        "is_range": True,
        "hikikomi": hikikomi,
        "front_key": front_key,
        "back_key": back_key,
    }


def exact_match(name: str):
    if name and name in coords:
        return name
    return None


def branch_neighbors(name: str):
    parsed = parse_pole_name(name)
    if not parsed or not parsed["branches"]:
        return []

    branches = parsed["branches"][:]
    last_letter, last_num = branches[-1]
    result = []

    for offset in NEAR_OFFSETS:
        new_num = last_num + offset
        if new_num <= 0:
            continue
        new_branches = branches[:-1] + [(last_letter, new_num)]
        result.append(build_pole_name(parsed["place"], parsed["parent"], new_branches))

    return result


def branch_reduction(name: str):
    parsed = parse_pole_name(name)
    if not parsed or not parsed["branches"]:
        return []

    result = []
    branches = parsed["branches"][:]

    while branches:
        branches = branches[:-1]
        result.append(build_pole_name(parsed["place"], parsed["parent"], branches))

    return result


def sibling_branch_search(name: str):
    parsed = parse_pole_name(name)
    if not parsed or not parsed["branches"]:
        return []

    result = []
    branches = parsed["branches"][:]
    last_letter, last_num = branches[-1]

    for offset in NEAR_OFFSETS:
        new_num = last_num + offset
        if new_num <= 0:
            continue
        result.append(build_pole_name(parsed["place"], parsed["parent"], branches[:-1] + [(last_letter, new_num)]))

    return result


def parent_only_candidates(name: str):
    """
    親番号のみ入力時
    例:
      葛川25
      ↓
      葛川25G9（G8/G10が無いときだけ）
      ↓
      葛川26, 葛川24
      ↓
      葛川25W1, 葛川25E1, 葛川25N1, 葛川25S1, 葛川25G1
      ↓
      葛川27, 葛川23 ...
    """
    parsed = parse_pole_name(name)
    if not parsed or parsed["branches"]:
        return []

    result = []
    place = parsed["place"]
    parent = parsed["parent"]

    if is_hazard_g9_candidate(place, parent):
        result.append(hazard_g9_name(place, parent))

    for d in range(1, 6):
        plus_name = build_pole_name(place, parent + d, [])
        minus_name = build_pole_name(place, parent - d, []) if parent - d > 0 else None

        if d == 1:
            if plus_name:
                result.append(plus_name)
            if minus_name:
                result.append(minus_name)

            for letter in ["W", "E", "N", "S", "G"]:
                result.append(build_pole_name(place, parent, [(letter, 1)]))
        else:
            if plus_name:
                result.append(plus_name)
            if minus_name:
                result.append(minus_name)

    return result


def non_parent_general_candidates(name: str):
    parsed = parse_pole_name(name)
    if not parsed:
        return [name]

    seen = set()
    result = []

    def add(x):
        if x and x not in seen:
            seen.add(x)
            result.append(x)

    add(name)

    for x in branch_neighbors(name):
        add(x)

    for x in branch_reduction(name):
        add(x)

    for x in sibling_branch_search(name):
        add(x)

    return result


def general_search_order(name: str):
    parsed = parse_pole_name(name)
    if not parsed:
        return [name]

    if not parsed["branches"]:
        seen = set()
        result = []

        def add(x):
            if x and x not in seen:
                seen.add(x)
                result.append(x)

        add(name)
        for x in parent_only_candidates(name):
            add(x)
        return result

    return non_parent_general_candidates(name)


def find_first_existing(candidates):
    for c in candidates:
        if c in coords:
            return c
    return None


def resolve_one(line: str):
    info = create_search_keys(line)
    display_name = info["display_name"]
    is_range = info["is_range"]
    hikikomi = info["hikikomi"]
    front_key = info["front_key"]
    back_key = info["back_key"]

    adopted = None
    preferred_key = None

    # 径間:
    # ① 後側完全一致
    # ② 前側完全一致
    # ③ 後側近傍探索
    # ④ 前側近傍探索
    # 引込/引き込みは前側のみ
    if is_range and back_key and not hikikomi:
        if exact_match(back_key):
            adopted = back_key
            preferred_key = back_key
        elif exact_match(front_key):
            adopted = front_key
            preferred_key = front_key
        else:
            adopted = find_first_existing(general_search_order(back_key))
            if adopted:
                preferred_key = back_key
            else:
                adopted = find_first_existing(general_search_order(front_key))
                if adopted:
                    preferred_key = front_key
    else:
        adopted = find_first_existing(general_search_order(front_key))
        preferred_key = front_key

    if not adopted:
        return {
            "found": False,
            "display_name": display_name,
            "url": None,
            "note": None
        }

    url = google_maps_url(coords[adopted])
    note = None

    if adopted != preferred_key:
        note = f"（{display_name} → {adopted}）"

    return {
        "found": True,
        "display_name": display_name,
        "url": url,
        "note": note
    }


def resolve_message(text: str) -> str:
    lines = split_input_lines(text)

    if not lines:
        return "入力が空です"

    blocks = []

    for line in lines:
        r = resolve_one(line)

        if r["found"]:
            block = f"{r['display_name']}\n{r['url']}"
            if r["note"]:
                block += f"\n{r['note']}"
        else:
            block = f"{r['display_name']}\n該当なし"

        blocks.append(block)

    return "\n\n".join(blocks)


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def find_nearby_poles(lat: float, lng: float, radius_m: float = 200):
    """
    高速版:
    1. 半径を緯度経度の矩形に変換
    2. 矩形に入る候補だけ絞る
    3. その候補だけ厳密距離計算
    """
    result = []

    lat_delta = radius_m / 111320.0

    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-12:
        lng_delta = 180.0
    else:
        lng_delta = radius_m / (111320.0 * cos_lat)

    min_lat = lat - lat_delta
    max_lat = lat + lat_delta
    min_lng = lng - lng_delta
    max_lng = lng + lng_delta

    rough_candidates = []
    for pole in pole_points:
        if min_lat <= pole["lat"] <= max_lat and min_lng <= pole["lng"] <= max_lng:
            rough_candidates.append(pole)

    for pole in rough_candidates:
        dist = haversine_m(lat, lng, pole["lat"], pole["lng"])
        if dist <= radius_m:
            result.append({
                "name": pole["name"],
                "lat": pole["lat"],
                "lng": pole["lng"],
                "distance_m": round(dist, 1),
                "google_maps_url": f"https://www.google.com/maps?q={pole['lat']},{pole['lng']}"
            })

    result.sort(key=lambda x: x["distance_m"])
    return result


@app.route("/nearby")
def nearby_page():
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius = request.args.get("radius", default=200, type=float)

    if lat is None or lng is None:
        return "lat / lng が必要です", 400

    nearby = find_nearby_poles(lat, lng, radius)
    return render_template(
        "nearby_map.html",
        center_lat=lat,
        center_lng=lng,
        radius=radius,
        nearby=nearby
    )


@app.route("/api/nearby")
def nearby_api():
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius = request.args.get("radius", default=200, type=float)

    if lat is None or lng is None:
        return jsonify({"error": "lat / lng required"}), 400

    nearby = find_nearby_poles(lat, lng, radius)
    return jsonify({
        "center": {"lat": lat, "lng": lng},
        "radius": radius,
        "count": len(nearby),
        "poles": nearby
    })


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text
    reply_text = resolve_message(user_text)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    lat = event.message.latitude
    lng = event.message.longitude
    radius = 200

    nearby = find_nearby_poles(lat, lng, radius)

    if BASE_URL:
        query = urlencode({
            "lat": lat,
            "lng": lng,
            "radius": radius
        })
        map_url = f"{BASE_URL}/nearby?{query}"
    else:
        map_url = "(BASE_URL未設定)"

    lines = [f"現在地周囲{radius}mの電柱: {len(nearby)}件", map_url]

    if nearby:
        lines.append("")
        for pole in nearby[:15]:
            lines.append(f"{pole['name']} {pole['distance_m']}m")
        if len(nearby) > 15:
            lines.append(f"…ほか {len(nearby) - 15}件")

    reply_text = "\n".join(lines)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
