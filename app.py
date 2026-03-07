from flask import Flask, request, abort
import json
import math
import os

from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, LocationMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

with open("coords.json", "r", encoding="utf-8") as f:
    coords = json.load(f)

def distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2-lat1)
    dlambda = math.radians(lon2-lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=LocationMessage)
def handle_location(event):

    user_lat = event.message.latitude
    user_lon = event.message.longitude

    nearest_name = None
    nearest_lat = None
    nearest_lon = None
    min_dist = 999999999

    for name, coord in coords.items():

        lat_str, lon_str = coord.split(",")

        lat = float(lat_str)
        lon = float(lon_str)

        d = distance(user_lat, user_lon, lat, lon)

        if d < min_dist:
            min_dist = d
            nearest_name = name
            nearest_lat = lat
            nearest_lon = lon

    text = f"""最寄り地点
{nearest_name}
距離: {int(min_dist)}m
https://www.google.com/maps?q={nearest_lat},{nearest_lon}
"""

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=text)
    )


if __name__ == "__main__":
    app.run()

