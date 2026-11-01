"""Ensure we never guess unsupported Gemini model names or spin on a 503."""
from types import SimpleNamespace
from app import model_router

class FakeModels:
    def __init__(self):
        self.calls=[]
    def list(self):
        return [
            SimpleNamespace(name='models/gemini-fake-pro',supported_actions=['generateContent']),
            SimpleNamespace(name='models/gemini-fake-flash-lite',supported_actions=['generateContent']),
            SimpleNamespace(name='models/gemini-fake-embed',supported_actions=['embedContent']),
        ]
    def generate_content(self,model,**kw):
        self.calls.append(model)
        if model.endswith('flash-lite'):
            raise RuntimeError('503 UNAVAILABLE high demand')
        return SimpleNamespace(text='Hi from fallback model')

def test_listed_generate_content_models_used_and_overload_fallback(monkeypatch):
    monkeypatch.setattr(model_router,'_cached',None)
    models=FakeModels()
    monkeypatch.setattr(model_router.time,'sleep',lambda _:None)
    result=model_router.generate(SimpleNamespace(models=models),'auto',contents='Hi')
    assert result.text=='Hi from fallback model'
    assert models.calls==['gemini-fake-flash-lite','gemini-fake-pro']

def test_named_unlisted_model_ignored(monkeypatch):
    monkeypatch.setattr(model_router,'_cached',None)
    models=FakeModels()
    monkeypatch.setattr(model_router.time,'sleep',lambda _:None)
    model_router.generate(SimpleNamespace(models=models),'gemini-guess-not-in-list',contents='Hi')
    assert 'gemini-guess-not-in-list' not in models.calls
