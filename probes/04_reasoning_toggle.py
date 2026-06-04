"""Try to disable reasoning/thinking on GLM-5.1 and Kimi-K2.6.

Three known toggles in OpenAI-compatible APIs:
  - extra_body={"thinking": {"type": "disabled"}}  (Anthropic/Z.ai style)
  - extra_body={"enable_thinking": False}          (Qwen / vLLM style)
  - extra_body={"chat_template_kwargs": {"enable_thinking": False}}  (vLLM newer)

We try each and report which one actually reduces completion_tokens.
"""
from __future__ import annotations

from _common import make_client, timed_chat

PROMPT = "Reply ONLY with valid JSON: {\"ok\": true}"

VARIANTS = [
    ("baseline", {}),
    ("thinking.disabled", {"extra_body": {"thinking": {"type": "disabled"}}}),
    ("enable_thinking=False", {"extra_body": {"enable_thinking": False}}),
    ("chat_template_kwargs", {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}),
    ("reasoning.exclude", {"extra_body": {"reasoning": {"exclude": True}}}),
]


def main() -> None:
    client = make_client()
    for model in ["zai-org/GLM-5.1", "moonshotai/Kimi-K2.6", "deepseek-ai/DeepSeek-V4-Pro"]:
        print(f"\n=== {model} ===")
        for label, extra in VARIANTS:
            resp, elapsed, err = timed_chat(
                client,
                model=model,
                max_tokens=200,
                temperature=0.0,
                messages=[{"role": "user", "content": PROMPT}],
                **extra,
            )
            if err:
                print(f"  {label:<28} ERR  {err[:80]}")
                continue
            out = resp.usage.completion_tokens
            content_len = len((resp.choices[0].message.content or "").strip())
            reasoning_len = len((getattr(resp.choices[0].message, "reasoning", "") or ""))
            print(f"  {label:<28} {elapsed:>5.2f}s  out_tok={out:<4} content={content_len:<4} reasoning={reasoning_len}")


if __name__ == "__main__":
    main()
