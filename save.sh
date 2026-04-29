#!/bin/bash
# Eleanor Save Script — commit & push improvements to eleanor-memory
# Usage: bash save.sh [commit message]
set -e

BACKUP_DIR="$HOME/eleanor-memory"
ELEANOR_DIR="$HOME/.hermes"

cd "$BACKUP_DIR"

# Pull latest first
git pull --quiet origin master 2>/dev/null || true

# Sync from live config
cp "$ELEANOR_DIR/config/config.yaml" config/config.yaml
cp "$ELEANOR_DIR/SOUL.md" config/SOUL.md
cp "$ELEANOR_DIR/memories/USER.md" memories/USER.md
cp "$ELEANOR_DIR/scripts/plane_brief.py" scripts/ 2>/dev/null || true
cp -r "$ELEANOR_DIR/skills/plane_manager" skills/ 2>/dev/null || true
cp -r "$ELEANOR_DIR/skills/whisper" skills/ 2>/dev/null || true
cp "$ELEANOR_DIR/cron/jobs.json" cron/plane_brief.json 2>/dev/null || true

# Commit
MSG="${1:-Update Eleanor memory}"
git add -A
if git diff --staged --quiet; then
    echo "No changes to save."
else
    git commit -m "$MSG"
    git push origin master
    echo "✅ Saved to eleanor-memory: $MSG"
fi
