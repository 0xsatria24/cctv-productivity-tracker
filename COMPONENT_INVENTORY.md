# Component Inventory

Versi 1.0 · 11 Oktober 2026 · Proposed Qt components, not implemented classes.

Sources: [UI/UX Spec](UI_UX_SPEC.md), [Design System](DESIGN_SYSTEM.md), [Architecture](docs/ARCHITECTURE.md), [OpenAPI](docs/api/openapi.json).

## 1. Shell and navigation

| ID / Proposed class | Qt implementation | Contract / behavior |
|---|---|---|
| C01 AppShell | QMainWindow + QWidget layouts + QStatusBar | Window/DPI/sidebar state local; engine lifetime remains supervisor-owned |
| C02 NavigationList | QListView + QAbstractListModel | Seven V1 sections, selected marker + label, keyboard selection |
| C03 PageHeader | QWidget/HBox, QLabel, QPushButton | Page title + one primary action, no welcome hero |
| C04 ContextToolbar | QWidget/GridLayout, QComboBox/date widgets | Local filters retained per page; applied filter separate from dirty draft |
| C05 EngineStatusStrip | QWidget labels + progress + action | SystemStatus + websocket snapshot; reconnect/degraded/maintenance text |
| C06 JobTray | Tool button + nonmodal panel + list model | Local known job IDs, GET jobs polling/subscription; 202 accepted not complete |
| C07 SplitWorkspace | QSplitter | Persist proportions per user; inspector drawer below width threshold |

AppShell never owns capture/inference/database or starts a database transaction. Closing GUI releases subscriptions; stop engine is distinct supervisor command.

## 2. Monitoring components

| ID / Proposed class | Qt implementation | Data / required states |
|---|---|---|
| C08 CameraList | QListView + model/delegate | Camera ID/name/status; loading/empty/filter/selected/disabled |
| C09 CameraGrid | QWidget + QGridLayout | 1/2×2/3×3, unique camera IDs, visible subscription set |
| C10 VideoTile | QWidget header + FrameCanvas + footer | Fresh/stale/connecting/offline/disabled/auth missing/preview paused |
| C11 FrameCanvas | Custom QWidget paintEvent + QImage | Own immutable copied preview pixels; aspect-preserving content rect |
| C12 DetectionOverlay | Shared renderer called by canvas | Matching generation/frame_seq; bbox neutral, optional track labels |
| C13 OverlayToolbar | QCheckBox + menu | Local preference only; zone/detection/track toggles |
| C14 CameraInspector | QWidget form labels/link buttons | Nullable diagnostics/count; stale/durable distinction; selected zone |
| C15 FocusCameraView | Reuse C10 + minimal toolbar | Native fullscreen, Esc/F11, essential status visible |
| C16 StreamStatePlaceholder | QWidget labels/actions | Clear reason, retry/test/navigation action; no misleading frozen LIVE |

Preview bytes are decoded outside UI thread into immutable frame data. Main thread paints QImage; QPixmap creation/display and widgets stay in main thread. Avoid converting/copying continuously on a timer when no new frame. Worker/callback emits presentation model, not raw engine handles.

Thread affinity dan queued signal delivery mengikuti event loop pemilik QObject; QWidget hanya dipakai di GUI thread. Pilihan render QPixmap di GUI thread merupakan baseline portabilitas desain. [Qt Threads and QObjects](https://doc.qt.io/qt-6/threads-qobject.html).

Overlay exact-source guard is reusable between Live and editor. Editor freezes reference frame deliberately; Live suppresses stale mismatched detection. CameraGrid must unsubscribe invisible tiles; GUI preview cannot affect accounting.

## 3. Metrics, tables, and history

| ID / Proposed class | Qt implementation | Semantics |
|---|---|---|
| C17 MetricStrip | QWidget labels in horizontal layout | Small values/definitions; nullable/N/A, live vs period partition |
| C18 StatusLabel | QLabel/delegate text + mark | State name/reason; color never sufficient |
| C19 ReportTable | QTableView + QAbstractTableModel + proxy | Snapshot rows, numeric alignment, sort scope explicit, stable pagination |
| C20 WorkspaceTable | Reuse table base with typed model | Identity/config/current state; avoids employee inference |
| C21 PeriodFilter | QDateEdit/range controls + grain combo | Site timezone, historical calendar, dirty vs applied |
| C22 TrendPlot | PyQtGraph PlotWidget adapter | Axis units/timezone, gap-aware series, selected bucket + table alternative |
| C23 DurationBarPlot | PyQtGraph/custom plotting adapter | Occupied/empty/unknown, units workstation-time, valid denominators |
| C24 HeatmapPlot | PyQtGraph ImageItem + keyed axis | Only with fine-resolution source; no fabrication from daily totals |
| C25 ZoneTimeline | Custom QWidget/QGraphicsView | Common time axis, schedule masking, unknown hatch, precise [start,end) |
| C26 IntervalInspector | QWidget FormLayout | Reason/count/provenance/durability; no video evidence promise |
| C27 SnapshotMetadata | Labels + help/action | source seq, expiry, precision, provisional, detail horizon |
| C28 EmptyDataState | QWidget labels + relevant action | No camera vs no eligible data vs no matching filter distinctly |

Do not retain all history in table model. Page size follows <=500 rows; materialized server snapshot max5000 rows. GUI sorting of current page must be labeled as such or server sorting contract must exist; do not imply global sort. Current OpenAPI lacks explicit sort query fields, so default order is fixed and full-range sorting remains a contract gate.

Time format helper separates local timestamps, elapsed duration and ratios. Row totals use raw durations, never formatted strings. Session/interval views share formatting but different source semantics.

## 4. Configuration and maintenance

| ID / Proposed class | Qt implementation | Important states |
|---|---|---|
| C29 CameraForm | QWidget form, QLineEdit/QSpinBox | Dirty/invalid/saving/revision conflict; endpoint no secret |
| C30 CredentialEditor | Password QLineEdit + explicit action | Missing/configured/store unavailable; no round-trip plaintext |
| C31 ConnectionTestPanel | Job status + stage labels | Accepted/running/completed/failed/interrupted; typed diagnostics gate |
| C32 WorkspaceForm | Native form controls | Name/kind/capacity/exclusive group + config draft |
| C33 PolygonCanvas | C11 with geometry tool controller | Add/close/drag/delete/undo; exact inverse mapping |
| C34 VertexTable | QTableView editable draft model | Keyboard alternative; X/Y normalized range checks |
| C35 RevisionReview | QDialog + difference table | Current vs draft, effective time, 412 conflict resolution |
| C36 ConfigurationStatus | Status label + job/ack observation | PENDING_APPLY/APPLIED/REVIEW_REQUIRED, no optimistic applied |
| C37 CalendarEditor | Native tables/date/time/timezone form | Holiday/break/overnight validation; historical version change |
| C38 RetentionEditor | Form + horizon/damage preview | Policy not implemented by existing API; typed gate before saving |
| C39 BackupTable | Typed table + verification labels | Verified/failed/not checked, snapshot metadata |
| C40 RestoreReview | Modal QDialog | Review effect, safe initial focus, no duplicate restore after reconnect |
| C41 OperationProgress | QProgressBar + text + cancel | Null progress indeterminate; cancellable from server |
| C42 RecoverableError | Inline/bounded error area | Sanitized code, request ID, meaningful next action, preserve draft |

All form submission services attach Idempotency-Key and ETag/If-Match. API acceptance updates presentation receipt/status; applied/runtime readiness is a later explicit state. Error messages are user copy from code mapping; raw JSON/exceptions/secrets are not shown.

## 5. Shared UI service boundaries

| Service | Owner / responsibilities | Exclusions |
|---|---|---|
| EngineClient | gui/services; authenticated loopback HTTP/ws, registry reconnect | No public auth/user identity, no raw SQL |
| PreviewSession | gui/services worker; metadata/binary pairing, bounded latest frame | No RTSP capture, person inference, accounting |
| PageViewModel | gui/viewmodels; immutable state, filter, nullable formatting | No database connection or core metric derivation |
| DraftController | gui/controllers; local polygon/form undo and validation | No mutating committed config until save |
| MetricPresenter | Formatting validated report rows/units | No face-based working/idle decisions |
| JobPresenter | Store/reconnect known IDs, status/cancel/download | No claiming execution completed from HTTP202 |
| UIPreferences | Local per-user window/layout/overlay choices | No credentials or engine rules |
| TokenStyleAdapter | Generate QPalette/QSS/QFont from JSON | No hardcoded screen-specific visual palettes |

Worker callbacks carry page request generation ID; outdated response cannot overwrite newer filter/screen state. Cancel navigation cancels local work/subscription when appropriate, not committed server mutation. Download/file dialog stays GUI-owned; managed file identity comes from server.

## 6. Reuse/state QA matrix

| Family | Minimum checks before reusable status |
|---|---|
| Controls | default/hover/selected/focus/disabled/error + keyboard labels |
| Video | aspect, frame_seq mismatch, stale time, offline, paused, hidden subscription |
| Tables | empty/loading/error, nullable columns, stable snapshot expiry, resize, >24h duration |
| Metrics/plots | N/A, no data, partial coverage, gaps, source precision, weighted totals |
| Config | dirty leave, undo, invalid geometry, secret redaction, 412, pending ack |
| Jobs | 202, null progress, cancellation boundary, interrupted/reconnect, expiry |
| Dialogs | safe default, focus restoration, Esc if allowed, keyboard-only review |

Proposal PNGs do not establish these components are implemented or accessible in a running Qt app. Component contract checks and screenshot review are documented separately in the screen plan.
