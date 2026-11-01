"""Read-only TIKI signature-build preflight. No API keys are printed.

Usage:
    python tools/preflight.py
    python tools/preflight.py --beep   # physically play a TIKI speaker test
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app import device, store
from app.config import GEMINI_API_KEY, DEMO_MODE, AI_MODEL, ESP_URL, PHOTO_DIR


def main():
    bad=0
    print('==== TIKI COMPLETE-DEMO PREFLIGHT ====')
    print('ESP32:',ESP_URL)
    d=device.status()
    if d.get('connected'):
        print('PASS ESP32 connected; firmware:', 'permission' if 'camera_armed' in d else 'legacy button')
    else:
        print('FAIL ESP32 not reachable. Check IP in Serial Monitor and .env')
        bad+=1
    for prop,title in [('camera_ready','Camera'),('audio_initialized','Hardware speaker')]:
        if d.get(prop) is True: print('PASS',title,'initialized')
        else: print('FAIL',title,'not initialized (or not reported)');bad+=1
    if 'button_pressed' in d and 'button_press_count' in d:
        print('PASS physical button endpoint is available; press count:',d['button_press_count'])
    else:
        print('FAIL firmware does not report press state and count');bad+=1
    if PHOTO_DIR.is_dir():
        print('PASS photos folder:',PHOTO_DIR)
    else:
        print('FAIL photos folder not writable/available');bad+=1
    store.init()
    print('PASS SQLite storage open; captures:',len(store.captures()),'memories:',len(store.memories()))
    try:
        import sounddevice as sd
        print('PASS microphone device:',sd.query_devices(kind='input')['name'])
    except Exception as exc:
        print('FAIL microphone:',exc);bad+=1
    if not GEMINI_API_KEY or DEMO_MODE:
        print('FAIL Gemini API key missing or demo mode enabled. Add GEMINI_API_KEY to .env.')
        bad+=1
    else:
        try:
            from app.brain import client
            from app.model_router import discover_models
            candidates=discover_models(client(),AI_MODEL)
            print('PASS models accessible to your Gemini key:',', '.join(candidates[:4]))
        except Exception as exc:
            print('FAIL Gemini model lookup:',str(exc)[:250]);bad+=1
    if '--beep' in sys.argv and d.get('connected'):
        try: device.beep();print('SPEAKER: Tone sent. Confirm you hear it on TIKI, not Mac.')
        except Exception as exc:print('SPEAKER FAILED:',exc);bad+=1
    print('RESULT:', 'READY FOR LIVE TEST' if not bad else f'{bad} blocker(s)')
    print('Live test: Click Talk on-screen to ask a question. Tap the glasses button ONCE to take a photo.')
    return 0 if not bad else 1

if __name__=='__main__':
    raise SystemExit(main())
