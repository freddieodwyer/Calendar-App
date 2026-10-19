import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file

import db
import freebusy
import ics

print("Running...")

CACHE_SECONDS = 600
# lets the page simulate another day/time; set the ALLOW_TEST_TIME env var to 0 to switch it off
ALLOW_TEST_TIME = os.environ.get("ALLOW_TEST_TIME", "1") == "1"
MAX_PEOPLE = 30
MAX_NAME = 30
MAX_GROUP_NAME = 40
BASE = Path(__file__).parent
HOST = os.environ.get("HOST", "127.0.0.1")  # this PC only: ngrok connects locally
PORT = int(os.environ.get("PORT", "5000"))

cache = {}  # person id -> (fetched_at, ics_text)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = ics.MAX_BYTES + 10_000


@app.errorhandler(ValueError)
def handle_value_error(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(413)
def handle_too_large(e):
    return jsonify(error="That file is too large"), 413


@app.errorhandler(OSError)
def handle_network_error(e):
    return jsonify(error="Couldn't download that link. Check it and try again."), 400


def clean_name(value, limit):
    name = (value or "").strip()
    if not name or len(name) > limit:
        raise ValueError(f"Name must be 1-{limit} characters")
    return name


def check_calendar(text):
    # make sure it actually works with the free/busy logic
    now = datetime.now(freebusy.TIMEZONE)
    freebusy.get_busy(freebusy.parse_calendar(text), now)


def read_calendar():
    # returns (url, ics_text): url for a subscription link, ics_text for an upload
    upload = request.files.get("file")
    link = request.form.get("link", "").strip()
    if upload and upload.filename:
        text = ics.strip_details(ics.decode(upload.read(ics.MAX_BYTES + 1)))
        check_calendar(text)
        return None, text
    if link:
        text = ics.fetch_ics(link)
        check_calendar(text)
        return link, None
    raise ValueError("Add a calendar link or upload an .ics file")


def group_or_404(group_id):
    group = db.get_group(group_id)
    if group is None:
        abort(404)
    return group


def person_or_404(code):
    person = db.get_person_by_code(code)
    if person is None:
        abort(404)
    return person


def admin_group_or_404(code):
    group = db.get_group_by_admin(code)
    if group is None:
        abort(404)
    return group


def admin_person_or_404(code, person_id):
    group = admin_group_or_404(code)
    person = db.get_person(person_id)
    if person is None or person["group_id"] != group["id"]:
        abort(404)
    return person


def get_calendar(person):
    if person["ics_text"]:
        return person["ics_text"]
    cached = cache.get(person["id"])
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    text = ics.fetch_ics(person["url"])
    cache[person["id"]] = (time.time(), text)
    return text


def safe_get(person):
    try:
        text = get_calendar(person)
    except Exception as e:
        print(person["name"], "fetch failed:", repr(e))
        # fall back to the last good copy if the fetch fails
        stale = cache.get(person["id"])
        text = stale[1] if stale else None
    return person["id"], text


def load_all(people):
    with ThreadPoolExecutor() as pool:
        return dict(pool.map(safe_get, people))


def person_status(name, text, now):
    if text is None:
        return {"name": name, "status": "error", "until": None}
    try:
        busy = freebusy.get_busy(freebusy.parse_calendar(text), now)
    except Exception as e:
        print(name, "parse failed:", repr(e))
        return {"name": name, "status": "error", "until": None}
    status, until = freebusy.free_status(busy, now)
    return {
        "name": name,
        "status": status,
        "until": until.strftime("%H:%M") if until else None,
    }


def get_now():
    at = request.args.get("at")
    if not (ALLOW_TEST_TIME and at):
        return datetime.now(freebusy.TIMEZONE)
    now = datetime.fromisoformat(at)
    if now.tzinfo is None:
        now = now.replace(tzinfo=freebusy.TIMEZONE)
    return now


def build_results(group):
    now = get_now()
    people = db.list_people(group["id"])
    texts = load_all(people)
    statuses = [person_status(p["name"], texts[p["id"]], now) for p in people]
    return {
        "group": group["name"],
        "day": now.strftime("%a"),
        "weekend": now.weekday() >= 5,
        "time": now.strftime("%H:%M"),
        "test_mode": ALLOW_TEST_TIME,
        "people": statuses,
    }


@app.route("/")
def home():
    return send_file(BASE / "home.html")


@app.post("/api/groups")
def api_create_group():
    name = clean_name((request.get_json(silent=True) or {}).get("name"), MAX_GROUP_NAME)
    group_id, admin_code = db.create_group(name)
    return jsonify(id=group_id, admin_code=admin_code)


@app.route("/g/<group_id>")
def group_page(group_id):
    group_or_404(group_id)
    return send_file(BASE / "group.html")


@app.route("/api/g/<group_id>/free")
def api_free(group_id):
    return jsonify(build_results(group_or_404(group_id)))


@app.post("/api/g/<group_id>/people")
def api_add_person(group_id):
    group_or_404(group_id)
    if db.count_people(group_id) >= MAX_PEOPLE:
        raise ValueError("This group is full")
    name = clean_name(request.form.get("name"), MAX_NAME)
    url, text = read_calendar()
    code = db.add_person(group_id, name, url, text)
    return jsonify(manage_url=f"/manage/{code}")


@app.route("/manage/<code>")
def manage_page(code):
    person_or_404(code)
    return send_file(BASE / "manage.html")


@app.route("/api/manage/<code>")
def api_manage_info(code):
    person = person_or_404(code)
    return jsonify(name=person["name"], group_id=person["group_id"])


@app.post("/api/manage/<code>")
def api_manage_update(code):
    person = person_or_404(code)
    url, text = read_calendar()
    db.update_person(person["id"], url, text)
    cache.pop(person["id"], None)
    return jsonify(ok=True)


@app.delete("/api/manage/<code>")
def api_manage_delete(code):
    person = person_or_404(code)
    db.delete_person(person["id"])
    cache.pop(person["id"], None)
    return jsonify(group_id=person["group_id"])


@app.route("/admin/<code>")
def admin_page(code):
    admin_group_or_404(code)
    return send_file(BASE / "admin.html")


@app.route("/api/admin/<code>")
def api_admin_info(code):
    group = admin_group_or_404(code)
    people = [
        {"id": p["id"], "name": p["name"], "kind": "link" if p["url"] else "file"}
        for p in db.list_people(group["id"])
    ]
    return jsonify(group_id=group["id"], group=group["name"], people=people)


@app.post("/api/admin/<code>/people/<int:person_id>/rename")
def api_admin_rename(code, person_id):
    person = admin_person_or_404(code, person_id)
    name = clean_name((request.get_json(silent=True) or {}).get("name"), MAX_NAME)
    db.rename_person(person["id"], name)
    return jsonify(ok=True)


@app.post("/api/admin/<code>/people/<int:person_id>/calendar")
def api_admin_calendar(code, person_id):
    person = admin_person_or_404(code, person_id)
    url, text = read_calendar()
    db.update_person(person["id"], url, text)
    cache.pop(person["id"], None)
    return jsonify(ok=True)


@app.delete("/api/admin/<code>/people/<int:person_id>")
def api_admin_delete(code, person_id):
    person = admin_person_or_404(code, person_id)
    db.delete_person(person["id"])
    cache.pop(person["id"], None)
    return jsonify(ok=True)


db.init_db()
print("Initializing...")

if __name__ == "__main__":
    from waitress import serve  # sturdier than Flask's built-in server

    serve(app, host=HOST, port=PORT, threads=8)
