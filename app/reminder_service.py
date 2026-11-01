"""Small background reminder worker. Due tasks trigger TIKI's hardware speaker.

The server must remain running; no paid scheduling service is involved.
"""
from __future__ import annotations
import os
import threading
from datetime import datetime, timezone, timedelta

from . import store


def eligible_due(now=None):
    now = now or datetime.now(timezone.utc)
    out=[]
    for task in store.reminders():
        if task['done'] or not task.get('due_at') or task.get('notified_at'):
            continue
        try:
            due=datetime.fromisoformat(task['due_at'].replace('Z','+00:00'))
            if due.tzinfo is None:
                due=due.astimezone()
            if due <= now and now - due <= timedelta(hours=24):
                out.append(task)
        except (TypeError, ValueError, OverflowError):
            continue
    return out[:5]


def announce_one(item, speaker):
    """Return True only after the device confirms it received the audio."""
    short_title=item['title'][:175]
    reply=speaker('Reminder: ' + short_title)
    if reply.get('target') == 'tiki':
        store.execute('UPDATE reminders SET notified_at=? WHERE id=? AND notified_at IS NULL',
                      (store.now(),item['id']))
        return True
    return False


class ReminderWorker:
    def __init__(self):
        self.stop=threading.Event()
        self.thread=None
    def start(self):
        if os.getenv('TIKI_REMINDERS_SPEAKER','1') != '1':
            return
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread=threading.Thread(target=self._run,daemon=True,name='tiki-reminders')
        self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
    def _run(self):
        while not self.stop.wait(12):
            try:
                from .bridge import bridge
                from .main import SpeakInput, speak
                if bridge.busy or bridge.record is not None:
                    continue
                for due in eligible_due():
                    if self.stop.is_set() or bridge.busy or bridge.record is not None:
                        break
                    if not announce_one(due,lambda text: speak(SpeakInput(text=text))):
                        break
            except Exception:
                # A temporary Wi-Fi failure should not kill the reminder loop.
                pass

worker = ReminderWorker()
