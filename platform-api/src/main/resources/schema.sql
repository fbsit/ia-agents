CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS organizations (
    org_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, org_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (org_id) REFERENCES organizations(org_id)
);

CREATE INDEX IF NOT EXISTS idx_memberships_org_id ON memberships(org_id);

CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    status TEXT NOT NULL,
    published_version INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organizations(org_id)
);

CREATE INDEX IF NOT EXISTS idx_skills_org_company ON skills(org_id, company_id);

CREATE TABLE IF NOT EXISTS skill_versions (
    skill_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    definition_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    created_by_user_id TEXT NOT NULL,
    PRIMARY KEY (skill_id, version),
    FOREIGN KEY (skill_id) REFERENCES skills(skill_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_skill_versions_skill_created ON skill_versions(skill_id, created_at DESC);

CREATE TABLE IF NOT EXISTS flows (
    flow_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    graph_json TEXT NOT NULL,
    status TEXT NOT NULL,
    published_version INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (org_id) REFERENCES organizations(org_id)
);

CREATE INDEX IF NOT EXISTS idx_flows_org_company ON flows(org_id, company_id);

CREATE TABLE IF NOT EXISTS flow_versions (
    flow_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    graph_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    created_by_user_id TEXT NOT NULL,
    PRIMARY KEY (flow_id, version),
    FOREIGN KEY (flow_id) REFERENCES flows(flow_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_flow_versions_flow_created ON flow_versions(flow_id, created_at DESC);
