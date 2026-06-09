from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────
MONGO_URI  = "mongodb+srv://Databaseapi:Databaseapi@cluster0.ymhnaiy.mongodb.net/?appName=Cluster0"
DB_NAME    = "lottery_db"
COLLECTION = "results"

app = Flask(__name__)
CORS(app)

# ── MongoDB (lazy singleton so cold-start is fast) ──
_client = None
def get_col():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client[DB_NAME][COLLECTION]


# ─────────────────────────────────────────
#  MATH HELPERS
# ─────────────────────────────────────────
def digital_root(n: int) -> int:
    n = abs(n)
    return 0 if n == 0 else 1 + (n - 1) % 9

def classify(dr: int) -> dict:
    if dr % 2 == 0:
        return {"size": "BIG",   "color": "RED",   "parity": "Even"}
    return     {"size": "SMALL", "color": "GREEN", "parity": "Odd"}

def last_digit(number) -> int:
    return int(str(int(number))[-1])


# ─────────────────────────────────────────
#  STRATEGY 1 – DRS  (Digital Root Subtraction)
#  Formula : (N1 + N3) − N2  → digital_root
# ─────────────────────────────────────────
def strategy_drs(n1, n2, n3) -> dict:
    raw = (n1 + n3) - n2
    dr  = digital_root(raw)
    return {
        "strategy"    : "DRS",
        "formula"     : f"({n1} + {n3}) - {n2} = {raw}",
        "digital_root": dr,
        **classify(dr),
    }


# ─────────────────────────────────────────
#  STRATEGY 2 – WFD  (Weighted Fibonacci Difference)
#  Formula : (N1×3) − (N2×2) + N3  → digital_root
# ─────────────────────────────────────────
def strategy_wfd(n1, n2, n3) -> dict:
    raw = (n1 * 3) - (n2 * 2) + n3
    dr  = digital_root(raw)
    return {
        "strategy"    : "WFD",
        "formula"     : f"({n1}×3) - ({n2}×2) + {n3} = {raw}",
        "digital_root": dr,
        **classify(dr),
    }


# ─────────────────────────────────────────
#  FINAL VOTE  (both strategies combined)
# ─────────────────────────────────────────
def final_vote(s1, s2) -> dict:
    if s1["size"] == s2["size"]:
        return {"prediction": s1["size"], "color": s1["color"], "confidence": "HIGH"}
    return {"prediction": "MIXED", "color": "YELLOW", "confidence": "LOW"}


# ─────────────────────────────────────────
#  ENRICH ONE DOCUMENT
#  doc     = current period (N1)
#  history = list of older docs, newest-first (N2 = [0], N3 = [1])
# ─────────────────────────────────────────
def enrich(doc, history) -> dict:
    base = {k: v for k, v in doc.items() if k != "_id"}

    if len(history) < 2 or doc.get("number") is None:
        return {**base, "analysis": None, "prediction": None, "outcome": None}

    n1 = last_digit(doc["number"])
    n2 = last_digit(history[0]["number"])
    n3 = last_digit(history[1]["number"])

    s1   = strategy_drs(n1, n2, n3)
    s2   = strategy_wfd(n1, n2, n3)
    vote = final_vote(s1, s2)

    actual_dr  = digital_root(n1)
    actual     = classify(actual_dr)

    outcome = {
        "actual_size" : actual["size"],
        "actual_color": actual["color"],
        "actual_dr"   : actual_dr,
        "drs_result"  : "WIN" if s1["size"] == actual["size"] else "LOSS",
        "wfd_result"  : "WIN" if s2["size"] == actual["size"] else "LOSS",
        "combined"    : "WIN" if vote["prediction"] == actual["size"] else "LOSS",
    }

    return {**base, "n1": n1, "n2": n2, "n3": n3,
            "analysis": {"DRS": s1, "WFD": s2},
            "prediction": vote, "outcome": outcome}


# ─────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────

# ── Health check ──────────────────────────
@app.route("/api/health")
def health():
    try:
        get_col().database.client.admin.command("ping")
        return jsonify({"status": "ok", "db": "connected",
                        "time": datetime.utcnow().isoformat() + "Z"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ── Last N results with full analysis ─────
@app.route("/api/results")
def results():
    limit = min(int(request.args.get("limit", 50)), 200)
    raw   = list(get_col().find({}, {"_id": 0}).sort("period", -1).limit(limit))

    if not raw:
        return jsonify({"status": "ok", "count": 0, "data": [], "summary": {}})

    enriched = [enrich(raw[i], raw[i+1:]) for i in range(len(raw))]

    # Summary stats
    valid      = [d for d in enriched if d["outcome"]]
    total      = len(valid)
    wins_drs   = sum(1 for d in valid if d["outcome"]["drs_result"] == "WIN")
    wins_wfd   = sum(1 for d in valid if d["outcome"]["wfd_result"] == "WIN")
    wins_comb  = sum(1 for d in valid if d["outcome"]["combined"]   == "WIN")

    summary = {
        "total_analyzed"   : total,
        "DRS_wins"         : wins_drs,
        "WFD_wins"         : wins_wfd,
        "Combined_wins"    : wins_comb,
        "DRS_accuracy_pct" : round(wins_drs  / total * 100, 1) if total else 0,
        "WFD_accuracy_pct" : round(wins_wfd  / total * 100, 1) if total else 0,
        "Combined_accuracy": round(wins_comb / total * 100, 1) if total else 0,
    }

    return jsonify({"status": "ok", "count": len(enriched),
                    "data": enriched, "summary": summary})


# ── Next period prediction ─────────────────
@app.route("/api/predict")
def predict():
    raw = list(get_col().find({}, {"_id": 0}).sort("period", -1).limit(3))

    if len(raw) < 3:
        return jsonify({"status": "error",
                        "message": "Need at least 3 results in DB"}), 400

    n1 = last_digit(raw[0]["number"])
    n2 = last_digit(raw[1]["number"])
    n3 = last_digit(raw[2]["number"])

    s1   = strategy_drs(n1, n2, n3)
    s2   = strategy_wfd(n1, n2, n3)
    vote = final_vote(s1, s2)

    return jsonify({
        "status"          : "ok",
        "based_on"        : {"N1_latest": n1, "N2_prev": n2, "N3_third": n3,
                             "periods"  : [r.get("period") for r in raw]},
        "DRS"             : s1,
        "WFD"             : s2,
        "final_prediction": vote,
        "generated_at"    : datetime.utcnow().isoformat() + "Z",
    })


# ── Deep stats (accuracy, streaks) ────────
@app.route("/api/stats")
def stats():
    raw = list(get_col().find({}, {"_id": 0}).sort("period", -1).limit(200))

    if len(raw) < 3:
        return jsonify({"status": "error", "message": "Need at least 3 results"}), 400

    wins_drs = wins_wfd = wins_comb = total = 0
    best_drs = best_wfd = cur_drs = cur_wfd = 0
    recent   = []  # last 10 combined outcomes

    for i in range(len(raw)):
        hist = raw[i+1:]
        if len(hist) < 2:
            continue
        d = enrich(raw[i], hist)
        if not d["outcome"]:
            continue
        total += 1
        o = d["outcome"]

        if o["drs_result"] == "WIN": wins_drs += 1; cur_drs += 1
        else: cur_drs = 0
        if o["wfd_result"] == "WIN": wins_wfd += 1; cur_wfd += 1
        else: cur_wfd = 0
        if o["combined"]   == "WIN": wins_comb += 1

        best_drs = max(best_drs, cur_drs)
        best_wfd = max(best_wfd, cur_wfd)

        if len(recent) < 10:
            recent.append({"period": raw[i].get("period"), "result": o["combined"]})

    return jsonify({
        "status"        : "ok",
        "total_analyzed": total,
        "DRS"           : {"wins": wins_drs, "accuracy_pct": round(wins_drs/total*100,1) if total else 0, "best_streak": best_drs},
        "WFD"           : {"wins": wins_wfd, "accuracy_pct": round(wins_wfd/total*100,1) if total else 0, "best_streak": best_wfd},
        "Combined"      : {"wins": wins_comb,"accuracy_pct": round(wins_comb/total*100,1) if total else 0},
        "recent_10"     : recent,
    })


# ─────────────────────────────────────────
#  Vercel entry-point  (must be named `app`)
# ─────────────────────────────────────────
# Vercel calls this file as a WSGI app — `app` is auto-detected.
