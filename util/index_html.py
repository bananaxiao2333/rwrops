"""Generate a static index.html for the dist/ output — pure HTML + CSS, no JS."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import html
import logging

logger = logging.getLogger(__name__)

# ── CSS (embedded in <style>) ──────────────────────────────────────────────
CSS = r"""
* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
    Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
  background: #f4f6f9;
  color: #1a1a2e;
  line-height: 1.6;
  min-height: 100vh;
}

/* ── Header ──────────────────────────────────────────────────────── */
header {
  background: linear-gradient(135deg, #16213e 0%, #0f3460 100%);
  color: #eaeaea;
  padding: 2.5rem 2rem 1.8rem;
  border-bottom: 4px solid #e94560;
}
header h1 {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  margin-bottom: 0.35rem;
}
header .meta {
  font-size: 0.88rem;
  opacity: 0.75;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem 2rem;
}
header .meta span {
  white-space: nowrap;
}

/* ── Main ─────────────────────────────────────────────────────────── */
main {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.5rem 1.2rem 3rem;
}

/* ── Summary cards ────────────────────────────────────────────────── */
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.8rem;
  margin-bottom: 2rem;
}
.summary-card {
  background: #fff;
  border-radius: 10px;
  padding: 1rem 1.2rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  border-left: 4px solid #e94560;
  transition: transform 0.15s;
}
.summary-card:hover {
  transform: translateY(-2px);
}
.summary-card .count {
  font-size: 1.8rem;
  font-weight: 700;
  color: #e94560;
}
.summary-card .label {
  font-size: 0.85rem;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* ── Section title ────────────────────────────────────────────────── */
.section-title {
  font-size: 1.3rem;
  font-weight: 600;
  color: #16213e;
  margin: 2rem 0 0.8rem;
  padding-bottom: 0.4rem;
  border-bottom: 2px solid #e94560;
  display: inline-block;
}

/* ── Details / accordion ──────────────────────────────────────────── */
details {
  background: #fff;
  border-radius: 10px;
  margin-bottom: 0.6rem;
  box-shadow: 0 2px 6px rgba(0,0,0,0.05);
  overflow: hidden;
}
details[open] {
  box-shadow: 0 4px 14px rgba(0,0,0,0.08);
}
summary {
  cursor: pointer;
  padding: 0.9rem 1.2rem;
  font-weight: 600;
  font-size: 1.05rem;
  color: #16213e;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  user-select: none;
  background: #fafbfc;
  border-bottom: 1px solid transparent;
  transition: background 0.12s;
}
summary:hover {
  background: #f0f2f5;
}
details[open] > summary {
  border-bottom-color: #e2e5ea;
}
summary::before {
  content: "+";
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  background: #e94560;
  color: #fff;
  font-weight: 700;
  font-size: 1rem;
  flex-shrink: 0;
  transition: transform 0.15s;
}
details[open] > summary::before {
  content: "\2212";  /* minus sign */
}

/* ── Table ────────────────────────────────────────────────────────── */
.table-wrap {
  overflow-x: auto;
  padding: 0.2rem;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.84rem;
  white-space: nowrap;
}
thead {
  background: #16213e;
  color: #fff;
}
th {
  padding: 0.6rem 0.8rem;
  text-align: left;
  font-weight: 600;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  position: sticky;
  top: 0;
}
td {
  padding: 0.5rem 0.8rem;
  border-bottom: 1px solid #eceff4;
  color: #333;
}
tbody tr:nth-child(even) {
  background: #f9fafb;
}
tbody tr:hover {
  background: #eef2f7;
}

/* Value styling */
td .null  { color: #aaa; font-style: italic; }
td .bool  { color: #805ad5; font-weight: 600; }
td .num   { color: #2b6cb0; font-family: "SF Mono", "Fira Code", monospace; }
td .str   { color: #22543d; }
td .list  { color: #744210; font-size: 0.8rem; }
td .dict  { color: #702459; font-size: 0.8rem; }

/* ── Assets section ───────────────────────────────────────────────── */
.asset-item {
  display: inline-block;
  background: #fff;
  border-radius: 8px;
  padding: 0.4rem 0.8rem;
  margin: 0.25rem;
  font-size: 0.8rem;
  font-family: "SF Mono", "Fira Code", monospace;
  color: #2d3748;
  border: 1px solid #e2e5ea;
}
.asset-item .hash {
  color: #718096;
  margin-left: 0.3rem;
}

/* ── Footer ───────────────────────────────────────────────────────── */
footer {
  text-align: center;
  padding: 1.5rem;
  color: #999;
  font-size: 0.78rem;
  border-top: 1px solid #e2e5ea;
  margin-top: 2rem;
}

/* ── Empty state ──────────────────────────────────────────────────── */
.empty {
  padding: 1.5rem;
  text-align: center;
  color: #999;
  font-style: italic;
}
</style>"""

# A set of common keys that get their own column early
PRIORITY_KEYS = {"key", "name", "type", "class", "value", "description"}


def _format_value(val: Any) -> str:
    """Return an HTML-safe string representation of a value."""
    if val is None:
        return '<span class="null">—</span>'
    if isinstance(val, bool):
        return f'<span class="bool">{"true" if val else "false"}</span>'
    if isinstance(val, (int, float)):
        return f'<span class="num">{val}</span>'
    if isinstance(val, list):
        return f'<span class="list">[{len(val)} items]</span>'
    if isinstance(val, dict):
        return f'<span class="dict">{"{"}{len(val)} keys{"}"}</span>'
    s = html.escape(str(val))
    if len(s) > 120:
        s = s[:117] + "…"
    return f'<span class="str">{s}</span>'


def _collect_keys(items: List[Dict[str, Any]]) -> List[str]:
    """Collect unique keys from a list of item dicts, with priority keys first."""
    seen = set()
    ordered = []
    for pk in PRIORITY_KEYS:
        for item in items:
            if pk in item and pk not in seen:
                seen.add(pk)
                ordered.append(pk)
    for item in items:
        for key in item:
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def _build_table(items: List[Dict[str, Any]], columns: List[str]) -> str:
    """Build an HTML <table> from a list of item dicts using the given columns."""
    if not items:
        return '<div class="empty">No items</div>'

    thead = "<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in columns) + "</tr>"
    rows = []
    for item in items:
        cells = "".join(
            f"<td>{_format_value(item.get(c))}</td>" for c in columns
        )
        rows.append(f"<tr>{cells}</tr>")

    return (
        f'<div class="table-wrap"><table>'
        f"<thead>{thead}</thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table></div>"
    )


def generate(
    out_dir: Path,
    to_dump: Union[List[Dict[str, Any]], Dict[str, Dict[str, Dict[str, Any]]]],
    entity_counts: Dict[str, int],
    metadata: Dict[str, Any],
    asset_map: Optional[Dict[str, str]] = None,
) -> None:
    """Generate dist/index.html as a static file index and data browser.

    Parameters
    ----------
    out_dir : Path
        The dist/ output directory.
    to_dump : list or dict
        The same data written to result.json:
        - list of dicts when sort is disabled
        - {entity_type: {key: entity_data}} when sort is enabled.
    entity_counts : dict
        {entity_type: count}
    metadata : dict
        Metadata dict (timestamp, config_file, source_paths, etc.)
    asset_map : dict, optional
        {rel_path: destination_filename} mapping from assets/_index.json.
    """

    # Resolve entity data to a uniform {entity_type: [items...]} form
    entity_items: Dict[str, List[Dict[str, Any]]] = {}

    if isinstance(to_dump, dict):
        for etype, idict in to_dump.items():
            if isinstance(idict, dict):
                entity_items[etype] = list(idict.values())
            elif isinstance(idict, list):
                entity_items[etype] = idict
            else:
                entity_items[etype] = []
    else:
        # list of dicts
        for item in to_dump:
            etype = item.get("type", "unknown")
            entity_items.setdefault(etype, []).append(item)

    # ── Build HTML ──────────────────────────────────────────────────────
    parts: List[str] = []

    # Doc head
    parts.append(
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<meta name="color-scheme" content="light">\n'
        "<title>RWR Ops — Data Index</title>\n"
        f"<style>{CSS}</style>\n"
        "</head>\n<body>\n"
    )

    # Header
    ts = metadata.get("timestamp", datetime.now(timezone.utc).isoformat())
    cfg = metadata.get("config_file", "?")
    parts.append("<header>\n")
    parts.append("  <h1> RWR Ops — Data Index</h1>\n")
    parts.append('  <div class="meta">\n')
    parts.append(f'    <span> Generated: {html.escape(ts)}</span>\n')
    parts.append(f'    <span> Config: {html.escape(str(cfg))}</span>\n')
    parts.append("  </div>\n")
    parts.append("</header>\n")

    parts.append("<main>\n")

    # ── Summary cards ───────────────────────────────────────────────────
    parts.append('  <h2 class="section-title"> Entity Summary</h2>\n')
    parts.append('  <div class="summary">\n')
    if entity_counts:
        for etype, count in sorted(entity_counts.items()):
            parts.append('    <div class="summary-card">\n')
            parts.append(f'      <div class="count">{count}</div>\n')
            parts.append(f'      <div class="label">{html.escape(etype)}</div>\n')
            parts.append("    </div>\n")
    else:
        parts.append('    <div class="empty">No entities found</div>\n')
    parts.append("  </div>\n")

    # ── Entity detail sections ──────────────────────────────────────────
    parts.append('  <h2 class="section-title"> Entities</h2>\n')
    if entity_items:
        for etype in sorted(entity_items.keys()):
            items = entity_items[etype]
            all_keys = _collect_keys(items)
            parts.append(f"  <details>\n")
            parts.append(
                f"    <summary>{html.escape(etype)} "
                f"<small>({len(items)} items)</small></summary>\n"
            )
            parts.append(f"    {_build_table(items, all_keys)}\n")
            parts.append("  </details>\n")
    else:
        parts.append('  <div class="empty">No entity data available</div>\n')

    # ── Assets ───────────────────────────────────────────────────────────
    if asset_map:
        parts.append('  <h2 class="section-title"> Assets</h2>\n')
        parts.append("  <div>\n")
        for rel_path, dest_name in sorted(asset_map.items()):
            name = html.escape(dest_name)
            parts.append(
                f'    <span class="asset-item">'
                f'{name}</span>\n'
            )
        parts.append("  </div>\n")

    parts.append("</main>\n")

    # Footer
    total_entities = sum(entity_counts.values()) if entity_counts else 0
    parts.append("<footer>\n")
    parts.append(f"  RWR Ops &copy; {datetime.now().year} — "
                 f"{total_entities} entities across {len(entity_items)} types\n")
    parts.append("</footer>\n")
    parts.append("</body>\n</html>")

    html_content = "\n".join(parts)

    index_path = out_dir / "index.html"
    index_path.write_text(html_content, encoding="utf-8")
    logger.info(f"Wrote index.html ({index_path.stat().st_size:,} bytes)")
