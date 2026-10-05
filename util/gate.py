"""Drop counters — the input to gate.sh.

Every place that throws data away must bump() with a reason, so the gate can
print a non-zero count instead of the loss happening silently. See gate.sh.
"""

from collections import Counter

COUNTERS: Counter = Counter()

# Reported even when zero. An explicit "parse_error: 0" is evidence; a missing
# line is just silence, and silence is what this module exists to remove.
ALWAYS_REPORT = ("parse_error", "inherit_ambiguous")


def bump(reason: str, n: int = 1) -> None:
    COUNTERS[reason] += n


def report(log) -> None:
    if not COUNTERS:
        log.info("[gate] no drops recorded")
        return
    for reason in ALWAYS_REPORT:
        log.info("[gate] %s: %d", reason, COUNTERS.get(reason, 0))
    for reason, n in sorted(COUNTERS.items()):
        if reason not in ALWAYS_REPORT:
            log.info("[gate] %s: %d", reason, n)
