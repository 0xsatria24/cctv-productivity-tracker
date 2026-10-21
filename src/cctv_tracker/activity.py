"""Lightweight visible-motion labels and display timers. Never occupancy evidence."""
from dataclasses import dataclass
import math


@dataclass
class TrackState:
    first: float
    last: float
    box: tuple
    display_box: tuple
    label: str | None = None
    moving: float = 0
    still: float = 0
    motion_ema: float | None = None
    last_motion: float | None = None


class TrackActivity:
    def __init__(self, gap_seconds=3, idle_seconds=8, working_seconds=.8, smoothing_ms=80, moving_threshold=.06, idle_threshold=.025, enabled=True):
        self.enabled = enabled
        self.gap = gap_seconds
        self.idle_seconds, self.working_seconds = idle_seconds, working_seconds
        self.smoothing_seconds = smoothing_ms / 1000
        self.moving_threshold, self.idle_threshold = moving_threshold,idle_threshold
        self.tracks, self.gray, self.last, self.generation = {}, None, None, None

    @staticmethod
    def _flow(previous, current, mask):
        import cv2
        import numpy as np
        points = cv2.goodFeaturesToTrack(previous, maxCorners=40, qualityLevel=.02, minDistance=3, mask=mask)
        if points is None or len(points) < 6:
            return None
        next_points, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None, winSize=(15,15), maxLevel=2)
        if next_points is None:
            return None
        back, backward_status, _ = cv2.calcOpticalFlowPyrLK(current, previous, next_points, None, winSize=(15,15), maxLevel=2)
        if back is None:
            return None
        valid = (status.ravel()==1) & (backward_status.ravel()==1) & (np.max(np.abs(back-points), axis=(1,2)) < 1.5)
        return (next_points-points).reshape(-1,2)[valid] if valid.sum() >= 6 else None

    def annotate(self, jpeg, detections, monotonic_ns, generation, retained_ids=None):
        import cv2
        import numpy as np
        at = monotonic_ns / 1e9
        if self.generation != generation or self.last is not None and at-self.last > self.gap:
            self.tracks.clear(); self.gray = None; self.last = None
        if self.last is not None and at <= self.last:
            raise ValueError('Activity timestamps must advance')
        if not self.enabled:
            return self._annotate_states(detections,at,generation,{},retained_ids)
        frame = cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_GRAYSCALE)
        if frame is None:
            # Detector fixtures can omit real image data; real detector rejects bad JPEGs first.
            return self._annotate_states(detections, at, generation, {},retained_ids)
        scale = min(1,320/frame.shape[1],180/frame.shape[0])
        if scale < 1:
            frame = cv2.resize(frame,(max(1,round(frame.shape[1]*scale)),max(1,round(frame.shape[0]*scale))),interpolation=cv2.INTER_AREA)
        if self.gray is not None and self.gray.shape != frame.shape:
            self.tracks.clear(); self.gray = None; self.last = None
        height, width = frame.shape
        motion = {}
        if self.gray is not None:
            dt = at-self.last
            background = np.full(frame.shape,255,np.uint8)
            for state in self.tracks.values():
                x1,y1,x2,y2 = state.box
                background[max(0,int(y1*height)-3):min(height,int(y2*height)+3),max(0,int(x1*width)-3):min(width,int(x2*width)+3)] = 0
            bg_flow = self._flow(self.gray,frame,background)
            camera_shift = np.median(bg_flow,axis=0) if bg_flow is not None else np.zeros(2)
            for row in detections:
                state = self.tracks.get(row.get('track_id'))
                if not state or state.last != self.last:
                    continue  # A missed observation cannot count as idle time.
                x1,y1,x2,y2 = state.box
                if (y2-y1)*height < 12 or (x2-x1)*width < 6:
                    continue
                mask = np.zeros(frame.shape,np.uint8)
                mask[int(y1*height):int((y1+(y2-y1)*.85)*height),int(x1*width):int(x2*width)] = 255
                flow = self._flow(self.gray,frame,mask)
                if flow is None:
                    continue
                speed = float(np.percentile(np.linalg.norm(flow-camera_shift,axis=1),80)) / max(1,(y2-y1)*height) / dt
                motion[row['track_id']] = speed
        self.gray = frame
        return self._annotate_states(detections,at,generation,motion,retained_ids)

    def _annotate_states(self, detections, at, generation, motion, retained_ids=None):
        self.tracks = {key:value for key,value in self.tracks.items() if key in retained_ids} if retained_ids is not None else {key:value for key,value in self.tracks.items() if at-value.last <= self.gap}
        for row in detections:
            identifier = row.get('track_id')
            if not identifier:
                continue
            box = tuple(row['box'])
            state = self.tracks.get(identifier)
            if state is None:
                state = self.tracks[identifier] = TrackState(at,at,box,box)
            dt = max(0,at-state.last)
            speed = motion.get(identifier)
            if speed is not None and dt > 0 and state.last == self.last:
                alpha_motion = 1-math.exp(-dt/.5)
                state.motion_ema = speed if state.motion_ema is None else state.motion_ema+(speed-state.motion_ema)*alpha_motion
                state.last_motion = at
                if state.motion_ema >= self.moving_threshold:
                    state.moving += dt; state.still = 0
                    if state.moving >= self.working_seconds:
                        state.label = 'Working'
                elif state.motion_ema <= self.idle_threshold:
                    state.still += dt; state.moving = 0
                    if state.still >= self.idle_seconds:
                        state.label = 'Idle'
                else:
                    state.moving = max(0,state.moving-dt*.5)
                    state.still = max(0,state.still-dt)
            else:
                if state.last_motion is None or at-state.last_motion > 1 or state.last != self.last:
                    state.moving = 0; state.still = 0
                    state.label = None; state.motion_ema = None
            old_center = ((state.box[0]+state.box[2])/2,(state.box[1]+state.box[3])/2)
            center = ((box[0]+box[2])/2,(box[1]+box[3])/2)
            velocity = math.dist(center,old_center)/max(.001,dt)/max(.02,box[3]-box[1]) if dt else 0
            alpha = 1 if velocity > .5 or dt <= 0 or not self.smoothing_seconds else 1-math.exp(-dt/self.smoothing_seconds)
            size_change=max(abs((box[2]-box[0])-(state.box[2]-state.box[0])),abs((box[3]-box[1])-(state.box[3]-state.box[1])))
            if self.smoothing_seconds and 0<dt<=1 and velocity<.05 and size_change<.02*max(.02,box[3]-box[1]):
                alpha=min(alpha,.5)  # Suppress tiny static jitter even at a low processed FPS.
            state.display_box = tuple(a+(b-a)*alpha for a,b in zip(state.display_box,box))
            state.box, state.last = box, at
            row['display_box'] = state.display_box
            row['activity'] = {'label':state.label,'basis':'visible_motion',
                               'tracked_elapsed_us':round((at-state.first)*1e6),
                               'motion_per_second':round(speed,4) if speed is not None else None}
        self.last, self.generation = at,generation
        return detections
