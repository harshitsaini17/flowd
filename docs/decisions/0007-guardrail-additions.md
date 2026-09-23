# 0007: Guardrail additions and cleanup-client limits

**Status:** proposed
**Date:** 2026-09-27

## Context

Spec 7.4 lists six guardrail checks. Running them over the outputs from ADR 0006's
model screen, plus hand-made failures, turned up two kinds of invention
that none of the six catch:

- **An answer instead of a rewrite.** "can you send me the the report by friday"
  → "Yes, I can send you the report by Friday." Every content word is in the raw
  text, and the length ratio is 1.0. Only the speaker has changed.
- **A repeated tail.** "…returns a json object with three fields" → "…with three
  fields. json object." ADR 0006 saw this from the LFM 350M chat model. The
  repeat is a small share of the output, so check 3 passes it.

Three more gaps turned up while wiring the client:

- `llama-server` runs with `-c 1024` (ADR 0006). The context holds prompt plus
  output, so a long dictation gets its answer cut off mid-sentence, with nothing
  in the reply that says so reliably.
- Spec 5.5 says the server is on `127.0.0.1`, but nothing enforced it. A
  `[llm] url` pointing elsewhere would send every dictation off the machine as
  plain HTTP, against spec 13.2.
- `flowctl` waits 2 s for a reply. After release, a `stop` now answers only after
  STT finalize (up to ~850 ms), the LLM (capped at 800 ms) and injection.

## Decision

1. **Check 7, person or answer flip.** Reject when the output has a first- or
   second-person pronoun (`i me my mine you your yours we us our ours`) that the
   raw text does not have, or when it opens with `yes`, `no`, `yeah` or `nope`
   and the raw text does not have that word. The pronoun inside a raw
   contraction counts as present, so "i'm" → "I am" is a rewrite, not a flip.
2. **Check 8, repeated content word.** Reject when a content word (stop-words
   removed) appears more often in the output than in the raw text.
2a. **Check 9, negation count.** Reject when the output has a different
   number of negations (`not`, `never`, `cannot`, any `…n't`) than the raw
   text. Negations are stop words, so checks 3 and 8 never see one being
   added or dropped. `no` is excluded, because in dictation it is mostly a
   self-correction cue ("five no wait six").
3. Checks run in number order and the first failure is recorded, so 7 and 8 are
   reached only by outputs that passed spec's 1–6. Neither adds a threshold.
4. **Context guard.** `[llm] context_tokens = 1024`, matching `-c`. When raw
   tokens + 16 (prompt overhead) + `max_tokens` exceeds it, the client skips the
   LLM and returns `"too long"`. The daemon falls back and counts it. It is not
   a server failure, so it does not count towards `down`.
5. **Loopback only.** Config rejects an `[llm] url` whose host is not
   `127.0.0.1`, `localhost` or `::1`, and the HTTP client ignores proxy
   environment variables (`trust_env=False`) so a proxy cannot route the
   request off the machine.
6. **`flowctl` reply timeout 5 s.**
7. **A timeout does not count towards `down`.** Only connect errors, HTTP errors
   and malformed replies do. A reply slower than 800 ms means a busy server, not
   a dead one, and marking it down would turn cleanup off for 30 s.

## Consequences

- Still open: an invented number ("…on Friday at 5")
  passes when it stays under check 4's 20%, and a single correction cue
  anywhere in the session loosens check 1's lower bound for all of it.
  Both change spec 7.4 thresholds.

- Known gap, unchanged: a rewrite that reorders words without adding any (for
  example "delete old branch push main" into a different command) passes every
  check. Only the eval's manual review catches it.
- Check 7 would reject a legitimate rewrite that adds a pronoun the speaker left
  out ("send it" → "I'll send it"). Sotto did not do this in the screen, and a
  fallback costs polish, not correctness.
- Long dictations (over roughly 400 tokens, about 300 words) always get
  `basic_clean` with single-pass cleanup. Chunked cleanup (ADR 0008) removes
  this limit.
