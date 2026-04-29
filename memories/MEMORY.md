Structure develop: ~/develop/<projet>/docs/<fichiers>. Si projet a repo Git → clone dans develop/ (donc docs/ est versionné). Si pas de repo → on crée la structure manuellement.

Wiki marketplace: https://github.com/wilrona/personal_market — 3 plugins: dev-skill (apex, frontend-design-pro, prd-generator), essential-workflows, ralph-pro. Le dossier /develop/<projet>/docs/ est dans le repo (donc versionné).

References stockées dans SQLite (table projects) ET dans description du projet Plane (liens vers docs/ et pages Plane).

Plane API key actuelle: plane_api_3983b540ae2645079fe7111eed6fc9c9. URL: https://plane.ndironalds.org. Workspaces: aligodu (perso), ease (pro), st-digital (pro).

Le skill plane_manager a été enrichi: create_project, update_project, create_page, list_pages, get_page, update_page, delete_page. secretary.py utilise maintenant plane_manager pour les ops Plane.

PRD workflow: quand user demande un projet, je pose les questions du prd-generator (14 questions commun + 7-13 par type), génère le PRD markdown → ~/develop/<projet>/docs/PRD.md, crée projet Plane + page wiki PRD, stocke refs dans SQLite.