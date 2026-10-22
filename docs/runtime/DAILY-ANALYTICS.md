# Rekap kehadiran area harian

Open **Analitik → Rekap Harian** in the integrated engine dashboard. The first
visit defaults to today when no explicit period was selected. Use the existing
period/workstation filters to inspect other days, all saved sessions, or an
overnight shift. **Hari ini** selects all sessions from local midnight to the
instant the button was pressed; press it again to advance that cutoff.

Each row describes one configured area/workstation on one local calendar day:
occupied, empty and unknown durations, coverage, first/last occupied evidence,
and whether the day is provisional or only partially included. Durations use
HH:MM:SS in the UI; CSV preserves integer microseconds. Coverage is
`(occupied + empty) / eligible`. First/last timestamps are evidence boundaries,
not arrival/departure or the basis of the duration calculation.

The backend splits canonical committed observation intervals at midnight using
the site's IANA timezone, including daylight-saving changes. It preserves gaps
as unknown, respects workstation monitoring start/end, and excludes future time
from daily summaries. SQLite already rejects overlapping zone intervals. No
database migration is required.

`GET /pilot/v1/reports` includes `daily` and `timezone` alongside the existing
period report. Its existing dataset, run, workstation and time filters apply.
`GET /pilot/v1/export.csv?daily=true` exports those daily rows with timezone,
source labels, monitoring-window basis and units. Existing CSV exports retain
their previous shape. Both routes retain existing authentication requirements.

**Lihat timeline** narrows the report to that row's workspace and included daily
window, retaining the selected dataset/session. CSV exports all matching rows,
not just the table's current page.

This first stage reports anonymous zone presence. It does not calculate named
worker hours, person-hours, combined occupancy across multiple zones, or
productivity. Assignment records do not establish observed identity. Automatic
work calendars and break deductions are not applied; a shift filter only clips
the selected time range. Replay/browser fixtures demonstrate accounting and UI
behavior, not accuracy on real factory CCTV.
