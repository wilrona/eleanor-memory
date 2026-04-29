"""
Plane Analysis module — velocity, estimate vs real time, recurring delays.
"""
from datetime import datetime, timezone, timedelta
from plane_manager.scripts.client import api_request


def get_tasks_with_time_logs(project_id: str = None, limit: int = 200) -> list[dict]:
    """
    Fetch work items that have time tracked.
    Plane stores time in cycles/time-slots — this is a best-effort
    estimation based on estimate_point vs completion time.
    """
    if project_id:
        data = api_request("GET", f"projects/{project_id}/work-items/",
                           params={"limit": limit})
    else:
        data = api_request("GET", "work-items/", params={"limit": limit})

    return data.get("results", [])


def analyze_velocity(project_id: str = None) -> dict:
    """
    Compare estimate vs actual time for completed tasks.
    Returns per-project stats: avg_estimate_hours, avg_actual_days,
    accuracy_score, tasks_analyzed.
    """
    tasks = get_tasks_with_time_logs(project_id, limit=300)

    completed = []
    for wi in tasks:
        state_id = wi.get("state")
        # Skip if not completed (we don't have state_map here, use completed_at)
        if wi.get("completed_at") and wi.get("estimate_point"):
            completed.append(wi)

    if not completed:
        return {"tasks_analyzed": 0, "message": "Aucune tâche terminée avec estimate"}

    project_stats = {}
    for wi in completed:
        pid = wi.get("project")
        estimate_value = _parse_estimate(wi.get("estimate_point"))
        created = wi.get("created_at", "")
        completed_at = wi.get("completed_at", "")

        try:
            c = datetime.fromisoformat(created.replace("Z", "+00:00"))
            d = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            actual_days = (d - c).total_seconds() / 86400
        except Exception:
            actual_days = None

        if estimate_value and actual_days is not None:
            project_stats.setdefault(pid, []).append({
                "id": wi["id"],
                "name": wi["name"],
                "estimate_hours": estimate_value,
                "actual_days": round(actual_days, 1),
                "ratio": actual_days / estimate_value if estimate_value else None,
            })

    summary = {}
    for pid, items in project_stats.items():
        if not items:
            continue
        avg_est = sum(i["estimate_hours"] for i in items) / len(items)
        avg_actual = sum(i["actual_days"] for i in items) / len(items)
        accuracy = sum(
            1 for i in items if i["ratio"] and 0.5 <= i["ratio"] <= 1.5
        ) / len(items)

        summary[pid] = {
            "tasks": len(items),
            "avg_estimate_hours": round(avg_est, 1),
            "avg_actual_days": round(avg_actual, 1),
            "accuracy_pct": round(accuracy * 100, 0),
            "items": items[:5],  # first 5 for detail
        }

    return summary


def find_overdue_tasks(project_id: str = None, days_threshold: int = 0) -> list[dict]:
    """
    Find tasks past their target_date that are not Done/Cancelled.
    Returns list of overdue tasks sorted by most overdue first.
    """
    tasks = get_tasks_with_time_logs(project_id, limit=300)
    now = datetime.now(timezone.utc)

    overdue = []
    # Completed state IDs (we'll filter by group)
    for wi in tasks:
        if wi.get("completed_at"):
            continue  # already done
        target = wi.get("target_date")
        if not target:
            continue
        try:
            due = datetime.fromisoformat(target.replace("Z", "+00:00"))
        except Exception:
            continue
        if due < now:
            days_late = (now - due).days
            if days_late >= days_threshold:
                overdue.append({
                    "id": wi["id"],
                    "name": wi["name"],
                    "priority": wi.get("priority", "none"),
                    "target_date": target,
                    "days_late": days_late,
                    "project_id": wi.get("project"),
                })

    overdue.sort(key=lambda x: x["days_late"], reverse=True)
    return overdue


def detect_workload_bottlenecks(project_id: str = None, days_ahead: int = 7) -> dict:
    """
    Show days in the next N days that have the most tasks due.
    Returns a dict: {date_string: [task_list]}
    """
    tasks = get_tasks_with_time_logs(project_id, limit=300)
    from collections import defaultdict

    future_deadlines = defaultdict(list)
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)

    for wi in tasks:
        if wi.get("completed_at"):
            continue
        target = wi.get("target_date")
        if not target:
            continue
        try:
            due = datetime.fromisoformat(target.replace("Z", "+00:00"))
        except Exception:
            continue
        if now <= due <= cutoff:
            date_key = due.strftime("%Y-%m-%d")
            future_deadlines[date_key].append({
                "id": wi["id"],
                "name": wi["name"],
                "priority": wi.get("priority", "none"),
                "estimate": wi.get("estimate_point"),
            })

    # Sort dates
    sorted_days = sorted(future_deadlines.items(), key=lambda x: x[0])
    return {k: v for k, v in sorted_days}


def reschedule_suggestions(project_id: str = None, max_hours_per_day: float = 4.0) -> list[dict]:
    """
    Suggest replanification when overloaded.
    Returns tasks that should be moved to later dates.
    """
    bottlenecks = detect_workload_bottlenecks(project_id, days_ahead=14)
    suggestions = []

    for date, tasks in bottlenecks.items():
        total_hours = 0
        for t in tasks:
            est = _parse_estimate(t.get("estimate"))
            if est:
                total_hours += est

        if total_hours > max_hours_per_day:
            overload = total_hours - max_hours_per_day
            suggestions.append({
                "date": date,
                "task_count": len(tasks),
                "total_hours": round(total_hours, 1),
                "overload_hours": round(overload, 1),
                "tasks": [t["name"] for t in tasks],
            })

    return suggestions


# ── Estimate parser ──────────────────────────────────────────────────────────

def _parse_estimate(estimate) -> float:
    """
    Convert estimate point to hours.
    Tuples like ('estimate', 'value', 'hours') or simple strings.
    Returns float in hours, or None if unparseable.
    """
    if not estimate:
        return None
    if isinstance(estimate, (int, float)):
        return float(estimate)
    if isinstance(estimate, str):
        # Try parsing "2h", "1j", "3j", etc.
        s = estimate.strip().lower()
        if s.endswith("h"):
            try:
                return float(s[:-1])
            except ValueError:
                pass
        if s.endswith("j") or s.endswith("d"):
            try:
                return float(s[:-1]) * 8
            except ValueError:
                pass
        if s.endswith("s") or s.endswith("semaine") or s.endswith("w"):
            try:
                return float(s[:-1]) * 40
            except ValueError:
                pass
        try:
            return float(s)
        except ValueError:
            return None
    return None
