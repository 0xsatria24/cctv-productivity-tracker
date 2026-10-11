# Design System

Versi 1.0 · 11 Oktober 2026 · Desktop PySide6/Qt Widgets. Basis: [UI/UX Spec](UI_UX_SPEC.md).

## 1. Prinsip visual

Information-dense, solid surfaces, tabular numbers, flat controls. Gunakan satu accent untuk selection/action/draft geometry; semantic colors hanya untuk status/series bermakna. State tidak bergantung warna. Tidak ada gradient, glassmorphism, blur, neon, glow, shadow, decorative pattern, emoji, animation dekoratif, giant KPI, atau nested decorative cards.

Tema awal dark. High-contrast/native accessibility settings perlu spike tersendiri sebelum diklaim supported. Preview fixed dark mengikuti permintaan/referensi, bukan otomatis mengubah warna semantic saat OS berubah.

## 2. Single token source

[design-tokens.json](docs/ui/design-tokens.json) adalah sumber machine-readable untuk renderer proposal dan generator Qt styles berikutnya. Hindari hex colors dan arbitrary spacings di masing-masing screen. Component semantic aliases menunjuk primitive tokens; semua label/status/plot mengikuti palette yang sama.

| Token | Nilai | Penggunaan |
|---|---|---|
| surface.canvas | #14171C | Background app |
| surface.sidebar | #181C21 | Navigation |
| surface.panel | #1B2027 | Panel/table/toolbar |
| surface.raised | #242B34 | Inputs/menu/dialog |
| surface.video | #101318 | Placeholder video |
| surface.hover | #2B333E | Hover neutral |
| surface.selected | #253F43 | Selected row/button |
| border.subtle | #35404B | Decorative dividers |
| border.control | #667789 | Essential input boundaries |
| text.primary | #EEF0F3 | Content |
| text.secondary | #B2BAC5 | Secondary readable content |
| text.muted | #A2ADBA | Caption/metadata |
| text.disabled | #6F7A88 | Disabled only, not essential instructions |
| accent.default | #86BBB7 | Main action/selection/draft polygon |
| accent.foreground | #14171C | Text on accent button |
| focus.ring | #8FC8D2 | Focus ring |
| status.occupied | #92C6A3 | Terisi/healthy when paired with correct context |
| status.empty | #A8B6C8 | Kosong |
| status.unknown | #BCC2CD | Unknown label/band |
| status.warning | #D8BA7B | Pending/degraded/caution |
| status.error | #E39C96 | Actionable failure |

Opaque surfaces; optional video veil is solid opaque label panel rather than blurred overlay. All status text must satisfy readable contrast on its assigned surface. Disabled contrast is not used to communicate why unavailable; helper remains secondary text. Contrast is calculated from relative sRGB luminance by [validate_ui_design.py](docs/ui/validate_ui_design.py), with the actual report in [Visual Review](docs/ui/VISUAL_REVIEW.md).

## 3. Typography and geometry

| Role | Qt point size | Weight | Typical use |
|---|---|---|---|
| caption | 9 pt | Regular | Frame age, metadata, table headings |
| body | 10 pt | Regular | Forms/table/content |
| section | 11 pt | Semibold | Panel/section heading |
| metric | 14 pt | Semibold + tabular | Compact metric strip |
| title | 15 pt | Semibold | Page title |
| code | 9 pt | Monospace | Diagnostic IDs/coordinates |

Font family Segoe UI on Windows, Noto Sans/system sans-serif on Linux; monospace Consolas/Noto Sans Mono. Use QFont point sizes, let Qt manage devicePixelRatio. Do not set every widget to a physical pixel font. Logical preview px uses the standard 96-DPI relationship solely for rendering the proposal. Qt Widgets memakai device-independent geometry; image buffers tetap memiliki pixel dimensions, sehingga canvas mapping memisahkan kedua koordinat. [Qt High DPI](https://doc.qt.io/qt-6/highdpi.html).

Duration uses tabular format “06:12:40”; summed values over 24 hours do not wrap as clock time. Numeric table cells right-aligned; timestamps remain fixed-width when practical. UI locale formatting differs from machine-readable CSV metadata; values never round differently between UI and export without explicit precision.

Spacing scale 4/8/12/16/24/32 logical px. Hairline divider 1 px, focus ring 2 px, polygon 2 px. Radius input/button 4 px, panel 4 px, menu/dialog 6 px, video 2 px. No large pill navigation. Control heights 32 px, table row 32 px, nav row 36 px, panel heading 36 px, video heading 32 px, footer 24 px, status bar 28 px.

Default window 1600×1000; comfortable 1440×900; minimum 1100×720. Native resize/layout must be tested at 100/150/200% scaling. Layout dimensions are logical pixels, not physical monitor dimensions.

## 4. Controls and states

| State | Rendering | Behavior |
|---|---|---|
| Default | Raised input/button, control border | Active keyboard/pointer target |
| Hover | Hover fill, primary text | No layout change |
| Selected | Selected fill + accent leading marker or checked indicator | aria/accessibility selected equivalent |
| Focused | Focus ring outside/inset with reserved space | Visible without relying on hover |
| Pressed | Selected fill; no scale/shadow animation | Standard Qt pressed/released behavior |
| Disabled | Muted border + disabled foreground | Helper remains readable; no fake successful action |
| Invalid | Error border + nearby error text | Focus first invalid field after submit |
| Pending | Indeterminate progress + status text | Prevent duplicate logical mutation; cancel only if allowed |

Primary button accent fill/dark foreground; one per workflow panel. Secondary neutral fill/control border. Tertiary text with no large border. Destructive action error text + bordered secondary default; solid destructive primary reserved for review dialog. Do not color all navigation icons/status fields accent.

QSS selectors target component dynamic properties (`tone`, `selected`, `invalid`, `density`) rather than fragile object names. QPalette handles broad colors; token-generated QSS handles states. Re-polish on dynamic property update. Geometry/font settings use layout/API where appropriate rather than all being QSS overrides.

## 5. Camera and overlay language

| Layer | Rendering |
|---|---|
| Camera status | Text + small status mark; ONLINE not sufficient for valid zone |
| Zone polygon | Accent outline, selected label on opaque panel; no glow |
| Draft vertex | Square handle + index; selected handle high contrast |
| Detector bbox | Neutral readable outline + optional label, same color for all anonymous people |
| Track ID | Monospace “Track anonim {short ID}”, camera-generation context in inspector |
| UNKNOWN zone | Label and segmented outline, no dangerous/idle inference |
| Stale frame | “Frame terakhir” + time/reason, LIVE removed |
| Frame mismatch | Suppress incompatible overlay, explain “Overlay belum sinkron” |

Source video colors are outside UI palette. Overlay label contrast must be enforced with opaque surface backing because footage varies. Labels avoid covering person faces when possible but do not use face visibility as validity input. Hide low-level labels when no room; keep selected object details in inspector.

## 6. Charts/timelines

Only semantic series OCCUPIED/EMPTY/UNKNOWN or one accent for utilization trend. Use line for trends, horizontal/stacked bar for comparison, timeline for intervals, heatmap only with sufficiently fine source resolution. Avoid donut, 3D, fake curves, confidence gauge, and decorative placeholder grids.

Axis title quantity + units; range/timezone displayed near chart. Missing values remain gaps; no connecting line across unknown buckets. Legend pairs state color with visible text. UNKNOWN uses a semantic hatch/stipple in timeline/stacked chart; this data encoding is the sole justified pattern and is not a decorative background.

Every graphic has table/detail alternative and accessible description. Chart mouse hover is supplemental; selected bucket/interval has keyboard detail. PyQtGraph tick count/redraw based on viewport; no unreadable fixed SVG shrink. Durations sum before ratio calculation. Ineligible schedule is visually separate from UNKNOWN.

## 7. Keyboard and focus

| Shortcut | Context | Result |
|---|---|---|
| Tab / Shift+Tab | All screens | Native focus order |
| Ctrl+F | List/table page | Focus local search |
| Enter | Selected camera | Focus view |
| Esc | Focus view/dialog/editor tool | Exit focus, cancel if allowed, or leave current tool |
| F11 | Focus camera | Toggle native fullscreen |
| Ctrl+S | Dirty form/editor | Save current draft after validation |
| Ctrl+Z / Ctrl+Y | Polygon draft | Undo/redo geometry only |
| Backspace | Polygon vertex selection | Remove selected vertex after geometry minimum check |
| Arrow keys | Table/vertex coordinate cells | Native selection/edit navigation |

Do not steal shortcuts from an active text field. QDialog owns modal focus; restore trigger focus after dismissal. Each field has label buddy, units, range, help and accessibleDescription where needed. Status changes announce meaningfully; avoid reading every preview frame or timer to assistive tools.

Canvas custom tidak otomatis memiliki semantics per shape. Sediakan selection/table/control native untuk vertex dan interval, serta QAccessibleInterface/action/value yang sesuai bila interaksi custom tidak terwakili alternatif native. Uji screen reader pada runtime; accessibleDescription saja bukan bukti semua geometry dapat dinavigasi. [Qt Accessibility](https://doc.qt.io/qt-6/accessible.html).

## 8. Production handoff boundaries

No screenshots of Qt runtime are included at this stage. Native styles, keyboard navigation, touchpad interaction, multi-screen DPI, NVDA/Orca and long session eye comfort require runtime review. The renderer/token contrast checks verify proposal assets only. Approval of direction precedes M-UI1 shell + one cohesive Live workflow as specified in [Screen Plan](SCREEN_IMPLEMENTATION_PLAN.md).
