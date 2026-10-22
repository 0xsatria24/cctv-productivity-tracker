from datetime import datetime

import pytest

from cctv_tracker.daily_analytics import daily_summary


def us(value):
    return int(datetime.fromisoformat(value).timestamp() * 1_000_000)


def interval(start, end, state='OCCUPIED', workspace='a', count=1):
    return {'workspaceId': workspace, 'start': us(start) / 1000, 'end': us(end) / 1000, 'state': state, 'count': count}


WORKSPACES = [{'workspace_id': 'a', 'workspace': 'Area A'}, {'workspace_id': 'b', 'workspace': 'Area B'}]
NOW = us('2026-10-22T12:00:00+07:00')


def test_midnight_split_and_count_is_not_person_hours():
    rows = daily_summary([interval('2026-10-20T23:30:00+07:00', '2026-10-21T00:30:00+07:00', count=2)], WORKSPACES, 'Asia/Jakarta', now_us=NOW)
    assert [r['date'] for r in rows] == ['2026-10-20', '2026-10-21']
    assert [r['occupied_us'] for r in rows] == [1800_000_000] * 2
    assert all(r['coverage'] == 1 and r['partial_day'] and not r['provisional'] for r in rows)


def test_leaving_returning_unknown_and_separate_zones():
    source = [
        interval('2026-10-21T08:00:00+07:00', '2026-10-21T09:00:00+07:00'),
        interval('2026-10-21T09:00:00+07:00', '2026-10-21T10:00:00+07:00', 'EMPTY'),
        interval('2026-10-21T10:00:00+07:00', '2026-10-21T11:00:00+07:00', 'UNKNOWN'),
        interval('2026-10-21T11:00:00+07:00', '2026-10-21T12:00:00+07:00'),
        interval('2026-10-21T08:00:00+07:00', '2026-10-21T12:00:00+07:00', workspace='b'),
    ]
    a, b = daily_summary(source, WORKSPACES, 'Asia/Jakarta', now_us=NOW)
    assert a['occupied_us'] == 7200_000_000
    assert a['empty_us'] == a['unknown_us'] == 3600_000_000
    assert a['coverage'] == .75
    assert a['utilization'] == pytest.approx(2 / 3)
    assert a['last_seen_utc_us'] - a['first_seen_utc_us'] == 14400_000_000
    assert b['occupied_us'] == 14400_000_000


def test_current_day_is_provisional_future_not_counted_and_empty_is_empty():
    rows = daily_summary([interval('2026-10-22T11:00:00+07:00', '2026-10-23T01:00:00+07:00', 'UNKNOWN')], WORKSPACES, 'Asia/Jakarta', now_us=NOW)
    assert len(rows) == 1 and rows[0]['provisional']
    assert rows[0]['unknown_us'] == 3600_000_000
    assert rows[0]['utilization'] is None and rows[0]['coverage'] == 0
    assert rows[0]['first_seen_utc_us'] is None
    assert daily_summary([], WORKSPACES, 'Asia/Jakarta', now_us=NOW) == []


@pytest.mark.parametrize(('start', 'end', 'hours'), [
    ('2026-03-08T00:00:00-05:00', '2026-03-09T00:00:00-04:00', 23),
    ('2026-11-01T00:00:00-04:00', '2026-11-02T00:00:00-05:00', 25),
])
def test_local_calendar_days_handle_daylight_saving(start, end, hours):
    row, = daily_summary([interval(start, end)], WORKSPACES, 'America/New_York', now_us=us('2026-12-01T00:00:00+00:00'))
    assert row['occupied_us'] == hours * 3600_000_000
    assert not row['partial_day']
