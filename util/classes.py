from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict, model_validator
import os
from enum import Enum


class TransformType(Enum):
    TO_FLOAT = "to_float"
    TO_INT = "to_int"
    TO_BOOL = "to_bool"
    PARSE_VECTOR3 = "parse_vector3"
    PARSE_VECTOR2 = "parse_vector2"


class AttributeMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')

    source: str
    target: str
    transform: Optional[TransformType] = None
    flatten_to_root: bool = False
    unique: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AttributeMapping':
        transform_str = data.get('transform')
        transform = TransformType(transform_str) if transform_str else None
        flatten_to_root = data.get('flatten_to_root', False)
        unique = data.get('unique', False)
        return cls(
            source=data['source'],
            target=data['target'],
            transform=transform,
            flatten_to_root=flatten_to_root,
            unique=unique
        )


class DeriveField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: str
    pattern: str


class EntityConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    selector: str
    name: str
    is_array: bool
    must_have_attr: Optional[List[str]] = None
    key_from_path: Optional[str] = None
    derive_fields: List[DeriveField] = Field(default_factory=list)
    attributes: List[AttributeMapping] = Field(default_factory=list)
    children: Dict[str, 'EntityConfig'] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EntityConfig':
        selector = data.get('selector', '')
        name = data.get('name', '')
        is_array = data.get('is_array', False)

        attributes = []
        for attr_data in data.get('attributes', []):
            attributes.append(AttributeMapping.from_dict(attr_data))

        children = {}
        for child_name, child_data in data.get('children', {}).items():
            children[child_name] = cls.from_dict(child_data)

        must_have_attr = data.get('must_have_attr')
        key_from_path = data.get('key_from_path')
        derive_fields = [DeriveField(**d) for d in data.get('derive_fields', [])]

        return cls(
            selector=selector,
            name=name,
            is_array=is_array,
            must_have_attr=must_have_attr,
            key_from_path=key_from_path,
            derive_fields=derive_fields,
            attributes=attributes,
            children=children
        )


class SortConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')

    enable: bool = False
    primarykey: str = 'key'


class Config(BaseModel):
    model_config = ConfigDict(extra='forbid')

    CONFIGFILE: str
    package_path: List[str]
    output_format: str
    pretty_print: bool
    include_source: bool
    generate_index_html: bool = True
    sort: SortConfig

    plugin_paths: List[str] = Field(default_factory=list)

    @field_validator('plugin_paths', mode='before')
    @classmethod
    def default_empty_list(cls, v: Any) -> List[str]:
        return v or []

    defaults: Dict[str, Any] = Field(default_factory=dict)
    entities: Dict[str, EntityConfig] = Field(default_factory=dict)
    must_have_attr: List[str] = Field(default_factory=list)
    exclude_patterns: List[str] = Field(default_factory=list)

    @model_validator(mode='before')
    @classmethod
    def convert_entities_to_entity_config(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        if 'entities' in data and isinstance(data['entities'], dict):
            converted_entities = {}
            for entity_name, entity_data in data['entities'].items():
                if isinstance(entity_data, dict):
                    converted_entities[entity_name] = EntityConfig.from_dict(
                        entity_data)
                elif isinstance(entity_data, EntityConfig):
                    converted_entities[entity_name] = entity_data
                else:
                    raise ValueError(
                        f"Invalid entity configuration for {entity_name}")
            data['entities'] = converted_entities

        # 确保sort字段是SortConfig对象
        if 'sort' in data and isinstance(data['sort'], dict):
            data['sort'] = SortConfig(**data['sort'])

        return data

    @field_validator('package_path')
    @classmethod
    def path_must_exists(cls, v: List[str]) -> List[str]:
        for item in v:
            if not os.path.exists(item):
                raise RuntimeError(
                    f"target package path doesn't exists: {item}")
        return v

    def _entity_to_dict(self, entity: EntityConfig) -> Dict[str, Any]:
        result = {
            'selector': entity.selector,
            'name': entity.name,
            'is_array': entity.is_array
        }

        if entity.attributes:
            result['attributes'] = []
            for attr in entity.attributes:
                attr_dict = {
                    'source': attr.source,
                    'target': attr.target
                }
                if attr.transform:
                    attr_dict['transform'] = attr.transform.value
                if attr.flatten_to_root:
                    attr_dict['flatten_to_root'] = str(attr.flatten_to_root)
                if attr.unique:
                    attr_dict['unique'] = str(attr.unique)
                result['attributes'].append(attr_dict)

        if entity.children:
            result['children'] = {}
            for child_name, child_config in entity.children.items():
                result['children'][child_name] = self._entity_to_dict(
                    child_config)

        return result

    def get_entity_config(self, entity_name: str) -> Optional[EntityConfig]:
        return self.entities.get(entity_name)

    def get_child_config(self, parent_name: str, child_name: str) -> Optional[EntityConfig]:
        parent = self.get_entity_config(parent_name)
        if parent:
            return parent.children.get(child_name)
        return None


class Temp(BaseModel):
    model_config = ConfigDict(extra='forbid')

    res_file: List[str] = Field(default_factory=list)
    conf_file: List[str] = Field(default_factory=list)
    final: List[Dict[str, Any]] = Field(default_factory=list)
    sorted_final: Dict[str, Dict[str, Dict]] = Field(default_factory=dict)