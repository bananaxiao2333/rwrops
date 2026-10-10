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


def reset() -> None:
    """Clear the counters.

    Multi-package runs report per package: one accumulated `[gate]` block for 22
    packages is unreadable, and AGENTS.md §3.4 requires every non-zero counter to
    be explainable.
    """
    COUNTERS.clear()


def report(log, prefix: str = "") -> None:
    tag = f"[gate]{prefix} " if prefix else "[gate] "
    if not COUNTERS:
        log.info("%sno drops recorded", tag)
        return
    for reason in ALWAYS_REPORT:
        log.info("%s%s: %d", tag, reason, COUNTERS.get(reason, 0))
    for reason, n in sorted(COUNTERS.items()):
        if reason not in ALWAYS_REPORT:
            log.info("%s%s: %d", tag, reason, n)
