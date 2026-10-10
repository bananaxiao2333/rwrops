"""Package layering — RWR's VFS overlay, as the extractor needs to see it.

`media/packages/` holds ~22 top-level package directories, but only some of them
are self-contained. The rest are *overlays*: `classic` ships 103 files of its
own and relies on the base game for everything else. Parsing an overlay in
isolation produces a dataset of 100-odd records and calls it "the classic
package", which is useless and misleading.

RWR itself never loads a package in isolation — it mounts a stack and lets the
topmost definition of a path win. This module reproduces that stack:

    layers(P) = [ base packages, in sorted order ]
              + [ P/packages/<dep> overrides, in sorted order ]
              + [ P's own tree, minus P/packages ]

Two shapes of `packages/` sub-directory exist and they mean different things:

  * `classic/packages/vanilla/` — `vanilla` also exists as a top-level package,
    so this is a *patch* on that package. Its files are keyed relative to
    `classic/packages/vanilla/`, which makes them line up with the base's keys
    and therefore override it.
  * `ww2_base/packages/ww2_undead/` — no top-level `ww2_undead` exists, so this
    is a *bundled package* that `ww2_base` brings along. It contributes its files
    like any other layer.

A package with no `packages/` sub-directory is layered on the default base
(`vanilla`) unless it *is* that base. That is the right answer for `pvp`,
`teddy_hunt`, `camera_mod` and friends, and a harmless one for the WW2
components, which are only ever used through `ww2_base` anyway.

Everything here is `sorted()`: the output must be a property of the tree, not of
the filesystem (AGENTS.md §2, gate check 2).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import gate

logger = logging.getLogger(__name__)

#: Base package every overlay without a declared dependency is stacked on.
DEFAULT_BASE = "vanilla"

#: Sub-directory that holds a package's bundled / overriding sub-packages.
NESTED_DIRNAME = "packages"


@dataclass
class Package:
    """One selectable package: its identity, its layer stack, its file set."""

    id: str
    root: Path
    #: Layer roots, base-first. Order is the overlay order: later wins.
    layers: List[Path] = field(default_factory=list)
    #: Package-relative key -> absolute path, after overlay resolution.
    files: Dict[str, Path] = field(default_factory=dict)
    #: How many files the layers below contributed, for reporting.
    shadowed: int = 0

    @property
    def label(self) -> str:
        return self.id


def _subdirs(path: Path) -> List[Path]:
    if not path.is_dir():
        return []
    return sorted((d for d in path.iterdir() if d.is_dir()), key=lambda d: d.name)


def _own_dirs(root: Path) -> List[Path]:
    """Directories of `root` that are part of the package itself.

    `root/packages/` is excluded: its content is handled as dependency layers,
    not as the package's own tree.
    """
    return [d for d in _subdirs(root) if d.name != NESTED_DIRNAME]


def resolve_layers(root: Path, package_id: str, default_base: str = DEFAULT_BASE) -> List[Path]:
    """Build the ordered layer stack for one top-level package."""
    nested = root / package_id / NESTED_DIRNAME
    nested_deps = [d.name for d in _subdirs(nested)]

    bases: List[Path] = []
    overrides: List[Path] = []

    if nested_deps:
        for dep in sorted(nested_deps):
            sibling = root / dep
            if sibling.is_dir():
                # A real package this one patches: mount it, then its patch.
                bases.append(sibling)
                overrides.append(nested / dep)
            else:
                # Bundled package that only exists inside this one.
                bases.append(nested / dep)
                gate.bump("layer_bundled_package")
                logger.debug("package '%s' bundles self-contained package '%s'",
                             package_id, dep)
    elif package_id != default_base:
        base = root / default_base
        if base.is_dir():
            bases.append(base)
        else:
            gate.bump("layer_base_missing")
            logger.warning("package '%s' has no layers and no base '%s' at %s",
                           package_id, default_base, root)

    own = root / package_id
    layers = bases + overrides + [own]
    return [p for p in layers if p.is_dir()]


def build_files(
    layers: Iterable[Path],
    own_root: Optional[Path] = None,
    exclude_patterns: Optional[List[str]] = None,
) -> tuple[Dict[str, Path], int]:
    """Merge layer trees into one key -> path map, later layers winning.

    `own_root`'s `packages/` sub-directory is skipped: its content is mounted as
    its own layer, and walking it twice would key those files under a
    `packages/...` prefix where they can never override anything.

    `exclude_patterns` is applied here, the same way `walk_dir` applies it, so a
    merged layer stack sees exactly the file set the old single-package walk did.
    Losing this filter silently pulled `models/`, `sounds/` and `static_objects/`
    into the parse and moved vanilla's counts (vehicle 379 → 383).

    Returns (files, shadowed). `shadowed` counts files that a higher layer
    overwrote — that is data being deliberately replaced, not lost, so it gets
    a counter rather than a silent `continue` (AGENTS.md §6.2).
    """
    patterns = [re.compile(p) for p in (exclude_patterns or [])]

    def excluded(name: str) -> bool:
        return any(p.fullmatch(name) for p in patterns)

    files: Dict[str, Path] = {}
    shadowed = 0
    for layer in layers:
        for dirpath, dirnames, filenames in os.walk(layer):
            dirnames[:] = sorted(d for d in dirnames if not excluded(d))
            if own_root is not None and Path(dirpath) == own_root:
                dirnames[:] = [d for d in dirnames if d != NESTED_DIRNAME]
            for name in sorted(filenames):
                if excluded(name):
                    continue
                abs_path = Path(dirpath, name)
                rel = abs_path.relative_to(layer).as_posix()
                if rel in files:
                    shadowed += 1
                files[rel] = abs_path
    if shadowed:
        gate.bump("layer_overridden", shadowed)
    return files, shadowed


def list_ids(
    packages_root: Path,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> List[str]:
    """Ordered package names under `packages_root`, after include/exclude."""
    packages_root = Path(packages_root)
    if not packages_root.is_dir():
        raise RuntimeError(f"packages_root doesn't exist: {packages_root}")

    include = list(include or [])
    exclude = set(exclude or [])

    ids = sorted(d.name for d in _subdirs(packages_root))
    if include:
        missing = [i for i in include if i not in ids]
        if missing:
            raise RuntimeError(f"packages.include names not found under {packages_root}: {missing}")
        ids = [i for i in ids if i in include]
    return [i for i in ids if i not in exclude]


def build(
    packages_root: Path,
    package_id: str,
    default_base: str = DEFAULT_BASE,
    exclude_patterns: Optional[List[str]] = None,
) -> Package:
    """Resolve one package's layer stack and merged file set."""
    packages_root = Path(packages_root)
    root = packages_root / package_id
    layers = resolve_layers(packages_root, package_id, default_base)
    files, shadowed = build_files(layers, own_root=root, exclude_patterns=exclude_patterns)
    pkg = Package(id=package_id, root=root, layers=layers, files=files, shadowed=shadowed)
    logger.debug("package '%s': %d layers, %d files (%d shadowed)",
                 package_id, len(layers), len(files), shadowed)
    return pkg
