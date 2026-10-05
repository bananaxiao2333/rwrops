"""XML config coverage checker.

Scans game XML files for each entity type defined in core.yaml,
discovers ALL available attributes/child elements,
and reports what the config is NOT extracting.

Usage:
  uv run python -m util.coverage_check
  uv run python -m util.coverage_check --verbose
"""

import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("ERROR: requires beautifulsoup4. Run: uv add bs4 lxml")
    sys.exit(1)

GAME_DIR = Path(
    "/Users/bananaxiao/Library/Application Support/Steam/steamapps/common/"
    "RunningWithRifles/RunningWithRifles.app/Contents/Resources/media/packages/vanilla"
)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "core.yaml"
EXCLUDE_DIRS = {"models", "particles", "sounds", "scripts", "materials", "fonts", "names"}

# For each entity type: (selector, glob_patterns)
ENTITY_SCAN_PATTERNS: Dict[str, tuple] = {
    "carry_item":   ("carry_item",   ["items/*.carry_item", "items/*.xml"]),
    "weapon":       ("weapon",       ["*.weapon", "weapons/*.xml"]),
    "vehicle":      ("vehicle",      ["*.vehicle", "vehicles/*.xml"]),
    "projectile":   ("projectile",   ["*.projectile", "projectiles/*.xml"]),
    "call":         ("call",         ["*.call", "calls/*.xml", "calls/**/*.xml"]),
    "achievement":  ("achievement",  ["achievements.xml", "extra_achievements.xml"]),
    "faction":      ("faction",      ["factions/*.xml"]),
    "language":     ("language",     ["languages/*.xml"]),
    "map_config":   ("map_config",   ["maps/*.xml"]),
    "translation":  ("translation",  ["*.xml"]),
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ── XML scanning ─────────────────────────────────────────────────────────

def scan_xml(etype: str, selector: str) -> dict:
    """Scan game XML files and discover all attributes and child structures."""
    root_attrs: Dict[str, int] = defaultdict(int)
    children: Dict[str, Any] = {}
    files_scanned = 0

    patterns = ENTITY_SCAN_PATTERNS.get(etype, ("", ["*.xml"]))[1]
    files: List[Path] = []
    for pat in patterns:
        files.extend(GAME_DIR.glob(pat))
    files = list(set(
        f for f in files
        if not any(d in f.relative_to(GAME_DIR).parts for d in EXCLUDE_DIRS)
    ))

    for fpath in files:
        try:
            raw = fpath.read_bytes()
            if len(raw) > 1_000_000:
                continue
            soup = BeautifulSoup(raw, "xml")
        except Exception:
            continue
        for elem in soup.find_all(selector):
            files_scanned += 1
            _collect_attrs(elem, root_attrs)
            _collect_children(elem, children)

    return {
        "root_attrs": dict(root_attrs),
        "children": dict(children),
        "files_scanned": files_scanned,
    }


def _collect_attrs(elem: Tag, counter: Dict[str, int]):
    for k in elem.attrs:
        counter[k] += 1


def _collect_children(elem: Tag, tree: Dict[str, Any]):
    for child in elem.children:
        if not isinstance(child, Tag):
            continue
        tag = child.name
        if tag not in tree:
            tree[tag] = {"count": 0, "attrs": defaultdict(int), "children": {}}
        tree[tag]["count"] += 1
        _collect_attrs(child, tree[tag]["attrs"])
        _collect_children(child, tree[tag]["children"])


# ── Config analysis ──────────────────────────────────────────────────────

def analyze_config_extraction(ecfg: dict) -> dict:
    """Analyze what the config extracts from an entity config block.

    Returns:
      {
        "root_attrs": set of XML attribute names extracted from root,
        "child_refs": set of child tag names that are accessed (flattened or as children),
        "child_attrs": {"child_tag": set of attribute names extracted},
        "child_full": {"child_tag": bool (full child extraction or just flattened attrs)},
      }
    """
    root_attrs: Set[str] = set()
    child_refs: Set[str] = set()
    child_attrs: Dict[str, Set[str]] = defaultdict(set)
    child_full: Dict[str, bool] = {}

    # root-level attributes: source="@key" -> extracts attribute "key"
    for attr in ecfg.get("attributes", []):
        src = attr.get("source", "")
        if src.startswith("@") and "/" not in src:
            root_attrs.add(src[1:])
        elif "/" in src:
            # nested path like "inventory/@price" -> child "inventory", attr "price"
            parts = src.split("/")
            child_tag = parts[0]
            child_refs.add(child_tag)
            if child_tag not in child_full:
                child_full[child_tag] = False
            if parts[1].startswith("@"):
                child_attrs[child_tag].add(parts[1][1:])

    # children section
    for cname, ccfg in ecfg.get("children", {}).items():
        sel = ccfg.get("selector", cname)
        child_refs.add(sel)
        child_full[sel] = True  # full child extraction
        for attr in ccfg.get("attributes", []):
            src = attr.get("source", "")
            if src.startswith("@"):
                child_attrs[sel].add(src[1:])
            elif "/" in src:
                parts = src.split("/")
                if parts[0] == sel and parts[1].startswith("@"):
                    child_attrs[sel].add(parts[1][1:])

    return {
        "root_attrs": root_attrs,
        "child_refs": child_refs,
        "child_attrs": dict(child_attrs),
        "child_full": child_full,
        "_raw_children": ecfg.get("children", {}),
    }


# ── Reporting ────────────────────────────────────────────────────────────

def build_report() -> dict:
    config = load_config()
    report = {}

    for etype, ecfg in config.get("entities", {}).items():
        selector = ecfg.get("selector", "")
        if not selector:
            continue

        scan_result = scan_xml(etype, selector)
        extracted = analyze_config_extraction(ecfg)

        # ── Root attribute gaps ──
        xml_root_attrs = set(scan_result.get("root_attrs", {}).keys())
        missing_root = xml_root_attrs - extracted["root_attrs"]

        # ── Child gaps ──
        discovered_children = scan_result.get("children", {})
        child_gaps = _find_child_gaps(
            discovered_children, extracted, selector
        )

        report[etype] = {
            "selector": selector,
            "files_scanned": scan_result["files_scanned"],
            "root_attrs": {
                "xml_count": len(xml_root_attrs),
                "extracted_count": len(extracted["root_attrs"]),
                "missing": sorted(missing_root),
            },
            "children": child_gaps,
            "_xml_children": {
                tag: {"count": v["count"], "attrs": dict(v["attrs"])}
                for tag, v in sorted(discovered_children.items())
            },
        }

    return report


def _find_child_gaps(discovered: dict, extracted: dict, parent_selector: str) -> dict:
    gaps = {}
    for tag, info in discovered.items():
        # Is this child referenced in config at all?
        is_fully_extracted = tag in extracted.get("child_full", {}) and extracted["child_full"][tag]
        has_flattened_attrs = tag in extracted.get("child_refs", {})

        xml_attrs = set(info.get("attrs", {}).keys())
        extracted_attrs = set(extracted.get("child_attrs", {}).get(tag, set()))
        missing_attrs = xml_attrs - extracted_attrs

        if not is_fully_extracted and not has_flattened_attrs:
            # child not referenced at all
            gaps[tag] = {
                "count": info["count"],
                "status": "FULLY MISSING",
                "missing_attrs": list(xml_attrs),
            }
        elif not is_fully_extracted and missing_attrs:
            # flattened-only, some attrs missing
            gaps[tag] = {
                "count": info["count"],
                "status": "FLATTENED (missing attrs)",
                "missing_attrs": sorted(missing_attrs),
            }
        elif is_fully_extracted and missing_attrs:
            gaps[tag] = {
                "count": info["count"],
                "status": "PARTIAL (missing attrs)",
                "missing_attrs": sorted(missing_attrs),
            }

        # Recurse into grandchildren
        sub_gaps = _find_child_gaps(
            info.get("children", {}),
            _make_sub_extracted(extracted, tag),
            tag,
        )
        if sub_gaps:
            if tag in gaps:
                gaps[tag]["sub_children"] = sub_gaps
            else:
                gaps[tag] = {
                    "count": info["count"],
                    "status": "COVERED (sub-gaps)",
                    "missing_attrs": [],
                    "sub_children": sub_gaps,
                }

    return gaps


def _make_sub_extracted(extracted: dict, parent_tag: str) -> dict:
    """Build an extracted set for children of a given child tag, finding
    the relevant sub-config from the parent's children section."""
    # Probe extracted config for any child definitions that match this parent_tag
    sub_child_refs: Set[str] = set()
    sub_child_attrs: Dict[str, Set[str]] = defaultdict(set)
    sub_child_full: Dict[str, bool] = {}
    sub_child_children: Dict[str, Any] = {}

    # Look through the parent-level children for a match
    for cname, ccfg in extracted.get("_raw_children", {}).items():
        sel = ccfg.get("selector", cname)
        if sel == parent_tag:
            for attr in ccfg.get("attributes", []):
                src = attr.get("source", "")
                if src.startswith("@"):
                    sub_child_attrs[parent_tag].add(src[1:])
        for sc_name, sc_cfg in ccfg.get("children", {}).items():
            if not isinstance(sc_cfg, dict):
                continue
            sc_sel = sc_cfg.get("selector", sc_name)
            sub_child_refs.add(sc_sel)
            sub_child_full[sc_sel] = True
            for attr in (sc_cfg.get("attributes") or []):
                if not isinstance(attr, dict):
                    continue
                src = attr.get("source", "")
                if src.startswith("@"):
                    sub_child_attrs[sc_sel].add(src[1:])
            # recurse one more level for grandchildren
            sub_child_children[sc_sel] = sc_cfg.get("children", {})
            break

    return {
        "root_attrs": set(),
        "child_refs": sub_child_refs,
        "child_attrs": dict(sub_child_attrs),
        "child_full": sub_child_full,
        "_raw_children": sub_child_children,
    }


def _print_report(report: dict, verbose: bool = False):
    for etype, info in sorted(report.items()):
        print(f"\n{'='*60}")
        print(f"  {etype}  ({info['files_scanned']} files, selector: {info['selector']})")
        print(f"{'='*60}")

        ra = info["root_attrs"]
        print(f"\n  Root attrs: {ra['xml_count']} in XML, {ra['extracted_count']} extracted")
        if ra["missing"]:
            print(f"    ⚠️  MISSING: {', '.join(ra['missing'])}")
        else:
            print(f"    ✅ All covered")

        cg = info["children"]
        if cg:
            print(f"\n  Child gaps:")
            _print_child_gaps(cg, indent=4)
        else:
            print(f"\n  ✅ All children covered")

        if verbose:
            xc = info.get("_xml_children", {})
            if xc:
                print(f"\n  [All discovered children]")
                for tag, ci in sorted(xc.items()):
                    print(f"    <{tag}> ({ci['count']}x) attrs: {list(ci['attrs'].keys())}")


def _print_child_gaps(gaps: dict, indent: int):
    pad = " " * indent
    for tag, info in sorted(gaps.items()):
        status = info["status"]
        count = info["count"]
        ma = info.get("missing_attrs", [])
        extra = f" — attrs: {', '.join(ma)}" if ma else ""
        print(f"{pad}⚠️  <{tag}> ({count}x) — {status}{extra}")
        if info.get("sub_children"):
            _print_child_gaps(info["sub_children"], indent + 4)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    verbose = "--verbose" in sys.argv

    if not GAME_DIR.exists():
        print(f"ERROR: Game directory not found at {GAME_DIR}")
        sys.exit(1)

    print(f"Game: {GAME_DIR}")
    print(f"Config: {CONFIG_PATH}")
    print()

    report = build_report()
    _print_report(report, verbose=verbose)

    # Summary
    total_missing_root = sum(
        len(v["root_attrs"]["missing"]) for v in report.values()
    )
    total_child_gaps = sum(
        _count_child_gaps(v.get("children", {})) for v in report.values()
    )
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {total_missing_root} missing root attrs, "
          f"{total_child_gaps} child gaps across {len(report)} entity types")
    print(f"{'='*60}")


def _count_child_gaps(gaps: dict) -> int:
    count = 0
    for info in gaps.values():
        count += 1
        if info.get("sub_children"):
            count += _count_child_gaps(info["sub_children"])
    return count


if __name__ == "__main__":
    main()
