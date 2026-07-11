"""
Plugin system for RWR Ops.

A plugin is a folder containing:
  plugin.yaml    — optional plugin metadata and additional entity configs
  *.xml / other  — data files scanned alongside the main package

Plugin folder structure:
  plugins/my_plugin/
    plugin.yaml
    vehicles/
    weapons/
    ...

plugin.yaml example:
  name: "My Custom Content"
  version: "1.0"
  description: "Adds custom weapons and vehicles"
  
  # Entity configs to add or override
  entities:
    weapon:
      attributes:
        - source: "@my_custom_attr"
          target: "my_custom_attr"
"""

import logging
from pathlib import Path
from typing import Optional
import yaml


logger = logging.getLogger("Plugin")


def load_plugin_config(plugin_dir: Path) -> dict:
    """Load plugin.yaml from a plugin directory."""
    config_file = plugin_dir / "plugin.yaml"
    if not config_file.exists():
        return {}
    try:
        with open(config_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load plugin config {config_file}: {e}")
        return {}
