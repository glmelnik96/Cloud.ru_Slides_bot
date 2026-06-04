# WS-E LLM probe harness

Per `memory/prompt_adaptation.md`, every re-engineered prompt under
`llm/prompts/` must be validated against live Cloud.ru FM before we
trust it inside the pipeline. The probe harness under `tests/probes/`
does that — one parametrised test per agent, exercised across 3 deck
sizes (small=3, medium=8, big=15 slides) using synthetic upstream
artefacts from `tests/probes/fixtures.py`.

## What gets covered

| Probe | Agent | Model | Schema |
|---|---|---|---|
| `test_agent_01_brief.py` | Brief Reader | Kimi-K2.6 vision | `Brief` |
| `test_agent_02_classifier.py` | Slide Classifier | DeepSeek-V4-Pro | `DeckClassification` |
| `test_agent_03_distributor.py` | Content Distributor | GLM-5.1 OFF | `DeckContent` (wrapper) |
| `test_agent_04_designer.py` | Layout Designer | DeepSeek-V4-Pro | `LayoutPlan` |
| `test_agent_05_icons.py` | Icon Picker | GLM-5.1 OFF | `DeckIcons` (wrapper) |
| `test_agent_06_infographic.py` | Infographic Maker | GLM-5.1 OFF | `DeckInfographics` (wrapper) |
| `test_agent_07_copyedit.py` | Copy Editor | GLM-5.1 OFF | `DeckContent` (wrapper) |
| `test_agent_10_visual.py` | Visual Verifier | Kimi-K2.6 vision | `VisualVerdict` |

8 agents × 3 sizes = **24 live API calls** per full run, all per-deck
(not per-slide), so the actual token bill is dominated by the bigger
fixtures (`big` = 15 slides).

## Running

Probes are double-gated so they never run by accident on CI:

```bash
export CLOUDRU_API_KEY=...
pytest --cloudru tests/probes/ -v
```

Without **both** `--cloudru` and `CLOUDRU_API_KEY` the tests SKIP.

Per-agent subset:

```bash
pytest --cloudru tests/probes/test_agent_07_copyedit.py -v
```

Single size:

```bash
pytest --cloudru "tests/probes/test_agent_02_classifier.py::test_classifier[small]"
```

## Report

A markdown report is written to `tests/probes/_report.md` at session
teardown (regardless of pass/fail). It contains:

- Summary: total runs, schema_ok count, retry count, total tokens.
- Per-agent rollup: model, schema_ok rate, retries used, tokens.
- Detail rows: per (agent, size) with elapsed/in/out tokens and either
  the first 120 chars of output (on success) or the validation error
  (on failure).

The report intentionally lives next to the probe code (not under
`reports/`) so it's discoverable when reviewing failures.

## Synthetic vs real fixtures

The current factories produce **plausible** parsed-deck / brief / etc.
JSON. They are not real LLM outputs — agent 02's classification was
hand-rolled to look like agent 02 would produce, and so on. This
isolates each probe so a failure in agent 02 doesn't poison the
agent 03 probe.

A second pass against **real** decks from
`C:\Users\Глеб\Downloads\презы_на_тест\презы на тест` lands after the
synthetic pass is green — we expect agent 02 → agent 03 chaining to
expose more edge cases.

## When to re-run

- Any change to `llm/prompts/agent_*.py` → re-run that agent's probe.
- Any change to `llm/roles.py` (model swap, thinking toggle) → re-run all.
- Any schema tightening in `schemas/slides.py` → re-run all (a previously
  passing prompt may now fail the stricter contract).
