"""Covers the actual signature workflow with local mock ESP32 and Gemini.
No real API keys or live hardware are used by these tests.
"""
import io
import time
import zipfile
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from PIL import Image

from app import main, brain, store, device, vision_memory, retrieval, reminder_service
from app.bridge import MacBridge, SAMPLE_RATE, plausible_transcript, speech_quality


def valid_jpeg(color='orange'):
    mem=io.BytesIO()
    Image.new('RGB',(100,80),color).save(mem,'JPEG')
    return mem.getvalue()


def test_legacy_press_photo_is_persisted_and_recalled(monkeypatch):
    current={'connected':True,'camera_ready':True,'audio_initialized':True,
             'button_pressed':False,'button_press_count':91}
    monkeypatch.setattr(device,'status',lambda:current.copy())
    photo=valid_jpeg('blue')
    seen=[]
    monkeypatch.setattr(device,'capture',lambda: seen.append('camera') or photo)
    monkeypatch.setattr(brain,'vision_analysis',lambda raw,prompt,*_: 'The image shows a blue ceramic cup on a table.')
    result=main.chat(main.Chat(text='Hey TIKI, take a picture and describe the cup'))
    assert result['kind']=='camera_permission'
    assert store.setting('pending_camera')['after_press']==91
    got=main.camera_complete_from_button(91)
    assert seen==['camera']
    assert got['capture_id']>0
    assert got['photo_url'].startswith('/api/photos/')
    assert got['spoken_reply']=='The image shows a blue ceramic cup on a table.'
    c=TestClient(main.app)
    assert c.get(got['photo_url']).content==photo
    assert any(row['id']==got['capture_id'] for row in c.get('/api/captures').json())
    hits=retrieval.search('blue ceramic cup',limit=10)
    assert any(r['kind']=='photo' and r['id']==got['capture_id'] for r in hits)
    assert c.post('/api/camera/complete').status_code==409


def test_photo_task_suggestions_are_opt_in(monkeypatch):
    vision_memory.decide_tasks(False)
    d={'connected':True,'button_press_count':105,'button_pressed':False,
       'camera_ready':True,'audio_initialized':True}
    monkeypatch.setattr(device,'status',lambda:d.copy())
    monkeypatch.setattr(device,'capture',lambda:valid_jpeg('white'))
    monkeypatch.setattr(brain,'vision_analysis',lambda *_:'This board says: Finish the prototype by Friday.')
    monkeypatch.setattr(vision_memory,'extract_tasks_from_photo',lambda *_:[
        {'task':'Finish the prototype','visible_evidence':'Finish the prototype',
         'due_text':'Friday','confidence':'high'}])
    store.set_setting('pending_camera',{
        'text':'Look at this assignment board and find tasks',
        'after_press':105, 'notes':True,'created_at':time.time()})
    before=len(store.reminders())
    got=main.camera_complete_from_button(105)
    assert got['proposed_tasks']
    assert len(store.reminders())==before
    assert got['note_id']
    assert 'Save' in got['reply'] or 'save' in got['reply']
    first=main.chat(main.Chat(text='TIKI, save those tasks'))
    assert first['kind']=='command'
    assert len(store.reminders())==before+1
    assert len(store.reminders())==before+1  # no duplicate on retry
    second=main.chat(main.Chat(text='save those tasks'))
    assert 'no pending' in second['reply'].lower()
    assert len(store.reminders())==before+1


def test_photo_task_sanitizer_requires_visible_evidence():
    assert vision_memory.sanitize_suggested_tasks({'tasks':[
        {'task':'Finish poster','visible_evidence':'','confidence':'high'},
        {'task':'Submit application','visible_evidence':'submit application',
         'due_text':'Nov 1','confidence':'medium'},
        {'task':'Submit application','visible_evidence':'submit application',
         'due_text':'Nov 1','confidence':'medium'},
        {'task':'Secret task','visible_evidence':'word','confidence':'uncertain'},
    ]})==[{'task':'Submit application','visible_evidence':'submit application',
          'due_text':'Nov 1','confidence':'medium'}]


def test_phone_png_becomes_jpeg_without_metadata(monkeypatch):
    photo=io.BytesIO();Image.new('RGBA',(20,20),'red').save(photo,'PNG')
    monkeypatch.setattr(brain,'vision_analysis',lambda *_:'I see a red square.')
    c=TestClient(main.app)
    resp=c.post('/api/phone/photo',files={'file':('screen.png',photo.getvalue(),'image/png')},
                data={'text':'TIKI, look at this red square'})
    assert resp.status_code==200,resp.text
    data=resp.json();jpeg=c.get(data['photo_url']).content
    assert jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
    assert Image.open(io.BytesIO(jpeg)).format=='JPEG'
    assert data['spoken_reply']=='I see a red square.'


def test_silence_does_not_create_fake_transcript():
    assert speech_quality(b'\0\0'*SAMPLE_RATE*2)[0] is False
    assert plausible_transcript('Thank you for watching!',2) is False
    assert plausible_transcript('I am showing you a dog',3) is True
    assert plausible_transcript('Here are many words '+('nonsense '*100),1) is False


def test_search_and_delete_capture_only(monkeypatch):
    jpeg=valid_jpeg('purple')
    monkeypatch.setattr(brain,'vision_analysis',lambda *_:'A purple marker is on the table.')
    c=TestClient(main.app)
    upload=c.post('/api/phone/photo',files={'file':('marker.jpg',jpeg,'image/jpeg')},
                  data={'text':'Look at this purple marker and remember it'})
    assert upload.status_code==200
    row=upload.json()
    url=row['photo_url']; cap_id=row['capture_id']
    assert c.get('/api/search?q=purple%20marker').status_code==200
    assert c.delete('/api/captures/'+str(cap_id)).status_code==200
    assert c.get(url).status_code==404
    assert c.delete('/api/captures/'+str(cap_id)).status_code==404
    assert c.get('/api/photos/../.env').status_code in (404,405)


def test_memory_export_has_db_and_original_photos_but_not_api_key():
    c=TestClient(main.app)
    result=c.get('/api/backup')
    assert result.status_code==200
    with zipfile.ZipFile(io.BytesIO(result.content)) as z:
        names=z.namelist()
        assert 'data/tiki.sqlite3' in names
        assert any(x.endswith('.jpg') for x in names)
        assert '.env' not in '\n'.join(names)


def test_reminder_speaker_announces_once(monkeypatch):
    due=(datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat()
    mid=store.add_reminder('Review saved whiteboard',due)
    calls=[]
    def speaker(text):
        calls.append(text)
        return {'target':'tiki'}
    row=next(t for t in reminder_service.eligible_due() if t['id']==mid)
    assert reminder_service.announce_one(row,speaker)
    assert calls==['Reminder: Review saved whiteboard']
    assert all(t['id']!=mid for t in reminder_service.eligible_due())


def test_spoken_summary_keeps_short_sentence_unchanged():
    assert brain.spoken_summary('I see a brown dog.')=='I see a brown dog.'
    long='The camera can see a whiteboard. '+('There is more writing here. '*50)
    result=brain.spoken_summary(long)
    assert result.endswith('.') and len(result)<600


def test_vision_api_outage_keeps_the_actual_photo(monkeypatch):
    d={'connected':True,'button_press_count':207,'button_pressed':False,'camera_ready':True}
    jpeg=valid_jpeg('green')
    monkeypatch.setattr(device,'status',lambda:d.copy())
    monkeypatch.setattr(device,'capture',lambda:jpeg)
    def out_of_service(*args):raise RuntimeError('503 Google overloaded')
    monkeypatch.setattr(brain,'vision_analysis',out_of_service)
    store.set_setting('pending_camera',{'text':'Take a picture of this green object',
                        'notes':False,'after_press':207,'created_at':time.time()})
    result=main.camera_complete_from_button(207)
    assert 'Photo saved' in result['reply']
    assert TestClient(main.app).get(result['photo_url']).content==jpeg
    assert store.capture_by_id(result['capture_id'])
