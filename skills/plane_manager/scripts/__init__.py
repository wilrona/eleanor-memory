"""
plane-manager skill — high-level API.

Usage:
    from plane_manager import list_projects, create_task, get_task

All functions raise plane_manager.client.PlaneError subclasses on failure.
"""
from plane_manager.scripts.client import (
    PlaneError,
    PlaneAuthError,
    PlaneNotFoundError,
    PlaneRateLimitError,
    PlaneServerError,
    PlaneConnectionError,
    PlaneAPIError,
    cache_get,
    get_project_id,
    ALL_WORKSPACES,
    search_tasks_all_workspaces,
)

from plane_manager.scripts.projects import (
    list_projects,
    sync_projects_to_cache,
    get_project_summary,
    ensure_project,
    normalize_project,
    get_project_id,
    create_project,
    update_project,
)
from plane_manager.scripts.tasks import (
    list_tasks,
    get_task,
    create_task,
    update_task,
    set_task_state,
    delete_task,
    add_comment,
    create_sub_task,
    normalize_task,
)
from plane_manager.scripts.pages import (
    list_pages,
    get_page,
    create_page,
    update_page,
    delete_page,
)
from plane_manager.scripts.analysis import (
    analyze_velocity,
    find_overdue_tasks,
    detect_workload_bottlenecks,
    reschedule_suggestions,
)

__all__ = [
    # Errors
    "PlaneError", "PlaneAuthError", "PlaneNotFoundError",
    "PlaneRateLimitError", "PlaneServerError", "PlaneConnectionError",
    # Projects
    "list_projects", "sync_projects_to_cache", "get_project_summary",
    "ensure_project", "normalize_project", "get_project_id",
    "create_project", "update_project",
    # Tasks
    "list_tasks", "get_task", "create_task", "update_task",
    "set_task_state", "delete_task", "add_comment",
    "create_sub_task", "normalize_task",
    # Pages
    "list_pages", "get_page", "create_page", "update_page", "delete_page",
    # Analysis
    "analyze_velocity", "find_overdue_tasks",
    "detect_workload_bottlenecks", "reschedule_suggestions",
]
