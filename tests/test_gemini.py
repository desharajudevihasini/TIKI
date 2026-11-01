"""No API call is made: fake Gemini client tests code paths."""
from types import SimpleNamespace
from app import brain, audio
from app import store


def test_gemini_prompt_and_image(monkeypatch):
    calls=[]
    fake = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw:(calls.append(kw) or SimpleNamespace(text='Gemini mock answer'))))
    # Make tests independent of whether optional google-genai is installed here.
    fake_types=SimpleNamespace(
        GenerateContentConfig=lambda **kw:SimpleNamespace(**kw),
        Part=SimpleNamespace(from_bytes=lambda data,mime_type:SimpleNamespace(inline_data=SimpleNamespace(data=data,mime_type=mime_type)))
    )
    monkeypatch.setattr(brain, 'types', fake_types)
    monkeypatch.setattr(audio, 'types', fake_types)
    monkeypatch.setattr(brain, 'DEMO_MODE', False)
    monkeypatch.setattr(brain, 'client', lambda:fake)
    monkeypatch.setattr(audio, 'client', lambda:fake)
    assert brain.ask_ai('Explain trees', 'class') == 'Gemini mock answer'
    assert 'LOCAL REFERENCE DATA' in str(calls[-1]['config'].system_instruction)
    assert brain.vision_analysis(b'fakejpeg', 'What is on this board?', 'class', True) == 'Gemini mock answer'
    assert len(calls[-1]['contents']) == 2
    monkeypatch.setattr(audio, 'DEMO_MODE', False)
    assert audio.transcribe('clip.webm', b'fakeaudio', 'audio/webm;codecs=opus') == 'Gemini mock answer'
    assert calls[-1]['contents'][1].inline_data.mime_type == 'audio/webm'
