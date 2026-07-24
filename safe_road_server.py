#!/usr/bin/env python3
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import cgi
import json
import random
from datetime import datetime, timezone

import github_auth
from vision_detector import detect_hazards_from_image

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
DETECTIONS_FILE = DATA_DIR / "detections.json"

HAZARD_CONFIG = {
    "trash": {
        "label": "Road trash",
        "severity": "medium",
        "message": "Trash detected on road. Notify road manager and warn nearby drivers.",
        "targets": ["road_manager", "navigation", "nearby_users"],
    },
    "roe_deer": {
        "label": "Roe deer",
        "severity": "high",
        "message": "Wild animal near road. Notify police and warn drivers to slow down.",
        "targets": ["police", "navigation", "nearby_users"],
    },
    "road_crack": {
        "label": "Road crack",
        "severity": "high",
        "message": "Road crack detected. Notify maintenance team and mark route as dangerous.",
        "targets": ["road_manager", "navigation", "nearby_users"],
    },
}

SAMPLE_LOCATIONS = [
    {"road": "Route 37", "latitude": 37.5665, "longitude": 126.9780},
    {"road": "Mountain Road 12", "latitude": 37.7519, "longitude": 128.8761},
    {"road": "City Ring Road", "latitude": 35.1796, "longitude": 129.0756},
    {"road": "Coastal Highway", "latitude": 33.4996, "longitude": 126.5312},
]


def ensure_data_file():
    DATA_DIR.mkdir(exist_ok=True)
    if not DETECTIONS_FILE.exists():
        DETECTIONS_FILE.write_text("[]\n", encoding="utf-8")


def load_detections():
    ensure_data_file()
    with DETECTIONS_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_detections(detections):
    ensure_data_file()
    with DETECTIONS_FILE.open("w", encoding="utf-8") as file:
        json.dump(detections, file, indent=2)
        file.write("\n")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_event(
    drone_id,
    hazard_type,
    latitude,
    longitude,
    confidence,
    severity=None,
    road="Unknown road",
    detail=None,
):
    config = HAZARD_CONFIG.get(hazard_type, {})
    event_id = f"evt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
    return {
        "id": event_id,
        "created_at": utc_now(),
        "drone_id": drone_id,
        "type": hazard_type,
        "label": config.get("label", hazard_type.replace("_", " ").title()),
        "severity": severity or config.get("severity", "medium"),
        "confidence": round(float(confidence), 2),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "road": road,
        "message": config.get("message", "Road hazard detected."),
        "detail": detail,
        "alert_targets": config.get("targets", ["road_manager", "nearby_users"]),
        "status": "new",
    }


def simulate_event():
    location = random.choice(SAMPLE_LOCATIONS)
    hazard_type = random.choice(list(HAZARD_CONFIG.keys()))
    confidence = random.uniform(0.78, 0.98)
    return build_event(
        drone_id="sim-drone-01",
        hazard_type=hazard_type,
        latitude=location["latitude"] + random.uniform(-0.015, 0.015),
        longitude=location["longitude"] + random.uniform(-0.015, 0.015),
        confidence=confidence,
        road=location["road"],
    )


class SafeRoadHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        parsed = urlparse(path)
        if parsed.path == "/":
            return str(STATIC_DIR / "index.html")
        if parsed.path.startswith("/static/"):
            return str(BASE_DIR / parsed.path.lstrip("/"))
        return str(STATIC_DIR / parsed.path.lstrip("/"))

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def read_multipart_form(self):
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type"),
            },
        )
        return form

    def send_redirect(self, location, cookie=None):
        self.send_response(302)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def current_session_token(self):
        return github_auth.session_token_from_cookie_header(self.headers.get("Cookie"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/auth/github/login":
            if not github_auth.is_configured():
                self.send_json(
                    {
                        "error": "GitHub login is not configured.",
                        "hint": "Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET, then restart the server.",
                    },
                    status=503,
                )
                return
            self.send_redirect(github_auth.build_authorize_url())
            return
        if parsed.path == "/auth/github/callback":
            params = parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            state = params.get("state", [""])[0]
            if not code or not github_auth.consume_state(state):
                self.send_json({"error": "Invalid or expired GitHub login attempt. Try again."}, status=400)
                return
            try:
                user = github_auth.exchange_code_for_user(code)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.send_json({"error": f"GitHub login failed: {error}"}, status=502)
                return
            token = github_auth.create_session(user)
            cookie = f"{github_auth.SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax"
            self.send_redirect("/", cookie=cookie)
            return
        if parsed.path == "/api/auth/me":
            user = github_auth.get_session_user(self.current_session_token())
            self.send_json(
                {
                    "configured": github_auth.is_configured(),
                    "authenticated": user is not None,
                    "user": user,
                }
            )
            return
        if parsed.path == "/api/detections":
            detections = sorted(load_detections(), key=lambda item: item["created_at"], reverse=True)
            self.send_json({"detections": detections})
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "service": "safe-road", "time": utc_now()})
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/logout":
            token = self.current_session_token()
            github_auth.destroy_session(token)
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Set-Cookie",
                f"{github_auth.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
            )
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/simulate":
            event = simulate_event()
            detections = load_detections()
            detections.append(event)
            save_detections(detections)
            self.send_json({"event": event}, status=201)
            return

        if parsed.path == "/api/drone/frame":
            try:
                payload = self.read_json_body()
                drone_id = payload.get("drone_id", "unknown-drone")
                latitude = payload["latitude"]
                longitude = payload["longitude"]
                road = payload.get("road", "Unknown road")
                new_events = []
                for detection in payload.get("detections", []):
                    hazard_type = detection.get("type")
                    if not hazard_type:
                        continue
                    new_events.append(
                        build_event(
                            drone_id=drone_id,
                            hazard_type=hazard_type,
                            latitude=latitude,
                            longitude=longitude,
                            confidence=detection.get("confidence", 0.8),
                            severity=detection.get("severity"),
                            road=road,
                            detail=detection.get("detail"),
                        )
                    )
                detections = load_detections()
                detections.extend(new_events)
                save_detections(detections)
                self.send_json({"accepted": len(new_events), "events": new_events}, status=201)
            except (KeyError, json.JSONDecodeError, ValueError) as error:
                self.send_json({"error": str(error)}, status=400)
            return

        if parsed.path == "/api/vision/image":
            try:
                form = self.read_multipart_form()
                image_field = form["image"]
                image_bytes = image_field.file.read()
                drone_id = form.getfirst("drone_id", "upload-drone-01")
                latitude = float(form.getfirst("latitude", "37.5665"))
                longitude = float(form.getfirst("longitude", "126.9780"))
                road = form.getfirst("road", "Uploaded road image")
                vision_detections = detect_hazards_from_image(image_bytes)

                new_events = [
                    build_event(
                        drone_id=drone_id,
                        hazard_type=detection["type"],
                        latitude=latitude,
                        longitude=longitude,
                        confidence=detection["confidence"],
                        severity=detection["severity"],
                        road=road,
                        detail=detection.get("detail"),
                    )
                    for detection in vision_detections
                ]

                detections = load_detections()
                detections.extend(new_events)
                save_detections(detections)
                self.send_json(
                    {
                        "accepted": len(new_events),
                        "events": new_events,
                        "message": "OpenCV image analysis completed.",
                    },
                    status=201,
                )
            except (KeyError, ValueError) as error:
                self.send_json({"error": str(error)}, status=400)
            return

        self.send_json({"error": "Not found"}, status=404)


def main():
    ensure_data_file()
    server = ThreadingHTTPServer(("0.0.0.0", 8000), SafeRoadHandler)
    print("Safe Road server running at http://localhost:8000")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


if __name__ == "__main__":
    main()
