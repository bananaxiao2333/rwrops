# RWR Ops - RWR Data Parser

A flexible and extensible XML data parser for RWR (Running With Rifles) game files that extracts structured data from vehicle, weapon, and other entity configurations.

## Overview

RWR Ops automatically scans directories for XML configuration files, parses them according to user-defined rules in YAML configuration files, and outputs normalized JSON data. The system supports:

- **Dynamic entity recognition** - Automatically identifies different entity types based on XML root elements
- **Hierarchical data extraction** - Extracts nested structures while maintaining relationships
- **Data transformation** - Converts strings to appropriate data types (float, int, bool, vectors)
- **Inheritance support** - Handles base/derived entity relationships through `inherit_from` references
- **Attribute flattening** - Optional normalization of nested attributes to root level
- **Multi-entity support** - Single configuration can handle multiple entity types (vehicles, weapons, etc.)

## Architecture

The system follows a clean separation of concerns:

1. **File Discovery**: Recursively scans configured directories for XML files
2. **Entity Recognition**: Matches XML root elements against configured selectors
3. **Structured Parsing**: Extracts data according to hierarchical configuration rules
4. **Data Transformation**: Applies type conversions and vector parsing
5. **Inheritance Resolution**: Loads and merges base entity data when referenced
6. **Output Generation**: Produces normalized JSON output

## Configuration File Structure

Configuration files use YAML format and define how to parse different entity types. Here's the complete structure:

### Root Level Configuration

```yaml
# Required: Directories to scan for XML files
package_path:
  - "C:\\path\\to\\your\\rwr\\data"

# Output options
output_format: "json" # Currently only JSON is supported
pretty_print: true # Pretty-print JSON output
include_source: false # Include source file paths in output

# Inheritance settings
defaults:
  inherit_enabled: true # Enable inheritance processing
  base_attr: "file" # XML attribute name that contains base file reference

# Entity definitions
entities:
  # Each entity type is defined here
  vehicle:
    # ... vehicle configuration ...
  weapon:
    # ... weapon configuration ...
```

### Entity Configuration

Each entity type defines how to extract data from matching XML elements:

```yaml
entities:
  vehicle: # Entity name (arbitrary identifier)
    selector: "vehicle" # XML root element tag to match
    name: "vehicle" # Output key name for this entity
    is_array: false # Whether multiple instances are expected

    # Attributes to extract from the root element
    attributes:
      - source: "@name" # XML attribute (prefixed with @)
        target: "name" # Output field name
        # Optional: flatten_to_root: true  # Place at root level (see below)

      - source: "@respawn_time"
        target: "respawn_time"
        transform: "to_float" # Apply data transformation

      - source: "@extent"
        target: "extent"
        transform: "parse_vector3" # Parse "x y z" to [x, y, z]

    # Nested child elements
    children:
      control:
        selector: "control" # Child XML element tag
        name: "control" # Output key name
        is_array: false # Single instance expected

        attributes:
          - source: "@max_speed"
            target: "max_speed"
            transform: "to_float"
            flatten_to_root: true # This will appear at entity root level!
```

### Supported Transform Types

| Transform       | Description               | Example Input → Output              |
| --------------- | ------------------------- | ----------------------------------- |
| `to_float`      | Convert string to float   | `"123.45"` → `123.45`               |
| `to_int`        | Convert string to integer | `"42"` → `42`                       |
| `to_bool`       | Convert to boolean        | `"true"` → `true`, `"1"` → `true`   |
| `parse_vector3` | Parse 3D vector           | `"1.0 2.0 3.0"` → `[1.0, 2.0, 3.0]` |
| `parse_vector2` | Parse 2D vector           | `"10 20"` → `[10.0, 20.0]`          |

### Attribute Flattening (`flatten_to_root`)

By default, attributes are nested within their parent structure. However, you can use the `flatten_to_root: true` flag to place any attribute directly at the entity's root level, regardless of where it's defined in the hierarchy.

**Example:**

```yaml
children:
  specification:
    selector: "specification"
    attributes:
      - source: "@class"
        target: "class"
        flatten_to_root: true # Appears at root, not under "specification"
      - source: "@name"
        target: "display_name" # Stays nested under "specification"
```

**Result:**

```json
{
  "class": "rifle", // Flattened to root
  "specification": {
    "display_name": "AK-47" // Remains nested
  }
}
```

### Special Source Types

- **`@attribute_name`**: Extract XML attribute value
- **`#text`**: Extract text content between XML tags
- **Child element paths**: Use nested `children` configuration for complex hierarchies

## Usage

### 1. Install Dependencies

Ensure you have Python 3.7+ installed, then install required packages:

```bash
pip install beautifulsoup4 pyyaml tqdm chardet
```

### 2. Configure Your Setup

1. Edit `config/core.yaml` to point to your RWR data directory:

   ```yaml
   package_path:
     - "C:\\Program Files\\RWR\\data" # Your actual RWR data path
   ```

2. Customize entity configurations as needed for your use case

### 3. Run the Parser

```bash
python main.py
```

The system will:

- Scan all subdirectories in your configured `package_path`
- Identify XML files containing vehicle, weapon, or other configured entities
- Parse and normalize the data according to your configuration
- Output JSON results to stdout

### 4. Example Output

For a vehicle configuration, you might get:

```json
[
  {
    "name": "T-72",
    "key": "t72",
    "inherit_from": "tank_base.vehicle",
    "respawn_time": 120.0,
    "control": {
      "max_speed": 60.0,
      "acceleration": 2.5
    },
    "type": "vehicle"
  }
]
```

## Advanced Features

### Inheritance Handling

When `inherit_enabled: true`, the system automatically:

1. Looks for the `inherit_from` field (mapped from `@file` attribute by default)
2. Loads the referenced base file
3. Merges base entity data into the current entity (current entity values take precedence)
4. Logs warnings if referenced files cannot be found

### Error Handling

- **Missing inheritance files**: Logged as WARNING, processing continues
- **Invalid transform values**: Original string value is preserved
- **Malformed XML**: File is skipped with error logging
- **Unknown entity types**: Ignored (only configured entities are processed)

## Customization

To add support for new entity types:

1. Add a new entry under `entities` in your YAML config
2. Define the `selector` to match the XML root element
3. Configure `attributes` and `children` as needed
4. Use `flatten_to_root: true` for attributes that should be normalized to root level

The system is designed to be easily extensible without code changes - most customization happens through configuration files.

## Troubleshooting

**Problem**: New entity type not being parsed

- **Solution**: Verify the `selector` matches the exact XML root element tag name

**Problem**: Attributes not appearing in output

- **Solution**: Check that XML actually contains the specified attributes; verify transform types match data format

**Problem**: Inheritance files not found

- **Solution**: Ensure referenced files exist in the configured `package_path` directories

**Problem**: Encoding issues with non-ASCII characters

- **Solution**: The system automatically detects file encoding using chardet

## License

This project is open source and available under the MIT License.
