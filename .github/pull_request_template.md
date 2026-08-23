## What this changes

A sentence or two. If it fixes an issue, `Fixes #N`.

## Why

What was wrong, or what became possible. If a tool or an API behaved
differently from its documentation and that is why the code looks the way it
does, this is the place to say so — that note tends to outlive everything else
in the pull request.

## How you know it works

- [ ] `uv run pytest -q`
- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run mypy flowd flowctl`

For a bug fix: which test fails without the fix?

For anything touching audio, injection or the overlay, the suite cannot reach
the hardware. Say what you ran by hand, on what compositor and session type,
and what you saw.

## Checklist

- [ ] Tests written before the implementation, and each one failed first
- [ ] No audio, transcripts, metrics, model weights or personal vocabulary added
- [ ] A decision record in `docs/decisions/` if this changes a default, a model,
      the architecture, or anything `docs/spec.md` states as a rule
- [ ] Commit messages follow `phase<N>(component): summary`
