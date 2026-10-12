CREATE TABLE employees (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 120),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    created_utc_us INTEGER NOT NULL
);
CREATE TABLE workstation_assignments (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    employee_id TEXT NOT NULL REFERENCES employees(id),
    effective_from_utc_us INTEGER NOT NULL,
    effective_to_utc_us INTEGER,
    source TEXT NOT NULL CHECK (source = 'manual_assignment'),
    CHECK (effective_to_utc_us IS NULL OR effective_to_utc_us > effective_from_utc_us)
);
CREATE INDEX assignment_period ON workstation_assignments(workspace_id,effective_from_utc_us);
CREATE TRIGGER assignment_no_overlap BEFORE INSERT ON workstation_assignments
WHEN EXISTS (
    SELECT 1 FROM workstation_assignments old WHERE old.workspace_id = NEW.workspace_id
      AND old.effective_from_utc_us < COALESCE(NEW.effective_to_utc_us,9223372036854775807)
      AND NEW.effective_from_utc_us < COALESCE(old.effective_to_utc_us,9223372036854775807)
)
BEGIN SELECT RAISE(ABORT,'overlapping workstation assignment'); END;
CREATE TABLE runtime_migration_checksums (
    version INTEGER PRIMARY KEY REFERENCES schema_migrations(version),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64)
);
