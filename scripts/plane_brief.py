#!/usr/bin/env python3.12
"""
Plane Morning Brief — génère un brief quotidien pour Telegram.
Run: python3.12 ~/.hermes/scripts/plane_brief.py
"""
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/root/.hermes/skills")

from plane_manager.scripts import (
    ensure_project, list_tasks,
)

# ── Config ────────────────────────────────────────────────
PROJECTS = [
    ("PERSO", "Vie Perso"),
    ("PRO",   "Vie Pro"),
    ("SIDE",  "Side Projects"),
]

NOW      = datetime.now(timezone(timedelta(hours=1)))  # UTC+1 = Douala
TODAY_S  = NOW.strftime("%Y-%m-%d")
MOIS = ["janvier","février","mars","avril","mai","juin",
        "juillet","août","septembre","octobre","novembre","décembre"]
TODAY_D = f"{NOW.day} {MOIS[NOW.month-1]} {NOW.year}"

# ── Helpers ───────────────────────────────────────────────
def priority_score(t):
    """Plus le score est élevé, plus la tâche est prioritaire."""
    score = 0
    labels = [l.lower() for l in t.get("labels", [])]
    state  = t.get("state", "")

    if any("urgent" in l for l in labels):
        score += 30
    if "important" in labels:
        score += 15
    if "santé" in labels or "sante" in labels:
        score += 20
    if state == "In Progress":
        score += 25
    td = t.get("target_date")
    if td and td < TODAY_S and state not in ("Done", "Cancelled"):
        score += 40
    return score

def fmt_task(t, prefix="  •"):
    """Formate une tâche en une ligne avec estimate et drapeaux."""
    name    = t["name"]
    labels  = t.get("labels", [])
    td      = t.get("target_date", "")
    state   = t.get("state", "")
    est     = t.get("estimate")
    is_ov   = td and td < TODAY_S and state not in ("Done", "Cancelled")

    flags = []
    if is_ov:
        flags.append("🔴 EN RETARD")
    if any("urgent" in l for l in labels):
        flags.append("⚡ urgent")
    if "important" in labels:
        flags.append("⭐")

    est_str = f" [{est:.0f}h]" if est else ""
    flag_str = " — " + " ".join(flags) if flags else ""

    return f"{prefix}{est_str} {name}{flag_str}"

# ── Collecte ──────────────────────────────────────────────
seen_ids   = set()
all_todo    = []
all_inprog  = []
all_overdue = []
project_tasks = {}  # proj_key -> {todo:[], in_prog:[], overdue:[]}
total_est_h = 0.0

for proj_key, proj_label in PROJECTS:
    pid = ensure_project(proj_key)
    tasks = list_tasks(project_id=pid, limit=200)

    todo_q, in_prog_q, overdue_q = [], [], []

    for t in tasks:
        tid = t.get("id")
        if tid in seen_ids:
            continue
        state = t.get("state", "")
        td    = t.get("target_date", "")
        is_ov = td and td < TODAY_S and state not in ("Done", "Cancelled")
        est   = t.get("estimate") or 0

        if is_ov:
            overdue_q.append(t)
            seen_ids.add(tid)
        elif state == "In Progress":
            in_prog_q.append(t)
            seen_ids.add(tid)
        elif state in ("Todo", "Backlog"):
            todo_q.append(t)
            seen_ids.add(tid)

        # Add estimate to total if not done
        if state not in ("Done", "Cancelled") and est:
            total_est_h += est

    all_todo.extend(todo_q)
    all_inprog.extend(in_prog_q)
    all_overdue.extend(overdue_q)
    project_tasks[proj_key] = {
        "todo": todo_q, "in_prog": in_prog_q, "overdue": overdue_q
    }

# ── Priorisation ────────────────────────────────────────────
all_action = sorted(all_todo + all_inprog, key=priority_score, reverse=True)
top3 = all_action[:3]

# ── Analyse ─────────────────────────────────────────────────
SURCHAGE_H = 6.0
surcharge      = total_est_h > SURCHAGE_H
retard_critique = any(
    o.get("target_date", "") < (NOW - timedelta(days=2)).strftime("%Y-%m-%d")
    for o in all_overdue
)

# ── Rédaction ─────────────────────────────────────────────
lines = []

lines.append(f"🌅 Bonjour Wilrona — {TODAY_D}")
lines.append("")

# Projets
has_tasks = any(
    pt["todo"] or pt["in_prog"] or pt["overdue"]
    for pt in project_tasks.values()
)

if has_tasks:
    for proj_key, proj_label in PROJECTS:
        pt = project_tasks.get(proj_key, {})
        todo    = pt.get("todo", [])
        in_prog = pt.get("in_prog", [])
        overdue = pt.get("overdue", [])

        if not todo and not in_prog and not overdue:
            continue

        lines.append(f"📁 {proj_label}")
        for t in in_prog:
            lines.append(fmt_task(t, "  ⏳"))
        for t in todo:
            lines.append(fmt_task(t, "  📋"))
        for t in overdue:
            lines.append(fmt_task(t, "  🔴"))
        lines.append("")
else:
    lines.append("📭 Aucun tâche prévue aujourd'hui.")
    lines.append("")

# Retards
if all_overdue:
    lines.append(f"🔴 EN RETARD — {len(all_overdue)} tâche(s)")
    for t in all_overdue[:5]:
        lines.append(fmt_task(t))
    lines.append("")

# Charge estimée
if total_est_h > 0:
    filled = min(int(total_est_h), int(SURCHAGE_H))
    bar = "🟢" * filled + "⚪" * max(0, int(SURCHAGE_H) - filled)
    surcharge_alert = " ⚠️ SURCHARGE" if surcharge else ""
    lines.append(f"📊 Charge estimée : {total_est_h:.1f}h / {int(SURCHAGE_H)}h  {bar}{surcharge_alert}")
    lines.append("")

# Top 3
if top3:
    lines.append("🎯 3 PRIORITÉS DU JOUR")
    for i, t in enumerate(top3, 1):
        lines.append(f"  {i}. {fmt_task(t)}")
    lines.append("")

# Alertes
if surcharge:
    lines.append("⚠️ Surcharge détectée (plus de 6h estimées).")
    lines.append("   Delegue les tâches non critiques à demain si possible.")

if retard_critique:
    lines.append("🚨 Tu as des tâches en retard de plus de 2 jours. Agis en priorité.")

# Encouragement
if not has_tasks and not all_overdue:
    lines.append("💬 Profite de ta journée, rien ne t'attend !")
elif surcharge or all_overdue:
    lines.append("💪 Chaque petite avancée compte. Go.")
else:
    lines.append("💪 Belle journée. Une tâche à la fois.")

print("\n".join(lines))
