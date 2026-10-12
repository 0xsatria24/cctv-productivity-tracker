# Local prototype verification

Verified on 12 October 2026 on Windows with Node.js 24.18.0, npm 11.16.0, and Microsoft Edge.

- `npm.cmd run build`: passed after integration and again after removing CSS cursor overrides. Final output: 326.18 kB JavaScript (100.21 kB gzip), 25.36 kB CSS (5.01 kB gzip).
- `npm.cmd test`: 6 tests passed. Covers weighted P/A/U accounting, sessions, zero denominators, interval clipping, polygon validity, and CSV escaping.
- `npm.cmd run test:e2e`: all 13 browser tests passed after integration. Covers seven routes and browser history, layouts and preview freeze, connection failures, activity simulation, forms, password exclusion, polygon revisions, analytics, timeline, tables, CSV download, cancellation, snapshots, retention, empty states, focus, Escape, and responsive sizing.
- Local dev server returned HTTP 200 and the interactive preview opened at `http://127.0.0.1:5173/`.
- After the cursor-only CSS change, browser inspection confirmed native cursor values (`auto` on the page and `default` on buttons), with no cursor overlay elements. No custom cursor image or glow is implemented in this prototype.

Actual browser screenshots from the integration test run:

- [Overview, 1440 px](screenshots/overview-1440.png)
- [Live monitoring, 1440 px](screenshots/live-1440.png)
- [Live monitoring, 1100 px](screenshots/live-1100.png)
- [Polygon editor, 1440 px](screenshots/editor-1440.png)

These checks validate the browser design prototype and mock interactions. They do not validate real CCTV, inference accuracy, the Python engine, native PySide6 behavior, or production performance. The production architecture and shared design tokens were not changed.
