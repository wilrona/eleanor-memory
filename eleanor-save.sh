#!/bin/bash
# Eleanor Auto-Save — runs after each session where improvements were made
# This runs automatically via cron, but can also be called manually
# Usage: bash eleanor-save.sh [optional commit message]

BACKUP_DIR="$HOME/eleanor-memory"
ELEANOR_DIR="$HOME/.hermes"
MSG="${1:-Auto-save after session}"

cd "$BACKUP_DIR"

# Sync from live config
cp "$ELEANOR_DIR/config/config.yaml" config/config.yaml
cp "$ELEANOR_DIR/SOUL.md" config/SOUL.md
cp "$ELEANOR_DIR/memories/USER.md" memories/USER.md
cp "$ELEANOR_DIR/scripts/plane_brief.py" scripts/ 2>/dev/null || true
cp -r "$ELEANOR_DIR/skills/plane_manager/" skills/ 2>/dev/null || true
cp -r "$ELEANOR_DIR/skills/whisper/" skills/ 2>/dev/null || true
cp "$ELEANOR_DIR/cron/jobs.json" cron/plane_brief.json 2>/dev/null || true

# Commit & push
git add -A
if git diff --staged --quiet; then
    echo "No changes to save."
else
    git commit -m "$MSG"
    git push origin master
    echo "✅ Saved to eleanor-memory"
fi
