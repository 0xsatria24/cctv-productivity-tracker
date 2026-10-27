from contextlib import closing
import json
import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

from cctv_tracker.record_destinations import DEFAULT_DESTINATION, DestinationManager, StorageAdapter, TransferFailure, rclone_path, validate_destination


def destination(tmp_path):
    return {**DEFAULT_DESTINATION,'enabled':True,'kind':'folder','folder':str(tmp_path/'nas')}


def artifact(manager, identifier='a'*32):
    name=identifier+'.mp4'
    (manager.root/name).write_bytes(b'SYNTHETIC record fixture\n'*100)
    return identifier,name


@pytest.mark.parametrize('update',[
    {'kind':'folder','folder':'relative/path'}, {'prefix':'../outside'}, {'prefix':'/root'},
    {'kind':'rclone','remote':'--config=secret'}, {'kind':'rclone','remote':'drive:path'},
    {'kind':'s3','bucket':'records','endpoint':'https://user:password@example.com'},
    {'kind':'s3','bucket':'records','endpoint':'file:///tmp/object'}, {'enabled':'true'},
])
def test_destination_validation(tmp_path, update):
    with pytest.raises(ValueError):
        validate_destination({**DEFAULT_DESTINATION,**update},tmp_path/'records')


def test_nas_copy_is_verified_idempotent_durable_and_pauses_on_target_change(tmp_path):
    manager=DestinationManager(tmp_path/'records')
    config=destination(tmp_path)
    manager.configure(config)
    identifier,name=artifact(manager)
    assert manager.enqueue(identifier,[name])==1
    assert manager.process_one()
    target=Path(config['folder'])/'CCTV'/identifier/name
    assert target.read_bytes()==(manager.root/name).read_bytes()
    assert manager.status()['counts']=={'COMPLETED':1}
    assert manager.enqueue(identifier,[name])==0
    other,other_name=artifact(manager,'b'*32)
    manager.enqueue(other,[other_name])
    with manager._db() as db, db:
        db.execute("UPDATE uploads SET state='UPLOADING' WHERE filename=?",(other_name,))
    restored=DestinationManager(manager.root)
    assert restored.status()['counts']['RETRY']==1
    restored.configure({**config,'enabled':False})
    assert not restored.process_one()
    restored.configure({**config,'folder':str(tmp_path/'nas-other')})
    assert restored.status()['paused_other_destination']==1
    assert not restored.process_one()
    assert not (tmp_path/'nas-other').exists()
    restored.configure(config)
    assert restored.process_one()
    assert restored.status()['counts']=={'COMPLETED':2}
    with pytest.raises(ValueError):
        restored.enqueue(identifier,['destination.protected'])


def test_failed_network_retries_are_bounded_and_survive_restart(tmp_path):
    now=[1000.]
    class Offline:
        def __init__(self,config): pass
        def put(self,*args): raise TransferFailure('Offline fixture')
    manager=DestinationManager(tmp_path/'records',adapter_factory=Offline,clock=lambda:now[0])
    manager.configure(destination(tmp_path))
    identifier,name=artifact(manager)
    manager.enqueue(identifier,[name]);manager.process_one()
    assert manager.status()['counts']=={'RETRY':1}
    assert not manager.process_one()
    manager=DestinationManager(manager.root,adapter_factory=Offline,clock=lambda:now[0])
    for attempt in range(7):
        now[0]+=301
        assert manager.process_one()
    assert manager.status()['counts']=={'FAILED':1}
    assert (manager.root/name).is_file()
    manager.retry()
    assert manager.status()['counts']=={'PENDING':1}
    assert manager.status()['recent'][0]['attempts']==0


def test_credentials_are_protected_redacted_and_not_reused_for_a_different_host(tmp_path):
    manager=DestinationManager(tmp_path/'records')
    value={**DEFAULT_DESTINATION,'enabled':True,'kind':'s3','endpoint':'https://storage.example.com','bucket':'records',
        'access_key':'fixture-access-key','secret_key':'fixture-private-secret'}
    manager.configure(value)
    public=json.dumps(manager.status())
    assert 'fixture-access-key' not in public and 'fixture-private-secret' not in public
    assert b'fixture-private-secret' not in manager.store.path.read_bytes()
    blank={**value,'access_key':'','secret_key':''}
    manager.configure(blank)
    assert manager.config['secret_key']=='fixture-private-secret'
    restored=DestinationManager(manager.root)
    assert restored.status()['secrets_configured']['secret_key']
    with pytest.raises(ValueError,match='kredensial'):
        restored.configure({**blank,'endpoint':'https://different.example.com'})


@pytest.mark.skipif(not rclone_path(),reason='Official rclone helper is not installed')
def test_actual_rclone_remote_copy_discovery_and_connection_probe(tmp_path,monkeypatch):
    root=tmp_path/'cloud-fixture';root.mkdir()
    config=tmp_path/'fixture.conf'
    config.write_text('[fixture]\ntype = alias\nremote = '+str(root).replace('\\','/')+'\n')
    monkeypatch.setenv('RCLONE_CONFIG',str(config))
    manager=DestinationManager(tmp_path/'records')
    value={**DEFAULT_DESTINATION,'enabled':True,'kind':'rclone','remote':'fixture'}
    manager.configure(value)
    assert manager.discover()['remotes']==[{'name':'fixture','type':'alias'}]
    identifier,name=artifact(manager)
    manager.enqueue(identifier,[name]);assert manager.process_one()
    assert manager.status()['counts']=={'COMPLETED':1}
    assert (root/'CCTV'/identifier/name).read_bytes()==(manager.root/name).read_bytes()
    adapter=StorageAdapter(value)
    adapter.probe(manager.state_root)
    assert not list(root.rglob('cctv-connection-test-*'))


@pytest.mark.skipif(not rclone_path(),reason='Official rclone helper is not installed')
def test_actual_s3_protocol_against_owned_loopback_fixture(tmp_path):
    root=tmp_path/'s3-fixture';(root/'records').mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([rclone_path(),'serve','s3',str(root),'--addr',f'127.0.0.1:{port}','--auth-key','fixture-access,fixture-secret'],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2): break
            except OSError: time.sleep(.1)
        else: pytest.fail('Owned loopback S3 fixture did not start')
        manager=DestinationManager(tmp_path/'records-local')
        value={**DEFAULT_DESTINATION,'kind':'s3','enabled':True,'provider':'Minio','endpoint':f'http://127.0.0.1:{port}',
            'bucket':'records','access_key':'fixture-access','secret_key':'fixture-secret'}
        manager.configure(value)
        identifier,name=artifact(manager)
        manager.enqueue(identifier,[name]);manager.process_one()
        assert manager.status()['counts']=={'COMPLETED':1},manager.status()['recent']
        assert (root/'records'/'CCTV'/identifier/name).read_bytes()==(manager.root/name).read_bytes()
    finally:
        process.terminate();process.wait(timeout=10)


def test_destination_api_auth_validation_and_secret_redaction(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from cctv_tracker.api import create_app
    from cctv_tracker.config import Settings
    from cctv_tracker.dashboard import ReplayController
    from cctv_tracker.persistence import Database
    import cctv_tracker.engine as module
    from test_live import FixtureDetector
    detector=FixtureDetector();detector.runtime_label='SYNTHETIC';detector.session=True;detector.manifest={}
    monkeypatch.setattr(module,'create_detector',lambda *args, **kwargs:detector)
    settings=Settings(database=tmp_path/'app.sqlite3')
    with closing(Database(settings.database)): pass
    with TestClient(create_app(settings.database,'t'*40,controller=ReplayController(settings))) as client:
        auth={'Authorization':'Bearer '+'t'*40}
        assert client.get('/pilot/v1/recordings/destination').status_code==401
        assert client.post('/pilot/v1/recordings/destination',headers={**auth,'Origin':'https://external.example'},json=DEFAULT_DESTINATION).status_code==403
        assert client.post('/pilot/v1/recordings/destination',headers=auth,json={**DEFAULT_DESTINATION,'kind':'folder','folder':'relative'}).status_code==422
        assert client.post('/pilot/v1/recordings/destination/enqueue-recent',headers=auth).status_code==422
        value={**DEFAULT_DESTINATION,'kind':'s3','enabled':False,'bucket':'records','endpoint':'https://example.invalid',
            'access_key':'api-fixture-access','secret_key':'api-fixture-secret'}
        response=client.post('/pilot/v1/recordings/destination',headers=auth,json=value)
        assert response.status_code==200
        assert response.json()['secrets_configured']['secret_key']
        assert 'api-fixture-secret' not in response.text and 'api-fixture-access' not in response.text
        assert 'api-fixture-secret' not in client.get('/pilot/v1/recordings/destination',headers=auth).text
