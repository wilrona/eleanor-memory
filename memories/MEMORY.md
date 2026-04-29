APEX skill complet chargé: ~/.hermes/marketplace/apex/ (SKILL.md + 9 steps). Workflow 8 étapes: INIT→ISSUE→ANALYSE→WORKTREE→PLAN→EXECUTE→VALIDATE→EXAMINE→RESOLVE→TEST→PR. Params: -I (issue), -W (worktree), -A (auto), -X (examine), -T (test), -P (pr), -E (economy). Règle: -W+-A = PR auto. Frontend = ask user shadcn vs Gemini avant continue.
## Plane API access
- Token: plane_api_3983b540ae2645079fe7111eed6fc9c9
- Base URL: https://plane.ndironalds.org
- Workspaces: aligodu (accessible), ease (0 projects/no access), st-digital (0 projects/no access)
- Multi-ws search: `search_tasks_all_workspaces(query)` searches all 3 workspaces, only aligodu returns data
- `_build_url(base, ws, path)` adds `workspaces/{ws}/` prefix — path must be RELATIVE (e.g., "projects/" not "workspaces/{ws}/projects/")

## Implement workflow (secretary.py)
- `implement --query "text"` → search all workspaces → multiple results = propose choix
- `search_tasks(query)` → `search_tasks_all_workspaces()` → list[dict]
- `_implement_from_search(task)` → returns task context
