import copy
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cctv_tracker.dataset import (baseline, evaluate_boxes, manifest_hash, match_boxes,
                                  prepare, read_json, validate_labels, validate_splits, write_json)


def fixture():
    frames = [{'key':f'clip:1:{i}', 'number':i, 'seconds':i/2, 'image':f'frames/clip/{i}.jpg',
               'width':640,'height':480,'sha256':'a'*64} for i in (1,2,3)]
    manifest = {'version':1,'sample_fps':2,'sequences':[{'id':'clip','group':'site/day',
                'split':'pilot','sha256':'b'*64,'frames':frames}]}
    labels = {'version':1,'revision':0,'manifest_sha256':manifest_hash(manifest),
              'frames':{f['key']:{'reviewed':True,'reviewer':'tester','label_source':'human',
                       'scenarios':['normal'],'comment':'','persons':[]} for f in frames}}
    predictions = {'state':'COMPLETED','manifest_sha256':manifest_hash(manifest),'frames':{}}
    return manifest,labels,predictions


def test_unreviewed_is_not_empty_and_scenarios_have_separate_counts():
    m,l,p = fixture()
    l['frames']['clip:1:1']['reviewed'] = False
    l['frames']['clip:1:2'].update(persons=[{'person_id':'p1','box':[.1,.1,.4,.8]}],scenarios=['bending','occlusion'])
    p['frames'] = {f'clip:1:{i}':{'detections':[{'box':[.1,.1,.4,.8],'confidence':.9}]} for i in (1,2,3)}
    result = evaluate_boxes(m,l,p)
    assert result['reviewed_frames'] == 2
    assert result['metrics']['overall']['tp'] == 1
    assert result['metrics']['overall']['fp'] == 1
    assert result['metrics']['scenario:bending']['recall'] == 1
    assert result['review_coverage'] == 2/3
    assert not result['production_qualified']
    for row in l['frames'].values():
        row['reviewed'] = False
    assert evaluate_boxes(m,l,p)['state'] == 'AWAITING_LABELS'


def test_missing_predictions_are_misses_and_empty_frames_are_scored():
    m,l,p = fixture()
    l['frames']['clip:1:1']['persons'] = [{'person_id':'p1','box':[.1,.1,.4,.8]}]
    l['frames']['clip:1:2']['label_source'] = 'assistant'
    p['frames']['clip:1:3'] = {'detections':[{'box':[.1,.1,.4,.8],'confidence':.9}]}
    result = evaluate_boxes(m,l,p)
    assert result['metrics']['overall']['fn'] == 1
    assert result['metrics']['overall']['fp'] == 1
    assert result['missing_prediction_frames'] == 2
    assert result['label_sources'] == {'human':2,'assistant':1}
    p['state'] = 'RUNNING'
    with pytest.raises(ValueError,match='completed'):
        evaluate_boxes(m,l,p)


def test_assignment_maximizes_cardinality_before_iou(monkeypatch):
    # A greedy best pair (0,0) would incorrectly leave one false miss and false positive.
    import cctv_tracker.dataset as module
    overlaps = [[.9,.6],[.6,.1]]
    monkeypatch.setattr(module,'iou',lambda a,b:overlaps[a[0]][b[0]])
    assert set(match_boxes([{'box':[0]},{'box':[1]}],[{'box':[0]},{'box':[1]}],.5)) == {(0,1),(1,0)}


def test_label_validation_and_group_leakage():
    m,l,p = fixture()
    duplicate = copy.deepcopy(m['sequences'][0]); duplicate.update(id='other',split='test',sha256='c'*64)
    with pytest.raises(ValueError,match='leakage'):
        validate_splits([m['sequences'][0],duplicate])
    duplicate.update(group='other site/day',sha256='b'*64)
    with pytest.raises(ValueError,match='leakage'):
        validate_splits([m['sequences'][0],duplicate])
    l['frames']['clip:1:1']['reviewer'] = ''
    with pytest.raises(ValueError,match='reviewer'):
        validate_labels(m,l)
    l['frames']['clip:1:1']['reviewer'] = 'tester'
    l['frames']['clip:1:1']['persons'] = [{'person_id':'p1','box':[0,0,float('nan'),1]}]
    with pytest.raises(ValueError,match='finite'):
        validate_labels(m,l)


def make_video(path):
    import av
    import numpy as np
    with av.open(str(path),'w') as output:
        stream = output.add_stream('mpeg4',rate=10)
        stream.width,stream.height,stream.pix_fmt = 800,400,'yuv420p'
        for i in range(12):
            frame=av.VideoFrame.from_ndarray(np.full((400,800,3),i*10,dtype=np.uint8),format='bgr24')
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


def test_prepare_pts_aspect_ratio_checksums_and_no_overwrite(tmp_path):
    import cv2
    from cctv_tracker.dataset import digest
    video=tmp_path/'source.mp4'; make_video(video)
    output=tmp_path/'dataset'
    m=prepare([video],output,group='site/day',sample_fps=2)
    sequence=m['sequences'][0]
    assert len(sequence['frames']) == 3
    assert [f['seconds'] for f in sequence['frames']] == [0,.5,1]
    f=sequence['frames'][0]
    assert cv2.imread(str(output/f['image'])).shape[:2] == (320,640)
    assert f['sha256'] == digest(output/f['image'])
    assert validate_labels(m,read_json(output/'labels.json'))
    with pytest.raises(FileExistsError):
        prepare([video],output,group='site/day')


def test_corrupt_and_duplicate_frames_are_dropped_without_compressing_time(tmp_path,monkeypatch):
    import av
    from contextlib import nullcontext
    from types import SimpleNamespace
    import numpy as np
    raw=av.VideoFrame.from_ndarray(np.zeros((240,320,3),np.uint8),format='bgr24')
    def frame(pts,corrupt=False):
        return SimpleNamespace(time=pts,is_corrupt=corrupt,width=320,height=240,
                               reformat=lambda **kwargs:raw.reformat(**kwargs))
    frames=[frame(5,True),frame(5.2),frame(5.2),frame(5.4,True),frame(5.8)]
    source=SimpleNamespace(streams=SimpleNamespace(video=[SimpleNamespace(average_rate=15)]),
                           decode=lambda **kwargs:iter(frames))
    monkeypatch.setattr(av,'open',lambda *_:nullcontext(source))
    video=tmp_path/'source.mp4';video.write_bytes(b'SYNTHETIC CORRUPTION METADATA')
    manifest=prepare([video],tmp_path/'dataset',group='synthetic',sample_fps=10)
    seq=manifest['sequences'][0]
    assert seq['corrupt_dropped'] == 2 and seq['duplicate_pts_dropped'] == 1
    assert [f['seconds'] for f in seq['frames']] == pytest.approx([.2,.8])


def test_baseline_is_not_ground_truth_and_rejects_modified_image(tmp_path):
    from types import SimpleNamespace
    video=tmp_path/'source.mp4'; make_video(video)
    dataset=tmp_path/'dataset'; m=prepare([video],dataset,group='site/day')
    fake=SimpleNamespace(manifest={'source':'SYNTHETIC_TEST'},sha='f'*64,
                         detect=lambda image:{'width':640,'height':320,'detections':[]})
    result=baseline(dataset,tmp_path/'baseline.json',detector=fake)
    assert result['state'] == 'COMPLETED' and not result['accuracy_evaluated']
    assert not any(row['reviewed'] for row in read_json(dataset/'labels.json')['frames'].values())
    (dataset/m['sequences'][0]['frames'][0]['image']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum'):
        baseline(dataset,tmp_path/'modified.json',detector=fake)
    assert read_json(tmp_path/'modified.json')['state'] == 'FAILED'


def test_local_annotation_server_rejects_csrf_conflicts_and_path_traversal(tmp_path):
    from cctv_tracker.dataset_server import make_server
    video=tmp_path/'source.mp4'; make_video(video)
    dataset=tmp_path/'dataset'; prepare([video],dataset,group='site/day')
    with make_server(dataset,0) as server:
        thread=Thread(target=server.serve_forever,daemon=True); thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base) as response:
                html=response.read().decode()
            token=html.split("'X-Annotation-Token':'",1)[1].split("'",1)[0]
            value=read_json(dataset/'labels.json')
            payload=json.dumps(value).encode()
            def put(headers):
                return urlopen(Request(base+'/labels',data=payload,method='PUT',headers={'Content-Type':'application/json',**headers}))
            with pytest.raises(HTTPError) as error:
                put({})
            assert error.value.code == 403
            with pytest.raises(HTTPError) as error:
                put({'X-Annotation-Token':token,'Origin':'https://untrusted.invalid'})
            assert error.value.code == 403
            with put({'X-Annotation-Token':token}) as response:
                assert json.load(response)['revision'] == 1
            with pytest.raises(HTTPError) as error:
                put({'X-Annotation-Token':token})
            assert error.value.code == 409
            with pytest.raises(HTTPError) as error:
                urlopen(base+'/../labels.json')
            assert error.value.code == 404
        finally:
            server.shutdown(); thread.join(timeout=2)
