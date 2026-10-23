"""Appearance evidence is staged until the owning checkpoint commits."""
from dataclasses import asdict
import math
import time

from .crops import make_crops
from .diagnostics import Diagnostics
from .extractor import validate_batch
from .gallery import Gallery
from .matcher import Matcher


class ReIdRuntime:
    def __init__(self, rules, extractor=None):
        self.rules, self.extractor = rules, extractor
        self.gallery, self.matcher = Gallery(rules), Matcher(rules)
        self.diagnostics = Diagnostics()
        self.votes, self.scope, self.last_sample_ns = {}, None, None
        self.disabled = False

    def prepare(self, jpeg, detections, token, manager, bindings, unavailable=None, *, replay=False):
        report = {'mode': self.rules.mode, 'status': 'OFF', 'decisions': [], 'rejections': []}
        staged = {'token': token, 'report': report, 'results': [], 'votes': {}, 'sampled': False,
                  'merges': [(s.session_id, s.merged_into) for s in manager.dirty.values() if s.merged_into]}
        if self.rules.mode == 'off':
            return staged
        if unavailable:
            report['status'] = 'UNAVAILABLE'
            return staged
        if jpeg is None:
            report['status'] = 'NO_PIXELS'
            return staged
        if self.disabled:
            report['status'] = 'DISABLED_AFTER_ERROR'
            return staged
        if self.scope == token.scope and self.last_sample_ns is not None and token.monotonic_ns-self.last_sample_ns < self.rules.sample_interval_seconds*1e9:
            report['status'] = 'SAMPLE_INTERVAL'
            staged['votes'] = self.votes
            return staged
        started = time.perf_counter()
        try:
            if self.rules.recovery_policy == 'short_occlusion' and not replay:
                raise ValueError('Short occlusion recovery is restricted to non-accounting replay')
            if self.extractor is None:
                from .openvino import OpenVinoExtractor
                self.extractor = OpenVinoExtractor(self.rules.manifest_path, device=self.rules.device)
            samples, report['rejections'] = make_crops(jpeg, detections, token, self.rules)
            results = self.extractor.extract(samples)
            validate_batch(results, samples, self.extractor.identity)
            report['elapsed_ms'] = (time.perf_counter()-started)*1000
            if report['elapsed_ms'] > self.rules.max_extra_latency_ms:
                report['status'] = 'LATENCY_BUDGET'
                staged['disable'] = True
                return staged
            staged['sampled'] = True
            queries, candidates, allowed = {}, {}, set()
            scorer = self._short_occlusion_score if self.rules.recovery_policy == 'short_occlusion' else (
                lambda old, candidate, detection, at: manager.recovery_score(old, candidate, detection, at))
            lost = [s for s in manager.sessions.values() if s.status == 'LOST' and s.recoverable and s.generation == token.generation_id]
            for result in results:
                detection, session = bindings[result.sample.detection_index]
                if session is None:
                    continue
                staged['results'].append((session.session_id, result))
                if token.monotonic_ns-session.first_ns > manager.rules.recovery_confirmation_window_seconds*1e9:
                    continue
                queries[session.session_id] = result
                for old in lost:
                    gap = session.first_ns-old.last_ns
                    if gap > self.rules.max_gap_seconds*1e9:
                        continue
                    if scorer(old, session, detection, token.monotonic_ns) is not None:
                        allowed.add((session.session_id, old.session_id))
                        candidates[old.session_id] = self.gallery.samples(old.session_id, token, result.model)
            # Motion ambiguity is a veto, even if appearance happens to favour one.
            rows = [(index, session) for index, (_, session) in enumerate(bindings) if session
                    and token.monotonic_ns-session.first_ns <= manager.rules.recovery_confirmation_window_seconds*1e9]
            motion_pairs, _ = manager._pairs(rows, lost,
                lambda old, row: scorer(old, row[1], bindings[row[0]][0], token.monotonic_ns), diagnose=False)
            allowed &= {(rows[index][1].session_id, target) for index, target in motion_pairs.items()}
            report['eligible_pairs'] = len(allowed)
            report['candidate_gallery_samples'] = sum(len(samples) for samples in candidates.values())
            decisions, staged['votes'] = self.matcher.decide(queries, candidates, token, allowed,
                                                           self.votes if self.scope == token.scope else {})
            report['decisions'] = [asdict(d) for d in decisions]
            if self.rules.mode == 'active':
                for decision in report['decisions']:
                    decision['policy_revision'] = 'reid-active-'+self.rules.recovery_policy+'-v1'
            report['status'] = 'ACTIVE' if self.rules.mode == 'active' else 'SHADOW'
            report['recovery_policy'] = self.rules.recovery_policy
            report['model'] = asdict(self.extractor.identity)
        except Exception as error:
            report.update(status='PROVIDER_ERROR', error_type=type(error).__name__)
            staged['results'], staged['votes'] = [], {}
            staged['disable'] = True
        return staged

    def _short_occlusion_score(self, old, candidate, detection, at):
        if (not old.recoverable or old.reason not in {'DETECTION_LOST', 'EVIDENCE_GAP'}
                or detection.confidence < self.rules.min_confidence):
            return None
        gap = (candidate.first_ns-old.last_ns)/1e9
        if gap <= 0 or gap > self.rules.max_gap_seconds or (at-old.last_ns)/1e9 > self.rules.max_gap_seconds+1:
            return None
        box, current = old.box, candidate.box
        if box[0] <= .02 or max(box[2:]) >= .98:
            return None
        # A high camera can clip a stationary person's head at the top. That
        # alone is not a visible exit; require observed upward travel there.
        if box[1] <= .02 and len(old.history) >= 3:
            first, last = old.history[0][1], old.history[-1][1]
            if box[3] < .15 and (first[1]+first[3]-last[1]-last[3])/2 > .015:
                return None
        ratios = [(current[2]-current[0])/(box[2]-box[0]), (current[3]-current[1])/(box[3]-box[1])]
        if any(not .5 <= ratio <= 2 for ratio in ratios):
            return None
        origin = ((box[0]+box[2])/2, (box[1]+box[3])/2)
        diagonal = math.hypot(box[2]-box[0], box[3]-box[1])
        tolerance = min(.15, diagonal*.5)
        for observed in (candidate.origin_box, current):
            distance = math.dist(origin, ((observed[0]+observed[2])/2, (observed[1]+observed[3])/2))
            if distance > tolerance:
                return None
        return 1-.4*distance/tolerance-.1*sum(abs(1-r) for r in ratios)

    def apply(self, staged, manager, bindings):
        """Apply accepted proposals before the owning checkpoint; never from a callback."""
        if self.rules.mode != 'active':
            return bindings
        decided = {d['candidate_session_id'] for d in staged['report']['decisions']}
        if staged['report']['status'] != 'SAMPLE_INTERVAL':
            for _, candidate in bindings:
                if candidate is not None and candidate.session_id not in decided:
                    candidate.candidate_id = None
        for decision in staged['report']['decisions']:
            index = decision['detection_index']
            detection, candidate = bindings[index]
            target = manager.sessions.get(decision['target_session_id'])
            if candidate is None or candidate.session_id != decision['candidate_session_id']:
                continue
            if decision['action'] == 'PENDING':
                candidate.candidate_id = decision['target_session_id']
                continue
            if decision['action'] != 'WOULD_MATCH':
                candidate.candidate_id = None
                continue
            if target is None or target.status != 'LOST' or not target.recoverable:
                decision.update(action='REJECT', reason='TARGET_NO_LONGER_ELIGIBLE')
                continue
            recovered = manager._recover(candidate, target, detection, staged['token'].monotonic_ns)
            if recovered is not target:
                continue
            bindings[index] = (detection, target)
            decision.update(action='MATCH', reason='APPEARANCE_RECOVERED')
            manager._event('REID_RECOVERED', target, provisional_session_id=candidate.session_id,
                           appearance_score=decision['score'], appearance_margin=decision['margin'])
            staged['results'] = [(target.session_id if sid == candidate.session_id else sid, result)
                                 for sid, result in staged['results']]
            staged['merges'].append((candidate.session_id, target.session_id))
            staged['votes'].pop(candidate.session_id, None)
        return bindings

    def commit(self, staged, valid_sessions):
        token, report = staged['token'], staged['report']
        if self.scope != token.scope or report['status'] == 'UNAVAILABLE':
            self.gallery.clear()
            self.votes, self.last_sample_ns = {}, None
        self.scope = token.scope
        for source, target in staged['merges']:
            self.gallery.reconcile(source, target)
        self.gallery.prune(token, valid_sessions)
        for session_id, result in staged['results']:
            self.gallery.add(session_id, result)
        self.votes = staged['votes']
        if staged['sampled']:
            self.last_sample_ns = token.monotonic_ns
        self.disabled |= staged.get('disable', False)
        self.diagnostics.record(report)
        return {**report, 'counts': self.diagnostics.snapshot(), 'gallery_sessions': len(self.gallery.entries)}

    def clear(self):
        self.gallery.clear()
        self.votes.clear()


ShadowReId = ReIdRuntime
