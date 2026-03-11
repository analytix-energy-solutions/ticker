"""Common utilities for migration module."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def slugify(text: str) -> str:
    """Create a slug from text."""
    import re
    text = str(text).lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text


def normalize_to_list(content: Any) -> list:
    """Normalize content to a list."""
    if content is None:
        return []
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        return [content]
    return []


def read_yaml_file(path: Path) -> Any:
    """Read and parse a YAML file, handling !include and other HA-specific tags."""

    # Custom loader that ignores HA-specific tags
    class SafeLineLoader(yaml.SafeLoader):
        pass

    # Handle !include, !include_dir_list, !secret, etc. by returning None/empty
    def ignore_tag(loader, tag_suffix, node):
        return None

    def include_handler(loader, node):
        return None

    def secret_handler(loader, node):
        return f"!secret {node.value}"

    # Register handlers for common HA tags
    SafeLineLoader.add_constructor('!include', include_handler)
    SafeLineLoader.add_constructor('!include_dir_list', include_handler)
    SafeLineLoader.add_constructor('!include_dir_merge_list', include_handler)
    SafeLineLoader.add_constructor('!include_dir_named', include_handler)
    SafeLineLoader.add_constructor('!include_dir_merge_named', include_handler)
    SafeLineLoader.add_constructor('!secret', secret_handler)
    SafeLineLoader.add_constructor('!env_var', include_handler)

    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=SafeLineLoader)


def write_yaml_file(path: Path, content: Any) -> None:
    """Write content to a YAML file."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(content, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
