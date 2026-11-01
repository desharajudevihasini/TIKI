"""Persist authorized visual observations and propose, but never silently commit, tasks.

This module deliberately stores the photo before AI analysis: outages do not
lose the user's image. Task suggestions are only committed after confirmation.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from . import store

MAX_TASKS = 5
PROPOSAL_TTL = 15 * 60


def should_extract_tasks(text: str) -> bool:
    t = text.casefold()
    return bool(re.search(r'\b(assignment|homework|deadline|task|to[ -]?do|remind|action items?|due|schedule|make a plan|study plan)\b', t))


def _json_dict(text: str) -> dict:
    """Accept raw Gemini JSON or fenced JSON, never evaluate returned text."""
    clean = (text or '').strip()
    if clean.startswith('```'):
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', clean, flags=re.I).strip()
    try:
        val = json.loads(clean)
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def sanitize_suggested_tasks(data: Any) -> list[dict]:
    """Reject malformed/unsubstantiated items; preserve unparsed dates as strings."""
    tasks = data.get('tasks', []) if isinstance(data, dict) else []
    if not isinstance(tasks, list):
        return []
    clean = []
    seen = set()
    for raw in tasks[:MAX_TASKS * 3]:
        if not isinstance(raw, dict):
            continue
        task = str(raw.get('task', '')).strip()
        evidence = str(raw.get('visible_evidence', '')).strip()
        due = str(raw.get('due_text', '') or '').strip()
        if not 4 <= len(task) <= 220 or not 3 <= len(evidence) <= 220:
            continue
        confidence = str(raw.get('confidence', 'uncertain')).casefold()
        if confidence not in ('high', 'medium'):
            continue
        if task.casefold() in seen:
            continue
        seen.add(task.casefold())
        clean.append({'task':task, 'visible_evidence':evidence,
                      'due_text':due[:80], 'confidence':confidence})
        if len(clean) >= MAX_TASKS:
            break
    return clean


def extract_tasks_from_photo(photo: bytes, spoken_request: str) -> list[dict]:
    """Second Gemini vision call only for explicit assignment/task questions.

    Results are untrusted suggestions requiring approval, NOT a calendar event.
    """
    from .brain import client, types
    from .config import DEMO_MODE, AI_MODEL
    from .model_router import generate
    if DEMO_MODE:
        return []
    instructions = (
        'Inspect this photograph and return ONLY a JSON object with a "tasks" array. '
        'Each entry has "task", "visible_evidence" (short exact visible text), '
        '"due_text" (copy EXACT visible due-date text, or empty), and '
        '"confidence" (high/medium/uncertain). '
        'Do not invent tasks or deadlines from ambiguous pictures. '
        'If you cannot actually read an assignment or task, return {"tasks":[]}. '
        'Dates must not be computed or assumed. Maximum five tasks. '
        'This is a DRAFT for the user to confirm; do not claim to create reminders.'
    )
    out = generate(
        client(), AI_MODEL,
        contents=[instructions + '\nUser request: ' + spoken_request,
                  types.Part.from_bytes(data=photo, mime_type='image/jpeg')],
        config=types.GenerateContentConfig(max_output_tokens=600, temperature=0),
    )
    return sanitize_suggested_tasks(_json_dict(getattr(out, 'text', '') or ''))


def propose_tasks(capture_id: int, tasks: list[dict]) -> dict | None:
    approved = sanitize_suggested_tasks({'tasks':tasks})
    if not approved:
        return None
    payload = {'capture_id':int(capture_id), 'tasks':approved,
               'created_at':time.time()}
    store.set_setting('proposed_tasks',payload)
    return payload


def pending_tasks() -> dict | None:
    proposal = store.setting('proposed_tasks')
    if not isinstance(proposal,dict):
        return None
    if time.time() - float(proposal.get('created_at',0)) > PROPOSAL_TTL:
        store.set_setting('proposed_tasks',None)
        return None
    return proposal


def decide_tasks(approve: bool) -> dict:
    """Atomic-ish confirmation serialized by the shared database RLock.

    The confirm operation is idempotent when issued twice in quick succession;
    failure to find a pending proposal produces zero inserts.
    """
    with store.LOCK:
        prop = pending_tasks()
        if prop is None:
            return {'status':'none', 'count':0, 'items':[]}
        store.set_setting('proposed_tasks',None)
        if not approve:
            return {'status':'dismissed', 'count':0, 'items':[]}
        ids = []
        for task in prop['tasks']:
            text = task['task']
            if task.get('due_text'):
                text += ' (written due date: ' + task['due_text'] + ')'
            # Uninterpretable due text is kept in the title. No fake timestamp.
            ids.append(store.add_reminder(text))
        return {'status':'saved','count':len(ids),'items':ids}


def task_prompt(proposal: dict | None) -> str:
    if not proposal:
        return ''
    tasks = proposal.get('tasks',[])
    if not tasks:
        return ''
    preview = '; '.join(t['task'] for t in tasks[:2])
    if len(tasks) > 2:
        preview += f' and {len(tasks)-2} more'
    return f' I found {len(tasks)} possible task(s): {preview}. Say "save those tasks" to confirm, or "discard those tasks".'
