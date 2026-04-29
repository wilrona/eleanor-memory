"""
Plane Projects module — list, sync, and cache project data.
"""
from plane_manager.scripts.client import api_request, cache_project, get_project_id


def list_projects(workspace: str = None) -> list[dict]:
    """
    List all projects in the workspace.
    Returns list of normalized project dicts.
    """
    data = api_request("GET", "projects/")
    results = []
    for p in data.get("results", []):
        results.append(normalize_project(p))
    return results


def normalize_project(p: dict) -> dict:
    """Convert raw Plane project to clean dict."""
    return {
        "id": p["id"],
        "name": p["name"],
        "identifier": p["identifier"],
        "description": p.get("description", ""),
        "is_member": p.get("is_member", False),
        "total_members": p.get("total_members", 0),
        "total_cycles": p.get("total_cycles", 0),
        "created_at": p.get("created_at"),
    }


def sync_projects_to_cache():
    """
    Fetch all projects and store their IDs in cache.
    Call this once after setup or when cache is stale.
    """
    data = api_request("GET", "projects/")
    for p in data.get("results", []):
        cache_project(p["name"], p["id"], p["identifier"])
    return len(data.get("results", []))


def get_project_summary(project_id: str) -> dict:
    """
    Get a project with task stats: open, in_progress, done, overdue.
    """
    data = api_request("GET", f"projects/{project_id}/")
    work_items = api_request("GET", f"projects/{project_id}/work-items/", params={"limit": 500})

    states = api_request("GET", f"projects/{project_id}/states/")
    state_map = {s["id"]: s for s in states.get("results", [])}

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    open_count = in_progress = done = cancelled = overdue = 0
    for wi in work_items.get("results", []):
        state = state_map.get(wi.get("state") or "", {})
        group = state.get("group", "")
        if group in ("completed", "cancelled"):
            continue
        open_count += 1
        if group == "started":
            in_progress += 1
        # Check overdue
        target = wi.get("target_date")
        if target and group != "completed":
            from datetime import datetime
            try:
                due = datetime.fromisoformat(target.replace("Z", "+00:00"))
                if due < now:
                    overdue += 1
            except Exception:
                pass

    return {
        "id": project_id,
        "name": data.get("name"),
        "identifier": data.get("identifier"),
        "open": open_count,
        "in_progress": in_progress,
        "done": done,
        "overdue": overdue,
        "total_work_items": work_items.get("total_count", 0),
    }


def ensure_project(name_or_id: str) -> str:
    """
    Resolve a project name, identifier, or UUID to UUID.
    If not in cache, sync from API.
    """
    import re
    # If already a UUID, validate format and return directly
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", name_or_id, re.I):
        return name_or_id

    pid = get_project_id(name_or_id)
    if pid:
        return pid
    sync_projects_to_cache()
    pid = get_project_id(name_or_id)
    if not pid:
        from plane_manager.scripts.client import PlaneNotFoundError
        raise PlaneNotFoundError(f"Projet introuvable: {name_or_id}")
    return pid


def create_project(
    name: str,
    description: str = "",
    identifier: str = None,
    color: str = None,
) -> dict:
    """
    Create a new project in the workspace.

    Args:
        name: Project name
        description: Project description (plain text or markdown)
        identifier: 4-char project code (e.g. "PROJ"). Auto-generated from name if not provided.
        color: Project color hex code (e.g. "#FF5733")

    Returns:
        Normalized project dict with id, name, identifier, etc.
    """
    # Auto-generate identifier from name if not provided
    if identifier is None:
        identifier = name.upper()[:4]

    payload = {
        "name": name,
        "description": description,
        "identifier": identifier.upper(),
    }
    if color:
        payload["color"] = color

    data = api_request("POST", "projects/", data=payload)
    project = normalize_project(data)
    # Cache it
    cache_project(name, project["id"], project["identifier"])
    return project


def update_project(
    project_id: str,
    name: str = None,
    description: str = None,
    identifier: str = None,
    color: str = None,
) -> dict:
    """
    Update an existing project.

    Args:
        project_id: UUID of the project
        name: New name (optional)
        description: New description (optional)
        identifier: New 4-char code (optional)
        color: New color hex (optional)

    Returns:
        Normalized updated project dict.
    """
    payload = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description
    if identifier is not None:
        payload["identifier"] = identifier.upper()
    if color is not None:
        payload["color"] = color

    data = api_request("PATCH", f"projects/{project_id}/", data=payload)
    project = normalize_project(data)
    # Update cache
    cache_project(project["name"], project["id"], project["identifier"])
    return project
