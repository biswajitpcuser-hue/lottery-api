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

# ── Core Math ─────────────────────────────────────────────

def digital_root(n):
    n = abs(int(n))
    return 0 if n == 0 else 1 + (n - 1) % 9

def to_size(dr):
    return "BIG" if dr % 2 == 0 else "SMALL"

def last_digit(x):
    return int(str(int(x))[-1])

# ── 5 Analysis Methods on full data ───────────────────────

def method_drs(nums):
    """Last 3 numbers: (N1+N3)-N2"""
    n1, n2, n3 = nums[0], nums[1], nums[2]
    return to_size(digital_root((n1 + n3) - n2))

def method_wfd(nums):
    """Last 3: (N1x3)-(N2x2)+N3"""
    n1, n2, n3 = nums[0], nums[1], nums[2]
    return to_size(digital_root((n1 * 3) - (n2 * 2) + n3))

def method_trend(nums):
    """Last 10 numbers: count BIG vs SMALL, predict minority (reversion)"""
    sizes = [to_size(digital_root(n)) for n in nums[:50]]
    big   = sizes.count("BIG")
    small = sizes.count("SMALL")
    # Reversion: if too many BIG recently, SMALL is due
    return "SMALL" if big > small else "BIG"

def method_streak(nums):
    """If same result 3+ times in a row, predict opposite"""
    sizes = [to_size(digital_root(n)) for n in nums[:6]]
    if len(sizes) >= 3 and sizes[0] == sizes[1] == sizes[2]:
        return "BIG" if sizes[0] == "SMALL" else "SMALL"
    return to_size(digital_root(nums[0]))  # fallback: current trend

def method_sum_pattern(nums):
    """Last 5 numbers sum -> digital root -> size"""
    s = sum(nums[:5])
    return to_size(digital_root(s))

# ── Deep Analysis: use ALL data ────────────────────────────

def deep_predict(all_nums):
    votes = [
        method_drs(all_nums),
        method_wfd(all_nums),
        method_trend(all_nums),
        method_streak(all_nums),
        method_sum_pattern(all_nums),
    ]
    count   = Counter(votes)
    winner  = count.most_common(1)[0][0]
    score   = count[winner]
    confidence = "HIGH" if score >= 4 else "MEDIUM" if score == 3 else "LOW"
    return winner, confidence, {
        "DRS"         : votes[0],
        "WFD"         : votes[1],
        "Trend"       : votes[2],
        "Streak"      : votes[3],
        "SumPattern"  : votes[4],
        "votes_BIG"   : count.get("BIG", 0),
        "votes_SMALL" : count.get("SMALL", 0),
    }

# ── Win/Loss History ───────────────────────────────────────

def build_history(docs):
    """
    For each doc (latest first), predict using data BEFORE it,
    compare with actual result → WIN or LOSS
    """
    history = []
    for i in range(len(docs)):
        doc  = docs[i]
        past = docs[i+1:]  # older data only
        if len(past) < 5:
            continue

        past_nums = [last_digit(d["number"]) for d in past]
        pred, conf, breakdown = deep_predict(past_nums)

        actual = doc.get("mapped", "")
        if actual == "B":
            actual_size = "BIG"
        elif actual == "S":
            actual_size = "SMALL"
        else:
            dr = digital_root(last_digit(doc["number"]))
            actual_size = to_size(dr)

        result = "WIN" if pred == actual_size else "LOSS"

        history.append({
            "issue_id"   : doc.get("issue_id"),
            "number"     : doc.get("number"),
            "actual"     : actual_size,
            "predicted"  : pred,
            "confidence" : conf,
            "result"     : result,
            "breakdown"  : breakdown,
        })

    return history

# ── Route ─────────────────────────────────────────────────

@app.route("/")
@app.route("/api/predict")
def get_prediction():
    # Fetch ALL available data, sorted latest first
    docs = list(col.find({}, {"_id": 0}).sort("issue_id", -1))

    if len(docs) < 5:
        return jsonify({"error": "Not enough data"}), 400

    all_nums = [last_digit(d["number"]) for d in docs]

    # Next prediction using full data
    prediction, confidence, breakdown = deep_predict(all_nums)

    # History: last 20 predictions vs actual
    history = build_history(docs[:22])  # use latest 22 to get 20 history rows

    wins   = sum(1 for h in history if h["result"] == "WIN")
    losses = sum(1 for h in history if h["result"] == "LOSS")
    total  = wins + losses
    accuracy = round(wins / total * 100, 1) if total else 0

    return jsonify({
        "latest_issue_id" : docs[0].get("issue_id"),
        "total_records"   : len(docs),
        "next_prediction" : prediction,
        "confidence"      : confidence,
        "breakdown"       : breakdown,
        "accuracy_last20" : f"{accuracy}%",
        "wins_last20"     : wins,
        "losses_last20"   : losses,
        "history"         : history,
        "generated_at"    : datetime.utcnow().isoformat() + "Z"
    })
