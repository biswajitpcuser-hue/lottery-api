from flask import Flask, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime
from collections import Counter

app = Flask(__name__)
CORS(app)

MONGO_URI = "mongodb+srv://Databaseapi:Databaseapi@cluster0.ymhnaiy.mongodb.net/?appName=Cluster0"
client    = MongoClient(MONGO_URI)
col       = client["lottery_db"]["results"]

def digital_root(n):
    n = abs(int(n))
    return 0 if n == 0 else 1 + (n - 1) % 9

def to_size(dr):
    return "BIG" if dr % 2 == 0 else "SMALL"

def last_digit(x):
    return int(str(int(x))[-1])

def deep_predict(nums):
    n1, n2, n3 = nums[0], nums[1], nums[2]

    # DRS
    drs = to_size(digital_root((n1 + n3) - n2))
    # WFD
    wfd = to_size(digital_root((n1 * 3) - (n2 * 2) + n3))
    # Trend last 50
    sizes50 = [to_size(digital_root(n)) for n in nums[:50]]
    big50   = sizes50.count("BIG")
    sml50   = sizes50.count("SMALL")
    trend   = "SMALL" if big50 > sml50 else "BIG"
    # Streak
    sizes6 = [to_size(digital_root(n)) for n in nums[:6]]
    if len(sizes6) >= 3 and sizes6[0] == sizes6[1] == sizes6[2]:
        streak = "BIG" if sizes6[0] == "SMALL" else "SMALL"
    else:
        streak = to_size(digital_root(n1))
    # Sum pattern last 5
    sump = to_size(digital_root(sum(nums[:5])))

    votes   = [drs, wfd, trend, streak, sump]
    count   = Counter(votes)
    winner  = count.most_common(1)[0][0]
    score   = count[winner]
    conf    = "HIGH" if score >= 4 else "MEDIUM" if score == 3 else "LOW"

    return winner, conf, {
        "DRS": drs, "WFD": wfd, "Trend50": trend,
        "Streak": streak, "SumPattern": sump,
        "votes_BIG": count.get("BIG", 0),
        "votes_SMALL": count.get("SMALL", 0),
    }

def get_actual(doc):
    m = doc.get("mapped", "")
    if m == "B": return "BIG"
    if m == "S": return "SMALL"
    return to_size(digital_root(last_digit(doc["number"])))

@app.route("/")
@app.route("/api/predict")
def get_prediction():
    docs = list(col.find({}, {"_id": 0}).sort("issue_id", -1))
    if len(docs) < 5:
        return jsonify({"error": "Not enough data"}), 400

    # ── CURRENT LIVE PERIOD ──
    # Latest doc = just came in, result already saved
    # So current running period = next one after latest
    latest      = docs[0]
    latest_id   = latest.get("issue_id", "")
    # Next period number = latest + 1 (your system increments by 1)
    try:
        next_period = str(int(latest_id) + 1)
    except:
        next_period = "unknown"

    # Predict for next period using all current data
    all_nums = [last_digit(d["number"]) for d in docs]
    prediction, confidence, breakdown = deep_predict(all_nums)

    # ── HISTORY: each past period — what was predicted BEFORE it, was it WIN/LOSS ──
    history = []
    for i in range(len(docs) - 5):
        doc       = docs[i]          # this period's actual result
        past_docs = docs[i+1:]       # data available BEFORE this period
        past_nums = [last_digit(d["number"]) for d in past_docs]
        pred, conf, bkd = deep_predict(past_nums)
        actual  = get_actual(doc)
        result  = "WIN" if pred == actual else "LOSS"
        history.append({
            "period"    : doc.get("issue_id"),
            "number"    : doc.get("number"),
            "predicted" : pred,
            "actual"    : actual,
            "result"    : result,
            "confidence": conf,
        })
        if len(history) == 20:
            break

    wins     = sum(1 for h in history if h["result"] == "WIN")
    losses   = len(history) - wins
    accuracy = round(wins / len(history) * 100, 1) if history else 0

    return jsonify({
        "current_period"  : next_period,
        "prediction"      : prediction,
        "confidence"      : confidence,
        "breakdown"       : breakdown,
        "history"         : history,
        "accuracy_last20" : f"{accuracy}%",
        "wins"            : wins,
        "losses"          : losses,
        "total_records"   : len(docs),
        "generated_at"    : datetime.utcnow().isoformat() + "Z",
    })
