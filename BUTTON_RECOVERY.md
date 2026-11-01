# TIKI camera button recovery

**The physical button is CAMERA ONLY.** Use the on-screen Talk control for voice.

The final integrated edition runs the button watcher into its own worker thread. It continues polling the camera GPIO40 button even if macOS microphone access or optional Vosk wake recognition fails. Camera presses made while the AI is speaking are queued and processed afterward. It does **not** change or flash the working ESP32 firmware.

## Run

1. Stop the old server (Control+C).
2. In the extracted folder run `python3 -m venv .venv && source .venv/bin/activate && python -m pip install -r requirements.txt`.
3. Copy your **previous working** `.env` and optionally `data/` here, after backing them up. The ZIP does not include private settings or old photos.
4. Run `curl --max-time 5 http://YOUR_ESP_IP/button` and press the button; `button_press_count` should increase.
5. Launch `python -m uvicorn app.main:app --host 127.0.0.1 --port 8002`; visit `http://localhost:8002`.
6. Wait 2 seconds for the watcher to establish the initial counter. Tap the physical button. One photo should be saved in the library; the AI response will be played through the ESP32 speaker.
7. To see what the watcher sees, open `http://localhost:8002/api/bridge/state`. If `glasses_connected` is false, verify the IP and that Mac and TIKI are on the same LAN. If `camera-error`, check the `error` and `detail` fields.

**Real hardware must be tested separately.** These tests simulate button signals and do not guarantee the live ESP32 connection. Do not flash firmware or change GPIO wiring for this software fix.

**Security:** A Gemini key shared in chat must be revoked and replaced before pushing to GitHub. `.env` and `data/` must remain untracked.
