# Mascot frontend

The custom TIKI character remains in `frontend/tiki-mascot.webp`; the interface retains its black-and-red design. No CSS artwork or API images are required.

**New behavior:** The physical glasses button is CAMERA ONLY. Mac microphone input is triggered by the app's **Talk to TIKI** button or optional wake phrase. The standard browser speech path is now one Gemini request for transcription + answer, with the old two-request path as a fallback. No ESP32 firmware upload is required.

**Run:** open the project in VS Code, copy `.env.example` to `.env`, enter a rotated private Gemini key and actual ESP32 IP, install `requirements.txt`, and run `python -m uvicorn app.main:app --host 127.0.0.1 --port 8002`.
