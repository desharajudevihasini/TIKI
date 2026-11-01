"""TIKI's Mac-side mic-to-device bridge.

The glasses have NO microphone. The ESP button is CAMERA ONLY.
Speech comes from the browser's Talk button or optional Mac wake-phrase listener;
all audio replies go to the physical ESP32 speaker.

An optional small Vosk model allows local wake-phrase detection, without
sending continuous background audio to the cloud. Only deliberately activated
speech is uploaded for transcription.
"""
import io
import json
import os
import queue
import re
import sys
import threading
import time
import wave
from array import array
from collections import deque
from pathlib import Path
from typing import Optional

from .config import ROOT

SAMPLE_RATE = 16000
WAKE_MODEL_DIR = ROOT / 'models' / 'vosk-model-small-en-us-0.15'
WAKE_RE = re.compile(r'\b(?:hey\s+)?(?:tiki|kitty)\s+spots\s+on\b|\bhey\s+(?:tiki|kitty)\b', re.I)


def wav_from_pcm(raw: bytes) -> bytes:
    with io.BytesIO() as out:
        with wave.open(out, 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(raw)
        return out.getvalue()


def rms(raw: bytes) -> float:
    if not raw:
        return 0.0
    # 16-bit little endian PCM on the Mac; no additional dependency needed.
    samples = array('h')
    samples.frombytes(raw[:len(raw) & ~1])
    if sys.byteorder != 'little':
        samples.byteswap()
    if not samples:
        return 0.0
    return (sum(int(x)*int(x) for x in samples)/len(samples))**0.5 / 32768


def speech_quality(raw: bytes) -> tuple[bool, str]:
    """Conservative acoustic check to reduce cloud STT hallucinated silence.

    No VAD can prove what words were said; this only rejects very weak input
    and short clicks. Humans can still correct the transcript in the app.
    """
    seconds = len(raw) / (2 * SAMPLE_RATE)
    if seconds < 0.7:
        return False, 'Speak for at least one second.'
    if rms(raw) < .0025:
        return False, 'I heard mostly silence. Try speaking closer to the Mac microphone.'
    frame_bytes = int(.05 * SAMPLE_RATE) * 2
    levels = [rms(raw[i:i + frame_bytes]) for i in range(0,len(raw),frame_bytes)
              if len(raw[i:i + frame_bytes]) == frame_bytes]
    if not levels:
        return False, 'Nothing recorded.'
    floor = sorted(levels)[max(0, int(len(levels)*.15)-1)]
    threshold = max(.0055, floor * 2.2)
    active = sum(v > threshold for v in levels)
    if active < max(4,int(len(levels)*.065)) and rms(raw) < .0075:
        return False, 'I heard noise but not enough clear speech. Please try again.'
    return True, ''


def plausible_transcript(text: str, audio_seconds: float) -> bool:
    """Reject classic generated boilerplate and impossible speech rates."""
    cleaned = text.casefold().strip(' .?!\n')
    if not cleaned or cleaned in ('no speech','inaudible','silence','unintelligible'):
        return False
    if any(s in cleaned for s in ('as an ai language model',
                                 'transcription of the audio',
                                 'no audible speech detected',
                                 'thank you for watching')):
        return False
    # At 5.5 words/sec plus tolerance, hallucinated paragraphs after a
    # one-second hold should be rejected. This is intentionally lenient.
    if len(text.split()) > audio_seconds * 5.5 + 5:
        return False
    return True


class MacBridge:
    def __init__(self):
        self.lock = threading.RLock()
        self.events = deque(maxlen=12)
        self.state = 'starting'
        self.detail = 'Preparing microphone'
        self.heard = ''
        self.answer = ''
        self.photo_url = ''
        self.last_error = ''
        self.connected = False
        self.wake_available = False
        self.wake_enabled = bool(int(os.getenv('TIKI_WAKE_ENABLED','1')))
        self.awake = False
        self.busy = False
        self.audio_q = queue.Queue(maxsize=180)
        self.thread = None
        self.camera_thread = None
        self.camera_last_seen_press = None
        self.deferred_press = None
        self.stop = threading.Event()
        self.last_press = None
        self.last_release = None
        self.last_pressed = None
        self.firmware_button_mode = 'unknown'
        self.record = None
        self.session_press_id = None
        self.active_source = None
        self.audio_started = 0.0
        self.last_voice = 0.0
        self.last_activity = time.monotonic()
        self.wake_recognizer = None
        self.wake_guard_until = 0.0
        self.started = False
        self.input_rate = SAMPLE_RATE

    def snapshot(self):
        with self.lock:
            return {'bridge_running':self.started, 'state':self.state,
                    'detail':self.detail, 'heard':self.heard,
                    'answer':self.answer, 'photo_url':self.photo_url, 'error':self.last_error,
                    'glasses_connected':self.connected,
                    'firmware_button_mode':self.firmware_button_mode,
                    'esp_url':os.getenv('TIKI_ESP_URL','http://192.168.0.115'),
                    'wake_model_installed':self.wake_available,
                    'wake_enabled':self.wake_enabled,
                    'awake':self.awake, 'busy':self.busy,
                    'events':list(self.events)}

    def publish(self, state, detail='', **kwargs):
        with self.lock:
            self.state = state
            self.detail = detail
            self.events.append({'state':state,'detail':detail,'time':round(time.time(),1)})
            for k,v in kwargs.items():
                setattr(self,k,v)

    def start(self):
        if self.started:
            return
        self.started = True
        # The camera button is deliberately independent of the microphone.
        # A denied Mac mic permission, missing Vosk model, or sounddevice error
        # must NEVER disable the glasses camera.
        self.camera_thread = threading.Thread(target=self._run_camera, daemon=True, name='tiki-camera-button')
        self.camera_thread.start()
        self.thread = threading.Thread(target=self._run, daemon=True, name='tiki-mic-wake')
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.camera_thread:
            self.camera_thread.join(timeout=3)
        if self.thread:
            self.thread.join(timeout=3)

    def toggle_wake(self, enabled: bool):
        with self.lock:
            self.wake_enabled = enabled
            if not enabled:
                self.awake = False
        return self.snapshot()

    def _on_audio(self, indata, frames, time_info, status):
        if status:
            # PortAudio overflow is nonfatal; the queue stays bounded.
            pass
        chunk = bytes(indata)
        if self.input_rate != SAMPLE_RATE:
            # Resample the built-in Mac microphone when 16kHz input is not
            # supported by CoreAudio. Data uploaded stays at true 16 kHz.
            import numpy as np
            inp = np.frombuffer(chunk, dtype='<i2')
            if len(inp):
                target = max(1, round(len(inp)*SAMPLE_RATE/self.input_rate))
                idx = np.linspace(0, len(inp)-1, num=target)
                chunk = np.interp(idx, np.arange(len(inp)), inp).astype('<i2').tobytes()
        try:
            self.audio_q.put_nowait(chunk)
        except queue.Full:
            try:
                self.audio_q.get_nowait()
                self.audio_q.put_nowait(chunk)
            except queue.Empty:
                pass

    def _init_wake(self):
        if not WAKE_MODEL_DIR.is_dir():
            self.wake_available = False
            return
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model = Model(str(WAKE_MODEL_DIR))
            self.wake_recognizer = KaldiRecognizer(model, SAMPLE_RATE)
            self.wake_available = True
        except Exception as exc:
            self.wake_available = False
            self.last_error = 'Wake model: ' + str(exc)

    def _start_record(self, source, press_id=None, seed=b''):
        with self.lock:
            if self.busy:
                return
            # Discard pre-press audio: a button press is the start of consent.
            if source == 'button':
                while True:
                    try:
                        self.audio_q.get_nowait()
                    except queue.Empty:
                        break
            self.record = [seed] if seed else []
            self.session_press_id = press_id
            self.active_source = source
            self.audio_started = time.monotonic()
            self.last_voice = self.audio_started
            self.publish('listening','Wake-listener capturing your question', heard='', answer='', last_error='')

    def _finish_record(self):
        with self.lock:
            if self.record is None:
                return
            frames = b''.join(self.record)
            press_id = self.session_press_id
            self.record = None
            self.active_source = None
            self.session_press_id = None
            if self.busy:
                return
            # A hold consisting of silence or switch clicks must never go
            # to Gemini transcription (which can hallucinate words).
            quality, reason = speech_quality(frames)
            if not quality:
                self.publish('ready',reason)
                return
            self.busy = True
        worker = threading.Thread(target=self._process, args=(frames,press_id), daemon=True)
        worker.start()

    def _process(self, raw, press_id):
        """Hands-free wake session only. Camera-only button never invokes this."""
        from .main import _fast_voice_core, SpeakInput, speak
        try:
            started_at = time.monotonic()
            self.publish('thinking','Understanding and answering in one request…')
            result = _fast_voice_core(wav_from_pcm(raw),'audio/wav')
            text = result['text']
            if re.search(r'\bspots\s+off\b', text, re.I):
                self.awake = False
            self.publish('thinking',f'Heard and answered in {time.monotonic()-started_at:.1f}s',heard=text)
            answer = result['reply']
            if result.get('kind') == 'camera_permission':
                self.publish('ready','Press the physical camera button once to capture.',answer=answer)
                # Keep this extremely brief. The actual image reply speaks
                # through the wearable after the authorized photo arrives.
                spoken = 'Press my camera button to take the picture.'
            else:
                spoken = result.get('spoken_reply') or answer
            from .brain import spoken_summary
            spoken = spoken_summary(spoken,max_chars=120)
            self.publish('speaking','Sending reply to TIKI speaker…', answer=answer)
            out = speak(SpeakInput(text=spoken))
            if out.get('target') != 'tiki':
                self.publish('speaker-error','Could not reach the physical speaker: '+out.get('reason','unknown'),answer=answer)
                return
            self.publish('ready','Ready for another question', answer=answer)
        except Exception as exc:
            self.publish('error','Could not finish the voice request',last_error=str(exc))
        finally:
            with self.lock:
                self.busy = False
                self.wake_guard_until = time.monotonic() + 1.2
                self.last_activity = time.monotonic()

    def _capture_pending_photo(self, press_id):
        """Camera consent press after an app/wake request; no voice recording."""
        from .main import camera_complete_from_button, SpeakInput, speak
        try:
            self.publish('looking', 'Glasses button authorized one photo…')
            result = camera_complete_from_button(press_id)
            self.photo_url = result['photo_url']
            self.publish('speaking', 'TIKI is describing your photo…', answer=result['reply'])
            output = speak(SpeakInput(text=result.get('spoken_reply', result['reply'])[:800]))
            if output.get('target') != 'tiki':
                self.publish('speaker-error', 'Photo analyzed, but speaker failed: '+output.get('reason','unknown'))
            else:
                self.publish('ready', 'Photo captured and described', answer=result['reply'])
        except Exception as exc:
            self.publish('error','Camera request failed',last_error=str(exc))
        finally:
            with self.lock:
                self.busy = False
                self.wake_guard_until = time.monotonic() + 1.3

    def _listen_wake(self, pcm):
        if not self.wake_recognizer:
            return
        try:
            if self.wake_recognizer.AcceptWaveform(pcm):
                text = json.loads(self.wake_recognizer.Result()).get('text','')
                if WAKE_RE.search(text):
                    self.awake = True
                    from .store import set_setting
                    set_setting('active', True)
                    self.last_activity = time.monotonic()
                    self.publish('awake','Spots on. Speak naturally, or use the app Talk button.')
                    threading.Thread(target=self._greet,daemon=True,name='tiki-greeting').start()
                    # Next utterance after wake can be captured on silence.
        except Exception:
            pass

    def _greet(self):
        from .main import SpeakInput, speak
        with self.lock:
            if self.busy:
                return
            self.busy = True
        try:
            self.publish('speaking','Spots on. I’m here.',answer='Spots on. I’m here.')
            output = speak(SpeakInput(text='Spots on. I’m here.'))
            if output['target'] != 'tiki':
                self.publish('speaker-error','Connect TIKI’s speaker: '+output.get('reason','unknown'))
            else:
                self.publish('awake','Ready. What’s on your mind?')
        except Exception as exc:
            self.publish('error','Could not play wake reply',last_error=str(exc))
        finally:
            with self.lock:
                self.busy = False
                self.wake_guard_until = time.monotonic() + 1.2

    def _poll_device(self):
        """The physical button is **camera only** on BOTH firmware versions.

        Track the monotonically increasing press counter, not the instantaneous
        button_pressed flag: quick taps may finish between HTTP polls.
        Each new press authorizes at most ONE image capture and never starts
        microphone recording. A previously spoken visual request supplies the
        photo question; a button press without one simply describes the image.
        """
        from .device import status
        from . import store
        d = status()
        connected = bool(d.get('connected'))
        with self.lock:
            self.connected = connected
        if not connected:
            if self.state in ('ready','starting','disconnected'):
                self.publish('disconnected','Cannot reach glasses. Check Wi-Fi and TIKI_ESP_URL.')
            return
        if self.state == 'disconnected':
            self.publish('ready','Glasses connected. Camera button ready.')
        if 'button_press_count' not in d:
            self.firmware_button_mode = 'unsupported'
            self.publish('firmware-error','ESP32 firmware needs button_press_count on /button.')
            return
        self.firmware_button_mode = 'permission' if 'button_release_count' in d and 'camera_armed' in d else 'legacy'
        press = int(d.get('button_press_count',0))
        if self.last_press is None or press < self.last_press:
            # At startup (or board reboot) establish a baseline. Never take
            # a picture just because the counter already contains old presses.
            self.last_press = press
            return
        changed = press > self.last_press
        self.last_press = press
        # Preserve the press if TIKI was talking when the button was tapped.
        # This avoids losing an actual user action while Gemini or I2S is busy.
        if changed:
            self.deferred_press = press
        if self.deferred_press is None or self.busy:
            return
        press = self.deferred_press
        self.deferred_press = None
        pending = store.setting('pending_camera')
        valid = bool(pending and time.time()-pending.get('created_at',0)<120
                     and press > int(pending.get('after_press',press)))
        if not valid:
            # The tap itself is explicit physical permission for ONE photo.
            store.set_setting('pending_camera',{
                'text':'Describe exactly what is visible in this photograph in one or two sentences.',
                'notes':False, 'after_press':max(0,press-1),
                'created_at':time.time()})
        with self.lock:
            self.busy = True
        threading.Thread(target=self._capture_pending_photo,
                         args=(press,),daemon=True,name='tiki-camera-only').start()

    def _run_camera(self):
        """Always-on camera-button monitor, regardless of Mac microphone status."""
        while not self.stop.is_set():
            # The ESP32 uses a single-threaded HTTP server. During PCM audio
            # playback, don't compete for its socket or cause speaker stalls.
            # The monotonic press count is read immediately once playback ends.
            if not self.busy:
                try:
                    self._poll_device()
                except Exception as exc:
                    self.publish('camera-error', 'Button watcher encountered an error', last_error=str(exc))
            self.stop.wait(.48)

    def _run(self):
        try:
            import sounddevice as sd
        except ImportError:
            self.publish('mic-error','Install sounddevice for hands-free wake. Camera button monitoring is unaffected.',last_error='sounddevice not installed')
            return
        self._init_wake()
        try:
            device = os.getenv('TIKI_INPUT_DEVICE')
            dev_arg = int(device) if device and device.isdecimal() else device or None
            try:
                sd.check_input_settings(device=dev_arg, channels=1, dtype='int16', samplerate=SAMPLE_RATE)
                self.input_rate = SAMPLE_RATE
            except Exception:
                # Many Mac microphones are natively 48kHz; CoreAudio may
                # reject a 16kHz stream even though 16kHz PCM is required
                # by the wake model and Gemini.
                self.input_rate = round(sd.query_devices(dev_arg, kind='input')['default_samplerate'])
            blocksize = max(256, round(self.input_rate / 10))
            with sd.RawInputStream(samplerate=self.input_rate, blocksize=blocksize,
                                   channels=1, dtype='int16', device=dev_arg,
                                   callback=self._on_audio):
                if self.state in ('starting', 'error'):
                    self.publish('ready','Camera button ready. Use Talk on screen or the wake phrase for speech.')
                while not self.stop.is_set():
                    now = time.monotonic()
                    try:
                        chunk = self.audio_q.get(timeout=.09)
                    except queue.Empty:
                        continue
                    with self.lock:
                        recording = self.record is not None
                        source = self.active_source
                        busy = self.busy
                        wake = self.wake_enabled and self.wake_available
                        awake = self.awake
                    if recording:
                        with self.lock:
                            if self.record is not None:
                                self.record.append(chunk)
                                if self.active_source == 'wake' and rms(chunk) > .018:
                                    self.last_voice = time.monotonic()
                        if source == 'wake' and now - self.audio_started > .8 and (
                            now - self.last_voice > 1.4 or now - self.audio_started > 12):
                            self._finish_record()
                        if now - self.audio_started > 24:
                            self._finish_record()
                    elif not busy and now >= self.wake_guard_until:
                        if wake and not awake:
                            self._listen_wake(chunk)
                        elif wake and awake:
                            if now - self.last_activity > 90:
                                self.awake = False
                                from .store import set_setting
                                set_setting('active', False)
                                self.publish('ready','Listening session ended')
                            elif rms(chunk) > .04:
                                self._start_record('wake', seed=chunk)
        except Exception as exc:
            self.publish('mic-error','Mac microphone could not start. The physical camera button is still monitored.',last_error=str(exc))

bridge = MacBridge()
