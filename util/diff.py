"""Compare two result.json files and answer one question: did we lose data?

    uv run python -m util.diff OLD.json NEW.json [--limit N]

Handles both shapes:
  - aggregated:  {"vehicle": {"jeep": {...}, ...}, ...}
  - flat/equal:  [{"type": "vehicle", "key": "jeep", ...}, ...]

Reported two ways, because the positional view is useless on its own: reordering
a list turns 600 identical values into 600 "changes" and buries the handful that
actually matter.

  1. record/entity counts per type
  2. values — order-independent, collapsed to path patterns, split three ways:
       CHANGED      same field, different value
       DISAPPEARED  field present before, gone now   <- data loss
       APPEARED     field that was not there before

Exit code is 1 if anything DISAPPEARED or any record/entity was removed, so this
can be used as a gate on its own.
"""

import json
import re
import sys
from collections import Counter, defaultdict

IDX = re.compile(r"\[\d+\]")


def flat(obj, prefix="", out=None):
    """Flatten to {path: scalar}. Lists keep their indices so positions are visible."""
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flat(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flat(v, f"{prefix}[{i}]", out)
    else:
        out[prefix] = obj
    return out


def load(path):
    """-> {type: {"keys": {key: fields} | None, "records": [fields] | None}}

    Accepts the versioned envelope {schema, counts, records}, the bare flat
    list, and the legacy {type: {key: entity}} dict.
    """
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)

    schema = obj.get("schema") if isinstance(obj, dict) else None
    if isinstance(obj, dict) and "records" in obj:
        obj = obj["records"]

    types = {}
    if isinstance(obj, dict):
        for t, items in obj.items():
            if isinstance(items, dict):
                types[t] = {"keys": {k: flat(v) for k, v in items.items()}, "records": None}
    elif isinstance(obj, list):
        for rec in obj:
            t = rec.get("type", "?") if isinstance(rec, dict) else "?"
            types.setdefault(t, {"keys": None, "records": []})["records"].append(
                flat(rec) if isinstance(rec, dict) else {"_scalar": rec})
    else:
        raise SystemExit(f"{path}: expected dict or list at top level")

    for entry in types.values():
        entry["schema"] = schema
    return types


def bag(fields):
    """Order-independent multiset of (pattern, value) — indices collapsed."""
    return Counter((IDX.sub("[]", p), repr(v)) for p, v in fields.items())


def type_bag(entry):
    """All values of one type, regardless of how records are grouped."""
    if entry["keys"] is not None:
        c = Counter()
        for fields in entry["keys"].values():
            c += bag(fields)
        return c
    c = Counter()
    for fields in entry["records"]:
        c += bag(fields)
    return c


def count_of(entry):
    if entry["keys"] is not None:
        return len(entry["keys"])
    return len(entry["records"])


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    limit = 6
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if len(argv) != 2:
        print(__doc__)
        return 2

    old, new = load(argv[0]), load(argv[1])

    removed_keys, added_keys = [], []
    lost_pat, gained_pat = defaultdict(int), defaultdict(int)
    lost_ex, gained_ex = defaultdict(list), defaultdict(list)

    for t in sorted(set(old) | set(new)):
        ea = old.get(t, {"keys": None, "records": []})
        eb = new.get(t, {"keys": None, "records": []})

        if ea["keys"] is not None and eb["keys"] is not None:
            for k in sorted(set(ea["keys"]) - set(eb["keys"])):
                removed_keys.append((t, k))
            for k in sorted(set(eb["keys"]) - set(ea["keys"])):
                added_keys.append((t, k))
            pairs = [(k, ea["keys"][k], eb["keys"][k])
                     for k in sorted(set(ea["keys"]) & set(eb["keys"]))]
        else:
            pairs = [(t, {}, {})]

        for k, fa, fb in pairs:
            A = bag(fa) if fa else type_bag(ea)
            B = bag(fb) if fb else type_bag(eb)
            for (p, v), n in (A - B).items():
                lost_pat[(t, p)] += n
                if len(lost_ex[(t, p)]) < limit:
                    lost_ex[(t, p)].append((k, v))
            for (p, v), n in (B - A).items():
                gained_pat[(t, p)] += n
                if len(gained_ex[(t, p)]) < limit:
                    gained_ex[(t, p)].append((k, v))

    changed, disappeared, appeared = [], [], []
    for key in set(lost_pat) | set(gained_pat):
        if key in lost_pat and key in gained_pat:
            changed.append(key)
        elif key in lost_pat:
            disappeared.append(key)
        else:
            appeared.append(key)

    print(f"RESULT DIFF\n  old: {argv[0]}\n  new: {argv[1]}\n")
    print("RECORDS")
    for t in sorted(set(old) | set(new)):
        a = count_of(old[t]) if t in old else 0
        b = count_of(new[t]) if t in new else 0
        print(f"  {t:<18} {a:>5} -> {b:<5}{'' if a == b else '   <-'}")
    if added_keys:
        print(f"  + added:   {', '.join(f'{t}.{k}' for t, k in added_keys[:20])}")
    if removed_keys:
        print(f"  - REMOVED: {', '.join(f'{t}.{k}' for t, k in removed_keys[:20])}")

    if disappeared:
        print(f"\nDISAPPEARED (field gone — this is data loss)  {len(disappeared)} patterns, "
              f"{sum(lost_pat[k] for k in disappeared)} occurrences")
        for key in sorted(disappeared, key=lambda k: -lost_pat[k]):
            t, p = key
            print(f"  - {t}.{p}  x{lost_pat[key]}")
            for k, v in lost_ex[key][:limit]:
                print(f"      [{k}] {v}")

    if appeared:
        print(f"\nAPPEARED (new field)  {len(appeared)} patterns, "
              f"{sum(gained_pat[k] for k in appeared)} occurrences")
        for key in sorted(appeared, key=lambda k: -gained_pat[k])[:20]:
            t, p = key
            print(f"  + {t}.{p}  x{gained_pat[key]}")

    if changed:
        print(f"\nCHANGED (same field, different value)  {len(changed)} patterns, "
              f"{sum(lost_pat[k] for k in changed)} occurrences")
        for key in sorted(changed, key=lambda k: -lost_pat[k])[:20]:
            t, p = key
            print(f"  ~ {t}.{p}  x{lost_pat[key]}")
            for (ka, va), (kb, vb) in zip(lost_ex[key][:limit], gained_ex[key][:limit]):
                print(f"      [{ka}] {va}  ->  [{kb}] {vb}")

    print("\nVERDICT")
    if removed_keys:
        print(f"  DATA LOST: {len(removed_keys)} entities removed")
    elif disappeared:
        print(f"  DATA LOST: {len(disappeared)} field patterns disappeared")
    elif changed:
        print(f"  no loss: {len(changed)} field patterns changed value")
    elif appeared:
        print(f"  no loss: {len(appeared)} field patterns appeared")
    else:
        print("  identical")
    return 1 if (removed_keys or disappeared) else 0


if __name__ == "__main__":
    sys.exit(main())
