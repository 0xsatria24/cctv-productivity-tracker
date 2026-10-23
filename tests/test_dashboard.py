from contextlib import closing
from dataclasses import replace
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from cctv_tracker.api import create_app
from cctv_tracker.config import load_settings
from cctv_tracker.dashboard import ReplayController
from cctv_tracker.persistence import Database

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = {"Origin": "http://127.0.0.1"}


@pytest.fixture
def integrated(tmp_path):
    config = replace(load_settings(ROOT / "config/pilot.example.json"), database=tmp_path / "app.sqlite3")
    with closing(Database(config.database)):
        pass
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text('<html><head></head><body><div id="root"></div></body></html>')
    controller = ReplayController(config, delay=0.01)
    app = create_app(config.database, "t" * 40, controller=controller, ui_dir=ui)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client, controller, config


def wait(controller, status="COMPLETED"):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        value = controller.snapshot()
        if value["status"] == status:
            return value
        if value["status"] == "FAILED":
            pytest.fail(value["error"])
        time.sleep(0.01)
    pytest.fail(f"Replay did not reach {status}: {controller.snapshot()}")


def test_session_is_httponly_and_not_in_javascript_and_origin_is_enforced(integrated):
    client, controller, _ = integrated
    assert client.get('/pilot/v1/status').status_code == 401
    page = client.get('/')
    assert 'window.__CCTV_ENGINE__=true' in page.text
    assert 't' * 40 not in page.text
    assert 'HttpOnly' in page.headers['set-cookie']
    assert 'SameSite=strict' in page.headers['set-cookie']
    assert client.get('/pilot/v1/status').status_code == 200
    assert client.post('/pilot/v1/replay').status_code == 403
    assert client.post('/pilot/v1/replay', headers={'Origin':'https://external.example'}).status_code == 403
    assert client.get('/', headers={'Host':'external.example'}).status_code == 400
    assert client.get('/', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403


def test_dashboard_replay_reports_timeline_and_csv_match_sqlite(integrated):
    client, controller, config = integrated
    client.get('/')
    empty = client.get('/pilot/v1/reports').json()
    assert empty['workstations'] == []
    assert client.post('/pilot/v1/replay', headers=ORIGIN).status_code == 202
    assert client.post('/pilot/v1/replay', headers=ORIGIN).status_code == 409
    completed = wait(controller)
    snapshot = client.get('/pilot/v1/status').json()
    assert snapshot['committed_event_seq'] == 86
    assert len(snapshot['cameras']) == 1 and len(snapshot['workspaces']) == 2
    result = client.get('/pilot/v1/reports', params={'run_id': completed['run_id']}).json()
    first = result['workstations'][0]
    assert first['occupied_us'] == 3_800_000
    assert first['empty_us'] == 1_800_000
    assert first['unknown_us'] == 11_400_000
    daily = result['daily'][0]
    assert daily['workspace_id'] == first['workspace_id']
    assert daily['occupied_us'] == first['occupied_us']
    assert daily['unknown_us'] == first['unknown_us']
    assert daily['timezone'] == 'Asia/Jakarta'
    assert daily['identity_source'] == 'anonymous'
    assert sum((r['end']-r['start'])*1000 for r in result['intervals'] if r['workspaceId']==first['workspace_id']) == 17_000_000
    filtered = client.get('/pilot/v1/reports', params={'run_id': completed['run_id'],'workspace_id':first['workspace_id']}).json()
    assert len(filtered['workstations']) == 1
    assert {r['workspaceId'] for r in filtered['intervals']} == {first['workspace_id']}
    csv = client.get('/pilot/v1/export.csv', params={'run_id': completed['run_id'],'workspace_id':first['workspace_id']})
    assert 'SYNTHETIC_REPLAY' in csv.text and '3800000,1800000,11400000' in csv.text
    assert 'Meja A02' not in csv.text
    daily_csv = client.get('/pilot/v1/export.csv', params={'run_id': completed['run_id'], 'workspace_id': first['workspace_id'], 'daily': True})
    assert 'cctv-daily-report.csv' in daily_csv.headers['content-disposition']
    assert 'timezone=Asia/Jakarta' in daily_csv.text
    assert '3800000,1800000,11400000' in daily_csv.text
    assert 'Meja A02' not in daily_csv.text
    assert client.get('/pilot/v1/reports', params={'run_id':'missing'}).status_code == 404
    assert client.get('/pilot/v1/reports', params={'start_utc_us':2,'end_utc_us':1}).status_code == 422
    with closing(Database(config.database)) as db:
        assert db.conn.execute('SELECT COUNT(*) FROM event_log').fetchone()[0] == 86


def test_cancel_then_restart_preserves_history_and_inserts_unknown_gap(integrated):
    client, controller, config = integrated
    controller.delay = 0.03
    client.get('/')
    client.post('/pilot/v1/replay', headers=ORIGIN)
    deadline = time.monotonic()+5
    while controller.snapshot()['processed']<5 and time.monotonic()<deadline:
        time.sleep(0.01)
    client.post('/pilot/v1/replay/stop', headers=ORIGIN)
    cancelled = wait(controller,'CANCELLED')
    with closing(Database(config.database)) as db:
        first_events = db.conn.execute('SELECT COUNT(*) FROM event_log').fetchone()[0]
    controller.delay=0
    client.post('/pilot/v1/replay',headers=ORIGIN)
    second=wait(controller)
    assert second['run_id']!=cancelled['run_id']
    with closing(Database(config.database)) as db:
        assert db.conn.execute('SELECT COUNT(*) FROM engine_runs').fetchone()[0]==2
        assert db.conn.execute('SELECT COUNT(*) FROM event_log').fetchone()[0]==first_events+86
    all_runs=client.get('/pilot/v1/reports').json()
    assert any(r['reason']=='ENGINE_INTERRUPTED' for r in all_runs['intervals'])
    for workspace in all_runs['workstations']:
        days = [row for row in all_runs['daily'] if row['workspace_id'] == workspace['workspace_id']]
        for key in ('occupied_us', 'empty_us', 'unknown_us', 'eligible_us'):
            assert sum(row[key] for row in days) == workspace[key]


def test_daily_report_respects_end_of_workspace_monitoring(integrated):
    client, controller, config = integrated
    client.get('/')
    controller.delay = 0
    client.post('/pilot/v1/replay', headers=ORIGIN)
    completed = wait(controller)
    original = client.get('/pilot/v1/reports', params={'run_id': completed['run_id']}).json()
    workspace_id = original['workstations'][0]['workspace_id']
    start = original['start_utc_us']
    stop = start + 8_000_000
    with closing(Database(config.database)) as db, db.transaction() as conn:
        conn.execute('UPDATE workspaces SET monitoring_to_utc_us=? WHERE id=?', (stop, workspace_id))
    result = client.get('/pilot/v1/reports', params={'run_id': completed['run_id'], 'workspace_id': workspace_id}).json()
    row, = result['daily']
    assert row['end_utc_us'] == stop
    assert row['eligible_us'] == 8_000_000
    assert sum((interval['end'] - interval['start']) * 1000 for interval in result['intervals']) == row['eligible_us']


def test_employee_assignment_is_persisted_and_cannot_spoof_identity(integrated):
    client, controller, config = integrated
    client.get('/')
    controller.delay=0
    client.post('/pilot/v1/replay',headers=ORIGIN)
    wait(controller)
    snapshot=client.get('/pilot/v1/status').json()
    added=client.post('/pilot/v1/employees',headers=ORIGIN,json={'display_name':'Karyawan Dashboard'})
    assert added.status_code==201
    assert client.post('/pilot/v1/employees',headers=ORIGIN,json={'display_name':'   '}).status_code==422
    run=snapshot['runs'][0]
    values={'employee_id':added.json()['id'],'workspace_id':snapshot['workspaces'][0]['id'],'start_utc_us':run['started_utc_us'],'end_utc_us':run['ended_utc_us']}
    assert client.post('/pilot/v1/assignments',headers=ORIGIN,json=values).status_code==201
    assert client.post('/pilot/v1/assignments',headers=ORIGIN,json=values).status_code==409
    assert client.post('/pilot/v1/assignments',headers=ORIGIN,json={**values,'is_observed_identity':True}).status_code==422
    report=client.get('/pilot/v1/reports').json()['workstations'][0]
    assert report['observed_employee_id'] is None
    assert report['assignment_is_observed_identity'] is False
    assert report['workstation_assignments'][0]['display_name']=='Karyawan Dashboard'


def test_synthetic_replay_cannot_mix_into_another_data_source(integrated):
    client, controller, config = integrated
    client.get('/')
    controller.delay=0
    client.post('/pilot/v1/replay',headers=ORIGIN)
    wait(controller)
    with closing(Database(config.database)) as db:
        with db.transaction() as conn:
            conn.execute("UPDATE engine_runs SET runtime_manifest_json=json_set(runtime_manifest_json,'$.data_source','LOCAL_VIDEO_REPLAY')")
    response=client.post('/pilot/v1/replay',headers=ORIGIN)
    assert response.status_code==409
    assert 'terpisah' in response.json()['detail']
