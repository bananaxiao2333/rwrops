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
from util import Clogger
from util.classes import Config, Temp
from util.file_utils import file_reader, walk_dir, xml_parser_factory
from util.ops import parse_file
from util.timer import timer

Clogger.init_color_logger()
logger = logging.getLogger("ROOT")


def clean_final(temp: Temp, primarykey: str) -> Temp:
    ret: Dict[str, Dict[str, Dict]] = {}

    for item in temp.final:
        type = item.get('type')
        key = item.get(primarykey)

        if type:
            if not ret.get(type):
                ret[type] = {}
            if key:
                if key in ret[type]:
                    # Merge: lists append unique, scalar keep existing
                    existing = ret[type][key]
                    for k2, v2 in item.items():
                        if isinstance(v2, list) and isinstance(existing.get(k2), list):
                            seen = {str(e) for e in existing[k2]}
                            for e in v2:
                                if str(e) not in seen:
                                    existing[k2].append(e)
                                    seen.add(str(e))
                        elif k2 not in existing:
                            existing[k2] = v2
                else:
                    ret[type][key] = item

    # 对每个类别按照primarykey排序
    sorted_ret: Dict[str, Dict[str, Dict]] = {}

    for type_name, type_data in ret.items():
        if not type_data:
            sorted_ret[type_name] = {}
            continue

        def get_sort_key(item_key: str, item_data: Dict) -> Any:
            """Try numeric sort, fall back to string. Returns (priority, value) tuple."""
            sort_value = item_data.get(primarykey, item_key)
            try:
                return (0, int(sort_value))
            except (ValueError, TypeError):
                try:
                    return (1, float(sort_value))
                except (ValueError, TypeError):
                    return (2, str(sort_value))

        # 按照primarykey排序
        sorted_items = sorted(
            type_data.items(),
            key=lambda x: get_sort_key(x[0], x[1])
        )

        # 创建新的字典
        sorted_ret[type_name] = {k: v for k, v in sorted_items}

    temp.sorted_final = sorted_ret
    return temp


@timer
def main_procces(config: Config):
    temp = Temp()
    Plogger = logging.getLogger(config.CONFIGFILE)

    @timer
    def scan(config: Config, temp: Temp) -> Temp:
        # Scan main packages
        for src_name, src_paths in [("package", config.package_path), ("plugin", config.plugin_paths)]:
            if not src_paths:
                continue
            for p in src_paths:
                Plogger.debug(f"walking in {src_name} '{p}'")
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

    Plogger.debug(
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
    Plogger.debug(
        f"configuration types: {list(conf_type.keys())} ")
    Plogger.debug(
        f"resource: {list(res_type.keys())} ")

    with tqdm(range(len(temp.conf_file)), desc="Files") as pbar:
        for item in temp.conf_file:
            try:
                data: str = file_reader(Path(item))
                xml_content: BeautifulSoup = xml_parser_factory(data)
                temp = parse_file(content=xml_content,
                                  config=config, temp=temp, source_path=item)
            except Exception:
                logger.warning(f"Error when parsing: {item}")
            pbar.update()

    # ── Plugin hooks: parse AngelScript files for commands & exchange items ──
    try:
        from util.as_parser import run as run_as_parser
        as_data = run_as_parser()
        # Inject commands as entities
        for cmd in as_data.get("commands", []):
            cmd["type"] = "command_config"
            cmd["key"] = cmd["command"]
            temp.final.append(cmd)
        n_cmds = len(as_data.get("commands", []))
        n_exch = len(as_data.get("exchange_categories", []))
        Plogger.info(f"AS plugin: {n_cmds} commands, {n_exch} exchange categories")

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
        Plogger.warning(f"AS plugin failed: {e}")

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

    # Sort / dedup data first
    to_dump = temp.final
    if config.sort.enable:
        temp = clean_final(temp, config.sort.primarykey)
        to_dump = temp.sorted_final

    json_str = json.dumps(to_dump, ensure_ascii=False)

    # Create flat dist/ output folder
    out_dir = Path("dist")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build entity counts
    entity_counts = {}
    if config.sort.enable and isinstance(to_dump, dict):
        for etype, items in to_dump.items():
            entity_counts[etype] = len(items) if isinstance(items, dict) else len(items) if isinstance(items, list) else 0
    else:
        for item in temp.final:
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
            Plogger.warning(f"Failed to copy {res_file_path} to {destination}: {e}")

    # Rewrite result.json references to use relative paths (matching _index.json keys)
    def _rewrite_refs(obj: Any) -> Any:
        if isinstance(obj, str):
            return rel_path_map.get(obj, obj)
        elif isinstance(obj, dict):
            return {k: _rewrite_refs(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_rewrite_refs(item) for item in obj]
        return obj

    # Parse back, rewrite, re-serialize to avoid object-reference issues with sorted_final
    to_dump_rewritten = json.loads(json_str)
    to_dump_rewritten = _rewrite_refs(to_dump_rewritten)
    json_str = json.dumps(to_dump_rewritten, ensure_ascii=False)

    # Asset index
    try:
        with open(assets_dir / "_index.json", "w", encoding="utf-8") as f:
            json.dump(asset_map, f, ensure_ascii=False, indent=2)
    except Exception as e:
        Plogger.warning(f"Failed to write asset index: {e}")

    # result.json + metadata.yaml
    with open(out_dir / "result.json", 'w', encoding='utf-8') as f:
        f.write(json_str)

    metadata = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_file": config.CONFIGFILE,
        "source_paths": config.package_path,
        "entity_counts": entity_counts,
        "assets": {
            "exported": res_files_exported,
            "skipped": skipped,
        },
    }

    with open(out_dir / "metadata.yaml", 'w', encoding='utf-8') as f:
        yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    Plogger.info(f"Wrote result.json + metadata.yaml + assets/ ({res_files_exported} files) to dist/")

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
            Plogger.info("Wrote index.html")
        except Exception as e:
            Plogger.warning(f"Failed to generate index.html: {e}")


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
        logger.info(f"handling config '{item}'")
        main_procces(config)
