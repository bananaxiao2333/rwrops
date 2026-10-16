"""AS parser — extract structured data from RWR's AngelScript sources.

RWR ships ~230 `.as` files under `media/packages`. Three families of
machine-readable data live in them, all written as AngelScript array literals:

  1. chat commands      checkCommand(message, "name")  → permission + actions
  2. weighted pools     array<ScoredResource@>         → {key, class, score, count}
  3. resource lists     array<Resource@>               → {key, class}

The first version of this module hard-coded two filenames
(`basic_command_handler.as`, `item_delivery_configurator_invasion.as`) and so
saw 186 of the game's 295 commands and 824 of its 884 `ScoredResource` entries.
Discovery is now by *content*: every `.as` file under the search roots is read
once, in a deterministic order, and routed to whichever extractor matches. The
old filenames survive only as role hints used to label a command's permission.

Overlay semantics match the XML side: a file is keyed by its path relative to
the layer root it was found under, so `classic/scripts/...` shadows
`vanilla/scripts/...` the same way the game resolves it.
"""
import json
import logging
import re
import time
from pathlib import Path

from util import gate

logger = logging.getLogger(__name__)


# ═══════════════════════ shared helpers ═══════════════════════

#: Block comments are replaced by their own newlines so line numbers survive.
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
#: Line comments, but never the `//` inside a quoted string.
_LINE_COMMENT = re.compile(r'("(?:[^"\\]|\\.)*")|//[^\n]*')

_FUNC_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:protected\s+|private\s+)?"
    r"(?:void|bool|int|string|float|uint)\s+(\w+)\s*\([^;{)]*\)\s*(?:const\s*)?\{"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_comments(text: str) -> str:
    """Remove comments, preserving line numbering.

    Not cosmetic: `spawn_at_node.as` carries a whole commented-out
    `array<ScoredResource@>` block, and `stage_configurator_invasion.as` keeps
    disabled entries as `//ScoredResource("", "", 0.0f)` lines. Parsing those
    would invent pools the game never loads.
    """
    text = _BLOCK_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return _LINE_COMMENT.sub(lambda m: m.group(1) or "", text)


def iter_as_files(dirs) -> list:
    """`(layer-relative path, absolute path)` for every `.as` under *dirs*.

    *dirs* is a package's layer stack, mod-first — the same list `main.py`
    hands the XML side. Keying on the layer-relative path reproduces the game's
    overlay rule (topmost definition of a path wins). Within one root the walk
    is sorted, so the result never depends on filesystem order.
    """
    claimed: dict = {}
    shadowed = 0
    for root in dirs:
        root = Path(root)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.as")):
            rel = p.relative_to(root).as_posix()
            if rel in claimed:
                shadowed += 1
                continue
            claimed[rel] = p
    if shadowed:
        gate.bump("as_layer_shadowed", shadowed)
    return sorted(claimed.items())


def _match_braces(text: str, start: int) -> str:
    """Extract the braced block at start (inclusive), returns substring or empty."""
    if start < 0 or start >= len(text) or text[start] != '{':
        return ""
    depth, end = 0, start
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    return text[start:end]


def _split_outer_arrays(body: str) -> list:
    """Split body like {ScoredResource...},\n{ScoredResource...},\n{ScoredResource...} into
    individual pool strings. We look for '},{' at the boundary between inner arrays."""
    pools = []
    depth = 0
    start = 0
    for i, ch in enumerate(body):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                # end of a pool array — check if next non-space char is ',' then '{'
                j = i + 1
                while j < len(body) and body[j] in ' \t\n\r,':
                    if body[j] == ',':
                        j += 1
                        while j < len(body) and body[j] in ' \t\n\r':
                            j += 1
                        if j < len(body) and body[j] == '{':
                            pools.append(body[start:i + 1])
                            start = j
                            break
                    j += 1
    # last pool
    if start < len(body):
        pools.append(body[start:])
    return pools


def _enclosing_function(text: str, pos: int):
    """`(name, body_start, body_end)` for the function containing *pos*."""
    best = None
    for m in _FUNC_RE.finditer(text, 0, pos):
        best = m
    if best is None:
        return "", pos, pos
    body_start = best.end() - 1
    body = _match_braces(text, body_start)
    return best.group(1), body_start, body_start + len(body)


_CLASS_RE = re.compile(r"(?:^|\n)[ \t]*class\s+(\w+)\s*(?::\s*(\w+))?\s*\{")


def _enclosing_class(text: str, pos: int):
    """`(name, base)` of the class whose body contains *pos*, else `("", "")`.

    The body check matters: without it, a global function that follows a class
    would be attributed to it.
    """
    best = None
    for m in _CLASS_RE.finditer(text, 0, pos):
        best = m
    if best is None:
        return "", ""
    body = _match_braces(text, best.end() - 1)
    if not body or pos > best.end() - 1 + len(body):
        return "", ""
    return best.group(1), best.group(2) or ""


def _decl_block(text: str, end: int) -> str:
    """Braced literal right after a declaration, or "" when it is not one.

    `array<string> keys = dict.getKeys();` matches the declaration regex too,
    so the `{` has to come before the statement's `;` to count as a literal.
    """
    brace = text.find('{', end)
    if brace < 0:
        return ""
    semi = text.find(';', end)
    if 0 <= semi < brace:
        return ""
    return _match_braces(text, brace)


def _human(name: str) -> str:
    r = [name[0].upper() if name[0].islower() else name[0]]
    for i, c in enumerate(name[1:], 1):
        if c.isupper() and name[i - 1].islower():
            r.append(' ')
        r.append(c)
    return ''.join(r).strip()


# ═══════════════════════ command parser ═══════════════════════

#: Fallback permission when neither a comment marker nor a guard call is in
#: sight. Only a fallback — the per-command scan below wins whenever it finds
#: something, so `basic_command_handler.as` keeps its existing labels.
_ROLE_HINTS = (
    ("supporter", "supporter"),
    ("emoticon", "player"),
    ("command_handler", "admin"),
)
_DEFAULT_ROLE = "player"


def _role_for(rel: str) -> str:
    name = Path(rel).name.lower()
    for needle, role in _ROLE_HINTS:
        if needle in name:
            return role
    return _DEFAULT_ROLE


def _permission(lines, i: int, default: str) -> str:
    """Resolve a command's permission level.

    Two passes, in order of authority:
      1. the original marker scan — a `moderator only` / `admin only` comment
         in the 30 lines above. Kept byte-for-byte, because it is what produced
         the eight moderator commands of `basic_command_handler.as`.
      2. an actual guard call between the enclosing function header and the
         command: `ownsDlc(…)` → supporter, `isModerator(…)` → moderator,
         `isAdmin(…)` → admin. This is what the files that were never parsed
         before rely on (`ban_manager.as`, `map_rotator_invasion.as`, …).
    """
    for j in range(i, max(i - 30, 0), -1):
        if "moderator only" in lines[j]:
            return "moderator"
        if "admin only" in lines[j]:
            return "admin"

    for j in range(i, max(i - 400, -1), -1):
        line = lines[j]
        if re.match(r"\s*(?:protected\s+|private\s+)?(?:void|bool|int|string)\s+\w+\s*\(",
                    line):
            break
        if "ownsDlc(" in line:
            return "supporter"
        if "isModerator(" in line:
            return "moderator"
        if "isAdmin(" in line:
            return "admin"

    return default


def parse_commands(path: Path, default_permission: str = "admin") -> list:
    """Extract every command with its full action chain.

    Reads the file *unstripped*, on purpose. Block boundaries here come from
    counting braces line by line, so removing comments moves where two long
    sibling blocks end (`/177`, `/196` in `basic_command_handler.as`) and
    silently changes their action lists. The command set is identical either
    way, so the raw text stays — it keeps the already-published output stable.
    """
    logger.debug("reading commands from %s", path)
    t0 = time.monotonic()
    text = _read(path)
    lines = text.split('\n')
    results = []
    seen = set()

    logger.debug("  %d lines, scanning for checkCommand patterns", len(lines))

    for i, line in enumerate(lines):
        m = re.search(r'checkCommand\(message,\s*"([^"]+)"\)', line)
        if not m:
            continue
        name = m.group(1)
        if name in seen:
            logger.debug("  duplicate command '%s' at line %d — skipped", name, i + 1)
            gate.bump("as_command_duplicate")
            continue
        seen.add(name)

        perm = _permission(lines, i, default_permission)

        # collect braced block (skip leading closing braces from prior else-if)
        code_lines, depth, started, saw_open = [], 0, False, False
        for j in range(i, min(i + 80, len(lines))):
            for ch in lines[j]:
                if ch == '{':
                    depth += 1
                    started = saw_open = True
                elif ch == '}' and saw_open:
                    depth -= 1
                    if depth == 0:
                        break
            code_lines.append(lines[j].strip())
            if saw_open and depth == 0:
                break
        block = '\n'.join(code_lines)

        # Parse actions inside this block
        actions = _parse_actions(block)

        results.append({
            "command": name,
            "permission": perm,
            "actions": actions,
        })

    elapsed = time.monotonic() - t0
    logger.debug("parsed %d commands from %s in %.2fs", len(results), path.name, elapsed)
    return results


def merge_commands(file_data: dict) -> list:
    """Merge per-file command lists into one package-level list.

    A package's layer stack is mod-first, so a mod that redefines `/restart`
    overrides vanilla's rather than producing a second record for it.

    Takes the already-extracted per-file data rather than re-reading: calling
    the extractor a second time in the same package would replay its drop
    counters and double them in the `[gate]` report.
    """
    out: list = []
    seen: dict = {}
    scanned = 0
    for rel, data in file_data.items():
        if not data["commands"]:
            continue
        scanned += 1
        for cached in data["commands"]:
            name = cached["command"]
            if name in seen:
                logger.debug("command '%s' already defined in %s — %s skipped",
                             name, seen[name], rel)
                gate.bump("as_command_shadowed")
                continue
            seen[name] = rel
            # Copy: the cached entry is shared with every other package, and
            # `source` is the one field the caller stamps on.
            cmd = dict(cached)
            cmd["source"] = rel
            out.append(cmd)
    logger.info("command sources: %d files, %d commands", scanned, len(out))
    return out


# ═══════════════════════ per-file memo ═══════════════════════

#: Every extractor below is a pure function of one file's bytes, but a build
#: re-reads nearly the same `.as` files for all 22 packages (`classic` scans
#: all of `vanilla`'s, `ww2_invasion` scans `ww2_base` + `vanilla`, …). The
#: results are memoised on the absolute path for the life of the process.
_FILE_CACHE: dict = {}


def _extract_file(path: Path) -> dict:
    """All per-file extraction for *path*, memoised.

    Drop counters are captured alongside the result and replayed on every cache
    hit, so a package that reuses a file still reports the `[gate]` numbers it
    would have reported had it re-parsed the file itself.
    """
    key = str(path)
    hit = _FILE_CACHE.get(key)
    if hit is not None:
        for reason, n in hit["counters"].items():
            gate.bump(reason, n)
        return hit

    before = dict(gate.COUNTERS)
    text = _read(path)
    role = _role_for(path.name)
    out: dict = {
        "commands": [],
        "reward_pools": [],
        "resource_lists": [],
        "string_tables": [],
        "value_tables": [],
        "module": None,
    }
    # Cheap substring gates keep the regexes off the ~200 files that cannot match.
    if "checkCommand(" in text:
        out["commands"] = parse_commands(path, default_permission=role)
    if "ScoredResource(" in text:
        out["reward_pools"] = parse_reward_pools(path)
    if "Resource(" in text:
        out["resource_lists"] = parse_resource_lists(path)
    if "array<string>" in text:
        out["string_tables"] = parse_string_tables(path)
    if "dictionary" in text or ".set(" in text:
        out["value_tables"] = parse_value_tables(path)

    module = parse_module_index(path)
    if module["classes"] or module["trackers"] or module["xml_classes"]:
        out["module"] = module

    out["counters"] = {
        reason: n
        for reason in set(gate.COUNTERS) | set(before)
        if (n := gate.COUNTERS.get(reason, 0) - before.get(reason, 0))
    }
    _FILE_CACHE[key] = out
    return out


def _parse_actions(block: str) -> list:
    """Extract sequential actions from a command block."""
    actions = []

    # 1) .getComms().send("<command .../>")  — inline XML string
    for m in re.finditer(r"""\.getComms\(\)\.send\("((?:[^"]|\\")*)"\)""", block):
        xml_str = m.group(1)
        actions.append({"type": "send_xml", "xml": xml_str})

    # 2) .getComms().send(XmlElement(varname)) — pre-built dynamic XML
    for m in re.finditer(r"""\.getComms\(\)\.send\(XmlElement\((\w+)\)\)""", block):
        varname = m.group(1)
        actions.append({"type": "send_xml_element", "variable": varname})

    # 3) .getComms().send(var) where var was built locally
    for m in re.finditer(r"""\.getComms\(\)\.send\(([a-zA-Z_]\w*)\)""", block):
        var = m.group(1)
        # Filter out noise variables
        if var in ("command", "dict", "c", "m_metagame", "XmlElement"):
            continue
        # Only count if we haven't already captured this as an XmlElement call
        already = any(a.get("variable") == var for a in actions)
        if not already:
            actions.append({"type": "send_var", "variable": var})

    # 4) sendPrivateMessage(metagame, senderId, "text")
    for m in re.finditer(r'sendPrivateMessage\([^,]+,\s*(\w+),\s*"([^"]*)"', block):
        target = m.group(1)
        msg = m.group(2)
        actions.append({"type": "chat_reply", "target": target, "message": msg})

    # 5) spawnInstanceNearPlayer(senderId, "key", "type")
    for m in re.finditer(r'spawnInstanceNearPlayer\(\w+,\s*"([^"]+)",\s*"([^"]+)"', block):
        actions.append({"type": "spawn", "key": m.group(1), "class": m.group(2)})

    # 6) destroyAllFactionVehicles(f, "key") or destroyAllEnemyVehicles("key")
    for m in re.finditer(r'destroyAllFactionVehicles\([^,]+,\s*"([^"]+)"\)', block):
        actions.append({"type": "destroy_vehicles", "key": m.group(1)})
    for m in re.finditer(r'destroyAllEnemyVehicles\((\w+)\)', block):
        actions.append({"type": "destroy_all_enemy_vehicles", "key": m.group(1)})

    # 7) fillInventory(senderId)
    if "fillInventory" in block:
        actions.append({"type": "fill_inventory"})

    # 8) handleKick(message, senderId)
    if "handleKick" in block:
        actions.append({"type": "kick_player"})

    # 9) handleSidInfo
    if "handleSidInfo" in block:
        actions.append({"type": "lookup_player_sid"})

    # 10) Play a character animation — supporter handler, e.g. /dance1
    for m in re.finditer(r'animate\([^,]+,\s*"([^"]+)"', block):
        actions.append({"type": "animate", "animation": m.group(1)})

    # 11) Emit an emoticon projectile — emoticons.as, e.g. /smiley
    for m in re.finditer(r'handleEmoticon\([^,]+,[^,]+,\s*"([^"]+)"', block):
        actions.append({"type": "emoticon", "key": m.group(1)})

    # 12) Parse inline XML commands for detail
    for m in re.finditer(r"(<command\s[^>]*/>)", block):
        xml = m.group(1)
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', xml))
        cmd_class = attrs.get("class", "")
        if cmd_class == "set_match_status":
            effect = []
            if "win" in attrs: effect.append(f"F{attrs['win']}_WIN")
            if "lose" in attrs: effect.append(f"F{attrs['lose']}_LOSE")
            actions.append({"type": "game_result", "detail": ", ".join(effect)})
        elif cmd_class == "update_base":
            actions.append({"type": "capture_base", "faction": attrs.get("owner_id", "?")})
        elif cmd_class == "commander_ai":
            bd = attrs.get("base_defense", "?")
            actions.append({"type": "set_ai_behavior", "base_defense": bd})
        elif cmd_class == "set_marker":
            actions.append({"type": "place_marker", "text": attrs.get("text", "")})
        elif cmd_class == "create_instance":
            actions.append({"type": "spawn", "instance_key": attrs.get("instance_key", ""), "where": attrs.get("position", "")})
        elif cmd_class == "update_inventory":
            actions.append({"type": "update_inventory_cmd"})
        elif cmd_class == "chat":
            actions.append({"type": "broadcast_message", "text": attrs.get("text", "")})

    # 13) XML assembled by string concatenation — `music_tracker.as` builds
    #     `<command class='set_soundtrack' … />` across a dozen `+` fragments,
    #     which none of the patterns above can see. Only consulted when nothing
    #     else matched, so already-parsed commands keep their exact action list.
    if not actions:
        for m in re.finditer(r'instance_key=\\\"([^\\]+)\\\"', block):
            actions.append({"type": "spawn_by_concatenation", "key": m.group(1)})
        seen_classes = []
        for m in re.finditer(r"class=\\?['\"]([A-Za-z_]\w*)", block):
            cls = m.group(1)
            if cls in ("command",) or cls in seen_classes:
                continue
            seen_classes.append(cls)
            actions.append({"type": "send_xml_class", "class": cls})

    return actions


# ═══════════════════════ reward / lottery pool parser ═══════════════════════

#: `array<ScoredResource@> resources = { … }` — one pool, every entry drawn.
_SCORED_DECL_FLAT = re.compile(r"array<\s*ScoredResource@\s*>\s+(\w+)\s*=")
#: `array<array<ScoredResource@>> rewardPasses = { {…}, {…} }` — N pools.
_SCORED_DECL_NESTED = re.compile(r"array<\s*array<\s*ScoredResource@\s*>\s*>\s+(\w+)\s*=")
_SCORED_ITEM = re.compile(
    r'ScoredResource\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*([0-9.]+)f\s*(?:,\s*(\d+)\s*)?\)'
)
_CALL_RE = re.compile(r"(\w+)\s*\(([^;{}()]*(?:\([^()]*\)[^;{}()]*)*)\)")
_STRING_RE = re.compile(r'"([^"]*)"')


def _scored_items(chunk: str) -> list:
    pool = []
    for m in _SCORED_ITEM.finditer(chunk):
        pool.append({
            "key": m.group(1),
            "class": m.group(2),
            "score": float(m.group(3)),
            "count": int(m.group(4)) if m.group(4) else 1,
        })
    return pool


def _consumer_of(text: str, start: int, end: int, var: str) -> tuple:
    """The call that consumes *var* after its declaration — name + string args.

    `SpawnAtNode(m_metagame, resources, "random_crate", 0, count)` yields
    `("SpawnAtNode", ["random_crate"])`, which is what tells a reader whether a
    pool feeds a crate drop, an escort reward, or a ticket exchange.
    """
    var_re = re.compile(r"\b" + re.escape(var) + r"\b")
    for m in _CALL_RE.finditer(text, start, end):
        name, args = m.group(1), m.group(2)
        if name in ("if", "for", "while", "switch", "return"):
            continue
        if not var_re.search(args):
            continue
        return name, [s for s in _STRING_RE.findall(args) if s]
    return "", []


#: `void setupXxx(...)` / `protected void setupXxx(...)` — the delivery side of a
#: ticket exchange.
_SETUP_FN = re.compile(r"(?:protected\s+)?void\s+(setup\w+)\s*\(")


def parse_reward_pools(path: Path) -> list:
    """Every weighted table in a file — one record per declaring function.

    This replaces two extractors that described the same thing. `parse_exchanges`
    read the `setup*()` delivery lists, `parse_reward_pools` read the
    `ScoredResource` literals; measured on `vanilla`, **31 of 36 tables came out
    of both, byte-identical**, so the pools were being written twice — once
    attached to the input item and once as their own record. They are one table
    with two optional halves:

      input   the `Resource(...)` items you hand over (ticket exchanges only)
      pools   the weighted `ScoredResource` tables you draw from

    A table is identified by the function that declares it, which is the only
    identity that covers both kinds: `setupTicketSummer` has an input and no
    consumer to speak of, `addRandomSpecialCrates` has no input and a consumer
    (`SpawnAtNode`, label `random_crate`).
    """
    text = _strip_comments(_read(path))
    tables: dict = {}

    # ── weighted literals ─────────────────────────────────────────────
    decls = [(m, False) for m in _SCORED_DECL_NESTED.finditer(text)]
    decls += [(m, True) for m in _SCORED_DECL_FLAT.finditer(text)]
    # A nested decl does not contain a flat decl, so overlaps only come from
    # ordering. Sort by position and drop any decl swallowed by an earlier one.
    decls.sort(key=lambda t: t[0].start())
    consumed_until = -1

    for m, flat in decls:
        if m.start() < consumed_until:
            continue
        brace = text.find('{', m.end())
        if brace < 0:
            continue
        block = _match_braces(text, brace)
        if not block:
            continue
        consumed_until = brace + len(block)

        if flat:
            pools = [_scored_items(block)]
        else:
            inner = block.strip().lstrip('{').rstrip('}')
            pools = [_scored_items(pt) for pt in _split_outer_arrays(inner)]
        pools = [p for p in pools if p]
        if not pools:
            gate.bump("as_pool_empty")
            continue

        fn, _body_start, body_end = _enclosing_function(text, m.start())
        consumer, consumer_args = _consumer_of(text, brace + len(block), body_end,
                                               m.group(1))
        group = fn or Path(path).stem
        tables[group] = {
            "group": group,
            "title": _human(group),
            "variable": m.group(1),
            "consumer": consumer,
            "label": consumer_args[0] if consumer_args else "",
            "input": [],
            "pools": pools,
        }

    # ── delivery lists, folded into the same record ────────────────────
    # A `setup*()` with no `ScoredResource` literal still has an input and is
    # still a table (vanilla has two: the laptop and briefcase unlock lists).
    for m in _SETUP_FN.finditer(text):
        group = m.group(1)
        brace = text.find('{', m.end())
        if brace < 0:
            continue
        body = _match_braces(text, brace)
        if not body:
            continue
        delivery = [{"key": k, "class": c} for k, c in _RES_ITEM.findall(body)]
        if not delivery:
            continue
        tables.setdefault(group, {
            "group": group,
            "title": _human(group),
            "variable": "",
            "consumer": "",
            "label": "",
            "input": [],
            "pools": [],
        })["input"] = delivery

    # Sorted by group so the record order is a property of the source, not of
    # the order the two passes happened to run in.
    return [tables[g] for g in sorted(tables)]


# ═══════════════════════ resource list parser ═══════════════════════

_RES_LIST_DECL = re.compile(r"array<\s*Resource@\s*>\s+(\w+)\s*=")
_RES_PUSH = re.compile(
    r'(\w+)\s*\.\s*push_back\(\s*Resource\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)\s*\)'
)
_RES_ITEM = re.compile(r'(?<!Scored)Resource\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')


def parse_resource_lists(path: Path) -> list:
    """Named `array<Resource@>` lists — delivery inputs and vehicle unlocks.

    Both spellings appear in the game: a literal
    `array<Resource@> deliveryList = { Resource(…) }`, and an accumulator built
    with `list.push_back(Resource(…))` in `vehicle_delivery_configurator_invasion.as`.
    """
    text = _strip_comments(_read(path))
    groups: dict = {}

    def add(fn: str, var: str, items: list):
        if not items:
            return
        slot = groups.setdefault((fn, var), [])
        for it in items:
            if it not in slot:
                slot.append(it)

    for m in _RES_LIST_DECL.finditer(text):
        brace = text.find('{', m.end())
        if brace < 0:
            continue
        block = _match_braces(text, brace)
        if not block:
            continue
        items = [{"key": k, "class": c} for k, c in _RES_ITEM.findall(block)]
        fn, _s, _e = _enclosing_function(text, m.start())
        add(fn or Path(path).stem, m.group(1), items)

    for m in _RES_PUSH.finditer(text):
        fn, _s, _e = _enclosing_function(text, m.start())
        add(fn or Path(path).stem, m.group(1),
            [{"key": m.group(2), "class": m.group(3)}])

    out = []
    for (fn, var), items in sorted(groups.items()):
        out.append({"group": fn, "variable": var, "items": items})
    return out


# ═══════════════════════ string / value tables ═══════════════════════

#: `array<string> m_rewardVehicles = { "tank.vehicle", … }` — 90 declarations
#: holding 328 values across the packages. Most of them *are* a game system:
#: the agent reward pools, the costume pools, the jammer lists, the drop tables.
_STRING_TABLE_DECL = re.compile(r"array<\s*string\s*>\s+(\w+)\s*=")
_DICT_DECL = re.compile(r"\bdictionary\s+(\w+)\s*=")
_DICT_SET = re.compile(r"(\w+)\.set\(\s*\"([^\"]+)\"\s*,\s*([^)]+?)\s*\)")
_DICT_PAIR = re.compile(r'\{\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\}')


def parse_string_tables(path: Path) -> list:
    """Named `array<string>` literals — the string tables behind game systems."""
    text = _strip_comments(_read(path))
    out: list = []
    for m in _STRING_TABLE_DECL.finditer(text):
        block = _decl_block(text, m.end())
        if not block:
            continue
        values = [s for s in _STRING_RE.findall(block) if s]
        if not values:
            gate.bump("as_table_empty")
            continue
        cls, base = _enclosing_class(text, m.start())
        fn, _s, _e = _enclosing_function(text, m.start())
        out.append({
            "owner": cls or base or "",
            "function": fn or "",
            "variable": m.group(1),
            "values": values,
        })
    return out


def parse_value_tables(path: Path) -> list:
    """`dictionary` literals and `dict.set(k, v)` — key→value tables.

    Two shapes carry real data: the `{"key", "value"}` literal lists, and the
    scored ones such as `mapIdToRegionIndex.set("map8", 0)` in the campaign
    configurators or the WW2 nation weights.
    """
    text = _strip_comments(_read(path))
    groups: dict = {}

    def add(owner, fn, var, entries):
        if not entries:
            return
        slot = groups.setdefault((owner, fn, var), [])
        for e in entries:
            if e not in slot:
                slot.append(e)

    for m in _DICT_DECL.finditer(text):
        block = _decl_block(text, m.end())
        if not block:
            continue
        cls, base = _enclosing_class(text, m.start())
        fn, _s, _e = _enclosing_function(text, m.start())
        add(cls or base or "", fn or "", m.group(1),
            [{"key": k, "value": v} for k, v in _DICT_PAIR.findall(block)])

    for m in _DICT_SET.finditer(text):
        lit = _STRING_RE.fullmatch(m.group(3))
        cls, base = _enclosing_class(text, m.start())
        fn, _s, _e = _enclosing_function(text, m.start())
        add(cls or base or "", fn or "", m.group(1),
            [{"key": m.group(2), "value": lit.group(1) if lit else m.group(3)}])

    return [
        {"owner": o, "function": f, "variable": v, "entries": e}
        for (o, f, v), e in sorted(groups.items())
    ]


# ═══════════════════════ module index ═══════════════════════

_INCLUDE = re.compile(r'#include\s+"([^"]+)"')
_TRACKER = re.compile(r"addTracker\(\s*(\w+)")
_XML_CLASS = re.compile(r"""class\s*=\s*\\?['"]([A-Za-z_]\w*)['"]""")


def parse_module_index(path: Path) -> dict:
    """Structural index of one `.as` file: what it pulls in, defines, assembles.

    The XML pipeline has no equivalent for this — the scripts are where a game
    mode is actually wired together, and none of it was visible in the dataset.
    `vanilla`'s invasion mode, for instance, assembles 53 trackers here.
    """
    text = _strip_comments(_read(path))
    classes = []
    for m in _CLASS_RE.finditer(text):
        entry = {"name": m.group(1), "base": m.group(2) or ""}
        if entry not in classes:
            classes.append(entry)

    trackers: dict = {}
    for m in _TRACKER.finditer(text):
        cls, _base = _enclosing_class(text, m.start())
        slot = trackers.setdefault(cls, [])
        if m.group(1) not in slot:
            slot.append(m.group(1))

    xml_classes = []
    for m in _XML_CLASS.finditer(text):
        if m.group(1) not in xml_classes:
            xml_classes.append(m.group(1))

    return {
        "includes": sorted(set(_INCLUDE.findall(text))),
        "classes": classes,
        "trackers": [{"owner": k, "trackers": v} for k, v in sorted(trackers.items())],
        "xml_classes": xml_classes,
    }


# ═══════════════════════ auto-discovery ═══════════════════════

#: The one filename discovery still needs: it is the canonical command handler,
#: so it is preferred as `command_source` when several files define commands.
#: Nothing else is special-cased — the exchange configurator used to be listed
#: here too, and that second pass is exactly what duplicated every prize pool.
_COMMAND_FILENAME = "basic_command_handler.as"


# ═══════════════════════ main ═══════════════════════

def run(
    cmd_path: Path | None = None,
    exch_path: Path | None = None,
    search_dirs: list | None = None,
) -> dict:
    """Run the full AS parse pipeline.

    Args:
        cmd_path:       Explicit path to a command handler. Overrides discovery.
        exch_path:      Accepted for compatibility; ignored. The exchange
                        configurator is no longer special — it is one of the
                        files the generic scan reads.
        search_dirs:    Package layer roots (mod-first) to scan.

    Returns:
        {"commands", "reward_pools", "resource_lists", "string_tables",
         "value_tables", "modules", "command_source"}
    """
    t0 = time.monotonic()
    result: dict = {
        "commands": [],
        "reward_pools": [],
        "resource_lists": [],
        "string_tables": [],
        "value_tables": [],
        "modules": [],
        "command_source": None,
    }
    dirs = [Path(d) for d in (search_dirs or [])]

    files = iter_as_files(dirs)
    logger.info("scanned %d AngelScript files across %d layer root(s)",
                len(files), len(dirs))

    # ── extract every file exactly once for this package ──────────────
    # Memoised across packages, but called once per (file, package): a second
    # call would replay the file's drop counters and double them in `[gate]`.
    file_data: dict = {}
    for rel, path in files:
        try:
            file_data[rel] = _extract_file(path)
        except OSError as e:
            logger.warning("cannot read %s: %s", path, e)
            gate.bump("as_read_error")
        except Exception as e:
            logger.warning("extraction failed for %s: %s", rel, e)
            gate.bump("as_parse_error")

    # ── commands ──────────────────────────────────────────────
    if cmd_path and Path(cmd_path).exists():
        logger.info("parsing commands from %s", cmd_path)
        result["commands"] = parse_commands(Path(cmd_path))
        for c in result["commands"]:
            c["source"] = Path(cmd_path).name
        result["command_source"] = str(cmd_path)
    elif file_data:
        result["commands"] = merge_commands(file_data)
        # `command_source` stays a single path for the callers that only want
        # "the" handler. The per-command `source` is the authoritative one.
        by_rel = dict(files)
        srcs = sorted({c["source"] for c in result["commands"] if c.get("source")})
        primary = _COMMAND_FILENAME if _COMMAND_FILENAME in by_rel else (srcs[0] if srcs else None)
        result["command_source"] = str(by_rel[primary]) if primary in by_rel else None
    else:
        logger.info("no AngelScript files under the layer roots — skipping commands")

    # ── pools, lists, tables, module index ────────────────────
    def _collect(key: str, entry: dict, rel: str) -> None:
        # Copy: cached entries are shared with every other package, and
        # `source` is the one field the caller stamps on.
        entry = dict(entry)
        entry["source"] = rel
        result[key].append(entry)

    for rel, data in file_data.items():
        for key in ("reward_pools", "resource_lists", "string_tables", "value_tables"):
            for entry in data[key]:
                _collect(key, entry, rel)
        if data["module"] is not None:
            _collect("modules", data["module"], rel)

    # ── exchanges ─────────────────────────────────────────────
    # Nothing to do: the ticket exchanges are `setup*()` functions holding an
    # `array<array<ScoredResource@>>`, which the generic scan above already
    # picked up. They used to be a second, special-cased pass over one
    # hard-coded filename, and that is what made the pools appear twice.
    if exch_path:
        logger.debug("exch_path=%s ignored — exchange configurators are "
                     "discovered like any other file", exch_path)

    logger.info(
        "AS totals: %d commands, %d reward pools, %d resource lists, "
        "%d string tables, %d value tables, %d modules, %.2fs",
        len(result["commands"]), len(result["reward_pools"]),
        len(result["resource_lists"]), len(result["string_tables"]),
        len(result["value_tables"]), len(result["modules"]),
        time.monotonic() - t0,
    )
    return result


if __name__ == "__main__":
    r = run(search_dirs=["."])
    print(f"Commands:           {len(r['commands'])}")
    print(f"Reward pools:       {len(r['reward_pools'])}")
    print(f"Resource lists:     {len(r['resource_lists'])}")
    print(f"String tables:      {len(r['string_tables'])}")
    print(f"Value tables:       {len(r['value_tables'])}")
    print(f"Modules:            {len(r['modules'])}")
    for c in r["commands"][:10]:
        print(f"\n  /{c['command']} [{c['permission']}]  ({c.get('source')})")
        for a in c["actions"][:3]:
            print(f"    - [{a['type']}] "
                  f"{json.dumps({k: v for k, v in a.items() if k != 'type'}, ensure_ascii=False)}")
