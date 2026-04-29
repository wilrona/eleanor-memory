"""
Plane Pages module — CRUD for project wiki pages.
"""
from plane_manager.scripts.client import api_request, PlaneNotFoundError


def list_pages(project_id: str) -> list[dict]:
    """
    List all pages in a project.
    Returns list of normalized page dicts.
    """
    data = api_request("GET", f"projects/{project_id}/pages/")
    return [normalize_page(p) for p in data.get("results", [])]


def get_page(page_id: str, project_id: str) -> dict:
    """
    Get a single page by ID within a project.
    """
    data = api_request("GET", f"projects/{project_id}/pages/{page_id}/")
    return normalize_page(data)


def create_page(
    project_id: str,
    name: str,
    description: str = "",
    description_html: str = "",
) -> dict:
    """
    Create a new page in a project.

    Args:
        project_id: UUID of the project
        name: Page title
        description: Plain text description (used if description_html not provided)
        description_html: HTML description (recommended for formatted content)

    Returns:
        Normalized page dict with id, name, description, etc.
    """
    payload = {"name": name}
    if description_html:
        payload["description_html"] = description_html
    elif description:
        payload["description"] = description

    data = api_request("POST", f"projects/{project_id}/pages/", data=payload)
    return normalize_page(data)


def update_page(
    page_id: str,
    project_id: str,
    name: str = None,
    description: str = None,
    description_html: str = None,
) -> dict:
    """
    Update an existing page.

    Args:
        page_id: UUID of the page
        project_id: UUID of the project (needed for URL construction)
        name: New title (optional)
        description: New plain text description (optional)
        description_html: New HTML description (recommended for formatted content)

    Returns:
        Normalized updated page dict.
    """
    payload = {}
    if name is not None:
        payload["name"] = name
    if description_html is not None:
        payload["description_html"] = description_html
    elif description is not None:
        payload["description"] = description

    data = api_request("PATCH", f"projects/{project_id}/pages/{page_id}/", data=payload)
    return normalize_page(data)


def delete_page(page_id: str, project_id: str) -> bool:
    """
    Delete a page. Returns True on success.
    """
    api_request("DELETE", f"projects/{project_id}/pages/{page_id}/")
    return True


def normalize_page(p: dict) -> dict:
    """
    Convert raw Plane page to clean dict.
    """
    return {
        "id": p["id"],
        "name": p.get("name", ""),
        "description": p.get("description", ""),
        "description_html": p.get("description_html", ""),
        "project_id": p.get("project"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "created_by": p.get("created_by"),
        "owned_by": p.get("owned_by"),
        "color": p.get("color"),
        "logo_url": p.get("logo_url"),
        "is_favorite": p.get("is_favorite", False),
        "parent_id": p.get("parent"),
        "workspace": p.get("workspace"),
    }
