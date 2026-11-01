"""TIKI quick, safe smoke test; reads .env locally, never prints API secrets.

python tools/doctor.py       # full check + live 12s button test
python tools/doctor.py --quick   # startup preflight without interactive button test
"""
import json
import os
import sys
import time
import wave
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
except ImportError:
    print('ERROR: Missing python-dotenv. Run: python -m pip install -r requirements.txt')
    raise SystemExit(2)

ESP=os.getenv('TIKI_ESP_URL','http://192.168.0.115').rstrip('/')
QUICK='--quick' in sys.argv

print('\n==== TIKI CONNECTION CHECK ====')
print('1. ESP32 URL:',ESP)
print('   GEMINI_API_KEY:', 'configured (hidden)' if os.getenv('GEMINI_API_KEY','').strip() else 'MISSING — AI conversation cannot run')

try:
    import requests
    r=requests.get(ESP+'/button',timeout=3)
    r.raise_for_status()
    data=r.json()
    print('2. ESP32 reachable: YES (HTTP 200)')
    if 'button_pressed' not in data or 'button_press_count' not in data:
        print('   ERROR: ESP32 response does not contain button_pressed and button_press_count.')
        print('   Your firmware is incompatible with the voice bridge.')
        print('   Response:',json.dumps(data)[:350])
        raise SystemExit(3)
    firmware='permission camera' if 'camera_armed' in data and 'button_release_count' in data else 'older button firmware (voice compatible)'
    print('   Button firmware:',firmware)
    print('   Press count:',data['button_press_count'],'  Currently pressed:',data['button_pressed'])
    print('   Camera ready:',data.get('camera_ready','unknown'),' Speaker initialized:',data.get('audio_initialized','unknown'))
    if data.get('network') in ('hotspot','TIKI-TEST'):
        print('   NOTE: ESP32 is in TIKI-TEST hotspot mode. Mac must join TIKI-TEST or reconnect device to home Wi-Fi.')
except SystemExit:
    raise
except Exception as e:
    print('2. ESP32 reachable: NO')
    print('   Error:',str(e)[:240])
    print('   FIX: Open Arduino Serial Monitor (115200) and read its latest IP.')
    print('   FIX: Mac and ESP32 must be on the SAME Wi-Fi. Set TIKI_ESP_URL=http://<actual-IP> in .env.')
    print('   No microphone/button code can work until this test succeeds.')
    raise SystemExit(2)

try:
    import sounddevice as sd
    dev=os.getenv('TIKI_INPUT_DEVICE')
    dev=int(dev) if dev and dev.isdecimal() else dev or None
    info=sd.query_devices(dev,kind='input')
    print('3. Mac microphone detected:',info['name'])
    if not QUICK:
        rate=16000
        try:sd.check_input_settings(device=dev,channels=1,dtype='int16',samplerate=rate)
        except Exception:rate=int(info['default_samplerate'])
        with sd.RawInputStream(device=dev,channels=1,dtype='int16',samplerate=rate):
            time.sleep(.25)
        print('   Microphone capture: OPENED successfully')
except Exception as e:
    print('3. Mac microphone: NOT READY —',str(e)[:250])
    print('   FIX: Allow microphone for VS Code/Terminal in System Settings → Privacy & Security → Microphone.')
    raise SystemExit(4)

if QUICK:
    print('4. Startup preflight passed. For a button test run: python tools/doctor.py')
    raise SystemExit(0)

print('\n4. HOLD THE PHYSICAL BUTTON FOR TWO SECONDS, then RELEASE it (12-second test).')
print('   Keep the board on, point your microphone toward yourself.')
last=None
seen_down=False
seen_up=False
end=time.monotonic()+12
while time.monotonic()<end:
    try:
        s=requests.get(ESP+'/button',timeout=1.5).json()
        cur=bool(s['button_pressed'])
        if last is None:
            last=cur
            if cur:print('   BUTTON DOWN (already held)');seen_down=True
        elif cur != last:
            print('   BUTTON DOWN — detected' if cur else '   BUTTON UP — detected')
            if cur:seen_down=True
            else:seen_up=True
            last=cur
        if seen_down and seen_up:break
    except Exception as e:
        print('   Network interruption:',e)
        break
    time.sleep(.09)
if seen_down and seen_up:
    print('RESULT: PASS — device, button down/up, and Mac microphone are reachable.')
    print('NEXT: Run TIKI server. It can now record on button hold and release.')
else:
    print('RESULT: Button transitions not confirmed.')
    print('Hold for 2 seconds while this command is running. Ensure the GPIO40 button connects to GND.')
    raise SystemExit(5)
