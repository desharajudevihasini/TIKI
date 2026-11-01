"""Mock-only audio transport and privacy regression checks."""
import io
from fastapi.testclient import TestClient
from app import main, audio, device


def test_speak_calls_hardware_pcm_upload_not_os_playback(monkeypatch):
    device_status={'connected':True,'audio_initialized':True,'button_press_count':0}
    monkeypatch.setattr(device,'status',lambda:device_status)
    pcm=b'\x00\x10\x00\x10'*1600
    synthesized=[];sent=[]
    monkeypatch.setattr(audio,'synthesize_pcm',lambda text:synthesized.append(text) or pcm)
    monkeypatch.setattr(device,'send_pcm',lambda raw: sent.append(raw) or 'OK')
    c=TestClient(main.app)
    result=c.post('/api/speak',json={'text':'Spots on. I see a camera.'})
    assert result.status_code==200
    assert result.json()=={'target':'tiki','bytes':len(pcm)}
    assert synthesized==['Spots on. I see a camera.']
    assert sent==[pcm]


def test_speaker_transport_failure_is_visible_not_mac_fallback(monkeypatch):
    monkeypatch.setattr(device,'status',lambda:{'connected':True,'audio_initialized':True})
    monkeypatch.setattr(audio,'synthesize_pcm',lambda _:b'abcd')
    def fail(_):raise device.DeviceError('ESP32 speaker disconnected')
    monkeypatch.setattr(device,'send_pcm',fail)
    r=TestClient(main.app).post('/api/speak',json={'text':'Check audio'})
    assert r.json()['target']=='error'
    assert 'disconnected' in r.json()['reason']


def test_photo_api_does_not_allow_unapproved_capture(monkeypatch):
    monkeypatch.setattr(device,'status',lambda:{'connected':True,'button_press_count':2,'button_pressed':False,'camera_ready':True})
    from app import store
    store.set_setting('pending_camera',None)
    r=TestClient(main.app).post('/api/camera/complete')
    assert r.status_code==409
