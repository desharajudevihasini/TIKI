# TIKI — Final complete project (one folder, no patches)

**Hardware button = CAMERA ONLY.** The app's Talk control (or optional Mac wake word) supplies the microphone. ESP32-CAM and MAX98357A output stay in the working Arduino firmware. This software was tested with mocks, not remotely on your hardware.

## Install once in VS Code on macOS

1. Stop the old TIKI server with Control+C. Back up your previous working folder.
2. Extract this ZIP and open **TIKI_FINAL_COMPLETE_CAMERA_ONLY** as a folder in VS Code.
3. Open a terminal in that folder and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

4. Edit `.env` locally with a **new/replaced** Gemini API key and current ESP32 IP. NEVER paste a key into chat or GitHub. `TIKI_MAC_BRIDGE=1`, `TIKI_FAST_REPLIES=1`.
5. To recover your personal history/photos, copy your OLD `data/` directory to this folder before starting either server. Keep this ZIP's new empty `data/` folder separate until ready to replace it.
6. Check your ESP32 URL and physical camera button **before launching**:

```bash
curl --max-time 5 http://192.168.0.115/button
python tools/check_camera_button.py
```

Use actual IP from Serial Monitor in place of 192.168.0.115. If curl times out, stop; reconnect Mac and ESP32 to same Wi-Fi and verify board's IP. A timeout cannot be fixed by changing the frontend.

7. Start:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Open http://localhost:8002 in Chrome and hard refresh (Cmd+Shift+R). If port 8002 is occupied, stop the old Uvicorn or choose 8003 and visit localhost:8003 instead.

## Demo

- **Talk** on the webpage starts Mac microphone. Finish speaking; words and TIKI answer display; reply plays on the hardware speaker, NOT the Mac.
- **Tap the ESP32 physical button once** to take and store one photo. TIKI analyzes and describes it. If you first ask a question about something in view using Talk, TIKI waits for the camera tap and uses that question. Do not hold physical button to speak.
- View pictures in Library > Photos; JPEGs are saved under `data/photos/` and records under `data/tiki.sqlite3`.
- TIKI still requires a Mac for speech input (no INMP441 installed) and cloud Gemini for AI.

## Test and GitHub

```bash
python -m pytest tests -q
node --check frontend/app.js
git init
git add .
git status
```

Before committing, verify `.env`, `.venv/`, and `data/` are absent from `git status` (`.gitignore` excludes them). Rotate the Gemini API key previously shared in chat. Keep your known-working Arduino firmware; reference firmware is included but shouldn't be flashed merely for this update.
