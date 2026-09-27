# 0010: Full-rewrite pass

Status: proposed

## Context

Spec 6.6 adds an opt-in pass: `flowctl stop --rewrite` sends the whole joined
text (≤ 300 words) through one more LLM call "with the `rewrite` prompt", under
the same guardrails. Spec 7.3 describes that prompt as a mode that "may reorder
sentences for clarity".

Sotto takes a fixed completion prompt with no instruction slot (ADR 0006), so
there is no second prompt to give it. ADR 0009 reached the same point for
modes.

## Options

1. Send the joined text through Sotto's own format, unchanged.
2. Serve a second, instruction-following model for this pass alone.
3. Drop the mode.

## Recommendation

Option 1. The chunked pass cleans 5-25 words at a time, so a self-correction
that crosses a chunk boundary is only half merged (ADR 0008). One pass over the
whole text fixes exactly that. On the reference machine, "So the meeting is
moved to three. No wait four. And bring the slides." came back as "The meeting
is moved to 4. And bring the slides.", and it passed every guardrail.

Option 2 would add a second resident model and blow the memory budget
(ADR 0006). Option 3 loses the only fix for cross-chunk corrections.

## Impact on spec

- 6.6: the pass uses the cleanup model's own prompt, not a separate `rewrite`
  prompt, and it does not reorder sentences.
- The pass has the recording-time budget (`llm.timeout_ms`, 2,000 ms) and not
  `final_timeout_ms`. The user asked for it, and its latency grows with length.
- `--rewrite` works on `stop` and on `toggle`. Code mode never rewrites,
  because it never uses the LLM (ADR 0009).
- The `stop` reply carries `rewrite`: `accepted`, `rejected`, `failed` or
  `skipped`. The metrics count `rewrite_accepted` and `rewrite_rejected`.
