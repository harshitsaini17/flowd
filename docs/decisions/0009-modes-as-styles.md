# 0009: Modes are pipeline styles, not prompts

Status: proposed

## Context

Spec 7.3 describes modes as instructions to the cleanup LLM ("code: keep symbols", "chat: casual"). Sotto (ADR 0006) is a fine-tuned cleanup model with a fixed input format and no instruction slot. Prompting it with a mode would push it off its training distribution, which the guardrails would then reject.

## Decision

1. **A mode picks a `Style` for the code around the LLM** (`flowd/modes.py`):
   - `default` and `email`: LLM cleanup and the sentence rules, unchanged.
   - `chat`: the same, then a single final period is dropped ("..." and "?" are kept).
   - `code`: no LLM. `minimal_clean` removes fillers and applies `[replace]`; repeats, casing and symbols are kept, and the joiner adds no sentence punctuation.
2. **A terminal with no `[modes]` entry gets code mode**, and always pastes with Ctrl+Shift+V (spec 7.3, 5.7).
3. **App ids match case-insensitively.** Hyprland reports `Slack`, Sway reports `slack`.
4. **The focused app is read once, at session start** (spec 9.4). Switching windows mid-dictation does not change the mode or the paste key.
5. **Defaults cover common Linux ids:** VS Code and forks, Zed, JetBrains and Neovide → code; Slack, Discord, Vesktop, Telegram, Signal, Element and WhatsApp → chat; Thunderbird, Evolution and Geary → email.

## Consequences

- Email and default read the same. A real "formal" register would need a model that takes instructions, and that belongs to the optional full-rewrite mode (spec 6.6).
- Code mode is faster, with no model round trip, but a spoken "open paren" stays as words. Symbol dictation would be a separate feature.
- Browsers report one id for every site, so Gmail in a browser gets default mode.
