import re
from bs4 import BeautifulSoup, Tag
import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from .classes import Config, Temp, TransformType, EntityConfig
from . import gate

logger = logging.getLogger(__name__)


def parse_file(content: BeautifulSoup, config: Config, temp: Temp, source_path: Optional[str] = None) -> Temp:
    """Parse XML content according to configuration and extract structured data."""
    cache = {}

    # Track unique values per (entity_type, attribute_name) combination
    unique_values: Dict[Tuple[str, str], Set[Any]] = {}

    # Get the correct base attribute field name from config
    base_attr_field = config.defaults.get('base_attr', 'inherit_from')

    # Process each entity type defined in the config
    for entity_name, entity_config in config.entities.items():
        # Handle both dictionary and EntityConfig objects
        if isinstance(entity_config, dict):
            # Convert dictionary to EntityConfig object
            entity_config_obj = EntityConfig.from_dict(entity_config)
        else:
            entity_config_obj = entity_config

        # Find root-level elements matching the selector
        # Strategy: only match the document root element when it IS the entity type,
        # to avoid picking up <call> stubs inside <resources>/<calls>/<map_config> etc.
        # Exception: <achievements> is a known container for <achievement> children.
        doc_root = content.find()
        if doc_root is not None and doc_root.name == entity_config_obj.selector:
            root_elements = [doc_root]
        elif doc_root is not None:
            # Container root: if root name ends with entity selector + "s", search children
            container_root = doc_root.name
            selector = entity_config_obj.selector
            if container_root == selector + "s":
                root_elements = doc_root.find_all(selector, recursive=False)
            else:
                root_elements = []
        else:
            root_elements = []

        for root_element in root_elements:
            # Parse the entity with its configuration
            entity_data, root_level_attrs = parse_entity(
                root_element, entity_config_obj, config, cache)

            # Merge root-level flattened attributes
            for key, value in root_level_attrs.items():
                entity_data[key] = value

            # Handle inheritance if enabled
            if config.defaults.get('inherit_enabled', False):
                # Resolve full inheritance chain recursively using the correct base field
                entity_data = resolve_inheritance_chain(
                    entity_data, config, entity_config_obj.selector, cache, logger, set(), base_attr_field)

            # Apply uniqueness constraints
            entity_data = apply_uniqueness_constraints(
                entity_data, entity_config_obj, entity_name, unique_values, logger)

            if entity_data is not None:  # Only add if not filtered out by uniqueness
                # Skip self-referencing entities (inherit_from == key)
                if base_attr_field in entity_data and "key" in entity_data:
                    if entity_data[base_attr_field] == entity_data["key"]:
                        # logger.debug(f"Skipping self-referencing entity: {entity_data['key']}")
                        continue

                # Extract key from file path if entity has key_from_path regex
                if entity_config_obj.key_from_path and source_path:
                    match = re.search(entity_config_obj.key_from_path, source_path)
                    if match:
                        entity_data['key'] = match.group(1)
                        entity_data['locale'] = match.group(1)

                # Validate required attributes: entity-level override, else global default
                must_have_attrs = entity_config_obj.must_have_attr if entity_config_obj.must_have_attr is not None else config.defaults.get('must_have_attr', [])
                missing_attrs = []
                for attr_name in must_have_attrs:
                    if attr_name not in entity_data or entity_data[attr_name] is None or entity_data[attr_name] == "":
                        missing_attrs.append(attr_name)

                if missing_attrs:
                    # logger.warning(f"Entity missing required attributes {missing_attrs}, skipping: {entity_data.get('key', 'unknown')}")
                    continue

                # Apply derive_fields: pattern-based field generation
                if entity_config_obj.derive_fields:
                    for df in entity_config_obj.derive_fields:
                        try:
                            resolved = df.pattern.format(**entity_data)
                            entity_data[df.target] = resolved.replace("\\", "_").replace("/", "_")
                        except KeyError:
                            pass  # skip if template vars missing

                # Add type information
                entity_data["type"] = entity_config_obj.name
                temp.final.append(entity_data)

    return temp


def apply_uniqueness_constraints(entity_data: Dict[str, Any], entity_config: EntityConfig, entity_name: str, unique_values: Dict[Tuple[str, str], Set[Any]], logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """Apply uniqueness constraints to entity data. Returns None if entity should be discarded due to duplicates."""

    # Check root-level attributes for uniqueness
    for attr_mapping in entity_config.attributes:
        if attr_mapping.unique and attr_mapping.target in entity_data:
            value = entity_data[attr_mapping.target]
            key = (entity_name, attr_mapping.target)

            if key not in unique_values:
                unique_values[key] = set()

            # Convert value to string for hashing if it's not hashable
            try:
                if value in unique_values[key]:
                    logger.warning(
                        f"Duplicate value '{value}' found for {entity_name}.{attr_mapping.target}, discarding entity")
                    return None
                unique_values[key].add(value)
            except TypeError:
                # Handle unhashable types (like lists/dicts) by converting to string
                value_str = str(value)
                if value_str in unique_values[key]:
                    logger.warning(
                        f"Duplicate value '{value}' found for {entity_name}.{attr_mapping.target}, discarding entity")
                    return None
                unique_values[key].add(value_str)

    # Check nested attributes for uniqueness
    def check_nested_uniqueness(data: Dict[str, Any], parent_config: EntityConfig, current_entity_name: str):
        """Recursively check nested structures for uniqueness constraints."""
        for child_name, child_config in parent_config.children.items():
            if child_name in data:
                child_data = data[child_name]
                if isinstance(child_data, list):
                    # Array of children
                    for item in child_data:
                        if isinstance(item, dict):
                            # Check uniqueness for this child item
                            for attr_mapping in child_config.attributes:
                                if attr_mapping.unique and attr_mapping.target in item:
                                    value = item[attr_mapping.target]
                                    key = (
                                        f"{current_entity_name}.{child_name}", attr_mapping.target)

                                    if key not in unique_values:
                                        unique_values[key] = set()

                                    try:
                                        if value in unique_values[key]:
                                            logger.warning(
                                                f"Duplicate value '{value}' found for {current_entity_name}.{child_name}.{attr_mapping.target}, discarding entity")
                                            return False
                                        unique_values[key].add(value)
                                    except TypeError:
                                        value_str = str(value)
                                        if value_str in unique_values[key]:
                                            logger.warning(
                                                f"Duplicate value '{value}' found for {current_entity_name}.{child_name}.{attr_mapping.target}, discarding entity")
                                            return False
                                        unique_values[key].add(value_str)

                            # Recursively check deeper nesting
                            if not check_nested_uniqueness(item, child_config, current_entity_name):
                                return False
                elif isinstance(child_data, dict):
                    # Single child object
                    for attr_mapping in child_config.attributes:
                        if attr_mapping.unique and attr_mapping.target in child_data:
                            value = child_data[attr_mapping.target]
                            key = (f"{current_entity_name}.{child_name}",
                                   attr_mapping.target)

                            if key not in unique_values:
                                unique_values[key] = set()

                            try:
                                if value in unique_values[key]:
                                    logger.warning(
                                        f"Duplicate value '{value}' found for {current_entity_name}.{child_name}.{attr_mapping.target}, discarding entity")
                                    return False
                                unique_values[key].add(value)
                            except TypeError:
                                value_str = str(value)
                                if value_str in unique_values[key]:
                                    logger.warning(
                                        f"Duplicate value '{value}' found for {current_entity_name}.{child_name}.{attr_mapping.target}, discarding entity")
                                    return False
                                unique_values[key].add(value_str)

                    # Recursively check deeper nesting
                    if not check_nested_uniqueness(child_data, child_config, current_entity_name):
                        return False
        return True

    # Apply nested uniqueness checks
    if not check_nested_uniqueness(entity_data, entity_config, entity_name):
        return None

    return entity_data


def parse_entity(element: Tag, entity_config: EntityConfig, config: Config, cache: Dict) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Parse a single XML element according to entity configuration.
    Returns: (entity_data, root_level_attrs) where root_level_attrs contains attributes marked for root level"""
    entity_data = {}
    root_level_attrs = {}
    
    # Process attributes
    for attr_mapping in entity_config.attributes:
        source = attr_mapping.source
        target = attr_mapping.target
        transform = attr_mapping.transform
        flatten_to_root = attr_mapping.flatten_to_root
        
        # Handle nested path expressions (e.g., "turret/@max_rotation_step" or "projectile/result/@class")
        if "/" in source and not source.startswith("@") and not source == "#text":
            # This is a nested path expression
            value = extract_nested_value(element, source)
            if value is not None:
                processed_value = apply_transform(str(value), transform)
                if flatten_to_root:
                    root_level_attrs[target] = processed_value
                else:
                    entity_data[target] = processed_value
        elif source.startswith("@"):
            # Attribute extraction (e.g., "@name" -> element.get("name"))
            attr_name = source[1:]
            value = element.get(attr_name)
            if value is not None:
                # Convert to string to handle various attribute value types
                str_value = str(value) if value is not None else ""
                processed_value = apply_transform(str_value, transform)
                if flatten_to_root:
                    root_level_attrs[target] = processed_value
                else:
                    entity_data[target] = processed_value
        elif source == "#text":
            # Text content extraction
            text_value = element.get_text(strip=True)
            if text_value:
                processed_value = apply_transform(text_value, transform)
                if flatten_to_root:
                    root_level_attrs[target] = processed_value
                else:
                    entity_data[target] = processed_value

    # Process children
    for child_name, child_config in entity_config.children.items():
        # recursive=child_config.deep. When deep is False this returns only
        # direct children, so a <turret> sitting inside <character_slot> stops
        # being counted as a vehicle-level turret.
        child_elements = element.find_all(
            child_config.selector, recursive=child_config.deep)

        if child_config.is_array:
            # Multiple children - create array
            child_data_list = []
            for child_element in child_elements:
                child_data, child_root_attrs = parse_entity(
                    child_element, child_config, config, cache)
                # Merge child's root-level attributes into current root_level_attrs
                for key, value in child_root_attrs.items():
                    root_level_attrs[key] = value
                if child_data:  # Only add non-empty children
                    child_data_list.append(child_data)
            if child_data_list:
                entity_data[child_config.name] = child_data_list
            # A matched element that parses to {} is invisible in the output.
            # Usually legitimate, but it is also what silently hides a child
            # that was matched from the wrong parent. Counted, not ignored.
            gate.bump("child_dropped_empty", len(child_elements) - len(child_data_list))
        else:
            # Single child - take first match
            if child_elements:
                child_data, child_root_attrs = parse_entity(
                    child_elements[0], child_config, config, cache)
                # Merge child's root-level attributes into current root_level_attrs
                for key, value in child_root_attrs.items():
                    root_level_attrs[key] = value
                if child_data:
                    entity_data[child_config.name] = child_data
                else:
                    gate.bump("child_dropped_empty")

    return entity_data, root_level_attrs


def resolve_inheritance_chain(entity_data: Dict[str, Any], config: Config, entity_selector: str, cache: Dict, logger: logging.Logger, visited_files: set, base_attr_field: str = "inherit_from") -> Dict[str, Any]:
    """Recursively resolve inheritance chain for an entity."""
    if base_attr_field not in entity_data:
        return entity_data

    base_file = entity_data[base_attr_field]

    # Check for self-reference (base file references itself)
    # This is common for base/template files that have no actual parent
    if "key" in entity_data and base_file == entity_data["key"]:
        # Treat as base file with no inheritance
        return entity_data

    # Prevent infinite recursion due to circular references
    if base_file in visited_files:
        logger.warning(
            f"Circular inheritance detected: {base_file} already visited in chain")
        return entity_data

    # Add current file to visited set
    visited_files.add(base_file)

    # Load the base entity (which will also resolve its own inheritance)
    base_entity = load_base_entity_with_inheritance(
        base_file, config, entity_selector, cache, logger, visited_files.copy())

    if base_entity:
        # Merge base entity data (current entity values take precedence)
        merged_data = base_entity.copy()
        merged_data.update(entity_data)
        return merged_data
    else:
        # Log warning when inherit_from file is not found
        logger.warning(f"inherit_from file '{base_file}' not found for entity")
        return entity_data


def find_file_in_package_paths(filename: str, package_paths: List[str]) -> Optional[str]:
    """Recursively search for a file in all package paths and their subdirectories.

    Returns a *deterministic* hit and reports ambiguity. rglob used to return
    whichever match the filesystem happened to yield first, so a base file
    present in several directories silently merged the wrong parent.
    """
    for package_dir in package_paths:
        package_path = Path(package_dir)
        if not package_path.exists():
            continue

        # First, check if file exists directly in package root
        direct_path = package_path / filename
        if direct_path.exists():
            return str(direct_path)

        # Then, recursively search all subdirectories
        try:
            hits = sorted(str(p) for p in package_path.rglob(filename) if p.is_file())
        except (OSError, PermissionError) as e:
            logger.warning(
                "Error searching %s: %s", package_dir, e)
            continue

        if hits:
            if len(hits) > 1:
                logger.error(
                    "inherit_from '%s' matches %d files, using %s (others: %s)",
                    filename, len(hits), hits[0], hits[1:4])
                gate.bump("inherit_ambiguous")
            return hits[0]

    return None


def load_base_entity_with_inheritance(base_file: str, config: Config, entity_selector: str, cache: Dict, logger: logging.Logger, visited_files: set, base_attr_field: str = "inherit_from") -> Optional[Dict[str, Any]]:
    """Load and parse a base entity from file, including resolving its own inheritance."""
    # Try to find the base file in configured package paths (including subdirectories)
    base_path = find_file_in_package_paths(base_file, config.package_path)

    # Key the cache on the resolved path, not the bare filename: two different
    # files called tank.vehicle used to share one cache entry.
    cache_key = f"{base_path or base_file}:{entity_selector}"
    if cache_key in cache:
        return cache.get(cache_key)

    if base_path:
        try:
            with open(base_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'xml')

            # Find the entity configuration that matches this selector
            for entity_name, entity_config in config.entities.items():
                # Handle both dictionary and EntityConfig objects
                if isinstance(entity_config, dict):
                    current_selector = entity_config.get('selector', '')
                else:
                    current_selector = entity_config.selector

                if current_selector == entity_selector:
                    base_root = soup.find(entity_selector)
                    if base_root:
                        # Use the same conversion logic as in parse_file
                        if isinstance(entity_config, dict):
                            entity_config_obj = EntityConfig.from_dict(
                                entity_config)
                        else:
                            entity_config_obj = entity_config

                        base_entity_data, base_root_attrs = parse_entity(
                            base_root, entity_config_obj, config, cache)

                        # Merge root-level flattened attributes
                        for key, value in base_root_attrs.items():
                            base_entity_data[key] = value

                        # Resolve inheritance for the base entity as well
                        if config.defaults.get('inherit_enabled', False):
                            base_entity_data = resolve_inheritance_chain(
                                base_entity_data, config, entity_selector, cache, logger, visited_files, base_attr_field
                            )

                        cache[cache_key] = base_entity_data
                        return base_entity_data
        except Exception as e:
            logger.warning(
                f"Error loading base entity '{base_file}' from '{base_path}': {e}")

    # File not found in any package path
    cache[cache_key] = None
    return None


def apply_transform(value: str, transform: Optional[TransformType]) -> Any:
    """Apply transformation to a value based on transform type."""
    if transform is None:
        return value

    try:
        if transform == TransformType.TO_FLOAT:
            return float(value)
        elif transform == TransformType.TO_INT:
            return int(value)
        elif transform == TransformType.TO_BOOL:
            # Handle various boolean representations
            return value.lower() in ('true', '1', 'yes', 'on')
        elif transform == TransformType.PARSE_VECTOR3:
            # Parse "x y z" format to [x, y, z]
            parts = value.strip().split()
            if len(parts) == 3:
                return [float(part) for part in parts]
            else:
                return value  # Return original if format doesn't match
        elif transform == TransformType.PARSE_VECTOR2:
            # Parse "x y" format to [x, y]
            parts = value.strip().split()
            if len(parts) == 2:
                return [float(part) for part in parts]
            else:
                return value  # Return original if format doesn't match
    except (ValueError, AttributeError):
        # If transformation fails, return original value
        return value

    return value


def load_base_entity(base_file: str, config: Config, entity_selector: str, cache: Dict) -> Optional[Dict[str, Any]]:
    """Legacy function maintained for backward compatibility - now delegates to new implementation."""
    base_attr_field = config.defaults.get('base_attr', 'inherit_from')
    return load_base_entity_with_inheritance(base_file, config, entity_selector, cache, logger, set(), base_attr_field)


def extract_nested_value(root_element: Tag, path: str) -> Optional[str]:
    """Extract value from nested XML path like 'turret/@max_rotation_step' or 'projectile/result/@class'."""
    parts = path.split('/')
    current_elements = [root_element]
    
    # Navigate through element path
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            # Last part - this should be an attribute or text
            values = []
            for elem in current_elements:
                if elem is None:
                    continue
                if part.startswith("@"):
                    # Attribute extraction
                    attr_name = part[1:]
                    attr_value = elem.get(attr_name)
                    if attr_value is not None:
                        values.append(str(attr_value))
                elif part == "#text":
                    # Text content extraction
                    text_value = elem.get_text(strip=True)
                    if text_value:
                        values.append(text_value)
                else:
                    # Element name - return the element's text content
                    text_value = elem.get_text(strip=True)
                    if text_value:
                        values.append(text_value)
            
            # Return first value found (similar to current behavior for single elements)
            return values[0] if values else None
        else:
            # Intermediate element - find all matching elements at this level
            next_elements = []
            for elem in current_elements:
                if elem is None:
                    continue
                found_elements = elem.find_all(part)
                next_elements.extend(found_elements)
            
            if not next_elements:
                return None
            current_elements = next_elements
    
    return None