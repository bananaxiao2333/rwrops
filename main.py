import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from bs4 import BeautifulSoup
from tqdm import tqdm
import yaml
from util.Clogger import setup_logging
from util.classes import Config, Temp
from util.file_utils import file_reader, walk_dir, xml_parser_factory
from util.ops import parse_file, rel_source, relative_to_roots
from util.timer import timer
from util import gate
from util import packages as pkgmod

setup_logging()
logger = logging.getLogger(__name__)

# Bump when the shape of result.json changes in a way a consumer must know about.
# Consumers should refuse a schema they do not understand rather than guess.
SCHEMA_VERSION = 2

DIST = Path("dist")
PACKAGES_DIR = DIST / "packages"
ASSETS_DIR = DIST / "assets"

#: Top-level entries of dist/ that are hand-managed, not generated. A build
#: clears everything else under dist/ so a removed package cannot linger.
#: Gate baselines deliberately live in `.gate/` at the repo root instead —
#: anything left in dist/ is uploaded to the CDN.
DIST_KEEP = {".edgeone", "edgeone.json", ".gitignore", ".env", ".cursor",
             "CNAME", "_redirects"}


class AssetPool:
    """`dist/assets/` — one content-addressed pool shared by every package.

    Vanilla alone exports ~1,000 files and 87 MB, and every overlay package
    references nearly the same set. Per-package asset directories would copy
    those bytes 20-odd times, so the pool is global: the flat name is derived
    from (package-relative path, content hash), which means the same texture
    reached through `vanilla/textures/` and through `classic`'s layer stack
    resolves to the *same* destination file and is written once.

    Same path + different content (a genuine override) hashes differently and
    therefore gets its own file, which is what the overlay semantics require.
    """

    def __init__(self, root: Path):
        self.root = root
        self._by_src: Dict[str, str] = {}
        self.written = 0
        self.reused = 0

    def export(self, src: Path, rel_posix: str) -> str:
        cached = self._by_src.get(str(src))
        if cached is not None:
            self.reused += 1
            return cached

        raw = src.read_bytes()
        chash = hashlib.sha256(raw).hexdigest()[:8]
        base_name = rel_posix.replace("\\", "_").replace("/", "_")
        stem = Path(base_name).stem
        suffix = Path(base_name).suffix
        safe_name = f"{stem}-{chash}{suffix}"

        destination = self.root / safe_name
        if destination.exists():
            # Same bytes reached through a different layer root (two packages
            # shipping an identical texture under different names).
            self.reused += 1
        else:
            destination.write_bytes(raw)
            self.written += 1
        self._by_src[str(src)] = safe_name
        return safe_name


def classify(paths: Iterable[Path]) -> Temp:
    """Split a file list into XML-ish configs and resources.

    Content-sniffed, not extension-matched: RWR's entity files are `.vehicle`,
    `.weapon`, `.projectile`, `.call`, ... and all of them are XML.
    """
    temp = Temp()
    for path in paths:
        try:
            data = file_reader(path, size=5)
            if data.startswith("<"):
                # SVG is XML, so it sniffs as a config file — but it is an
                # asset. `map_config.objects_svg` points at maps/<key>/objects.svg
                # (19 files, 96 MB) and the frontend renders it as the map
                # object-layout overlay. Treating it as a config both failed to
                # parse it and left the field pointing at nothing, so every map
                # showed a broken image.
                if path.suffix.lower() == '.svg':
                    temp.res_file.append(str(path))
                    continue
                temp.conf_file.append(str(path))
            else:
                raise RuntimeError
        except Exception:
            temp.res_file.append(str(path))
    return temp


def collect_resources(config: Config) -> Iterable[Path]:
    for p in config.package_path:
        yield from walk_dir(Path(p), config.exclude_patterns)


@timer
def parse_package(
    config: Config,
    *,
    out_dir: Path,
    pool: AssetPool,
    temp: Temp,
    parse_paths: List[str],
) -> Dict[str, Any]:
    """Parse one package's already-resolved file set and write its dataset.

    `temp` arrives pre-classified (conf_file + res_file) so the caller decides
    which files belong to the package. `parse_paths` is that package's layer
    roots, mod-first, used for `inherit_from` resolution and `_source`.
    """
    log = logging.getLogger(__name__)

    with tqdm(range(len(temp.conf_file)), desc="Files") as pbar:
        for item in temp.conf_file:
            try:
                data: str = file_reader(Path(item))
                xml_content: BeautifulSoup = xml_parser_factory(data)
                temp = parse_file(content=xml_content,
                                  config=config, temp=temp, source_path=item)
            except Exception as e:
                # A whole file's data disappears here. Count it, don't just warn.
                logger.warning(f"Error when parsing: {item}: {e}")
                gate.bump("parse_error")
            pbar.update()

    # ── Plugin hooks: parse AngelScript files for commands & exchange items ──
    try:
        from util.as_parser import run as run_as_parser

        as_data = run_as_parser(
            cmd_path=Path(config.as_command_path) if config.as_command_path else None,
            exch_path=Path(config.as_exchange_path) if config.as_exchange_path else None,
            search_dirs=[Path(p) for p in parse_paths],
        )
        # Inject commands as entities. They come from AngelScript, not XML, so
        # they carry their own source and need the same identity fields.
        cmd_src = rel_source(as_data.get("command_source"), parse_paths)
        for cmd in as_data.get("commands", []):
            cmd["type"] = "command_config"
            cmd["key"] = cmd["command"]
            cmd["_source"] = cmd_src
            cmd["_id"] = f"command_config:{cmd['command']}@{cmd_src or '?'}"
            temp.final.append(cmd)
        n_cmds = len(as_data.get("commands", []))
        n_exch = len(as_data.get("exchange_categories", []))
        log.info(f"AS plugin: {n_cmds} commands, {n_exch} exchange categories")

        # Attach exchange data: forward (this → prizes) and reverse (prize → source)
        for cat in as_data.get("exchange_categories", []):
            cat_name = cat.get("category", "")
            prize_pools = cat.get("prize_pools", [])

            # Forward: input items → what prizes you get
            for inp in cat.get("input", []):
                inp_key = inp.get("key", "")
                if not inp_key:
                    continue
                for entity in temp.final:
                    if entity.get("key") == inp_key:
                        if "exchange_prizes" not in entity:
                            entity["exchange_prizes"] = []
                        entity["exchange_prizes"].append({
                            "category": cat_name,
                            "prize_pools": prize_pools,
                        })
                        break

            # Reverse: prize items → which categories they come from
            for pool_entry in prize_pools:
                for prize in pool_entry:
                    p_key = prize.get("key", "")
                    if not p_key:
                        continue
                    for entity in temp.final:
                        if entity.get("key") == p_key:
                            if "exchange_sources" not in entity:
                                entity["exchange_sources"] = []
                            source_entry = {
                                "category": cat_name,
                                "input": cat.get("input", []),
                            }
                            # dedup by category name
                            existing_cats = {s.get("category") for s in entity["exchange_sources"]}
                            if cat_name not in existing_cats:
                                entity["exchange_sources"].append(source_entry)
                            break
    except Exception as e:
        log.warning(f"AS plugin failed: {e}")

    # Collect all referenced filenames from entity data (recursive)
    refs = set()

    def _collect_refs(obj):
        if isinstance(obj, str):
            refs.add(obj)
            refs.add(obj.replace("\\", "/"))
        elif isinstance(obj, dict):
            for v in obj.values():
                _collect_refs(v)
        elif isinstance(obj, list):
            for item in obj:
                _collect_refs(item)

    for item in temp.final:
        _collect_refs(item)

    # Flat records, one per parsed node, never merged. Aggregate-by-key used to
    # live here and silently dropped colliding scalars (65 of them measured); see
    # output_schema.md. `sort` now sorts, it does not aggregate.
    to_dump = temp.final
    if config.sort.enable:
        pk = config.sort.primarykey
        to_dump = sorted(to_dump, key=lambda e: str(e.get(pk) or e.get("_id") or ""))

    json_str = json.dumps(to_dump, ensure_ascii=False)

    # Build entity counts
    entity_counts: Dict[str, int] = {}
    for item in to_dump:
        t = item.get("type", "unknown")
        entity_counts[t] = entity_counts.get(t, 0) + 1

    # Export referenced .res files into the shared pool
    asset_map: Dict[str, str] = {}
    rel_path_map: Dict[str, str] = {}  # bare/asset_name → relative path
    res_files_exported = 0
    skipped = 0
    for res_file_path in temp.res_file:
        res_path = Path(res_file_path)
        # Deepest root wins, not first match. `parse_paths` is mod-first, so a
        # package's own directory precedes its `packages/<dep>` override mounts:
        # first-match keyed `classic/packages/vanilla/maps/map11/map.png` as
        # `packages/vanilla/maps/map11/map.png`, which no record references, so
        # it failed the filter below and was dropped. That silently killed the
        # map icon for the 10 maps classic overrides.
        rel_posix = relative_to_roots(res_path, parse_paths) or res_path.name
        asset_name = rel_posix.replace("/", "_").replace("\\", "_")
        if rel_posix not in refs and res_path.name not in refs and asset_name not in refs:
            skipped += 1
            continue

        # Record lookup mappings: bare/asset name → posix relative path
        res_bare = res_path.name
        if res_bare not in rel_path_map:
            rel_path_map[res_bare] = rel_posix
        for alias in (rel_posix, asset_name):
            if alias not in rel_path_map:
                rel_path_map[alias] = rel_posix

        try:
            asset_map[rel_posix] = pool.export(res_path, rel_posix)
            res_files_exported += 1
        except Exception as e:
            log.warning(f"Failed to export {res_file_path}: {e}")
            gate.bump("asset_export_failed")

    # Rewrite result.json references to use relative paths (matching assets.json keys)
    def _rewrite_refs(obj: Any) -> Any:
        if isinstance(obj, str):
            return rel_path_map.get(obj, obj)
        elif isinstance(obj, dict):
            return {k: _rewrite_refs(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_rewrite_refs(item) for item in obj]
        return obj

    # Parse back, rewrite, re-serialize so asset paths are rewritten throughout
    to_dump_rewritten = json.loads(json_str)
    to_dump_rewritten = _rewrite_refs(to_dump_rewritten)

    # Versioned envelope: a consumer that does not know this version can fail
    # loudly instead of silently misreading the shape. Deliberately no timestamp
    # here -- gate.sh compares result.json byte-for-byte across runs, and the
    # build time already lives in metadata.yaml, which every consumer fetches.
    payload = {
        "schema": SCHEMA_VERSION,
        "counts": entity_counts,
        "records": to_dump_rewritten,
    }
    json_str = json.dumps(payload, ensure_ascii=False)

    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-package asset index: package-relative path → flat name in the shared pool.
    try:
        with open(out_dir / "assets.json", "w", encoding="utf-8") as f:
            json.dump(asset_map, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"Failed to write asset index: {e}")

    with open(out_dir / "result.json", 'w', encoding='utf-8') as f:
        f.write(json_str)

    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "schema": SCHEMA_VERSION,
        "config_file": config.CONFIGFILE,
        "entity_counts": entity_counts,
        "assets": {
            "exported": res_files_exported,
            "skipped": skipped,
        },
    }

    with open(out_dir / "metadata.yaml", 'w', encoding='utf-8') as f:
        yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    log.info(f"Wrote result.json + metadata.yaml + assets.json ({res_files_exported} assets) to {out_dir}/")

    # ── Generate index.html ──────────────────────────────────────────
    if config.generate_index_html:
        try:
            from util.index_html import generate as generate_index
            generate_index(
                out_dir=out_dir,
                to_dump=to_dump_rewritten,
                entity_counts=entity_counts,
                metadata=metadata,
                asset_map=asset_map,
            )
            log.info("Wrote index.html")
        except Exception as e:
            log.warning(f"Failed to generate index.html: {e}")

    return metadata


def reset_dist() -> None:
    """Clear generated output without touching hand-managed deploy files."""
    DIST.mkdir(parents=True, exist_ok=True)
    for entry in sorted(DIST.iterdir()):
        if entry.name in DIST_KEEP:
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink()


def single_package_run(config: Config) -> None:
    """Legacy single-package mode: walk `package_path` and write to dist/ root."""
    log = logging.getLogger(__name__)
    temp = classify(collect_resources(config))

    log.debug(f"configuration: {len(temp.conf_file)} resource: {len(temp.res_file)}")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    pool = AssetPool(ASSETS_DIR)
    metadata = parse_package(config, out_dir=DIST, pool=pool, temp=temp,
                             parse_paths=list(config.package_path))
    (DIST / "packages.json").write_text(json.dumps({
        "schema": SCHEMA_VERSION,
        "packages": [{
            "id": "default",
            "label": "default",
            "layers": [Path(p).name for p in config.package_path],
            "records": sum(metadata["entity_counts"].values()),
            "counts": metadata["entity_counts"],
            "assets": metadata["assets"]["exported"],
        }],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def multi_package_run(config: Config) -> None:
    """Every package under `packages.root` becomes its own selectable dataset."""
    log = logging.getLogger(__name__)
    assert config.packages is not None
    root = Path(os.path.expanduser(config.packages.root))

    ids = pkgmod.list_ids(root,
                          include=config.packages.include,
                          exclude=config.packages.exclude)
    log.info("discovered %d packages under %s", len(ids), root)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    pool = AssetPool(ASSETS_DIR)

    index: List[Dict[str, Any]] = []
    for pid in ids:
        # Counters are reported per package: one accumulated block for 22
        # packages cannot be explained, which AGENTS.md §3.4 requires.
        gate.reset()
        pkg = pkgmod.build(root, pid,
                           default_base=config.packages.default_base,
                           exclude_patterns=config.exclude_patterns)
        log.info("── package '%s' (%d layers, %d files, %d shadowed)",
                 pkg.id, len(pkg.layers), len(pkg.files), pkg.shadowed)

        # Mod-first so `inherit_from` prefers the overriding copy; the layer
        # stack that built the file map is base-first, which is its inverse.
        parse_paths = [str(p) for p in reversed(pkg.layers)]

        # Derive the effective config: every path-relative operation (inherit
        # resolution, _source) must see this package's stack, not the config's.
        pkg_config = config.model_copy(update={"package_path": parse_paths})

        temp = classify(pkg.files.values())
        out_dir = PACKAGES_DIR / pkg.id
        metadata = parse_package(pkg_config, out_dir=out_dir, pool=pool,
                                 temp=temp, parse_paths=parse_paths)
        gate.report(log, prefix=f"[{pkg.id}]")

        index.append({
            "id": pkg.id,
            "label": pkg.id,
            # A nested override dir carries the same name as the package it
            # patches, so the raw path list reads `vanilla + vanilla + classic`.
            # Collapse to the names a person would say out loud.
            "layers": list(dict.fromkeys(p.name for p in pkg.layers)),
            "files": len(pkg.files),
            "shadowed": pkg.shadowed,
            "records": sum(metadata["entity_counts"].values()),
            "counts": metadata["entity_counts"],
            "assets": metadata["assets"]["exported"],
            "built": metadata["timestamp"],
        })

    # ── dist/packages.json — the selector's data ──────────────────────
    with open(DIST / "packages.json", "w", encoding="utf-8") as f:
        json.dump({"schema": SCHEMA_VERSION, "packages": index}, f,
                  ensure_ascii=False, indent=2)

    # ── dist/metadata.yaml — build-level summary ──────────────────────
    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "schema": SCHEMA_VERSION,
        "config_file": config.CONFIGFILE,
        "packages_root": str(root),
        "package_count": len(index),
        "entity_counts": {
            t: sum(p["counts"].get(t, 0) for p in index)
            for t in sorted({t for p in index for t in p["counts"]})
        },
        "assets": {
            "pool_files": pool.written + pool.reused,
            "written": pool.written,
            "deduplicated": pool.reused,
        },
    }
    with open(DIST / "metadata.yaml", 'w', encoding='utf-8') as f:
        yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    log.info("package index: %d packages, asset pool %d written / %d deduplicated (%d total)",
             len(index), pool.written, pool.reused, pool.written + pool.reused)

    # ── dist/index.html — package selector landing page ────────────────
    if config.generate_index_html:
        try:
            from util.index_html import generate_landing
            generate_landing(DIST, index, metadata)
            log.info("Wrote package landing page")
        except Exception as e:
            log.warning(f"Failed to generate landing index.html: {e}")


@timer
def main_procces(config: Config):
    logging.getLogger(__name__).info("processing config '%s'", config.CONFIGFILE)
    reset_dist()
    if config.packages is not None:
        # Multi-package mode reports its own counters per package.
        multi_package_run(config)
    else:
        single_package_run(config)
        gate.report(logger)


if __name__ == "__main__":
    logger.info("RWROPS requested | Fidelity Bravery Integrity")
    logger.debug(f"CWD: {os.getcwd()}")
    logger.info("reading yaml files in config folder")
    configs_path = os.listdir("config")
    configs_path = [item for item in configs_path if item.endswith(".yaml")]
    logger.debug(f"awaiting config file count: {len(configs_path)}")
    for item in configs_path:
        item_path = Path(os.path.join("config", item))

        logger.debug(f"trying to read config '{item}'")
        try:
            data = yaml.load(file_reader(
                item_path), Loader=yaml.FullLoader)
            config = Config(CONFIGFILE=item, **data)
        except Exception as e:
            logger.critical(
                f"error when reading config '{item}'", exc_info=e)
            continue

        # Re-init logging with config-level settings
        setup_logging(level=config.log_level, log_file=config.log_file)

        logger.info(f"handling config '{item}'")
        main_procces(config)
