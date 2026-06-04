"""Inspect what GLM-5.1 actually returns when content is empty."""
from __future__ import annotations

import json

from _common import make_client, timed_chat


def main() -> None:
    client = make_client()
    resp, elapsed, err = timed_chat(
        client,
        model="zai-org/GLM-5.1",
        max_tokens=256,
        temperature=0.0,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
    )
    if err:
        print("ERR", err)
        return
    print(f"elapsed={elapsed:.2f}s")
    print("--- raw choice 0 ---")
    print(json.dumps(resp.choices[0].model_dump(), indent=2, ensure_ascii=False))
    print("--- usage ---")
    print(json.dumps(resp.usage.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
