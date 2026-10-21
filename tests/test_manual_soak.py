from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts'/'soak_dashboard.py'))
Monitor, validate = MODULE['Monitor'],MODULE['validate_options']


def options(**overrides):
    return SimpleNamespace(**{**dict(url='http://127.0.0.1:8767',hours=24,interval=5,timeout=5,grace=60,
                              no_progress=30,max_rss_mb=4096,max_growth_mb=512,min_free_mb=1024,
                              max_log_mb=256,min_fps=.5,max_age_ms=5000,pid=None),**overrides})


def test_manual_runner_only_accepts_loopback_and_bounded_configuration():
    assert validate(options(hours=72)).hours == 72
    for values in ({'hours':73},{'hours':float('nan')},{'interval':float('inf')},
                   {'url':'http://admin:secret@127.0.0.1:8767'}, {'url':'http://public.example'},
                   {'url':'http://127.0.0.1:8767/path'},{'url':'http://127.0.0.1:bad'},
                   {'interval':40,'no_progress':30}):
        with pytest.raises(ValueError):
            validate(options(**values))


def wall(processed=0,session='one',health='ONLINE',analysis=True):
    import time
    return {'cameras':[{'id':'a','analysis':analysis,'engine':{'processed':processed,'session_id':session,
             'camera_health':health,'status':'RUNNING',
             'latest':{'processed_monotonic_ns':time.perf_counter_ns()},'performance':{}}}]}


def test_monitor_detects_persistent_outage_and_session_counter_reset():
    monitor=Monitor(['a'],grace=10,no_progress=5,min_fps=.5,max_age_ms=5000)
    assert monitor.sample(wall(10),0)[0]['effective_fps'] is None
    assert monitor.sample(wall(20),5)[0]['effective_fps'] == 2
    monitor.sample(wall(21,health='RECONNECTING'),10)
    assert not monitor.findings
    monitor.sample(wall(21,health='RECONNECTING'),16)
    assert ('ENGINE_UNHEALTHY','a') in monitor.findings
    monitor.sample(wall(1,session='two'),20)
    assert monitor.findings[('SESSION_RESTART','a')]['samples'] == 1
    monitor.sample(wall(20,session='two'),25)
    assert ('ENGINE_UNHEALTHY','a') not in monitor.conditions


def test_monitor_keeps_expected_camera_set_and_bounds_history():
    monitor=Monitor(['a'],grace=0,no_progress=5,min_fps=.5,max_age_ms=5000)
    for elapsed in range(100):
        monitor.sample({'cameras':[]},elapsed)
    assert set(monitor.previous) == set()
    assert len(monitor.findings) == 1
    assert ('CAMERA_REMOVED','a') in monitor.findings


def test_observer_refreshes_cookie_after_app_restart():
    paths=[]
    statuses=iter([403,200,200])
    def get(path,**kwargs):
        paths.append(path)
        return SimpleNamespace(status_code=next(statuses),raise_for_status=lambda:None,json=lambda:wall(1))
    result=MODULE['fetch_wall'](SimpleNamespace(get=get),'http://127.0.0.1:8767',5)
    assert result['cameras'][0]['id'] == 'a'
    assert paths == ['http://127.0.0.1:8767/pilot/v1/camera-wall',
                     'http://127.0.0.1:8767/','http://127.0.0.1:8767/pilot/v1/camera-wall']


def test_dry_run_does_not_contact_app_or_create_output(tmp_path):
    import json
    output=tmp_path/'not-created'
    script=Path(__file__).resolve().parents[1]/'scripts'/'soak_dashboard.py'
    result=subprocess.run([sys.executable,str(script),'--hours','24','--url','http://127.0.0.1:1',
                           '--output',str(output),'--dry-run'],capture_output=True,text=True,timeout=20)
    assert result.returncode == 0,result.stderr
    assert json.loads(result.stdout)['state'] == 'NOT_STARTED'
    assert not output.exists()
