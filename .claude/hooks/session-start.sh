#!/bin/bash
# ReelMagic SessionStart hook — prepares a fresh Claude Code on the web container
# so tests, the pipeline CLI, and the app all run immediately.
#
# Synchronous (no async line): guarantees deps are ready before the session
# starts. Idempotent + non-interactive. Web-only.
set -euo pipefail

# Only run in the remote (web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR"

echo "[reelmagic hook] preparing environment…"

# 1. System deps: ffmpeg (render), libsndfile (librosa), fonts (overlays).
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[reelmagic hook] installing ffmpeg + libsndfile…"
  SUDO=""; command -v sudo >/dev/null 2>&1 && SUDO="sudo"
  $SUDO apt-get update -y >/dev/null 2>&1 || true
  $SUDO apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 fonts-dejavu-core >/dev/null 2>&1 || \
    echo "[reelmagic hook] WARN: could not apt-get ffmpeg; render/tests may fail"
fi

# 2. Python venv + backend deps (pip install benefits from container caching).
if [ ! -d ".venv" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 .venv
  else
    python3 -m venv .venv
  fi
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip >/dev/null 2>&1 || true
pip install --quiet -r backend/requirements.txt

# 3. Bundled music + precomputed beat maps (deterministic; WAVs aren't committed).
if [ -z "$(ls backend/assets/music/*.wav 2>/dev/null)" ]; then
  echo "[reelmagic hook] generating bundled music…"
  (cd backend && python scripts/generate_music.py >/dev/null && python scripts/build_beatmaps.py >/dev/null)
fi

# 4. Frontend deps (optional; skip silently if npm is unavailable).
if command -v npm >/dev/null 2>&1 && [ -f frontend/package.json ]; then
  (cd frontend && npm install --silent >/dev/null 2>&1) || \
    echo "[reelmagic hook] WARN: npm install failed; frontend may need manual install"
fi

# 5. Persist the venv on PATH for the rest of the session.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

echo "[reelmagic hook] ready ✅"
