"""Regression coverage: CAMERA-ONLY button does not depend on Mac audio."""
import time
from app.bridge import MacBridge

def test_camera_button_survives_microphone_failure(monkeypatch):
    from app import device
    b = MacBridge()
    state={'counter':5}
    monkeypatch.setattr(device, 'status', lambda: {
        'connected': True, 'button_press_count': state['counter'],
        'button_pressed': False, 'camera_ready': True, 'audio_initialized': True
    })
    photos=[]
    monkeypatch.setattr(b, '_capture_pending_photo', lambda press_id: photos.append(press_id))
    monkeypatch.setattr(b, '_run', lambda: b.publish('mic-error', 'Mic intentionally unavailable'))
    b.start()
    try:
        time.sleep(.65)
        state['counter'] += 1
        for _ in range(25):
            if photos: break
            time.sleep(.07)
        assert photos == [6]
        assert b.active_source is None
        assert b.record is None
    finally:
        b.close()

def test_camera_press_queued_when_speaker_busy(monkeypatch):
    from app import device
    b=MacBridge()
    count={'n':10}
    monkeypatch.setattr(device,'status',lambda:{'connected':True,'button_press_count':count['n']})
    photos=[]
    monkeypatch.setattr(b,'_capture_pending_photo',lambda press_id:photos.append(press_id))
    b._poll_device() # establish counter baseline
    b.busy=True
    count['n']=11
    b._poll_device() # press noticed but pending while speaking
    assert b.deferred_press == 11
    assert not photos
    b.busy=False
    b._poll_device()
    for _ in range(50):
        if photos:break
        time.sleep(.01)
    assert photos==[11]
