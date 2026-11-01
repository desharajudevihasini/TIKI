"""Fast route must not wait for the ESP32 to answer a normal text question."""
from app import main

def test_regular_chat_never_blocks_on_esp32(monkeypatch):
    def fail_on_status():
        raise AssertionError("Ordinary chat must not poll ESP32 /button")
    monkeypatch.setattr(main, 'device_state', fail_on_status)
    monkeypatch.setattr(main.brain,'handle_command', lambda _:None)
    monkeypatch.setattr(main.brain,'relevant_sources', lambda _:[])
    monkeypatch.setattr(main.brain,'ask_ai', lambda *a,**kw:'One short answer. More text for the page.')
    response = main.chat(main.Chat(text='Tell me something about trees'))
    assert response['reply']=='One short answer. More text for the page.'
    assert response['spoken_reply']
    assert response['kind']=='conversation'


def test_visual_chat_still_checks_esp32(monkeypatch):
    seen=[]
    monkeypatch.setattr(main,'device_state',lambda:(seen.append(1) or {'connected':False,'button_press_count':0}))
    result=main.chat(main.Chat(text='Please take a picture'))
    assert result['kind']=='camera_permission'
    assert seen
