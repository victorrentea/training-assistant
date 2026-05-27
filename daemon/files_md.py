"""files.md — the canonical store of files opened during a session.

All feature state lives in the markdown file itself:
- Repo default branch cached in `<!-- default_branch:... -->` on the `##` heading.
- File first-open timestamp + path/reason cached in HTML comments on each bullet.

HTML comments are stripped before serving to participants — see `sanitize_for_wire`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

EMPTY_STATE = "# Files opened this session\n\nNo files opened yet\n"

_TITLE = "# Files opened this session"

_RE_REPO = re.compile(
    r"^## \[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\) <!-- default_branch:(?P<branch>[^ ]+) -->$"
)
_RE_LINKED = re.compile(
    r"^- \[(?P<basename>[^\]]+)\]\((?P<blob>[^)]+)\) "
    r"<!-- ts:(?P<ts>[^ ]+) path:(?P<path>[^ ]+) -->$"
)
_RE_UNLINKED = re.compile(
    r"^- (?P<basename>\S+) <!-- ts:(?P<ts>[^ ]+) reason:(?P<reason>[^ ]+) -->$"
)
_RE_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Entry:
    basename: str
    blob_url: str | None
    path: str | None
    ts: str
    reason: str | None


@dataclass
class Repo:
    url: str
    name: str
    default_branch: str
    entries: list[Entry] = field(default_factory=list)


@dataclass
class Doc:
    repos: list[Repo] = field(default_factory=list)

    def find_repo(self, url: str) -> Repo | None:
        for r in self.repos:
            if r.url == url:
                return r
        return None

    def find_entry(self, repo_url: str, basename: str) -> Entry | None:
        repo = self.find_repo(repo_url)
        if repo is None:
            return None
        for e in repo.entries:
            if e.basename == basename:
                return e
        return None

    def render(self) -> str:
        if not self.repos:
            return EMPTY_STATE
        parts = [_TITLE, ""]
        for repo in self.repos:
            parts.append(
                f"## [{repo.name}]({repo.url}) <!-- default_branch:{repo.default_branch} -->"
            )
            parts.append("")
            for e in repo.entries:
                if e.blob_url and e.path:
                    parts.append(
                        f"- [{e.basename}]({e.blob_url}) <!-- ts:{e.ts} path:{e.path} -->"
                    )
                else:
                    parts.append(
                        f"- {e.basename} <!-- ts:{e.ts} reason:{e.reason or 'no-path'} -->"
                    )
            parts.append("")
        text = "\n".join(parts).rstrip() + "\n"
        return text

    @classmethod
    def parse(cls, text: str) -> "Doc":
        doc = cls()
        if not text or text.strip() == EMPTY_STATE.strip():
            return doc
        current: Repo | None = None
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line:
                continue
            m = _RE_REPO.match(line)
            if m:
                current = Repo(
                    url=m.group("url"),
                    name=m.group("name"),
                    default_branch=m.group("branch"),
                )
                doc.repos.append(current)
                continue
            if current is None:
                continue
            m = _RE_LINKED.match(line)
            if m:
                current.entries.append(
                    Entry(
                        basename=m.group("basename"),
                        blob_url=m.group("blob"),
                        path=m.group("path"),
                        ts=m.group("ts"),
                        reason=None,
                    )
                )
                continue
            m = _RE_UNLINKED.match(line)
            if m:
                current.entries.append(
                    Entry(
                        basename=m.group("basename"),
                        blob_url=None,
                        path=None,
                        ts=m.group("ts"),
                        reason=m.group("reason"),
                    )
                )
        return doc


def atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def sanitize_for_wire(text: str) -> str:
    return _RE_COMMENT.sub("", text)
