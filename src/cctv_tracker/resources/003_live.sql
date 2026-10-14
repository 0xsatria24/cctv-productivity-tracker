CREATE TABLE live_calibrations (
    source_kind TEXT PRIMARY KEY CHECK (source_kind IN ('WEBCAM_LIVE','RTSP_LIVE')),
    revision INTEGER NOT NULL CHECK (revision > 0),
    configuration_json TEXT NOT NULL CHECK (json_valid(configuration_json)),
    saved_utc_us INTEGER NOT NULL
);
