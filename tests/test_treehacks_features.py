"""Behavior-focused tests; no Gemini bills and no actual ESP32 power required."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Event
import time

from fastapi.testclient import TestClient
from app import brain, device, main, retrieval, store

client = TestClient(main.app)


def test_camera_intent_requires_explicit_request():
    for text in ('What is a whiteboard?', 'Tell me about dog breeds',
                 'Explain the concept of visual attention',
                 'Could you help me with this?'):
        assert not brain.wants_camera(text), text
    for text in ('Hey TIKI, look at this dog',
                 'Take a pic of the board and make notes for me later',
                 'Read this page for me'):
        assert brain.wants_camera(text), text


def test_relevant_recall_and_source_provenance():
    memory_id = store.add_memory('My lumicube spectrometer prototype is powered by solar panels')
    other_id = store.add_memory('Secret marshmallow preference from a different topic')
    note_id = store.add_note('Captured board: Lumicube notes',
                             'First concept: spectroscopy. Second concept: diffraction.',
                             'photo_demo_test.jpg')
    retrieved = retrieval.search('What was the second concept on that board?',limit=8)
    assert any(r['kind']=='note' and r['id']==note_id for r in retrieved)
    prompt = retrieval.safe_context(retrieved)
    assert f'NOTE#{note_id}' in prompt and 'diffraction' in prompt
    tech = retrieval.search('lumicube spectrometer prototype',limit=8)
    assert any(r['kind']=='memory' and r['id']==memory_id for r in tech)
    assert not any(r['kind']=='memory' and r['id']==other_id for r in tech)


def test_reminder_due_time_interpreter():
    title, due = brain.interpret_reminder('remind me to test the camera in 20 minutes')
    assert title == 'test the camera'
    assert due is not None
    delta=(datetime.fromisoformat(due)-datetime.now().astimezone()).total_seconds()
    assert 19*60 <= delta <= 21*60
    title, due = brain.interpret_reminder('remind me to read the board tomorrow at 8pm')
    assert title == 'read the board' and datetime.fromisoformat(due).hour == 20
    assert brain.interpret_reminder('remind me to charge TIKI later')[1] is None


def test_speaker_diagnostic_endpoint(monkeypatch):
    monkeypatch.setattr(device,'beep',lambda:'Three tones played')
    assert client.post('/api/device/chime').json()['result']=='Three tones played'
    response=client.get('/api/diagnostics').json()
    assert 'gemini_enabled' in response and 'device_connected' in response


def test_camera_request_cannot_double_capture_even_with_racing_calls(monkeypatch):
    fake={'connected':True,'camera_ready':True,'camera_armed':False,'button_press_count':21}
    monkeypatch.setattr(device,'status',lambda:fake.copy())
    assert client.post('/api/camera/request',json={'text':'Take a photo of this page'}).status_code==200
    fake.update(camera_armed=True, button_press_count=22)
    capturing=Event();allow_finish=Event();calls=[]
    def capture():
        calls.append(1)
        capturing.set()
        assert allow_finish.wait(timeout=4)
        return b'\xff\xd8'+b'\x01'*900+b'\xff\xd9'
    monkeypatch.setattr(device,'capture',capture)
    monkeypatch.setattr(main.brain,'vision_analysis',lambda *_args,**_kw:'This is a simulated scene in a test, not actual vision.')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(client.post,'/api/camera/complete')
        assert capturing.wait(timeout=4)
        second=client.post('/api/camera/complete')
        assert second.status_code==409
        allow_finish.set()
        result=first.result(timeout=4)
    assert result.status_code==200, result.text
    assert len(calls)==1
    assert client.post('/api/camera/complete').status_code==409
    assert result.json()['note_id'] is None
    assert client.get(result.json()['photo_url']).status_code==200


def test_local_mac_speech_can_reach_device_without_gemini(monkeypatch):
    monkeypatch.setattr(device,'status',lambda:{'connected':True})
    monkeypatch.setattr(main.audio,'synthesize_pcm',lambda text:b'\x01\x02\x03\x04'*20)
    outgoing=[]
    monkeypatch.setattr(device,'send_pcm',lambda pcm:outgoing.append(pcm))
    result=client.post('/api/speak',json={'text':'TIKI, say hello!'}).json()
    assert result['target']=='tiki'
    assert result['bytes']==80 and len(outgoing)==1


def test_plans_question_finds_saved_tasks_even_without_shared_words():
    new_id = store.add_reminder('Finish telescope motor calibration', '2026-11-01T08:30:00+05:30')
    found = brain.relevant_sources('Hey TIKI, I am behind on my schedule, what should I work on?')
    assert any(r['kind']=='task' and r['id']==new_id for r in found)


def test_natural_visual_request_is_not_missed():
    assert brain.wants_camera('Hey TIKI could you look through the camera and tell me if that is a rose?')


def test_phone_camera_is_real_explicit_upload(monkeypatch):
    from PIL import Image
    from io import BytesIO
    image=Image.new('RGB',(64,64),'#acb7aa')
    output=BytesIO(); image.save(output,format='JPEG');jpeg=output.getvalue()
    monkeypatch.setattr(main.brain,'vision_analysis',lambda *_a, **_kw:'The photo shows a plant. Breed or species uncertain.')
    result=client.post('/api/phone/photo',files={'file':('plant.jpg',jpeg,'image/jpeg')},
                       data={'text':'Look at this plant. Is it a rose?'})
    assert result.status_code==200, result.text
    data=result.json()
    assert 'plant' in data['reply'] and data['photo_url'].startswith('/api/photos/')
    with Image.open(BytesIO(client.get(data['photo_url']).content)) as result_image:
        assert result_image.size == (64,64)
        assert result_image.format == 'JPEG'
    bad=client.post('/api/phone/photo',files={'file':('not_a_photo.jpg',b'INVALID','image/jpeg')},
                    data={'text':'Look at this plant'})
    assert bad.status_code==415
