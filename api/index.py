from flask import Flask, request, jsonify

app = Flask(__name__)


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

    origin = parameters.get("origin", "未提供出發地")
    destination = parameters.get("destination", "未提供目的地")
    date = parameters.get("date", "未提供日期")

    flights = search_flights(origin, destination, date)
    reply_text = build_reply(origin, destination, date, flights)

    return jsonify({
        "fulfillmentText": reply_text
    })


def search_flights(origin, destination, date):
    flights = [
        {
            "origin": "臺北",
            "destination": "東京都",
            "platform": "Trip.com",
            "airline": "Peach Aviation",
            "price": 4280,
            "include": "含手提行李 7kg，不含托運行李",
            "link": "https://www.trip.com/flights/"
        },
        {
            "origin": "臺北",
            "destination": "東京都",
            "platform": "Skyscanner",
            "airline": "Tigerair Taiwan",
            "price": 4650,
            "include": "含手提行李，不含餐點",
            "link": "https://www.skyscanner.com.tw/"
        },
        {
            "origin": "臺北",
            "destination": "東京都",
            "platform": "Google Flights",
            "airline": "Jetstar Japan",
            "price": 4990,
            "include": "基本票價，托運行李需另外加購",
            "link": "https://www.google.com/travel/flights"
        }
    ]

    # 先用目的地簡單篩選，避免輸入「東京」和資料「東京都」對不起來
    matched_flights = []

    for flight in flights:
        if destination in flight["destination"] or flight["destination"] in destination:
            matched_flights.append(flight)

    if not matched_flights:
        matched_flights = flights

    matched_flights = sorted(matched_flights, key=lambda x: x["price"])

    return matched_flights[:3]


def build_reply(origin, destination, date, flights):
    if not flights:
        return f"目前查不到 {origin} 到 {destination} 在 {date} 的機票資料。"

    reply = f"我幫你找到 {len(flights)} 筆 {origin} 到 {destination} 的便宜機票：\n\n"

    for index, flight in enumerate(flights, start=1):
        reply += (
            f"{index}. {flight['platform']}\n"
            f"航空：{flight['airline']}\n"
            f"價格：NT${flight['price']}\n"
            f"包含：{flight['include']}\n"
            f"購買平台：{flight['link']}\n\n"
        )

    reply += "提醒：此為測試資料，實際價格可能會因時間、行李、付款方式而變動。"

    return reply