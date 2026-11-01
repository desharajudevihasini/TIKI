"""Check the actual ESP32 GPIO40 camera button without Gemini or microphone access."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ESP_URL
from app.device import status

print('TIKI camera-only button test')
print('ESP32:', ESP_URL)
first = status()
if not first['connected']:
    sys.exit('FAIL: Mac cannot reach ESP32 /button. Verify the IP in Arduino Serial Monitor and .env, and check both are on the same 2.4 GHz Wi-Fi.')
print('ESP32 connected. Camera ready:', first.get('camera_ready', 'unknown'))
if 'button_press_count' not in first:
    sys.exit('FAIL: /button response lacks button_press_count.')
start=int(first['button_press_count'])
print('Initial press count:', start)
print('TAP and RELEASE the physical glasses button ONCE within 12 seconds. (Do not hold to speak.)', flush=True)
end=time.monotonic()+12
failures=0
while time.monotonic()<end:
    now=status()
    if not now.get('connected'):
        failures += 1
        if failures > 3:
            sys.exit('FAIL: Wi-Fi connection dropped while checking the button. Check ESP32 IP and power.')
        continue
    count=int(now.get('button_press_count', start))
    if count>start:
        print('PASS: Physical button registered, count', start,'->',count)
        print('The hardware button works. If the app still does not capture, verify the background camera watcher is running (/api/bridge/state).')
        sys.exit(0)
    time.sleep(.35)
sys.exit('FAIL: Button counter did not increase. Inspect Arduino Serial Monitor while pressing. If it logs no presses, check GPIO40 button wiring.')
