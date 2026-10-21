from types import SimpleNamespace
import cv2
import numpy as np
import pytest

from cctv_tracker.detector_zoom import ZoomExperiment


class FakeDetector:
    sha='f'*64
    manifest={'threshold':.45,'tracking_candidate_threshold':.1}
    def __init__(self,results):self.results=iter(results);self.shapes=[]
    def detect(self,jpeg):
        image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),1);h,w=image.shape[:2]
        self.shapes.append((w,h))
        rows=next(self.results)
        return {'width':w,'height':h,'detections':[d for d in rows if d['confidence']>=.45],
                'tracking_candidates':rows}


def jpeg():return cv2.imencode('.jpg',np.zeros((480,640,3),np.uint8))[1].tobytes()


def test_zoom_maps_measured_boxes_and_drops_artificial_edge_fragments():
    detector=FakeDetector([[],[{'box':[.1,.1,.9,.9],'confidence':.8},
                              {'box':[0,.1,.2,.8],'confidence':.9},
                              {'box':[.2,.4,.8,1],'confidence':.7}]])
    result=ZoomExperiment(detector,[(.25,0,.5,.5)]).detect(jpeg())
    assert detector.shapes==[(640,480),(160,240)]
    assert result['count']==1 and result['boundary_candidates_rejected']==2
    assert result['detections'][0]['box']==pytest.approx([.275,.05,.475,.45])
    assert result['zoom_passes']==2


def test_zoom_deduplicates_same_person_but_keeps_low_confidence_separate():
    same={'box':[.275,.05,.475,.45],'confidence':.9}
    detector=FakeDetector([[same],[{'box':[.1,.1,.9,.9],'confidence':.8},
                                {'box':[.1,.01,.3,.05],'confidence':.2}]])
    result=ZoomExperiment(detector,[(.25,0,.5,.5)]).detect(jpeg())
    assert result['count']==1 and len(result['tracking_candidates'])==2
    assert result['detections'][0]==same


def test_true_frame_edge_is_not_discarded_and_invalid_regions_fail():
    detector=FakeDetector([[],[{'box':[0,0,.5,.5],'confidence':.8}]])
    result=ZoomExperiment(detector,[(0,0,.5,.5)]).detect(jpeg())
    assert result['count']==1
    for regions in ([],[(0,0,0,1)],[(0,0,float('nan'),1)],[(0,0,1,1)]*5):
        with pytest.raises(ValueError):ZoomExperiment(detector,regions)
