#!/usr/bin/env bash
# One-time setup for offline speech-to-text (used to cut the edit to the narration).
# Installs sherpa-onnx and downloads Silero VAD + Whisper base.en from the official
# k2-fsa/sherpa-onnx GitHub releases into tools/models/ (git-ignored).
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL=${WHISPER_MODEL:-base.en}
DEST=tools/models
REL=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models
mkdir -p "$DEST"
python3 -c "import sherpa_onnx" 2>/dev/null || pip install sherpa-onnx
[ -f "$DEST/silero_vad.onnx" ] || curl -fL --retry 3 -o "$DEST/silero_vad.onnx" "$REL/silero_vad.onnx"
if [ ! -d "$DEST/sherpa-onnx-whisper-$MODEL" ]; then
  curl -fL --retry 3 "$REL/sherpa-onnx-whisper-$MODEL.tar.bz2" | tar -xj -C "$DEST"
fi
ls -1 "$DEST" "$DEST/sherpa-onnx-whisper-$MODEL"
