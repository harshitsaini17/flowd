# 0008: Chunked cleanup details

Status: proposed

## Context

The scheduler implements spec 6's single-flight design. Five details are not settled by the spec, or conflict with earlier decisions.

## Decision

1. **Context reaches the guardrails, not the prompt.** Spec 6.2 sends the last `context_sentences` polished sentences as read-only context. Sotto's prompt format (ADR 0006) has no slot for it, so context is passed to guardrail checks 3 (known words) and 6 (repeated sentence) only.
2. **The recording timeout applies while recording.** A chunk dispatched while recording gets `[llm] timeout_ms` (2,000 ms). After release, each chunk gets whatever is left of `final_timeout_ms`.
3. **A correction cue is scoped to one chunk.** A cue loosens check 1's lower bound for the chunk it appears in, or for the merged chunk. It no longer applies across the whole session.
4. **Seams are repaired in code.** When a chunk's raw text did not end a sentence, `stitch()` drops the period the LLM added. It also lowercases the next chunk's capital if that chunk's raw text started in lowercase. `?`, `!` and a capital "I" are kept.
5. **The fallback rate is per chunk** (spec 11.3's "chunks rejected ÷ chunks"). The eval now reports `llm_chunks` and `sessions_with_fallback` as well.

## Consequences

- Smaller inputs give Sotto less to go on, so there are more chunk-level rewrites for the guardrails to reject. On the dry run, most rejections are check 3 and check 7 on archaic audiobook text ("thy" → "my", "first" → "1").
- A self-correction that spans more than one previous chunk is only half merged. The spec leaves deep corrections to the full-rewrite mode.
