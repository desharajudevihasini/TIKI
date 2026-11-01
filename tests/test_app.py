"""API integration checks with a mocked ESP32; never requires hardware or API billing."""
import os
import tempfile
from pathlib import Path
os.environ['TIKI_DATA_DIR']=tempfile.mkdtemp(prefix='tiki_test_')
os.environ['TIKI_DEMO_MODE']='1'

from fastapi.testclient import TestClient
from app import main, device, store

c=TestClient(main.app)

def test_static_frontend_and_state(monkeypatch):
    monkeypatch.setattr(device,'status',lambda:{'connected':False,'camera_armed':False,'button_press_count':0})
    assert c.get('/').status_code==200
    assert 'TIKI' in c.get('/').text
    result=c.get('/api/state').json()
    assert result['demo_mode'] is True
    assert result['device']['connected'] is False

def test_modes_chat_memory_and_tasks():
    assert c.post('/api/chat',json={'text':'Hey TIKI spots on'}).status_code==200
    assert c.get('/api/state').json()['active'] is True
    assert c.post('/api/chat',json={'text':'Work mode'}).json()['mode']=='work'
    r=c.post('/api/chat',json={'text':'Remember that I enjoy short answers.'}).json()
    assert 'saved' in r['reply'].lower()
    assert any('short answers' in x['content'] for x in c.get('/api/memories').json())
    assert len(c.get('/api/history').json())>=3
    assert c.post('/api/chat',json={'text':'Remind me to test TIKI later'}).status_code==200
    assert any('test tiki' in x['title'].lower() for x in c.get('/api/reminders').json())

def test_camera_denied_without_new_press(monkeypatch):
    monkeypatch.setattr(device,'status',lambda:{'connected':True,'camera_armed':False,'button_press_count':3})
    assert c.post('/api/chat',json={'text':'Look at this whiteboard and make notes for me'}).json()['kind']=='camera_permission'
    r=c.post('/api/camera/complete')
    assert r.status_code==409
    assert 'physical button' in r.json()['detail'].lower()
    assert c.get('/api/state').json()['pending_camera'] is not None

def test_camera_authorized_once_and_saved(monkeypatch):
    fake_status={'connected':True,'camera_armed':False,'button_press_count':3}
    monkeypatch.setattr(device,'status',lambda:fake_status.copy())
    monkeypatch.setattr(device,'capture',lambda:b'\xff\xd8'+b'\x00'*500+b'\xff\xd9')
    monkeypatch.setattr(main.brain,'vision_analysis',lambda image,prompt,mode,note:'Simulated image analysis for testing only')
    assert c.post('/api/camera/request',json={'text':'Make notes from this board'}).status_code==200
    fake_status.update(camera_armed=True,button_press_count=4)
    result=c.post('/api/camera/complete')
    assert result.status_code==200, result.text
    data=result.json()
    assert data['photo_url'].endswith('.jpg')
    assert c.get(data['photo_url']).content.startswith(b'\xff\xd8')
    assert data['note_id'] is not None
    assert c.get('/api/notes').json()
    assert c.post('/api/camera/complete').status_code==409

def test_crud():
    r=c.post('/api/memories',json={'content':'I enjoy calm explanations'}).json()
    assert c.delete('/api/memories/'+str(r['id'])).status_code==200
    todo=c.post('/api/reminders',json={'title':'Record demo','due_at':'2026-11-01T10:30'}).json()
    assert c.post(f"/api/reminders/{todo['id']}/toggle").status_code==200
    assert c.delete(f"/api/reminders/{todo['id']}").status_code==200
    assert c.get('/api/photos/..%2Fetc%2Fpasswd').status_code in (404,422)
