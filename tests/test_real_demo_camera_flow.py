"""Simulation of the real user's firmware, button, camera and speaker API calls."""
import time

from fastapi.testclient import TestClient
from app import main, device, audio, store
from app.bridge import MacBridge, SAMPLE_RATE


def test_same_legacy_physical_press_captures_once_and_speaks_through_tiki(monkeypatch):
    # The user's working ESP32 firmware does NOT expose camera_armed.
    d={'connected':True,'camera_ready':True,'audio_initialized':True,
       'button_pressed':False,'button_press_count':11}
    monkeypatch.setattr(device,'status',lambda:d.copy())
    jpeg=b'\xff\xd8'+b'JPEGDATA'*80+b'\xff\xd9'
    captures=[]
    monkeypatch.setattr(device,'capture',lambda:captures.append('captured') or jpeg)
    monkeypatch.setattr(main.brain,'vision_analysis',lambda raw,text,*_:'I see a blue mug on a desk.')
    replies=[]
    monkeypatch.setattr(main,'speak',lambda item: replies.append(item.text) or {'target':'tiki'})
    # A spoken request sets pending camera without taking an image.
    result=main.chat(main.Chat(text='TIKI, take a picture and tell me what you see'))
    assert result['kind']=='camera_permission'
    assert captures==[]
    # The user's ONE physical camera-button tap authorizes capture.
    d['button_press_count']=12
    b=MacBridge();b.busy=True
    b._capture_pending_photo(12)
    assert captures==['captured']
    assert 'blue mug' in b.answer
    assert b.photo_url.startswith('/api/photos/')
    assert replies==['I see a blue mug on a desk.']
    assert store.setting('pending_camera') is None
    assert TestClient(main.app).get(b.photo_url).content==jpeg
    assert TestClient(main.app).post('/api/camera/complete').status_code==409
    assert captures==['captured']


def test_legacy_unapproved_http_camera_rejected(monkeypatch):
    d={'connected':True,'camera_ready':True,'button_press_count':20,
       'button_pressed':False}
    monkeypatch.setattr(device,'status',lambda:d.copy())
    c=TestClient(main.app)
    r=c.post('/api/chat',json={'text':'TIKI, take a picture and describe it'})
    assert r.json()['kind']=='camera_permission'
    assert c.post('/api/camera/complete').status_code==409
    assert store.setting('pending_camera')['after_press']==20
    # A confirmed new hardware press is permitted even with legacy firmware.
    d['button_press_count']=21
    monkeypatch.setattr(device,'capture',lambda:b'\xff\xd8'+b'3'*500+b'\xff\xd9')
    monkeypatch.setattr(main.brain,'vision_analysis',lambda *_:'There is a notebook.')
    result=main.camera_complete_from_button(21)
    assert 'notebook' in result['reply']


def test_camera_request_not_auto_authorized_by_previous_new_firmware_press(monkeypatch):
    d={'connected':True,'camera_ready':True,'camera_armed':True,
       'button_release_count':7,'button_press_count':7}
    monkeypatch.setattr(device,'status',lambda:d.copy())
    c=TestClient(main.app)
    assert c.post('/api/chat',json={'text':'take a picture'}).status_code==200
    assert store.setting('pending_camera')['after_press']==7
    assert c.post('/api/camera/complete').status_code==409


def test_silence_wake_session_does_not_call_ai(monkeypatch):
    b=MacBridge()
    sent=[]
    monkeypatch.setattr(b,'_process',lambda *args:sent.append(args))
    b.record=[b'\x00\x00'*SAMPLE_RATE]
    b.session_press_id=12
    b.active_source='wake'
    b._finish_record()
    assert not sent
    assert b.state=='ready'
