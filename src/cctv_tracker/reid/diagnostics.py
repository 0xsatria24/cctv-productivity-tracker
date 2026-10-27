from collections import Counter


class Diagnostics:
    def __init__(self):
        self.counts = Counter()

    def record(self, report):
        self.counts[report['status']] += 1
        for row in report.get('rejections', ()):
            self.counts[row['reason']] += 1
        for row in report.get('decisions', ()):
            self.counts[row['reason']] += 1

    def snapshot(self):
        return dict(self.counts)
