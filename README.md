# RWROPS — RWR Omni Parser System

A flexible XML data parser for [Running With Rifles](https://www.runningwithrifles.com/) that extracts structured data from vehicle, weapon, and other entity configs into normalized JSON — for **every package the game ships**, plus static HTML data browsers.

## Features

- **Dynamic entity recognition** — auto-identifies entity types from XML root elements
- **Multi-package extraction** — every package under `media/packages` becomes its own selectable dataset
- **VFS layering** — each package is parsed as the game loads it (base + overrides), so an overlay mod yields real data, not just the handful of files it ships
- **Shared asset pool** — content-addressed, so 22 packages cost 1,816 files instead of 21,900
- **Hierarchical extraction** — nested structures with relationship preservation
- **Data transforms** — float, int, bool, vector3/2 parsing
- **Inheritance resolution** — merges base entity data via `inherit_from`
- **Attribute flattening** — optional promotion of nested attrs to root level
- **Static HTML index** — pure HTML+CSS data browser, one per package plus a landing page
- **AngelScript plugin** — parses AS command & exchange item configs
- **Multi-config** — drop any number of `.yaml` configs into `config/`

## Quick Start

```bash
# 1. Clone
git clone https://github.com/bananaxiao2333/rwrops.git
cd rwrops

# 2. Install (uv)
uv sync

# 3. Configure
cp config/core.yaml.example config/core.yaml
# Edit packages.root to point at your RWR media/packages directory

# 4. Run (22 packages, ~5.5 min)
uv run python main.py
```

> **Contributing?** Read [`AGENTS.md`](AGENTS.md) first. Every change must pass
> `./gate.sh`, which checks that two runs produce identical output, reports what
> each package's run discarded, and diffs every package against its baseline to
> prove no data was lost.

One dataset per game package, plus a shared asset pool:

```
dist/
├── packages.json                     # package index — what the site's selector reads
├── metadata.yaml                     # build-level summary
├── index.html                        # landing page linking every package
├── assets/                           # ONE content-addressed pool for all packages
└── packages/<id>/
    ├── result.json                   # that package's records
    ├── metadata.yaml                 # per-package stats
    ├── assets.json                   # package-relative path → name in the pool
    └── index.html                    # standalone browser for that package
```

### Packages are overlays, not directories

`media/packages/` holds 22 top-level packages, but only a few are self-contained.
`classic` ships 103 files of its own and gets everything else from the base game;
parsing it alone would yield ~100 records and call that "the classic package".
So each package is loaded the way the game loads it — base packages first, then
its own tree, with the topmost definition of a path winning. `classic` therefore
comes out as ~2,137 records, not 100. See `util/packages.py` and `AGENTS.md` §1.1.

Because packages share most of their files, assets are written to one global pool
keyed by `(package-relative path, content hash)`. The 22 packages reference
21,900 assets between them and the pool holds **1,816 files** — 92% deduplicated.

## Configuration

Config files live in `config/` (git-ignored). Start from the example:

```
config/
├── core.yaml          ← your config (ignored)
└── core.yaml.example  ← template (tracked)
```

Full config structure is documented in the example file. Key sections:

| Section            | Purpose                                          |
| ------------------ | ------------------------------------------------ |
| `packages.root`    | `media/packages` — every sub-directory becomes a selectable dataset |
| `packages.include` / `exclude` | Which packages to build (empty = all)  |
| `packages.default_base` | Base package for overlays that declare no dependency (`vanilla`) |
| `package_path`     | Single-package mode; ignored while `packages` is set |
| `entities`         | Per-entity-type extraction rules                 |
| `generate_index_html` | Toggle `index.html` generation (default: true) |
| `sort`             | Sort output by primary key                       |
| `exclude_patterns` | Regex patterns to skip during file walk          |

## Supported Transforms

| Transform       | Input → Output                    |
| --------------- | --------------------------------- |
| `to_float`      | `"123.45"` → `123.45`             |
| `to_int`        | `"42"` → `42`                     |
| `to_bool`       | `"true"` → `true`                 |
| `parse_vector3` | `"1.0 2.0 3.0"` → `[1.0, 2.0, 3.0]` |
| `parse_vector2` | `"10 20"` → `[10.0, 20.0]`        |

## Project Structure

```
rwrops/
├── main.py               # Entry point — reads configs, runs pipeline
├── pyproject.toml        # uv project metadata
├── icon.svg              # App icon (embedded in index.html)
├── config/
│   └── core.yaml.example # Annotated config template
├── util/
│   ├── classes.py        # Pydantic models (Config, EntityConfig, Temp)
│   ├── ops.py            # Core parse logic
│   ├── file_utils.py     # File I/O, walker, XML parser factory
│   ├── as_parser.py      # AngelScript command/exchange parser
│   ├── index_html.py     # Static HTML index generator
│   ├── Clogger.py        # Colored logging setup
│   ├── timer.py          # @timer decorator
│   └── plugin.py         # Plugin hooks
└── dist/                 # Output (git-ignored)
```

## Related

- [bananaxiao2333/rwrops-webhelper](https://github.com/bananaxiao2333/rwrops-webhelper) — React web frontend for browsing this data
