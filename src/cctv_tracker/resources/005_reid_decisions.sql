CREATE TABLE reid_decisions (
    decision_id TEXT PRIMARY KEY,
    engine_run_id TEXT NOT NULL REFERENCES engine_runs(id),
    camera_id TEXT NOT NULL REFERENCES cameras(id),
    generation_id TEXT NOT NULL REFERENCES camera_generations(id),
    frame_seq INTEGER NOT NULL,
    monotonic_ns TEXT NOT NULL,
    input_mapping_version INTEGER NOT NULL,
    committed_mapping_version INTEGER NOT NULL,
    candidate_session_id TEXT NOT NULL REFERENCES person_sessions(session_id),
    target_session_id TEXT REFERENCES person_sessions(session_id),
    action TEXT NOT NULL CHECK(action IN ('MATCH','REJECT','PENDING')),
    reason TEXT NOT NULL,
    appearance_score REAL,
    candidate_margin REAL,
    model_json TEXT NOT NULL CHECK(json_valid(model_json)),
    policy_revision TEXT NOT NULL,
    committed_event_seq INTEGER NOT NULL REFERENCES event_log(seq)
);
CREATE INDEX reid_run_event ON reid_decisions(engine_run_id,committed_event_seq);
