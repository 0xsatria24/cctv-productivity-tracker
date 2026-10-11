"""Executable design checks; does not implement or test the CCTV runtime."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
CHECKS: list[str] = []


def check(condition: bool, name: str) -> None:
    if not condition:
        raise AssertionError(name)
    CHECKS.append(name)


def rejected(db: sqlite3.Connection, sql: str, args: tuple, name: str) -> None:
    db.execute("SAVEPOINT rejection_check")
    try:
        db.execute(sql, args)
    except sqlite3.IntegrityError:
        db.execute("ROLLBACK TO rejection_check")
        db.execute("RELEASE rejection_check")
        CHECKS.append(name)
    else:
        db.execute("ROLLBACK TO rejection_check")
        db.execute("RELEASE rejection_check")
        raise AssertionError(f"Expected rejection: {name}")


def uid(number: int) -> str:
    return str(uuid.UUID(int=number, version=4))


def database_checks(db: sqlite3.Connection, directory: Path) -> None:
    db.executescript((ROOT / "database/001_initial.sql").read_text(encoding="utf-8"))
    db.execute("PRAGMA busy_timeout=2000")
    check(db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal", "WAL on local file")
    db.execute("PRAGMA synchronous=FULL")
    check(db.execute("PRAGMA foreign_keys").fetchone()[0] == 1, "Foreign keys enabled")
    db.execute("INSERT INTO database_state VALUES (?,?,?,?)", (1, uid(500), 0, None))
    rejected(db, "INSERT INTO database_state VALUES (?,?,?,?)", (2, uid(501), 0, None),
             "Database epoch registry accepts only singleton row")
    db.execute("INSERT INTO sites VALUES (?, ?, ?)", (uid(1), "Fixture site", 0))
    db.execute("INSERT INTO cameras VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (uid(2), uid(1), "Fixture camera", "rtsp://example.invalid/stream", None, 1, 1, "{}", 0))
    db.execute("INSERT INTO model_artifacts VALUES (?, ?, ?, ?, ?)", (uid(3), "a" * 64, "fixture.onnx", "{}", 0))
    db.execute("INSERT INTO rule_sets VALUES (?, ?, ?)", (uid(4), "{}", 0))
    db.execute("INSERT INTO schedule_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
               (uid(5), uid(1), 1, "Asia/Bangkok", "{}", 0, None))
    db.execute("INSERT INTO engine_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
               (uid(6), uid(3), "fixture", "{}", 0, None, None))
    for number in (10, 20):
        db.execute("INSERT INTO workspaces VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (uid(number), uid(1), f"Desk {number}", "desk", 1, "desk-group", 0, None))
        db.execute("INSERT INTO workspace_configurations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (uid(number + 1), uid(number), uid(2), uid(4), 1,
                    "[[0,0],[1,0],[1,1]]", 1920, 1080, "fixture-scene", 0, None))
    db.execute("INSERT INTO event_log(event_id,engine_run_id,producer_seq,event_type,observed_utc_us,recorded_utc_us,payload_version,payload_json) VALUES (?,?,?,?,?,?,?,?)",
               (uid(7), uid(6), 1, "CHECKPOINT", 0, 0, 1, "{}"))

    statement = "INSERT INTO zone_intervals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"

    def interval(number: int, state: str, count: int | None, start: int,
                 end: int | None, evidence: int | None = None, reason: str | None = None,
                 workspace: int = 10, config: int | None = None) -> tuple:
        return (uid(number), uid(workspace), uid(config or workspace + 1), uid(6), state,
                count, reason, start * 1_000_000,
                None if end is None else end * 1_000_000,
                (evidence if evidence is not None else end) * 1_000_000, 1, 1)

    db.execute(statement, interval(100, "OCCUPIED", 1, 0, 10))
    db.execute(statement, interval(101, "OCCUPIED", 2, 10, 20))
    check(db.execute("SELECT count(*),sum(occupied_us) FROM occupied_sessions").fetchone()
          == (1, 20_000_000), "Adjacent count changes remain one 20-second presence session")

    rejected(db, statement, interval(102, "EMPTY", 0, 5, 15), "Overlapping interval rejected")
    rejected(db, "UPDATE zone_intervals SET end_utc_us=?,evidence_until_utc_us=? WHERE id=?",
             (15_000_000, 15_000_000, uid(100)), "Update creating overlap rejected")
    rejected(db, statement, interval(103, "EMPTY", None, 20, 25), "EMPTY with null count rejected")
    rejected(db, statement, interval(104, "OCCUPIED", 0, 20, 25), "OCCUPIED with zero count rejected")
    rejected(db, statement, interval(105, "UNKNOWN", 1, 20, 25, reason="CAMERA_OFFLINE"), "UNKNOWN with numeric count rejected")
    rejected(db, statement, interval(106, "UNKNOWN", None, 20, 25), "UNKNOWN without reason rejected")
    rejected(db, statement, interval(107, "EMPTY", 0, 20, 20), "Zero-duration interval rejected")
    rejected(db, statement, interval(108, "EMPTY", 0, 20, 25, config=21), "Configuration/workspace foreign key mismatch rejected")

    db.execute(statement, interval(110, "UNKNOWN", None, 20, 25, reason="PENDING_CONFIRMATION"))
    db.execute(statement, interval(111, "OCCUPIED", None, 25, 30))
    check(db.execute("SELECT count(*),sum(occupied_us) FROM occupied_sessions").fetchone()
          == (2, 25_000_000), "Unknown breaks sessions; unavailable count preserves presence")
    db.execute(statement, interval(112, "EMPTY", 0, 30, 40))
    db.execute(statement, interval(113, "OCCUPIED", 1, 40, None, evidence=50))
    check(db.execute("SELECT occupied_us FROM occupied_sessions WHERE is_open=1").fetchone()[0]
          == 10_000_000, "Open session duration stops at durable evidence watermark")
    rejected(db, statement, interval(114, "EMPTY", 0, 60, None, evidence=70), "Second open interval rejected")

    duplicate = "INSERT INTO event_log(event_id,engine_run_id,producer_seq,event_type,observed_utc_us,recorded_utc_us,payload_version,payload_json) VALUES (?,?,?,?,?,?,?,?)"
    rejected(db, duplicate, (uid(7), uid(6), 2, "CHECKPOINT", 1, 1, 1, "{}"), "Duplicate event ID rejected")
    rejected(db, duplicate, (uid(8), uid(6), 1, "CHECKPOINT", 1, 1, 1, "{}"), "Duplicate producer sequence rejected")
    rejected(db, duplicate, (uid(8), uid(6), 2, "CHECKPOINT", 1, 1, 1, "not-json"), "Malformed JSON rejected")
    rejected(db, "DELETE FROM rule_sets WHERE id=?", (uid(4),), "Referenced rule set deletion rejected")

    initial_count = db.execute("SELECT count(*) FROM event_log").fetchone()[0]
    db.execute("SAVEPOINT atomic_batch")
    db.execute(duplicate, (uid(9), uid(6), 2, "CHECKPOINT", 1, 1, 1, "{}"))
    try:
        db.execute(statement, interval(115, "EMPTY", 0, 1, 2))
    except sqlite3.IntegrityError:
        db.execute("ROLLBACK TO atomic_batch")
    else:
        raise AssertionError("Invalid batch must fail")
    db.execute("RELEASE atomic_batch")
    check(db.execute("SELECT count(*) FROM event_log").fetchone()[0] == initial_count,
          "Event and projection roll back atomically")

    db.execute("INSERT INTO aggregation_runs VALUES (?,?,?,?,?,?,?)",
               (uid(200), "PUBLISHED", 1, 1, "{}", 0, 1))
    base = (uid(201), uid(200), uid(10), uid(11), uid(5), "DAY", "fixture", 0, 120_000_000,
            120_000_000, 60_000_000, 55_000_000, 5_000_000, 115_000_000, 90_000_000, 2, 1, 0, 60_000_000, 1)
    # Bind the complete fixture; a changed schema must be reviewed alongside it.
    stats_sql = "INSERT INTO period_statistics VALUES (" + ",".join("?" for _ in base) + ")"
    db.execute(stats_sql, base)
    utilization, coverage = db.execute("SELECT utilization_pct,coverage_pct FROM statistics_metrics WHERE id=?", (uid(201),)).fetchone()
    check(abs(utilization - 100 * 60 / 115) < 1e-9 and abs(coverage - 100 * 115 / 120) < 1e-9,
          "Utilization excludes unknown and coverage includes eligible denominator")
    invalid = list(base); invalid[0] = uid(202); invalid[6] = "invalid"; invalid[12] = 0
    invalid[7:9] = [120_000_000, 240_000_000]
    rejected(db, stats_sql, tuple(invalid), "Aggregate P+A+U mismatch rejected")
    zero = list(base); zero[0] = uid(203); zero[6] = "zero"
    zero[7:9] = [240_000_000, 360_000_000]
    zero[9:17] = [0, 0, 0, 0, 0, 0, None, 0]
    zero[17:19] = [None, None]
    db.execute(stats_sql, tuple(zero))
    check(db.execute("SELECT utilization_pct,coverage_pct,average_observed_count FROM statistics_metrics WHERE id=?", (uid(203),)).fetchone()
          == (None, None, None), "Zero denominators produce NULL rather than zero")

    check(db.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Database integrity check")
    check(db.execute("PRAGMA foreign_key_check").fetchall() == [], "Database foreign key check")
    backup = sqlite3.connect(directory / "backup.db", isolation_level=None)
    try:
        db.backup(backup)
        check(backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "Online backup integrity")
        check(backup.execute("SELECT count(*),sum(occupied_us) FROM occupied_sessions").fetchone()
              == db.execute("SELECT count(*),sum(occupied_us) FROM occupied_sessions").fetchone(),
              "Backup round trip preserves derived sessions")
    finally:
        backup.close()


def static_contract_checks() -> None:
    spec = json.loads((ROOT / "api/openapi.json").read_text(encoding="utf-8"))
    check(spec["openapi"] == "3.1.0", "OpenAPI version declared")

    def walk(value: object):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    references = [node["$ref"] for node in walk(spec) if "$ref" in node]
    for reference in references:
        check(reference.startswith("#/"), f"Reference is local: {reference}")
        target = spec
        for part in reference[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
    CHECKS.append(f"All {len(references)} OpenAPI references resolve")
    operation_ids = []
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            operation_ids.append(operation["operationId"])
            path_variables = set(re.findall(r"\{([^}]+)\}", path))
            declared = {p["name"] for p in operation.get("parameters", []) if p["in"] == "path" and p.get("required")}
            if path_variables != declared:
                raise AssertionError(f"Path parameters: {method} {path}")
            if method in {"patch", "put"}:
                headers = {p["name"] for p in operation["parameters"]}
                if not {"If-Match", "Idempotency-Key"}.issubset(headers):
                    raise AssertionError(f"Concurrency headers: {path}")
            if not any(code.startswith("2") for code in operation["responses"]):
                raise AssertionError(f"Success response: {path}")
    check(len(operation_ids) == len(set(operation_ids)), "Operation IDs unique and path/concurrency declarations consistent")
    check(spec["security"] == [{"LocalBearer": []}], "Authentication required globally")
    check(all(p["writeOnly"] for p in spec["components"]["schemas"]["Credentials"]["properties"].values()),
          "Credential request fields write-only")
    response_schema = spec["components"]["schemas"]["Camera"]["properties"]
    check("password" not in response_schema and "username" not in response_schema, "Camera response excludes credential fields")
    observation = json.loads((ROOT / "contracts/zone-observation.schema.json").read_text(encoding="utf-8"))
    check(observation["additionalProperties"] is False and set(observation["required"]) == set(observation["properties"]),
          "Observation contract declares strict complete input")
    check(observation["properties"]["observed_monotonic_ns"]["type"] == "string", "Nanosecond value avoids JSON number precision loss")
    # Deliberately not an official OpenAPI/JSON Schema conformance validator.


def documentation_links() -> None:
    for document in (ROOT.parent / "README.md", ROOT.parent / "PRD-CCTV-Productivity-Tracker.md", *ROOT.glob("*.md")):
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if "://" not in target and not target.startswith("#"):
                resolved = document.parent / target.split("#", 1)[0]
                if not resolved.exists():
                    raise AssertionError(f"Broken link in {document.name}: {target}")
    CHECKS.append("Local documentation links resolve")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cctv_design_") as folder:
        directory = Path(folder)
        db = sqlite3.connect(directory / "reference.db", isolation_level=None)
        try:
            database_checks(db, directory)
        finally:
            db.close()
    static_contract_checks()
    documentation_links()
    distinct = list(dict.fromkeys(CHECKS))
    report = "# Design Validation Results\n\n"
    report += f"SQLite {sqlite3.sqlite_version}. Reference schema and static checks: PASS.\n\n"
    report += "## Executed checks\n\n" + "\n".join(f"- PASS: {name}" for name in distinct if not name.startswith("Reference is local:"))
    report += "\n\n## Scope\n\nNo CCTV/GPU/runtime/API server was executed. OpenAPI checks cover JSON parsing, local references, operation/path declarations, auth, and credential fields; they are not full OpenAPI/JSON Schema conformance validation. State-machine, HTTP/WebSocket, packaging, throughput and 24-hour tests remain implementation gates.\n"
    (ROOT / "validation/RESULTS.md").write_text(report, encoding="utf-8")
    print(f"PASS: {len(distinct)} distinct design checks, SQLite {sqlite3.sqlite_version}")
    print("Report: docs/validation/RESULTS.md")


if __name__ == "__main__":
    main()
