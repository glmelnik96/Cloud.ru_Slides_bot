"""Markdown report collector for WS-E probe runs.

Each probe records one row per (agent, size) — schema_ok, retry_used,
elapsed, tokens, content head. The session-scope report fixture flushes
the accumulated table to ``tests/probes/_report.md`` at teardown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ProbeRow:
    agent: str
    size: str
    model: str
    schema_ok: bool
    retry_used: bool
    elapsed_s: float
    prompt_tokens: int
    completion_tokens: int
    content_head: str  # first ~120 chars of the FINAL (post-retry) output
    error: str = ""  # populated when schema_ok=False


@dataclass
class ProbeReport:
    rows: list[ProbeRow] = field(default_factory=list)

    def record(self, row: ProbeRow) -> None:
        self.rows.append(row)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        lines.append("# WS-E probe report")
        lines.append("")
        lines.append(f"_generated {datetime.now(timezone.utc).isoformat()}_")
        lines.append("")
        # Aggregate summary
        total = len(self.rows)
        ok = sum(1 for r in self.rows if r.schema_ok)
        retried = sum(1 for r in self.rows if r.retry_used)
        total_pt = sum(r.prompt_tokens for r in self.rows)
        total_ct = sum(r.completion_tokens for r in self.rows)
        total_elapsed = sum(r.elapsed_s for r in self.rows)
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- runs:           **{total}**")
        lines.append(f"- schema_ok:      **{ok} / {total}**")
        lines.append(f"- retries used:   **{retried}**")
        lines.append(f"- elapsed total:  **{total_elapsed:.1f} s**")
        lines.append(f"- prompt tokens:  **{total_pt}**")
        lines.append(f"- output tokens:  **{total_ct}**")
        lines.append("")
        # Per-agent rollup
        by_agent: dict[str, list[ProbeRow]] = {}
        for r in self.rows:
            by_agent.setdefault(r.agent, []).append(r)
        lines.append("## Per agent")
        lines.append("")
        lines.append("| agent | model | runs | schema_ok | retries | sec | in tok | out tok |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for agent, rs in sorted(by_agent.items()):
            n = len(rs)
            n_ok = sum(1 for r in rs if r.schema_ok)
            n_retry = sum(1 for r in rs if r.retry_used)
            sec = sum(r.elapsed_s for r in rs)
            pt = sum(r.prompt_tokens for r in rs)
            ct = sum(r.completion_tokens for r in rs)
            model = rs[0].model
            lines.append(
                f"| {agent} | {model} | {n} | {n_ok}/{n} "
                f"| {n_retry} | {sec:.1f} | {pt} | {ct} |"
            )
        lines.append("")
        # Full row dump
        lines.append("## Detail rows")
        lines.append("")
        lines.append(
            "| agent | size | schema_ok | retry | sec | in | out | error / head |"
        )
        lines.append("|---|---|:---:|:---:|---:|---:|---:|---|")
        for r in self.rows:
            note = r.error if not r.schema_ok else r.content_head
            note = note.replace("|", "\\|").replace("\n", " ")
            if len(note) > 120:
                note = note[:117] + "…"
            ok_mark = "✓" if r.schema_ok else "✗"
            retry_mark = "✓" if r.retry_used else " "
            lines.append(
                f"| {r.agent} | {r.size} | {ok_mark} | {retry_mark} "
                f"| {r.elapsed_s:.1f} | {r.prompt_tokens} "
                f"| {r.completion_tokens} | {note} |"
            )
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
