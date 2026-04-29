# Eleanor Memory

## Infrastructure Fixes

### Plane redirect :8080 ( résolu le 29/04/2026 )
**Problème:** Plane redirectait vers `http://plane.ndironalds.org:8080` après le chargement, causant une erreur de connexion.

**Cause:** `WEB_URL` dans `/var/plane/docker-compose.yml` pointait vers `http://plane.ndironalds.org:8080`.

**Fix:** Changer `WEB_URL` de `http://plane.ndironalds.org:8080` → `https://plane.ndironalds.org` (9 occurrences dans api, automation-consumer, beat-worker, migrator, outbox-poller, worker, Space, web).

**Note:** Les autres variables avec `:8080` (PI_BASE_URL, PLANE_API_HOST, PLANE_FRONTEND_URL, PLANE_OAUTH_REDIRECT_URI) peuvent rester avec `:8080` — le proxy Docker route correctement. Seul WEB_URL necessitait le changement.

**Rollback:** Remettre `WEB_URL: http://plane.ndironalds.org:8080` dans toutes les sections du docker-compose.yml et restart.

**Chemin fichier:** `/var/plane/docker-compose.yml`
