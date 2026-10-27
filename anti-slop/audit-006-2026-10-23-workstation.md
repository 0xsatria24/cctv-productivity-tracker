# After audit: workstation replay

Scope: replay calibration, primary workstation totals, secondary person details.
The user's session choice is After. Existing CCTV console direction is retained:
ENERGY 1 / RHYTHM 1 / MOTION 1. Primary focal point: workstation duration; the
video remains its evidence. Accent: existing cyan for the selected zone and
workstation rows. Existing typography, dark surfaces, spacing and radii preserve
readability beside CCTV footage. No assets, branding, or navigation were added.

## Hard gate

- R-02 PASS: new rendered copy contains no em dash.
- R-03 PASS: desktop document width 1209 <= viewport 1224; mobile 375 <=390; modal width342 with scrollWidth325. Screenshots inspected.
- R-17 PASS: clocks and coverage come from measured replay packets; no invented statistics.
- R-18 PASS: no testimonials or invented people.
- R-23 PASS: only existing icons and the selected local video frame; no invented visual assets.
- R-24 PASS: no new navigation links; README links to the implemented release document.
- R-25 PASS: caption rgb(162,173,186) on rgb(27,32,39), contrast7.19:1; primary text inherits the established lighter token.
- R-26 PASS: add/select/delete zone, click/numeric point entry, delete/undo point, association method, apply/cancel/close, and details disclosure have working actions.
- R-27 PASS: no-zone, template-not-applied, waiting-for-frame, paused, stale, unknown and server-rejection states were inspected.
- R-28 PASS: no FAQ added.
- R-32 PASS: numeric coordinate entry works without pointer drawing; Tab focuses the method select with a visible 2px cyan outline; Escape closes and restores focus to calibration.
- R-33 PASS: source changes were written with apply_patch; OpenAPI is a generated contract artifact.
- R-34 PASS: no theme control or theme change; new controls inherit existing tokens.
- R-35 PASS: Vite build and20 frontend tests pass. Recorded browser flow: import075831.mp4, layout1, open editor, add zone, enter four corners, apply, enable detection, play/pause, speed2x, seekHome, resume. Backend regression evidence is recorded below.
- R-36 PASS: UI calls person matching experimental and occupancy non-productivity; release document explicitly withholds production readiness.
- R-37 PASS: established CCTV console direction above; no new visual direction invented.
- R-38 PASS: actual video, actual backend totals and explicitly labeled test ROI; no fabricated operational records.

## Purpose gate

- R-01 PASS: no new gradients or glows.
- R-04 PASS: existing play, pause, file and delete icons retain their direct control meanings; new calibration actions use text.
- R-06 PASS: numeric timers use existing tabular numerals for comparison; no new display typeface.
- R-07 PASS: no decorative background pattern.
- R-08 PASS: no decorative CTA arrows.
- R-09 PASS: existing replay label distinguishes source; no promotional badges added.
- R-10 PASS: no glass or blur added.
- R-12 PASS: no shadows added.
- R-13 PASS: existing focus outline identifies keyboard focus; no glow added.
- R-14 PASS: workstation rows are data records with elapsed-state columns, not feature cards.
- R-19 PASS: no animation added; video movement is source evidence.
- R-22 PASS: no illustration added.

## Liveliness

- Dials PASS:1/1/1 match the existing operational console.
- Focal point PASS: workstation totals precede collapsed experimental person details.
- Whitespace PASS:12px row spacing separates zones;14px form spacing separates calibration operations.
- Accent PASS: existing cyan marks the selected polygon and workstation rows.
- Motif PASS: replay label, framed video and aligned elapsed totals continue existing monitoring patterns.
- Direction PASS: existing product design and user's After mode are retained.

## Craftsmanship and consistency

- C-1 PASS: each major visual choice has its purpose above.
- C-2 PASS: point deletion, undo, mode selection, invalid-geometry rejection and successful apply were exercised.
- C-3 PASS: added content serves calibration, evidence freshness and elapsed occupancy.
- C-4 PASS: mobile modal scrolls, fields wrap, keyboard access works and storage/API failures have visible feedback.
- C-5 PASS: source is explicitly local replay; no employee identity or productivity claim.
- R-05 PASS: existing monitoring layout retained; no template sections added.
- R-11 PASS: existing panel/button radii retained.
- R-15 PASS: actions name their result: Kalibrasi zona, Tambah workstation, Terapkan zona.
- R-16 PASS: new UI copy contains no marketing buzzwords.
- R-20 PASS: existing CCTV evidence/occupancy console identity retained.
- R-21 PASS: existing dark monitoring console matches video observation; no theme redesign.
- R-29 PASS: existing neutrals and cyan accent only.
- R-30 PASS: no external product cloned.
- R-31 PASS: color, layout, typography, spacing and hierarchy reasons documented above.

## Evidence and functional limits

- `evidence-006-workstation/calibration-mobile.png`: real video calibration at390x844.
- `evidence-006-workstation/workstation-replay-desktop.png`: actual video, detected box, zone and primary cumulative workstation totals.
- Geometry rejection: crossed polygon returned422 and stayed in editor; valid polygon applied successfully.
- Persistence: restart/reimport recovered the browser's saved template; engine acknowledgement was required before it became active.
- Pause: workstation text/totals stayed identical while changing speed and toggling person details.
- SeekHome: previous workstation rows cleared; the next accepted timeline began at zero.
- Python full suite272 passed in44.79s, including failed-tracker isolation; frontend20 tests and Vite build passed.
- Independent labels, actual deployment ROI approval, real-camera acceptance and the24h soak remain outstanding. This audit approves the scoped UI, not production accuracy.
