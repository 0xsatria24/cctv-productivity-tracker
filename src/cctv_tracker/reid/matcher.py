import statistics
from .types import MatchDecision


class Matcher:
    def __init__(self, rules):
        self.rules = rules

    def decide(self, queries, candidates, token, allowed_pairs, votes=None):
        """Pure proposal step: neither sessions nor gallery nor prior votes are mutated."""
        scores = {}
        for query_id, embedding in queries.items():
            if embedding.sample.token != token:
                raise ValueError('ReID query frame mismatch')
            for target, samples in candidates.items():
                compatible = [s for s in samples if s.model == embedding.model and s.sample.token.scope == token.scope
                              and 0 < token.monotonic_ns-s.sample.token.monotonic_ns <= self.rules.ttl_seconds*1e9
                              and s.sample.token.frame_seq < token.frame_seq]
                if (query_id, target) not in allowed_pairs or len(compatible) < self.rules.min_gallery_samples:
                    continue
                similarities = sorted((sum(a*b for a, b in zip(embedding.vector, s.vector)) for s in compatible), reverse=True)
                # Require agreement from multiple independent samples while
                # allowing a gallery to contain more than one body pose/view.
                scores[query_id, target] = statistics.mean(similarities[:self.rules.min_gallery_samples])
        decisions, updated = [], {}
        for query_id, embedding in queries.items():
            ranked = sorted(((score, target) for (query, target), score in scores.items() if query == query_id), reverse=True)
            target, score, margin, action, reason = None, None, None, 'REJECT', 'NO_ELIGIBLE_GALLERY'
            if ranked:
                score, target = ranked[0]
                peers = sorted(((value, key) for (key, other), value in scores.items() if other == target), reverse=True)
                margin = min(score-ranked[1][0] if len(ranked) > 1 else 2,
                             score-peers[1][0] if len(peers) > 1 else 2)
                if score < self.rules.min_similarity:
                    reason = 'APPEARANCE_MISMATCH'
                elif peers[0][1] != query_id or margin < self.rules.min_margin:
                    reason = 'APPEARANCE_AMBIGUOUS'
                else:
                    prior = (votes or {}).get(query_id)
                    valid = (prior and prior[0] == target and prior[3] < token.frame_seq and prior[4] < token.monotonic_ns
                             and token.monotonic_ns-prior[4] <= self.rules.max_gap_seconds*1e9)
                    count, first = (prior[1]+1, prior[2]) if valid else (1, token.monotonic_ns)
                    updated[query_id] = (target, count, first, token.frame_seq, token.monotonic_ns)
                    ready = count >= self.rules.confirm_observations and token.monotonic_ns-first >= self.rules.confirm_seconds*1e9
                    action, reason = ('WOULD_MATCH', 'APPEARANCE_CONFIRMED') if ready else ('PENDING', 'CONFIRMATION_PENDING')
            decisions.append(MatchDecision(token, embedding.sample.detection_index, query_id, target, action, reason, score, margin))
        return decisions, updated
