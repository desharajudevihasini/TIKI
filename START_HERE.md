# START HERE — TIKI

**Physical hardware button = CAMERA ONLY. Voice = app Talk button or optional hands-free wake phrase.**

1. Back up your existing working project; stop all previous TIKI servers. Keep the currently working ESP32 firmware unchanged.
2. Open `TIKI_FINAL_COMPLETE_CAMERA_ONLY` in VS Code.
3. Run `python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt`.
4. Run `cp .env.example .env`, then set a **rotated** Gemini key and your actual TIKI IP in `.env`.
5. Stop servers before copying your old `data/` folder here to preserve saved pictures and memories. Never add `data/` or `.env` to GitHub.
6. Run `python tools/preflight.py --beep` to check the real TIKI speaker and camera.
7. Run `python -m uvicorn app.main:app --host 127.0.0.1 --port 8002` and open http://localhost:8002 in Chrome.
8. Click **Talk**, speak, click **Finish**. For a photo, ask TIKI to look and then **tap the physical button once** (or tap it alone to describe the scene).

This version makes a single Gemini request for browser audio transcription+reply, with fallback if unsupported. A working internet connection and Gemini access are still required. The Mac handles microphone input; audio output is the physical TIKI speaker.
