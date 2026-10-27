from collections import OrderedDict, deque


class Gallery:
    def __init__(self, rules):
        self.rules, self.entries = rules, OrderedDict()

    def samples(self, session_id, token, model):
        return tuple(sample for sample in self.entries.get(session_id, ())
                     if sample.sample.token.scope == token.scope and sample.model == model
                     and 0 < token.monotonic_ns-sample.sample.token.monotonic_ns <= self.rules.ttl_seconds*1e9)

    def prune(self, token, valid_sessions):
        for key in list(self.entries):
            valid = [sample for sample in self.entries[key] if sample.sample.token.scope == token.scope
                     and 0 <= token.monotonic_ns-sample.sample.token.monotonic_ns <= self.rules.ttl_seconds*1e9]
            if key not in valid_sessions or not valid:
                del self.entries[key]
            else:
                self.entries[key] = deque(valid, maxlen=self.rules.max_gallery_samples)

    def add(self, session_id, result):
        samples = self.entries.setdefault(session_id, deque(maxlen=self.rules.max_gallery_samples))
        if samples and (result.model != samples[-1].model or result.sample.token.scope != samples[-1].sample.token.scope):
            raise ValueError('Gallery scope/model cannot be mixed')
        if samples and (result.sample.token.frame_seq <= samples[-1].sample.token.frame_seq
                        or result.sample.token.monotonic_ns-samples[-1].sample.token.monotonic_ns < self.rules.sample_interval_seconds*1e9):
            return False
        samples.append(result)
        self.entries.move_to_end(session_id)
        while len(self.entries) > self.rules.max_gallery_sessions:
            self.entries.popitem(last=False)
        return True

    def clear(self):
        self.entries.clear()

    def reconcile(self, source, target):
        """Move a committed provisional session's samples exactly once."""
        incoming = self.entries.pop(source, ())
        if not incoming:
            return
        existing = self.entries.get(target, ())
        if existing and (existing[-1].model != incoming[-1].model
                         or existing[-1].sample.token.scope != incoming[-1].sample.token.scope):
            return
        combined = sorted([*existing, *incoming], key=lambda s: s.sample.token.monotonic_ns)
        self.entries.pop(target, None)
        for result in combined:
            self.add(target, result)
