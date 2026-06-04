"""Smoke test: verify all three models are reachable and return text."""
from __future__ import annotations

from _common import MODELS, make_client, timed_chat


def main() -> None:
    client = make_client()
    print(f"{'model':<32} {'lat_s':>6}  {'tok_out':>7}  status")
    print("-" * 72)
    for model in MODELS:
        resp, elapsed, err = timed_chat(
            client,
            model=model,
            max_tokens=64,
            temperature=0.0,
            messages=[{"role": "user", "content": "Reply with exactly: pong"}],
        )
        if err:
            print(f"{model:<32} {elapsed:>6.2f}  {'-':>7}  ERR  {err[:80]}")
            continue
        txt = (resp.choices[0].message.content or "").strip()
        out_tok = getattr(resp.usage, "completion_tokens", None)
        print(f"{model:<32} {elapsed:>6.2f}  {str(out_tok):>7}  OK   {txt[:40]!r}")


if __name__ == "__main__":
    main()
