import requests
from .config import ESP_URL

class DeviceError(RuntimeError):
    pass

def status():
    try:
        r = requests.get(ESP_URL + '/button', timeout=1.3)
        r.raise_for_status()
        data = r.json()
        return {'connected':True, **data}
    except (requests.RequestException, ValueError):
        return {'connected':False, 'camera_armed':False, 'button_press_count':0}

def capture():
    try:
        r = requests.get(ESP_URL + '/capture', timeout=18)
    except requests.RequestException as e:
        raise DeviceError(f'TIKI camera connection failed: {e}') from e
    if r.status_code == 403:
        raise DeviceError('Camera permission expired. Press the physical button again.')
    if not r.ok:
        raise DeviceError(f'Camera failed (HTTP {r.status_code}): {r.text[:180]}')
    if (not r.headers.get('content-type','').startswith('image/jpeg') or len(r.content) < 300
            or not r.content.startswith(b'\xff\xd8') or not r.content.endswith(b'\xff\xd9')):
        raise DeviceError('Incomplete JPEG from TIKI camera. Check camera power and Wi-Fi.')
    return r.content

def send_pcm(data):
    try:
        r = requests.post(ESP_URL + '/pcm', files={'file':('reply.pcm',data,'application/octet-stream')}, timeout=70)
        r.raise_for_status()
        return r.text[:160]
    except requests.RequestException as e:
        raise DeviceError(f'Could not send audio to speaker: {e}') from e


def beep():
    """Manual speaker self-test; no AI or TTS key needed."""
    try:
        response=requests.get(ESP_URL + '/beep', timeout=12)
        response.raise_for_status()
        return response.text[:160]
    except requests.RequestException as e:
        raise DeviceError(f'Could not play test tones: {e}') from e
