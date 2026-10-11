# Design Validation Results

SQLite 3.53.1. Reference schema and static checks: PASS.

## Executed checks

- PASS: WAL on local file
- PASS: Foreign keys enabled
- PASS: Database epoch registry accepts only singleton row
- PASS: Adjacent count changes remain one 20-second presence session
- PASS: Overlapping interval rejected
- PASS: Update creating overlap rejected
- PASS: EMPTY with null count rejected
- PASS: OCCUPIED with zero count rejected
- PASS: UNKNOWN with numeric count rejected
- PASS: UNKNOWN without reason rejected
- PASS: Zero-duration interval rejected
- PASS: Configuration/workspace foreign key mismatch rejected
- PASS: Unknown breaks sessions; unavailable count preserves presence
- PASS: Open session duration stops at durable evidence watermark
- PASS: Second open interval rejected
- PASS: Duplicate event ID rejected
- PASS: Duplicate producer sequence rejected
- PASS: Malformed JSON rejected
- PASS: Referenced rule set deletion rejected
- PASS: Event and projection roll back atomically
- PASS: Utilization excludes unknown and coverage includes eligible denominator
- PASS: Aggregate P+A+U mismatch rejected
- PASS: Zero denominators produce NULL rather than zero
- PASS: Database integrity check
- PASS: Database foreign key check
- PASS: Online backup integrity
- PASS: Backup round trip preserves derived sessions
- PASS: OpenAPI version declared
- PASS: All 156 OpenAPI references resolve
- PASS: Operation IDs unique and path/concurrency declarations consistent
- PASS: Authentication required globally
- PASS: Credential request fields write-only
- PASS: Camera response excludes credential fields
- PASS: Observation contract declares strict complete input
- PASS: Nanosecond value avoids JSON number precision loss
- PASS: Local documentation links resolve

## Scope

No CCTV/GPU/runtime/API server was executed. OpenAPI checks cover JSON parsing, local references, operation/path declarations, auth, and credential fields; they are not full OpenAPI/JSON Schema conformance validation. State-machine, HTTP/WebSocket, packaging, throughput and 24-hour tests remain implementation gates.
