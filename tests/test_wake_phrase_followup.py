from app import brain

def test_wake_phrase_with_question_is_not_swallowed():
    assert brain.handle_command('Hey TIKI, spots on. What is your purpose?') is None
    assert brain.handle_command('Hey TIKI, spots on') == 'Spots on. I’m ready. What’s on your mind?'
    assert brain.handle_command('Hey TIKI spots off') == 'Spots off. I’m here when you need me.'
