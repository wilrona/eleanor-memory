#!/bin/bash
# Eleanor Auto-Save — runs after each session where improvements were made
# This runs automatically via cron, but can also be called manually
# Usage: bash eleanor-save.sh [optional commit message]

ELEANOR_DIR="$HOME/.hermes"
MSG="${1:-Auto-save after session}"

cd "$HOME/eleanor-memory"

# Sync from live config (use absolute paths to work from any CWD)
cp /root/.hermes/config.yaml config/config.yaml
cp /root/.hermes/SOUL.md config/SOUL.md
cp /root/.hermes/memories/USER.md memories/USER.md
cp /root/.hermes/memories/MEMORY.md memories/MEMORY.md
cp /root/.hermes/scripts/plane_brief.py scripts/ 2>/dev/null || true
cp /root/.hermes/scripts/secretary.py scripts/ 2>/dev/null || true
cp /root/.hermes/scripts/schema.sql scripts/ 2>/dev/null || true
cp -r /root/.hermes/skills/plane_manager/ skills/ 2>/dev/null || true
cp -r /root/.hermes/skills/whisper/ skills/ 2>/dev/null || true
cp /root/.hermes/cron/jobs.json cron/plane_brief.json 2>/dev/null || true

# Commit & push
git add -A
if git diff --staged --quiet; then
    echo "No changes to save."
else
    git commit -m "$MSG"
    git push origin master
    echo "✅ Saved to eleanor-memory"
fi
