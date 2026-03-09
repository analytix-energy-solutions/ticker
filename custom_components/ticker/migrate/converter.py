"""Conversion functions for migration module."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

from ..const import DOMAIN, MIGRATE_SOURCE_AUTOMATION
from .common import read_yaml_file, slugify, write_yaml_file

_LOGGER = logging.getLogger(__name__)


async def async_convert_notification(
    hass: HomeAssistant,
    finding: dict[str, Any],
    category_id: str,
    category_name: str,
    apply_directly: bool = False,
    title: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """
    Convert a notification finding to use ticker.notify.

    Returns:
        Dict with success, yaml, applied, error
    """
    old_service_data = finding.get("service_data", {})

    # Use custom title/message if provided, otherwise fall back to original
    final_title = title if title is not None else old_service_data.get("title", "Notification")
    final_message = message if message is not None else old_service_data.get("message", "")

    # Build replacement action
    new_action = {
        "service": f"{DOMAIN}.notify",
        "data": {
            "category": category_name,
            "title": final_title,
            "message": final_message,
        }
    }

    # Preserve alias if present
    if finding.get("action_alias"):
        new_action["alias"] = finding["action_alias"]

    # Preserve extra data fields
    extra_data = {k: v for k, v in old_service_data.items() if k not in ("title", "message")}
    if extra_data:
        new_action["data"]["data"] = extra_data

    # Generate YAML
    yaml_str = yaml.dump(new_action, default_flow_style=False, allow_unicode=True, sort_keys=False)

    result = {
        "success": True,
        "yaml": yaml_str,
        "new_action": new_action,
        "applied": False,
        "error": None,
    }

    if apply_directly:
        try:
            if finding["source_type"] == MIGRATE_SOURCE_AUTOMATION:
                await _apply_to_automation(hass, finding, new_action)
            else:
                await _apply_to_script(hass, finding, new_action)
            result["applied"] = True
            _LOGGER.info("Converted %s to ticker.notify (category: %s)", finding["source_id"], category_name)
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
            _LOGGER.error("Failed to apply conversion: %s", e)

    return result


async def _apply_to_automation(
    hass: HomeAssistant,
    finding: dict[str, Any],
    new_action: dict[str, Any],
) -> None:
    """Apply conversion to an automation."""
    source_file = finding.get("source_file", "")

    # Check if it's a UI-created automation (.storage)
    if ".storage" in source_file:
        await _apply_to_ui_automation(hass, finding, new_action)
    else:
        # YAML-based automation
        await _apply_to_yaml_file(hass, finding, new_action, "automation")


async def _apply_to_ui_automation(
    hass: HomeAssistant,
    finding: dict[str, Any],
    new_action: dict[str, Any],
) -> None:
    """Apply conversion to a UI-created automation."""
    from homeassistant.helpers.storage import Store

    store = Store(hass, 5, "automation.config")
    data = await store.async_load()

    if not data or "items" not in data:
        raise ValueError("Automation not found in UI storage.")

    source_id = finding["source_id"]
    auto_id = source_id.replace("automation.", "")

    automation = None
    auto_index = None
    for idx, item in enumerate(data["items"]):
        item_id = item.get("id", "")
        item_alias = item.get("alias", "")
        if item_id == auto_id or slugify(item_alias) == auto_id:
            automation = item
            auto_index = idx
            break

    if automation is None:
        raise ValueError(f"Automation '{source_id}' not found in UI storage.")

    # Apply the change
    action_path = finding["action_path"]
    action_index = finding["action_index"]

    # Determine which key the automation uses (actions or action)
    action_key = "actions" if "actions" in automation else "action"

    if action_path == f"[{action_index}]":
        actions = automation.get(action_key, [])
        if not isinstance(actions, list):
            actions = [actions]
        if action_index < len(actions):
            actions[action_index] = new_action
            automation[action_key] = actions
    else:
        _apply_at_path(automation, action_path, new_action, key=action_key)

    data["items"][auto_index] = automation
    await store.async_save(data)
    await hass.services.async_call("automation", "reload")


async def _apply_to_script(
    hass: HomeAssistant,
    finding: dict[str, Any],
    new_action: dict[str, Any],
) -> None:
    """Apply conversion to a script."""
    source_file = finding.get("source_file", "")

    # Check if it's a UI-created script (.storage)
    if ".storage" in source_file:
        await _apply_to_ui_script(hass, finding, new_action)
    else:
        # YAML-based script
        await _apply_to_yaml_file(hass, finding, new_action, "script")


async def _apply_to_yaml_file(
    hass: HomeAssistant,
    finding: dict[str, Any],
    new_action: dict[str, Any],
    entity_type: str,
) -> None:
    """
    Apply conversion to a YAML file.

    Creates a timestamped backup before modifying.
    """
    from datetime import datetime
    import shutil

    source_file = finding.get("source_file", "")
    if not source_file:
        raise ValueError("No source file information available.")

    # Convert relative path to absolute
    # source_file is like "config/automations.yaml" - need to get actual path
    config_dir = Path(hass.config.config_dir)

    # Remove "config/" prefix if present
    if source_file.startswith("config/"):
        relative_path = source_file[7:]  # Remove "config/"
    else:
        relative_path = source_file

    file_path = config_dir / relative_path

    if not file_path.exists():
        raise ValueError(f"Source file not found: {file_path}")

    # Create backup directory
    backup_dir = config_dir / "ticker_migration_backups"
    backup_dir.mkdir(exist_ok=True)

    # Create timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{file_path.name}.{timestamp}"
    backup_path = backup_dir / backup_filename

    await hass.async_add_executor_job(shutil.copy2, file_path, backup_path)
    _LOGGER.info("Created backup: %s", backup_path)

    # Read the YAML file
    content = await hass.async_add_executor_job(read_yaml_file, file_path)

    # Find and modify the correct item
    source_id = finding["source_id"]
    action_path = finding["action_path"]
    action_index = finding["action_index"]

    if entity_type == "automation":
        # automations.yaml is a list
        if isinstance(content, list):
            auto_id = source_id.replace("automation.", "")
            for auto in content:
                if not isinstance(auto, dict):
                    continue
                item_id = auto.get("id", "")
                item_alias = auto.get("alias", "")
                if item_id == auto_id or slugify(item_alias) == auto_id:
                    # Determine which key the automation uses (actions or action)
                    action_key = "actions" if "actions" in auto else "action"
                    _apply_action_to_item(auto, action_path, action_index, new_action, action_key)
                    break
            else:
                raise ValueError(f"Automation '{source_id}' not found in {file_path}")
        else:
            raise ValueError(f"Expected list in {file_path}, got {type(content)}")

    elif entity_type == "script":
        script_id = source_id.replace("script.", "")
        # scripts.yaml is a dict
        if isinstance(content, dict):
            if script_id in content:
                _apply_action_to_item(content[script_id], action_path, action_index, new_action, "sequence")
            else:
                raise ValueError(f"Script '{script_id}' not found in {file_path}")
        else:
            raise ValueError(f"Expected dict in {file_path}, got {type(content)}")

    # Write back to file
    await hass.async_add_executor_job(write_yaml_file, file_path, content)

    # Reload
    await hass.services.async_call(entity_type, "reload")
    _LOGGER.info("Applied migration to %s and reloaded %ss", file_path, entity_type)


def _apply_action_to_item(
    item: dict[str, Any],
    action_path: str,
    action_index: int,
    new_action: dict[str, Any],
    key: str,
) -> None:
    """Apply new action to an item at the specified path."""
    if action_path == f"[{action_index}]":
        # Simple top-level action
        actions = item.get(key, [])
        if not isinstance(actions, list):
            actions = [actions]
        if action_index < len(actions):
            actions[action_index] = new_action
            item[key] = actions
    else:
        # Nested path
        _apply_at_path(item, action_path, new_action, key=key)


async def _apply_to_ui_script(
    hass: HomeAssistant,
    finding: dict[str, Any],
    new_action: dict[str, Any],
) -> None:
    """Apply conversion to a UI-created script."""
    from homeassistant.helpers.storage import Store

    store = Store(hass, 5, "script.config")
    data = await store.async_load()

    if not data or "items" not in data:
        raise ValueError("Script not found in UI storage.")

    source_id = finding["source_id"]
    script_id = source_id.replace("script.", "")

    script = None
    script_index = None
    for idx, item in enumerate(data["items"]):
        if item.get("id", "") == script_id:
            script = item
            script_index = idx
            break

    if script is None:
        raise ValueError(f"Script '{source_id}' not found in UI storage.")

    action_path = finding["action_path"]
    action_index = finding["action_index"]

    if action_path == f"[{action_index}]":
        sequence = script.get("sequence", [])
        if not isinstance(sequence, list):
            sequence = [sequence]
        if action_index < len(sequence):
            sequence[action_index] = new_action
            script["sequence"] = sequence
    else:
        _apply_at_path(script, action_path, new_action, key="sequence")

    data["items"][script_index] = script
    await store.async_save(data)
    await hass.services.async_call("script", "reload")


def _apply_at_path(
    obj: dict[str, Any],
    path: str,
    new_value: dict[str, Any],
    key: str = "action",
) -> None:
    """Navigate to a nested path and apply new value."""
    import re

    segments = re.findall(r'\[(\d+)\]|\.(\w+)', path)

    # Support both 'actions' and 'action' keys with provided key taking precedence
    current = obj.get(key) or obj.get("actions") or obj.get("action", [])

    for i, segment in enumerate(segments):
        idx_str, key_str = segment

        if i == len(segments) - 1:
            # Last segment - apply here
            if idx_str:
                idx = int(idx_str)
                if isinstance(current, list) and idx < len(current):
                    current[idx] = new_value
            return

        if idx_str:
            idx = int(idx_str)
            if isinstance(current, list) and idx < len(current):
                current = current[idx]
        elif key_str:
            if isinstance(current, dict) and key_str in current:
                current = current[key_str]
