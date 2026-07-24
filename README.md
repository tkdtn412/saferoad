# Safe Road

Safe Road is a starter prototype for an AI drone road-safety system. It receives drone-style detection data, records road hazards, and shows alerts for police, road managers, navigation services, and nearby users.

## What it detects

- Road trash
- Roe deer / animals
- Road cracks

The current OpenCV image detector can analyze uploaded road images for road-crack-like edge patterns and visible trash-like colored objects. Roe deer detection still needs a trained object model such as YOLO.

## Run on Ubuntu

```bash
cd /home/aa/safe_road
python3 safe_road_server.py
```

Then open:

```text
http://localhost:8000
```

## GitHub ID login

The dashboard supports signing in with a GitHub account (OAuth).

1. Create an OAuth App at <https://github.com/settings/developers>:
   - Homepage URL: `http://localhost:8000`
   - Authorization callback URL: `http://localhost:8000/auth/github/callback`
2. Export the credentials before starting the server:

```bash
export GITHUB_CLIENT_ID="your_client_id"
export GITHUB_CLIENT_SECRET="your_client_secret"
# optional, only needed if the server is not on localhost:8000
export GITHUB_CALLBACK_URL="http://localhost:8000/auth/github/callback"
python3 safe_road_server.py
```

3. Open the dashboard and click **Sign in with GitHub**. Your GitHub ID and
   avatar appear in the top bar; **Log out** ends the session.

Login endpoints:

- `GET /auth/github/login` — redirects to GitHub authorization
- `GET /auth/github/callback` — OAuth callback, sets the session cookie
- `GET /api/auth/me` — current login state (`configured`, `authenticated`, `user`)
- `POST /api/auth/logout` — clears the session

Sessions are kept in server memory, so restarting the server logs everyone out.
If the credentials are not set, the app still works — the sign-in button is
simply disabled.

## API

### Get detections

```bash
curl http://localhost:8000/api/detections
```

### Simulate one drone event

```bash
curl -X POST http://localhost:8000/api/simulate
```

### Send real drone detection data later

```bash
curl -X POST http://localhost:8000/api/drone/frame \
  -H "Content-Type: application/json" \
  -d '{
    "drone_id": "drone-01",
    "latitude": 37.5665,
    "longitude": 126.9780,
    "road": "Test Road",
    "detections": [
      {"type": "road_crack", "confidence": 0.91, "severity": "high"}
    ]
  }'
```

### Analyze an image with OpenCV

```bash
curl -X POST http://localhost:8000/api/vision/image \
  -F "image=@road.jpg" \
  -F "road=Test Road" \
  -F "latitude=37.5665" \
  -F "longitude=126.9780"
```

## Project structure

```text
safe_road/
  safe_road_server.py
  static/
    index.html
    style.css
    app.js
  data/
    detections.json
  README.md
```

## Next upgrades

- Connect a real drone camera stream
- Add YOLO animal detection model
- Add map display
- Send SMS/app/police-road-center alerts
- Store events in a database
