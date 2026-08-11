# -*- coding: utf-8 -*-
"""Dev server for the besedka landing: serves static files + booking API.
Mirrors the Google Apps Script contract so the frontend code is identical
in dev and production. Run: py -3 dev_server.py
"""
import json
import os
import re
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "dev-bookings.json")
NOTIFY_LOG = os.path.join(ROOT, "dev-notifications.log")
# Пароль ТОЛЬКО для локальной разработки: сервер слушает 127.0.0.1 и наружу
# не смотрит. Боевой пароль задаётся отдельно, в backend/Code.gs.
ADMIN_TOKEN = "123"
PORT = 8743

_lock = threading.Lock()
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("new", "confirmed", "cancelled")


def load_db():
    if not os.path.exists(DB_PATH):
        return {"bookings": [], "blocked": [], "counter": 0}
    with open(DB_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_db(db):
    with open(DB_PATH, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=2)


def notify(text):
    with open(NOTIFY_LOG, "a", encoding="utf-8") as fh:
        fh.write("[%s] %s\n" % (datetime.now().isoformat(timespec="seconds"), text))


def busy_dates(db):
    return sorted({b["date"] for b in db["bookings"] if b["status"] in ("new", "confirmed")})


def clean(value, limit=300):
    return str(value or "").strip()[:limit]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def send_json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorised(self, token):
        return token == ADMIN_TOKEN

    # ---------- routing ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") == "/api":
            return self.api_get(parse_qs(parsed.query))
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/api":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(raw)
        except ValueError:
            return self.send_json({"ok": False, "error": "bad_json"}, 400)
        return self.api_post(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    # ---------- api ----------
    def api_get(self, q):
        action = (q.get("action") or [""])[0]
        with _lock:
            db = load_db()
            if action == "availability":
                return self.send_json({"ok": True, "busy": busy_dates(db), "blocked": sorted(db["blocked"])})
            if action == "list":
                if not self.authorised((q.get("token") or [""])[0]):
                    return self.send_json({"ok": False, "error": "auth"}, 403)
                items = sorted(db["bookings"], key=lambda b: (b["date"], b["created"]))
                return self.send_json({"ok": True, "items": items, "blocked": sorted(db["blocked"])})
        return self.send_json({"ok": False, "error": "unknown_action"}, 400)

    def api_post(self, data):
        action = data.get("action")
        with _lock:
            db = load_db()

            if action == "book":
                date = clean(data.get("date"), 10)
                name = clean(data.get("name"), 80)
                phone = clean(data.get("phone"), 30)
                digits = re.sub(r"\D", "", phone)
                if not DATE_RE.match(date):
                    return self.send_json({"ok": False, "error": "bad_date"}, 400)
                if len(name) < 2:
                    return self.send_json({"ok": False, "error": "bad_name"}, 400)
                if not 10 <= len(digits) <= 15:
                    return self.send_json({"ok": False, "error": "bad_phone"}, 400)
                if date in db["blocked"] or date in busy_dates(db):
                    return self.send_json({"ok": False, "error": "date_taken"}, 409)

                db["counter"] += 1
                booking = {
                    "id": "TM-%04d" % db["counter"],
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "date": date,
                    "tariff": clean(data.get("tariff"), 20),
                    "tariffLabel": clean(data.get("tariffLabel"), 60),
                    "timeFrom": clean(data.get("timeFrom"), 5),
                    "timeTo": clean(data.get("timeTo"), 5),
                    "hours": int(data.get("hours") or 0),
                    "guests": int(data.get("guests") or 0),
                    "price": int(data.get("price") or 0),
                    "name": name,
                    "phone": phone,
                    "comment": clean(data.get("comment"), 500),
                    "status": "new",
                }
                db["bookings"].append(booking)
                save_db(db)
                notify("NEW BOOKING %s | %s %s-%s | %s | %s | %s rub" % (
                    booking["id"], booking["date"], booking["timeFrom"], booking["timeTo"],
                    booking["name"], booking["phone"], booking["price"]))
                return self.send_json({"ok": True, "id": booking["id"]})

            if action in ("status", "block", "unblock"):
                if not self.authorised(clean(data.get("token"), 60)):
                    return self.send_json({"ok": False, "error": "auth"}, 403)

                if action == "status":
                    new_status = clean(data.get("status"), 20)
                    if new_status not in STATUSES:
                        return self.send_json({"ok": False, "error": "bad_status"}, 400)
                    for b in db["bookings"]:
                        if b["id"] == clean(data.get("id"), 20):
                            b["status"] = new_status
                            save_db(db)
                            return self.send_json({"ok": True})
                    return self.send_json({"ok": False, "error": "not_found"}, 404)

                date = clean(data.get("date"), 10)
                if not DATE_RE.match(date):
                    return self.send_json({"ok": False, "error": "bad_date"}, 400)
                if action == "block":
                    if date not in db["blocked"]:
                        db["blocked"].append(date)
                else:
                    db["blocked"] = [d for d in db["blocked"] if d != date]
                save_db(db)
                return self.send_json({"ok": True})

        return self.send_json({"ok": False, "error": "unknown_action"}, 400)


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as srv:
        print("dev server on http://localhost:%d (admin token: %s)" % (PORT, ADMIN_TOKEN))
        srv.serve_forever()
