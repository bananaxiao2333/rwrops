"""Throwaway probe: measure the XML 'universe' in the vanilla package.

Answers, with hard numbers:
  1. how many files are XML configs vs binary resources (same sniff rule as main.py)
  2. the set of XML root elements and their frequencies
  3. for each root element: the full attribute/element universe, recursively
  4. how much of that universe the current core.yaml actually extracts

Usage: uv run python -m util._probe_universe
"""
import json
import os
import re
import sys
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


def excluded(name):
    return any(p.fullmatch(name) for p in EXCLUDE)


def sniff(path: Path):
    """Return 'xml' if the file looks like XML, 'res' otherwise. Same rule as main.py."""
    try:
        head = path.read_bytes()[:5]
    except OSError:
        return None
    return "xml" if head.startswith(b"<") else "res"


def walk():
    for root, dirs, files in os.walk(GAME, topdown=True):
        dirs[:] = [d for d in dirs if not excluded(d)]
        for f in files:
            if not excluded(f):
                yield Path(root) / f


def collect(elem: Tag, attr_counter: Counter, child_tree: dict):
    for k in elem.attrs:
        attr_counter[k] += 1
    for c in elem.children:
        if not isinstance(c, Tag):
            continue
        node = child_tree.setdefault(c.name, {"count": 0, "attrs": Counter(), "children": {}})
        node["count"] += 1
        collect(c, node["attrs"], node["children"])


def config_extracted(ecfg: dict) -> dict:
    """What core.yaml pulls out of one entity block: root attrs + child paths."""
    root_attrs, child_full, child_attrs, child_child = set(), set(), defaultdict(set), {}
    for a in ecfg.get("attributes", []):
        src = a.get("source", "")
        if "/" in src:
            parts = src.split("/")
            child_attrs[parts[0]].add(parts[1].lstrip("@") if len(parts) > 1 else "")
        elif src.startswith("@"):
            root_attrs.add(src[1:])
    for cname, ccfg in ecfg.get("children", {}).items():
        sel = ccfg.get("selector", cname)
        child_full.add(sel)
        for a in ccfg.get("attributes", []):
            src = a.get("source", "")
            if src.startswith("@"):
                child_attrs[sel].add(src[1:])
        child_child[sel] = ccfg.get("children", {})
    return {"root_attrs": root_attrs, "child_full": child_full,
            "child_attrs": dict(child_attrs), "child_child": child_child}


def gap_count(discovered: dict, extracted: dict) -> dict:
    """Return {missing_root_attrs, missing_children, missing_child_attrs} recursively."""
    miss_root, miss_child, miss_attr = 0, 0, 0
    details = {"root": [], "children": [], "attrs": []}
    for tag, info in discovered.items():
        xml_attrs = set(info["attrs"].keys())
        if tag not in extracted["child_full"]:
            miss_child += 1
            details["children"].append(tag)
        else:
            miss = xml_attrs - extracted["child_attrs"].get(tag, set())
            miss_attr += len(miss)
            if miss:
                details["attrs"].append((tag, sorted(miss)))
        sub = info["children"]
        if sub:
            sub_ex = {"root_attrs": set(), "child_full": set(),
                      "child_attrs": {}, "child_child": {}}
            for cname, ccfg in extracted["child_child"].get(tag, {}).items():
                sel = ccfg.get("selector", cname)
                sub_ex["child_full"].add(sel)
                sub_ex["child_attrs"][sel] = {a.get("source", "").lstrip("@")
                                              for a in ccfg.get("attributes", [])
                                              if a.get("source", "").startswith("@")}
                sub_ex["child_child"][sel] = ccfg.get("children", {})
            r = gap_count(sub, sub_ex)
            miss_child += r["missing_children"]
            miss_attr += r["missing_attributes"]
            details["children"].extend(r["details"]["children"])
            details["attrs"].extend(r["details"]["attrs"])
    return {"missing_children": miss_child, "missing_attributes": miss_attr, "details": details}


def main():
    cfg = yaml.safe_load(open(CFG))
    entities = cfg.get("entities", {})

    n_xml = n_res = 0
    roots = Counter()
    universe = {}   # root name -> {attrs: Counter, children: tree}
    parse_fail = 0
    total_bytes = 0

    files = list(walk())
    print(f"walked {len(files)} files", file=sys.stderr)

    for i, p in enumerate(files):
        kind = sniff(p)
        if kind == "res":
            n_res += 1
            continue
        if p.suffix.lower() == ".svg":
            continue
        n_xml += 1
        try:
            raw = p.read_bytes()
            total_bytes += len(raw)
            soup = BeautifulSoup(raw, "xml")
        except Exception:
            parse_fail += 1
            continue
        root = soup.find()
        if root is None:
            parse_fail += 1
            continue
        roots[root.name] += 1
        node = universe.setdefault(root.name, {"attrs": Counter(), "children": {}})
        collect(root, node["attrs"], node["children"])
        if i % 500 == 0:
            print(f"  ...{i}/{len(files)}", file=sys.stderr)

    print("\n" + "=" * 70)
    print("  1. FILE CLASSIFICATION")
    print("=" * 70)
    print(f"  XML config files : {n_xml}")
    print(f"  binary resources : {n_res}")
    print(f"  XML bytes read   : {total_bytes/1e6:.1f} MB")
    print(f"  parse failures   : {parse_fail}")

    print("\n" + "=" * 70)
    print("  2. ROOT ELEMENTS (the actual entity space)")
    print("=" * 70)
    for name, c in roots.most_common():
        configured = "config" if name in entities or any(
            e.get("selector") == name for e in entities.values()) else "  --  "
        print(f"  {c:5d}  <{name}>  [{configured}]")

    # Which configured selectors were never seen?
    seen_selectors = set(universe.keys())
    print("\n  configured selectors with NO file found:")
    for name, e in entities.items():
        sel = e.get("selector")
        if sel not in seen_selectors:
            print(f"    ! {name} -> <{sel}>")

    # Roots nobody configured
    unconfigured = [r for r in roots if r not in seen_selectors]
    print(f"\n  root elements NOT covered by any configured selector: {len(unconfigured)}")
    for r in unconfigured:
        print(f"    - <{r}> ({roots[r]} files)")

    print("\n" + "=" * 70)
    print("  3. ATTRIBUTE / CHILD UNIVERSE vs CONFIG COVERAGE")
    print("=" * 70)
    total_attrs = total_missing_attrs = 0
    total_children = total_missing_children = 0
    for name, e in entities.items():
        sel = e.get("selector")
        if sel not in universe:
            continue
        u = universe[sel]
        ex = config_extracted(e)
        xml_root_attrs = set(u["attrs"].keys())
        miss_root = xml_root_attrs - ex["root_attrs"]
        g = gap_count(u["children"], ex)

        total_attrs += len(xml_root_attrs) + sum(
            len(v["attrs"]) for v in u["children"].values())
        total_missing_attrs += len(miss_root) + g["missing_attributes"]
        total_children += len(u["children"])
        total_missing_children += g["missing_children"]

        print(f"\n  [{name}] <{sel}>  roots seen={roots.get(sel,0)}")
        print(f"    root attrs : {len(xml_root_attrs)} in XML / {len(ex['root_attrs'])} extracted"
              f" -> MISSING {len(miss_root)}: {sorted(miss_root)[:12]}")
        print(f"    children   : {len(u['children'])} in XML, {g['missing_children']} not referenced")
        if g["details"]["children"][:8]:
            print(f"      unreferenced: {g['details']['children'][:8]}")
        if g["details"]["attrs"][:5]:
            print(f"      partial: {g['details']['attrs'][:5]}")

    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  root+child attrs in XML : {total_attrs}")
    print(f"  attrs NOT extracted     : {total_missing_attrs}"
          f"  ({100*total_missing_attrs/max(total_attrs,1):.1f}%)")
    print(f"  child elements in XML   : {total_children}")
    print(f"  children NOT referenced : {total_missing_children}"
          f"  ({100*total_missing_children/max(total_children,1):.1f}%)")


if __name__ == "__main__":
    main()
