"""What a robot keeps between runs.

Until now every run started fresh: the transcript recorded everything and forgot it the
moment the process exited. `RobotMemory` is the small, honest fix: one append-only JSONL
file per robot (adapter:backend, so a simulated duck and a real one never share notes),
holding two kinds of entry —

- **notes** the model chose to keep (`remember`: "the ball is usually near the left wall"),
- **episodes** quackd writes itself at the end of every run (outcome, reason, highlights).

At the next run the newest of each are rendered into the system prompt, so the pilot
starts with what it learned last time instead of nothing. No embeddings, no database: a
file you can read, edit and delete with `quackd memory`.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

DEFAULT_DIR = "~/.quackd/memory"
ENV_DIR = "QUACKD_MEMORY_DIR"
MAX_ENTRIES = 400
"""Hard cap on lines per file; the oldest are dropped past it (episodes first, notes last)."""
NOTE_MAX_CHARS = 200

Kind = Literal["note", "episode"]


def memory_dir(override: str | Path | None = None) -> Path:
    """`--memory-dir`, else `$QUACKD_MEMORY_DIR`, else `~/.quackd/memory`."""
    raw = override or os.environ.get(ENV_DIR) or DEFAULT_DIR
    return Path(raw).expanduser()


def robot_slug(key: str) -> str:
    """`microduck:sim2d` → `microduck-sim2d`: a file name, nothing clever."""
    slug = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")
    return slug or "robot"


@dataclass
class MemoryEntry:
    kind: Kind
    text: str
    ts: float
    duck: str | None = None
    tags: list[str] = field(default_factory=list)
    outcome: str | None = None
    highlights: list[str] = field(default_factory=list)
    run_dir: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "text": self.text, "ts": round(self.ts, 3)}
        if self.duck:
            out["duck"] = self.duck
        if self.tags:
            out["tags"] = self.tags
        if self.outcome:
            out["outcome"] = self.outcome
        if self.highlights:
            out["highlights"] = self.highlights
        if self.run_dir:
            out["run_dir"] = self.run_dir
        return out

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> MemoryEntry:
        return cls(
            kind=d.get("kind", "note"),
            text=str(d.get("text", "")),
            ts=float(d.get("ts", 0.0)),
            duck=d.get("duck"),
            tags=list(d.get("tags", [])),
            outcome=d.get("outcome"),
            highlights=list(d.get("highlights", [])),
            run_dir=d.get("run_dir"),
        )

    @property
    def date(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self.ts))


class RobotMemory:
    """One robot's memory file. Every method re-reads the file: cheap, and safe across
    a CLI run and an MCP server pointing at the same robot."""

    def __init__(self, robot_key: str, base_dir: str | Path | None = None) -> None:
        self.robot_key = robot_key
        self.path = memory_dir(base_dir) / f"{robot_slug(robot_key)}.jsonl"

    # ── storage ─────────────────────────────────────────────────────────────────────

    def entries(self) -> list[MemoryEntry]:
        if not self.path.exists():
            return []
        out: list[MemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(MemoryEntry.from_json(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue  # a hand-edited line that is not JSON is skipped, not fatal
        return out

    def _write_all(self, entries: list[MemoryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        tmp.write_text(
            "".join(json.dumps(e.to_json(), ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def _append(self, entry: MemoryEntry) -> None:
        entries = self.entries()
        entries.append(entry)
        if len(entries) > MAX_ENTRIES:
            # drop the oldest episodes first; notes were chosen on purpose
            episodes = [e for e in entries if e.kind == "episode"]
            excess = len(entries) - MAX_ENTRIES
            drop = {id(e) for e in episodes[:excess]}
            entries = [e for e in entries if id(e) not in drop]
            if len(entries) > MAX_ENTRIES:
                entries = entries[-MAX_ENTRIES:]
        self._write_all(entries)

    def notes(self) -> list[MemoryEntry]:
        return [e for e in self.entries() if e.kind == "note"]

    def episodes(self) -> list[MemoryEntry]:
        return [e for e in self.entries() if e.kind == "episode"]

    def clear(self) -> int:
        n = len(self.entries())
        if self.path.exists():
            self.path.unlink()
        return n

    # ── writing ─────────────────────────────────────────────────────────────────────

    def remember(
        self,
        text: str,
        *,
        tags: list[str] | None = None,
        duck: str | None = None,
        run_dir: str | Path | None = None,
        now: float | None = None,
    ) -> MemoryEntry:
        """Save one short fact. The same sentence twice refreshes the old entry instead of
        duplicating it, so a model that repeats itself does not fill the file."""
        clean = " ".join(str(text).split())[:NOTE_MAX_CHARS]
        if not clean:
            raise ValueError("nothing to remember")
        ts = time.time() if now is None else now
        entries = self.entries()
        for e in entries:
            if e.kind == "note" and e.text.lower() == clean.lower():
                e.ts = ts
                e.tags = sorted(set(e.tags) | set(tags or []))
                if duck:
                    e.duck = duck
                self._write_all(entries)
                return e
        entry = MemoryEntry(
            kind="note",
            text=clean,
            ts=ts,
            duck=duck,
            tags=sorted(set(tags or [])),
            run_dir=str(run_dir) if run_dir else None,
        )
        self._append(entry)
        return entry

    def record_episode(
        self,
        *,
        duck: str,
        outcome: str,
        reason: str,
        steps: int,
        highlights: list[str] | None = None,
        run_dir: str | Path | None = None,
        now: float | None = None,
    ) -> MemoryEntry:
        text = (
            f"{duck}: {outcome} — {' '.join(str(reason).split())[:NOTE_MAX_CHARS]} ({steps} steps)"
        )
        entry = MemoryEntry(
            kind="episode",
            text=text,
            ts=time.time() if now is None else now,
            duck=duck,
            outcome=outcome,
            highlights=[" ".join(h.split())[:NOTE_MAX_CHARS] for h in (highlights or [])][:4],
            run_dir=str(run_dir) if run_dir else None,
        )
        self._append(entry)
        return entry

    # ── reading ─────────────────────────────────────────────────────────────────────

    def recall(self, *, max_notes: int = 20, max_episodes: int = 5) -> str:
        """The block the system prompt carries. Empty string when there is nothing yet."""
        notes = self.notes()[-max_notes:]
        episodes = self.episodes()[-max_episodes:]
        if not notes and not episodes:
            return ""
        lines: list[str] = []
        if notes:
            lines.append("Notes you saved earlier:")
            lines.extend(f"- [{e.date}] {e.text}" for e in reversed(notes))
        if episodes:
            if lines:
                lines.append("")
            lines.append("Your most recent runs on this robot (newest first):")
            for e in reversed(episodes):
                line = f"- [{e.date}] {e.text}"
                if e.highlights:
                    line += " · " + "; ".join(e.highlights)
                lines.append(line)
        return "\n".join(lines)

    def summary(self) -> dict[str, Any]:
        entries = self.entries()
        return {
            "robot": self.robot_key,
            "path": str(self.path),
            "notes": sum(1 for e in entries if e.kind == "note"),
            "episodes": sum(1 for e in entries if e.kind == "episode"),
        }
