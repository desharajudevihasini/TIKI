"""Bridge tests validate press/release recording, wake phrases and audio WAV without a board."""
import io
import wave
import time
from unittest.mock import patch

from app.bridge import MacBridge, SAMPLE_RATE, WAKE_RE, wav_from_pcm, rms


def test_wav_from_pcm_is_16k_mono():
    data = b'\x00\x00\xff\x7f' * 1600
    result = wav_from_pcm(data)
    with wave.open(io.BytesIO(result),'rb') as f:
        assert f.getframerate() == SAMPLE_RATE
        assert f.getnchannels() == 1
        assert f.getsampwidth() == 2
        assert f.readframes(f.getnframes()) == data
    assert rms(data) > .6


def test_button_press_captures_camera_only(monkeypatch):
    import app.device as device
    from app import store
    b = MacBridge()
    states=iter([
        {'connected':True,'button_press_count':7,'button_pressed':False},
        {'connected':True,'button_press_count':8,'button_pressed':True},
        {'connected':True,'button_press_count':8,'button_pressed':False},
    ])
    monkeypatch.setattr(device,'status',lambda:next(states))
    captured=[]
    def camera_job(pid):
        captured.append(pid)
        b.busy=False
    monkeypatch.setattr(b,'_capture_pending_photo',camera_job)
    b._poll_device()
    b._poll_device()
    for _ in range(50):
        if captured:break
        time.sleep(.01)
    assert captured==[8]
    assert b.record is None
    assert b.active_source is None
    assert store.setting('pending_camera')['text'].startswith('Describe exactly')
    b._poll_device()
    assert captured==[8]  # release cannot create a second photograph


def test_wake_is_explicit():
    assert WAKE_RE.search('hey tiki spots on')
    assert WAKE_RE.search('hey kitty spots on')
    assert not WAKE_RE.search('the dog was spotted on the lawn')
    assert not WAKE_RE.search('can you describe a dog')


def test_bridge_shows_real_speaker_failure(monkeypatch):
    from app import audio, device, main
    b=MacBridge();b.busy=True
    monkeypatch.setattr(main,'_fast_voice_core',lambda *args:{'text':'What are my plans today?','kind':'conversation','reply':'You have one saved task.'})
    monkeypatch.setattr(main,'speak',lambda c:{'target':'error','reason':'Speaker offline'})
    monkeypatch.setattr(device,'status',lambda:{'connected':False})
    b._process(b'\x00\x00'*SAMPLE_RATE, 4)
    assert b.snapshot()['state']=='speaker-error'
    assert 'Speaker offline' in b.snapshot()['detail']


def test_fast_tap_between_polls_is_one_photo_not_mic(monkeypatch):
    """Legacy camera-only tapping is recognized even if no pressed=True is seen."""
    import app.device as device
    from app import store
    b=MacBridge()
    states=iter([
        {'connected':True,'button_press_count':3,'button_pressed':False},
        {'connected':True,'button_press_count':4,'button_pressed':False},
        {'connected':True,'button_press_count':4,'button_pressed':False},
    ])
    monkeypatch.setattr(device,'status',lambda:next(states))
    captured=[]
    monkeypatch.setattr(b,'_capture_pending_photo',lambda pid:captured.append(pid))
    b._poll_device()
    assert b.snapshot()['firmware_button_mode']=='legacy'
    b._poll_device()
    for _ in range(50):
        if captured:break
        time.sleep(.01)
    assert captured==[4]
    assert b.record is None
    assert store.setting('pending_camera')['after_press']==3


def test_button_uses_previous_spoken_camera_question(monkeypatch):
    import app.device as device
    from app import store
    b=MacBridge()
    states=iter([
        {'connected':True,'button_press_count':11,'button_pressed':False},
        {'connected':True,'button_press_count':12,'button_pressed':False},
    ])
    monkeypatch.setattr(device,'status',lambda:next(states))
    store.set_setting('pending_camera',{
        'text':'What breed of dog is this?', 'notes':False,
        'after_press':11,'created_at':time.time()})
    hits=[]
    monkeypatch.setattr(b,'_capture_pending_photo',lambda pid:hits.append(pid))
    b._poll_device();b._poll_device()
    for _ in range(50):
        if hits:break
        time.sleep(.01)
    assert hits==[12]
    assert store.setting('pending_camera')['text']=='What breed of dog is this?'
