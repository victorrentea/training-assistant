from quiz_core import _SYSTEM_PROMPT


def test_system_prompt_warns_about_noisy_transcripts():
    lower = _SYSTEM_PROMPT.lower()
    assert "gibberish" in lower
    assert "repeated" in lower
    assert "nonsense" in lower
    assert "low-signal" in lower


def test_system_prompt_enforces_transcript_first_focus():
    lower = _SYSTEM_PROMPT.lower()
    assert "first identify the main topics from the transcript" in lower
    assert "build the question around those transcript topics" in lower
    assert "do not let reference materials override the main transcript focus" in lower

