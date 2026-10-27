# Replay as the reference for live

The user's standing requirement is recorded in root AGENTS.md: each applicable
replay engine feature, bug fix and UI/UX change must ship to live in the same
task. Prefer shared code and maintain replay/live comparison tests.

Shared workstation policy now owns area evidence classification, candidate
exclusion, marker reading/error states, eligible bodies for check-in, default
rules and sampling frequency. Live and replay publish that same policy. New
live calibrations inherit engine rules instead of a separate three-second gap
default. Explicit rules on existing saved profiles are preserved.

Browser frame capture shares its size limits, JPEG quality and cadence helper.
Both paths read workstation frequency from the backend. RTSP workstation
inference also enforces that cadence; preview polling does not define engine
sampling frequency.

Source clocks and storage remain adapters: replay uses media positions and
deduplicates intervals across seeks; live uses monotonic captures and committed
SQLite intervals. A seek boundary is skipped in replay, while a camera outage
remains unobserved/unknown in live. Neither earns occupied time.

Validation:

- Shared-evidence tests compare area state, counts, reason, occupied/empty/
  unknown totals and marker registration with identical samples. Cases include
  body overlap and footpoint association, weak bodies, tracking candidates,
  empty areas, multiple people/markers, unregistered markers, decoder failure,
  evidence gaps and generation changes.
- Seven parity/default/cadence cases and five existing live integration cases
  pass in the final targeted run: runtime/parity-contract-tests.xml.
- Full backend regression passed 354 tests before the final RTSP cadence and
  API-default additions; those final additions passed the targeted checks above.
- 34 frontend tests and the production frontend build pass.
- The running local APIs return matching policy: 2 workstation samples/second
  and a one-second evidence gap with the launcher's default configuration.
  Evidence: runtime/shared-engine-policy.json.

The area editor, overlays, workstation results and CSV remain shared components.
No physical RTSP source or badge-distance accuracy is claimed by these tests.
