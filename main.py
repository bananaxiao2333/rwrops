from ast import List
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from bs4 import BeautifulSoup
from tqdm import tqdm
import yaml
from util.Clogger import setup_logging
from util.classes import Config, Temp
from util.file_utils import file_reader, walk_dir, xml_parser_factory
from util.ops import parse_file, rel_source
from util.timer import timer
from util import gate

setup_logging()
logger = logging.getLogger(__name__)

# Bump when the shape of result.json changes in a way a consumer must know about.
# Consumers should refuse a schema they do not understand rather than guess.
SCHEMA_VERSION = 2


@timer
def main_procces(config: Config):
    temp = Temp()
    log = logging.getLogger(__name__)
    log.info("processing config '%s'", config.CONFIGFILE)

    @timer
    def scan(config: Config, temp: Temp) -> Temp:
        # Scan main packages
        for src_name, src_paths in [("package", config.package_path), ("plugin", config.plugin_paths)]:
            if not src_paths:
                continue
            for p in src_paths:
                log.debug(f"walking in {src_name} '{p}'")
                for path in walk_dir(Path(p), config.exclude_patterns):
                    try:
                        data = file_reader(path, size=5)
                        if data.startswith("<"):
                            # SVG files disabled — too large for asset export
                            if path.suffix.lower() == '.svg':
                                continue
                            temp.conf_file.append(str(path))
                        else:
                            raise RuntimeError
                    except:
                        temp.res_file.append(str(path))
                        continue
        return temp

    temp: Temp = scan(config, temp)

    log.debug(
        f"configuration: {len(temp.conf_file)} resource: {len(temp.res_file)} ")
    conf_type = {}
    for item in temp.conf_file:
        conf_type[str(os.path.basename(item)).split(".")[1]] = 0
    res_type = {}
    for item in temp.res_file:
        try:
            res_type[str(os.path.basename(item)).split(".")[1]] = 0
        except:
            pass
    log.debug(
        f"configuration types: {list(conf_type.keys())} ")
    log.debug(
        f"resource: {list(res_type.keys())} ")

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

        # Build search dirs from package_path + plugin_paths
        search_dirs: list[Path] = []
        for p in config.package_path:
            search_dirs.append(Path(p))
        for p in config.plugin_paths:
            search_dirs.append(Path(p))

        as_data = run_as_parser(
            cmd_path=Path(config.as_command_path) if config.as_command_path else None,
            exch_path=Path(config.as_exchange_path) if config.as_exchange_path else None,
            search_dirs=search_dirs,
        )
        # Inject commands as entities. They come from AngelScript, not XML, so
        # they carry their own source and need the same identity fields.
        cmd_src = rel_source(as_data.get("command_source"), config.package_path)
        for cmd in as_data.get("commands", []):
            cmd["type"] = "command_config"
            cmd["key"] = cmd["command"]
            cmd["source"] = cmd_src
            cmd["id"] = f"command_config:{cmd['command']}@{cmd_src or '?'}"
            temp.final.append(cmd)
        n_cmds = len(as_data.get("commands", []))
        n_exch = len(as_data.get("exchange_categories", []))
        log.info(f"AS plugin: {n_cmds} commands, {n_exch} exchange categories")

        # Attach exchange data: forward (this → prizes) and reverse (prize → source)
        for cat in as_data.get("exchange_categories", []):
            cat_name = cat.get("category", "")
            pools = cat.get("prize_pools", [])

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
                            "prize_pools": pools,
                        })
                        break

            # Reverse: prize items → which categories they come from
            for pool in pools:
                for prize in pool:
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
        to_dump = sorted(to_dump, key=lambda e: str(e.get(pk) or e.get("id") or ""))

    json_str = json.dumps(to_dump, ensure_ascii=False)

    # Create flat dist/ output folder
    out_dir = Path("dist")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build entity counts
    entity_counts = {}
    for item in to_dump:
        t = item.get("type", "unknown")
        entity_counts[t] = entity_counts.get(t, 0) + 1

    # Export referenced .res files to dist/assets/ with content-hash suffixes
    assets_dir = out_dir / "assets"
    if assets_dir.exists():
        import shutil
        shutil.rmtree(assets_dir, ignore_errors=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_map = {}
    rel_path_map = {}  # bare/asset_name → relative path, for rewriting result.json
    res_files_exported = 0
    skipped = 0
    for res_file_path in temp.res_file:
        res_path = Path(res_file_path)
        rel_path = res_path.name
        for pp in config.package_path:
            pp_path = Path(pp)
            try:
                rel_path = str(res_path.relative_to(pp_path))
                break
            except ValueError:
                continue
        rel_posix = rel_path.replace("\\", "/")
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

        # Read content and compute hash
        raw = res_path.read_bytes()
        chash = hashlib.sha256(raw).hexdigest()[:8]

        base_name = rel_posix.replace("\\", "_").replace("/", "_")
        stem = Path(base_name).stem
        suffix = Path(base_name).suffix
        safe_name = f"{stem}-{chash}{suffix}"
        destination = assets_dir / safe_name

        try:
            destination.write_bytes(raw)
            res_files_exported += 1
            asset_map[rel_posix] = destination.name
        except Exception as e:
            log.warning(f"Failed to copy {res_file_path} to {destination}: {e}")

    # Rewrite result.json references to use relative paths (matching _index.json keys)
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

    # Asset index
    try:
        with open(assets_dir / "_index.json", "w", encoding="utf-8") as f:
            json.dump(asset_map, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"Failed to write asset index: {e}")

    # result.json + metadata.yaml
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

    log.info(f"Wrote result.json + metadata.yaml + assets/ ({res_files_exported} files) to dist/")

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

    # ── Drop ledger: what this run threw away, and why ──────────────
    gate.report(log)


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
