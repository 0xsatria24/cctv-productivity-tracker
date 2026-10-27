from copy import deepcopy
import json

import pytest

from cctv_tracker.dataset import (baseline,digest,manifest_hash,prediction_rows,prepare,read_json,write_json)
from cctv_tracker.detector_evaluation import compare,threshold_proposal,write_report
from test_dataset import fixture,make_video


def measured_fixture():
    manifest,labels,predictions=fixture()
    for row in labels['frames'].values():
        row['persons']=[{'person_id':'p1','box':[.1,.1,.4,.8]}]
    predictions.update(model={'threshold':.45},model_sha256='f'*64,warmup_frames=2)
    for key in labels['frames']:
        predictions['frames'][key]={'detections':[], 'candidate_floor':.1,
              'candidates':[{'box':[.1,.1,.4,.8],'confidence':.3}],'inference_ms':10}
    return manifest,labels,predictions


def test_sweep_uses_weak_candidates_without_promoting_labels_or_live_settings():
    m,l,p=measured_fixture()
    for row in l['frames'].values():
        row['label_source']='assistant'
    result=compare(m,l,{'YOLOX':p},thresholds=[.25,.45])
    low,high=result['models'][0]['variants']
    assert low['evaluation']['metrics']['overall']['recall'] == 1
    assert high['evaluation']['metrics']['overall']['recall'] == 0
    assert result['label_sources'] == {'assistant':3}
    assert result['threshold_proposal']['state'] == 'NOT_ELIGIBLE'
    assert not result['threshold_proposal']['applied']
    assert not result['live_configuration_changed'] and not result['production_qualified']
    assert low['object_height_recall']['at_least_one_third_frame_height']=={'persons':3,'detected':3,'recall':1}


def test_legacy_cache_cannot_be_swept_below_its_filtered_threshold():
    m,l,p=measured_fixture()
    for row in p['frames'].values():
        row.pop('candidates');row.pop('candidate_floor')
    result=compare(m,l,{'legacy':p},thresholds=[.25,.45])
    assert result['models'][0]['variants'][0]['state'] == 'UNAVAILABLE_BELOW_CACHE_FLOOR'
    with pytest.raises(ValueError,match='floor'):
        prediction_rows(p,next(iter(l['frames'])),.25)


def test_paired_coverage_manifest_and_completion_are_enforced():
    m,l,p=measured_fixture()
    other=deepcopy(p);other['frames'].pop(next(iter(l['frames'])))
    with pytest.raises(ValueError,match='every reviewed'):
        compare(m,l,{'full':p,'partial':other})
    other['state']='RUNNING'
    with pytest.raises(ValueError,match='completed'):
        compare(m,l,{'partial':other})
    other=deepcopy(p);other['manifest_sha256']='wrong'
    with pytest.raises(ValueError,match='immutable'):
        compare(m,l,{'other':other})


def test_test_split_cannot_be_used_for_threshold_search():
    m,l,p=measured_fixture()
    with pytest.raises(ValueError,match='frozen'):
        compare(m,l,{'model':p},split='test',thresholds=[.25,.45])


@pytest.mark.parametrize('value',[float('nan'),float('inf'),0,1.1])
def test_invalid_iou_is_rejected_even_without_labels(value):
    m,l,p=measured_fixture()
    for row in l['frames'].values():row['reviewed']=False
    with pytest.raises(ValueError,match='IoU'):
        compare(m,l,{'model':p},iou_threshold=value)


def test_baseline_warms_selected_images_and_stores_candidates_separately(tmp_path):
    from types import SimpleNamespace
    video=tmp_path/'source.mp4';make_video(video)
    data=tmp_path/'dataset';manifest=prepare([video],data,group='synthetic')
    labels=read_json(data/'labels.json')
    key=next(iter(labels['frames']))
    labels['frames'][key].update(reviewed=True,reviewer='Test',scenarios=['normal'])
    calls=[]
    def detect(image):
        calls.append(image)
        return {'width':800,'height':400,'detections':[],
                'tracking_candidates':[{'box':[.1,.1,.4,.8],'confidence':.2}]}
    fake=SimpleNamespace(manifest={'tracking_candidate_threshold':.1,'threshold':.45},sha='f'*64,detect=detect)
    result=baseline(data,tmp_path/'prediction.json',detector=fake,labels=labels,reviewed_only=True,warmup=2)
    assert len(calls)==3
    assert list(result['frames'])==[key]
    assert result['frames'][key]['candidate_floor']==.1
    assert len(result['frames'][key]['candidates'])==1 and not result['frames'][key]['detections']
    assert result['label_snapshot_sha256']==manifest_hash(labels)
    assert not read_json(data/'labels.json')['frames'][key]['reviewed']


def test_threshold_proposal_never_applies_and_requires_empty_frames_and_holdout():
    m,l,p=measured_fixture()
    sequence=m['sequences'][0];sequence['split']='validation'
    template=deepcopy(sequence['frames'][0]);sequence['frames']=[];l['frames']={}
    for i in range(21):
        frame={**template,'key':f'validation:{i}','number':i+1};sequence['frames'].append(frame)
        l['frames'][frame['key']]={'reviewed':True,'reviewer':'Test','label_source':'human',
            'scenarios':['empty'] if i==20 else ['normal'],'comment':'',
            'persons':[] if i==20 else [{'person_id':f'p{n}','box':[.1,.1,.4,.8]} for n in range(3)]}
    model={'name':'model','variants':[{'confidence':.45,'evaluation':{'metrics':{'overall':{'precision':1,'recall':1,'f1':1}}}}]}
    assert threshold_proposal(m,l,[model],'validation')['state']=='NOT_ELIGIBLE'
    m['sequences'].append({'id':'test','group':'another-day','split':'test','sha256':'c'*64,'frames':[]})
    assert threshold_proposal(m,l,[model],'validation')['state']=='NOT_ELIGIBLE'
    m['sequences'][-1]['frames']=[{**template,'key':'heldout:1'}]
    result=threshold_proposal(m,l,[model],'validation')
    # Declaring a test group alone does not constitute field acceptance.
    assert result['state']=='PROPOSAL_REQUIRES_HELD_OUT_ACCEPTANCE'
    assert not result['applied'] and not result['production_qualified']
    l['frames']['validation:0']['label_source']='pseudo'
    assert threshold_proposal(m,l,[model],'validation')['state']=='NOT_ELIGIBLE'


def test_report_is_private_escaped_and_does_not_overwrite(tmp_path):
    video=tmp_path/'source.mp4';make_video(video)
    data=tmp_path/'dataset';manifest=prepare([video],data,group='synthetic')
    labels=read_json(data/'labels.json');predictions={'state':'COMPLETED','manifest_sha256':manifest_hash(manifest),'frames':{}}
    for key,row in labels['frames'].items():
        row.update(reviewed=True,reviewer='Test',scenarios=['empty'],comment='</script><img src=x onerror=alert(1)>')
        predictions['frames'][key]={'detections':[],'inference_ms':1}
    original=digest(data/'labels.json')
    result=write_report(data,labels,{'model':predictions},tmp_path/'report',thresholds=[.45])
    html=(tmp_path/'report'/'review.html').read_text(encoding='utf-8')
    assert '</script><img src=x' not in html
    assert '\\u003c/script>' in html
    assert 'data:image/jpeg;base64,' in html
    assert digest(data/'labels.json')==original
    assert (tmp_path/'report'/'summary.csv').exists()
    with pytest.raises(FileExistsError):
        write_report(data,labels,{'model':predictions},tmp_path/'report',thresholds=[.45])


def test_report_preview_only_serves_one_document_and_rejects_foreign_host(tmp_path):
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import Request,urlopen
    from cctv_tracker.detector_report_server import make_server
    (tmp_path/'review.html').write_text('<html>PRIVATE SYNTHETIC REPORT</html>')
    (tmp_path/'labels-snapshot.json').write_text('PRIVATE LABELS')
    with make_server(tmp_path,0) as server:
        worker=Thread(target=server.serve_forever,daemon=True);worker.start()
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(url,timeout=3) as response:
                assert b'PRIVATE SYNTHETIC REPORT' in response.read()
            for path in ('/labels-snapshot.json','/../labels-snapshot.json'):
                with pytest.raises(HTTPError) as error:urlopen(url+path,timeout=3)
                assert error.value.code==404
            with pytest.raises(HTTPError) as error:
                urlopen(Request(url,headers={'Host':'untrusted.invalid'}),timeout=3)
            assert error.value.code==403
        finally:
            server.shutdown();worker.join(timeout=2)
