"""Deletion functions for migration module."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import MIGRATE_SOURCE_AUTOMATION
from .common import read_yaml_file, slugify, write_yaml_file

_LOGGER = logging.getLogger(__name__)


async def async_delete_notification(
    hass: HomeAssistant,
    finding: dict[str, Any],
) -> dict[str, Any]:
    """
    Delete a notification action from an automation or script.

    Returns:
        Dict with success, deleted, error
    """
    result = {
        "success": True,
        "deleted": False,
        "error": None,
    }

    try:
        if finding["source_type"] == MIGRATE_SOURCE_AUTOMATION:
            await _delete_from_automation(hass, finding)
        else:
            await _delete_from_script(hass, finding)
        result["deleted"] = True
        _LOGGER.info(
            "Deleted notification action from %s at %s",
            finding["source_id"],
            finding["action_path"],
        )
    except Exception as e:
        result["success"] = False
        result["error"] = str(e)
        _LOGGER.error("Failed to delete notification: %s", e)

    return result


async def _delete_from_automation(
    hass: HomeAssistant,
    finding: dict[str, Any],
) -> None:
    """Delete action from an automation."""
    source_file = finding.get("source_file", "")

    if ".storage" in source_file:
        await _delete_from_ui_automation(hass, finding)
    else:
        await _delete_from_yaml_file(hass, finding, "automation")


async def _delete_from_ui_automation(
    hass: HomeAssistant,
    finding: dict[str, Any],
) -> None:
    """Delete action from a UI-created automation."""
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

    action_path = finding["action_path"]
    action_index = finding["action_index"]
    action_key = "actions" if "actions" in automation else "action"

    _delete_at_path(automation, action_path, action_index, key=action_key)

    data["items"][auto_index] = automation
    await store.async_save(data)
    await hass.services.async_call("automation", "reload")


async def _delete_from_script(
    hass: HomeAssistant,
    finding: dict[str, Any],
) -> None:
    """Delete action from a script."""
    source_file = finding.get("source_file", "")

    if ".storage" in source_file:
        await _delete_from_ui_script(hass, finding)
    else:
        await _delete_from_yaml_file(hass, finding, "script")


async def _delete_from_ui_script(
    hass: HomeAssistant,
    finding: dict[str, Any],
) -> None:
    """Delete action from a UI-created script."""
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

    _delete_at_path(script, action_path, action_index, key="sequence")

    data["items"][script_index] = script
    await store.async_save(data)
    await hass.services.async_call("script", "reload")


async def _delete_from_yaml_file(
    hass: HomeAssistant,
    finding: dict[str, Any],
    entity_type: str,
) -> None:
    """Delete action from a YAML file."""
    source_file = finding.get("source_file", "")
    if not source_file:
        raise ValueError("No source file information available.")

    config_dir = Path(hass.config.config_dir)

    if source_file.startswith("config/"):
        relative_path = source_file[7:]
    else:
        relative_path = source_file

    file_path = config_dir / relative_path

    if not file_path.exists():
        raise ValueError(f"Source file not found: {file_path}")

    # Read the YAML file
    content = await hass.async_add_executor_job(read_yaml_file, file_path)

    source_id = finding["source_id"]
    action_path = finding["action_path"]
    action_index = finding["action_index"]

    if entity_type == "automation":
        if isinstance(content, list):
            auto_id = source_id.replace("automation.", "")
            for auto in content:
                if not isinstance(auto, dict):
                    continue
                item_id = auto.get("id", "")
                item_alias = auto.get("alias", "")
                if item_id == auto_id or slugify(item_alias) == auto_id:
                    action_key = "actions" if "actions" in auto else "action"
                    _delete_at_path(auto, action_path, action_index, key=action_key)
                    break
            else:
                raise ValueError(f"Automation '{source_id}' not found in {file_path}")
        else:
            raise ValueError(f"Expected list in {file_path}, got {type(content)}")

    elif entity_type == "script":
        script_id = source_id.replace("script.", "")
        if isinstance(content, dict):
            if script_id in content:
                _delete_at_path(content[script_id], action_path, action_index, key="sequence")
            else:
                raise ValueError(f"Script '{script_id}' not found in {file_path}")
        else:
            raise ValueError(f"Expected dict in {file_path}, got {type(content)}")

    # Write back to file
    await hass.async_add_executor_job(write_yaml_file, file_path, content)

    # Reload
    await hass.services.async_call(entity_type, "reload")
    _LOGGER.info("Deleted action from %s and reloaded %ss", file_path, entity_type)


def _delete_at_path(
    obj: dict[str, Any],
    path: str,
    action_index: int,
    key: str = "action",
) -> None:
    """Navigate to a nested path and delete the action at that index."""
    import re

    # Simple case: top-level action
    if path == f"[{action_index}]":
        actions = obj.get(key) or obj.get("actions") or obj.get("action", [])
        if isinstance(actions, list) and action_index < len(actions):
            del actions[action_index]
            # Update the object with the modified list
            if key in obj:
                obj[key] = actions
            elif "actions" in obj:
                obj["actions"] = actions
            elif "action" in obj:
                obj["action"] = actions
        return

    # Nested path: navigate to parent and delete from there
    segments = re.findall(r'\[(\d+)\]|\.(\w+)', path)

    current = obj.get(key) or obj.get("actions") or obj.get("action", [])
    parent_list = None
    target_index = None

    for i, segment in enumerate(segments):
        idx_str, key_str = segment

        if i == len(segments) - 1:
            # Last segment - this is where we delete
            if idx_str:
                target_index = int(idx_str)
                parent_list = current
            break

        if idx_str:
            idx = int(idx_str)
            if isinstance(current, list) and idx < len(current):
                current = current[idx]
        elif key_str:
            if isinstance(current, dict) and key_str in current:
                current = current[key_str]

    if parent_list is not None and target_index is not None:
        if isinstance(parent_list, list) and target_index < len(parent_list):
            del parent_list[target_index]
