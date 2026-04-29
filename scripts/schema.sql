-- SecretaryIA local database schema
-- Source: Plane (read-only) + user metadata + estimation history

CREATE TABLE IF NOT EXISTS task_metadata (
    id TEXT PRIMARY KEY,              -- Plane task ID
    workspace TEXT NOT NULL,          -- aligodu / ease / st-digital
    project_id TEXT,
    project_name TEXT,
    task_type TEXT DEFAULT 'flexible', -- fixed / flexible / recurring
    energy TEXT DEFAULT 'light',       -- intense / light
    dependencies TEXT,                -- JSON array of task IDs
    override_deadline TEXT,           -- Manual override date
    override_duration REAL,           -- Manual duration (hours)
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS estimation_history (
    task_id TEXT PRIMARY KEY,         -- Plane task ID
    workspace TEXT NOT NULL,
    project_name TEXT,               -- For pattern matching
    title TEXT,                      -- Full task title for context
    task_type TEXT,                  -- DEV, gestion, admin, test, devops
    energy TEXT,                    -- intense, light
    ia_proposed_h REAL,             -- Estimation proposée par IA
    user_accepted_h REAL,           -- Estimation acceptée par user (peut = ia_proposed si acceptée)
    actual_h REAL,                  -- Durée réelle (fournie par user à la fin)
    completed INTEGER DEFAULT 0,     -- 0 = en cours, 1 = terminée
    completed_at TEXT,               -- Timestamp completion
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES task_metadata(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS type_bias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,         -- DEV, gestion, admin, test, devops
    project_pattern TEXT,            -- 'prisma', 'landing', 'api', 'auth', etc. (extrait du titre, lowercase)
    sample_count INTEGER DEFAULT 0,
    total_ratio REAL DEFAULT 0,      -- Somme des ratios actual/user_accepted
    avg_ratio REAL DEFAULT 1.0,      -- Ratio moyen actual/user_accepted (1.0 = parfait)
    std_dev REAL DEFAULT 0,         -- Ecart-type du ratio
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_type, project_pattern)
);

CREATE TABLE IF NOT EXISTS daily_recap (
    date TEXT PRIMARY KEY,            -- YYYY-MM-DD
    workspace TEXT NOT NULL,          -- Which workspace this recap covers
    recap_text TEXT,                  -- Generated recap content
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
    context TEXT,                     -- pro / perso / famille
    enabled INTEGER DEFAULT 1,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Projets (，每一个 projet dans Plane peut avoir un repo et des docs)
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,                  -- Plane project ID
    workspace TEXT NOT NULL,              -- aligodu / ease / st-digital
    name TEXT NOT NULL,                   -- Nom du projet
    identifier TEXT,                      -- Code projet (ex: PROJ)
    repo_url TEXT,                        -- URL du repo Git (si existe)
    local_path TEXT,                      -- Chemin local ~/develop/<project>/
    docs_path TEXT,                       -- Chemin vers docs/ (local_path/docs/)
    prd_page_id TEXT,                     -- Plane page ID pour le PRD
    plan_page_id TEXT,                    -- Plane page ID pour le plan d'implantation
    prd_file_path TEXT,                   -- Chemin vers PRD.md
    plan_file_path TEXT,                  -- Chemin vers implementation-plan.md
    prd_version TEXT DEFAULT 'v0.1',    -- Version actuelle du PRD
    plan_version TEXT DEFAULT 'v0.1',     -- Version actuelle du plan
    has_repo INTEGER DEFAULT 0,           -- 1 = a un repo Git
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Historique des versions docs (pour tracker les modifs manuelles)
CREATE TABLE IF NOT EXISTS doc_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,               -- 'prd' ou 'plan'
    file_path TEXT NOT NULL,              -- Chemin du fichier
    version TEXT NOT NULL,                 -- Numéro de version
    content_hash TEXT,                    -- Hash du contenu pour détecter mods
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_task_workspace ON task_metadata(workspace);
CREATE INDEX IF NOT EXISTS idx_task_deps ON task_metadata(dependencies);
CREATE INDEX IF NOT EXISTS idx_estimation_workspace ON estimation_history(workspace);
CREATE INDEX IF NOT EXISTS idx_estimation_type ON estimation_history(task_type);
CREATE INDEX IF NOT EXISTS idx_estimation_completed ON estimation_history(completed);
CREATE INDEX IF NOT EXISTS idx_bias_type ON type_bias(task_type);
CREATE INDEX IF NOT EXISTS idx_recap_date ON daily_recap(date);
CREATE INDEX IF NOT EXISTS idx_project_workspace ON projects(workspace);
CREATE INDEX IF NOT EXISTS idx_project_name ON projects(name);
CREATE INDEX IF NOT EXISTS idx_doc_versions_project ON doc_versions(project_id);
