"""Generate a static index.html for the dist/ output — pure HTML + CSS, no JS.

Design language: RWROPS Tactical Data Terminal (matches rwrops_webhelper).
"""

from __future__ import annotations

import html
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# ── Tactical Dark CSS ──────────────────────────────────────────────────────
CSS = r"""
/* ════════════════════════════════════════════════
   RWROPS TACTICAL DATA TERMINAL — Index Theme
   ════════════════════════════════════════════════ */

:root {
  --bg-deep:        #080c12;
  --bg-surface:     #131a24;
  --bg-elevated:    #182233;
  --accent:         #f59e0b;
  --accent-glow:    rgba(245, 158, 11, 0.35);
  --accent-dim:     #b45309;
  --success:        #22c55e;
  --danger:         #ef4444;
  --info:           #3b82f6;
  --text-primary:   #e8edf3;
  --text-secondary: #8899aa;
  --text-muted:     #556677;
  --text-dim:       #3a4a5a;
  --border-subtle:  #1e2d3d;
  --border-mid:     #2a3a4e;
  --font-display:   'Rajdhani', sans-serif;
  --font-mono:      'Share Tech Mono', monospace;
  --radius-sm:      3px;
  --radius-md:      6px;
  --shadow-sm:      0 1px 3px rgba(0,0,0,0.45);
  --shadow-md:      0 4px 12px rgba(0,0,0,0.5);
  --ease-out:       cubic-bezier(0.16, 1, 0.3, 1);
  --ease-smooth:    cubic-bezier(0.4, 0, 0.2, 1);
  --dot-color:      rgba(245, 158, 11, 0.04);
}

*, *::before, *::after {
  margin: 0; padding: 0; box-sizing: border-box;
}

html {
  font-size: 16px;
  -webkit-font-smoothing: antialiased;
}

body {
  font-family: var(--font-display);
  font-weight: 400;
  background-color: var(--bg-deep);
  color: var(--text-primary);
  line-height: 1.6;
  min-height: 100vh;
  overflow-x: hidden;
}

/* Tactical dot-grid */
body::before {
  content: '';
  position: fixed; inset: 0; z-index: -1;
  pointer-events: none;
  background-image: radial-gradient(circle, var(--dot-color) 1px, transparent 1px);
  background-size: 24px 24px;
}

/* Selection */
::selection {
  background: var(--accent);
  color: var(--bg-deep);
}

/* Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg-deep); }
::-webkit-scrollbar-thumb { background: var(--border-mid); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent-dim); }
* { scrollbar-width: thin; scrollbar-color: var(--border-mid) var(--bg-deep); }

h1, h2, h3, h4, h5, h6 {
  font-family: var(--font-display);
  font-weight: 600;
  letter-spacing: 0.03em;
  line-height: 1.25;
}

a { text-decoration: none; color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* ═══════════════════════════ HEADER ═══════════════════════════ */
header {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
  padding: 1.6rem 2rem 1.4rem;
  display: flex;
  align-items: center;
  gap: 1.2rem;
  flex-wrap: wrap;
}

.header-icon {
  width: 48px; height: 48px;
  flex-shrink: 0;
}

.header-text h1 {
  font-size: clamp(22px, 2.5vw, 36px);
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--text-primary);
  margin-bottom: 0.15rem;
}

.header-meta {
  font-family: var(--font-mono);
  font-size: clamp(9px, 0.7vw, 12px);
  color: var(--text-muted);
  letter-spacing: 0.06em;
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 2rem;
}
.header-meta span { white-space: nowrap; }

/* gradient accent line below header */
.header-accent-line {
  height: 1px;
  background: linear-gradient(to right, var(--accent), transparent);
  width: 100%;
}

/* ═══════════════════════════ MAIN ═══════════════════════════ */
main {
  max-width: 1400px;
  margin: 0 auto;
  padding: 1.8rem 1.5rem 3rem;
}

/* ── Section title ────────────────────────────────────────────────── */
.section-title {
  font-family: var(--font-display);
  font-size: clamp(16px, 1.5vw, 22px);
  font-weight: 600;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin: 2.5rem 0 1rem;
  display: flex;
  align-items: center;
  gap: 0.6rem;
}
.section-title::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(to right, var(--border-subtle), transparent);
}

/* ── Summary cards grid ───────────────────────────────────────────── */
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0.7rem;
  margin-bottom: 0.5rem;
}

.summary-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 1rem 1.1rem;
  transition: border-color 0.15s var(--ease-out), transform 0.15s var(--ease-out);
  animation: fade-in 0.3s var(--ease-smooth) both;
}
.summary-card:hover {
  border-color: var(--accent-dim);
  transform: translateY(-2px);
}

.summary-card .count {
  font-family: var(--font-display);
  font-size: 2.2rem;
  font-weight: 700;
  color: var(--accent);
  line-height: 1;
  margin-bottom: 0.25rem;
}

.summary-card .label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* ── Details / accordion ──────────────────────────────────────────── */
details {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  margin-bottom: 0.5rem;
  overflow: hidden;
  animation: fade-in 0.3s var(--ease-smooth) both;
}
details[open] {
  border-color: var(--border-mid);
}

summary {
  cursor: pointer;
  padding: 0.75rem 1.1rem;
  font-family: var(--font-display);
  font-weight: 600;
  font-size: 1rem;
  color: var(--text-primary);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  user-select: none;
  background: var(--bg-elevated);
  border-bottom: 1px solid transparent;
  transition: background 0.12s var(--ease-out);
}
summary:hover {
  background: #1c2838;
}
details[open] > summary {
  border-bottom-color: var(--border-subtle);
}

summary small {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--text-muted);
  font-weight: 400;
  letter-spacing: 0.04em;
}

summary::before {
  content: '+';
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-sm);
  background: var(--accent-dim);
  color: #fff;
  font-family: var(--font-mono);
  font-weight: 700;
  font-size: 0.9rem;
  flex-shrink: 0;
  transition: transform 0.15s var(--ease-out);
}
details[open] > summary::before {
  content: '\2212';
  background: var(--accent);
}

/* ── Table ────────────────────────────────────────────────────────── */
.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: clamp(9px, 0.7vw, 13px);
  white-space: nowrap;
}

thead {
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-mid);
}

th {
  padding: 0.5rem 0.75rem;
  text-align: left;
  font-weight: 600;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-secondary);
  position: sticky;
  top: 0;
  background: var(--bg-elevated);
}

td {
  padding: 0.4rem 0.75rem;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
}

tbody tr:nth-child(even) {
  background: rgba(245, 158, 11, 0.02);
}
tbody tr:hover {
  background: rgba(245, 158, 11, 0.06);
}

/* Value type styling (tactical palette) */
td .null  { color: var(--text-dim); font-style: italic; }
td .bool  { color: #a78bfa; font-weight: 600; }
td .num   { color: #60a5fa; }
td .str   { color: #4ade80; }
td .list  { color: var(--accent); font-size: 0.75rem; }
td .dict  { color: #f472b6; font-size: 0.75rem; }

/* ── Assets section ───────────────────────────────────────────────── */
.asset-item {
  display: inline-block;
  background: var(--bg-elevated);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 0.3rem 0.7rem;
  margin: 0.2rem;
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--text-secondary);
  transition: border-color 0.12s var(--ease-out);
}
.asset-item:hover {
  border-color: var(--accent-dim);
}

/* ── Empty state ──────────────────────────────────────────────────── */
.empty {
  padding: 1.5rem;
  text-align: center;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--text-muted);
  letter-spacing: 0.06em;
}

/* ═══════════════════════════ FOOTER ═══════════════════════════ */
footer {
  font-family: var(--font-mono);
  text-align: center;
  padding: 1.5rem;
  color: var(--text-dim);
  font-size: 0.7rem;
  letter-spacing: 0.06em;
  border-top: 1px solid var(--border-subtle);
  margin-top: 2rem;
}

/* ── Animations ───────────────────────────────────────────────────── */
@keyframes fade-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Responsive ───────────────────────────────────────────────────── */
@media (max-width: 768px) {
  html { font-size: 14px; }
  body::before { background-size: 32px 32px; }
  header { padding: 1.2rem 1rem 1rem; }
  main   { padding: 1rem 0.8rem 2rem; }
}

@media (max-width: 480px) {
  html { font-size: 13px; }
}
"""

# A set of common keys that get their own column early
PRIORITY_KEYS = {"key", "name", "type", "class", "value", "description"}

# ── Project root marker (icon.svg shipped alongside) ───────────────────────
_ICON_SRC: Optional[Path] = None


def _resolve_icon_src() -> Optional[Path]:
    """Locate icon.svg next to this module, falling back to project root."""
    global _ICON_SRC
    if _ICON_SRC is not None:
        return _ICON_SRC if _ICON_SRC.exists() else None

    candidates = [
        Path(__file__).resolve().parent.parent / "icon.svg",  # project root
        Path.cwd() / "icon.svg",
    ]
    for p in candidates:
        if p.exists():
            _ICON_SRC = p
            return p
    return None


def _format_value(val: Any) -> str:
    """Return an HTML-safe string representation of a value."""
    if val is None:
        return '<span class="null">--</span>'
    if isinstance(val, bool):
        return f'<span class="bool">{"true" if val else "false"}</span>'
    if isinstance(val, (int, float)):
        return f'<span class="num">{val}</span>'
    if isinstance(val, list):
        return f'<span class="list">[{len(val)} items]</span>'
    if isinstance(val, dict):
        return f'<span class="dict' + '">' + f'{"{"}{len(val)} keys{"}"}</span>'
    s = html.escape(str(val))
    if len(s) > 120:
        s = s[:117] + "..."
    return f'<span class="str">{s}</span>'


def _collect_keys(items: List[Dict[str, Any]]) -> List[str]:
    """Collect unique keys from a list of item dicts, with priority keys first."""
    seen: set[str] = set()
    ordered: List[str] = []
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
    """Build an HTML <table> from a list of item dicts."""
    if not items:
        return '<div class="empty">NO ITEMS</div>'

    thead = "<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in columns) + "</tr>"
    rows = [
        "<tr>" + "".join(f"<td>{_format_value(item.get(c))}</td>" for c in columns) + "</tr>"
        for item in items
    ]

    return (
        '<div class="table-wrap"><table>'
        f"<thead>{thead}</thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def generate(
    out_dir: Path,
    to_dump: Union[List[Dict[str, Any]], Dict[str, Dict[str, Dict[str, Any]]]],
    entity_counts: Dict[str, int],
    metadata: Dict[str, Any],
    asset_map: Optional[Dict[str, str]] = None,
) -> None:
    """Generate dist/index.html — tactical dark static data browser.

    Also copies icon.svg into dist/ for the favicon.
    """

    # ── Copy icon.svg ─────────────────────────────────────────────────────
    icon_src = _resolve_icon_src()
    if icon_src:
        icon_dst = out_dir / "icon.svg"
        try:
            shutil.copy2(icon_src, icon_dst)
            logger.debug(f"Copied icon.svg → {icon_dst}")
        except Exception as e:
            logger.warning(f"Failed to copy icon.svg: {e}")

    # ── Normalise entity data ─────────────────────────────────────────────
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
        for item in to_dump:
            etype = item.get("type", "unknown")
            entity_items.setdefault(etype, []).append(item)

    # ── Build HTML ────────────────────────────────────────────────────────
    lines: List[str] = []

    # doctype + head
    lines.append("<!DOCTYPE html>")
    lines.append('<html lang="en">')
    lines.append("<head>")
    lines.append('<meta charset="UTF-8">')
    lines.append('<link rel="icon" type="image/svg+xml" href="icon.svg">')
    lines.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    lines.append('<meta name="color-scheme" content="dark">')
    lines.append("<title>RWROPS — Data Index</title>")

    # Google Fonts
    lines.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    lines.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    lines.append(
        '<link href="https://fonts.googleapis.com/css2?'
        'family=Rajdhani:wght@400;500;600;700&'
        'family=Share+Tech+Mono&display=swap" rel="stylesheet">'
    )

    lines.append(f"<style>{CSS}</style>")
    lines.append("</head>")
    lines.append("<body>")

    # ── Header ────────────────────────────────────────────────────────────
    ts = metadata.get("timestamp", datetime.now(timezone.utc).isoformat())
    cfg = metadata.get("config_file", "?")

    lines.append("<header>")
    lines.append('  <img class="header-icon" src="icon.svg" alt="RWROPS" width="48" height="48">')
    lines.append('  <div class="header-text">')
    lines.append("    <h1>RWROPS DATA INDEX</h1>")
    lines.append('    <div class="header-meta">')
    lines.append(f"      <span>GENERATED {html.escape(ts)}</span>")
    lines.append(f"      <span>CONFIG {html.escape(str(cfg))}</span>")
    lines.append("    </div>")
    lines.append("  </div>")
    lines.append("</header>")
    lines.append('<div class="header-accent-line"></div>')

    lines.append("<main>")

    # ── Summary cards ─────────────────────────────────────────────────────
    lines.append('<h2 class="section-title">ENTITY SUMMARY</h2>')
    lines.append('<div class="summary">')
    if entity_counts:
        for etype, count in sorted(entity_counts.items()):
            lines.append('  <div class="summary-card">')
            lines.append(f'    <div class="count">{count}</div>')
            lines.append(f'    <div class="label">{html.escape(etype)}</div>')
            lines.append("  </div>")
    else:
        lines.append('<div class="empty">NO ENTITIES FOUND</div>')
    lines.append("</div>")

    # ── Entity detail accordions ──────────────────────────────────────────
    lines.append('<h2 class="section-title">ENTITIES</h2>')
    if entity_items:
        for etype in sorted(entity_items.keys()):
            items = entity_items[etype]
            all_keys = _collect_keys(items)
            lines.append("<details>")
            lines.append(
                f"  <summary>{html.escape(etype)} "
                f"<small>({len(items)} ITEMS)</small></summary>"
            )
            lines.append(f"  {_build_table(items, all_keys)}")
            lines.append("</details>")
    else:
        lines.append('<div class="empty">NO ENTITY DATA</div>')

    # ── Assets ─────────────────────────────────────────────────────────────
    if asset_map:
        lines.append('<h2 class="section-title">ASSETS</h2>')
        lines.append("<div>")
        for _rel_path, dest_name in sorted(asset_map.items()):
            name = html.escape(dest_name)
            lines.append(f'<span class="asset-item">{name}</span>')
        lines.append("</div>")

    lines.append("</main>")

    # ── Footer ────────────────────────────────────────────────────────────
    total_entities = sum(entity_counts.values()) if entity_counts else 0
    lines.append("<footer>")
    lines.append(
        f"  RWROPS &copy; {datetime.now().year} &mdash; "
        f"{total_entities} ENTITIES ACROSS {len(entity_items)} TYPES"
    )
    lines.append("</footer>")

    lines.append("</body>")
    lines.append("</html>")

    html_content = "\n".join(lines) + "\n"

    index_path = out_dir / "index.html"
    index_path.write_text(html_content, encoding="utf-8")
    logger.info(f"Wrote index.html ({index_path.stat().st_size:,} bytes)")
