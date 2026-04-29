#!/bin/bash
# Eleanor Restore Script — run on a fresh machine to restore everything
# Usage: bash restore.sh
set -e

ELEANOR_DIR="$HOME/.hermes"
BACKUP_DIR="$HOME/eleanor-memory"

echo "🧠 Eleanor Restore — starting..."

# Check for .env
if [ ! -f "$BACKUP_DIR/config/.env" ]; then
    echo "⚠️  config/.env not found!"
    echo "   Copy setup/restore.env.template to config/.env and fill in your keys."
    echo "   Or transfer from your old machine: scp oldserver:~/.hermes/.env $BACKUP_DIR/config/.env"
    exit 1
fi

# 1. Copy config files
echo "📁 Copying config files..."
mkdir -p "$ELEANOR_DIR"
cp "$BACKUP_DIR/config/.env" "$ELEANOR_DIR/.env"
cp "$BACKUP_DIR/config/config.yaml" "$ELEANOR_DIR/config.yaml"
cp "$BACKUP_DIR/config/SOUL.md" "$ELEANOR_DIR/SOUL.md"

# 2. Copy memories
echo "💾 Copying memories..."
mkdir -p "$ELEANOR_DIR/memories"
cp "$BACKUP_DIR/memories/USER.md" "$ELEANOR_DIR/memories/USER.md"

# 3. Copy skills
echo "🛠️ Installing skills..."
mkdir -p "$ELEANOR_DIR/skills"
cp -r "$BACKUP_DIR/skills/plane_manager" "$ELEANOR_DIR/skills/plane_manager"
cp -r "$BACKUP_DIR/skills/whisper" "$ELEANOR_DIR/skills/whisper"

# 4. Copy scripts
echo "📜 Copying scripts..."
mkdir -p "$ELEANOR_DIR/scripts"
cp "$BACKUP_DIR/scripts/plane_brief.py" "$ELEANOR_DIR/scripts/plane_brief.py"

# 5. Restore cron jobs
echo "⏰ Restoring cron jobs..."
mkdir -p "$ELEANOR_DIR/cron"
cp "$BACKUP_DIR/cron/plane_brief.json" "$ELEANOR_DIR/cron/jobs.json"

# 6. Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install openai-whisper --quiet 2>/dev/null || true

echo ""
echo "✅ Eleanor restored successfully!"
echo "   Restart Hermes Agent: hermes"
echo ""
echo "📋 Next steps:"
echo "   1. Check config/.env has the right API keys"
echo "   2. Run: hermes"
echo "   3. Say hi to Eleanor! 👋"
