import pytest
from app import main,store,device
from fastapi.testclient import TestClient

def test_button_first_what_is_this_requires_real_camera_permission(monkeypatch):
    c=TestClient(main.app)
    state={'connected':True,'camera_armed':True,'button_press_count':21,'camera_ready':True}
    monkeypatch.setattr(device,'status',lambda:state.copy())
    monkeypatch.setattr(device,'capture',lambda:b'\xff\xd8'+b'0'*700+b'\xff\xd9')
    monkeypatch.setattr(main.brain,'vision_analysis',lambda image,prompt,mode,note:'A sample object, in simulated test')
    r=c.post('/api/chat',json={'text':'Hey TIKI, what is this?'})
    assert r.status_code==200 and r.json()['kind']=='camera_permission'
    assert main.store.setting('pending_camera')['after_press']==21
    complete=main.camera_complete_from_button(21)
    assert 'sample object' in complete['reply']
    assert main.store.setting('pending_camera') is None
