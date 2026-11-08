#!/usr/bin/env bash
# One-time setup for the birthday video repo (macOS or Linux; on Windows use WSL).
#   ./setup.sh              ffmpeg, node, Python env with faster-whisper, git-lfs, checks
#   ./setup.sh --video-use  also installs browser-use's video-use skill (needs an ElevenLabs key)
set -euo pipefail
cd "$(dirname "$0")"
say() { printf "\n==> %s\n" "$1"; }

say "System tools"
if [[ "$(uname)" == "Darwin" ]]; then
  command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
  for f in ffmpeg node git-lfs python@3.12; do
    brew list "$f" >/dev/null 2>&1 || brew install "$f"
  done
  PY="$(brew --prefix)/bin/python3.12"
elif command -v apt-get >/dev/null; then
  sudo apt-get update -y
  sudo apt-get install -y ffmpeg nodejs npm git-lfs python3-venv python3-pip fonts-dejavu
  PY=python3
else
  echo "Install ffmpeg, node 18+, python 3.10+ and git-lfs yourself, then re-run."; PY=python3
fi
git lfs install >/dev/null 2>&1 || true

say "Folders"
mkdir -p raw reference photos music brand brief plan work output

say "Python environment (.venv) with faster-whisper for free local transcription"
[[ -d .venv ]] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q faster-whisper

say "Remotion agent skills (already in .claude/skills; refreshing)"
npx -y skills update -p -y >/dev/null 2>&1 || echo "   (skills update skipped; the bundled copies still work)"

if [[ "${1:-}" == "--video-use" ]]; then
  say "video-use (browser-use) as a project skill"
  [[ -d vendor/video-use ]] || git clone --depth 1 https://github.com/browser-use/video-use vendor/video-use
  [[ -d vendor/video-use/.venv ]] || "$PY" -m venv vendor/video-use/.venv
  vendor/video-use/.venv/bin/pip install -q -e vendor/video-use
  mkdir -p .claude/skills
  ln -sfn ../../vendor/video-use .claude/skills/video-use
  if [[ ! -f .env ]] || ! grep -q ELEVENLABS_API_KEY .env; then
    echo "ELEVENLABS_API_KEY=" >> .env
    echo "   Put your key from https://elevenlabs.io/app/settings/api-keys into .env"
  fi
fi

say "Check"
.venv/bin/python scripts/vkit.py doctor || true
echo
echo "Next: drop clips into raw/, photos into photos/, music into music/, fill brief/,"
echo "then run:  claude   and paste the master prompt from PROMPT.md"
