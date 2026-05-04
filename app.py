from flask import Flask, request, abort, render_template
import os
import json
import unicodedata
import re
import math
import urllib.parse
import urllib.request
import threading
import uuid
import time
import secrets
from datetime import datetime, timezone, timedelta

import redis
from dotenv import load_dotenv

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

load_dotenv()

# ----------------------------
# Env / Config
# ----------------------------
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")
REDIS_URL = os.getenv("REDIS_URL")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

MULTI_MAP_TTL_SECONDS = 60 * 60 * 24 * 7
JST = timezone(timedelta(hours=9))
BRANCH_LETTERS = "WNESGK"
NEAR_OFFSETS = [1, -1, 2, -2, 3, -3]
RANGE_PATTERN = re.compile(r"[～~]")
POLE_PATTERN = re.compile(rf"^(.*?)(\d+)((?:[{BRANCH_LETTERS}]\d+)*)$")

OPERATOR_USER_IDS = {
    x.strip() for x in os.getenv("OPERATOR_USER_IDS", "").split(",") if x.strip()
}

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
近くの電柱をまとめて確認できるよ🗺️"""

MSG_WAIT = """今探してるよ
少し待っててね🔎"""

MSG_REGISTER_GUIDE = """このアカウントはまだ利用登録されてないよ
会社管理者から招待コードをもらって、最初にこう送ってね

参加 招待コード

例
ABCD1234"""

MSG_ALREADY_REGISTERED = "このアカウントはもう登録済みだよ👌"

MSG_JOIN_SUCCESS = """利用登録が完了したよ🎉
これでいつも通り使えるようになったよ"""

MSG_JOIN_FAILED_INVALID = """招待コードを確認できなかったよ💦
英数字や空白の違いがないか見直してみてね"""

MSG_JOIN_FAILED_LIMIT = """この会社の利用人数が上限に達しとるよ
管理者に確認してみてね"""

MSG_JOIN_FAILED_INACTIVE = """この招待コードは使えない状態みたい
管理者に新しいコードを発行してもらってね"""

MSG_ACCESS_DENIED = """このアカウントではまだ利用できないよ
管理者から招待コードをもらって登録してね"""

# ----------------------------
# Common helpers
# ----------------------------
def now_iso():
    return datetime.now(JST).isoformat()


def parse_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    text = text.upper()
    return text


def remove_spaces(text: str) -> str:
    return re.sub(r"[ \u3000]+", "", str(text))


def normalize_key(text: str) -> str:
    return remove_spaces(normalize_text(text))


def normalize_input_line(text: str) -> str:
    return remove_spaces(normalize_text(text.strip()))


def split_input_lines(text: str):
    lines = [normalize_input_line(line) for line in text.splitlines()]
    return [line for line in lines if line]


def make_display_name(text: str) -> str:
    return remove_spaces(normalize_text(text))


def has_hikikomi(text: str) -> bool:
    return "引込" in text or "引き込み" in text


def normalize_invite_code(code: str) -> str:
    return remove_spaces(normalize_text(code or ""))


def generate_invite_code(length=8):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


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


def is_operator(user_id: str) -> bool:
    return bool(user_id) and user_id in OPERATOR_USER_IDS

# ----------------------------
# Redis JSON helpers
# ----------------------------
def redis_json_get(key):
    if not redis_client:
        return None

    raw = redis_client.get(key)
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def redis_json_set(key, value):
    if not redis_client:
        return False

    redis_client.set(key, json.dumps(value, ensure_ascii=False))
    return True


def get_company(company_id):
    return redis_json_get(f"company:{company_id}")


def save_company(company_data):
    payload = dict(company_data)
    now = now_iso()

    if "created_at" not in payload:
        payload["created_at"] = now
    payload["updated_at"] = now

    company_id = payload["company_id"]
    return redis_json_set(f"company:{company_id}", payload)


def get_user(user_id):
    return redis_json_get(f"user:{user_id}")


def save_user(user_data):
    payload = dict(user_data)
    now = now_iso()

    if "created_at" not in payload:
        payload["created_at"] = now
    payload["updated_at"] = now

    user_id = payload["user_id"]
    return redis_json_set(f"user:{user_id}", payload)


def get_invite(code):
    return redis_json_get(f"invite:{code}")


def save_invite(invite_data):
    payload = dict(invite_data)
    now = now_iso()

    if "created_at" not in payload:
        payload["created_at"] = now
    payload["updated_at"] = now

    code = payload["code"]
    return redis_json_set(f"invite:{code}", payload)


def add_user_to_company(company_id, user_id):
    if not redis_client:
        return 0
    return redis_client.sadd(f"company_users:{company_id}", user_id)


def remove_user_from_company(company_id, user_id):
    if not redis_client:
        return 0
    return redis_client.srem(f"company_users:{company_id}", user_id)


def count_company_users(company_id):
    if not redis_client:
        return 0
    return redis_client.scard(f"company_users:{company_id}")


def list_company_users(company_id):
    if not redis_client:
        return []
    return sorted(redis_client.smembers(f"company_users:{company_id}"))


def add_invite_to_company(company_id, code):
    if not redis_client:
        return 0
    return redis_client.sadd(f"company_invites:{company_id}", code)


def list_company_invite_codes(company_id):
    if not redis_client:
        return []
    return sorted(redis_client.smembers(f"company_invites:{company_id}"))


def count_keys_by_pattern(pattern: str) -> int:
    if not redis_client:
        return -1
    count = 0
    for _ in redis_client.scan_iter(match=pattern):
        count += 1
    return count

# ----------------------------
# User management helpers
# ----------------------------
def is_company_active(company_data):
    return bool(company_data) and company_data.get("status") == "active"


def is_user_active(user_data):
    return bool(user_data) and user_data.get("status") == "active"


def is_invite_expired(invite_data):
    expires_at = invite_data.get("expires_at")
    if not expires_at:
        return False

    dt = parse_iso(expires_at)
    if not dt:
        return False

    return datetime.now(JST) > dt


def touch_user(user_data):
    if not user_data:
        return

    payload = dict(user_data)
    payload["last_seen_at"] = now_iso()
    save_user(payload)


def is_user_allowed(user_id):
    if not user_id:
        return False, "user_id_missing", None, None

    user_data = get_user(user_id)
    if not user_data:
        return False, "user_not_registered", None, None

    if not is_user_active(user_data):
        return False, "user_disabled", user_data, None

    company_id = user_data.get("company_id")
    if not company_id:
        return False, "company_missing", user_data, None

    company_data = get_company(company_id)
    if not company_data:
        return False, "company_not_found", user_data, None

    if not is_company_active(company_data):
        return False, "company_inactive", user_data, company_data

    return True, "ok", user_data, company_data


def can_join_company(company_id):
    company_data = get_company(company_id)
    if not company_data:
        return False, "company_not_found", None

    if company_data.get("status") != "active":
        return False, "company_inactive", company_data

    user_limit = int(company_data.get("user_limit", 0) or 0)
    current_count = count_company_users(company_id)

    if user_limit > 0 and current_count >= user_limit:
        return False, "user_limit_reached", company_data

    return True, "ok", company_data


def create_company(company_id, name, user_limit, plan="subcontractor_basic", note=""):
    company_id = normalize_key(company_id)

    if not company_id:
        return False, "company_id_empty"

    if get_company(company_id):
        return False, "company_exists"

    company_data = {
        "company_id": company_id,
        "name": name.strip(),
        "status": "active",
        "plan": plan,
        "user_limit": int(user_limit),
        "admin_user_ids": [],
        "created_by": "operator",
        "note": note,
    }
    save_company(company_data)
    return True, company_id


def add_admin_to_company(company_id, user_id):
    company_data = get_company(company_id)
    if not company_data:
        return False, "company_not_found"

    admin_ids = company_data.get("admin_user_ids", [])
    if user_id not in admin_ids:
        admin_ids.append(user_id)

    company_data["admin_user_ids"] = admin_ids
    save_company(company_data)
    return True, "ok"


def create_invite(company_id, created_by, role="member", max_uses=1, expires_days=7):
    company_data = get_company(company_id)
    if not company_data:
        return False, "company_not_found", None

    if company_data.get("status") != "active":
        return False, "company_inactive", None

    code = generate_invite_code()

    expires_at = None
    if expires_days:
        expires_at = (datetime.now(JST) + timedelta(days=expires_days)).isoformat()

    invite_data = {
        "code": code,
        "company_id": company_id,
        "role": role,
        "status": "active",
        "created_by": created_by,
        "max_uses": int(max_uses),
        "used_count": 0,
        "expires_at": expires_at,
    }

    save_invite(invite_data)
    add_invite_to_company(company_id, code)
    return True, "ok", invite_data


def consume_invite(code):
    invite_data = get_invite(code)
    if not invite_data:
        return False, "invite_not_found", None

    if invite_data.get("status") != "active":
        return False, "invite_inactive", invite_data

    if is_invite_expired(invite_data):
        invite_data["status"] = "expired"
        save_invite(invite_data)
        return False, "invite_expired", invite_data

    max_uses = int(invite_data.get("max_uses", 1) or 1)
    used_count = int(invite_data.get("used_count", 0) or 0)

    if used_count >= max_uses:
        invite_data["status"] = "used_up"
        save_invite(invite_data)
        return False, "invite_limit_reached", invite_data

    invite_data["used_count"] = used_count + 1

    if invite_data["used_count"] >= max_uses:
        invite_data["status"] = "used_up"

    save_invite(invite_data)
    return True, "ok", invite_data


def join_company_with_invite(user_id, code):
    code = normalize_invite_code(code)
    if not code:
        return False, "invite_code_empty"

    existing_user = get_user(user_id)
    if existing_user and existing_user.get("status") == "active":
        return False, "already_registered"

    invite_data = get_invite(code)
    if not invite_data:
        return False, "invite_not_found"

    if invite_data.get("status") != "active":
        return False, "invite_inactive"

    if is_invite_expired(invite_data):
        invite_data["status"] = "expired"
        save_invite(invite_data)
        return False, "invite_expired"

    company_id = invite_data.get("company_id")
    role = invite_data.get("role", "member")

    ok, reason, company_data = can_join_company(company_id)
    if not ok:
        return False, reason

    ok, reason, invite_data = consume_invite(code)
    if not ok:
        return False, reason

    user_data = {
        "user_id": user_id,
        "company_id": company_id,
        "role": role,
        "status": "active",
        "joined_at": now_iso(),
        "invited_by": invite_data.get("created_by", ""),
        "invite_code": code,
        "display_name": "",
        "last_seen_at": now_iso(),
    }

    save_user(user_data)
    add_user_to_company(company_id, user_id)

    if role == "admin":
        add_admin_to_company(company_id, user_id)

    return True, "ok"


def disable_invite(company_id, code):
    code = normalize_invite_code(code)
    invite_data = get_invite(code)
    if not invite_data:
        return False, "invite_not_found"

    if invite_data.get("company_id") != company_id:
        return False, "company_mismatch"

    invite_data["status"] = "disabled"
    save_invite(invite_data)
    return True, "ok"

# ----------------------------
# Data
# ----------------------------
def load_pole_coords():
    with open("GPS.json", "r", encoding="utf-8") as f:
        raw = json.load(f)

    pole_coords = {}
    gps_points = []

    for raw_name, value in raw.items():
        try:
            lat_str, lng_str = str(value).split(",")
            lat = float(lat_str)
            lng = float(lng_str)
            latlon = f"{lat_str.strip()},{lng_str.strip()}"

            name = normalize_key(raw_name)

            pole_coords[name] = latlon
            gps_points.append({
                "name": raw_name,
                "search_name": name,
                "lat": lat,
                "lng": lng,
            })
        except Exception:
            pass

    return pole_coords, gps_points


POLE_COORDS, GPS_POINTS = load_pole_coords()

# ----------------------------
# Formatting helpers
# ----------------------------
def format_single_result(display_name: str, url: str, map_url=None, note=None) -> str:
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


def format_span_result(display_name: str, url: str, note=None) -> str:
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


def format_location_result(map_url: str, count: int, header=None) -> str:
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


def format_location_empty(map_url: str, header=None) -> str:
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


def format_multi_line_results(results, multi_map_url=None):
    found_results = [r for r in results if r["found"]]
    not_found_results = [r for r in results if not r["found"]]

    lines = []

    if found_results:
        lines.append(f"検索結果 {len(found_results)}件")
        lines.append("")

        for i, r in enumerate(found_results):
            lines.append(r["display_name"])
            lines.append(r["url"])

            if r["note"]:
                lines.append(f"{r['note']}")

            if i != len(found_results) - 1:
                lines.append("")

    if not_found_results:
        if lines:
            lines.append("")
        lines.append("見つからなかったもの")
        for r in not_found_results:
            lines.append(f"- {r['display_name']}")

    if multi_map_url:
        if lines:
            lines.append("")
        lines.append("複数の候補をまとめた地図はこちら🗺️")
        lines.append(multi_map_url)

    return "\n".join(lines)


def format_resolve_results(results, include_single_map=True, multi_map_url=None):
    if not results:
        return "入力が空です"

    if len(results) >= 2:
        return format_multi_line_results(results, multi_map_url=multi_map_url)

    blocks = []

    for r in results:
        if r["found"]:
            if r["is_range"]:
                block = format_span_result(r["display_name"], r["url"], r["note"])
            else:
                map_url = r["map_url"] if include_single_map else None
                block = format_single_result(r["display_name"], r["url"], map_url, r["note"])
        else:
            block = format_not_found(r["display_name"])

        blocks.append(block)

    text = "\n\n".join(blocks)

    if multi_map_url:
        text += f"\n\n複数の候補をまとめた地図はこちら🗺️\n{multi_map_url}"

    return text

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
    return f"{BASE_URL}/map?lat={lat}&lng={lng}"


def build_multi_map_url(points):
    payload = []
    for p in points:
        payload.append({
            "name": p["display_name"],
            "lat": p["lat"],
            "lng": p["lng"],
        })

    map_id = str(uuid.uuid4())

    if redis_client:
        redis_client.set(
            f"multi_map:{map_id}",
            json.dumps(payload, ensure_ascii=False),
            ex=MULTI_MAP_TTL_SECONDS,
        )
    else:
        print("[build_multi_map_url] REDIS_URL is not set")
        return None

    return f"{BASE_URL}/multi-map?id={map_id}"


def build_two_point_multi_map_url(p1_name: str, lat1: float, lng1: float, p2_name: str, lat2: float, lng2: float):
    q = urllib.parse.urlencode(
        {
            "p1n": p1_name or "始点",
            "p1": f"{lat1},{lng1}",
            "p2n": p2_name or "終点",
            "p2": f"{lat2},{lng2}",
        }
    )
    return f"{BASE_URL}/multi-map?{q}"


def resolve_span_endpoint_adopted(key: str):
    if not key:
        return None
    if exact_match(key):
        return key
    return find_first_existing(general_search_order(key))


def format_span_two_point_result(display_name: str, url: str, note=None) -> str:
    lines = [
        display_name,
        "始点と終点を2点で確認できる地図はこちら🗺️",
        url,
    ]
    if note:
        lines.extend(["", note])
    return "\n".join(lines)


def try_span_two_point_reply(line: str):
    info = create_search_keys(line)
    if not info["is_range"] or not info["back_key"] or info["hikikomi"]:
        return None

    k_front = resolve_span_endpoint_adopted(info["front_key"])
    k_back = resolve_span_endpoint_adopted(info["back_key"])
    if not k_front or not k_back:
        return None

    latlon1 = POLE_COORDS.get(k_front)
    latlon2 = POLE_COORDS.get(k_back)
    if not latlon1 or not latlon2:
        return None

    parsed1 = parse_latlng(latlon1)
    parsed2 = parse_latlng(latlon2)
    if not parsed1 or not parsed2:
        return None

    lat1, lng1 = parsed1
    lat2, lng2 = parsed2

    note = None
    notes = []
    if k_front != info["front_key"]:
        notes.append(f"始点（{info['front_key']}→{k_front}）")
    if k_back != info["back_key"]:
        notes.append(f"終点（{info['back_key']}→{k_back}）")
    if notes:
        note = "ぴったりの候補がなかったから近い候補で案内してるよ\n" + "\n".join(notes)

    url = build_two_point_multi_map_url(
        info["front_key"], lat1, lng1, info["back_key"], lat2, lng2
    )
    return format_span_two_point_result(info["display_name"], url, note)


def extract_found_points(results):
    points = []

    for r in results:
        if not r["found"]:
            continue

        if not r["adopted"]:
            continue

        latlon = POLE_COORDS.get(r["adopted"])
        if not latlon:
            continue

        parsed = parse_latlng(latlon)
        if not parsed:
            continue

        lat, lng = parsed

        points.append({
            "display_name": r["display_name"],
            "lat": lat,
            "lng": lng,
        })

    return points

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
    for letter, num in re.findall(rf"([{BRANCH_LETTERS}])(\d+)", branch_str):
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

    m_num = re.match(rf"^(\d+)((?:[{BRANCH_LETTERS}]\d+)*)$", back_raw)
    if m_num:
        parent = int(m_num.group(1))
        branch_str = m_num.group(2)
        branches = [(l, int(n)) for l, n in re.findall(rf"([{BRANCH_LETTERS}])(\d+)", branch_str)]
        return build_pole_name(front["place"], parent, branches)

    m_branch_only = re.match(rf"^((?:[{BRANCH_LETTERS}]\d+)+)$", back_raw)
    if m_branch_only:
        back_branches = [(l, int(n)) for l, n in re.findall(rf"([{BRANCH_LETTERS}])(\d+)", back_raw)]
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

    if is_hazard_g9_candidate(place, parent):
        result.append(hazard_g9_name(place, parent))

    plus_1 = build_pole_name(place, parent + 1, [])
    minus_1 = build_pole_name(place, parent - 1, []) if parent - 1 > 0 else None

    if plus_1:
        result.append(plus_1)
    if minus_1:
        result.append(minus_1)

    for letter in ["W", "E", "N", "S", "G", "K"]:
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

    if len(lines) >= 2:
        results = resolve_lines(user_text)
        points = extract_found_points(results)

        multi_map_url = None
        if len(points) >= 2:
            multi_map_url = build_multi_map_url(points)

        return format_resolve_results(
            results,
            include_single_map=False,
            multi_map_url=multi_map_url
        )

    span_two = try_span_two_point_reply(lines[0])
    if span_two is not None:
        return span_two

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
# Management command handlers
# ----------------------------
def format_company_info(company_data):
    return (
        f"会社ID: {company_data.get('company_id')}\n"
        f"会社名: {company_data.get('name')}\n"
        f"状態: {company_data.get('status')}\n"
        f"プラン: {company_data.get('plan')}\n"
        f"人数上限: {company_data.get('user_limit')}\n"
        f"登録人数: {count_company_users(company_data.get('company_id'))}人\n"
        f"管理者数: {len(company_data.get('admin_user_ids', []))}人"
    )


def process_operator_command(user_id, user_text):
    if not user_text.startswith("運営 "):
        return None

    if not is_operator(user_id):
        return "運営コマンドを使える権限がないよ"

    parts = user_text.split(maxsplit=4)
    if len(parts) < 2:
        return "運営コマンドの形式が不正だよ"

    action = parts[1]

    if action == "会社作成":
        if len(parts) < 5:
            return "使い方: 運営 会社作成 company_id 人数上限 会社名"

        company_id = parts[2]
        try:
            user_limit = int(parts[3])
        except ValueError:
            return "人数上限は数字で入れてね"

        company_name = parts[4]
        ok, result = create_company(company_id, company_name, user_limit)
        if not ok:
            if result == "company_exists":
                return "その会社IDはもう使われとるよ"
            return f"会社作成に失敗したよ: {result}"

        company_data = get_company(result)
        return f"会社を作成したよ👌\n\n{format_company_info(company_data)}"

    if action == "会社情報":
        if len(parts) < 3:
            return "使い方: 運営 会社情報 company_id"

        company_id = normalize_key(parts[2])
        company_data = get_company(company_id)
        if not company_data:
            return "会社が見つからんかったよ"

        return format_company_info(company_data)

    if action == "会社停止":
        if len(parts) < 3:
            return "使い方: 運営 会社停止 company_id"

        company_id = normalize_key(parts[2])
        company_data = get_company(company_id)
        if not company_data:
            return "会社が見つからんかったよ"

        company_data["status"] = "suspended"
        save_company(company_data)
        return f"{company_id} を停止したよ"

    if action == "会社再開":
        if len(parts) < 3:
            return "使い方: 運営 会社再開 company_id"

        company_id = normalize_key(parts[2])
        company_data = get_company(company_id)
        if not company_data:
            return "会社が見つからんかったよ"

        company_data["status"] = "active"
        save_company(company_data)
        return f"{company_id} を再開したよ"

    if action == "管理招待作成":
        if len(parts) < 3:
            return "使い方: 運営 管理招待作成 company_id [回数]"

        company_id = normalize_key(parts[2])
        max_uses = 1

        if len(parts) >= 4:
            try:
                max_uses = int(parts[3])
            except ValueError:
                return "回数は数字で入れてね"

        ok, reason, invite_data = create_invite(
            company_id=company_id,
            created_by=user_id,
            role="admin",
            max_uses=max_uses,
            expires_days=7,
        )
        if not ok:
            return f"管理者招待コードの作成に失敗したよ: {reason}"

        return (
            "管理者用の招待コードを作成したよ\n"
            f"会社ID: {company_id}\n"
            f"コード: {invite_data['code']}\n"
            f"回数: {invite_data['max_uses']}\n"
            f"期限: {invite_data.get('expires_at') or 'なし'}"
        )

    if action == "Redis確認":
        company_count = count_keys_by_pattern("company:*")
        user_count = count_keys_by_pattern("user:*")
        invite_count = count_keys_by_pattern("invite:*")
        company_users_count = count_keys_by_pattern("company_users:*")
        multi_map_count = count_keys_by_pattern("multi_map:*")

        return (
            "Redis確認\n"
            f"company:* {company_count}件\n"
            f"user:* {user_count}件\n"
            f"invite:* {invite_count}件\n"
            f"company_users:* {company_users_count}件\n"
            f"multi_map:* {multi_map_count}件"
        )

    return "その運営コマンドはまだ対応してないよ"


def process_admin_command(user_id, user_text, user_data):
    role = user_data.get("role")
    company_id = user_data.get("company_id")

    if role not in ("admin", "operator"):
        return None

    if user_text.startswith("招待作成"):
        parts = user_text.split(maxsplit=1)
        max_uses = 1

        if len(parts) >= 2:
            try:
                max_uses = int(parts[1])
            except ValueError:
                return "使い方: 招待作成 または 招待作成 3"

        ok, reason, invite_data = create_invite(
            company_id=company_id,
            created_by=user_id,
            role="member",
            max_uses=max_uses,
            expires_days=7,
        )
        if not ok:
            return f"招待コード作成に失敗したよ: {reason}"

        return (
            "招待コードを作成したよ👌\n"
            f"コード: {invite_data['code']}\n"
            f"回数: {invite_data['max_uses']}\n"
            f"期限: {invite_data.get('expires_at') or 'なし'}"
        )

    if user_text == "招待一覧":
        codes = list_company_invite_codes(company_id)
        if not codes:
            return "この会社の招待コードはまだないよ"

        lines = ["招待コード一覧"]
        for code in codes:
            invite_data = get_invite(code)
            if not invite_data:
                continue
            lines.append(
                f"{code} / {invite_data.get('role')} / "
                f"{invite_data.get('status')} / "
                f"{invite_data.get('used_count', 0)}/{invite_data.get('max_uses', 1)}"
            )

        return "\n".join(lines)

    if user_text.startswith("招待停止"):
        parts = user_text.split(maxsplit=1)
        if len(parts) < 2:
            return "使い方: 招待停止 コード"

        code = parts[1].strip()
        ok, reason = disable_invite(company_id, code)
        if not ok:
            return f"招待停止に失敗したよ: {reason}"

        return f"{normalize_invite_code(code)} を停止したよ"

    if user_text == "利用者一覧":
        user_ids = list_company_users(company_id)
        if not user_ids:
            return "利用者はまだ登録されとらんよ"

        lines = [f"利用者一覧 {len(user_ids)}人"]
        for uid in user_ids:
            u = get_user(uid)
            if not u:
                continue
            role = u.get("role", "")
            status = u.get("status", "")
            lines.append(f"{role} / {status} / {uid}")

        return "\n".join(lines)

    return None

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


@app.route("/multi-map")
def multi_map_view():
    map_id = request.args.get("id")

    if map_id:
        if not redis_client:
            return "redis is not configured", 500

        raw = redis_client.get(f"multi_map:{map_id}")

        if not raw:
            return "data expired or not found", 404

        try:
            points = json.loads(raw)
        except Exception:
            return "invalid stored data", 500

        valid_points = []

        for p in points:
            try:
                lat = float(p["lat"])
                lng = float(p["lng"])
                name = str(p.get("name", "電柱"))

                valid_points.append({
                    "name": name,
                    "lat": lat,
                    "lng": lng,
                })
            except Exception:
                pass

        if not valid_points:
            return "no valid points", 400

        return render_template("multi_map.html", points=valid_points)

    p1 = request.args.get("p1")
    p2 = request.args.get("p2")
    if p1 and p2:
        p1n = request.args.get("p1n") or "始点"
        p2n = request.args.get("p2n") or "終点"
        ll1 = parse_latlng(p1)
        ll2 = parse_latlng(p2)
        if not ll1 or not ll2:
            return "invalid p1/p2", 400

        lat1, lng1 = ll1
        lat2, lng2 = ll2
        valid_points = [
            {"name": str(p1n), "lat": lat1, "lng": lng1},
            {"name": str(p2n), "lat": lat2, "lng": lng2},
        ]
        return render_template("multi_map.html", points=valid_points)

    return "missing id or p1/p2", 400


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
def push_if_possible(to_id=None, text=""):
    if not to_id:
        return
    try:
        line_bot_api.push_message(to_id, TextSendMessage(text=text))
    except Exception as e:
        print(f"[push_if_possible] failed: {e}")


def reply_text_message(reply_token, text):
    line_bot_api.reply_message(reply_token, TextSendMessage(text=text))

# ----------------------------
# LINE handlers
# ----------------------------
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = getattr(event.source, "user_id", None)

    allowed, _, _, _ = is_user_allowed(user_id)
    if allowed:
        text = MSG_FRIEND
    else:
        text = f"{MSG_FRIEND}\n\n{MSG_REGISTER_GUIDE}"

    try:
        reply_text_message(event.reply_token, text)
    except Exception as e:
        print(f"[handle_follow] failed: {e}")


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    user_id = getattr(event.source, "user_id", None)

    # 運営コマンドは未登録でも通す
    operator_reply = process_operator_command(user_id, user_text)
    if operator_reply is not None:
        reply_text_message(event.reply_token, operator_reply)
        return

    # 通常利用可否判定
    allowed, reason, user_data, company_data = is_user_allowed(user_id)
    # temporary recovery mode: 利用者管理の不整合解消まで通常利用制限を無効化
    allowed = True

    # temporary recovery mode: 未登録ユーザーの参加案内/利用ブロックを一時停止
    # if not allowed:
    #     candidate_code = user_text
    #
    #     if user_text.startswith("参加"):
    #         parts = user_text.split(maxsplit=1)
    #         candidate_code = parts[1].strip() if len(parts) >= 2 else ""
    #
    #     normalized_code = normalize_invite_code(candidate_code)
    #     invite_data = get_invite(normalized_code) if normalized_code else None
    #
    #     if invite_data:
    #         ok, join_reason = join_company_with_invite(user_id, normalized_code)
    #
    #         if ok:
    #             reply_text = MSG_JOIN_SUCCESS
    #         elif join_reason == "already_registered":
    #             reply_text = MSG_ALREADY_REGISTERED
    #         elif join_reason in ("user_limit_reached",):
    #             reply_text = MSG_JOIN_FAILED_LIMIT
    #         elif join_reason in ("company_inactive", "invite_inactive", "invite_limit_reached", "invite_expired"):
    #             reply_text = MSG_JOIN_FAILED_INACTIVE
    #         else:
    #             reply_text = MSG_JOIN_FAILED_INVALID
    #
    #         reply_text_message(event.reply_token, reply_text)
    #         return
    #
    #     reply_text_message(event.reply_token, MSG_REGISTER_GUIDE)
    #     return

    # 管理者コマンド
    admin_reply = process_admin_command(user_id, user_text, user_data) if user_data else None
    if admin_reply is not None:
        touch_user(user_data)
        reply_text_message(event.reply_token, admin_reply)
        return

    done = {"flag": False}

    def delayed_notice():
        time.sleep(3)
        if not done["flag"]:
            push_if_possible(user_id, MSG_WAIT)

    threading.Thread(target=delayed_notice, daemon=True).start()

    try:
        reply_text = process_text_logic(user_text)
    finally:
        done["flag"] = True

    touch_user(user_data)
    reply_text_message(event.reply_token, reply_text)


@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):
    user_id = getattr(event.source, "user_id", None)
    allowed, reason, user_data, company_data = is_user_allowed(user_id)
    # temporary recovery mode: 利用者管理の不整合解消まで位置情報利用制限を無効化
    # if not allowed:
    #     reply_text_message(event.reply_token, MSG_ACCESS_DENIED)
    #     return

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

    touch_user(user_data)
    reply_text_message(event.reply_token, reply_text)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))