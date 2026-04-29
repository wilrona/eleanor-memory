#!/usr/bin/env python3
"""
SecretaryIA Local Engine
- Reads tasks from Plane API
- Enriches with local SQLite metadata
- Calculates 7-day load, detects conflicts
- Generates structured recap
"""

import sqlite3
import json
import os
import sys
import re
import math
from datetime import datetime, timedelta, date, time as dtime
from typing import Optional
import urllib.request
import urllib.error

# ─── Config ────────────────────────────────────────────────────────────────────

HOME = os.path.expanduser("~/.hermes")
DB_PATH = os.path.join(HOME, "secretary.db")
PLANE_BASE_URL = os.environ.get("PLANE_BASE_URL", "https://plane.ndironalds.org")
PLANE_API_KEY = os.environ.get("PLANE_API_KEY", "")
PLANE_WORKSPACE = os.environ.get("PLANE_WORKSPACE_SLUG", "aligodu")

# Develop folder base path
DEVELOP_BASE = os.path.join(HOME, "develop")

# ─── User Profile (Secretary Mode) ─────────────────────────────────────────────

PROFILE = {
    "work_start": 8,
    "work_end": 17,
    "weekend_start": 8,
    "weekend_end": 15,
    "weekend_enabled": True,
    "min_sleep_hours": 4,
    "min_daily_hours": 5,
    "max_weekly_hours": 40,
    "deep_work_start": 8,
    "deep_work_end": 12,
    "blocked_days": [],  # e.g. ["saturday", "sunday"] for non-negotiable rest
    "non_negotiable": ["sport", "famille", "vacances", "déplacement"],
    "priority_order": ["pro", "perso", "famille"],
    "task_types": ["DEV", "gestion", "test", "devops"],
    "autonomy_level": "hybrid",
}

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    schema_path = os.path.join(HOME, "scripts", "schema.sql")
    if os.path.exists(schema_path):
        with open(schema_path) as f:
            schema = f.read()
        conn = sqlite3.connect(DB_PATH)
        conn.executescript(schema)
        conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS task_metadata (
                id TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                task_type TEXT DEFAULT 'flexible',
                energy TEXT DEFAULT 'light',
                dependencies TEXT,
                override_deadline TEXT,
                override_duration REAL,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS daily_recap (
                date TEXT PRIMARY KEY,
                workspace TEXT NOT NULL,
                recap_text TEXT,
                total_hours REAL,
                conflicts_detected INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_preferences (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS workspace_config (
                workspace TEXT PRIMARY KEY,
                display_name TEXT,
                context TEXT,
                enabled INTEGER DEFAULT 1,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.close()
    print(f"[Secretary] DB initialized at {DB_PATH}")

def get_workspaces() -> list[dict]:
    """Return list of workspaces the user has access to."""
    return [
        {"slug": "aligodu", "display_name": "Vie Perso", "context": "perso", "enabled": True},
        {"slug": "ease", "display_name": "EASE", "context": "pro", "enabled": True},
        {"slug": "st-digital", "display_name": "ST Digital", "context": "pro", "enabled": True},
    ]

def get_metadata(task_id: str) -> Optional[dict]:
    """Get local metadata for a task."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM task_metadata WHERE id = ?", (task_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def set_metadata(task_id: str, workspace: str, **kwargs):
    """Upsert metadata for a task."""
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM task_metadata WHERE id = ?", (task_id,)
    ).fetchone()
    
    if existing:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        conn.execute(
            f"UPDATE task_metadata SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            list(kwargs.values()) + [task_id]
        )
    else:
        cols = ", ".join(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join(["?"] * len(vals))
        conn.execute(
            f"INSERT INTO task_metadata (id, workspace, {cols}) VALUES (?, ?, {placeholders})",
            [task_id, workspace] + vals
        )
    conn.commit()
    conn.close()

def get_task_metadata_map(task_ids: list[str]) -> dict[str, dict]:
    """Bulk fetch metadata for multiple tasks."""
    if not task_ids:
        return {}
    conn = get_db()
    placeholders = ", ".join(["?"] * len(task_ids))
    rows = conn.execute(
        f"SELECT * FROM task_metadata WHERE id IN ({placeholders})",
        task_ids
    ).fetchall()
    conn.close()
    return {row["id"]: dict(row) for row in rows}

# ─── Plane API ────────────────────────────────────────────────────────────────

def plane_get(endpoint: str) -> dict:
    """Make authenticated request to Plane API."""
    url = f"{PLANE_BASE_URL}/api/v1/{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("X-API-Key", PLANE_API_KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}


# ─── Estimation Engine ─────────────────────────────────────────────────────────

COMPLEXITY_KEYWORDS = {
    "prisma": 1.5, "database": 1.3, "migration": 1.4, "schema": 1.2,
    "api": 1.2, "rest": 1.1, "graphql": 1.4, "auth": 1.3, "jwt": 1.2,
    "landing": 0.8, "page": 0.7, "blog": 0.8, "portfolio": 0.9,
    "dashboard": 1.2, "admin": 1.1, "crm": 1.3, "analytics": 1.2,
    "docker": 1.3, "kubernetes": 1.6, "ci/cd": 1.3, "deploy": 1.2,
    "refonte": 1.4, "migration": 1.5, "legacy": 1.4, "refactor": 1.3,
    "architecture": 1.5, "microservices": 1.6, "integration": 1.2,
    "test": 1.1, "testing": 1.1, "unit test": 1.0, "e2e": 1.3,
    "fix": 0.9, "bug": 0.9, "hotfix": 0.8, "patch": 0.8,
    "setup": 1.0, "init": 0.9, "config": 0.9, "setup": 1.0,
    "email": 0.9, "mail": 0.9, "smtp": 1.1, "newsletter": 1.0,
    "pdf": 1.1, "export": 1.0, "import": 1.1, "csv": 1.0,
    "frontend": 1.0, "backend": 1.3, "fullstack": 1.2, "mobile": 1.3,
    "ai": 1.4, "ml": 1.5, "llm": 1.4, "openai": 1.3, "embedding": 1.3,
}

# Base duration estimates by task_type (in hours) — human baseline
BASE_DURATION = {
    "dev": 2.0,
    "devops": 2.5,
    "gestion": 1.0,
    "admin": 0.5,
    "test": 1.5,
    "flexible": 1.0,
}


def extract_project_pattern(title: str) -> str:
    """Extract the most relevant project pattern keyword from task title."""
    if not title:
        return "general"
    title_lower = title.lower()
    matches = []
    for keyword, factor in COMPLEXITY_KEYWORDS.items():
        # Use word boundary matching to avoid substring false positives
        # e.g., "ai" in "email", "pa" in "partner"
        import re
        if re.search(r'\b' + re.escape(keyword) + r'\b', title_lower):
            matches.append((keyword, factor, len(keyword)))
    if not matches:
        return "general"
    # Return the highest-impact keyword; tiebreak by longer keyword (more specific)
    matches.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return matches[0][0]


def get_type_bias(task_type: str, project_pattern: str) -> dict:
    """Get bias factor for a given task type and project pattern."""
    conn = get_db()
    row = conn.execute(
        "SELECT avg_ratio, sample_count FROM type_bias WHERE task_type = ? AND project_pattern = ?",
        (task_type.lower(), project_pattern.lower())
    ).fetchone()
    conn.close()
    if not row:
        return {"avg_ratio": 1.0, "sample_count": 0}
    return {"avg_ratio": row[0], "sample_count": row[1]}


def update_type_bias(task_type: str, project_pattern: str, ratio: float):
    """Update bias with a new sample (ratio = actual / user_accepted)."""
    conn = get_db()
    existing = conn.execute(
        "SELECT id, sample_count, total_ratio FROM type_bias WHERE task_type = ? AND project_pattern = ?",
        (task_type.lower(), project_pattern.lower())
    ).fetchone()

    if existing:
        sample_count = existing[1] + 1
        total_ratio = existing[2] + ratio
        avg_ratio = total_ratio / sample_count
        # Online variance update (Welford's algorithm simplified)
        old_avg = conn.execute(
            "SELECT avg_ratio FROM type_bias WHERE id = ?", (existing[0],)
        ).fetchone()[0]
        old_var = conn.execute(
            "SELECT std_dev FROM type_bias WHERE id = ?", (existing[0],)
        ).fetchone()[0]
        new_var = math.sqrt(((old_var ** 2 * (sample_count - 1)) + (ratio - old_avg) ** 2) / sample_count) if sample_count > 1 else 0.0
        conn.execute(
            """UPDATE type_bias SET sample_count = ?, total_ratio = ?, avg_ratio = ?, std_dev = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (sample_count, total_ratio, avg_ratio, new_var, existing[0])
        )
    else:
        conn.execute(
            """INSERT INTO type_bias (task_type, project_pattern, sample_count, total_ratio, avg_ratio, std_dev)
               VALUES (?, ?, 1, ?, ?, 0.0)""",
            (task_type.lower(), project_pattern.lower(), ratio, ratio)
        )
    conn.commit()
    conn.close()


# ─── Estimation functions ──────────────────────────────────────────────────────

def propose_estimation(task: dict) -> dict:
    """
    Propose a human-realistic estimation for a task.
    Returns: {
        "ia_proposed_h": float,        -- estimation IA de base
        "adjusted_h": float,           -- estimation ajustée avec biais historique
        "confidence": str,            -- 'low' / 'medium' / 'high'
        "pattern": str,               -- project pattern détecté
        "bias_ratio": float,          -- ratio de correction appliqué
        "reasoning": str,             -- explication courte
    }
    """
    title = task.get("title", "")
    task_type = (task.get("task_type") or task.get("type") or "flexible").lower()
    energy = (task.get("energy") or "light").lower()

    # Extract project pattern
    pattern = extract_project_pattern(title)

    # Get bias for this type+pattern
    bias = get_type_bias(task_type, pattern)
    bias_ratio = bias["avg_ratio"]
    sample_count = bias["sample_count"]

    # Base estimation from type
    base_h = BASE_DURATION.get(task_type, 1.0)

    # Complexity multiplier from pattern
    complexity_mult = COMPLEXITY_KEYWORDS.get(pattern, 1.0)

    # Energy multiplier
    energy_mult = 1.5 if energy == "intense" else 1.0

    # IA-proposed = base × complexity × energy
    ia_proposed_h = round(base_h * complexity_mult * energy_mult, 1)

    # Adjust with historical bias (if we have samples)
    if sample_count >= 3:
        adjusted_h = round(ia_proposed_h * bias_ratio, 1)
        confidence = "high" if sample_count >= 10 else "medium"
    else:
        adjusted_h = ia_proposed_h
        confidence = "low"

    # Clamp to reasonable bounds (15min - 40h)
    adjusted_h = max(0.25, min(40.0, adjusted_h))

    reasoning = []
    if sample_count >= 3:
        reasoning.append(f"Biais {pattern}/{task_type}: ×{bias_ratio:.2f} ({sample_count} samples)")
    else:
        reasoning.append(f"Pas d'historique {pattern}/{task_type} — estimation de base")
    if complexity_mult != 1.0:
        reasoning.append(f"Complexité '{pattern}': ×{complexity_mult}")
    if energy == "intense":
        reasoning.append("Énergie intense: ×1.5")

    return {
        "ia_proposed_h": ia_proposed_h,
        "adjusted_h": adjusted_h,
        "confidence": confidence,
        "pattern": pattern,
        "bias_ratio": bias_ratio,
        "reasoning": "; ".join(reasoning),
        "task_type": task_type,
        "energy": energy,
    }


def save_estimation(task_id: str, workspace: str, ia_proposed_h: float, user_accepted_h: float,
                    task_type: str, energy: str, title: str, project_name: str = None) -> dict:
    """
    Save a proposed + accepted estimation for a task.
    Called when user accepts or modifies the IA proposal.
    """
    conn = get_db()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO estimation_history
            (task_id, workspace, title, task_type, energy, ia_proposed_h, user_accepted_h, completed, project_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (task_id, workspace, title, task_type, energy, ia_proposed_h, user_accepted_h, project_name))
        conn.commit()
        return {"status": "saved", "task_id": task_id, "user_accepted_h": user_accepted_h}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def complete_task(task_id: str, actual_h: float) -> dict:
    """
    Record actual duration for a task and update bias.
    Called when user marks a task done and provides real duration.
    """
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT task_type, energy, ia_proposed_h, user_accepted_h, workspace, project_name FROM estimation_history WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if not row:
            return {"error": f"Task {task_id} not found in estimation_history — save estimation first with 'estimate' command"}

        task_type, energy, ia_proposed_h, user_accepted_h, workspace, project_name = row

        # Extract pattern from title (need title from task_metadata or estimation_history)
        title = conn.execute("SELECT title FROM estimation_history WHERE task_id = ?", (task_id,)).fetchone()[0]
        pattern = extract_project_pattern(title or "")

        # Calculate ratio: actual / user_accepted
        ratio = actual_h / user_accepted_h if user_accepted_h > 0 else 1.0

        # Update estimation_history with actual and completed
        conn.execute(
            """UPDATE estimation_history SET actual_h = ?, completed = 1, completed_at = CURRENT_TIMESTAMP,
               updated_at = CURRENT_TIMESTAMP WHERE task_id = ?""",
            (actual_h, task_id)
        )

        # Update type_bias with new sample
        update_type_bias(task_type or "flexible", pattern, ratio)

        conn.commit()

        # Return summary
        bias = get_type_bias(task_type or "flexible", pattern)
        diff_pct = (ratio - 1.0) * 100
        direction = "plus" if ratio > 1.0 else "moins"

        return {
            "status": "completed",
            "task_id": task_id,
            "actual_h": actual_h,
            "user_accepted_h": user_accepted_h,
            "ratio": round(ratio, 2),
            "bias_avg": round(bias["avg_ratio"], 2),
            "message": f"⏱ {actual_h}h réel vs {user_accepted_h}h accepté ({direction} {abs(diff_pct):.0f}%) — biais mis à jour"
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()


def get_pending_estimations() -> list:
    """Return all tasks that have an estimation saved but not completed."""
    conn = get_db()
    rows = conn.execute(
        "SELECT task_id, workspace, title, task_type, energy, ia_proposed_h, user_accepted_h FROM estimation_history WHERE completed = 0"
    ).fetchall()
    conn.close()
    return [
        {
            "task_id": r[0], "workspace": r[1], "title": r[2],
            "task_type": r[3], "energy": r[4],
            "ia_proposed_h": r[5], "user_accepted_h": r[6],
        }
        for r in rows
    ]


def plane_patch(endpoint: str, data: dict) -> dict:
    """Make authenticated PATCH request to Plane API."""
    url = f"{PLANE_BASE_URL}/api/v1/{endpoint}"
    req = urllib.request.Request(url, data=json.dumps(data).encode(), method="PATCH")
    req.add_header("X-API-Key", PLANE_API_KEY)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "detail": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}

def get_state_map(workspace_slug: str, project_id: str) -> dict:
    """Get state name -> id mapping for a project."""
    states_data = plane_get(f"workspaces/{workspace_slug}/projects/{project_id}/states/")
    state_map = {}
    for s in states_data.get("results", []):
        state_map[s["name"].lower()] = s["id"]
        state_map[s["group"].lower()] = s["id"]
    return state_map

def parse_secretary_block(description: str) -> dict:
    """
    Parse [Secretary] metadata block from task description.
    
    Format:
    [Secretary]
    type: deep
    energy: high
    estimation: 2h
    ---
    Description normale de la tâche ici...
    """
    result = {
        "task_type": None,
        "energy": None,
        "estimation": None,
    }
    
    if not description:
        return result
    
    # Look for [Secretary] block
    match = re.search(r'\[Secretary\](.*?)(?:---|$)', description, re.DOTALL | re.IGNORECASE)
    if not match:
        return result
    
    block = match.group(1)
    
    # Parse type
    type_match = re.search(r'type:\s*(\w+)', block, re.IGNORECASE)
    if type_match:
        result["task_type"] = type_match.group(1).lower()
    
    # Parse energy
    energy_match = re.search(r'energy:\s*(\w+)', block, re.IGNORECASE)
    if energy_match:
        result["energy"] = energy_match.group(1).lower()
    
    # Parse estimation (e.g., "2h", "30min", "1.5h")
    est_match = re.search(r'estimation:\s*([\d.,]+)\s*(h|hr|hrs|min|m)?', block, re.IGNORECASE)
    if est_match:
        value = float(est_match.group(1).replace(',', '.'))
        unit = (est_match.group(2) or 'h').lower()
        if unit.startswith('m'):
            value = value / 60  # Convert minutes to hours
        result["estimation"] = value
    
    return result


def parse_duration_string(duration_str: str) -> float:
    """Parse duration string like '2h', '30min', '1.5h' to hours."""
    if not duration_str:
        return 1.0
    match = re.search(r'([\d.,]+)\s*(h|hr|hrs|min|m)?', duration_str, re.IGNORECASE)
    if not match:
        return 1.0
    value = float(match.group(1).replace(',', '.'))
    unit = (match.group(2) or 'h').lower()
    if unit and unit[0] == 'm':
        return value / 60
    return value


def get_all_tasks_7_days(workspace_slug: str) -> list[dict]:
    """Fetch all tasks with due dates in the next 7 days from Plane."""
    today = date.today()
    end_date = today + timedelta(days=7)
    
    tasks = []
    
    # Get projects first
    projects_data = plane_get(f"workspaces/{workspace_slug}/projects/")
    if "error" in projects_data and projects_data.get("error") == "HTTP 403":
        return []
    
    projects = projects_data.get("results", [])
    
    for project in projects:
        project_id = project["id"]
        # Fetch work items - Plane uses work-items endpoint
        items_data = plane_get(f"workspaces/{workspace_slug}/projects/{project_id}/work-items/")
        
        if "error" in items_data:
            continue
            
        items = items_data.get("results", [])
        
        for item in items:
            # Get target date
            target_date = None
            if item.get("target_date"):
                try:
                    target_date = datetime.fromisoformat(
                        item["target_date"].replace("Z", "+00:00")
                    ).date()
                except:
                    pass
            
            # Skip if no target date or outside window
            if not target_date:
                continue
            if target_date < today or target_date > end_date:
                continue
            
            # Parse [Secretary] block from description
            description = item.get("description", "") or ""
            secretary_meta = parse_secretary_block(description)
            
            # Get duration: priority is [Secretary] estimation > Plane estimate_point > default 1h
            duration = secretary_meta.get("estimation")
            if not duration:
                estimate = item.get("estimate_point")
                if estimate:
                    duration = float(estimate) / 2  # Plane uses points, convert to hours
                else:
                    duration = 1.0
            
            # Get metadata from local DB (can override)
            meta = get_metadata(item["id"])
            if meta and meta.get("override_duration"):
                duration = meta["override_duration"]
            
            # Merge: DB metadata > [Secretary] block > defaults
            task_type = None
            energy = None
            
            if meta:
                task_type = meta.get("task_type")
                energy = meta.get("energy")
            
            if not task_type and secretary_meta.get("task_type"):
                task_type = secretary_meta["task_type"]
            if not task_type:
                task_type = "flexible"
                
            if not energy and secretary_meta.get("energy"):
                energy = secretary_meta["energy"]
            if not energy:
                energy = "light"
            
            tasks.append({
                "id": item["id"],
                "project_id": project_id,
                "project_name": project["name"],
                "workspace": workspace_slug,
                "title": item.get("name", "Untitled"),
                "description": description,
                "state": item.get("state_id"),
                "priority": item.get("priority", "none"),
                "target_date": target_date.isoformat(),
                "duration": duration,
                "task_type": task_type,
                "energy": energy,
                "assignee": item.get("assignee_names", ""),
                "url": f"{PLANE_BASE_URL}/{workspace_slug}/projects/{project_id}/work-items/{item['id']}",
            })
    
    return tasks


def get_backlog_tasks(workspace_slug: str) -> list[dict]:
    """Get all tasks in Backlog state with a target_date set."""
    today = date.today()
    
    tasks = []
    projects_data = plane_get(f"workspaces/{workspace_slug}/projects/")
    if "error" in projects_data and projects_data.get("error") == "HTTP 403":
        return []
    
    projects = projects_data.get("results", [])
    
    for project in projects:
        project_id = project["id"]
        # Get state map for this project
        state_map = get_state_map(workspace_slug, project_id)
        backlog_state_id = state_map.get("backlog")
        if not backlog_state_id:
            continue
        
        # Fetch work items in backlog state
        items_data = plane_get(
            f"workspaces/{workspace_slug}/projects/{project_id}/work-items/?state_id={backlog_state_id}"
        )
        if "error" in items_data:
            continue
        
        items = items_data.get("results", [])
        
        for item in items:
            target_date = None
            if item.get("target_date"):
                try:
                    target_date = datetime.fromisoformat(
                        item["target_date"].replace("Z", "+00:00")
                    ).date()
                except:
                    pass
            
            # Only include tasks with a target_date
            if not target_date:
                continue
            
            description = item.get("description", "") or ""
            secretary_meta = parse_secretary_block(description)
            
            duration = secretary_meta.get("estimation")
            if not duration:
                estimate = item.get("estimate_point")
                if estimate:
                    duration = float(estimate) / 2
                else:
                    duration = 1.0
            
            tasks.append({
                "id": item["id"],
                "project_id": project_id,
                "project_name": project["name"],
                "workspace": workspace_slug,
                "title": item.get("name", "Untitled"),
                "target_date": target_date.isoformat(),
                "target_date_obj": target_date,
                "duration": duration,
                "state_id": item.get("state_id"),
                "state_name": "Backlog",
                "priority": item.get("priority", "none"),
                "url": f"{PLANE_BASE_URL}/{workspace_slug}/projects/{project_id}/work-items/{item['id']}",
            })
    
    return tasks


def move_task_to_state(task_id: str, workspace_slug: str, project_id: str, target_state: str) -> dict:
    """
    Move a task to a different state.
    target_state: 'todo', 'in progress', 'done', 'backlog', 'cancelled'
    """
    state_map = get_state_map(workspace_slug, project_id)
    target_state_id = state_map.get(target_state.lower())
    
    if not target_state_id:
        return {"error": f"Unknown state: {target_state}. Available: {list(state_map.keys())}"}
    
    result = plane_patch(
        f"workspaces/{workspace_slug}/projects/{project_id}/work-items/{task_id}/",
        {"state": target_state_id}
    )
    
    if "error" in result:
        return result
    
    return {"success": True, "task_id": task_id, "new_state": target_state}


# ─── Scheduling Engine ─────────────────────────────────────────────────────────

# ── Configurable weights (from PROFILE, can be overridden per user) ──────────

DEFAULT_SCORE_WEIGHTS = {
    "deadline": 100,
    "priority": 30,
    "dependencies": 20,
    "project_urgency": 15,
}

DEFAULT_PLACEMENT_STRATEGY = "energy"  # energy | earliest | deadline | balanced
DEFAULT_BUFFER_AFTER_INTENSE = 15  # minutes

# ── Slot Status ───────────────────────────────────────────────────────────────

SLOT_STATUS = {
    "free": "libre",
    "locked": "verrouillé",
    "occupied": "occupé",
    "energy_high": "énergie_haute",
    "energy_low": "énergie_basse",
    "out_of_range": "hors_plage",
}


def build_canvas(start_day: date, horizon_days: int = 7) -> list[dict]:
    """
    Build a canvas of time slots over horizon_days starting from start_day.
    Each slot is 30 minutes. Slots are tagged with status and energy level.
    """
    canvas = []
    SLOT_DURATION_MINUTES = 30

    for day_offset in range(horizon_days):
        current_day = start_day + timedelta(days=day_offset)
        is_weekend = current_day.weekday() >= 5
        work_start_hour, work_end_hour = get_work_hours(current_day)

        # Build slots for this day
        for hour in range(work_start_hour, work_end_hour):
            for half in [0, 1]:
                slot_start = datetime.combine(current_day, dtime(hour=hour, minute=30 if half else 0))
                slot_end = slot_start + timedelta(minutes=SLOT_DURATION_MINUTES)

                # Determine base status
                if is_weekend and not PROFILE["weekend_enabled"]:
                    status = SLOT_STATUS["out_of_range"]
                else:
                    status = SLOT_STATUS["free"]

                # Tag energy level
                # Default: 8h-12h = energy_high, 14h-17h = energy_low
                energy = "medium"
                if hour < 12:
                    energy = "high"
                elif hour >= 14:
                    energy = "low"

                canvas.append({
                    "start": slot_start,
                    "end": slot_end,
                    "date": current_day.isoformat(),
                    "status": status,
                    "energy": energy,
                    "locked_reason": None,
                    "occupied_by": None,
                    "buffer_reserved": False,
                })

    return canvas


def lock_canvas_slots(canvas: list[dict], start: datetime, end: datetime, reason: str):
    """Lock all slots overlapping with [start, end] range."""
    for slot in canvas:
        if slot["start"] < end and slot["end"] > start:
            if slot["status"] not in (SLOT_STATUS["occupied"], SLOT_STATUS["out_of_range"]):
                slot["status"] = SLOT_STATUS["locked"]
                slot["locked_reason"] = reason


def get_free_slots(canvas: list[dict], duration_minutes: int, energy_preference: str = None) -> list[dict]:
    """Get all contiguous blocks of free slots that can fit duration_minutes."""
    free_slots = [s for s in canvas if s["status"] == SLOT_STATUS["free"]]
    if not free_slots:
        return []

    required_slots = duration_minutes // 30
    if duration_minutes % 30 > 0:
        required_slots += 1

    contiguous_groups = []
    current_group = []

    for slot in free_slots:
        if not current_group:
            current_group = [slot]
        else:
            prev = current_group[-1]
            if slot["start"] == prev["end"] and (energy_preference is None or slot["energy"] == energy_preference):
                current_group.append(slot)
            else:
                if len(current_group) >= required_slots:
                    contiguous_groups.append(current_group)
                current_group = [slot]

    if current_group and len(current_group) >= required_slots:
        contiguous_groups.append(current_group)

    return contiguous_groups


def mark_slots_occupied(canvas: list[dict], slots: list[dict], task_id: str):
    """Mark a group of slots as occupied by a task."""
    for slot in slots:
        for cs in canvas:
            if cs["start"] == slot["start"] and cs["end"] == slot["end"]:
                cs["status"] = SLOT_STATUS["occupied"]
                cs["occupied_by"] = task_id
                break


def reserve_buffer(canvas: list[dict], after_dt: datetime, buffer_minutes: int):
    """Reserve a buffer after an intense task."""
    buffer_end = after_dt + timedelta(minutes=buffer_minutes)
    for slot in canvas:
        if slot["start"] >= after_dt and slot["end"] <= buffer_end:
            if slot["status"] == SLOT_STATUS["free"]:
                slot["status"] = SLOT_STATUS["locked"]
                slot["locked_reason"] = "buffer"
                slot["buffer_reserved"] = True


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_task(task: dict, config: dict = None, now: date = None) -> float:
    """
    Score a task using the 4-factor formula from PRD.
    Higher score = higher priority.
    """
    if config is None:
        config = {}
    if now is None:
        now = date.today()

    weights = config.get("score_weights", DEFAULT_SCORE_WEIGHTS)
    score = 0.0

    # Factor 1: Deadline urgency (0 → weights.deadline)
    if task.get("target_date"):
        try:
            due = datetime.fromisoformat(task["target_date"]).date()
            days = (due - now).days

            if days <= 0:
                coef = 1.0
            elif days == 1:
                coef = 0.90
            elif days <= 3:
                coef = 0.70
            elif days <= 7:
                coef = 0.40
            elif days <= 14:
                coef = 0.15
            else:
                coef = 0.05

            score += weights["deadline"] * coef
        except:
            pass

    # Factor 2: Priority manual (0 → weights.priority)
    priority_map = {"urgent": 1.0, "high": 1.0, "medium": 0.5, "low": 0.15, "none": 0.0}
    priority_coef = priority_map.get(str(task.get("priority", "none")).lower(), 0.0)
    score += weights["priority"] * priority_coef

    # Factor 3: Dependencies (0 → weights.dependencies)
    # A task that unlocks others gets bonus
    blocked_count = task.get("_blocked_count", 0)
    dep_bonus = min(blocked_count * (weights["dependencies"] / 4), weights["dependencies"])
    score += dep_bonus

    # Factor 4: Project urgency (0 → weights.project_urgency)
    project_urgency = task.get("project_urgency", "normale").lower()
    urgency_map = {"critique": 1.0, "haute": 0.5, "normale": 0.1}
    project_coef = urgency_map.get(project_urgency, 0.0)
    score += weights["project_urgency"] * project_coef

    return round(score, 2)


def sort_tasks_by_score(tasks: list[dict], config: dict = None) -> list[dict]:
    """Sort tasks by score descending. Tiebreak by target_date then priority."""
    now = date.today()
    scored = [(t, score_task(t, config, now)) for t in tasks]
    # Sort: score desc, then date asc, then priority
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
    scored.sort(key=lambda x: (
        -x[1],
        x[0].get("target_date", "9999-12-31"),
        priority_order.get(str(x[0].get("priority", "none")).lower(), 5)
    ))
    return [t for t, _ in scored]


# ── Placement ────────────────────────────────────────────────────────────────

def find_best_slot(
    task: dict,
    canvas: list[dict],
    strategy: str = "energy",
    buffer_minutes: int = 15
) -> list[dict] | None:
    """
    Find the best contiguous slot group for a task.
    Returns list of slots (the block) or None if no fit.
    """
    duration_min = int((task.get("duration", 1.0)) * 60)
    energy_pref = "high" if task.get("energy") == "intense" else ("low" if task.get("energy") == "light" else None)

    free_groups = get_free_slots(canvas, duration_min, energy_pref)

    if not free_groups:
        # Fallback: any free slot regardless of energy
        free_groups = get_free_slots(canvas, duration_min, None)

    if not free_groups:
        return None

    if strategy == "energy":
        # Prefer energy-matching slots
        if energy_pref:
            preferred = [g for g in free_groups if all(s["energy"] == energy_pref for s in g)]
            if preferred:
                return preferred[0]
        return free_groups[0]

    elif strategy == "earliest":
        return free_groups[0]

    elif strategy == "deadline":
        # Find slot closest to deadline without exceeding
        if not task.get("target_date"):
            return free_groups[0]
        deadline = datetime.fromisoformat(task["target_date"])
        best = None
        best_dist = float("inf")
        for group in free_groups:
            # Group end time
            group_end = group[-1]["end"]
            if group_end <= deadline:
                dist = (deadline - group_end).total_seconds() / 3600
                if dist < best_dist:
                    best_dist = dist
                    best = group
        return best if best else free_groups[0]

    elif strategy == "balanced":
        # Pick the group that leaves most room on its day (least loaded)
        day_loads = {}
        for group in free_groups:
            day = group[0]["date"]
            day_loads[day] = day_loads.get(day, 0) + 1
        min_day = min(day_loads, key=day_loads.get)
        for group in free_groups:
            if group[0]["date"] == min_day:
                return group
        return free_groups[0]

    return free_groups[0]


def place_tasks(tasks: list[dict], canvas: list[dict], config: dict = None) -> tuple[list[dict], list[dict]]:
    """
    Place tasks on canvas using scoring + placement strategy.
    Returns (placed, unplaced) where placed = list of {task, slots}.
    """
    if config is None:
        config = {}
    strategy = config.get("placement_strategy", DEFAULT_PLACEMENT_STRATEGY)
    buffer_minutes = config.get("buffer_after_intense", DEFAULT_BUFFER_AFTER_INTENSE)

    sorted_tasks = sort_tasks_by_score(tasks, config)
    placed = []
    unplaced = []

    for task in sorted_tasks:
        # Skip fixed tasks (not in our model yet)
        if task.get("task_type") == "fixed":
            continue

        slots = find_best_slot(task, canvas, strategy, buffer_minutes)
        if slots:
            mark_slots_occupied(canvas, slots, task["id"])
            # Reserve buffer after intense tasks
            if task.get("energy") == "intense" and buffer_minutes > 0:
                reserve_buffer(canvas, slots[-1]["end"], buffer_minutes)
            placed.append({"task": task, "slots": slots})
        else:
            unplaced.append({"task": task, "reason": "no_slot_available"})

    return placed, unplaced


# ── Conflict Detection ────────────────────────────────────────────────────────

def detect_conflicts(
    tasks: list[dict],
    canvas: list[dict] = None,
    config: dict = None
) -> list[dict]:
    """
    Detect all conflict types per PRD Section 7.
    """
    if config is None:
        config = {}
    if canvas is None:
        canvas = build_canvas(date.today(), 7)

    conflicts = []
    now = date.today()
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}

    # Group tasks by day
    by_day = {}
    for task in tasks:
        td = task.get("target_date", now.isoformat())
        if td not in by_day:
            by_day[td] = []
        by_day[td].append(task)

    for day_str, day_tasks in by_day.items():
        day = datetime.fromisoformat(day_str).date()
        work_start, work_end = get_work_hours(day)
        available_hours = work_end - work_start
        total_needed = sum(t.get("duration", 1.0) for t in day_tasks)

        # Surcharge journée
        if total_needed > available_hours:
            conflicts.append({
                "type": "surcharge_journée",
                "severity": "majeur",
                "day": day_str,
                "needed": total_needed,
                "available": available_hours,
                "auto_resolvable": True,
                "tasks": day_tasks,
                "message": f"⚠️ {day.strftime('%a %d')} : {total_needed:.1f}h nécessaires mais {available_hours}h disponibles",
            })

        # High priority density
        high_pri = [t for t in day_tasks if priority_order.get(str(t.get("priority", "none")).lower(), 5) <= 1]
        if len(high_pri) > 2:
            conflicts.append({
                "type": "high_priority_density",
                "severity": "majeur",
                "day": day_str,
                "count": len(high_pri),
                "auto_resolvable": False,
                "tasks": high_pri,
                "message": f"🔴 {day.strftime('%a %d')} : {len(high_pri)} tâches haute priorité — risque de surcharge",
            })

        # Deadline impossible (pas assez de temps)
        for task in day_tasks:
            if task.get("target_date"):
                due = datetime.fromisoformat(task["target_date"]).date()
                days_until = (due - now).days
                duration_h = task.get("duration", 1.0)
                # Rough check: if remaining days × available hours < duration
                if days_until >= 0:
                    remaining_days = days_until + 1
                    total_available = remaining_days * available_hours
                    if total_available < duration_h * 1.5:  # 1.5 buffer
                        conflicts.append({
                            "type": "deadline_impossible",
                            "severity": "critique",
                            "day": day_str,
                            "task": task,
                            "auto_resolvable": False,
                            "message": f"🚨 Deadline serrée : \"{task['title'][:40]}\" ({duration_h}h, {days_until}j) — risque de louper la date",
                        })

    # Surcharge semaine
    if config:
        weekly_threshold = config.get("weekly_overload_threshold", PROFILE.get("max_weekly_hours", 40))
    else:
        weekly_threshold = PROFILE.get("max_weekly_hours", 40)

    total_weekly = sum(t.get("duration", 1.0) for t in tasks)
    if total_weekly > weekly_threshold:
        conflicts.append({
            "type": "surcharge_semaine",
            "severity": "majeur",
            "needed": total_weekly,
            "available": weekly_threshold,
            "auto_resolvable": True,
            "message": f"⚠️ Surcharge semaine : {total_weekly:.1f}h / {weekly_threshold}h — {total_weekly - weekly_threshold:.1f}h de trop",
        })

    return conflicts


# ── Options Generation ────────────────────────────────────────────────────────

def generate_options(
    conflicts: list[dict],
    tasks: list[dict],
    canvas: list[dict],
    config: dict = None
) -> list[dict]:
    """
    Generate 2-3 options per conflict with one recommended.
    Returns list of {conflict, options}.
    """
    options_by_conflict = []

    for conflict in conflicts:
        conflict_options = []
        ctype = conflict["type"]

        if ctype == "surcharge_journée":
            day = conflict["day"]
            surplus = conflict["needed"] - conflict["available"]
            day_tasks = conflict["tasks"]

            # Option A (recommended): move surplus to next available day
            next_day_slots = [s for s in canvas if s["date"] > day and s["status"] == "libre"]
            if next_day_slots:
                conflict_options.append({
                    "id": f"{day}_redistribute",
                    "label": f"Déplacer {surplus:.1f}h vers le prochain jour disponible",
                    "description": f"Répartir la charge excédentaire du {day} sur les jours suivants",
                    "impact": f"Deadline maintenue, {surplus:.1f}h déplacés",
                    "is_recommended": True,
                    "changes": [{"type": "redistribute", "from_day": day, "surplus_hours": surplus}],
                })

            # Option B: reduce task scope
            conflict_options.append({
                "id": f"{day}_reduce",
                "label": "Raccourcir certaines tâches",
                "description": "Réduire la durée de 2 tâches flexibles de 30%",
                "impact": "Charge réduite, risque de tâche incomplète",
                "is_recommended": False,
                "changes": [{"type": "reduce_duration", "day": day, "reduction": 0.3}],
            })

            # Option C: ask later
            conflict_options.append({
                "id": f"{day}_defer",
                "label": "Décider plus tard",
                "description": "Me rappeler dans 2h pour résoudre ce conflit",
                "impact": "Conflit non résolu, rappel automatique",
                "is_recommended": False,
                "changes": [],
            })

        elif ctype == "surcharge_semaine":
            surplus = conflict["needed"] - conflict["available"]

            conflict_options.append({
                "id": "week_redistribute",
                "label": "Redistribuer les tâches flexibles sur 2 semaines",
                "description": f"Décaler {surplus:.1f}h de tâches flexibles à la semaine suivante",
                "impact": "Semaine équilibrée, charge lissée",
                "is_recommended": True,
                "changes": [{"type": "redistribute_week", "surplus_hours": surplus}],
            })

            conflict_options.append({
                "id": "week_identify",
                "label": "Identifier les tâches à déléguer ou supprimer",
                "description": "Lister les tâches non essentielles à retirer cette semaine",
                "impact": "Réduction de charge, action manuelle requise",
                "is_recommended": False,
                "changes": [],
            })

            conflict_options.append({
                "id": "week_alert",
                "label": "Garder le planning avec alerte quotidienne",
                "description": "Maintenir la surcharge et suivre de près l'avancement",
                "impact": "Surcharge maintenue, suivi renforcé",
                "is_recommended": False,
                "changes": [],
            })

        elif ctype == "high_priority_density":
            conflict_options.append({
                "id": f"{conflict['day']}_prioritise",
                "label": "Ne garder que les 2 tâches haute priorité",
                "description": "Décaler les autres vers les jours suivants",
                "impact": "2 tâches prioritaires assurées, reste reporté",
                "is_recommended": True,
                "changes": [{"type": "prioritise", "day": conflict["day"], "keep": 2}],
            })

            conflict_options.append({
                "id": f"{conflict['day']}_split",
                "label": "Scinder les tâches longues",
                "description": "Couper les tâches de +2h en sous-tâches sur 2 jours",
                "impact": "Toutes les tâches traitées, étalées sur 2 jours",
                "is_recommended": False,
                "changes": [],
            })

        elif ctype == "deadline_impossible":
            task = conflict.get("task", {})
            conflict_options.append({
                "id": f"deadline_{task.get('id', 'unknown')}_reorganise",
                "label": f"Réorganiser les jours précédents pour {task.get('title', '?')[:30]}",
                "description": "Libérer du temps les jours avant la deadline",
                "impact": "Deadline respectée, réorganisation nécessaire",
                "is_recommended": True,
                "changes": [{"type": "reorganise", "task_id": task.get("id")}],
            })

            conflict_options.append({
                "id": f"deadline_{task.get('id', 'unknown')}_renegociate",
                "label": "Renégocier la deadline",
                "description": "Signaler que la deadline n'est pas réaliste",
                "impact": "Deadline à revoir, communication nécessaire",
                "is_recommended": False,
                "changes": [],
            })

        options_by_conflict.append({
            "conflict": conflict,
            "options": conflict_options,
        })

    return options_by_conflict


# ── Main scheduling pipeline ─────────────────────────────────────────────────

def run_scheduling_pipeline(
    tasks: list[dict],
    config: dict = None,
    horizon_days: int = 7
) -> dict:
    """
    Full 5-step pipeline from PRD Section 2.
    Returns: { canvas, placed, unplaced, conflicts, options }
    """
    if config is None:
        config = {}
    now = date.today()

    # Step 1: Build canvas
    canvas = build_canvas(now, horizon_days)

    # Step 2: Score tasks (already done in place_tasks via sort)
    scored_tasks = sort_tasks_by_score(tasks, config)

    # Step 3: Place tasks
    placed, unplaced = place_tasks(scored_tasks, canvas, config)

    # Step 4: Detect conflicts
    conflicts = detect_conflicts(tasks, canvas, config)

    # Step 5: Generate options
    options = generate_options(conflicts, tasks, canvas, config)

    return {
        "canvas": canvas,
        "placed": placed,
        "unplaced": unplaced,
        "conflicts": conflicts,
        "options": options,
    }


# ── Legacy helpers (kept for backward compat) ─────────────────────────────────

def get_work_hours(day: date) -> tuple[int, int]:
    """Return (start, end) work hours for a given day."""
    is_weekend = day.weekday() >= 5

    if is_weekend and PROFILE["weekend_enabled"]:
        return PROFILE["weekend_start"], PROFILE["weekend_end"]

    return PROFILE["work_start"], PROFILE["work_end"]


def calculate_daily_load(tasks: list[dict], day: date) -> float:
    """Calculate total estimated hours for a given day."""
    total = 0.0
    for task in tasks:
        if task["target_date"] == day.isoformat():
            total += task.get("duration", 1.0)
    return total


def calculate_weekly_load(tasks: list[dict], start_day: date) -> dict:
    """Calculate load for each day of the week starting from start_day."""
    daily_loads = {}
    total = 0.0

    for i in range(7):
        day = start_day + timedelta(days=i)
        load = calculate_daily_load(tasks, day)
        daily_loads[day.isoformat()] = {
            "date": day,
            "hours": load,
            "is_weekend": day.weekday() >= 5,
            "work_start": get_work_hours(day)[0],
            "work_end": get_work_hours(day)[1],
        }
        total += load

    return {
        "daily": daily_loads,
        "total": total,
        "max": PROFILE["max_weekly_hours"],
        "remaining": max(0, PROFILE["max_weekly_hours"] - total),
        "status": "ok" if total <= PROFILE["max_weekly_hours"] else "overload",
    }


def detect_conflicts_legacy(tasks: list[dict], day: date) -> list[dict]:
    """Legacy conflict detection for backward compat."""
    return detect_conflicts(tasks, None, None)


def get_deep_work_tasks(tasks: list[dict]) -> list[dict]:
    """Return tasks suitable for deep work (morning, intense)."""
    return [t for t in tasks if t.get("energy") == "intense" or t.get("task_type") in ["DEV", "devops"]]


def get_light_tasks(tasks: list[dict]) -> list[dict]:
    """Return tasks suitable for light afternoon work."""
    return [t for t in tasks if t.get("energy") == "light" or t.get("task_type") in ["gestion", "admin"]]


def score_task_legacy(task: dict) -> float:
    """Legacy scoring for backward compat."""
    return score_task(task, {}, date.today())

# ─── Move Proposer ─────────────────────────────────────────────────────────────

def get_proposed_moves(days: int = 7) -> list[dict]:
    """
    Get backlog tasks that should be moved to Todo based on their target_date.
    Returns list of tasks with target_date <= today + days.
    """
    today = date.today()
    cutoff = today + timedelta(days=days)
    proposed = []
    
    for ws in get_workspaces():
        if not ws["enabled"]:
            continue
        backlog_tasks = get_backlog_tasks(ws["slug"])
        for task in backlog_tasks:
            td = task.get("target_date_obj")
            if td and td <= cutoff:
                proposed.append(task)
    
    # Sort by target_date, then by priority
    priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
    proposed.sort(key=lambda t: (t.get("target_date_obj", today), priority_order.get(t.get("priority", "none"), 5)))
    
    return proposed


def generate_proposals_text(days: int = 7) -> str:
    """Generate text showing proposed moves from Backlog to Todo."""
    today = date.today()
    proposed = get_proposed_moves(days)
    
    if not proposed:
        return ""
    
    lines = []
    lines.append(f"**📋 Propositions — Backlog → Todo ({len(proposed)} tâches)**")
    lines.append("")
    lines.append("Ces tâches ont une date butoir dans les prochains jours :")
    lines.append("")
    
    for t in proposed:
        td = t.get("target_date_obj", today)
        days_until = (td - today).days
        urgency = "🔴" if days_until <= 1 else ("🟡" if days_until <= 3 else "🟢")
        
        lines.append(f"  {urgency} {td.strftime('%a %d')} — {t['title'][:50]}")
        lines.append(f"      ↳ {t['workspace']} / {t['project_name']} ({t.get('duration', 1):.1f}h)")
    
    lines.append("")
    lines.append("**Action :** Je move ces tâches vers Todo ? Réponds `ok` pour valider.")
    
    return "\n".join(lines)


# ─── Recap Generator ───────────────────────────────────────────────────────────

def generate_recap(tasks: list[dict], days: int = 7, include_proposals: bool = True) -> str:
    """Generate a structured daily recap."""
    today = date.today()
    lines = []
    
    lines.append(f"📋 **Recap — {today.strftime('%d %b %Y')}**")
    lines.append("")
    
    # ── 7-day load overview
    weekly = calculate_weekly_load(tasks, today)
    
    lines.append("**📊 Charge 7 jours**")
    for day_str, info in weekly["daily"].items():
        day = info["date"]
        marker = ""
        if info["is_weekend"] and not PROFILE["weekend_enabled"]:
            marker = " 🌙"
        elif info["hours"] > PROFILE["max_weekly_hours"] / 5:
            marker = " ⚠️" if info["hours"] > (info["work_end"] - info["work_start"]) else ""
        elif info["hours"] > 0:
            marker = " ✅" if info["hours"] >= PROFILE["min_daily_hours"] else " ⚡"
        
        lines.append(
            f"  {day.strftime('%a %d')} : {info['hours']:.1f}h"
            f" ({info['work_start']}h–{info['work_end']}h){marker}"
        )
    
    lines.append(f"  **Total : {weekly['total']:.1f}h / {weekly['max']}h**")
    if weekly["status"] == "overload":
        lines.append(f"  🚨 **SURCHARGE** : {weekly['total'] - weekly['max']:.1f}h de trop cette semaine")
    lines.append("")
    
def generate_recap(tasks: list[dict], days: int = 7, include_proposals: bool = True) -> str:
    """Generate a structured daily recap using the full scheduling pipeline."""
    today = date.today()
    lines = []

    # Run the full scheduling pipeline
    config = {"score_weights": DEFAULT_SCORE_WEIGHTS, "placement_strategy": DEFAULT_PLACEMENT_STRATEGY}
    pipeline = run_scheduling_pipeline(tasks, config, days)
    placed = pipeline["placed"]
    conflicts = pipeline["conflicts"]
    options = pipeline["options"]

    lines.append(f"📋 **Recap — {today.strftime('%d %b %Y')}**")
    lines.append("")

    # ── Pipeline summary
    placed_ids = [p["task"]["id"] for p in placed]
    placed_tasks = [t for t in tasks if t["id"] in placed_ids]
    weekly = calculate_weekly_load(placed_tasks, today)

    lines.append("**📊 Charge 7 jours**")
    for day_str, info in weekly["daily"].items():
        day = info["date"]
        marker = ""
        if info["is_weekend"] and not PROFILE["weekend_enabled"]:
            marker = " 🌙"
        elif info["hours"] > PROFILE["max_weekly_hours"] / 5:
            marker = " ⚠️" if info["hours"] > (info["work_end"] - info["work_start"]) else ""
        elif info["hours"] > 0:
            marker = " ✅" if info["hours"] >= PROFILE["min_daily_hours"] else " ⚡"

        lines.append(
            f"  {day.strftime('%a %d')} : {info['hours']:.1f}h"
            f" ({info['work_start']}h–{info['work_end']}h){marker}"
        )

    lines.append(f"  **Total : {weekly['total']:.1f}h / {weekly['max']}h**")
    if weekly["status"] == "overload":
        lines.append(f"  🚨 **SURCHARGE** : {weekly['total'] - weekly['max']:.1f}h de trop cette semaine")
    lines.append("")

    # ── Conflicts + Options
    if conflicts:
        lines.append(f"**⚠️ {len(conflicts)} conflit(s) détecté(s)**")
        for og in options:
            c = og["conflict"]
            lines.append(f"  {c['message']}")
            for opt in og["options"]:
                rec = "👉 " if opt["is_recommended"] else "  "
                lines.append(f"    {rec}{opt['label']}")
                lines.append(f"       Impact : {opt['impact']}")
        lines.append("")

    # ── Today's placed tasks (from pipeline — already sorted by score)
    today_placed = [p for p in placed if p["slots"][0]["date"] == today.isoformat()]

    if today_placed:
        lines.append(f"**🎯 Aujourd'hui ({today.strftime('%a %d')} — {len(today_placed)} tâches)**")

        # Morning (energy high)
        morning = [p for p in today_placed if p["slots"][0]["start"].hour < 12]
        afternoon = [p for p in today_placed if p["slots"][0]["start"].hour >= 12]

        if morning:
            lines.append("  🔴 **Matin (énergie haute)**")
            for p in morning[:3]:
                t = p["task"]
                lines.append(f"    • {t['title'][:50]} ({t.get('duration', 1):.1f}h)")
                lines.append(f"      ↳ {t.get('workspace', '')} / {t.get('project_name', '')}")
                lines.append(f"      ↳ Score: {score_task(t, config, today):.0f}")

        if afternoon:
            lines.append("  🟡 **Après-midi (énergie basse)**")
            for p in afternoon[:5]:
                t = p["task"]
                lines.append(f"    • {t['title'][:50]} ({t.get('duration', 1):.1f}h)")
                lines.append(f"      ↳ {t.get('workspace', '')} / {t.get('project_name', '')}")

        lines.append("")

    # ── This week's deadlines
    week_deadlines = [t for t in tasks if t.get("target_date") and today <= datetime.fromisoformat(t["target_date"]).date() <= today + timedelta(days=7)]
    if week_deadlines:
        lines.append(f"**📅 Deadlines de la semaine ({len(week_deadlines)} tâches)**")
        week_deadlines.sort(key=lambda t: t["target_date"])
        for t in week_deadlines[:8]:
            day = datetime.fromisoformat(t["target_date"]).date()
            days_until = (day - today).days
            urgency = "🔴" if days_until <= 1 else ("🟡" if days_until <= 3 else "🟢")
            lines.append(f"  {urgency} {day.strftime('%a %d')} — {t['title'][:45]}")
        lines.append("")

    # ── Status summary by workspace
    workspaces = {}
    for t in tasks:
        ws = t.get("workspace", "unknown")
        if ws not in workspaces:
            workspaces[ws] = {"total": 0, "done": 0, "in_progress": 0}
        workspaces[ws]["total"] += 1
        if t.get("state_name", "").lower() in ["done", "completed", "cancelled"]:
            workspaces[ws]["done"] += 1

    if workspaces:
        lines.append("**📦 Par workspace**")
        for ws, stats in workspaces.items():
            pct = (stats["done"] / stats["total"] * 100) if stats["total"] > 0 else 0
            lines.append(f"  {ws} : {stats['done']}/{stats['total']} done ({pct:.0f}%)")
        lines.append("")

    # ── Recommendations
    recommendations = []

    if weekly["status"] == "overload":
        recommendations.append("⚠️ Réduire la charge cette semaine ou décaler des tâches")

    if weekly["total"] < PROFILE["min_daily_hours"] * 5:
        recommendations.append("📉 Semaine légère — espace disponible")

    today_load = sum(p["task"].get("duration", 1) for p in today_placed) if today_placed else 0
    if today_load < PROFILE["min_daily_hours"]:
        recommendations.append(f"💡 Aujourd'hui : {today_load:.1f}h de chargé, espace disponible")

    deep_today = [p for p in today_placed if p["task"].get("energy") == "intense" or p["task"].get("task_type") in ["DEV", "devops"]]
    if not deep_today and today_placed:
        recommendations.append("💡 Pas de deep work prévu — idéal pour les tâches administratives")

    if recommendations:
        lines.append("**💡 Recommandations**")
        for r in recommendations:
            lines.append(f"  {r}")
        lines.append("")

    # ── Propose backlog -> todo moves
    if include_proposals:
        proposals_text = generate_proposals_text(days)
        if proposals_text:
            lines.append(proposals_text)

    return "\n".join(lines)


# ─── Project & PRD Management ───────────────────────────────────────────────────

def ensure_develop_folder():
    """Ensure ~/develop/ folder exists."""
    os.makedirs(DEVELOP_BASE, exist_ok=True)

def get_project_by_name(name: str, workspace: str = None) -> Optional[dict]:
    """Get a project from SQLite by name and optional workspace."""
    conn = get_db()
    if workspace:
        row = conn.execute(
            "SELECT * FROM projects WHERE name = ? AND workspace = ?", (name, workspace)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM projects WHERE name = ?", (name,)
        ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_project_by_id(project_id: str) -> Optional[dict]:
    """Get a project from SQLite by Plane ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def save_project(project_data: dict):
    """Insert or update a project in SQLite."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM projects WHERE id = ?", (project_data["id"],)).fetchone()
    if existing:
        sets = ", ".join(f"{k} = ?" for k in project_data if k != "id")
        conn.execute(
            f"UPDATE projects SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [project_data[k] for k in project_data if k != "id"] + [project_data["id"]]
        )
    else:
        cols = ", ".join(project_data.keys())
        placeholders = ", ".join(["?"] * len(project_data))
        conn.execute(
            f"INSERT INTO projects ({cols}) VALUES ({placeholders})",
            list(project_data.values())
        )
    conn.commit()
    conn.close()

def create_project_folder(name: str, repo_url: str = None) -> dict:
    """
    Create project folder structure: ~/develop/<name>/docs/
    If repo_url provided, clone into ~/develop/<name>/ first.
    Returns: {local_path, docs_path, has_repo}
    """
    ensure_develop_folder()
    project_path = os.path.join(DEVELOP_BASE, name)
    docs_path = os.path.join(project_path, "docs")

    has_repo = False
    if repo_url:
        # Clone repo into project folder
        import subprocess
        try:
            subprocess.run(
                ["git", "clone", repo_url, project_path],
                check=True, capture_output=True, text=True
            )
            has_repo = True
            # docs/ might already exist in the repo
            if not os.path.exists(docs_path):
                os.makedirs(docs_path, exist_ok=True)
        except subprocess.CalledProcessError as e:
            # Repo might already exist locally
            if os.path.exists(os.path.join(project_path, ".git")):
                has_repo = True
            else:
                return {"error": f"Git clone failed: {e.stderr}"}
    else:
        # Just create the folder structure
        os.makedirs(docs_path, exist_ok=True)

    return {
        "local_path": project_path,
        "docs_path": docs_path,
        "has_repo": has_repo,
    }


# ─── Plane helpers (using plane_manager when available) ─────────────────────────

def create_plane_project(name: str, workspace_slug: str, description: str = "") -> dict:
    """Create a project in Plane workspace using plane_manager."""
    try:
        sys.path.insert(0, "/root/.hermes/skills")
        from plane_manager.scripts import create_project as pm_create_project
        return pm_create_project(name=name, description=description)
    except Exception as e:
        return {"error": str(e)}


def create_plane_page(project_id: str, workspace_slug: str, title: str, content: str = "") -> dict:
    """Create a page in a Plane project using plane_manager."""
    try:
        sys.path.insert(0, "/root/.hermes/skills")
        from plane_manager.scripts import create_page as pm_create_page
        return pm_create_page(project_id=project_id, name=title, description_html=content)
    except Exception as e:
        return {"error": str(e)}


def update_project_description(project_id: str, workspace_slug: str, description: str):
    """Update the description of a Plane project using plane_manager."""
    try:
        sys.path.insert(0, "/root/.hermes/skills")
        from plane_manager.scripts import update_project as pm_update_project
        return pm_update_project(project_id=project_id, description=description)
    except Exception as e:
        return {"error": str(e)}

# ─── PRD Generation ─────────────────────────────────────────────────────────────

PRD_QUESTIONS_COMMON = [
    "1. **Nom du projet** — Quel est le nom de ce projet/initiative ?",
    "2. **Problème résolu** — Quel problème résout-on ? Pourquoi c'est important maintenant ?",
    "3. **Objectifs mesurables** — Quels sont les objectifs SMART (Specific, Measurable, Achievable, Relevant, Time-bound) ?",
    "4. **Timeline** — Quelle est la deadline ou la durée estimée ?",
    "5. **Risques principaux** — Quels sont les 3 risques les plus critiques ?",
    "6. **Parties prenantes** — Qui sont les utilisateurs/acteurs concernés ?",
    "7. **Contraintes** — Y a-t-il des contraintes techniques, budgétaires ou organisationnelles ?",
]

PRD_QUESTIONS_TECHNIQUE = [
    "8. **Architecture** — Quelle architecture technique est envisagée (monolithique, microservices, serverless…) ?",
    "9. **Stack technique** — Quelles technologies, langages, frameworks ?",
    "10. **API** — Y a-t-il des besoins API (REST, GraphQL, websockets…) ?",
    "11. **Base de données** — Quel type de DB (SQL, NoSQL, cache…) ?",
    "12. **Sécurité** — Y a-t-il des besoins d'authentification, autorisation, chiffrement ?",
    "13. **Déploiement** — Quel environnement de déploiement (cloud, on-premise, hybrid) ?",
    "14. **Intégrations** — Y a-t-il des intégrations avec des services tiers ?",
]

PRD_QUESTIONS_PRODUIT = [
    "8. **Utilisateurs cibles** — Qui sont les personas (nom, rôle, besoins, pain points) ?",
    "9. **User stories** — Quelles sont les principales user stories (En tant que… Je veux… Afin de…) ?",
    "10. **UX/UI** — Y a-t-il des maquettes, flows, ou inspirations UI à intégrer ?",
    "11. **Fonctionnalités prioritaires** — Quelles sont les fonctionnalités must-have vs nice-to-have ?",
    "12. **Métriques de succès** — Comment mesure-t-on le succès du produit (DAU, conversion, NPS…) ?",
    "13. **Launch plan** — Quel est le plan de lancement (beta, rollout progressif, GA) ?",
]

PRD_QUESTIONS_STRATEGIQUE = [
    "8. **Vision & Mission** — Quelle est la vision long terme et la mission de cette initiative ?",
    "9. **Business Case** — Quel est le ROI attendu, le budget estimé ?",
    "10. **Analyse marché** — Quelle est la taille du marché (TAM/SAM/SOM) et la concurrence ?",
    "11. **OKRs** — Quels sont les Objectives et Key Results attendus ?",
    "12. **Roadmap** — Quelles sont les phases principales et les milestones ?",
    "13. **Go-to-Market** — Quelle est la stratégie de pénétration du marché ?",
]

def get_questions_for_type(prd_type: str) -> list:
    """Get the full question list for a PRD type."""
    questions = list(PRD_QUESTIONS_COMMON)
    if prd_type == "technique":
        questions.extend(PRD_QUESTIONS_TECHNIQUE)
    elif prd_type == "produit":
        questions.extend(PRD_QUESTIONS_PRODUIT)
    elif prd_type == "strategique":
        questions.extend(PRD_QUESTIONS_STRATEGIQUE)
    return questions

def build_prd_content(prd_type: str, project_name: str, answers: dict) -> str:
    """Build a complete PRD markdown from user answers."""
    today = datetime.now().strftime("%Y-%m-%d")

    def s(key, default=""):
        return answers.get(key, default)

    # Header
    lines = [
        f"# PRD {prd_type.capitalize()} : {project_name}",
        "",
        "---",
        "",
        "## 📋 Métadonnées",
        "",
        "| Champ | Valeur |",
        "|-------|--------|",
        f"| Type | PRD {prd_type.capitalize()} |",
        f"| Date | {today} |",
        "| Auteur | Ronald Ndi (Wilrona) |",
        "| Version | v0.1 |",
        "| Statut | Draft |",
        "",
        "---",
        "",
        "## Résumé Exécutif",
        "",
        s('resume', '[À compléter — 3-5 phrases : What, Why, Who, Value]'),
        "",
        "---",
        "",
        "## Contexte",
        "",
        "### Problème résolu",
        "",
        s('probleme', '[Décrire le problème que cette initiative résout]'),
        "",
        "### Pourquoi maintenant",
        "",
        s('pourquoi', "[Expliquer pourquoi c'est urgent/important maintenant]"),
        "",
        "---",
        "",
        "## Objectifs",
        "",
        s('objectifs', '[Objectifs SMART — Specific, Measurable, Achievable, Relevant, Time-bound]'),
        "",
        "## Métriques de Succès",
        "",
        "| Métrique | Baseline | Target | Timeframe |",
        "|----------|----------|--------|----------|",
        "| [Métrique 1] | [Valeur actuelle] | [Cible] | [Date] |",
        "| [Métrique 2] | [Valeur actuelle] | [Cible] | [Date] |",
        "",
        "---",
        "",
        "## Risques & Contraintes",
        "",
        "### Risques principaux",
        "",
        "| Risque | Impact | Probabilité | Mitigation |",
        "|--------|--------|-------------|------------|",
        f"| {s('risque_1', '[Risque 1]')} | [High/Medium/Low] | [High/Medium/Low] | [Mitigation] |",
        f"| {s('risque_2', '[Risque 2]')} | [High/Medium/Low] | [High/Medium/Low] | [Mitigation] |",
        f"| {s('risque_3', '[Risque 3]')} | [High/Medium/Low] | [High/Medium/Low] | [Mitigation] |",
        "",
        "### Contraintes",
        "",
        s('contraintes', '[Contraintes techniques, budgétaires, organisationnelles]'),
        "",
        "---",
        "",
        "## Parties Prenantes",
        "",
        s('parties_prenantes', '[Utilisateurs, acteurs, équipes impactées]'),
        "",
        "---",
        "",
        "## Planning",
        "",
        s('planning', '[Phases, milestones, timeline]'),
        "",
        "## Checklist de Validation",
        "",
        "- [ ] Résumé Exécutif validé",
        "- [ ] Objectifs SMART approuvés",
        "- [ ] Risques identifiés et mitigation planifiée",
        "- [ ] Planning réaliste et validé",
        "- [ ] Parties prenantes alignées",
        "",
        "---",
    ]

    if prd_type == "technique":
        lines.extend([
            "## Architecture Technique",
            "",
            s('architecture', "[Description de l'architecture — monolithique, microservices, event-driven…]"),
            "",
            "### Stack Technique",
            "",
            "| Composant | Technologie |",
            "|-----------|-------------|",
            f"| Langage | {s('stack_langage', '[Langage]')} |",
            f"| Framework | {s('stack_framework', '[Framework]')} |",
            f"| Base de données | {s('db', '[SQL/NoSQL/Cache]')} |",
            f"| API | {s('api', '[REST/GraphQL/WebSocket]')} |",
            f"| Déploiement | {s('deploy', '[Cloud/On-premise/Hybrid]')} |",
            "",
            "### Spécifications API",
            "",
            s('api_specs', '[Endpoints, méthodes, formats de requête/réponse]'),
            "",
            "### Schéma de Base de Données",
            "",
            s('db_schema', '[Tables principales, indexes, relations]'),
            "",
            "### Sécurité",
            "",
            s('securite', '[Auth, authorisation, validation, chiffrement]'),
            "",
            "### Performance",
            "",
            s('performance', '[Objectifs de performance, optimisations]'),
            "",
            "### Déploiement",
            "",
            s('deploy_details', '[Environnements, stratégie de déploiement, rollback]'),
            "",
            "### Intégrations",
            "",
            s('integrations', '[Services tiers, webhooks, APIs externes]'),
            "",
        ])
    elif prd_type == "produit":
        lines.extend([
            "## Utilisateurs Cibles",
            "",
            s('utilisateurs', '[Personas — nom, rôle, besoins, pain points]'),
            "",
            "### User Stories",
            "",
            s('user_stories', '[Format: En tant que / Je veux / Afin de]'),
            "",
            "### Expérience Utilisateur",
            "",
            s('ux', '[Flows, screens, interactions, maquettes]'),
            "",
            "### Fonctionnalités",
            "",
            s('fonctionnalites', '[Fonctionnalités avec règles métier]'),
            "",
            "### Priorisation (MoSCoW)",
            "",
            "| Priorité | Fonctionnalité |",
            "|----------|----------------|",
            "| Must Have | [Fonctionnalité critique] |",
            "| Should Have | [Fonctionnalité importante] |",
            "| Could Have | [Fonctionnalité nice-to-have] |",
            "| Won't Have | [Hors périmètre] |",
            "",
            "### Accessibilité",
            "",
            s('accessibilite', '[WCAG compliance, accessibilité]'),
            "",
            "### Internationalisation",
            "",
            s('i18n', '[Langues supportées, localisation]'),
            "",
            "### Plan de Lancement",
            "",
            s('launch', '[Beta, rollout progressif, GA]'),
            "",
        ])
    elif prd_type == "strategique":
        lines.extend([
            "## Vision & Mission",
            "",
            s('vision', '[Vision long terme et mission]'),
            "",
            "### Business Case",
            "",
            s('business_case', '[ROI, investissement, valeur]'),
            "",
            "### Analyse Marché",
            "",
            s('marche', '[TAM/SAM/SOM, tendances, concurrence]'),
            "",
            "### Avantages Concurrentiels",
            "",
            s('advantages', '[Différenciation, barrières]'),
            "",
            "### OKRs",
            "",
            "| Objective | Key Result | Target |",
            "|-----------|------------|--------|",
            f"| {s('okr_obj_1', '[Objectif 1]')} | {s('okr_kr_1', '[KR]')} | [Date] |",
            f"| {s('okr_obj_2', '[Objectif 2]')} | {s('okr_kr_2', '[KR]')} | [Date] |",
            "",
            "### Roadmap Stratégique",
            "",
            s('roadmap', '[Phases, initiatives, milestones]'),
            "",
            "### Budget & Ressources",
            "",
            s('budget', '[Investissement, équipe, compétences]'),
            "",
            "### Go-to-Market",
            "",
            s('gtm', '[Positionnement, pricing, canaux]'),
            "",
        ])

    lines.extend([
        "---",
        "",
        "*Document généré avec SecretaryIA — PRD Generator v0.1*",
    ])

    return "\n".join(lines)

def build_plan_content(project_name: str, prd_content: str, answers: dict) -> str:
    """Build an implementation plan from PRD and answers."""
    today = datetime.now().strftime("%Y-%m-%d")

    def s(key, default=""):
        return answers.get(key, default)

    lines = [
        f"# Plan d'Implantation : {project_name}",
        "",
        "---",
        "",
        "## 📋 Métadonnées",
        "",
        "| Champ | Valeur |",
        "|-------|--------|",
        f"| Projet | {project_name} |",
        f"| Date | {today} |",
        "| Version | v0.1 |",
        "| Statut | Draft |",
        "",
        "---",
        "",
        "## Vue d'ensemble",
        "",
        s('overview', '[Résumé du plan — ce qui va être fait et comment]'),
        "",
        "---",
        "",
        "## Phases d'Implantation",
        "",
        "### Phase 1 — Fondation",
        "",
        "**Objectif** : [Construire les fondations techniques/produit]",
        "",
        "| Tâche | Responsable | Durée | Dépendances |",
        "|-------|-------------|-------|-------------|",
        "| [Tâche 1.1] | [Ronald] | [Xj] | — |",
        "| [Tâche 1.2] | [Ronald] | [Xj] | 1.1 |",
        "| [Tâche 1.3] | [Ronald] | [Xj] | 1.2 |",
        "",
        "### Phase 2 — Développement",
        "",
        "**Objectif** : [Développer les fonctionnalités core]",
        "",
        "| Tâche | Responsable | Durée | Dépendances |",
        "|-------|-------------|-------|-------------|",
        "| [Tâche 2.1] | [Ronald] | [Xj] | 1.3 |",
        "| [Tâche 2.2] | [Ronald] | [Xj] | 2.1 |",
        "| [Tâche 2.3] | [Ronald] | [Xj] | 2.1 |",
        "",
        "### Phase 3 — Validation & Déploiement",
        "",
        "**Objectif** : [Valider et déployer en production]",
        "",
        "| Tâche | Responsable | Durée | Dépendances |",
        "|-------|-------------|-------|-------------|",
        "| [Tâche 3.1] | [Ronald] | [Xj] | 2.3 |",
        "| [Tâche 3.2] | [Ronald] | [Xj] | 3.1 |",
        "",
        "---",
        "",
        "## Découpage Technique (si applicable)",
        "",
        s('decoupage_technique', '[Architecture, services, modules]'),
        "",
        "## Ressources",
        "",
        s('ressources', '[Outils, environnements, accès nécessaires]'),
        "",
        "## Points de Vigilance",
        "",
        s('vigilance', '[Points critiques à surveiller]'),
        "",
        "---",
        "",
        "## Checklist Avancement",
        "",
        "- [ ] Phase 1 terminée",
        "- [ ] Phase 2 terminée",
        "- [ ] Phase 3 terminée",
        "- [ ] Validation finale approuvée",
        "",
        "---",
        "",
        "*Plan généré avec SecretaryIA — v0.1*",
    ]

    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def cmd_recap(days: int = 7, workspace: str = None):
    """Generate recap for all workspaces or specific one."""
    all_tasks = []
    
    workspaces = get_workspaces()
    if workspace:
        workspaces = [w for w in workspaces if w["slug"] == workspace]
    
    for ws in workspaces:
        if not ws["enabled"]:
            continue
        tasks = get_all_tasks_7_days(ws["slug"])
        all_tasks.extend(tasks)
    
    if not all_tasks:
        return "Aucun tâche trouvée dans les 7 prochains jours."
    
    return generate_recap(all_tasks, days)

def cmd_set_metadata(task_id: str, workspace: str, **kwargs):
    """Set metadata for a task."""
    set_metadata(task_id, workspace, **kwargs)
    return f"Metadata updated for {task_id}"

def cmd_status():
    """Show current status."""
    today = date.today()
    all_tasks = []
    
    for ws in get_workspaces():
        if ws["enabled"]:
            tasks = get_all_tasks_7_days(ws["slug"])
            all_tasks.extend(tasks)
    
    weekly = calculate_weekly_load(all_tasks, today)
    
    lines = [
        f"📊 SecretaryIA Status — {today.strftime('%d %b %Y')}",
        f"  Workspaces actifs : {sum(1 for w in get_workspaces() if w['enabled'])}",
        f"  Tâches 7j : {len(all_tasks)}",
        f"  Charge semaine : {weekly['total']:.1f}h / {weekly['max']}h",
        f"  Statut : {'✅ OK' if weekly['status'] == 'ok' else '🚨 SURCHARGE'}",
    ]
    
    return "\n".join(lines)

def cmd_proposals(days: int = 7):
    """Show proposed backlog -> todo moves."""
    return generate_proposals_text(days)

def cmd_execute_moves(days: int = 7) -> str:
    """Execute all proposed moves (backlog -> todo) for tasks in the given window."""
    proposed = get_proposed_moves(days)

    if not proposed:
        return "Aucune tâche à mover."

    results = []
    for t in proposed:
        result = move_task_to_state(
            task_id=t["id"],
            workspace_slug=t["workspace"],
            project_id=t["project_id"],
            target_state="todo"
        )
        if "error" in result:
            results.append(f"❌ {t['title'][:40]} — {result['error']}")
        else:
            results.append(f"✅ {t['title'][:40]} → Todo")

    return "\n".join(results)


def cmd_estimate(task_id: str = None, workspace: str = None, user_h: float = None) -> str:
    """
    Propose an estimation for a task (or pending tasks).

    Usage:
      estimate                          # list pending estimations
      estimate <task_id> --workspace <ws>  # propose estimation for a task
      estimate <task_id> --workspace <ws> --user-h 3.5  # accept/modify and save
    """
    # List pending estimations
    if not task_id:
        pending = get_pending_estimations()
        if not pending:
            return "Aucune tâche en attente d'estimation.\nPour proposer une estimation: estimate <task_id> --workspace <slug>"
        lines = ["**📝 Tâches en attente d'estimation**", ""]
        for p in pending:
            lines.append(f"  • {p['title'][:50]} ({p['task_type']}/{p['energy']})")
            lines.append(f"    ↳ IA: {p['ia_proposed_h']}h | Accepté: {p['user_accepted_h']}h")
        return "\n".join(lines)

    # Fetch task from Plane to get full context
    from plane_manager import get_task_by_id
    task_data = get_task_by_id(workspace, task_id)
    if not task_data or "error" in task_data:
        return f"Task {task_id} non trouvée dans {workspace}"

    # Parse [Secretary] block if exists
    sec = parse_secretary_block(task_data.get("description", ""))
    task_data["task_type"] = sec.get("task_type") or "flexible"
    task_data["energy"] = sec.get("energy") or "light"
    if sec.get("estimation"):
        task_data["duration"] = sec["estimation"]

    # Propose estimation
    proposal = propose_estimation(task_data)

    lines = [
        f"**📊 Estimation pour:** {task_data['title'][:60]}",
        f"  Type: {proposal['task_type']} | Énergie: {proposal['energy']}",
        "",
        f"  **Proposition IA: {proposal['ia_proposed_h']}h**",
        f"  **Après historique: {proposal['adjusted_h']}h** ({proposal['confidence']} confidence)",
        f"  Pattern: {proposal['pattern']} (×{COMPLEXITY_KEYWORDS.get(proposal['pattern'], 1.0)})",
        f"  Raisonnement: {proposal['reasoning']}",
    ]

    # If user provided --user-h, save it
    if user_h is not None:
        result = save_estimation(
            task_id=task_id,
            workspace=workspace,
            ia_proposed_h=proposal["ia_proposed_h"],
            user_accepted_h=user_h,
            task_type=proposal["task_type"],
            energy=proposal["energy"],
            title=task_data["title"],
            project_name=task_data.get("project_name"),
        )
        if "error" in result:
            lines.append(f"\n❌ Erreur: {result['error']}")
        else:
            lines.append(f"\n✅ Estimation sauvegardée: {user_h}h (IA avait proposé {proposal['ia_proposed_h']}h)")

    return "\n".join(lines)


def cmd_complete(task_id: str, workspace: str, actual_h: float) -> str:
    """
    Complete a task and record actual duration.

    Usage:
      complete <task_id> --workspace <ws> --actual-h 3.5
    """
    result = complete_task(task_id, actual_h)
    if "error" in result:
        return f"❌ {result['error']}"
    return f"✅ {result['message']}"


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SecretaryIA Local Engine")
    parser.add_argument("command", choices=["recap", "status", "metadata", "proposals", "move", "done", "estimate", "complete"],
                        help="Command to run")
    parser.add_argument("--days", type=int, default=7, help="Number of days to include in recap")
    parser.add_argument("--workspace", type=str, help="Filter by workspace slug")
    parser.add_argument("--task-id", type=str, help="Task ID")
    parser.add_argument("--task-type", type=str, choices=["fixed", "flexible", "recurring"],
                        help="Task type (fixed/flexible/recurring)")
    parser.add_argument("--energy", type=str, choices=["intense", "light"],
                        help="Energy required (intense/light)")
    parser.add_argument("--duration", type=float, help="Override duration in hours")
    parser.add_argument("--actual-h", type=float, help="Actual duration in hours (for complete command)")
    parser.add_argument("--user-h", type=float, help="User-accepted estimation in hours (for estimate command)")
    
    args = parser.parse_args()
    
    if args.command == "recap":
        print(cmd_recap(days=args.days, workspace=args.workspace))
    elif args.command == "status":
        print(cmd_status())
    elif args.command == "metadata":
        if not args.task_id or not args.workspace:
            print("Error: --task-id and --workspace required for metadata command")
            sys.exit(1)
        kwargs = {}
        if args.task_type:
            kwargs["task_type"] = args.task_type
        if args.energy:
            kwargs["energy"] = args.energy
        if args.duration:
            kwargs["override_duration"] = args.duration
        print(cmd_set_metadata(args.task_id, args.workspace, **kwargs))
    elif args.command == "proposals":
        print(cmd_proposals(days=args.days))
    elif args.command == "move":
        print(cmd_execute_moves(days=args.days))
    elif args.command == "done":
        # Move a specific task to done
        if not args.task_id or not args.workspace:
            print("Error: --task-id and --workspace required for done command")
            sys.exit(1)
        # Need project_id for done - fetch task first
        from pprint import pprint
        print("done command requires project_id — use move command instead")
    elif args.command == "estimate":
        print(cmd_estimate(task_id=args.task_id, workspace=args.workspace, user_h=args.user_h))
    elif args.command == "complete":
        if not args.task_id or not args.workspace or not args.actual_h:
            print("Error: --task-id, --workspace, and --actual-h required for complete command")
            sys.exit(1)
        print(cmd_complete(args.task_id, args.workspace, args.actual_h))
