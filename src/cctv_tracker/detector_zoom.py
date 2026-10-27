"""Opt-in offline ROI-zoom experiment using the same detector weights.

Not constructed by engine.py or any live edition. Accuracy, duplicated boxes and
additional latency must be reviewed before a camera policy can adopt this.
"""
import math
import time

from .dataset import iou
from .vision import Detection
from .person_detection import detection_proposals


class ZoomExperiment:
    def __init__(self,detector,regions):
        if not 1<=len(regions)<=4:
            raise ValueError('Specify 1..4 normalized zoom regions')
        for region in regions:
            if len(region)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in region) or region[2]<=region[0] or region[3]<=region[1]:
                raise ValueError('Zoom regions require finite normalized xyxy coordinates')
        self.detector,self.regions,self.sha=detector,tuple(tuple(r) for r in regions),detector.sha
        self.manifest={**detector.manifest,'analysis_profile':'OFFLINE_ROI_ZOOM',
                       'zoom_regions':self.regions,'internal_boundary_margin_pixels':2}

    def detect(self,jpeg):
        import cv2
        import numpy as np
        started=time.perf_counter()
        image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Invalid zoom source JPEG')
        height,width=image.shape[:2]
        whole=self.detector.detect(jpeg)
        if (whole['width'],whole['height'])!=(width,height):
            raise ValueError('Detector dimensions do not match the image')
        if 'tracking_candidates' not in whole:
            raise ValueError('Zoom experiment requires unfiltered measured candidates')
        candidates=[dict(d) for d in detection_proposals(whole)]
        boundary_rejected=0
        for region in self.regions:
            x0,y0,x1,y1=round(region[0]*width),round(region[1]*height),round(region[2]*width),round(region[3]*height)
            crop_width,crop_height=x1-x0,y1-y0
            if min(crop_width,crop_height)<32:
                raise ValueError('Zoom region must span at least 32 source pixels per side')
            ok,encoded=cv2.imencode('.jpg',image[y0:y1,x0:x1],[cv2.IMWRITE_JPEG_QUALITY,75])
            if not ok:
                raise ValueError('Zoom JPEG encoding failed')
            result=self.detector.detect(encoded.tobytes())
            if (result['width'],result['height'])!=(crop_width,crop_height):
                raise ValueError('Detector dimensions do not match the crop')
            for row in detection_proposals(result):
                box=row['box'];Detection(tuple(box),row['confidence'])
                # Artificial crop-edge fragments must not become extra people.
                # A true image edge is allowed; it represents an actually clipped
                # source person, rather than truncation caused by this experiment.
                touches=(x0>0 and box[0]*crop_width<=2 or y0>0 and box[1]*crop_height<=2 or
                         x1<width and (1-box[2])*crop_width<=2 or y1<height and (1-box[3])*crop_height<=2)
                if touches:
                    boundary_rejected+=1
                    continue
                mapped=[(x0+box[0]*crop_width)/width,(y0+box[1]*crop_height)/height,
                        (x0+box[2]*crop_width)/width,(y0+box[3]*crop_height)/height]
                candidates.append({'box':mapped,'confidence':row['confidence']})
        if len(candidates)>1024:
            raise ValueError('Zoom candidate limit exceeded')
        kept=[]
        for row in sorted(candidates,key=lambda d:d['confidence'],reverse=True):
            Detection(tuple(row['box']),row['confidence'])
            if all(iou(row['box'],existing['box'])<=.5 for existing in kept):
                kept.append(row)
        self.manifest.update(self.detector.manifest)
        detections=[d for d in kept if d['confidence']>=self.manifest['threshold']]
        return {'width':width,'height':height,'detections':detections,
                'tracking_candidates':[row for row in kept if row['confidence'] < self.manifest['threshold']],
                'count':len(detections),'model':'YOLOX OFFLINE ROI-ZOOM EXPERIMENT',
                'inference_ms':(time.perf_counter()-started)*1000,
                'zoom_passes':1+len(self.regions),'boundary_candidates_rejected':boundary_rejected}
