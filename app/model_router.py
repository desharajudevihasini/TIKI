"""Use models reported as supporting generateContent by THIS API key.
No hardcoded, guessed version numbers. SDK's supported_actions may differ
across versions, so we also accept supported_generation_methods.
"""
import os
import re
import time

_cached = None


def discover_models(client, preferred='auto'):
    global _cached
    if _cached is not None:
        names = list(_cached)
    else:
        items = list(client.models.list())
        names = []
        for item in items:
            methods = getattr(item, 'supported_actions', None)
            if methods is None:
                methods = getattr(item, 'supported_generation_methods', None)
            methods = [str(x).lower().replace('_', '') for x in (methods or [])]
            name = str(getattr(item, 'name', '') or '').replace('models/', '')
            if name and 'generatecontent' in methods and name.startswith('gemini-') and not any(
                token in name for token in ('tts', 'embedding', 'image', 'live', 'robotics', 'computer-use')
            ):
                names.append(name)
        _cached = tuple(names)
    if not names:
        raise RuntimeError('No Gemini generateContent models are accessible with this API key. Check Google AI Studio project access.')
    def score(n):
        # Small, comparatively economical text+image models first.
        return (0 if 'flash-lite' in n else 1 if 'flash' in n else 2,
                1 if any(w in n for w in ('preview','experimental','exp')) else 0,
                n)
    names.sort(key=score)
    if preferred and preferred != 'auto':
        p = preferred.replace('models/', '')
        if p in names:
            names.remove(p)
            names.insert(0,p)
    return names


def generate(client, preferred, **kwargs):
    """Retry temporary 503 failures, then try another listed compatible model.

    This does NOT bypass any quota; 429 is returned without trying to evade limits.
    """
    # Test doubles may implement only generate_content, without list.
    try:
        names = discover_models(client,preferred)
    except (AttributeError,TypeError):
        names = [preferred if preferred != 'auto' else 'gemini-model-for-test']
    last = None
    # An overloaded model should not be retried and then followed by several
    # other slow retries on the critical voice path. Immediately try another
    # model listed for this key. Quota errors are still never bypassed.
    for model in names[:3]:
        try:
            return client.models.generate_content(model=model, **kwargs)
        except Exception as exc:
            last = exc
            msg = str(exc)
            status = getattr(exc,'code',None)
            if str(status) == '429' or re.search(r'\b429\b|RESOURCE_EXHAUSTED',msg):
                raise RuntimeError('Gemini free-tier request quota reached. Please wait or use local Ollama; no billing needed.') from exc
            overloaded = str(status) == '503' or '503' in msg or 'UNAVAILABLE' in msg
            missing = str(status) == '404' or '404' in msg or 'NOT_FOUND' in msg
            if missing or overloaded:
                continue
            raise
    raise RuntimeError(f'Gemini is temporarily unavailable across your accessible models. Last error: {last}')
