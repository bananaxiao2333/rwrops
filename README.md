# RWROPS — RWR Omni Parser System

A flexible XML data parser for [Running With Rifles](https://www.runningwithrifles.com/) that extracts structured data from vehicle, weapon, and other entity configs into normalized JSON — plus a static HTML data browser.

## Features

- **Dynamic entity recognition** — auto-identifies entity types from XML root elements
- **Hierarchical extraction** — nested structures with relationship preservation
- **Data transforms** — float, int, bool, vector3/2 parsing
- **Inheritance resolution** — merges base entity data via `inherit_from`
- **Attribute flattening** — optional promotion of nested attrs to root level
- **Asset export** — copies referenced `.res` files into `dist/assets/` with content-hash names
- **Static HTML index** — pure HTML+CSS data browser generated in `dist/index.html`
- **AngelScript plugin** — parses AS command & exchange item configs
- **Multi-config** — drop any number of `.yaml` configs into `config/`

## Quick Start

```bash
# 1. Clone
git clone https://github.com/bananaxiao2333/rwrops-core.git
cd rwrops-core

# 2. Install (uv)
uv sync

# 3. Configure
cp config/core.yaml.example config/core.yaml
# Edit package_path to point at your RWR vanilla data

# 4. Run
uv run python main.py
```

Output lands in `dist/`:
- `result.json` — all parsed entity data
- `metadata.yaml` — generation metadata & stats
- `index.html` — static tactical data browser (open in any browser)
- `assets/` — exported resource files with `_index.json` mapping

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
| `package_path`     | Directories to scan for XML                      |
| `entities`         | Per-entity-type extraction rules                 |
| `generate_index_html` | Toggle `dist/index.html` generation (default: true) |
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
