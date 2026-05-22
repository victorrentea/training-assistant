#!/usr/bin/env python3
"""One-shot migration: rename feature-sense `poll` keys to `quiz` in persisted session JSON.

The current Poll feature (the one with correct answers and scoring) is being renamed
to Quiz everywhere. This script rewrites persisted JSON files on disk so the daemon
can load them under the new schema.

Targets:
    - ``session-state.json`` / ``session_state.json`` — per-session snapshots
    - ``daemon_state.json`` — legacy daemon state (if present)
    - ``global-state.json`` — global daemon state (rarely contains poll keys but
      walked for completeness)

Transformations (top-level only, conservative):
    1. ``current_activity == "poll"`` -> ``"quiz"``
    2. top-level ``"poll"`` -> ``"quiz"`` (whole object moved verbatim).
       If both ``"poll"`` and ``"quiz"`` exist, the existing ``"quiz"`` wins
       (treat as already-migrated, warn).
    3. Legacy flat keys at top level:
       ``poll_active``, ``poll_correct_indices``, ``poll_opened_at``,
       ``poll_timer_seconds``, ``poll_timer_started_at``
       -> ``quiz_active``, ``quiz_correct_indices``, ``quiz_opened_at``,
          ``quiz_timer_seconds``, ``quiz_timer_started_at``

Idempotent. Safe on already-migrated files. Writes ``<file>.bak`` (unless
``--no-backup``) only when the .bak does not already exist.

Usage:
    python3 scripts/migrate_poll_to_quiz.py [--dry-run] [--no-backup] <root>...
    python3 scripts/migrate_poll_to_quiz.py --self-test
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import tempfile
from pathlib import Path

TARGET_FILENAMES = {
    "session-state.json",
    "session_state.json",
    "daemon_state.json",
    "global-state.json",
}

LEGACY_FLAT_KEY_RENAMES = {
    "poll_active": "quiz_active",
    "poll_correct_indices": "quiz_correct_indices",
    "poll_opened_at": "quiz_opened_at",
    "poll_timer_seconds": "quiz_timer_seconds",
    "poll_timer_started_at": "quiz_timer_started_at",
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def transform(data: dict) -> tuple[dict, bool, list[str]]:
    """Apply migration transformations to a top-level dict.

    Returns:
        (new_data, changed, warnings)
    """
    warnings: list[str] = []
    # Work on a shallow copy preserving key order.
    new: dict = {}
    changed = False

    # 1) current_activity == "poll" -> "quiz"
    has_current_activity = "current_activity" in data
    current_activity = data.get("current_activity")

    # 2) Handle top-level "poll" -> "quiz" key rename (move whole object).
    has_poll = "poll" in data
    has_quiz = "quiz" in data

    # Decide the resolved "quiz" value (and whether we drop "poll").
    drop_poll_key = False
    quiz_value: object | None = None
    if has_poll and has_quiz:
        warnings.append(
            "both 'poll' and 'quiz' top-level keys present; keeping existing 'quiz' and dropping 'poll'"
        )
        drop_poll_key = True
        # No change to quiz value; the existing 'quiz' value is preserved as-is.
        quiz_value = data["quiz"]
        changed = True  # we are dropping the stale 'poll' key
    elif has_poll and not has_quiz:
        drop_poll_key = True
        quiz_value = data["poll"]
        changed = True
    # else: no poll key; nothing to do for this step.

    # 3) Legacy flat key renames (only fire if the old key is present and
    #    the new key is not already present — preserve already-migrated state).
    flat_renames: dict[str, str] = {}
    for old_key, new_key in LEGACY_FLAT_KEY_RENAMES.items():
        if old_key in data:
            if new_key in data:
                warnings.append(
                    f"both '{old_key}' and '{new_key}' present; dropping legacy '{old_key}'"
                )
                flat_renames[old_key] = ""  # drop only
            else:
                flat_renames[old_key] = new_key
            changed = True

    will_change_current_activity = has_current_activity and current_activity == "poll"
    if will_change_current_activity:
        changed = True

    # Now reconstruct the dict preserving the original ordering. We replace
    # keys as we walk the existing entries; brand-new "quiz" key (when there
    # was only "poll") is inserted in the same slot as the original "poll".
    inserted_quiz = False
    for key, value in data.items():
        if key == "current_activity" and will_change_current_activity:
            new[key] = "quiz"
            continue
        if key == "poll":
            if drop_poll_key:
                # Insert "quiz" here (preserving slot) unless "quiz" already
                # exists later in the original dict — in which case it will
                # come in via its own iteration.
                if not has_quiz and not inserted_quiz:
                    new["quiz"] = quiz_value
                    inserted_quiz = True
                # Skip the old poll entry entirely.
                continue
            else:
                new[key] = value
                continue
        if key == "quiz":
            # Preserve original quiz value (or the one we resolved above if
            # both were present — they are identical here since we kept the
            # existing one).
            new[key] = value
            inserted_quiz = True
            continue
        if key in flat_renames:
            target = flat_renames[key]
            if target:  # rename
                new[target] = value
            # else: drop legacy duplicate
            continue
        new[key] = value

    # Edge case: drop_poll_key was true, quiz value not yet inserted (because
    # the "poll" key was somehow missing from iteration — shouldn't happen,
    # but be defensive).
    if drop_poll_key and not inserted_quiz:
        new["quiz"] = quiz_value

    return new, changed, warnings


def _read_text(path: Path) -> tuple[str, bool]:
    """Read file text; return (text, ends_with_newline)."""
    raw = path.read_text(encoding="utf-8")
    return raw, raw.endswith("\n")


def _dump_json(data: object, *, ensure_ascii: bool = True) -> str:
    return json.dumps(data, indent=2, ensure_ascii=ensure_ascii)


def process_file(path: Path, *, dry_run: bool, no_backup: bool) -> str:
    """Process a single file. Returns a status string for logging."""
    try:
        text, trailing_newline = _read_text(path)
    except OSError as exc:
        return f"[warn] cannot read {path}: {exc}"

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return f"[warn] invalid JSON in {path}: {exc}"

    if not isinstance(data, dict):
        return f"[skipped: not a JSON object] {path}"

    has_relevant_key = (
        "current_activity" in data
        or "poll" in data
        or "quiz" in data
        or any(k in data for k in LEGACY_FLAT_KEY_RENAMES)
        or any(k in data for k in LEGACY_FLAT_KEY_RENAMES.values())
    )
    if not has_relevant_key:
        return f"[skipped: no relevant keys] {path}"

    new_data, changed, warnings = transform(data)

    for warn in warnings:
        _log(f"[warn] {path}: {warn}")

    if not changed:
        return f"[unchanged] {path}"

    new_text = _dump_json(new_data)
    if trailing_newline:
        new_text += "\n"

    if dry_run:
        diff = difflib.unified_diff(
            text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path) + " (migrated)",
        )
        sys.stdout.writelines(diff)
        return f"[would-change] {path}"

    # Write backup before mutating, unless suppressed or .bak already exists.
    if not no_backup:
        bak_path = path.with_suffix(path.suffix + ".bak")
        if not bak_path.exists():
            try:
                bak_path.write_text(text, encoding="utf-8")
            except OSError as exc:
                return f"[error] cannot write backup {bak_path}: {exc}"

    try:
        # Atomic-ish write: write to a temp file in the same dir, then replace.
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(new_text)
            os.replace(tmp_name, path)
        except Exception:
            # Clean up tmp file on any failure
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        return f"[error] cannot write {path}: {exc}"

    return f"[migrated] {path}"


def walk_roots(roots: list[Path]) -> list[Path]:
    """Walk each root and return paths matching TARGET_FILENAMES."""
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            _log(f"[warn] root does not exist: {root}")
            continue
        if root.is_file():
            if root.name in TARGET_FILENAMES:
                found.append(root)
            continue
        for dirpath, _, filenames in os.walk(root, followlinks=False):
            for name in filenames:
                if name in TARGET_FILENAMES:
                    found.append(Path(dirpath) / name)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rename feature-sense `poll` keys to `quiz` in persisted session JSON files.",
    )
    parser.add_argument(
        "roots",
        nargs="*",
        help="One or more directories (walked recursively) or files to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a diff of what would change for each file; do not modify files.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not write a `<file>.bak` before rewriting. Default: backup is written.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run an in-process self test on synthetic JSON fixtures and exit.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()

    if not args.roots:
        parser.error("at least one root directory or file is required (or use --self-test)")

    roots = [Path(r) for r in args.roots]
    targets = walk_roots(roots)

    if not targets:
        _log("[info] no target files found")
        return 0

    for path in targets:
        status = process_file(path, dry_run=args.dry_run, no_backup=args.no_backup)
        _log(status)

    return 0


# ---------------------------------------------------------------------------
# Self test
# ---------------------------------------------------------------------------

def _run_self_test() -> int:
    failures: list[str] = []

    def check(cond: bool, label: str) -> None:
        if cond:
            _log(f"  ok   {label}")
        else:
            _log(f"  FAIL {label}")
            failures.append(label)

    _log("[self-test] running")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # File A: needs migration
        file_a = tmp_path / "session-state.json"
        file_a.write_text(
            json.dumps(
                {
                    "session_id": "abc123",
                    "current_activity": "poll",
                    "poll": {"question": "Q", "options": ["a", "b"], "correct_count": 1},
                    "poll_active": True,
                    "poll_correct_indices": [0],
                    "poll_timer_seconds": 30,
                    "extra": "keep me",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        # File B: already migrated — should be unchanged
        file_b = tmp_path / "subdir-b" / "session_state.json"
        file_b.parent.mkdir(parents=True)
        already_migrated = {
            "session_id": "def456",
            "current_activity": "quiz",
            "quiz": {"question": "Q", "options": ["a", "b"], "correct_count": 1},
            "quiz_active": True,
            "extra": "keep me",
        }
        file_b_text = json.dumps(already_migrated, indent=2) + "\n"
        file_b.write_text(file_b_text, encoding="utf-8")

        # File C: no poll/quiz keys at all — should be skipped
        file_c = tmp_path / "subdir-c" / "session-state.json"
        file_c.parent.mkdir(parents=True)
        file_c_text = json.dumps({"session_id": "ghi789", "mode": "talk"}, indent=2) + "\n"
        file_c.write_text(file_c_text, encoding="utf-8")

        # File D: invalid JSON — should warn and skip
        file_d = tmp_path / "subdir-d" / "session-state.json"
        file_d.parent.mkdir(parents=True)
        file_d.write_text("{not valid json", encoding="utf-8")

        # File E: a global-state.json with no relevant keys
        file_e = tmp_path / "global-state.json"
        file_e.write_text(
            json.dumps({"active_session_id": "abc123", "log_level": "info"}, indent=2) + "\n",
            encoding="utf-8",
        )

        # Run the migration on the tmp tree
        rc = main([str(tmp_path)])
        check(rc == 0, "exit code is 0")

        # File A migrated correctly
        a_new = json.loads(file_a.read_text(encoding="utf-8"))
        check(a_new.get("current_activity") == "quiz", "A: current_activity -> quiz")
        check("poll" not in a_new, "A: top-level 'poll' removed")
        check(a_new.get("quiz") == {"question": "Q", "options": ["a", "b"], "correct_count": 1}, "A: quiz object preserved")
        check(a_new.get("quiz_active") is True, "A: poll_active -> quiz_active")
        check(a_new.get("quiz_correct_indices") == [0], "A: poll_correct_indices -> quiz_correct_indices")
        check(a_new.get("quiz_timer_seconds") == 30, "A: poll_timer_seconds -> quiz_timer_seconds")
        check("poll_active" not in a_new, "A: legacy 'poll_active' removed")
        check(a_new.get("extra") == "keep me", "A: unrelated keys preserved")
        check(a_new.get("session_id") == "abc123", "A: session_id preserved")

        # Backup exists for File A
        bak_a = file_a.with_suffix(file_a.suffix + ".bak")
        check(bak_a.exists(), "A: .bak created")

        # File B unchanged on disk
        b_after = file_b.read_text(encoding="utf-8")
        check(b_after == file_b_text, "B: already-migrated file unchanged")
        # No backup should have been written (because no change occurred).
        bak_b = file_b.with_suffix(file_b.suffix + ".bak")
        check(not bak_b.exists(), "B: no .bak written for unchanged file")

        # File C unchanged on disk
        c_after = file_c.read_text(encoding="utf-8")
        check(c_after == file_c_text, "C: file with no relevant keys unchanged")

        # File D still invalid (untouched)
        check(file_d.read_text(encoding="utf-8") == "{not valid json", "D: invalid-JSON file untouched")

        # File E unchanged (no relevant keys)
        e_after = json.loads(file_e.read_text(encoding="utf-8"))
        check(e_after == {"active_session_id": "abc123", "log_level": "info"}, "E: global-state untouched")

        # ----- Second run: idempotency -----
        a_text_after_first = file_a.read_text(encoding="utf-8")
        bak_text_before_second = bak_a.read_text(encoding="utf-8")
        rc2 = main([str(tmp_path)])
        check(rc2 == 0, "second run exit code 0")
        check(file_a.read_text(encoding="utf-8") == a_text_after_first, "A: idempotent (no diff on second run)")
        # .bak from the first run must NOT be overwritten by the second run
        check(bak_a.read_text(encoding="utf-8") == bak_text_before_second, "A: .bak not clobbered on re-run")

        # ----- Conflict case: both poll and quiz present -----
        file_f = tmp_path / "conflict" / "session-state.json"
        file_f.parent.mkdir()
        file_f.write_text(
            json.dumps(
                {
                    "current_activity": "quiz",
                    "poll": {"stale": True},
                    "quiz": {"fresh": True},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        rc3 = main([str(file_f)])
        check(rc3 == 0, "conflict-file exit code 0")
        f_after = json.loads(file_f.read_text(encoding="utf-8"))
        check("poll" not in f_after, "F: stale 'poll' dropped")
        check(f_after.get("quiz") == {"fresh": True}, "F: existing 'quiz' wins")

        # ----- Dry-run leaves file unchanged -----
        file_g = tmp_path / "dryrun" / "session-state.json"
        file_g.parent.mkdir()
        original_g = (
            json.dumps({"current_activity": "poll", "poll": {"x": 1}}, indent=2) + "\n"
        )
        file_g.write_text(original_g, encoding="utf-8")
        rc4 = main(["--dry-run", str(file_g)])
        check(rc4 == 0, "dry-run exit code 0")
        check(file_g.read_text(encoding="utf-8") == original_g, "G: dry-run did not modify file")
        check(not file_g.with_suffix(file_g.suffix + ".bak").exists(), "G: dry-run did not create .bak")

        # ----- --no-backup suppresses .bak -----
        file_h = tmp_path / "nobackup" / "session-state.json"
        file_h.parent.mkdir()
        file_h.write_text(
            json.dumps({"current_activity": "poll", "poll": {"x": 1}}, indent=2) + "\n",
            encoding="utf-8",
        )
        rc5 = main(["--no-backup", str(file_h)])
        check(rc5 == 0, "--no-backup exit code 0")
        check(not file_h.with_suffix(file_h.suffix + ".bak").exists(), "H: --no-backup suppressed .bak")
        h_after = json.loads(file_h.read_text(encoding="utf-8"))
        check(h_after.get("current_activity") == "quiz", "H: --no-backup still migrated content")

    if failures:
        _log(f"[self-test] FAILED ({len(failures)} failures)")
        return 1
    _log("[self-test] PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
