# Eleanor Memory — Backup & Restore

This repo contains everything needed to restore Eleanor (your personal AI assistant) on a new machine.

## What's Inside

```
eleanor-memory/
├── README.md              ← This file
├── setup/
│   └── restore.sh         ← One-command restore script
│   └── restore.env         ← TEMPLATE (fill in your keys)
├── config/
│   ├── .env               ← API keys (RESTORED SEPARATELY — NOT in git)
│   ├── config.yaml        ← Hermes Agent configuration
│   └── SOUL.md            ← Eleanor's personality
├── memories/
│   └── USER.md            ← Your preferences & identity
├── skills/
│   ├── plane_manager/     ← Plane project management skill
│   └── whisper/           ← Audio transcription skill
├── scripts/
│   └── plane_brief.py     ← Daily morning brief
└── cron/
    └── plane_brief.json   ← Cron job definition
```

## Quick Restore (on a new machine)

```bash
# 1. Clone this repo
git clone https://github.com/wilrona/eleanor-memory.git ~/eleanor-memory

# 2. Copy your .env file (with real API keys)
#    Option A: from old machine
scp oldserver:~/.hermes/.env ~/eleanor-memory/config/.env
#    Option B: manually create from the template
cp ~/eleanor-memory/setup/restore.env.template ~/eleanor-memory/config/.env
#    Then edit config/.env and fill in your real keys

# 3. Run the restore script
cd ~/eleanor-memory && bash setup/restore.sh

# 4. Restart Hermes Agent
hermes
```

## What Gets Restored

- ✅ All API keys (`.env` — restored separately for security)
- ✅ Eleanor's identity (Wilrona / Eleanor)
- ✅ Preferences (MiniMax-M2.7 for everything)
- ✅ Plane projects & tasks skill
- ✅ Whisper transcription
- ✅ Daily morning brief cron job
- ✅ All skills & configurations

## API Keys Needed

Before restoring, make sure you have these keys (see `setup/restore.env.template`):

| Service | Key | Where to get |
|---|---|---|
| MiniMax | `MINIMAX_API_KEY` | https://www.minimax.io |
| Telegram | `TELEGRAM_BOT_TOKEN` | @BotFather |
| Plane | `PLANE_API_KEY` | https://plane.ndironalds.org |
| GitHub | `GITHUB_TOKEN` | https://github.com/settings/tokens |

## Security

This repo is **public** by default. The `.env` file with real API keys is **NOT** committed
(gitignored). You must restore it separately from your old machine or manually.

For a fully automatic restore, either:
- Make this repo **private** and commit `.env` (safe if repo is private)
- Use `scp` to transfer `.env` from old machine to new machine
