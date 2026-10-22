-- Session timing is independent of legacy diagnostic track_visits.
CREATE TABLE person_sessions (
    session_id TEXT PRIMARY KEY,
    engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
    camera_id TEXT NOT NULL REFERENCES cameras(id),
    camera_alias TEXT NOT NULL,
    generation_id TEXT NOT NULL REFERENCES camera_generations(id),
    first_seen_utc_us INTEGER NOT NULL,
    last_seen_utc_us INTEGER NOT NULL,
    accumulated_duration_us INTEGER NOT NULL CHECK(accumulated_duration_us >= 0),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','LOST','EXPIRED')),
    track_id TEXT,
    track_lifecycle TEXT,
    mapping_version INTEGER NOT NULL,
    reason TEXT,
    merged_into TEXT,
    matching_json TEXT NOT NULL CHECK(json_valid(matching_json)),
    zone_times_json TEXT NOT NULL CHECK(json_valid(zone_times_json)),
    updated_event_seq INTEGER NOT NULL REFERENCES event_log(seq),
    CHECK(last_seen_utc_us >= first_seen_utc_us),
    CHECK(status = 'ACTIVE' OR (track_id IS NULL AND track_lifecycle IS NULL))
);
CREATE UNIQUE INDEX session_active_lifecycle ON person_sessions(camera_id, track_lifecycle)
    WHERE status='ACTIVE' AND track_lifecycle IS NOT NULL;
CREATE UNIQUE INDEX session_active_track ON person_sessions(engine_run_id, camera_id, generation_id, track_id)
    WHERE status='ACTIVE' AND track_id IS NOT NULL;
CREATE INDEX session_run_state ON person_sessions(engine_run_id, status);
