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

    reply_text = f"你想查的是：{origin} 到 {destination}，日期是 {date}。"

    return jsonify({
        "fulfillmentText": reply_text
    })