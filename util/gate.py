"""Drop counters — the input to gate.sh.

Every place that throws data away must bump() with a reason, so the gate can
print a non-zero count instead of the loss happening silently. See gate.sh.
"""

from collections import Counter

COUNTERS: Counter = Counter()


def bump(reason: str, n: int = 1) -> None:
    COUNTERS[reason] += n


def report(log) -> None:
    if not COUNTERS:
        log.info("[gate] no drops recorded")
        return
    for reason, n in sorted(COUNTERS.items()):
        log.info("[gate] %s: %d", reason, n)
