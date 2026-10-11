# Screen Implementation Plan

Versi 1.0 · 11 Oktober 2026 · UI delivery setelah approval arah desain.

Design inputs: [UI/UX Spec](UI_UX_SPEC.md), [Design System](DESIGN_SYSTEM.md), [Component Inventory](COMPONENT_INVENTORY.md). Backend milestones: [Implementation Plan](docs/IMPLEMENTATION-PLAN.md).

## 1. Tahap sekarang dan approval gate

Prompt pengguna menyatakan “First produce” empat dokumen dan “Then present the proposed design direction for approval.” Tahap ini menyelesaikan dokumen/token/preview untuk review. Implementasi seluruh aplikasi tidak dilakukan dalam satu pass. Approval yang diminta adalah arah visual dan struktur workflow yang sudah konkret, bukan izin membuat dokumen.

Setelah approved, kerjakan shell + satu cohesive Live workflow terlebih dahulu dengan native PySide6/Qt. Runtime dependency spike tetap mengunci kombinasi Qt/Python/PyQtGraph/decoder; membuat proposal PNG tidak menyelesaikan spike tersebut.

## 2. Urutan increment

| ID | Screen/workflow | Backend dependency | Output dan gate |
|---|---|---|---|
| UI0 | Documents/tokens/static previews | PRD/architecture/schema dibaca | Direction review; tanpa fake metrics/stream |
| UI1 | Shell + camera list + one Live focused tile | M0/M4/M8, typed preview/status fake adapter dahulu | Native UI, no-stream/reconnect/fresh/stale, keyboard/focus, responsive; actual Qt screenshots |
| UI2 | Multi-camera grid + inspector | M5/M6/M7 + health contract | 1/2×2/3×3, matching overlays, bounded preview, GUI close/reconnect |
| UI3 | Camera add/edit/credentials/test | M5/M8, typed test result | Secret redaction, ETag, dirty form, actual job lifecycle |
| UI4 | Workstation list + one polygon workflow | M2/M7/M8 | Geometry/keyboard/letterbox mapping, review revision, pending/applied/conflict |
| UI5 | Ringkasan live + period metrics | M8/M9 | Live vs period labels, weighted durations, no-data/null/coverage/provisional |
| UI6 | Analitik summary + timeline | M2/M9 | Exact clipping, unknown/missing/ineligible, retained/expired detail, plot table alternative |
| UI7 | Reports + CSV job | M9/M11 | Full filter export, stable pagination, null progress, save/download/expiry |
| UI8 | Calendar + backup/restore settings | M8/M12 + settings gaps closed | Versioned calendar, verified backup, maintenance reconnect/outcome |
| UI9 | Packaging/pilot/a11y soak | M13/M14 | Fresh install, real screenshots, keyboard/screen reader, DPI, prolonged use |

UI1 intentionally contains an adapter seam, not complete CV/DB application. Fixture states used by tests are marked development-only and never sent to production reports; proposal preview shows no numeric analytics. Add features only when corresponding domain/API gates are complete.

## 3. Before/after workflow for every increment

Before coding: specify primary task and entry/exit paths; information hierarchy; reused components/tokens; source fields and null semantics; state matrix; API readiness; window constraints. Use UI_UX_SPEC screen section as review checklist.

After coding: run actual native app → capture screenshots from the app → inspect 1600×1000, 1440×900, 1100×720 and 100/150/200% scaling → verify typography/alignment/density → inspect overlay on bright/dark footage → exercise keyboard/loading/empty/error/reconnect → fix visible issues → recapture. Save screenshot/environment/check notes under docs/ui/runtime-reviews/{increment}/. Do not label SVG/Pillow design output as runtime screenshot.

## 4. API traceability and honest gaps

Existing contract: [API Design](docs/API-DESIGN.md), [OpenAPI](docs/api/openapi.json). Planned UI does not imply missing endpoints/fields already exist. Gaps below are contract tasks before active controls are released; UI cannot bypass them with SQLite access.

| Workflow | Existing contract | Gap / implementation requirement |
|---|---|---|
| Engine status | GET /v1/system/status + ws status | Typed transport/update timestamps and compatibility state; actual supervisor start/stop channel |
| Live preview | ws preview docs define generation/frame_seq | Typed metadata+overlay schema, availability/reasons, resolution/latency/actual FPS/reconnect counters |
| Current zone inspector/table | Workspaces/configurations + report/timeline | Typed current zone snapshot: canonical state, reason, count, watermark, primary scope; don't guess from last report row |
| Ringkasan | GET dashboard + POST reports/query | Eligible period scope and reporting-zone overlap policy explicitly resolved; no global unique headcount |
| Camera edit | CameraPatch has target FPS | Camera GET must return editable target FPS/current settings; test job typed result/status freshness |
| Workstation create/revision | POST workspaces; POST configurations | Typed metadata update/retirement, exclusion zone schema, scene review acknowledgement |
| Calendar | GET schedules/current + POST schedules | Baseline scheduled calendar supported; separate operational vs scheduled basis/effective-from/fold UI needs typed fields before enable |
| Report sorting | Snapshot query/timeline pagination | Fixed default server order now; add sort allowlist if global sorting exposed |
| Old history | precision/detail_available | Query capabilities/resolution/history horizon typed response for selecting aligned-cache range |
| Heatmap/time-of-day | Cache includes optional FIVE_MINUTES | Availability and response bin grain exposed, else only coarser trend/table |
| Settings performance/rules/retention | GET rule-sets, status, schema policy | Policy read/update + revision + storage stats/provider manifest contract before editor save |
| Backup/restore | GET backups, jobs; backup/restore POST | Verification/schema/size/horizon typed result; cancellation stage and completion outcome |
| Reopen job tray | GET jobs/{id} only | Persist GUI-known job IDs; if full historical list required, add constrained job-list endpoint |

OpenAPI does not currently expose all rich health/settings data described in technical design. Close gaps one workflow at a time, update OpenAPI and generated-contract tests, then enable corresponding controls. Until available, display “Belum tersedia” or omit the control; do not invent data or show a button that pretends to save.

## 5. Native code organization

```text
src/cctv_tracker/gui/
  shell.py
  design/        token loader, palette/QSS/font adapter
  widgets/       video, status, tables, filters, polygon, timeline
  pages/         overview, live, cameras, workspaces, analytics, reports, settings
  viewmodels/    typed immutable presentation state
  controllers/   draft/selection/navigation state
  services/      EngineClient, PreviewSession, jobs, local preferences
tests/gui/       state presentation, keyboard, response generation, frame guard
```

QApplication/widgets on main thread. Network/preview conversion/report work uses appropriate workers/native async network and signals; CPU-heavy CV stays engine-owned. Table updates incremental/batched; preview uses latest available frame, no growing queue. UI preferences local; credentials only via backend CredentialStore. Qt API/component choices use locked dependency documentation during implementation.

## 6. Meaningful verification

| Scenario | Expected behavior |
|---|---|
| Engine not ready/disconnected | Status explicit, no fake green/0 metrics, reconnect preserves page/filter |
| Camera offline after known state | LIVE removed; zone unknown, frame timestamp visible, no away classification |
| Inference offline but preview available | Separate quality status; preview cannot produce valid duration |
| Count unavailable while occupied | Terisi + jumlah belum tersedia; duration remains correct |
| GUI receives stale response | Earlier request generation does not replace new active filter |
| Preview and overlay frame mismatch | No stale boxes painted as current |
| Long occupied duration | No wrapping at 24h; bounded by evidence watermark |
| Credentials validation fails | Sanitized copy/log; password not reflected in payload/error |
| Polygon with letterbox/zoom | Saved coordinates correspond original frame, max64/simple polygon validation |
| Config revision conflict | Preserve draft, compare/load; never overwrite silently |
| Report has no denominator/data | N/A or empty state with reason; no decorative chart |
| Snapshot expires midpage | Reload explicit; don't append page from new snapshot |
| Detail retained vs expired | Exact drill-down only retained; aligned-cache alternative explicit |
| Export gets HTTP202/null progress | Accepted/indeterminate, no complete toast until result |
| Restore interrupts API | Preserve job ID, reauthenticate new instance, verify actual completion receipt |
| Close dashboard | Unsubscribe UI; headless engine continues according actual status |

Run domain/metric correctness on backend fixture gates; GUI tests validate presentation of those states instead of mirroring implementation code. Native a11y focus/labels, frame throughput and 24h responsiveness require real platform runs.

## 7. Proposal verification versus release verification

Proposal: token JSON parse, essential contrast, local links, SVG/XML parse, no forbidden styles, no invented metrics, PNG output inspected at two logical sizes. Results in [Visual Review](docs/ui/VISUAL_REVIEW.md).

Release: actual running Qt screenshots + interactions + API contract + CV pipeline + persistent data + packaging. Proposal review is not a production readiness claim.
