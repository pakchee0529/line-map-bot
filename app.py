from linebot.models import MessageEvent, TextMessage, TextSendMessage
import unicodedata
import re
import difflib

def normalize(text):

    text = unicodedata.normalize("NFKC", text)
    text = text.upper()
    text = text.replace(" ", "")

    return text


@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):

    user_text = normalize(event.message.text)

    # 正規化辞書作成
    normalized_map = {normalize(k): k for k in coords.keys()}

    # 完全一致
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

        # 部分一致
        if candidate is None:

            base = re.sub(r"N\d+", "", user_text)

            for nk, original in normalized_map.items():

                if base in nk:
                    candidate = original
                    break

        # 類似検索
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
