from flask import Flask, request, abort
import json
import os
import unicodedata
import re
import difflib

from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError


app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


with open("coords.json", "r", encoding="utf-8") as f:
    coords = json.load(f)


def normalize(text):

    text = unicodedata.normalize("NFKC", text)
    text = text.upper()
    text = text.replace(" ", "")

    return text


@app.route("/callback", methods=['POST'])
def callback():

    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):

    user_text = normalize(event.message.text)

    normalized_map = {normalize(k): k for k in coords.keys()}

    if user_text in normalized_map:

        key = normalized_map[user_text]

        lat, lon = coords[key].split(",")

        url = f"https://maps.google.com/?q={lat},{lon}"

        text = f"{key}\n{url}"

    else:

        candidate = None

        match = re.match(r"(.*N)(\d+)", user_text)

        if match:

            prefix = match.group(1)
            num = int(match.group(2))

            for i in [num-1, num+1]:

                key_try = f"{prefix}{i}"

                if key_try in normalized_map:
                    candidate = normalized_map[key_try]
                    break

        if candidate is None:

            base = re.sub(r"N\d+", "", user_text)

            for nk, original in normalized_map.items():

                if base in nk:
                    candidate = original
                    break

        if candidate is None:

            close = difflib.get_close_matches(user_text, normalized_map.keys(), n=1, cutoff=0.6)

            if close:
                candidate = normalized_map[close[0]]

        if candidate:

            lat, lon = coords[candidate].split(",")

            url = f"https://maps.google.com/?q={lat},{lon}"

            text = f"""指定の電柱は見つかりませんでした

最寄り候補
{candidate}

{url}"""

        else:

            text = "該当する電柱が見つかりませんでした"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=text)
    )


if __name__ == "__main__":
    app.run()
