-- Reference schema for design review. Not an installed application database.
-- Runtime requires a local SQLite with JSON functions and window functions.
-- Every runtime connection must enable foreign_keys and a bounded busy_timeout.
-- WAL and synchronous policy are configured on the actual disk-backed database.
PRAGMA foreign_keys = ON;

BEGIN;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_utc_us INTEGER NOT NULL
);

CREATE TABLE database_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    instance_id TEXT NOT NULL UNIQUE,
    created_utc_us INTEGER NOT NULL,
    restored_from_backup_id TEXT
);

CREATE TABLE sites (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_utc_us INTEGER NOT NULL
);

CREATE TABLE cameras (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    stream_endpoint TEXT NOT NULL,
    credential_ref TEXT,
    enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
    revision INTEGER NOT NULL CHECK (revision > 0),
    settings_json TEXT NOT NULL CHECK (json_valid(settings_json)),
    created_utc_us INTEGER NOT NULL
);

CREATE TABLE model_artifacts (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    artifact_path TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    created_utc_us INTEGER NOT NULL
);

CREATE TABLE rule_sets (
    id TEXT PRIMARY KEY,
    settings_json TEXT NOT NULL CHECK (json_valid(settings_json)),
    created_utc_us INTEGER NOT NULL
);

CREATE TABLE schedule_versions (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    timezone TEXT NOT NULL,
    rules_json TEXT NOT NULL CHECK (json_valid(rules_json)),
    effective_from_utc_us INTEGER NOT NULL,
    effective_to_utc_us INTEGER,
    CHECK (effective_to_utc_us IS NULL OR effective_to_utc_us > effective_from_utc_us),
    UNIQUE (site_id, revision)
);

CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('desk','room','area')),
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    exclusive_group TEXT,
    monitoring_from_utc_us INTEGER NOT NULL,
    monitoring_to_utc_us INTEGER,
    CHECK (monitoring_to_utc_us IS NULL OR monitoring_to_utc_us > monitoring_from_utc_us)
);

CREATE TABLE workspace_configurations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    camera_id TEXT NOT NULL REFERENCES cameras(id),
    rule_set_id TEXT NOT NULL REFERENCES rule_sets(id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    polygon_json TEXT NOT NULL CHECK (json_valid(polygon_json)),
    reference_width INTEGER NOT NULL CHECK (reference_width > 0),
    reference_height INTEGER NOT NULL CHECK (reference_height > 0),
    scene_fingerprint TEXT NOT NULL,
    effective_from_utc_us INTEGER NOT NULL,
    effective_to_utc_us INTEGER,
    CHECK (effective_to_utc_us IS NULL OR effective_to_utc_us > effective_from_utc_us),
    UNIQUE (workspace_id, revision),
    UNIQUE (id, workspace_id)
);
CREATE UNIQUE INDEX workspace_one_active_config
    ON workspace_configurations(workspace_id) WHERE effective_to_utc_us IS NULL;

CREATE TABLE engine_runs (
    id TEXT PRIMARY KEY,
    model_artifact_id TEXT NOT NULL REFERENCES model_artifacts(id),
    engine_version TEXT NOT NULL,
    runtime_manifest_json TEXT NOT NULL CHECK (json_valid(runtime_manifest_json)),
    started_utc_us INTEGER NOT NULL,
    ended_utc_us INTEGER,
    termination_reason TEXT,
    CHECK (ended_utc_us IS NULL OR ended_utc_us >= started_utc_us)
);

CREATE TABLE camera_generations (
    id TEXT PRIMARY KEY,
    engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
    camera_id TEXT NOT NULL REFERENCES cameras(id),
    generation INTEGER NOT NULL CHECK (generation > 0),
    started_utc_us INTEGER NOT NULL,
    ended_utc_us INTEGER,
    CHECK (ended_utc_us IS NULL OR ended_utc_us >= started_utc_us),
    UNIQUE (engine_run_id, camera_id, generation),
    UNIQUE (id, camera_id)
);

CREATE TABLE event_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
    producer_seq INTEGER NOT NULL CHECK (producer_seq > 0),
    event_type TEXT NOT NULL,
    observed_utc_us INTEGER NOT NULL,
    recorded_utc_us INTEGER NOT NULL,
    payload_version INTEGER NOT NULL CHECK (payload_version > 0),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    UNIQUE (engine_run_id, producer_seq)
);
CREATE INDEX event_run_order ON event_log(engine_run_id, producer_seq);

CREATE TABLE command_receipts (
    request_id TEXT PRIMARY KEY,
    command_name TEXT NOT NULL,
    parameters_sha256 TEXT NOT NULL CHECK (length(parameters_sha256) = 64),
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    committed_event_seq INTEGER NOT NULL REFERENCES event_log(seq),
    committed_utc_us INTEGER NOT NULL
);

CREATE TABLE zone_intervals (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    configuration_id TEXT NOT NULL,
    engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
    state TEXT NOT NULL CHECK (state IN ('OCCUPIED','EMPTY','UNKNOWN')),
    observed_count INTEGER,
    reason TEXT,
    start_utc_us INTEGER NOT NULL,
    end_utc_us INTEGER,
    evidence_until_utc_us INTEGER NOT NULL,
    created_event_seq INTEGER NOT NULL REFERENCES event_log(seq),
    updated_event_seq INTEGER NOT NULL REFERENCES event_log(seq),
    FOREIGN KEY (configuration_id, workspace_id)
        REFERENCES workspace_configurations(id, workspace_id),
    CHECK (evidence_until_utc_us >= start_utc_us),
    CHECK (end_utc_us IS NULL OR end_utc_us > start_utc_us),
    CHECK (end_utc_us IS NULL OR end_utc_us = evidence_until_utc_us),
    CHECK (updated_event_seq >= created_event_seq),
    CHECK (
        (state = 'UNKNOWN' AND observed_count IS NULL AND reason IS NOT NULL)
        OR (state = 'EMPTY' AND observed_count IS NOT NULL AND observed_count = 0)
        OR (state = 'OCCUPIED' AND (observed_count IS NULL OR observed_count >= 1))
    )
);
CREATE INDEX zone_interval_range ON zone_intervals(workspace_id, start_utc_us, end_utc_us);
CREATE UNIQUE INDEX zone_one_open_interval
    ON zone_intervals(workspace_id) WHERE end_utc_us IS NULL;

-- Interval coverage and configuration boundaries also require domain validation.
-- The triggers reject overlap, including across two configurations of a workspace.
CREATE TRIGGER zone_no_overlap_insert BEFORE INSERT ON zone_intervals
WHEN EXISTS (
    SELECT 1 FROM zone_intervals old
    WHERE old.workspace_id = NEW.workspace_id
      AND old.start_utc_us < COALESCE(NEW.end_utc_us, 9223372036854775807)
      AND NEW.start_utc_us < COALESCE(old.end_utc_us, 9223372036854775807)
)
BEGIN SELECT RAISE(ABORT, 'overlapping zone intervals'); END;

CREATE TRIGGER zone_no_overlap_update BEFORE UPDATE ON zone_intervals
WHEN EXISTS (
    SELECT 1 FROM zone_intervals old
    WHERE old.workspace_id = NEW.workspace_id AND old.id <> NEW.id
      AND old.start_utc_us < COALESCE(NEW.end_utc_us, 9223372036854775807)
      AND NEW.start_utc_us < COALESCE(old.end_utc_us, 9223372036854775807)
)
BEGIN SELECT RAISE(ABORT, 'overlapping zone intervals'); END;

-- Track visits are diagnostic attribution, never the source of utilization.
CREATE TABLE track_visits (
    id TEXT PRIMARY KEY,
    generation_id TEXT NOT NULL REFERENCES camera_generations(id),
    track_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    start_utc_us INTEGER NOT NULL,
    end_utc_us INTEGER,
    last_observed_utc_us INTEGER NOT NULL,
    identity_source TEXT NOT NULL DEFAULT 'anonymous' CHECK (identity_source = 'anonymous'),
    CHECK (last_observed_utc_us >= start_utc_us),
    CHECK (end_utc_us IS NULL OR end_utc_us > start_utc_us),
    UNIQUE (generation_id, track_id, workspace_id, start_utc_us)
);

CREATE TABLE aggregation_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('BUILDING','PUBLISHED','FAILED')),
    source_event_seq INTEGER NOT NULL REFERENCES event_log(seq),
    metric_version INTEGER NOT NULL CHECK (metric_version > 0),
    calendar_manifest_json TEXT NOT NULL CHECK (json_valid(calendar_manifest_json)),
    started_utc_us INTEGER NOT NULL,
    completed_utc_us INTEGER
);

CREATE TABLE period_statistics (
    id TEXT PRIMARY KEY,
    aggregation_run_id TEXT NOT NULL REFERENCES aggregation_runs(id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    configuration_id TEXT NOT NULL,
    schedule_version_id TEXT NOT NULL REFERENCES schedule_versions(id),
    grain TEXT NOT NULL CHECK (grain IN ('DAY','WEEK','MONTH','YEAR','FIVE_MINUTES')),
    calendar_label TEXT NOT NULL,
    bucket_start_utc_us INTEGER NOT NULL,
    bucket_end_utc_us INTEGER NOT NULL,
    eligible_us INTEGER NOT NULL CHECK (eligible_us >= 0),
    occupied_us INTEGER NOT NULL CHECK (occupied_us >= 0),
    empty_us INTEGER NOT NULL CHECK (empty_us >= 0),
    unknown_us INTEGER NOT NULL CHECK (unknown_us >= 0),
    count_known_us INTEGER NOT NULL CHECK (count_known_us >= 0),
    count_integral_person_us INTEGER NOT NULL CHECK (count_integral_person_us >= 0),
    peak_observed_count INTEGER CHECK (peak_observed_count >= 0),
    session_starts INTEGER NOT NULL CHECK (session_starts >= 0),
    first_seen_utc_us INTEGER,
    last_seen_utc_us INTEGER,
    detail_available INTEGER NOT NULL CHECK (detail_available IN (0,1)),
    FOREIGN KEY (configuration_id, workspace_id)
        REFERENCES workspace_configurations(id, workspace_id),
    CHECK (bucket_end_utc_us > bucket_start_utc_us),
    CHECK (eligible_us <= bucket_end_utc_us - bucket_start_utc_us),
    CHECK (occupied_us + empty_us + unknown_us = eligible_us),
    CHECK (count_known_us <= occupied_us + empty_us),
    UNIQUE (aggregation_run_id, workspace_id, configuration_id, schedule_version_id, grain, bucket_start_utc_us)
);
CREATE INDEX statistics_lookup ON period_statistics(workspace_id, grain, bucket_start_utc_us);

CREATE TABLE aggregate_publications (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    grain TEXT NOT NULL CHECK (grain IN ('DAY','WEEK','MONTH','YEAR','FIVE_MINUTES')),
    calendar_label TEXT NOT NULL,
    aggregation_run_id TEXT NOT NULL REFERENCES aggregation_runs(id),
    PRIMARY KEY (workspace_id, grain, calendar_label)
);

CREATE TABLE backup_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('RUNNING','VERIFIED','FAILED')),
    started_utc_us INTEGER NOT NULL,
    completed_utc_us INTEGER,
    destination TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK (json_valid(manifest_json)),
    error_code TEXT
);

CREATE TABLE api_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('CAMERA_TEST','EXPORT','BACKUP','REBUILD','RESTORE')),
    status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED','INTERRUPTED')),
    request_id TEXT NOT NULL UNIQUE,
    parameters_json TEXT NOT NULL CHECK (json_valid(parameters_json)),
    result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json)),
    error_code TEXT,
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    created_utc_us INTEGER NOT NULL,
    started_utc_us INTEGER,
    completed_utc_us INTEGER
);
CREATE INDEX api_jobs_status ON api_jobs(status, created_utc_us);

CREATE TABLE maintenance_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('REBUILD','RETENTION','RESTORE','MIGRATION')),
    status TEXT NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    started_utc_us INTEGER NOT NULL,
    completed_utc_us INTEGER,
    scope_json TEXT NOT NULL CHECK (json_valid(scope_json)),
    result_json TEXT CHECK (result_json IS NULL OR json_valid(result_json))
);

CREATE VIEW statistics_metrics AS
SELECT s.*,
    CASE WHEN occupied_us + empty_us > 0
         THEN 100.0 * occupied_us / (occupied_us + empty_us) END AS utilization_pct,
    CASE WHEN eligible_us > 0
         THEN 100.0 * (occupied_us + empty_us) / eligible_us END AS coverage_pct,
    CASE WHEN count_known_us > 0
         THEN 1.0 * count_integral_person_us / count_known_us END AS average_observed_count
FROM period_statistics s;

CREATE VIEW occupied_sessions AS
WITH ordered AS (
    SELECT z.*,
        LAG(state) OVER w AS previous_state,
        LAG(evidence_until_utc_us) OVER w AS previous_until,
        LAG(configuration_id) OVER w AS previous_configuration
    FROM zone_intervals z
    WINDOW w AS (PARTITION BY workspace_id ORDER BY start_utc_us, id)
), grouped AS (
    SELECT *, SUM(CASE
        WHEN state = 'OCCUPIED' AND previous_state = 'OCCUPIED'
          AND previous_until = start_utc_us AND previous_configuration = configuration_id
        THEN 0 ELSE 1 END)
        OVER (PARTITION BY workspace_id ORDER BY start_utc_us, id) AS session_group
    FROM ordered
)
SELECT workspace_id, configuration_id, session_group,
       MIN(start_utc_us) AS start_utc_us,
       MAX(evidence_until_utc_us) AS evidence_until_utc_us,
       SUM(evidence_until_utc_us - start_utc_us) AS occupied_us,
       MAX(CASE WHEN end_utc_us IS NULL THEN 1 ELSE 0 END) AS is_open
FROM grouped WHERE state = 'OCCUPIED'
GROUP BY workspace_id, configuration_id, session_group;

COMMIT;
