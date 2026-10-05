"""Throwaway probe #2: (a) corrected coverage taxonomy, (b) measured cost of the
current hot paths, so the report's efficiency claims are numbers not vibes.

Usage: uv run python -m util._probe_cost
"""
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from bs4 import BeautifulSoup, Tag

GAME = Path(
    "/Users/bananaxiao/Library/Application Support/Steam/steamapps/common/"
    "RunningWithRifles/RunningWithRifles.app/Contents/Resources/media/packages/vanilla"
)
CFG = Path(__file__).resolve().parent.parent / "config" / "core.yaml"
EXCLUDE = [re.compile(p) for p in
           ["models", "particles", "scripts.*", "sounds", "static_objects",
            "materials", "fonts", "names"]]


def excluded(n):
    return any(p.fullmatch(n) for p in EXCLUDE)


def walk_files():
    out = []
    for root, dirs, files in os.walk(GAME, topdown=True):
        dirs[:] = [d for d in dirs if not excluded(d)]
        for f in files:
            if not excluded(f):
                out.append(Path(root) / f)
    return out


def xml_files(files):
    out = []
    for p in files:
        try:
            if p.read_bytes()[:5].startswith(b"<") and p.suffix.lower() != ".svg":
                out.append(p)
        except OSError:
            pass
    return out


# ── corrected taxonomy ───────────────────────────────────────────────────

def collect(elem, attrs: Counter, children: dict):
    for k in elem.attrs:
        attrs[k] += 1
    for c in elem.children:
        if not isinstance(c, Tag):
            continue
        n = children.setdefault(c.name, {"count": 0, "attrs": Counter(), "children": {}})
        n["count"] += 1
        collect(c, n["attrs"], n["children"])


def declared(ecfg: dict):
    """root attrs, and per-child-tag: ('full'|'flat', set(attrs))"""
    root, kids = set(), {}
    for a in ecfg.get("attributes", []):
        s = a.get("source", "")
        if "/" in s:
            parts = s.split("/")
            tag = parts[0]
            rec = kids.setdefault(tag, ["flat", set()])
            if len(parts) > 1 and parts[1].startswith("@"):
                rec[1].add(parts[1][1:])
        elif s.startswith("@"):
            root.add(s[1:])
    for cname, ccfg in ecfg.get("children", {}).items():
        sel = ccfg.get("selector", cname)
        rec = kids.setdefault(sel, ["full", set()])
        rec[0] = "full"
        for a in ccfg.get("attributes", []):
            s = a.get("source", "")
            if s.startswith("@"):
                rec[1].add(s[1:])
        # grandchildren flattened under this child
        for sc in (ccfg.get("children") or {}).values():
            pass
    return root, kids


def classify(discovered, root_attrs_xml, root_declared, kids_declared):
    """Return counts for root attrs + child taxonomy."""
    miss_root = root_attrs_xml - root_declared
    buckets = Counter()
    detail = defaultdict(list)
    for tag, info in discovered.items():
        xml_attrs = set(info["attrs"].keys())
        if tag in kids_declared:
            mode, dattrs = kids_declared[tag]
            miss = xml_attrs - dattrs
            if mode == "full" and miss:
                buckets["PARTIAL"] += 1
                detail["PARTIAL"].append((tag, sorted(miss)))
            elif mode == "full":
                buckets["FULL"] += 1
            elif miss:
                buckets["FLATTENED"] += 1
                detail["FLATTENED"].append((tag, sorted(miss)))
            else:
                buckets["FLATTENED_OK"] += 1
        else:
            buckets["MISSING"] += 1
            detail["MISSING"].append((tag, sorted(xml_attrs)))
    return miss_root, buckets, detail


def main():
    cfg = yaml.safe_load(open(CFG))
    entities = cfg.get("entities", {})

    t0 = time.monotonic()
    files = walk_files()
    t_walk = time.monotonic() - t0

    t0 = time.monotonic()
    xf = xml_files(files)
    t_sniff = time.monotonic() - t0
    print(f"files={len(files)}  xml={len(xf)}")
    print(f"walk_dir()          : {t_walk:.2f}s")
    print(f"sniff ({len(files)} files)  : {t_sniff:.2f}s")
    print(f"  -> main.py pays this TWICE (walk_dir double-walk + sniff per file)")

    # ── benchmark 1: full BeautifulSoup tree build (current) ──
    raws = [(p, p.read_bytes()) for p in xf]
    t0 = time.monotonic()
    soups = [BeautifulSoup(r, "xml") for _, r in raws]
    t_bs = time.monotonic() - t0

    # ── benchmark 2: lxml.iterparse streaming (proposed) ──
    from lxml import etree
    import io
    t0 = time.monotonic()
    n_elem = 0
    for _, r in raws:
        try:
            for _, _ in etree.iterparse(io.BytesIO(r), events=("start",)):
                n_elem += 1
        except Exception:
            pass
    t_iter = time.monotonic() - t0

    print(f"\nparse all XML:")
    print(f"  BeautifulSoup tree  : {t_bs:.2f}s   ({sum(len(r) for _,r in raws)/1e6:.1f} MB)")
    print(f"  lxml.iterparse      : {t_iter:.2f}s   ({n_elem} elements)")
    print(f"  speedup             : {t_bs/max(t_iter,1e-9):.1f}x")

    # ── benchmark 3: rglob inheritance lookup (current) vs index ──
    inherit_targets = set()
    for s in soups:
        for v in s.find_all("vehicle"):
            f = v.get("file")
            if f:
                inherit_targets.add(f)
    inherit_targets = sorted(inherit_targets)[:40]
    print(f"\ninheritance: {len(inherit_targets)} distinct base filenames sampled")

    t0 = time.monotonic()
    hits = 0
    for fn in inherit_targets:
        for f in GAME.rglob(fn):
            if f.is_file():
                hits += 1
                break
    t_rglob = time.monotonic() - t0

    t0 = time.monotonic()
    index = {}
    for root, dirs, fs in os.walk(GAME):
        for f in fs:
            index.setdefault(f, os.path.join(root, f))
    t_index_build = time.monotonic() - t0
    t0 = time.monotonic()
    hits2 = sum(1 for fn in inherit_targets if fn in index)
    t_index_q = time.monotonic() - t0

    print(f"  rglob per lookup    : {t_rglob:.2f}s for {len(inherit_targets)} lookups"
          f"  ({1000*t_rglob/len(inherit_targets):.0f} ms each, {hits} found)")
    print(f"  index build (once)  : {t_index_build:.2f}s")
    print(f"  index query         : {t_index_q*1000:.1f} ms for {len(inherit_targets)} lookups"
          f"  ({hits2} found)")
    if inherit_targets:
        n_all = len(set(f for s in soups for v in s.find_all(True) if v.get("file")))
        print(f"  -> extrapolated to all {n_all} inherit_from lookups in the vanilla package:")
        print(f"       rglob  ≈ {t_rglob/len(inherit_targets)*n_all:.0f}s")
        print(f"       index  ≈ {t_index_q/max(len(inherit_targets),1)*n_all*1000:.0f} ms")

    # ── coverage taxonomy ──
    universe = {}
    for s in soups:
        r = s.find()
        if r is None:
            continue
        node = universe.setdefault(r.name, {"attrs": Counter(), "children": {}})
        collect(r, node["attrs"], node["children"])

    print("\n" + "=" * 74)
    print("  COVERAGE TAXONOMY (auto-discovered, no hardcoded globs)")
    print("=" * 74)
    tot = Counter()
    for name, e in entities.items():
        sel = e.get("selector")
        # container form is also valid
        if sel not in universe:
            continue
        u = universe[sel]
        rd, kd = declared(e)
        miss_root, buckets, detail = classify(
            u["children"], set(u["attrs"].keys()), rd, kd)
        tot.update(buckets)
        print(f"\n  [{name}] <{sel}>")
        print(f"    root attrs {len(u['attrs'])-len(miss_root)}/{len(u['attrs'])}"
              f"  MISSING {len(miss_root)}: {sorted(miss_root)[:10]}")
        print(f"    children   FULL={buckets['FULL']} PARTIAL={buckets['PARTIAL']}"
              f" FLATTENED={buckets['FLATTENED']} FLATTENED_OK={buckets['FLATTENED_OK']}"
              f" NOT_REFERENCED={buckets['MISSING']}")
        for k in ("MISSING", "PARTIAL", "FLATTENED"):
            if detail[k]:
                print(f"      {k}: {detail[k][:6]}")

    print("\n" + "=" * 74)
    print(f"  child elements across all configured entities:")
    print(f"    fully captured as child objects : {tot['FULL']}")
    print(f"    captured but missing attrs      : {tot['PARTIAL']}")
    print(f"    only flattened, attrs missing   : {tot['FLATTENED']}")
    print(f"    flattened, complete             : {tot['FLATTENED_OK']}")
    print(f"    NOT REFERENCED AT ALL           : {tot['MISSING']}")




if __name__ == "__main__":
    main()
