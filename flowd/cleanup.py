"""llama-server client for the cleanup pass (spec 5.5, ADR 0006).

Sotto is a base-model fine-tune with its own completion format, so this calls
`/completion` rather than the spec's chat endpoint (ADR 0006). Every failure
returns a `CleanupResult` with `text=None`; the daemon falls back to
`basic_clean`, so nothing here ever raises into a dictation.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any

import httpx

from flowd.config import Llm

log = logging.getLogger(__name__)

#: Sotto's training format (ADR 0006). The `### ` stop ends the answer before
#: the model invents a next example; a blank line ends it before a second one.
PROMPT_TEMPLATE = "### Input:\n{raw}\n\n### Output:\n"
_STOP = ("###", "\n\n")
#: ADR 0006's screen used these; 1.05 stops the rare echo loop at temperature 0.
_REPEAT_PENALTY = 1.05
#: spec 5.5: "max_tokens = ceil(1.5 x raw tokens) + 16". The factor is config;
#: the constant headroom is the spec's formula, not a tunable.
_MAX_TOKENS_HEADROOM = 16
#: Upper bound on what PROMPT_TEMPLATE adds around the raw text; it tokenizes
#: to under ten tokens with LFM's tokenizer, so this over-reserves slightly.
_PROMPT_OVERHEAD_TOKENS = 16


@dataclass(frozen=True, slots=True)
class CleanupResult:
    """`text` is the model's output, or None with `error` saying why not."""

    text: str | None
    error: str | None = None


class CleanupClient:
    """One cleanup request at a time, with spec 5.5's up/down tracking.

    `down` flips after `down_after_failures` consecutive connection or server
    errors and flips back on the first healthy probe. A timeout is not a
    failure: it says this input was too long for the budget, not that the
    server is gone.
    """

    def __init__(self, cfg: Llm, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.cfg = cfg
        self._client = httpx.AsyncClient(base_url=cfg.url, transport=transport)
        self._failures = 0
        self.down = False

    async def aclose(self) -> None:
        await self._client.aclose()

    def max_tokens(self, raw_tokens: int) -> int:
        return math.ceil(self.cfg.max_tokens_factor * raw_tokens) + _MAX_TOKENS_HEADROOM

    async def clean(self, raw: str, timeout_ms: int) -> CleanupResult:
        """Rewrite `raw`, or say why not, within `timeout_ms` in total."""
        if self.down:
            return CleanupResult(None, "down")
        try:
            # One budget for both calls: the user is waiting on the sum.
            async with asyncio.timeout(timeout_ms / 1000):
                tokenized = await self._post("/tokenize", {"content": raw})
                n_tokens = len(tokenized["tokens"])
                n_predict = self.max_tokens(n_tokens)
                if n_tokens + _PROMPT_OVERHEAD_TOKENS + n_predict > self.cfg.context_tokens:
                    # The server would cut the answer off mid-sentence; that is
                    # the text, not the server, so it is not a failure either.
                    return CleanupResult(None, "too long")
                reply = await self._post(
                    "/completion",
                    {
                        "prompt": PROMPT_TEMPLATE.format(raw=raw),
                        "n_predict": n_predict,
                        "temperature": 0,
                        "repeat_penalty": _REPEAT_PENALTY,
                        "stop": list(_STOP),
                        "cache_prompt": True,
                    },
                )
        except TimeoutError:
            return CleanupResult(None, "timeout")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            self._record_failure(exc)
            return CleanupResult(None, f"error: {type(exc).__name__}")
        self._failures = 0
        content = reply.get("content")
        if not isinstance(content, str):
            return CleanupResult(None, "error: no content")
        return CleanupResult(content.strip())

    async def check_health(self) -> bool:
        """Probe `GET /health` (spec 5.5); updates `down` and returns whether up."""
        try:
            async with asyncio.timeout(self.cfg.timeout_ms / 1000):
                response = await self._client.get("/health")
                response.raise_for_status()
        except (TimeoutError, httpx.HTTPError) as exc:
            self._record_failure(exc)
            return False
        if self.down:
            log.info("cleanup LLM is back at %s", self.cfg.url)
        self._failures = 0
        self.down = False
        return True

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(path, json=body)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a JSON object")
        return data

    def _record_failure(self, exc: BaseException) -> None:
        self._failures += 1
        if not self.down and self._failures >= self.cfg.down_after_failures:
            self.down = True
            log.warning("cleanup LLM marked down after %d failures: %s", self._failures, exc)
