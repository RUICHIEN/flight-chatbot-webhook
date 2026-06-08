from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return "Flight webhook is running."


@app.route("/webhook", methods=["POST"])
def webhook():
    req = request.get_json()

    # 取得 Dialogflow ES 傳來的參數
    parameters = req.get("queryResult", {}).get("parameters", {})

    origin = parameters.get("origin", "未提供出發地")
    destination = parameters.get("destination", "未提供目的地")
    date = parameters.get("date", "未提供日期")

    reply_text = f"你想查的是：{origin} 到 {destination}，日期是 {date}。"

    return jsonify({
        "fulfillmentText": reply_text
    })


if __name__ == "__main__":
    app.run(debug=True)