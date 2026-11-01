import re
import threading
import uuid
import os
import sqlite3
import tempfile
import zipfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store, brain, device, audio, retrieval, vision_memory
from .config import ROOT, PHOTO_DIR, DEMO_MODE, ESP_URL

store.init()
app = FastAPI(title='TIKI — Smart Glasses Companion', version='4.0.0')

# The Mac gateway monitors camera-button presses and optional wake speech.
# Browser speech uses the Talk control; the hardware button is camera-only.
from .bridge import bridge
from .reminder_service import worker as reminder_worker
import sys

@app.on_event('startup')
def start_mac_bridge():
    if sys.platform == 'darwin' and os.getenv('TIKI_MAC_BRIDGE','1') == '1':
        bridge.start()
    reminder_worker.start()

@app.on_event('shutdown')
def stop_mac_bridge():
    reminder_worker.close()
    bridge.close()

class WakeToggle(BaseModel):
    enabled: bool

@app.get('/api/bridge/state')
def bridge_state():
    return bridge.snapshot()

@app.post('/api/bridge/wake')
def bridge_wake(payload: WakeToggle):
    return bridge.toggle_wake(payload.enabled)

CAMERA_CAPTURE_LOCK = threading.Lock()
SPEAKER_LOCK = threading.Lock()

class Chat(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

class MemoryInput(BaseModel):
    content: str = Field(min_length=3, max_length=1000)

class ReminderInput(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    due_at: Optional[str] = None

class NoteInput(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=2, max_length=10000)

class ModeInput(BaseModel):
    mode: str

class CameraRequest(BaseModel):
    text: str = Field(min_length=2, max_length=1000)

class DecisionInput(BaseModel):
    approve: bool

class SpeakInput(BaseModel):
    text: str = Field(min_length=1, max_length=800)


def device_state():
    d = device.status()
    return d

@app.get('/api/state')
def state():
    return {
        'mode': store.setting('mode','companion'),
        'active': store.setting('active',False),
        'demo_mode': DEMO_MODE,
        'device': device_state(),
        'pending_camera': store.setting('pending_camera'),
        'esp_url': ESP_URL,
        'proposed_tasks': vision_memory.pending_tasks(),
        'last_photo': next(iter(store.captures()), None),
    }

@app.get('/api/search')
def search_saved(q: str):
    if len(q) > 300:
        raise HTTPException(400, 'Search is too long')
    hits = retrieval.search(q, limit=10)
    return [{'kind':r['kind'],'id':r['id'],'title':r['title'],
             'excerpt':r['text'][:280], 'label':r['label'],
             'photo_url': '/api/photos/'+r['photo_filename'] if r.get('photo_filename') else None} for r in hits]

@app.get('/api/diagnostics')
def diagnostics():
    d = device_state()
    return {'device_connected':bool(d.get('connected')),
            'device_camera_ready':bool(d.get('camera_ready')),
            'device_audio_ready':bool(d.get('audio_initialized')),
            'physical_camera_permission_supported':'camera_armed' in d and d.get('connected'),
            'gemini_enabled':not DEMO_MODE,
            'speaker_macos_tts_enabled':audio.MAC_TTS,
            'memory_database':'local SQLite',
            'camera_note':'Physical button authorizes exactly one camera capture. Speak with the on-screen Talk control; legacy firmware does not gate /capture at the device endpoint.'}

@app.get('/api/history')
def history():
    return store.history(80)

@app.post('/api/chat')
def chat(request: Chat):
    text = request.text.strip()
    store.add_message('user', text)
    # Photo requests override the generic 'remember' command so phrases like
    # 'remember this board' actually capture the visible board first.
    command = None if brain.wants_camera(text) else brain.handle_command(text)
    if command is not None:
        reply, kind = command, 'command'
    else:
        # Camera requests must be explicit. The native bridge can use the SAME
        # physical press as the voice question for one authorized image.
        # Browser requests require a separate hardware press.
        # Ordinary conversations have no reason to wait for ESP32 /button.
        # The Mac bridge already polls it. Check hardware ONLY for visual requests.
        visual_request = brain.wants_camera(text)
        ambiguous_visual_question = bool(re.search(
            r"\b(?:what(?:'s| is) this|what(?:'s| is) that|tell me about this)\b",text,re.I))
        d = device_state() if (visual_request or ambiguous_visual_question) else {}
        armed = bool(d.get('connected') and d.get('camera_armed'))
        camera_request = visual_request or (armed and ambiguous_visual_question)
        if camera_request:
            press_count = int(d.get('button_press_count',0))
            pending = {'text':text, 'notes':brain.wants_notes(text),
                       'after_press':press_count,
                       'created_at':datetime.now(timezone.utc).timestamp()}
            store.set_setting('pending_camera', pending)
            reply = 'Press my camera button once. I will take a picture and tell you what I see.'
            kind = 'camera_permission'
        else:
            sources = brain.relevant_sources(text)
            try:
                reply = brain.ask_ai(text, store.setting('mode','companion'), sources=sources)
            except Exception as e:
                raise HTTPException(502, f'AI service error: {e}')
            kind = 'conversation'
    store.add_message('assistant', reply)
    return {'reply':reply, 'spoken_reply':brain.spoken_summary(reply, max_chars=190),
            'kind':kind, 'mode':store.setting('mode','companion'),
            'demo_mode':DEMO_MODE, 'sources': retrieval.public_sources(sources) if kind == 'conversation' else []}

@app.post('/api/mode')
def mode(payload: ModeInput):
    if payload.mode not in brain.MODES:
        raise HTTPException(400, 'Choose companion, class, or work')
    store.set_setting('mode',payload.mode)
    return {'mode': payload.mode}

@app.get('/api/memories')
def get_memories():
    return store.memories()

@app.post('/api/memories')
def add_memory(payload: MemoryInput):
    id = store.add_memory(payload.content)
    return {'id':id}

@app.delete('/api/memories/{record_id}')
def delete_memory(record_id: int):
    store.execute('DELETE FROM memories WHERE id=?',(record_id,))
    return {'deleted': True}

@app.get('/api/notes')
def notes():
    return store.notes()

@app.post('/api/notes')
def add_note(payload: NoteInput):
    id = store.add_note(payload.title,payload.content)
    return {'id':id}

@app.delete('/api/notes/{record_id}')
def delete_note(record_id: int):
    store.execute('DELETE FROM notes WHERE id=?',(record_id,))
    return {'deleted':True}

@app.get('/api/reminders')
def reminders():
    return store.reminders()

@app.post('/api/reminders')
def add_reminder(payload: ReminderInput):
    if payload.due_at:
        try:
            datetime.fromisoformat(payload.due_at)
        except ValueError:
            raise HTTPException(400,'Invalid ISO date/time')
    id = store.add_reminder(payload.title,payload.due_at)
    return {'id':id}

@app.post('/api/reminders/{record_id}/toggle')
def toggle_reminder(record_id: int):
    store.execute('UPDATE reminders SET done=CASE WHEN done=1 THEN 0 ELSE 1 END WHERE id=?',(record_id,))
    return {'updated':True}

@app.delete('/api/reminders/{record_id}')
def delete_reminder(record_id: int):
    store.execute('DELETE FROM reminders WHERE id=?',(record_id,))
    return {'deleted':True}

@app.post('/api/camera/request')
def camera_request(payload: CameraRequest):
    d = device_state()
    store.set_setting('pending_camera',{
        'text':payload.text, 'notes':brain.wants_notes(payload.text),
        'after_press':d.get('button_press_count',0),
        'created_at':datetime.now(timezone.utc).timestamp()
    })
    return {'pending':True,'instruction':'Press the physical glasses button once. The red LED lights while the image is being captured.'}

@app.post('/api/camera/cancel')
def camera_cancel():
    store.set_setting('pending_camera',None)
    return {'pending':False}

@app.post('/api/camera/complete')
def camera_complete():
    if not CAMERA_CAPTURE_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'A camera capture is already in progress.')
    try:
        return _complete_camera_once()
    finally:
        CAMERA_CAPTURE_LOCK.release()

def camera_complete_from_button(press_id: int):
    """Internal bridge-only capture: validated physical camera-button event.

    Never exposed as an HTTP route; the native Mac bridge supplies a press ID
    observed directly from the ESP32 while recording the visual request.
    """
    if not CAMERA_CAPTURE_LOCK.acquire(blocking=False):
        raise HTTPException(409, 'A camera capture is already in progress.')
    try:
        return _complete_camera_once(authorized_press_id=press_id)
    finally:
        CAMERA_CAPTURE_LOCK.release()

def _complete_camera_once(authorized_press_id: Optional[int] = None):
    pending = store.setting('pending_camera')
    if not pending:
        raise HTTPException(409,'No camera request is waiting. Ask TIKI to look first.')
    if datetime.now(timezone.utc).timestamp() - pending['created_at'] > 120:
        store.set_setting('pending_camera',None)
        raise HTTPException(410,'Request expired. Ask TIKI to look again.')
    state = device_state()
    if not state.get('connected'):
        raise HTTPException(503,'ESP32 is offline. Check TIKI_ESP_URL and Wi-Fi.')
    count = int(state.get('button_press_count', 0))
    # Modern permission firmware gates /capture itself. With the user's older
    # working firmware we accept only a press genuinely observed by MacBridge.
    hardware_grant = bool(state.get('camera_armed') and (
        count > pending['after_press'] or
        (isinstance(authorized_press_id, int) and authorized_press_id > 0
         and count == authorized_press_id == pending['after_press'])
    ))
    legacy_bridge_grant = (
        not ('camera_armed' in state and 'button_release_count' in state)
        and isinstance(authorized_press_id, int)
        and authorized_press_id > 0
        and count == authorized_press_id
        and count >= pending['after_press']
    )
    if not (hardware_grant or legacy_bridge_grant):
        raise HTTPException(409, 'Camera awaits the physical button on the glasses. Press the camera button once after speaking, or press it alone to describe a scene.')
    if state.get('camera_ready') is False:
        raise HTTPException(503, 'The ESP32 camera is not ready.')
    # Clear pending BEFORE capture: no repeated captures on refresh / retry.
    store.set_setting('pending_camera',None)
    try:
        jpeg = device.capture()
    except device.DeviceError as e:
        raise HTTPException(502,str(e))
    filename = f'{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:8]}.jpg'
    (PHOTO_DIR / filename).write_bytes(jpeg)
    try:
        answer = brain.vision_analysis(jpeg,pending['text'],store.setting('mode','companion'),pending['notes'])
    except Exception as e:
        # The image is still saved if the AI call fails.
        answer = 'Photo saved, but AI analysis failed: ' + str(e)
    capture_id = store.add_capture(filename,pending['text'],answer)
    note_id = None
    if pending['notes']:
        title = 'Visual memory · ' + datetime.now().strftime('%b %d, %I:%M %p')
        note_id = store.add_note(title, answer, filename)
    proposal = None
    if vision_memory.should_extract_tasks(pending['text']):
        try:
            suggested = vision_memory.extract_tasks_from_photo(jpeg,pending['text'])
            proposal = vision_memory.propose_tasks(capture_id,suggested)
            if proposal:
                answer += vision_memory.task_prompt(proposal)
        except Exception:
            # Gemini may be unavailable for task extraction even when it
            # completed the first answer. The photo itself remains saved.
            pass
    store.add_message('assistant', answer)
    return {'reply':answer, 'spoken_reply':brain.spoken_summary(answer),
            'filename':filename, 'photo_url':'/api/photos/'+filename,
            'capture_id':capture_id, 'note_id':note_id,
            'proposed_tasks':proposal, 'demo_mode':DEMO_MODE}

@app.post('/api/phone/photo')
async def phone_photo(file: UploadFile = File(...), text: str = Form(...)):
    """One explicit user-selected phone image, not a live camera feed.

    This route does NOT allow the hardware camera to bypass its permission gate.
    """
    text = text.strip()
    if not 2 <= len(text) <= 1000:
        raise HTTPException(400, 'Say what you want TIKI to look at.')
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, 'Photo exceeds the 8 MB limit.')
    # Phone cameras can supply JPEG, PNG, or WEBP. Convert to a bounded JPEG
    # with orientation fixed and EXIF/GPS metadata removed before persistence.
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with Image.open(BytesIO(raw)) as img:
            if img.width * img.height > 24_000_000:
                raise HTTPException(413, 'Photo dimensions are too large. Choose a smaller image.')
            if img.format not in ('JPEG', 'PNG', 'WEBP'):
                raise HTTPException(415, 'Use a JPEG, PNG, or WEBP picture. HEIC needs conversion to JPEG first.')
            img = ImageOps.exif_transpose(img).convert('RGB')
            img.thumbnail((1600, 1600))
            out = BytesIO()
            img.save(out, format='JPEG', quality=85, optimize=True)
            raw = out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise HTTPException(415, 'Unsupported or damaged photo. Try a JPEG or PNG.')
    filename = f'{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:8]}.jpg'
    (PHOTO_DIR / filename).write_bytes(raw)
    wants_notes = brain.wants_notes(text)
    try:
        answer = brain.vision_analysis(raw, text, store.setting('mode','companion'), wants_notes)
    except Exception as exc:
        answer = 'I saved your photo, but image analysis could not finish: ' + str(exc)
    capture_id = store.add_capture(filename, text, answer)
    note_id = None
    if wants_notes:
        note_id = store.add_note('Visual memory · ' + datetime.now().strftime('%b %d, %I:%M %p'), answer, filename)
    proposal = None
    if vision_memory.should_extract_tasks(text):
        try:
            proposal = vision_memory.propose_tasks(capture_id,
                     vision_memory.extract_tasks_from_photo(raw,text))
            if proposal:
                answer += vision_memory.task_prompt(proposal)
        except Exception:
            pass
    store.add_message('user', text)
    store.add_message('assistant', answer)
    return {'reply':answer, 'spoken_reply':brain.spoken_summary(answer),
            'filename':filename, 'photo_url':'/api/photos/'+filename,
            'capture_id':capture_id, 'note_id':note_id,
            'proposed_tasks':proposal, 'demo_mode':DEMO_MODE}

@app.get('/api/captures')
def captures():
    return [{**row,'photo_url':'/api/photos/'+row['filename']} for row in store.captures()]


@app.delete('/api/captures/{capture_id}')
def delete_capture(capture_id: int):
    filename = store.remove_capture(capture_id)
    if filename is None:
        raise HTTPException(404,'Photo not found')
    if re.fullmatch(r'[A-Za-z0-9_]+\.jpg', filename):
        path = PHOTO_DIR / filename
        if path.is_file():
            path.unlink()
    return {'deleted':True, 'id':capture_id}


@app.get('/api/proposed-tasks')
def proposed_tasks():
    return vision_memory.pending_tasks() or {'tasks':[], 'capture_id':None}


@app.post('/api/proposed-tasks/decide')
def decide_proposed_tasks(payload: DecisionInput):
    return vision_memory.decide_tasks(payload.approve)


@app.get('/api/backup')
def backup(request: Request):
    # Keep the bulk private-data download on the user's own Mac by default.
    # People connected to the same Wi-Fi must not be able to fetch all memory.
    origin = request.client.host if request.client else ''
    if origin not in ('127.0.0.1','::1','testclient') and os.getenv('TIKI_ALLOW_REMOTE_BACKUP','0') != '1':
        raise HTTPException(403,'Download private memory backups from localhost on your Mac.')
    # ZIP includes a SQLite-consistent snapshot and original JPEGs. It NEVER
    # contains the Gemini key, which lives in .env outside the data folder.
    from .config import DB_PATH
    tmp = tempfile.NamedTemporaryFile(prefix='tiki_backup_',suffix='.sqlite3',delete=False)
    tmp.close()
    try:
        with sqlite3.connect(DB_PATH) as src, sqlite3.connect(tmp.name) as dst:
            src.backup(dst)
        mem = BytesIO()
        with zipfile.ZipFile(mem,'w',compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp.name,'data/tiki.sqlite3')
            for path in PHOTO_DIR.glob('*.jpg'):
                if path.is_file():
                    zf.write(path,'data/photos/'+path.name)
            zf.writestr('RESTORE.txt','Close TIKI, then copy the data/ folder into your TIKI project to restore your photos and memories.\n')
        mem.seek(0)
    finally:
        os.unlink(tmp.name)
    return StreamingResponse(mem,media_type='application/zip',headers={
        'Content-Disposition':'attachment; filename="TIKI_memory_backup.zip"'})


@app.get('/api/photos/{filename}')
def photo(filename: str):
    # Restrict to filenames created by our app; no path traversal.
    if not re.fullmatch(r'[A-Za-z0-9_]+\.jpg', filename):
        raise HTTPException(404,'Photo not found')
    path = PHOTO_DIR / filename
    if not path.is_file():
        raise HTTPException(404,'Photo not found')
    return FileResponse(path, media_type='image/jpeg')

def _fast_voice_core(data: bytes, content_type: str):
    """One cloud call handles both speech recognition and the ordinary reply.

    The actual camera and memory-changing commands remain server-side, so
    model-generated JSON cannot authorize a photo or invent a saved task.
    """
    from .bridge import plausible_transcript
    recent = []
    for m in store.memories()[:3]:
        recent.append('Saved memory: '+str(m['content'])[:250])
    for t in store.reminders()[:5]:
        if not t.get('done'):
            recent.append('Saved task: '+str(t['title'])[:180]+' due '+str(t.get('due_at') or 'unspecified'))
    for c in store.captures()[:2]:
        recent.append('Previously saved photo: '+str(c['analysis'])[:450])
    for n in store.notes()[:2]:
        recent.append('Saved note: '+str(n['title'])[:80]+' '+str(n['content'])[:250])
    text, suggested = audio.understand_and_answer('tiki-voice',data,content_type,'\n'.join(recent))
    if not text:
        raise HTTPException(422,'No clear speech detected. Please try again.')
    # Uncompressed 16kHz mono WAV includes a 44-byte header. Speech-rate
    # plausibility check is meaningful for raw WAV, not compressed browser audio.
    if content_type.startswith('audio/wav') and len(data)>44:
        seconds=(len(data)-44)/(16000*2)
        if not plausible_transcript(text,seconds):
            raise HTTPException(422,'Transcript uncertain. Please try speaking again.')
    if brain.wants_camera(text):
        local=chat(Chat(text=text))
        return {'text':text,**local}
    command=brain.handle_command(text)
    if command is not None:
        store.add_message('user',text)
        store.add_message('assistant',command)
        return {'text':text,'reply':command,'spoken_reply':brain.spoken_summary(command,max_chars=125),'kind':'command'}
    store.add_message('user',text)
    reply=suggested or 'I heard you, but could not form a reply. Please try again.'
    store.add_message('assistant',reply)
    return {'text':text,'reply':reply,'spoken_reply':brain.spoken_summary(reply,max_chars=125),'kind':'conversation'}


@app.post('/api/voice/fast')
async def fast_voice(file: UploadFile = File(...)):
    """Browser mic: audio -> single Gemini call -> transcript + reply."""
    data=await file.read(15*1024*1024+1)
    if len(data)>15*1024*1024:
        raise HTTPException(413,'Voice recording is too large.')
    try:
        return _fast_voice_core(data,file.content_type or 'audio/webm')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502,'Fast voice processing failed: '+str(exc)) from exc


@app.post('/api/transcribe')
async def transcribe(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 15*1024*1024:
        raise HTTPException(413,'Recording too large')
    try:
        text = audio.transcribe(file.filename or 'voice.webm',raw,file.content_type or 'application/octet-stream')
    except Exception as e:
        raise HTTPException(502,str(e))
    return {'text':text}

@app.post('/api/device/chime')
def device_chime():
    try:
        result = device.beep()
    except device.DeviceError as e:
        raise HTTPException(503, str(e))
    return {'result': result}

@app.post('/api/speak')
def speak(payload: SpeakInput):
    # Mac system text-to-speech can drive the physical ESP32 speaker even when
    # Gemini is off; don't force browser TTS merely because no AI key exists.
    # Do not block up to 1.3 seconds on a redundant device /button check.
    # /pcm itself gives the authoritative result if the speaker is offline.
    try:
        with SPEAKER_LOCK:
            pcm = audio.synthesize_pcm(payload.text)
            device.send_pcm(pcm)
        return {'target':'tiki','bytes':len(pcm)}
    except Exception as e:
        return {'target':'error','reason':str(e)}

app.mount('/assets',StaticFiles(directory=str(ROOT/'frontend')),name='assets')
@app.get('/')
def index():
    return FileResponse(ROOT/'frontend'/'index.html')
