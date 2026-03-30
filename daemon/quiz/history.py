"""
Auto-generate and auto-refine quiz flows used by the training daemon.
"""

from typing import Optional

from daemon import log
from daemon.config import Config, read_session_notes
from daemon.quiz.generator import generate_quiz, print_quiz, refine_quiz
from daemon.quiz import poll_api
from daemon.quiz.poll_api import fetch_quiz_history, fetch_summary_points, post_status
from daemon.transcript.loader import extract_last_n_minutes, load_transcription_files

try:
    from dataclasses import replace
except ImportError:
    from copy import copy as replace  # type: ignore


def auto_generate(minutes: int, config: Config) -> Optional[tuple]:
    """Load transcript -> generate quiz -> post preview. Returns (quiz, text) or None on failure."""
    post_status("generating", "Loading context...", config)

    notes = read_session_notes(config)

    # Prefer key points over raw transcript (saves tokens)
    summary_points = fetch_summary_points(config)
    key_points_text = ""
    if summary_points:
        key_points_text = "\n".join(f"- [{p.get('time','')}] {p['text']}" for p in summary_points)

    text = ""
    if not key_points_text:
        # Fall back to raw transcript when no key points available
        entries = load_transcription_files(config.folder)
        if not entries:
            if not notes:
                post_status("error", "No transcription files or session notes found.", config)
                return None
        else:
            text = extract_last_n_minutes(entries, minutes)

    if not text and not key_points_text and not notes:
        post_status("error", "No content available for quiz generation.", config)
        return None

    # Assemble combined prompt
    parts = []
    if notes:
        parts.append(
            "SESSION NOTES (trainer's written agenda/key points — treat as primary source):\n" + notes
        )
    if key_points_text:
        parts.append(
            "KEY POINTS DISCUSSED (AI-extracted from live session — use as primary context):\n" + key_points_text
        )
    elif text:
        parts.append(
            f"TRANSCRIPT EXCERPT (last {minutes} min of live audio — use for context and recent topics):\n" + text
        )
    quiz_history = fetch_quiz_history(config)
    if quiz_history:
        parts.append(
            "QUESTIONS ALREADY ASKED THIS SESSION (do NOT generate a similar question):\n" + quiz_history
        )
        if config.session_folder:
            try:
                (config.session_folder / "quiz.md").write_text(quiz_history, encoding="utf-8")
            except OSError as exc:
                log.error("quiz", f"Could not write quiz.md: {exc}")
    combined = "\n\n".join(parts)

    if key_points_text:
        status_detail = f"{len(summary_points)} key points"
    else:
        line_count = len([l for l in text.splitlines() if l.strip()])
        status_detail = f"{len(text):,} chars ({line_count} lines, last {minutes} min)"
    notes_info = f" + {len(notes):,} chars notes" if notes else ""
    post_status("generating", f"Sending {status_detail}{notes_info} to Claude...", config)

    try:
        quiz = generate_quiz(combined, config)
    except RuntimeError as e:
        post_status("error", str(e), config)
        return None

    print_quiz(quiz)

    try:
        if poll_api._ws_client and poll_api._ws_client.connected:
            poll_api._ws_client.send({"type": "quiz_preview", "quiz": {
                "question": quiz["question"],
                "options": quiz["options"],
                "multi": len(quiz.get("correct_indices", [])) > 1,
                "correct_indices": quiz.get("correct_indices", []),
                "source": quiz.get("source"),
                "page": quiz.get("page"),
            }})
        else:
            post_status("error", "Failed to post preview: WS not connected", config)
            return None
    except Exception as e:
        post_status("error", f"Failed to post preview: {e}", config)
        return None

    post_status("done", "Question ready — review and fire from host panel.", config)
    return quiz, combined


def auto_generate_topic(topic: str, config: Config) -> Optional[tuple]:
    """Generate a quiz from a topic using RAG. Returns (quiz, topic_context) or None."""
    post_status("generating", f"Generating question about '{topic}'...", config)
    notes = read_session_notes(config)
    notes_text = (
        "SESSION NOTES (trainer's written agenda/key points — treat as primary source):\n" + notes
        if notes else ""
    )
    quiz_history = fetch_quiz_history(config)
    quiz_history_text = (
        "\n\nQUESTIONS ALREADY ASKED THIS SESSION (do NOT generate a similar question):\n" + quiz_history
        if quiz_history else ""
    )
    from dataclasses import replace as dc_replace
    topic_config = dc_replace(config, topic=topic)
    try:
        quiz = generate_quiz(notes_text + quiz_history_text, topic_config)
    except RuntimeError as e:
        post_status("error", str(e), topic_config)
        return None
    print_quiz(quiz)
    topic_context = f"TOPIC: {topic}"
    try:
        if poll_api._ws_client and poll_api._ws_client.connected:
            poll_api._ws_client.send({"type": "quiz_preview", "quiz": {
                "question": quiz["question"],
                "options": quiz["options"],
                "multi": len(quiz.get("correct_indices", [])) > 1,
                "correct_indices": quiz.get("correct_indices", []),
                "source": quiz.get("source"),
                "page": quiz.get("page"),
            }})
        else:
            post_status("error", "Failed to post preview: WS not connected", config)
            return None
    except Exception as e:
        post_status("error", f"Failed to post preview: {e}", config)
        return None
    post_status("done", "Question ready — review and fire from host panel.", config)
    return quiz, topic_context


def auto_refine(target: str, current_quiz: dict, original_text: str, config: Config) -> Optional[dict]:
    """Refine a specific option or the whole question. Returns updated quiz or None on failure."""
    label = "question" if target == "question" else f"option {chr(65 + int(target[3:]))}"
    post_status("generating", f"Regenerating {label}...", config)
    try:
        updated = refine_quiz(current_quiz, target, original_text, config)
    except RuntimeError as e:
        post_status("error", f"Claude API error: {e}", config)
        return None

    print_quiz(updated)
    try:
        if poll_api._ws_client and poll_api._ws_client.connected:
            poll_api._ws_client.send({"type": "quiz_preview", "quiz": {
                "question": updated["question"],
                "options": updated["options"],
                "multi": len(updated.get("correct_indices", [])) > 1,
                "correct_indices": updated.get("correct_indices", []),
                "source": updated.get("source"),
                "page": updated.get("page"),
            }})
        else:
            post_status("error", "Failed to post updated preview: WS not connected", config)
            return None
    except Exception as e:
        post_status("error", f"Failed to post updated preview: {e}", config)
        return None

    post_status("done", "Updated — review and fire from host panel.", config)
    return updated
