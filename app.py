from flask import Flask, render_template, request, jsonify, send_from_directory, make_response
from pathlib import Path
import json, os, time
import math
import logging


app = Flask(__name__, template_folder="templates", static_folder="static")
# make DATA_PATH absolute and relative to this file (safe)
BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "presentser_data.json"
app.logger.info("DATA_PATH resolved to: %s", str(DATA_PATH))
logging.basicConfig(level=logging.INFO)

GENDER_DEFAULTS = {"male": 75.0, "female": 73.0}
GLOBAL_DEFAULT = 75.0
# --- add these imports at top if not already present ---

# --- add this route to your app (place below other @app.route definitions) ---
@app.route('/autosave', methods=['POST'])
def autosave():
    try:
        payload = request.get_json(force=True) or {}
    except Exception as e:
        app.logger.exception("autosave: invalid json")
        return {"status":"bad_request"}, 400

    # choose key: prefer username if present else 'local'
    key = str(payload.get('username') or payload.get('first_name') or 'local')

    # log incoming payload (helpful while debugging)
    app.logger.info("autosave: saving key=%s payload=%s", key, {k: payload.get(k) for k in ("present","total","target","gender","username","first_name")})

    # load existing data safely
    data = {}
    if DATA_PATH.exists():
        try:
            text = DATA_PATH.read_text(encoding='utf-8')
            data = json.loads(text) if text.strip() else {}
        except Exception as e:
            app.logger.exception("autosave: failed to read existing data, will continue with empty dict")

    # parse numbers robustly
    try:
        present = float(payload.get('present') or 0)
    except Exception:
        present = 0.0
    try:
        total = float(payload.get('total') or 0)
    except Exception:
        total = 0.0

    # prefer provided target, otherwise keep existing or default 75
    try:
        target_val = payload.get('target')
        if target_val in (None, "", []):
            target = data.get(key, {}).get('target', 75.0)
        else:
            target = float(target_val)
    except Exception:
        target = data.get(key, {}).get('target', 75.0)

    # update data
    data[key] = {
        "present": present,
        "total": total,
        "target": target,
        "gender": payload.get('gender'),
        "username": payload.get('username') or key,
        "first_name": payload.get('first_name')
    }

    # try to write the file, but log any failure
    try:
        DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        app.logger.info("autosave: wrote %d records to %s", len(data), DATA_PATH)
    except Exception as e:
        app.logger.exception("autosave: Failed to save data")
        return {"status":"error", "message": "write_failed"}, 500

    return {"status":"ok"}
def load_data():
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_data(data):
    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def required_future_days(present: float, total: float, target_fraction: float):
    """Days to attend (full days, no absence) to reach at least target_fraction."""
    if total <= 0:
        return None
    current = present / total
    if current >= target_fraction:
        return 0
    if math.isclose(target_fraction, 1.0) or target_fraction > 1.0:
        if not math.isclose(present, total):
            return None
    numerator = target_fraction * total - present
    denom = 1 - target_fraction
    if denom == 0:
        return None
    x = numerator / denom
    if x <= 0:
        return 0
    return math.ceil(x)

def max_bunkable_days(present: float, total: float, target_fraction: float):
    """
    Number of full days the student can *skip* (be absent) and still be >= target_fraction.
    Solve p / (t + x) >= target -> x <= p/target - t
    Return floor(max_x) or 0 if none.
    """
    if total < 0:
        return 0
    if target_fraction <= 0:
        return 0
    # if already below target, no safe bunking
    if total == 0:
        return 0
    current = present / total
    if current < target_fraction:
        return 0
    max_x = present / target_fraction - total
    if max_x <= 0:
        return 0
    return math.floor(max_x)

# simple quips
QUIPS = {
    "low": ["Pavam 😬 — time to attend more classes!", "Oy! wake up, bro — attendance needs work. 💪"],
    "mid": ["Not bad — steady wins the race. 🚶‍♂️", "Keep going! Two more and you’ll be safe. ✌️"],
    "high": ["Champion! 🎉 Keep that streak going.", "Nice — that’s the campus flex. 💯"],
}
import random
def pick_quip(pct):
    if pct < 50:
        return random.choice(QUIPS["low"])
    if pct < 75:
        return random.choice(QUIPS["mid"])
    return random.choice(QUIPS["high"])

@app.route("/")
def index():
    resp = make_response(render_template("index.html"))
    return resp

# API: Calculate (without saving)
@app.route("/api/calc", methods=["POST"])
def api_calc():
    body = request.json or {}
    try:
        present = float(body.get("present", 0))
        total = float(body.get("total", 0))
    except Exception:
        return jsonify({"ok": False, "error": "Invalid numbers"}), 400

    gender = (body.get("gender") or "").lower()
    custom_target = body.get("target")
    if custom_target:
        try:
            target_pct = float(custom_target)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid target percent"}), 400
    else:
        if gender in GENDER_DEFAULTS:
            target_pct = GENDER_DEFAULTS[gender]
        else:
            target_pct = GLOBAL_DEFAULT

    if total <= 0:
        return jsonify({"ok": False, "error": "Total days must be > 0"}), 400

    current_pct = (present / total) * 100
    req_days = required_future_days(present, total, target_pct / 100.0)
    bunkable = max_bunkable_days(present, total, target_pct / 100.0)

    data = {
        "ok": True,
        "present": present,
        "total": total,
        "current_pct": round(current_pct, 2),
        "target_pct": target_pct,
        "required_future_days": req_days,
        "bunkable_days": bunkable,
        "quip": pick_quip(current_pct)
    }
    return jsonify(data)

# API: Save for a username (optional)
@app.route("/api/save", methods=["POST"])
def api_save():
    body = request.json or {}
    username = body.get("username") or "guest"
    try:
        present = float(body.get("present", 0))
        total = float(body.get("total", 0))
    except Exception:
        return jsonify({"ok": False, "error": "Invalid numbers"}), 400
    gender = body.get("gender")
    target = None
    if body.get("target"):
        try:
            target = float(body.get("target"))
        except Exception:
            target = None

    data = load_data()
    data.setdefault(str(username), {})
    data[str(username)]["present"] = present
    data[str(username)]["total"] = total
    if gender:
        data[str(username)]["gender"] = gender
    if target:
        data[str(username)]["target"] = target
    save_data(data)
    return jsonify({"ok": True, "username": username})

# API: status (load saved)
@app.route("/api/status", methods=["GET"])
def api_status():
    username = request.args.get("username") or "guest"
    data = load_data()
    rec = data.get(str(username))
    if not rec:
        return jsonify({"ok": False, "error": "No record"}), 404
    return jsonify({"ok": True, "record": rec})

# static file (css)
@app.route("/static/<path:fn>")
def static_file(fn):
    return send_from_directory("static", fn)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

from flask import render_template

@app.route("/data")
def view_data():
    # quick auth via ?key=admin123 (you can replace with session-based protection)
    key = request.args.get("key")
    if key != "admin123":
        return "Unauthorized", 403

    # load JSON file
    try:
        with open("presentser_data.json", "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        raw = {}

    # transform to list of rows for the template
    rows = []
    for username, rec in raw.items():
        rows.append({
            "username": username,
            "present": rec.get("present"),
            "total": rec.get("total"),
            "target": rec.get("target"),
            "gender": rec.get("gender"),
            "first_name": rec.get("first_name")
        })

    # sort rows by username (optional)
    rows.sort(key=lambda r: str(r["username"]).lower())

    return render_template("admin_data.html", rows=rows)


@app.route('/presentser_data.json')
def get_json():
    with open("presentser_data.json") as f:
        return f.read()

VISITS_FILE = "visits.json"
# ensure file exists
if not os.path.exists(VISITS_FILE):
    with open(VISITS_FILE, "w") as f:
        json.dump({"total_hits":0, "visitors":{}}, f)

def load_visits():
    with open(VISITS_FILE,"r") as f:
        return json.load(f)

def save_visits(d):
    with open(VISITS_FILE,"w") as f:
        json.dump(d, f, indent=2)

@app.route("/track", methods=["POST"])
def track():
    payload = request.get_json(silent=True) or {}
    vid = payload.get("vid")
    path = payload.get("path", "")
    if not vid:
        return jsonify({"status":"no-vid"}), 400

    data = load_visits()
    data["total_hits"] = data.get("total_hits",0) + 1

    # record visitor if new or update timestamp
    visitors = data.setdefault("visitors",{})
    visitors[vid] = { "first_seen": visitors.get(vid, {}).get("first_seen", time.time()),
                      "last_seen": time.time(),
                      "path": path }

    save_visits(data)
    return jsonify({"ok":True}), 200

# Enhance your /stats (admin) to return unique and total
def require_admin():
    pass 


@app.route("/stats")
def stats():
    require_admin()   # keep your existing admin protection
    data = load_visits()
    unique = len(data.get("visitors",{}))
    total_hits = data.get("total_hits",0)
    # you can still include presenter_data metrics
    # presenters = load_data() as before...
    return jsonify({
      "unique_visitors": unique,
      "total_hits": total_hits
    })
from flask import abort
import os

ADMIN_KEY = os.getenv("ADMIN_KEY")  # set on Render to protect /admin if you want

@app.route("/admin")
def admin_ui():
    # if ADMIN_KEY is set, require ?key=ADMIN_KEY (lightweight)
    if ADMIN_KEY:
        req_key = request.args.get("key")
        if req_key != ADMIN_KEY:
            return abort(403, "forbidden")
    return render_template("admin.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)