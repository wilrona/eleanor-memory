---
name: plane-manager
description: "Gère les projets et tâches Plane (https://plane.ndironalds.org) — lecture, écriture, analyse."
version: 1.0.0
author: Eleanor (assistant personnel de Wilrona)
license: MIT
platform: local
tools: terminal, file, delegation
---

# Plane Manager — SKILL.md

Gère les projets et tâches Plane pour Wilrona via l'API REST.

## Setup

### Credentials

Récupérés automatiquement depuis `~/.hermes/.env` :
- `PLANE_API_KEY` → `X-API-Key` header
- `PLANE_BASE_URL` → `https://plane.ndironalds.org`
- `PLANE_WORKSPACE_SLUG` → `aligodu`

### Structure Python

```
~/.hermes/skills/plane_manager/scripts/
├── client.py     # Connexion API + cache UUIDs + gestion erreurs
├── projects.py   # Projets : liste, résumé, sync cache
├── tasks.py      # Work items : CRUD, states, labels, commentaires
├── analysis.py   # Analyse : vélocité, retards, ré规划
└── __init__.py   # Exports publics
```

### Import

```python
import sys
sys.path.insert(0, "/root/.hermes/skills")
from plane_manager.scripts import (
    # Projets
    list_projects, get_project_summary, ensure_project,
    # Tâches
    create_task, get_task, update_task, delete_task,
    set_task_state, add_comment,
    list_tasks,
    # Analyse
    get_velocity_report, get_overdue_tasks,
)
```

## Projets

### list_projects() → list[dict]

Liste tous les projets du workspace.

```python
projects = list_projects()
for p in projects:
    print(f"{p['name']} ({p['identifier']}) — {p['task_count']} tâches")
```

### get_project_summary(name_or_id: str) → dict

Résumé complet d'un projet.

```python
summary = get_project_summary("PERSO")
print(summary)
# {'id': '...', 'name': 'Vie Perso', 'identifier': 'PERSO',
#  'task_count': 12, 'state_summary': {'Todo': 5, 'In Progress': 3, 'Done': 4},
#  'tasks_by_label': {'urgent-perso': 2, 'santé': 1, ...}}
```

### ensure_project(name_or_id: str) → str

Résout un nom, identifiant ou UUID de projet en UUID.

```python
pid = ensure_project("PERSO")  # → '6397e2aa-e104-4635-915c-05fb04e9b75e'
```

## Tâches

**Règle importante** : `project_id` est obligatoire pour toutes les opérations sur les tâches
(CRUD, états, labels, commentaires). Utiliser `ensure_project("NOM")` pour résoudre.

### create_task(name, project_id, state=None, priority=None, labels=None, target_date=None, description=None) → dict

```python
pid = ensure_project("PERSO")

task = create_task(
    name="RDV médecin généraliste",
    project_id=pid,          # ou "PERSO" (sera résolu)
    state="Todo",            # optionnel, défaut = premier état du projet
    priority="urgent",       # urgent | high | medium | low | none
    labels=["santé", "urgent-perso"],
    target_date="2026-05-05",
    description="Check-up annuel",
)
# → {'id': '...', 'name': 'RDV médecin généraliste', 'state': 'Todo', ...}
```

### get_task(task_id, project_id) → dict

Détail complet avec sous-tâches et commentaires.

```python
detail = get_task(task_id, project_id=pid)
print(f"Sous-tâches: {len(detail['sub_items'])}")
print(f"Commentaires: {len(detail['comments'])}")
```

### list_tasks(project_id, state=None, priority=None, label=None, assignee=None, target_date_from=None, target_date_to=None, limit=100) → list[dict]

```python
# Toutes les tâches PERSO
all_perso = list_tasks(project_id="PERSO")

# Filtrées
urgent = list_tasks(project_id="PERSO", state="Todo", priority="urgent")
sante = list_tasks(project_id="PERSO", label="santé")
this_week = list_tasks(project_id="PERSO", target_date_to="2026-05-08")
```

### set_task_state(task_id, state_name, project_id) → dict

```python
done = set_task_state(task_id, "Done", pid)
```

### add_comment(task_id, text, project_id) → dict

```python
comment = add_comment(task_id, "Fait ! Merci Eleanor", pid)
```

### delete_task(task_id, project_id)

```python
delete_task(task_id, pid)
```

## Labels disponibles (identifiants Plane)

| Label | Description |
|-------|-------------|
| `urgent-perso` | Urgent perso |
| `urgent-pro` | Urgent pro |
| `important` | Important |
| `routine` | Routine / quotidien |
| `deep-work` | Travail profond |
| `social` | Social / amis |
| `maison` | Maison / intérieur |
| `sortie` | Sortie / extérieur |
| `dev` | Développement |
| `client` | Client / relation client |
| `finance` | Finance / argent |
| `apprentissage` | Apprentissage |
| `santé` | Santé / bien-être |

## États disponibles

Dépendent du projet — typiquement : `Backlog`, `Todo`, `In Progress`, `Done`, `Cancelled`.

## Analyse

### get_velocity_report(project_id, days=30) → dict

Vélocité sur N jours : nombre de tâchesDone vs créées.

```python
report = get_velocity_report(pid, days=30)
print(report)
# {'period_days': 30, 'tasks_created': 8, 'tasks_completed': 5,
#  'velocity': 5, 'completion_rate': 0.625}
```

### get_overdue_tasks(project_id) → list[dict]

Tâches en retard (target_date dépassée, non terminées).

```python
overdue = get_overdue_tasks("PRO")
for t in overdue:
    print(f"[{t['priority']}] {t['name']} — dû {t['target_date']}")
```

## Erreurs

| Erreur | Cause |
|--------|-------|
| `PlaneAuthError` | Clé API invalide ou accès refusé |
| `PlaneNotFoundError` | Projet/tâche introuvable |
| `PlaneRateLimitError` | Trop de requêtes (429) |
| `PlaneServerError` | Erreur serveur Plane (5xx) |
| `PlaneConnectionError` | Impossible de joindre Plane |

## Notes techniques

- **Endpoints Work Items** : Tous les write ops utilisent `projects/{pid}/work-items/{tid}/`
- **Cache UUIDs** : Les UUIDs de projets/states/labels sont cachés dans `cache.json`
- **Estimates** : Les endpoints estimates (`/estimates`, `/estimates-points`) retournent 404 sur cette instance — le champ `estimate_point` existe sur les work items mais pas de système de points configurable
- **Labels** : Retourne parfois des objets dicts, parfois des UUIDs — normalisé automatiquement
- **DELETE** : Retourne une réponse vide (204) → `{"success": true}`
