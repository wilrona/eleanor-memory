"""
Plane API Client — base module for plane-manager skill.
Handles auth, caching of UUIDs, and standardized error handling.
"""
import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────

CACHE_FILE = Path.home() / ".hermes/skills/plane-manager/cache.json"


def _load_env():
    """Read credentials from ~/.hermes/.env"""
    key = os.getenv("PLANE_API_KEY", "")
    base = os.getenv("PLANE_BASE_URL", "").rstrip("/")
    workspace = os.getenv("PLANE_WORKSPACE_SLUG", "")
    if not key or not base or not workspace:
        raise EnvironmentError(
            "Missing PLANE_API_KEY, PLANE_BASE_URL or PLANE_WORKSPACE_SLUG in ~/.hermes/.env"
        )
    return key, base, workspace


# ── Cache ─────────────────────────────────────────────────────────────────────

def _read_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _write_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def cache_get(key: str, sub_key: str) -> Optional[str]:
    """Get UUID from cache. Returns None if not cached."""
    c = _read_cache()
    return c.get(key, {}).get(sub_key)


def cache_set(key: str, sub_key: str, value: str):
    """Store a UUID in cache."""
    c = _read_cache()
    c.setdefault(key, {})[sub_key] = value
    _write_cache(c)


def cache_project(name: str, project_id: str, identifier: str = ""):
    cache_set("projects", name.lower(), project_id)
    if identifier:
        cache_set("project_ids", identifier.upper(), project_id)


def cache_label(project_id: str, label_name: str, label_id: str):
    cache_set(f"labels:{project_id}", label_name.lower(), label_id)


def cache_state(project_id: str, state_name: str, state_id: str):
    cache_set(f"states:{project_id}", state_name.lower().replace(" ", ""), state_id)


def get_project_id(name_or_identifier: str) -> Optional[str]:
    """Resolve project name or identifier to UUID."""
    c = _read_cache()
    # Try identifier first (uppercase)
    identifier = name_or_identifier.upper()
    if identifier in c.get("project_ids", {}):
        return c["project_ids"][identifier]
    # Try name (lowercase)
    name = name_or_identifier.lower()
    if name in c.get("projects", {}):
        return c["projects"][name]
    return None


def get_label_id(project_id: str, label_name: str) -> Optional[str]:
    return cache_get(f"labels:{project_id}", label_name.lower())


def get_state_id(project_id: str, state_name: str) -> Optional[str]:
    key = state_name.lower().replace(" ", "")
    return cache_get(f"states:{project_id}", key)


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _build_url(base: str, workspace: str, path: str) -> str:
    return f"{base}/api/v1/workspaces/{workspace}/{path.lstrip('/')}"


def api_request(
    method: str,
    path: str,
    data: Optional[dict] = None,
    params: Optional[dict] = None,
) -> dict:
    """
    Make an authenticated request to the Plane API.
    Raises PlaneError subclasses on failure.
    """
    key, base, workspace = _load_env()

    url = _build_url(base, workspace, path)
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    headers = {
        "X-API-Key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            if not body:
                return {"success": True}
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            err_body = json.loads(body_bytes)
        except Exception:
            err_body = {"detail": body_bytes.decode(errors="replace")}

        status = e.code
        detail = err_body.get("detail", str(err_body))

        if status == 401:
            raise PlaneAuthError(f"Clé API invalide (401): {detail}")
        if status == 403:
            raise PlaneAuthError(f"Accès refusé (403): {detail}")
        if status == 404:
            raise PlaneNotFoundError(f"Ressource introuvable (404): {detail}")
        if status == 429:
            raise PlaneRateLimitError(f"Rate limit atteint (429): {detail}")
        if status >= 500:
            raise PlaneServerError(f"Erreur serveur Plane ({status}): {detail}")
        raise PlaneAPIError(f"Erreur API ({status}): {detail}")
    except urllib.error.URLError as e:
        raise PlaneConnectionError(f"Connexion impossible à Plane: {e}")


# ── Exceptions ────────────────────────────────────────────────────────────────

class PlaneError(Exception):
    """Base exception for Plane operations."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

class PlaneAuthError(PlaneError):        pass  # 401/403
class PlaneNotFoundError(PlaneError):    pass  # 404
class PlaneRateLimitError(PlaneError):   pass  # 429
class PlaneServerError(PlaneError):     pass  # 5xx
class PlaneConnectionError(PlaneError):  pass  # network
class PlaneAPIError(PlaneError):        pass  # other HTTP errors
