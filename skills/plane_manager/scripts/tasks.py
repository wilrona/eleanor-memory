"""
Plane Work Items (Tasks) module.
Create, read, update, delete, and filter tasks.
"""
from datetime import datetime, timezone
import re
from plane_manager.scripts.client import (
    api_request,
    cache_state,
    cache_label,
    get_state_id,
    get_label_id,
    PlaneNotFoundError,
)

# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_task(wi: dict, state_map: dict = None, label_map: dict = None) -> dict:
    """
    Convert raw Plane work-item to clean dict.
    Uses state_map and label_map (id -> name) if provided.
    """
    state_id = wi.get("state") or ""
    state_name = (state_map or {}).get(state_id, {}).get("name", state_id) if state_map else state_id

    label_ids = wi.get("labels") or []
    if label_map and label_ids:
        # API can return either UUIDs or full label dicts
        try:
            label_names = []
            for lid in label_ids:
                if isinstance(lid, dict):
                    label_names.append(lid.get("name", str(lid)))
                else:
                    label_names.append(label_map.get(lid, {}).get("name", lid))
        except (TypeError, KeyError):
            label_names = label_ids
    else:
        label_names = [l.get("name") if isinstance(l, dict) else l for l in label_ids]

    # Extract estimate from description_html (stored as "Estim : Xh" or "Estimé : Xh")
    # The HTML is "<p><strong>Estim :</strong> Xh</p>" — we strip tags first.
    estimate_from_desc = None
    desc_html = wi.get("description_html", "") or ""
    # Strip HTML tags to get plain text
    plain = re.sub(r"<[^>]+>", " ", desc_html)
    plain = re.sub(r"\s+", " ", plain).strip()
    # Match "Estim(e): Xh" or "Estim(e) : Xh" etc.
    for pat in (
        r"Estim(?:é|e)?\s*:\s*(\d+(?:\.\d+)?)\s*h",
        r"ESTIM(?:É|E)?\s*:\s*(\d+(?:\.\d+)?)\s*H",
    ):
        m = re.search(pat, plain, re.IGNORECASE)
        if m:
            estimate_from_desc = float(m.group(1))
            break

    return {
        "id": wi["id"],
        "name": wi.get("name", ""),
        "description": desc_html,
        "state": state_name,
        "state_id": state_id,
        "priority": wi.get("priority", "none"),
        "start_date": wi.get("start_date"),
        "target_date": wi.get("target_date"),
        "estimate": estimate_from_desc if m else wi.get("estimate_point"),
        "labels": label_names,
        "project_id": wi.get("project"),
        "parent_id": wi.get("parent"),
        "assignees": wi.get("assignees", []),
        "sequence_id": wi.get("sequence_id"),
        "created_at": wi.get("created_at"),
        "updated_at": wi.get("updated_at"),
        "completed_at": wi.get("completed_at"),
    }


def _build_state_map(project_id: str) -> dict:
    data = api_request("GET", f"projects/{project_id}/states/")
    smap = {}
    for s in data.get("results", []):
        smap[s["id"]] = s
        # Cache all states
        cache_state(project_id, s["name"], s["id"])
    return smap


def _build_label_map(project_id: str) -> dict:
    data = api_request("GET", f"projects/{project_id}/labels/")
    lmap = {}
    for l in data.get("results", []):
        lmap[l["id"]] = l
        cache_label(project_id, l["name"], l["id"])
    return lmap


# ── Reading ─────────────────────────────────────────────────────────────────

def list_tasks(
    project_id: str = None,
    state: str = None,
    priority: str = None,
    label: str = None,
    assignee: str = None,
    target_date_from: str = None,
    target_date_to: str = None,
    limit: int = 100,
) -> list[dict]:
    """
    List work items for a project.
    project_id can be a name, identifier, or UUID.
    """
    if not project_id:
        raise ValueError("project_id is required. Use ensure_project(name) to resolve.")
    from plane_manager.scripts.projects import ensure_project
    pid = ensure_project(project_id)

    params = {"limit": limit}
    if state:
        sid = get_state_id(pid, state)
        if sid:
            params["state"] = sid
    if priority:
        params["priority"] = priority
    if assignee:
        params["assignees"] = assignee
    if target_date_from:
        params["target_date__gte"] = target_date_from
    if target_date_to:
        params["target_date__lte"] = target_date_to

    path = f"projects/{pid}/work-items/"
    data = api_request("GET", path, params=params)
    results = []

    smap = _build_state_map(pid)
    lmap = _build_label_map(pid)

    for wi in data.get("results", []):
        n = normalize_task(wi, smap, lmap)
        # Apply label filter client-side (API doesn't always support it)
        if label:
            if label.lower() not in [l.lower() for l in n["labels"]]:
                continue
        results.append(n)

    return results


def get_task(task_id: str, project_id: str = None) -> dict:
    """
    Get full task details including sub-items and comments.
    project_id is REQUIRED — Plane's API requires project context for work items.
    """
    if not project_id:
        raise ValueError(
            "project_id is required for get_task. "
            "Use ensure_project(name) to resolve a name to ID first."
        )

    smap = _build_state_map(project_id)
    lmap = _build_label_map(project_id)

    wi = api_request("GET", f"projects/{project_id}/work-items/{task_id}/")
    n = normalize_task(wi, smap, lmap)

    # Fetch sub-items
    try:
        children = api_request("GET", f"projects/{project_id}/work-items/{task_id}/sub-items/", params={"limit": 100})
        n["sub_items"] = [
            normalize_task(c, smap, lmap) for c in children.get("results", [])
        ]
    except Exception:
        n["sub_items"] = []

    # Fetch comments
    try:
        comments = api_request("GET", f"projects/{project_id}/work-items/{task_id}/comments/", params={"limit": 100})
        n["comments"] = [
            {"id": c["id"], "text": c.get("comment_html", ""), "created_at": c.get("created_at")}
            for c in comments.get("results", [])
        ]
    except Exception:
        n["comments"] = []

    return n


# ── Writing ─────────────────────────────────────────────────────────────────

def create_task(
    name: str,
    project_id: str = None,
    description: str = "",
    state: str = None,
    priority: str = "none",
    start_date: str = None,
    target_date: str = None,
    labels: list[str] = None,
    parent_id: str = None,
    estimate: str = None,
) -> dict:
    """
    Create a new work item.
    project_id: UUID or name/identifier (will be resolved)
    state: state name like 'Todo', 'In Progress' (resolved to UUID)
    labels: list of label names (resolved to UUIDs)
    estimate: currently stored as-is (API estimate system not yet mapped)
    """
    from plane_manager.scripts.projects import ensure_project

    if project_id:
        pid = ensure_project(project_id) if not _is_uuid(project_id) else project_id
    else:
        raise ValueError("project_id is required")

    payload = {
        "name": name,
        "project": pid,
        "description_html": f"<p>{description}</p>",
        "priority": priority,
    }

    if state:
        sid = get_state_id(pid, state) or _get_state_id_by_name(pid, state)
        if sid:
            payload["state"] = sid

    if start_date:
        payload["start_date"] = start_date
    if target_date:
        payload["target_date"] = target_date
    if parent_id:
        payload["parent"] = parent_id
    if estimate is not None:
        # Plane n'a pas de système d'estimates accessible via API.
        # On stocke l'estimée en heures dans la description (sans accent pour éviter les pb d'encodage).
        est_h = f"{estimate}h"
        est_html = f"<p><strong>Estim :</strong> {est_h}</p>"
        if description:
            payload["description_html"] = f"<p>{description}</p>{est_html}"
        else:
            payload["description_html"] = est_html
    elif description:
        payload["description_html"] = f"<p>{description}</p>"

    # Resolve label names to UUIDs
    if labels:
        lmap = _build_label_map(pid)
        label_ids = []
        for lbl in labels:
            for lid, ldata in lmap.items():
                if ldata["name"].lower() == lbl.lower():
                    label_ids.append(lid)
                    break
        payload["labels"] = label_ids

    result = api_request("POST", f"projects/{pid}/work-items/", data=payload)
    # Resolve state/label names in the returned dict
    smap = _build_state_map(pid)
    lmap = _build_label_map(pid)
    return normalize_task(result, smap, lmap)


def update_task(
    task_id: str,
    project_id: str = None,
    name: str = None,
    description: str = None,
    state: str = None,
    priority: str = None,
    start_date: str = None,
    target_date: str = None,
    labels: list[str] = None,
) -> dict:
    """Update any field of a work item."""
    if not project_id:
        raise ValueError(
            "project_id is required for update_task. "
            "Use ensure_project(name) to resolve a name to ID first."
        )

    # Always build maps for normalize_task
    smap = _build_state_map(project_id)
    lmap = _build_label_map(project_id)

    payload = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description_html"] = f"<p>{description}</p>"
    if state:
        sid = get_state_id(project_id, state) or _get_state_id_by_name(project_id, state)
        if sid:
            payload["state"] = sid
    if priority:
        payload["priority"] = priority
    if start_date is not None:
        payload["start_date"] = start_date
    if target_date is not None:
        payload["target_date"] = target_date

    if labels is not None:
        label_ids = []
        for lbl in labels:
            for lid, ldata in lmap.items():
                if ldata["name"].lower() == lbl.lower():
                    label_ids.append(lid)
                    break
        payload["labels"] = label_ids

    result = api_request("PATCH", f"projects/{project_id}/work-items/{task_id}/", data=payload)
    return normalize_task(result, smap, lmap)


def set_task_state(task_id: str, state_name: str, project_id: str) -> dict:
    """Change a task's state. Convenience method."""
    return update_task(task_id, project_id, state=state_name)


def delete_task(task_id: str, project_id: str):
    """Archive (soft delete) a work item."""
    api_request("DELETE", f"projects/{project_id}/work-items/{task_id}/")


def add_comment(task_id: str, text: str, project_id: str) -> dict:
    """Add a comment to a task."""
    result = api_request("POST", f"projects/{project_id}/work-items/{task_id}/comments/", data={
        "comment_html": f"<p>{text}</p>",
    })
    return {"id": result["id"], "text": text, "created_at": result.get("created_at")}


def create_sub_task(
    name: str,
    parent_id: str,
    project_id: str = None,
    description: str = "",
    priority: str = "none",
) -> dict:
    """Create a sub-item (child task)."""
    if not project_id:
        wi = api_request("GET", f"work-items/{parent_id}/")
        project_id = wi.get("project")
    return create_task(
        name=name,
        project_id=project_id,
        description=description,
        priority=priority,
        parent_id=parent_id,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_uuid(s: str) -> bool:
    import re
    return bool(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", s, re.I))

def _get_state_id_by_name(project_id: str, name: str) -> str:
    """Fallback: fetch all states and find by name."""
    data = api_request("GET", f"projects/{project_id}/states/")
    for s in data.get("results", []):
        if s["name"].lower() == name.lower():
            cache_state(project_id, s["name"], s["id"])
            return s["id"]
    raise PlaneNotFoundError(f"State introuvable: {name}")
