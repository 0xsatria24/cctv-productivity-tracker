# Replay fullscreen and compact overlays

The fullscreen article previously kept the header, settings and workstation
results in a vertical flex layout. They consumed the viewport and shrank the
video frame. Fullscreen now gives the frame the entire viewport and overlays a
compact playback bar. The video retains its aspect ratio without cropping.

Area and person captions use one line at 11 CSS pixels. Long area names shorten
with the available image width. Full names remain in the area title and results.
The video clock follows the displayed image edge instead of the outer pillarbox.
The playback bar hides after 2.5 seconds while playing, unless it is hovered or
has keyboard focus. Pointer movement and Tab reveal it. Pausing keeps it visible.
Playback errors remain visible in fullscreen. Double-click toggles fullscreen.

Direction: existing CCTV console, video as the focal point. ENERGY 1 / RHYTHM 1 /
MOTION 1. The short opacity transition only hides playback controls; reduced
motion disables it. Existing play/pause and fullscreen icons retain their usual
playback meanings. No new visual assets or accounting behavior were introduced.

Validation for this change:

- PASS build: `npm.cmd run build`.
- PASS frontend: all 31 existing tests.
- PASS browser: local 075831.mp4, native fullscreen, 1280 x 800 frame in a
  1280 x 800 viewport; normal settings hidden; label height 17.6 pixels.
- PASS playback controls: pause, resume, seek to 40 seconds, exit fullscreen,
  return to normal controls, automatic hiding, and Tab revealing the bar.
- PASS browser console: no errors or warnings observed during the check.
- PASS text contrast: 7.59:1 for captions over a white image through the 76%
  dark backing, 12.51:1 for button text. Control borders 3.11:1; focus 7.73:1.
- PASS Hard Gate for the changed replay UI: working controls, explicit error
  handling, keyboard access, successful build and local-video verification.
- PASS Purpose Gate: original CCTV palette and playback icons; no decorative
  gradients, assets, shadows or new product sections.
- PASS Liveliness: the video fills the available viewport and overlays stay
  subordinate; the existing accent remains on actionable controls and geometry.
- PASS Craftsmanship: aspect ratio and overlay alignment preserved, compact
  labels, keyboard focus protected from hiding, no fabricated accuracy claims.

Browser verification covers the Windows desktop replay path. Camera accuracy
and ArUco identity performance are outside this UI change.

Evidence: `runtime/fullscreen-replay-fixed.png` and
`runtime/fullscreen-replay-controls.png`.
