# 0006: Cleanup LLM for phase 3

**Status:** proposed (awaiting owner approval, spec 13.2)
**Date:** 2026-09-27

## Context

Spec 3 fixes the cleanup LLM as LFM2.5-350M QAD Q4_0 and lists LFM2.5-230M QAD
Q4_0 as the approved fallback. The owner asked for the smallest model that
fits, and phase 2's known issue 2 leaves almost no memory for `llama-server`.
The owner's own search surfaced one more candidate: Sotto, a dictation-cleanup
fine-tune of LFM2.5-350M-Base.

All three were served by `llama-server` 0.4.1-dev (build 10964) on the
reference machine (Ryzen 5 5600H), measured with `scripts/bench_llm.py`: one
warm-up request, then 12 fixed cases at temperature 0. The chat models got one
system prompt; Sotto got its own `### Input:` / `### Output:` completion format.

| Model | File | SHA-256 (prefix) | RSS | Anon | File-backed | p50 | max |
|---|---|---|---|---|---|---|---|
| LFM2.5-350M QAD Q4_0 (spec default) | 219 MB | `3d10b6ab` | 421.7 MB | 201.3 MB | 220.4 MB | 183 ms | 498 ms |
| LFM2.5-230M QAD Q4_0 (spec fallback) | 142 MB | `e75f8326` | 284.5 MB | 131.2 MB | 153.4 MB | 107 ms | 338 ms |
| Sotto cleanup LFM2.5-350M Q4_K_M | 219 MB | `6cd4dfed` | 409.5 MB | 179.6 MB | 229.9 MB | 102 ms | 118 ms |

## Findings

**Server flags matter as much as the model.** The spec's service runs with
`-c 2048` and llama-server's defaults (auto parallel slots, 2048/512 batches, an
8 GiB prompt cache). `-c 1024 -np 1 -b 128 -ub 128 -cram 0` saves ~27 MB of
anonymous memory on the 350M and ~30 MB on the 230M at the same latency. Chunks
are 5–25 words, so 1,024 tokens of context is ample. `--no-repack` saves a
further ~150 MB but makes decoding 10–18× slower (3.6 s p50 on the 350M), so it
is rejected.

**The general chat models do not clean dictation; they answer it.** Both LFM
chat models were given "what time does the meeting start" and replied "The
meeting starts at 10:00 AM." Both wrote a poem for "write a poem about the
ocean." The 350M answered "can you send me the the report by friday" with "Sure!
Here's a cleaned-up version:" and invented "json object." at the end of another
case. The 230M mostly echoed its input unchanged — no punctuation, fillers and
self-corrections kept — except where it answered instead. Spec 6's guardrails
would reject most of these, but a model whose output is rejected most of the
time buys nothing over `basic_clean`. One system prompt was tried; a better
prompt might help the 230M, and that is untested.

**Sotto did the job on 11 of 12 cases.** It removed fillers, applied both
self-corrections ("five no wait six" → "6", "two no three" → "three"), kept
acronyms (LLM, STT, API, JSON, PR), and left the question, the poem request and
the git instruction as punctuated dictation instead of acting on them. Its one
failure changed a word: "can you remind me to call mom" became "can you
remember to call mom" — exactly what spec 6's novel-word guardrail exists to
catch. It was also the fastest and the most consistent (118 ms worst case).

## Decision (proposed)

Use Sotto cleanup LFM2.5-350M Q4_K_M for phase 3, with the trimmed server
flags above, and keep spec 6's guardrails as the safety net rather than trusting
the model. Keep LFM2.5-230M as the fallback only if a prompt is found that makes
it clean rather than echo or answer.

"Smallest that fits" is read as "smallest that does the task": the 230M is
128 MB smaller but does not clean, so it does not fit.

## Consequences

- **Memory is over budget.** Daemon after dictating (424.6 MB) + overlay
  (194.4 MB) + Sotto (409.5 MB) = 1,028.5 MB against 900 MB. 229.9 MB of
  Sotto's figure is file-backed model mapping the kernel can reclaim; counting
  anonymous memory only, the total is 798.6 MB. Whether the budget is RSS or
  anonymous memory is the owner's call, and it decides whether this passes.
- **License is unchanged in kind.** Sotto is a derivative of LFM2.5-350M-Base
  and its GGUF keeps the LFM Open License v1.0, the same as the spec default.
  The upstream fine-tune labels itself MIT; the base license governs.
- **Third-party weights.** Sotto is a community fine-tune, not a Liquid AI
  release. `models.lock` pins its hash, so it cannot change underneath us.
- **Prompt shape is decided by the model.** Sotto takes a completion prompt, not
  chat, which settles phase 0's unresolved `<new></new>` question for this
  model: phase 3's `cleanup.py` calls `/completion`, not `/v1/chat/completions`.
- **Not yet done, pending approval:** `models.lock`, `scripts/fetch_models.sh`
  and `systemd/flowd-llm.service` still name the 350M and the old flags. The two
  candidate files are in `$XDG_DATA_HOME/flowd/models/candidates/`, outside the
  lock, so the daemon's hash check is unaffected.
- **12 cases is a screen, not an eval.** Phase 3's recorded eval run (spec 11)
  is what accepts or rejects this choice.
