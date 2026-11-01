# TIKI — Camera-Only Button + Faster Voice (TreeHacks MVP)

**Complete VS Code source — not a patch.** Animated TIKI mascot frontend, FastAPI backend, optional offline wake phrase, ESP32-S3 camera + MAX98357A speaker, saved photos, vision memory, notes, and reminders. Keep your already-working ESP32 sketch; **no Arduino upload is needed**.

## Interaction contract (this is intentional)

- **Physical glasses button = CAMERA ONLY.** One tap captures exactly one authorized photo. If you just tap it, TIKI saves the image and describes the scene. If you first ask via voice, e.g., "TIKI, look at this dog — what breed might it be?", it waits for your tap, then saves and answers that specific question.
- **On-screen Talk button = MICROPHONE.** Tap to start recording with the Mac microphone; tap *Finish speaking* when done. The text and answer appear in the app. On supported Chrome versions, browser recognition can skip separate transcription.
- **Optional "Hey TIKI, spots on" = hands-free speech.** Requires the separately installed Vosk model (see below) and the Mac microphone, not the hardware button.
- **Replies = the ESP32 speaker**, NOT the Mac output. The Mac synthesizes an audio file but does not play it locally. No onboard mic exists yet.

The older working ESP32 sketch may leave the LED toggled after a button press; the Python application cannot correct that firmware behavior. The newer reference sketch in `firmware/` has tighter camera permissions but **do not upload it just for this software update**.

## How this version reduces delays

The browser Talk recording now sends audio through `/api/voice/fast`: **one Gemini request produces both the literal transcript and a short answer**. Older versions issued two sequential requests (transcribe then answer). It falls back to the original two-request path if the fast route is unsupported. Optional wake-mode voice uses the same one-request processing. Text requests skip redundant ESP32 status checks. Physical camera taps are handled from press counters so short taps aren't missed; button polling is lighter than before. Spoken summaries are shorter, so less PCM needs to be synthesized and sent over Wi-Fi.

**This improves the architecture, but cannot guarantee a fixed response time.** Gemini overload, network delays, voice encoding, and PCM delivery still take time. Camera image analysis always needs an additional Gemini Vision request because the picture must be captured first.

## Install in VS Code (Mac)

1. Extract the ZIP, open `TIKI_FINAL_COMPLETE_CAMERA_ONLY` folder in VS Code.
2. **Stop your previous TIKI Uvicorn server**, and keep a copy of your previously working folder.
3. Run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

4. Edit `.env`: add a **new private** `GEMINI_API_KEY` and `TIKI_ESP_URL=http://YOUR_CURRENT_ESP32_IP`. Set `TIKI_AI_MODEL=auto`, `TIKI_MAC_BRIDGE=1`, `TIKI_FAST_REPLIES=1`. You previously exposed an API key in chat; **revoke/rotate that key before pushing to GitHub**.
5. To preserve previous captures and memories, copy your **existing `data/` folder** into this extracted folder with both servers stopped. Don't commit `data/` or `.env`.
6. Test connection (use the current actual IP from Arduino Serial Monitor):

```bash
curl --max-time 5 http://YOUR_ESP_IP/button
python tools/preflight.py --beep
```

7. Start:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Open http://localhost:8002 in **Chrome**, press Cmd+Shift+R. If port 8002 is busy, stop the old server or use 8003. Keep the server running while using TIKI. You may need to grant macOS microphone permissions to Terminal/VS Code.

### Final demo (about 60 seconds)

1. **Speech:** Click **Talk to TIKI**, say "Hey TIKI, spots on. What can you do?", click **Finish speaking**. See the transcript and hear the wearable speaker answer.
2. **Vision:** Click Talk, say "TIKI, look at this dog and tell me its likely breed", click Finish. TIKI shows "Waiting for camera button". Aim the camera and **tap the ESP32 button once**. One real JPEG is saved, shown, and analyzed; TIKI speaks the visual answer through its physical speaker. Breed estimates are tentative, not certain identification.
3. **Memory:** Click Talk and ask, "What did you see in that photo earlier?" or open **Your library → Photos** to display the saved image and description.

You can also **tap the camera button without speaking** to take and describe one photo.

### Optional wake phrase / YOLO

- Optional Mac-based offline wake model: `python tools/install_wake_model.py` and enable the on-screen wake switch. It requires the Mac microphone running. The model is not bundled.
- Optional generic object tags from YOLO: `python -m pip install -r requirements-yolo.txt`, then `TIKI_YOLO_ENABLED=1` in `.env`. **Leave it off for the fastest demo.** YOLO does not reliably classify dog breeds; Gemini analyzes the captured image.

### Privacy, safety and source control

Photographs and SQLite are stored locally under `data/photos` and `data/tiki.sqlite3`, but authorized audio and photos sent to Gemini leave your computer. The old ESP32 firmware may expose `/capture` to anyone on the same trusted LAN; never expose the ESP32 or Mac backend to the public internet. Do not record others without consent. If the ESP32 feels unusually hot, disconnect it.

```bash
python -m pytest tests -q
node --check frontend/app.js
python -m compileall -q app
# Review before publishing
 git init
 git add .
 git status
```

`.gitignore` excludes `.env`, `data/`, `.venv/` and models. For repository upload, commit only after checking `git status`, and push to a repo you own. The suite simulates Gemini and ESP32; this package is **not yet live-tested on your exact hardware after the update**.
