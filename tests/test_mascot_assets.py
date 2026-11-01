from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_mascot_used_as_main_character():
    html=(ROOT/'frontend/index.html').read_text()
    assert 'class="mascot-img"' in html
    assert 'src="/assets/tiki-mascot.webp"' in html
    assert 'id="talkBtn"' in html
    assert 'id="lastPhoto"' in html
    assert 'id="worldBtn"' in html

def test_mascot_assets_present():
    assert (ROOT/'frontend/tiki-mascot.webp').stat().st_size > 1000
    assert (ROOT/'frontend/tiki-icon.png').stat().st_size > 1000

def test_faster_voice_path_retained():
    script=(ROOT/'frontend/app.js').read_text()
    assert 'SpeechRecognition' in script
    assert '/api/voice/fast' in script
    assert '/api/transcribe' in script
    assert '/api/speak' in script
