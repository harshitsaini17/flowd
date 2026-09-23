#!/usr/bin/env bash
# Smoke test: prove llama-server can clean up dictated speech.
#
# Starts a throwaway llama-server on a non-default port, sends one cleanup
# prompt, prints the result, and stops the server on exit.
set -euo pipefail

MODEL="${FLOWD_MODEL:-${XDG_DATA_HOME:-$HOME/.local/share}/flowd/models/sotto-cleanup-lfm25-350m-q4_k_m.gguf}"
PORT="${FLOWD_SMOKE_PORT:-8177}"
LOG=/tmp/flowd-smoke-llm.log

# Physical cores minus two, leaving headroom for the STT worker and the desktop.
# Each physical core appears once per SMT sibling in this listing, so the pairs
# are deduplicated before counting -- without that this reads 12 on a 6-core CPU.
PHYSICAL_CORES="$(lscpu -p=Core,Socket | grep -v '^#' | sort -u | wc -l)"
THREADS=$(( PHYSICAL_CORES - 2 ))
(( THREADS < 1 )) && THREADS=1

[[ -f "$MODEL" ]] || { echo "Model missing at $MODEL. Run scripts/fetch_models.sh first." >&2; exit 1; }
command -v llama-server >/dev/null || { echo "llama-server not found (pacman -S llama-cpp)." >&2; exit 1; }

echo "==> Starting llama-server on 127.0.0.1:$PORT with -t $THREADS ($PHYSICAL_CORES physical cores)"
llama-server -m "$MODEL" -c 1024 -np 1 -b 128 -ub 128 -cram 0 \
  --host 127.0.0.1 --port "$PORT" -t "$THREADS" \
  >"$LOG" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "llama-server exited during startup. Log:" >&2
    tail -20 "$LOG" >&2
    exit 1
  fi
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done

curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 || {
  echo "llama-server did not become healthy within 60s. Log:" >&2
  tail -20 "$LOG" >&2
  exit 1
}

echo "==> Sending a cleanup prompt"
# Sotto is a base-model fine-tune, not a chat model: it takes the `### Input:` /
# `### Output:` completion format from its model card, at temperature 0 with a
# 1.05 repeat penalty, through `/completion` rather than the chat endpoint
# (ADR 0006). The `<new></new>` finding was on the general 350M chat model,
# not on Sotto.
curl -fsS "http://127.0.0.1:$PORT/completion" \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "### Input:\nso um i think we should uh probably ship it on monday\n\n### Output:\n",
    "temperature": 0,
    "repeat_penalty": 1.05,
    "n_predict": 64,
    "stop": ["###", "\n\n"]
  }' | python3 -c '
import json, re, sys

text = json.load(sys.stdin)["content"].strip()
print("RESULT:", text)

# A 200 from the server is not a passing smoke test: the point is that the model
# followed the instruction. Without these checks the script reports success on a
# reply that kept every filler, or answered in the wrong language.
padded = f" {text.lower()} "
problems = [f"filler {f.strip()!r} survived" for f in (" um ", " uh ") if f in padded]
if not (re.search(r"\bship\b", padded) and re.search(r"\bmonday\b", padded)):
    problems.append("meaning not preserved: expected \"ship\" and \"monday\"")

if problems:
    print("SMOKE TEST FAILED: " + "; ".join(problems), file=sys.stderr)
    raise SystemExit(1)
'

echo "==> Smoke test passed. Server log: $LOG"
