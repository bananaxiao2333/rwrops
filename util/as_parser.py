"""AS parser — deep command action extraction + exchange category parsing (no entity injection)."""
import re, json, logging
from pathlib import Path

logger = logging.getLogger("ASParser")

CMD_SRC  = r"C:\Users\hongx\Documents\test_sub\scripts\trackers\basic_command_handler.as"
EXCH_SRC = r"C:\Users\hongx\Documents\test_sub\scripts\gamemodes\invasion\item_delivery_configurator_invasion.as"


# ═══════════════════════ command parser ═══════════════════════

def parse_commands(path: Path) -> list:
    """Extract every command with its full action chain."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.split('\n')
    results = []
    seen = set()

    for i, line in enumerate(lines):
        m = re.search(r'checkCommand\(message,\s*"([^"]+)"\)', line)
        if not m:
            continue
        name = m.group(1)
        if name in seen:
            continue
        seen.add(name)

        # Determine permission
        perm = "admin"
        for j in range(i, max(i - 30, 0), -1):
            if "moderator only" in lines[j]:
                perm = "moderator"
                break
            if "admin only" in lines[j]:
                break

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

    return results


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

    # 10) Parse inline XML commands for detail
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

    # 11) Build XML by string concatenation
    if not actions and "getComms().send" not in block:
        # maybe the XML is built via string concatenation
        for m in re.finditer(r'instance_key=\\\"([^\\]+)\\\"', block):
            actions.append({"type": "spawn_by_concatenation", "key": m.group(1)})
        for m in re.finditer(r'class=\\\'([^\\]+)\\\'', block):
            actions.append({"type": "xml_command", "class": m.group(1)})

    return actions


# ═══════════════════════ exchange parser ═══════════════════════

def parse_exchanges(path: Path) -> list:
    """Extract exchange categories (parsed but not injected as entities)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    result = []

    for mm in re.finditer(r'(?:protected\s+)?void\s+(setup\w+)\s*\(', text):
        sname = mm.group(1)
        start = mm.end()
        brace = text.find('{', start)
        if brace < 0:
            continue
        depth, end = 0, brace
        for i in range(brace, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
            if depth == 0:
                end = i + 1
                break
        body = text[brace:end]

        delivery = []
        for rm in re.finditer(r'Resource\("([^"]+)"\s*,\s*"([^"]+)"\)', body):
            delivery.append({"key": rm.group(1), "class": rm.group(2)})

        pools = _extract_pools(body)

        if delivery or pools:
            result.append({
                "category": _human(sname),
                "input": delivery,
                "prize_pools": pools,
            })

    return result


def _extract_pools(body: str) -> list:
    """Extract prize pools from rewardPasses. Pools are separated by '},{' in the array literal."""
    pools = []
    rp_idx = body.find("rewardPasses")
    if rp_idx < 0:
        return pools
    tail = body[rp_idx:]

    # Find the outer array: rewardPasses = { [pool1], ..., [poolN] };
    outer = _match_braces(tail, tail.find('{'))
    if not outer:
        return pools

    # Split pools by '},{' — each pool is a { ... } block
    # First, split the outer array body by the '},{' delimiter that separates inner arrays
    outer_body = outer.strip().lstrip('{').rstrip('}')
    pool_texts = _split_outer_arrays(outer_body)

    for pt in pool_texts:
        pool = []
        for m in re.finditer(
            r'ScoredResource\("([^"]+)"\s*,\s*"([^"]+)"\s*,\s*([0-9.]+)f\s*(?:,\s*(\d+)\s*)?\)', pt
        ):
            pool.append({
                "key": m.group(1),
                "class": m.group(2),
                "score": float(m.group(3)),
                "count": int(m.group(4)) if m.group(4) else 1,
            })
        if pool:
            pools.append(pool)

    return pools


def _match_braces(text: str, start: int) -> str:
    """Extract the braced block at start (inclusive), returns substring or empty."""
    if start < 0 or text[start] != '{':
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


def _human(name: str) -> str:
    r = [name[0].upper() if name[0].islower() else name[0]]
    for i, c in enumerate(name[1:], 1):
        if c.isupper() and name[i - 1].islower():
            r.append(' ')
        r.append(c)
    return ''.join(r).strip()


# ═══════════════════════ main ═══════════════════════

def run() -> dict:
    result = {"commands": [], "exchange_categories": []}

    cp = Path(CMD_SRC)
    if cp.exists():
        result["commands"] = parse_commands(cp)
        logger.info(f"Parse {len(result['commands'])} commands")

    ep = Path(EXCH_SRC)
    if ep.exists():
        result["exchange_categories"] = parse_exchanges(ep)
        total = sum(len(c["input"]) + sum(len(p) for p in c["prize_pools"]) for c in result["exchange_categories"])
        logger.info(f"Parse {len(result['exchange_categories'])} exchange categories ({total} items)")

    return result


if __name__ == "__main__":
    r = run()
    print(f"Commands: {len(r['commands'])}")
    print(f"Exchange categories: {len(r['exchange_categories'])}")
    for c in r["commands"][:10]:
        print(f"\n  /{c['command']} [{c['permission']}]")
        print(f"  描述: {c['description']}")
        print(f"  效果: {c['effects']}")
        for a in c["actions"][:3]:
            print(f"    - [{a['type']}] {json.dumps({k:v for k,v in a.items() if k!='type'}, ensure_ascii=False)}")
