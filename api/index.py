from flask import Flask, request, jsonify
import requests
import os
import re
from datetime import datetime

app = Flask(__name__)

USER_STATE = {}
# 常用城市 / 機場對照表。
# SerpApi Google Flights 可以接受 IATA 機場代碼，多機場城市可用逗號分隔。
AIRPORT_MAP = {
    # Taiwan
    "台北": "TPE",
    "臺北": "TPE",
    "台北市": "TPE",
    "臺北市": "TPE",
    "桃園": "TPE",
    "桃園機場": "TPE",
    "桃園國際機場": "TPE",
    "松山": "TSA",
    "松山機場": "TSA",
    "高雄": "KHH",
    "小港": "KHH",
    "台中": "RMQ",
    "臺中": "RMQ",

    # Japan
    "東京": "NRT,HND",
    "東京都": "NRT,HND",
    "成田": "NRT",
    "成田機場": "NRT",
    "羽田": "HND",
    "羽田機場": "HND",
    "大阪": "KIX,ITM",
    "大阪市": "KIX,ITM",
    "關西": "KIX",
    "關西機場": "KIX",
    "伊丹": "ITM",
    "伊丹機場": "ITM",
    "京都": "KIX,ITM",
    "名古屋": "NGO",
    "中部": "NGO",
    "福岡": "FUK",
    "札幌": "CTS",
    "新千歲": "CTS",
    "沖繩": "OKA",
    "沖縄": "OKA",
    "那霸": "OKA",
    "那覇": "OKA",

    # Korea
    "首爾": "ICN,GMP",
    "首爾市": "ICN,GMP",
    "韓國": "ICN,GMP",
    "仁川": "ICN",
    "仁川機場": "ICN",
    "金浦": "GMP",
    "釜山": "PUS",

    # Asia
    "曼谷": "BKK,DMK",
    "廊曼": "DMK",
    "清邁": "CNX",
    "香港": "HKG",
    "澳門": "MFM",
    "新加坡": "SIN",
    "吉隆坡": "KUL",
    "胡志明": "SGN",
    "河內": "HAN",
    "峴港": "DAD",
    "馬尼拉": "MNL",
    "宿霧": "CEB",
    "雅加達": "CGK",
    "峇里島": "DPS",
    "登巴薩": "DPS",

    # Europe / US
    "巴黎": "CDG,ORY",
    "倫敦": "LHR,LGW,STN,LTN",
    "紐約": "JFK,LGA,EWR",
    "洛杉磯": "LAX",
    "舊金山": "SFO",
    "西雅圖": "SEA",
    "溫哥華": "YVR",
}


@app.route("/", methods=["GET"])
def home():
    return "Flight webhook is running."


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    """Dialogflow ES webhook."""
    if request.method == "GET":
        return "Webhook endpoint is running. Please use POST from Dialogflow."

    req = request.get_json(silent=True)

    if not req:
        return jsonify({
            "fulfillmentText": "Webhook 有收到請求，但沒有收到 JSON 資料。"
        })

    parameters = req.get("queryResult", {}).get("parameters", {})

    origin = parameters.get("origin", "臺北")
    destination = parameters.get("destination", "東京")
    date = parameters.get("date", "")

    origin_code = resolve_airport_code(origin)
    destination_code = resolve_airport_code(destination)
    outbound_date = format_dialogflow_date(date)

    if not outbound_date:
        return jsonify({
            "fulfillmentText": "我有收到查詢，但日期格式不完整。請輸入像「7月10號」或「2026-07-10」這樣的日期。"
        })

    if not origin_code or not destination_code:
        reply = build_location_error_reply(origin, destination)
        return jsonify({"fulfillmentText": reply})

    flights = search_flights_from_serpapi(origin_code, destination_code, outbound_date)
    reply_messages = build_reply_messages(origin, destination, outbound_date, flights)

    return jsonify({
        "fulfillmentText": "\n\n".join(reply_messages),
        "fulfillmentMessages": [
            {"text": {"text": [message]}}
            for message in reply_messages
        ]
    })


@app.route("/line-webhook", methods=["GET", "POST"])
def line_webhook():
    """LINE Messaging API webhook."""
    if request.method == "GET":
        return "LINE webhook endpoint is running."

    data = request.get_json(silent=True)

    if not data:
        return "No JSON received", 400

    events = data.get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        reply_token = event.get("replyToken")

        if message.get("type") == "text" and reply_token:
            user_text = message.get("text", "")
            user_id = event.get("source", {}).get("userId", "unknown_user")
            reply_text = handle_line_message(user_id, user_text)
            reply_to_line(reply_token, reply_text)

    return "OK", 200


# -----------------------------
# 地點解析 / 機場代碼轉換
# -----------------------------

def normalize_place_name(place):
    if not place:
        return ""

    normalized = str(place).strip()

    replace_words = [
        "國際機場",
        "国际机场",
        "機場",
        "机场",
        "城市",
        "市",
        "縣",
        "县",
        "県",
        "府",
        "都",
        "區",
        "区",
        "省",
        "州",
        " ",
        "　",
    ]

    for word in replace_words:
        normalized = normalized.replace(word, "")

    return normalized.strip()


def resolve_airport_code(place):
    """
    將中文地名 / 機場名 / IATA 代碼轉成 SerpApi 可用的機場代碼。
    找不到時回傳 None。
    """
    if not place:
        return None

    place = str(place).strip()

    # 使用者直接輸入 TPE、NRT、KIX 這類 IATA code。
    if len(place) == 3 and place.isalpha():
        return place.upper()

    # 使用者輸入 NRT,HND 這類多機場代碼。
    if re.fullmatch(r"[A-Za-z]{3}(,[A-Za-z]{3})+", place):
        return place.upper()

    # 直接查本地表。
    if place in AIRPORT_MAP:
        return AIRPORT_MAP[place]

    # 清理行政區、機場等尾字後再查。
    normalized_place = normalize_place_name(place)
    if normalized_place in AIRPORT_MAP:
        return AIRPORT_MAP[normalized_place]

    # 模糊比對：大阪市、東京都、台北市這類字串。
    for key, code in AIRPORT_MAP.items():
        if key in place or place in key:
            return code

    for key, code in AIRPORT_MAP.items():
        normalized_key = normalize_place_name(key)
        if normalized_key and (normalized_key in normalized_place or normalized_place in normalized_key):
            return code

    return None


# 保留舊函式名稱，避免其他地方還有呼叫 convert_to_airport_code。
def convert_to_airport_code(place):
    return resolve_airport_code(place)


def is_valid_flight_location_id(value):
    """SerpApi Google Flights 可接受 IATA 代碼、多機場代碼，或 /m、/g 開頭的 location id。"""
    if not value:
        return False

    value = str(value).strip()

    if re.fullmatch(r"[A-Z]{3}(,[A-Z]{3})*", value):
        return True

    if value.startswith("/m") or value.startswith("/g"):
        return True

    return False


# -----------------------------
# 使用者文字解析
# -----------------------------

def parse_user_query(user_text):
    """
    解析 LINE 使用者輸入。
    支援範例：
    - 我想查 7月10號 台北到東京的便宜機票
    - 我想知道 2026-07-10 台北飛大阪多少錢
    - 台北飛成田 7月10號
    - 2026-07-10 TPE飛KIX
    """
    origin = None
    destination = None
    outbound_date = parse_date_from_text(user_text)

    # A 到 B / A 飛 B / A 去 B
    route_match = re.search(
        r"(?:從)?(.+?)(?:到|飛|飞|去|前往)(.+?)(?:的|便宜|機票|机票|多少錢|多少钱|價格|价格|$)",
        user_text
    )

    if route_match:
        before = route_match.group(1)
        after = route_match.group(2)
        origin = find_place_in_text(before)
        destination = find_place_in_text(after)

    return origin, destination, outbound_date


def parse_date_from_text(text):
    if not text:
        return None

    # 2026-07-10 / 2026/07/10 / 2026.07.10
    date_match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if date_match:
        year = int(date_match.group(1))
        month = int(date_match.group(2))
        day = int(date_match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # 7月10號 / 7月10日
    date_match = re.search(r"(\d{1,2})月(\d{1,2})(?:號|号|日)?", text)
    if date_match:
        current_year = datetime.now().year
        month = int(date_match.group(1))
        day = int(date_match.group(2))
        return f"{current_year:04d}-{month:02d}-{day:02d}"

    return None


def find_place_in_text(text):
    if not text:
        return None

    text = str(text).strip()

    # 先抓 IATA code，例如：TPE飛KIX。
    code_match = re.search(r"\b[A-Za-z]{3}\b", text)
    if code_match:
        return code_match.group(0).upper()

    # 先找完整 key，長字串優先，避免「大阪市」先被「大阪」吃掉。
    for place in sorted(AIRPORT_MAP.keys(), key=len, reverse=True):
        if place in text:
            return place

    normalized_text = normalize_place_name(text)

    for place in sorted(AIRPORT_MAP.keys(), key=len, reverse=True):
        normalized_place = normalize_place_name(place)
        if normalized_place and normalized_place in normalized_text:
            return place

    # 找不到時回傳清理後文字，讓 resolve_airport_code() 再試一次。
    return normalized_text or text


# -----------------------------
# LINE 查詢流程
# -----------------------------

def handle_line_flight_query(user_text):
    origin, destination, outbound_date = parse_user_query(user_text)

    if not outbound_date:
        return (
            "我有看到你想查機票，但還缺日期。\n\n"
            "請用這種格式輸入：\n"
            "2026-07-10 台北飛大阪\n"
            "或：7月10號 台北到東京"
        )

    if not origin or not destination:
        return build_location_error_reply(origin, destination)

    origin_code = resolve_airport_code(origin)
    destination_code = resolve_airport_code(destination)

    if not origin_code or not destination_code:
        return build_location_error_reply(origin, destination)

    flights = search_flights_from_serpapi(origin_code, destination_code, outbound_date)
    messages = build_reply_messages(origin, destination, outbound_date, flights)

    return "\n\n".join(messages)


def build_location_error_reply(origin=None, destination=None):
    if not origin:
        return (
            "我沒有判斷出出發地。\n\n"
            "請用這種格式輸入：\n"
            "2026-07-10 台北飛大阪"
        )

    if not destination:
        return (
            "我沒有判斷出目的地。\n\n"
            "請用這種格式輸入：\n"
            "2026-07-10 台北飛大阪"
        )

    return (
        f"我目前無法判斷「{origin}」或「{destination}」對應的機場。\n\n"
        "你可以改用城市、機場名稱或 IATA 代碼，例如：\n"
        "台北、東京、大阪、成田、羽田、首爾、香港、TPE、NRT、KIX。"
    )


# -----------------------------
# Dialogflow / SerpApi / LINE 工具函式
# -----------------------------

def format_dialogflow_date(date_value):
    if not date_value:
        return None

    date_text = str(date_value)

    # Dialogflow 常會回傳：2026-07-10T12:00:00+08:00
    # SerpApi 需要：2026-07-10
    if len(date_text) >= 10:
        return date_text[:10]

    return None


def search_flights_from_serpapi(origin_code, destination_code, outbound_date):
    # 防呆：不管前面傳進來的是「大阪市」還是「KIX,ITM」，
    # 這裡都再轉換一次，避免 SerpApi 收到中文地名後報錯。
    origin_code = resolve_airport_code(origin_code) or origin_code
    destination_code = resolve_airport_code(destination_code) or destination_code

    if not is_valid_flight_location_id(origin_code):
        return {
            "error": "INVALID_LOCATION_ID",
            "message": f"出發地代碼不正確：{origin_code}",
        }

    if not is_valid_flight_location_id(destination_code):
        return {
            "error": "INVALID_LOCATION_ID",
            "message": f"目的地代碼不正確：{destination_code}",
        }

    api_key = os.environ.get("SERPAPI_KEY")

    if not api_key:
        return {"error": "SERPAPI_KEY_NOT_FOUND"}

    url = "https://serpapi.com/search"

    params = {
        "engine": "google_flights",
        "departure_id": origin_code,
        "arrival_id": destination_code,
        "outbound_date": outbound_date,
        "type": "2",  # 2 = 單程票；來回票之後再加 return_date 與 type=1
        "currency": "TWD",
        "hl": "zh-tw",
        "api_key": api_key,
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
    except Exception as e:
        return {
            "error": "REQUEST_FAILED",
            "message": str(e),
        }

    if "error" in data:
        return {
            "error": "SERPAPI_ERROR",
            "message": data.get("error"),
        }

    results = []
    all_flights = []
    all_flights.extend(data.get("best_flights", []))
    all_flights.extend(data.get("other_flights", []))

    for item in all_flights[:5]:
        flight_segments = item.get("flights", [])

        if not flight_segments:
            continue

        first_segment = flight_segments[0]
        last_segment = flight_segments[-1]

        airline = first_segment.get("airline", "未提供航空公司")
        departure_airport = first_segment.get("departure_airport", {})
        arrival_airport = last_segment.get("arrival_airport", {})

        departure_time = departure_airport.get("time", "未提供")
        arrival_time = arrival_airport.get("time", "未提供")

        price = item.get("price", "未提供")
        duration = item.get("total_duration", "未提供")

        if len(flight_segments) == 1:
            transfer_text = "直飛"
        else:
            transfer_text = f"轉機 {len(flight_segments) - 1} 次"

        results.append({
            "airline": airline,
            "price": price,
            "departure_time": departure_time,
            "arrival_time": arrival_time,
            "duration": duration,
            "transfer": transfer_text,
            "include": "實際行李、餐點與票種內容請以購買平台顯示為準。",
        })

    return results


def build_reply_messages(origin, destination, outbound_date, flights):
    if isinstance(flights, dict) and flights.get("error") == "SERPAPI_KEY_NOT_FOUND":
        return ["目前 Vercel 尚未設定 SERPAPI_KEY，所以無法查詢真實機票資料。"]

    if isinstance(flights, dict) and flights.get("error") == "REQUEST_FAILED":
        return [f"查詢機票 API 時發生連線問題：{flights.get('message')}"]

    if isinstance(flights, dict) and flights.get("error") == "SERPAPI_ERROR":
        return [f"SerpApi 回傳錯誤：{flights.get('message')}"]

    if isinstance(flights, dict) and flights.get("error") == "INVALID_LOCATION_ID":
        return [f"地點轉換失敗：{flights.get('message')}。請改用城市、機場名稱或三碼機場代碼，例如台北、東京、大阪、TPE、NRT、KIX。"]

    if not flights:
        return [f"目前查不到 {origin} 到 {destination} 在 {outbound_date} 的機票資料。"]

    display_flights = flights[:3]

    messages = [
        f"我幫你查到 {len(display_flights)} 筆 {origin} 到 {destination} 在 {outbound_date} 的機票："
    ]

    for index, flight in enumerate(display_flights, start=1):
        message = (
            f"第 {index} 筆\n"
            f"航空：{flight['airline']}\n"
            f"價格：約 NT${flight['price']}\n"
            f"時間：{flight['departure_time']} → {flight['arrival_time']}\n"
            f"航程：{flight['duration']} 分鐘\n"
            f"轉機：{flight['transfer']}\n"
            f"備註：{flight['include']}"
        )
        messages.append(message)

    messages.append("提醒：機票價格會即時變動，實際金額與行李規則請以購買頁面為準。")

    return messages


def reply_to_line(reply_token, reply_text):
    channel_access_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

    if not channel_access_token:
        print("LINE_CHANNEL_ACCESS_TOKEN not found")
        return

    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}",
    }

    # LINE 單一 text message 有長度限制。這裡保守切成最多 5 則。
    messages = []
    for chunk in split_line_text(reply_text):
        messages.append({"type": "text", "text": chunk})
        if len(messages) >= 5:
            break

    body = {
        "replyToken": reply_token,
        "messages": messages,
    }

    response = requests.post(url, headers=headers, json=body, timeout=20)

    print("LINE reply status:", response.status_code)
    print("LINE reply response:", response.text)


def split_line_text(text, limit=4500):
    """避免 LINE 單則訊息過長；優先用空行切段。"""
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""

    for part in text.split("\n\n"):
        candidate = part if not current else current + "\n\n" + part
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part

    if current:
        chunks.append(current)

    return chunks

def handle_line_message(user_id, user_text):
    user_text = user_text.strip()

    state = USER_STATE.get(user_id, {
        "step": "IDLE"
    })

    # 使用者開始查機票
    if user_text in ["我想查機票", "查機票", "機票"]:
        USER_STATE[user_id] = {
            "step": "WAITING_DATE"
        }

        return (
            "請輸入出發日期。\n\n"
            "例如：\n"
            "2026-07-10\n"
            "或：7月10號"
        )

    # 等待使用者輸入日期
    if state.get("step") == "WAITING_DATE":
        outbound_date = parse_date_from_text(user_text)

        if not outbound_date:
            return (
                "我沒有判斷出日期。\n\n"
                "請輸入這種格式：\n"
                "2026-07-10\n"
                "或：7月10號"
            )

        USER_STATE[user_id] = {
            "step": "WAITING_ROUTE",
            "date": outbound_date
        }

        return (
            f"收到，出發日期是 {outbound_date}。\n\n"
            "請輸入出發地與目的地。\n"
            "例如：台北飛大阪"
        )

    # 等待使用者輸入路線
    if state.get("step") == "WAITING_ROUTE":
        origin, destination = parse_route_from_text(user_text)

        if not origin or not destination:
            return (
                "我沒有判斷出出發地與目的地。\n\n"
                "請輸入這種格式：\n"
                "台北飛大阪\n"
                "或：台北到東京"
            )

        outbound_date = state.get("date")

        USER_STATE[user_id] = {
            "step": "RESULT_READY",
            "date": outbound_date,
            "origin": origin,
            "destination": destination
        }

        return (
            f"收到，準備查詢：\n"
            f"日期：{outbound_date}\n"
            f"路線：{origin} → {destination}\n\n"
            "下一步會接上機票 API 查詢。"
        )

    # 使用者詢問如何購買
    if user_text in ["如何購買", "怎麼買", "我要怎麼買"]:
        if state.get("step") != "RESULT_READY":
            return "請先查詢一次機票，再輸入「如何購買」。"

        return (
            "你可以依照上一筆查詢結果，到 Google Flights、航空公司官網或訂票平台確認。\n\n"
            "實際購買前建議確認：\n"
            "1. 最終票價\n"
            "2. 是否含托運行李\n"
            "3. 是否需要轉機\n"
            "4. 付款手續費與退改票規則"
        )

    # 預設回覆
    return (
        "請輸入「我想查機票」開始查詢。\n\n"
        "流程會依序詢問：\n"
        "1. 出發日期\n"
        "2. 出發地與目的地\n"
        "3. 查詢機票結果"
    )
def parse_date_from_text(text):
    text = text.strip()

    # 支援 2026-07-10
    date_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)

    if date_match:
        year = int(date_match.group(1))
        month = int(date_match.group(2))
        day = int(date_match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # 支援 7月10號 / 7月10日
    date_match = re.search(r"(\d{1,2})月(\d{1,2})(號|日)?", text)

    if date_match:
        current_year = datetime.now().year
        month = int(date_match.group(1))
        day = int(date_match.group(2))
        return f"{current_year:04d}-{month:02d}-{day:02d}"

    return None
def parse_route_from_text(text):
    text = text.strip()

    route_match = re.search(r"(.+?)(飛|到|去)(.+)", text)

    if not route_match:
        return None, None

    origin = route_match.group(1).strip()
    destination = route_match.group(3).strip()

    return origin, destination