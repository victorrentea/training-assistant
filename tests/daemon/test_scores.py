import threading
from daemon.scores import Scores


def make_scores():
    return Scores()


def test_add_score_same_pid():
    s = make_scores()
    s.add_score("p1", 10)
    s.add_score("p1", 5)
    assert s.scores["p1"] == 15


def test_add_score_different_pid():
    s = make_scores()
    s.add_score("p1", 10)
    s.add_score("p2", 20)
    assert s.scores["p1"] == 10
    assert s.scores["p2"] == 20


def test_snapshot_returns_copy():
    s = make_scores()
    s.add_score("p1", 10)
    snap = s.snapshot()
    snap["p1"] = 999
    assert s.scores["p1"] == 10


def test_snapshot_base_captures_current():
    s = make_scores()
    s.add_score("p1", 10)
    s.snapshot_base()
    s.add_score("p1", 5)
    assert s.base_scores["p1"] == 10
    assert s.scores["p1"] == 15


def test_reset_clears_both():
    s = make_scores()
    s.add_score("p1", 10)
    s.snapshot_base()
    s.reset()
    assert s.scores == {}
    assert s.base_scores == {}


def test_sync_from_restore_replaces_data():
    s = make_scores()
    s.add_score("p1", 100)
    s.sync_from_restore({"scores": {"p2": 50}, "base_scores": {"p2": 30}})
    assert s.scores == {"p2": 50}
    assert s.base_scores == {"p2": 30}
    assert "p1" not in s.scores


def test_sync_from_restore_missing_base_scores():
    """When base_scores is absent from restore data, existing base_scores are preserved."""
    s = make_scores()
    s.add_score("p1", 100)
    s.snapshot_base()
    s.sync_from_restore({"scores": {"p2": 50}})
    assert s.scores == {"p2": 50}
    assert s.base_scores == {"p1": 100}  # untouched — key absent from restore data


def test_thread_safety():
    s = make_scores()
    pid = "p1"
    threads = []

    def add_many():
        for _ in range(1000):
            s.add_score(pid, 1)

    for _ in range(4):
        t = threading.Thread(target=add_many)
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert s.scores[pid] == 4000
