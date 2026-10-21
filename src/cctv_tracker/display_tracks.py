"""Short-lived presentation predictions. Never passed into accounting or counts."""
from collections import OrderedDict
import math


class DisplayTracks:
    def __init__(self, seconds=1):
        self.seconds=seconds
        self.tracks=OrderedDict()
        self.generation=None

    def update(self, measured, at_ns, generation, retained_ids):
        if not self.seconds:
            self.tracks.clear()
            return []
        if generation!=self.generation:
            self.tracks.clear()
        self.generation=generation
        self.tracks=OrderedDict((key,row) for key,row in self.tracks.items()
                                if key in retained_ids and 0<=at_ns-row['at']<=self.seconds*1e9)
        seen=set()
        for row in measured:
            key=row.get('track_id')
            if not key:continue
            seen.add(key)
            box=tuple(row.get('display_box',row['box']))
            old=self.tracks.get(key);velocity=(0,0)
            if old and at_ns>old['at']:
                dt=(at_ns-old['at'])/1e9
                cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
                previous=old['box']
                vx=(cx-(previous[0]+previous[2])/2)/dt
                vy=(cy-(previous[1]+previous[3])/2)/dt
                limit=max(.02,box[3]-box[1])*.5
                speed=math.hypot(vx,vy)
                scale=min(1,limit/max(1e-12,speed))
                velocity=(vx*scale,vy*scale)
            self.tracks[key]={'at':at_ns,'box':box,'velocity':velocity,
                              'elapsed':row.get('activity',{}).get('tracked_elapsed_us',0)}
            self.tracks.move_to_end(key)
        while len(self.tracks)>128:self.tracks.popitem(last=False)
        predictions=[]
        for key,state in self.tracks.items():
            age=(at_ns-state['at'])/1e9
            if key in seen or not 0<age<self.seconds:continue
            box=state['box'];vx,vy=state['velocity']
            # Limit drift even for a fast worker; the box may move at most 20% of its height.
            horizon=min(age,.4)
            dx=max(-box[0],min(1-box[2],vx*horizon))
            dy=max(-box[1],min(1-box[3],vy*horizon))
            predicted=[box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy]
            predictions.append({'track_id':key,'box':predicted,'display_box':predicted,'evidence':'PREDICTED',
                                'valid_for_ms':round((self.seconds-age)*1000),
                                'activity':{'label':None,'basis':'presentation_prediction',
                                            'tracked_elapsed_us':state['elapsed']+round(age*1e6)}})
        return predictions
