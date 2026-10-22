"""Daily summaries of canonical, non-overlapping workstation observations."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def daily_summary(intervals, workstations, timezone_name, *, now_us=None):
    """Split monitoring intervals at local midnight; never infer employee identity."""
    zone = ZoneInfo(timezone_name)
    now_us = now_us if now_us is not None else int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    names = {row['workspace_id']: row['workspace'] for row in workstations}
    rows = {}
    for interval in intervals:
        left = int(round(interval['start'] * 1000))
        end = min(int(round(interval['end'] * 1000)), now_us)
        while left < end:
            day = datetime.fromtimestamp(left / 1_000_000, zone).date()
            day_start = int(datetime.combine(day, time.min, zone).timestamp() * 1_000_000)
            day_end = int(datetime.combine(day + timedelta(days=1), time.min, zone).timestamp() * 1_000_000)
            right = min(end, day_end)
            workspace_id = interval['workspaceId']
            key = (day.isoformat(), workspace_id)
            if key not in rows:
                rows[key] = {
                    'id': f'{day}:{workspace_id}', 'date': day.isoformat(),
                    'workspace_id': workspace_id, 'workspace': names[workspace_id],
                    'timezone': timezone_name, 'start_utc_us': left, 'end_utc_us': right,
                    'occupied_us': 0, 'empty_us': 0, 'unknown_us': 0,
                    'first_seen_utc_us': None, 'last_seen_utc_us': None,
                    'provisional': day_start <= now_us < day_end,
                    'identity_source': 'anonymous', 'schedule_applied': False,
                    'basis': 'monitoring_window',
                }
            row = rows[key]
            row['start_utc_us'] = min(row['start_utc_us'], left)
            row['end_utc_us'] = max(row['end_utc_us'], right)
            state = interval['state']
            row[{'OCCUPIED': 'occupied_us', 'EMPTY': 'empty_us'}.get(state, 'unknown_us')] += right - left
            if state == 'OCCUPIED':
                row['first_seen_utc_us'] = min(row['first_seen_utc_us'] or left, left)
                row['last_seen_utc_us'] = max(row['last_seen_utc_us'] or right, right)
            row['partial_day'] = row['start_utc_us'] > day_start or row['end_utc_us'] < day_end
            left = right
    for row in rows.values():
        known = row['occupied_us'] + row['empty_us']
        row['eligible_us'] = known + row['unknown_us']
        row['coverage'] = known / row['eligible_us'] if row['eligible_us'] else None
        row['utilization'] = row['occupied_us'] / known if known else None
    return sorted(rows.values(), key=lambda row: (row['date'], row['workspace'], row['workspace_id']))
