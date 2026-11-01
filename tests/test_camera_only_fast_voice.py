"""One-request voice reply and camera-only physical button behavior."""
from fastapi.testclient import TestClient
from app import main, audio, device, store


def test_fast_voice_single_call_and_local_memory(monkeypatch):
    called=[]
    def fake_fast(filename, data, content_type, context):
        called.append((data,content_type,context))
        return 'What is your name?', 'I am TIKI, your small wearable companion.'
    monkeypatch.setattr(audio,'understand_and_answer',fake_fast)
    monkeypatch.setattr(main.brain,'handle_command',lambda t:None)
    monkeypatch.setattr(main.brain,'ask_ai',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Should not call Gemini twice')))
    resp=TestClient(main.app).post('/api/voice/fast',files={'file':('voice.webm',b'fake-webm-bytes','audio/webm')})
    assert resp.status_code==200
    assert resp.json()['text']=='What is your name?'
    assert resp.json()['kind']=='conversation'
    assert 'TIKI' in resp.json()['reply']
    assert len(called)==1


def test_camera_voice_waits_for_physical_permission(monkeypatch):
    monkeypatch.setattr(audio,'understand_and_answer',lambda *_:('Hey TIKI, look at this dog, what breed?', 'I see a dog'))
    hits=[]
    monkeypatch.setattr(device,'status',lambda:{'connected':True,'button_press_count':9,'button_pressed':False})
    monkeypatch.setattr(device,'capture',lambda:hits.append('photo') or b'\xff\xd8'+b'0'*500+b'\xff\xd9')
    resp=TestClient(main.app).post('/api/voice/fast',files={'file':('voice.webm',b'voice','audio/webm')})
    assert resp.status_code==200 and resp.json()['kind']=='camera_permission'
    assert store.setting('pending_camera')['after_press']==9
    assert hits==[]


def test_silence_fast_voice_is_not_accepted(monkeypatch):
    monkeypatch.setattr(audio,'understand_and_answer',lambda *_:('',''))
    resp=TestClient(main.app).post('/api/voice/fast',files={'file':('voice.webm',b'voice','audio/webm')})
    assert resp.status_code==422


def test_physical_button_is_not_microphone(monkeypatch):
    from app.bridge import MacBridge
    b=MacBridge()
    state={'connected':True,'button_press_count':3,'button_pressed':False}
    monkeypatch.setattr(device,'status',lambda:state.copy())
    attempts=[]
    monkeypatch.setattr(b,'_start_record',lambda *args,**kwargs:attempts.append('mic'))
    monkeypatch.setattr(b,'_capture_pending_photo',lambda pid:attempts.append(('camera',pid)))
    b._poll_device()
    state['button_press_count']=4
    b._poll_device()
    import time
    for _ in range(100):
        if attempts: break
        time.sleep(.005)
    assert attempts==[('camera',4)]
