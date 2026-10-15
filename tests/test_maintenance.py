from contextlib import closing
import json

import pytest

from cctv_tracker.config import Settings
from cctv_tracker.fleet import CameraFleet, FairDetector
from cctv_tracker.lease import EngineLease
from cctv_tracker.maintenance import BackupManager, app_lock_path
from cctv_tracker.persistence import Database
from test_live import FixtureDetector
from test_fleet import Capture, setup_camera


def test_verified_round_trip_includes_config_and_refuses_running_app(tmp_path):
    path = tmp_path / 'site.sqlite3'
    with closing(Database(path)) as db:
        original = db.add_employee('Before backup')
    fleet = CameraFleet(Settings(database=path), FairDetector(FixtureDetector()), capture_factory=Capture)
    camera = setup_camera(fleet, 'north')
    manager = BackupManager(path, fleet)
    manifest = manager.create()
    fleet.shutdown()
    manager.fleet = None
    assert len(manifest['files']) == 3
    with closing(Database(path)) as db:
        db.add_employee('After backup')
    lease = EngineLease(app_lock_path(path))
    try:
        with pytest.raises(RuntimeError, match='Another occupancy writer'):
            manager.restore(manifest['id'])
    finally:
        lease.close()
    receipt = manager.restore(manifest['id'])
    assert receipt['verified'] and receipt['safety_backup_id'] != manifest['id']
    with closing(Database(path)) as db:
        assert [r['id'] for r in db.conn.execute('SELECT id FROM employees')] == [original]
    reloaded = CameraFleet(Settings(database=path), FixtureDetector(), capture_factory=Capture)
    try:
        assert reloaded.get(camera).engine.profiles['RTSP_LIVE']['revision'] == 1
    finally:
        reloaded.shutdown()
    assert manager.status()['restore_receipt']['verified']
    assert not manager.journal.exists()


def test_tamper_path_rejection_and_partial_restore_resume(tmp_path, monkeypatch):
    path = tmp_path / 'site.sqlite3'
    with closing(Database(path)) as db:
        db.add_employee('Saved')
    manager = BackupManager(path)
    snapshot = manager.create()
    with pytest.raises(ValueError):
        manager.verify('../other')
    with pytest.raises(ValueError):
        manager.target('fleet/../outside')
    backup = manager.root / snapshot['id'] / 'replay.sqlite3'
    content = backup.read_bytes()
    backup.write_bytes(b'invalid')
    with pytest.raises(ValueError, match='checksum'):
        manager.restore(snapshot['id'])
    assert not manager.journal.exists()
    backup.write_bytes(content)
    import cctv_tracker.maintenance as module
    write = module.atomic_write
    def fail_receipt(target, data):
        if target == manager.receipt:
            raise OSError('injected crash after database restore')
        write(target, data)
    monkeypatch.setattr(module, 'atomic_write', fail_receipt)
    with pytest.raises(OSError):
        manager.restore(snapshot['id'])
    assert manager.journal.exists()
    safety = json.loads(manager.journal.read_text())['safety_backup_id']
    monkeypatch.setattr(module, 'atomic_write', write)
    assert manager.restore(snapshot['id'])['safety_backup_id'] == safety
    assert not manager.journal.exists()
