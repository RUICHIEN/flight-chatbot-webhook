from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)


AIRPORT_MAP = {
    "台北": "TPE",
    "臺北": "TPE",
    "桃園": "TPE",
    "東京": "TYO",
    "東京都": "TYO",
    "大阪": "OSA",
    "關西": "KIX",
    "首爾": "SEL",
    "韓國": "SEL",
    "曼谷": "BKK",
    "香港": "HKG"
}


@app.route("/", methods=["GET"])
def home():
    return "Flight webhook is running."


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
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

    origin_code = convert_to_airport_code(origin)
    destination_code = convert_to_airport_code(destination)
    outbound_date = format_dialogflow_date(date)

    if not origin_code:
        return jsonify({
            "fulfillmentText": f"目前還不支援出發地「{origin}」，請先試試台北、東京、大阪、首爾、曼谷或香港。"
        })

    if not destination_code:
        return jsonify({
            "fulfillmentText": f"目前還不支援目的地「{destination}」，請先試試東京、大阪、首爾、曼谷或香港。"
        })

    if not outbound_date:
        return jsonify({
            "fulfillmentText": "我有收到查詢，但日期格式不完整。請輸入像「7月10號」或「2026-07-10」這樣的日期。"
        })

    flights = search_flights_from_serpapi(origin_code, destination_code, outbound_date)

    reply_text = build_reply(origin, destination, outbound_date, flights)

    return jsonify({
        "fulfillmentText": reply_text
    })


def convert_to_airport_code(place):
    if not place:
        return None

    place = str(place).strip()

    if place.upper() in AIRPORT_MAP.values():
        return place.upper()

    return AIRPORT_MAP.get(place)


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
    api_key = os.environ.get("SERPAPI_KEY")

    if not api_key:
        return {
            "error": "SERPAPI_KEY_NOT_FOUND"
        }

    url = "https://serpapi.com/search"

    params = {
        "engine": "google_flights",
        "departure_id": origin_code,
        "arrival_id": destination_code,
        "outbound_date": outbound_date,
        "type": "2",
        "currency": "TWD",
        "hl": "zh-tw",
        "api_key": api_key
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
    except Exception as e:
        return {
            "error": "REQUEST_FAILED",
            "message": str(e)
        }

    if "error" in data:
        return {
            "error": "SERPAPI_ERROR",
            "message": data.get("error")
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
        layovers = item.get("layovers", [])

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
            "include": "實際行李、餐點與票種內容請以購買平台顯示為準。"
        })

    return results


def build_reply(origin, destination, outbound_date, flights):
    if isinstance(flights, dict) and flights.get("error") == "SERPAPI_KEY_NOT_FOUND":
        return "目前 Vercel 尚未設定 SERPAPI_KEY，所以無法查詢真實機票資料。"

    if isinstance(flights, dict) and flights.get("error") == "REQUEST_FAILED":
        return f"查詢機票 API 時發生連線問題：{flights.get('message')}"

    if isinstance(flights, dict) and flights.get("error") == "SERPAPI_ERROR":
        return f"SerpApi 回傳錯誤：{flights.get('message')}"

    if not flights:
        return f"目前查不到 {origin} 到 {destination} 在 {outbound_date} 的機票資料。"

    reply = f"我幫你查到 {len(flights)} 筆 {origin} 到 {destination} 在 {outbound_date} 的機票：\n\n"

    for index, flight in enumerate(flights, start=1):
        reply += (
            f"{index}. {flight['airline']}\n"
            f"價格：約 NT${flight['price']}\n"
            f"時間：{flight['departure_time']} → {flight['arrival_time']}\n"
            f"航程：{flight['duration']} 分鐘\n"
            f"轉機：{flight['transfer']}\n"
            f"包含：{flight['include']}\n\n"
        )

    reply += "提醒：機票價格會即時變動，實際金額與行李規則請以購買頁面為準。"

    return reply