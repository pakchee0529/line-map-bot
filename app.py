from flask import Flask, request, abort, render_template
import json
import os
import unicodedata
import re
import math
import urllib.parse
import urllib.request
import threading
import time

from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent,
    TextMessage,
    TextSendMessage,
    LocationMessage,
    FollowEvent,
)
from linebot.exceptions import InvalidSignatureError

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


# ----------------------------
# Data
# ----------------------------
def load_pole_coords():
    with open("GPS.json", "r", encoding="utf-8") as f:
        raw = json.load(f)

    pole_coords = {}
    gps_points = []

    for name, value in raw.items():
        try:
            lat_str, lng_str = str(value).split(",")
            lat = float(lat_str)
            lng = float(lng_str)
            latlon = f"{lat_str.strip()},{lng_str.strip()}"

            pole_coords[name] = latlon
            gps_points.append({
                "name": name,
                "lat": lat,
                "lng": lng,
            })
        except Exception:
            pass

    return pole_coords, gps_points


POLE_COORDS, GPS_POINTS = load_pole_coords()


# ----------------------------
# Constants / patterns
# ----------------------------
NEAR_OFFSETS = [1, -1, 2, -2, 3, -3]
RANGE_PATTERN = re.compile(r"[～~]")
POLE_PATTERN = re.compile(r"^(.*?)(\d+)((?:[WNESG]\d+)*)$")


# ----------------------------
# Messages
# ----------------------------
MSG_FRIEND = """はじめまして、電柱ナビのいっぱつちゃんだよ
電柱名や径間名を送ると、その場所を地図で案内できるよ📍

▼使い方
そのまま送ればOK
葛川25～26 / 谷垣内22
複数まとめて送っても大丈夫👌

電柱を1本だけ送ったときは
その場所と、周辺200mの電柱地図も一緒に出すよ

座標（緯度,経度）や、LINEの「＋」から位置情報を送ると
近くの電柱をまとめて確認できるよ🗺️

※ちょっとだけお願い
地図を確認しながら探してるから、少し時間がかかることがあるよ
見つけたらちゃんと案内するから、そのまま待っててね✨"""

MSG_WAIT = """今探してるよ
少し待っててね🔎"""


# ----------------------------
# Formatting helpers
# ----------------------------
def format_single_result(display_name: str, url: str, map_url: str | None, note: str | None = None) -> str:
    lines = [
        display_name,
        "見つかったよ📍",
        "この電柱の場所はここ",
        url,
    ]

    if map_url:
        lines.extend([
            "",
            "近くの電柱も一緒に確認できるよ",
            "（半径200mの地図）",
            map_url,
        ])

    if note:
        lines.extend([
            "",
            "ぴったりの候補がなかったから",
            "近い候補で案内してるよ",
            note,
        ])

    return "\n".join(lines)


def format_span_result(display_name: str, url: str, note: str | None = None) -> str:
    lines = [
        display_name,
        "見つかったよ📍",
        "この径間の場所はここ",
        url,
    ]

    if note:
        lines.extend([
            "",
            "ぴったりの候補がなかったから",
            "近い候補で案内してるよ",
            note,
        ])

    return "\n".join(lines)


def format_not_found(display_name: str) -> str:
    return f"""{display_name}
ごめんね
今回は見つからなかったよ💦

地名や番号を少し変えると見つかるかも"""


def format_location_result(map_url: str, count: int, header: str | None = None) -> str:
    lines = []
    if header:
        lines.append(header)

    lines.extend([
        "この場所のまわりを確認したよ",
        "半径200mの電柱地図はこれ🗺️",
        f"件数: {count}件",
        map_url,
    ])
    return "\n".join(lines)


def format_location_empty(map_url: str, header: str | None = None) -> str:
    lines = []
    if header:
        lines.append(header)

    lines.extend([
        "この場所のまわりを確認したよ",
        "でも200m以内に電柱は見つからなかったよ💦",
        "",
        "地図はここから見れるよ🗺️",
        map_url,
    ])
    return "\n".join(lines)


def format_address_result(address_name: str, map_url: str) -> str:
    return f"""場所を見つけたよ📍
この周辺の電柱地図はこれ🗺️
{address_name}
{map_url}"""


# ----------------------------
# Basic text helpers
# ----------------------------
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


def parse_latlng(text: str):
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", text)
    if not m:
        return None

    lat = float(m.group(1))
    lng = float(m.group(2))

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    return lat, lng


# ----------------------------
# Nearby search
# ----------------------------
def distance_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def find_nearby(lat, lng, radius=200):
    result = []
    for p in GPS_POINTS:
        d = distance_m(lat, lng, p["lat"], p["lng"])
        if d <= radius:
            item = dict(p)
            item["distance"] = d
            result.append(item)

    result.sort(key=lambda x: x["distance"])
    return result


def geocode_address(address: str):
    query = urllib.parse.urlencode({
        "q": address,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "jp",
        "addressdetails": 0,
    })

    url = f"https://nominatim.openstreetmap.org/search?{query}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "line-map-bot/1.0 (LINE bot pole map)"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"[geocode_address] request failed: {e}")
        return None

    if not data:
        print("[geocode_address] no result")
        return None

    try:
        item = data[0]
        lat = float(item["lat"])
        lng = float(item["lon"])
        display_name = item.get("display_name", address)
        return lat, lng, display_name
    except Exception as e:
        print(f"[geocode_address] parse failed: {e}")
        return None


def build_map_url(lat, lng):
    base_url = os.getenv("BASE_URL", "").rstrip("/")
    return f"{base_url}/map?lat={lat}&lng={lng}"


# ----------------------------
# Pole parsing / search logic
# ----------------------------
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
    if prefix_branches is None:
        prefix_branches = []

    g9 = build_pole_name(place, parent, prefix_branches + [("G", 9)])
    g8 = build_pole_name(place, parent, prefix_branches + [("G", 8)])
    g10 = build_pole_name(place, parent, prefix_branches + [("G", 10)])

    if g9 not in POLE_COORDS:
        return False
    if g8 in POLE_COORDS or g10 in POLE_COORDS:
        return False
    return True


def hazard_g9_name(place: str, parent: int, prefix_branches=None):
    if prefix_branches is None:
        prefix_branches = []
    return build_pole_name(place, parent, prefix_branches + [("G", 9)])


def complete_back_key(front_raw: str, back_raw: str):
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
    if name and name in POLE_COORDS:
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
    parsed = parse_pole_name(name)
    if not parsed:
        return []

    if parsed["branches"]:
        return []

    result = []
    place = parsed["place"]
    parent = parsed["parent"]

    # 完全一致(name)の直後に、危険箇所扱いの G9 候補を差し込む
    if is_hazard_g9_candidate(place, parent):
        result.append(hazard_g9_name(place, parent))

    plus_1 = build_pole_name(place, parent + 1, [])
    minus_1 = build_pole_name(place, parent - 1, []) if parent - 1 > 0 else None

    if plus_1:
        result.append(plus_1)
    if minus_1:
        result.append(minus_1)

    for letter in ["W", "E", "N", "S", "G"]:
        result.append(build_pole_name(place, parent, [(letter, 1)]))

    for d in range(2, 6):
        plus_name = build_pole_name(place, parent + d, [])
        minus_name = build_pole_name(place, parent - d, []) if parent - d > 0 else None

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
        if c in POLE_COORDS:
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
            "note": None,
            "is_range": is_range,
            "map_url": None,
            "adopted": None,
        }

    latlon = POLE_COORDS[adopted]
    url = google_maps_url(latlon)
    note = None
    map_url = None

    if adopted != preferred_key:
        note = f"（{display_name} → {adopted}）"

    if not is_range:
        parsed = parse_latlng(latlon)
        if parsed:
            map_url = build_map_url(parsed[0], parsed[1])

    return {
        "found": True,
        "display_name": display_name,
        "url": url,
        "note": note,
        "is_range": is_range,
        "map_url": map_url,
        "adopted": adopted,
    }


def resolve_lines(text: str):
    lines = split_input_lines(text)
    results = []

    for line in lines:
        results.append(resolve_one(line))

    return results


def format_resolve_results(results):
    if not results:
        return "入力が空です"

    blocks = []

    for r in results:
        if r["found"]:
            if r["is_range"]:
                block = format_span_result(r["display_name"], r["url"], r["note"])
            else:
                block = format_single_result(r["display_name"], r["url"], r["map_url"], r["note"])
        else:
            block = format_not_found(r["display_name"])

        blocks.append(block)

    return "\n\n".join(blocks)


# ----------------------------
# Routes
# ----------------------------
@app.route("/")
def index():
    return "LINE pole map bot is running."


@app.route("/healthz")
def healthz():
    return "ok", 200


@app.route("/map")
def map_view():
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)

    if lat is None or lng is None:
        return "invalid lat/lng", 400

    nearby = find_nearby(lat, lng, 200)

    return render_template(
        "map.html",
        lat=lat,
        lng=lng,
        nearby=nearby
    )


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


# ----------------------------
# LINE event helpers
# ----------------------------
def push_if_possible(to_id: str | None, text: str):
    if not to_id:
        return
    try:
        line_bot_api.push_message(to_id, TextSendMessage(text=text))
    except Exception as e:
        print(f"[push_if_possible] failed: {e}")


def process_text_logic(user_text: str) -> str:
    parsed = parse_latlng(user_text)
    if parsed:
        lat, lng = parsed
        nearby = find_nearby(lat, lng, 200)
        map_url = build_map_url(lat, lng)
        if nearby:
            return format_location_result(map_url, len(nearby))
        return format_location_empty(map_url)

    lines = split_input_lines(user_text)
    if not lines:
        return "入力が空です"

    # 複数行入力は検索専用として扱い、住所ジオコーディングには流さない
    if len(lines) >= 2:
        results = resolve_lines(user_text)
        return format_resolve_results(results)

    # 1行入力なら電柱検索 → ダメなら住所検索へ
    results = resolve_lines(user_text)
    if results and results[0]["found"]:
        return format_resolve_results(results)

    geo = geocode_address(user_text)
    if geo:
        lat, lng, address_name = geo
        map_url = build_map_url(lat, lng)
        return format_address_result(address_name, map_url)

    return format_resolve_results(results)


# ----------------------------
# LINE handlers
# ----------------------------
@handler.add(FollowEvent)
def handle_follow(event):
    try:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=MSG_FRIEND)
        )
    except Exception as e:
        print(f"[handle_follow] failed: {e}")


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    user_id = getattr(event.source, "user_id", None)

    done = {"flag": False}

    def delayed_notice():
        time.sleep(0.5)
        if not done["flag"]:
            push_if_possible(user_id, MSG_WAIT)

    threading.Thread(target=delayed_notice, daemon=True).start()

    try:
        reply_text = process_text_logic(user_text)
    finally:
        done["flag"] = True

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    lat = event.message.latitude
    lng = event.message.longitude

    title = event.message.title or "位置情報"
    address = event.message.address or ""

    header_lines = [title]
    if address:
        header_lines.append(address)

    header = "\n".join(header_lines)

    nearby = find_nearby(lat, lng, 200)
    map_url = build_map_url(lat, lng)

    if nearby:
        reply_text = format_location_result(map_url, len(nearby), header=header)
    else:
        reply_text = format_location_empty(map_url, header=header)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
