"""Scanner functions for migration module."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import (
    MIGRATE_SOURCE_AUTOMATION,
    MIGRATE_SOURCE_SCRIPT,
    MIGRATE_SERVICES,
)
from .common import normalize_to_list, read_yaml_file, slugify
from .duplicates import _mark_adjacent_duplicates

_LOGGER = logging.getLogger(__name__)


async def async_scan_for_notifications(
    hass: HomeAssistant,
    services: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Scan automations and scripts for notify service calls.

    Args:
        hass: The Home Assistant instance.
        services: Optional list of service domains to match (e.g. ["notify"]).
            Defaults to MIGRATE_SERVICES when None.
    """
    match_services = services if services is not None else list(MIGRATE_SERVICES)
    findings = []

    # Scan automations
    auto_findings = await _scan_automations(hass, match_services)
    findings.extend(auto_findings)
    _LOGGER.info("Found %d notification calls in automations", len(auto_findings))

    # Scan scripts
    script_findings = await _scan_scripts(hass, match_services)
    findings.extend(script_findings)
    _LOGGER.info("Found %d notification calls in scripts", len(script_findings))

    # Mark adjacent duplicates
    _mark_adjacent_duplicates(findings)

    _LOGGER.info("Migration scan found %d notification calls total", len(findings))
    return findings


async def _scan_automations(hass: HomeAssistant, match_services: list[str]) -> list[dict[str, Any]]:
    """Scan all automations for notify calls."""
    findings = []
    scanned_ids = set()
    config_dir = Path(hass.config.config_dir)

    # Method 1: UI-created automations from .storage
    try:
        from homeassistant.helpers.storage import Store
        store = Store(hass, 5, "automation.config")
        data = await store.async_load()

        if data and "items" in data:
            _LOGGER.debug("Found %d UI automations in storage", len(data["items"]))
            for auto in data["items"]:
                entity_id, f = _process_automation(auto, match_services, source_file=".storage/automation.config")
                findings.extend(f)
                scanned_ids.add(entity_id)
    except Exception as e:
        _LOGGER.debug("Could not load UI automations: %s", e)

    # Method 2: YAML - single file (automations.yaml)
    automations_file = config_dir / "automations.yaml"
    if automations_file.exists():
        try:
            content = await hass.async_add_executor_job(read_yaml_file, automations_file)
            if isinstance(content, list):
                _LOGGER.debug("Found %d automations in automations.yaml", len(content))
                for auto in content:
                    if not isinstance(auto, dict):
                        continue
                    entity_id, f = _process_automation(auto, match_services, source_file="config/automations.yaml")
                    if entity_id not in scanned_ids:
                        findings.extend(f)
                        scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.warning("Could not read automations.yaml: %s", e)

    # Method 3: YAML - directory (!include_dir_list or !include_dir_merge_list)
    automations_dir = config_dir / "automations"
    if automations_dir.is_dir():
        try:
            yaml_files = list(automations_dir.glob("**/*.yaml")) + list(automations_dir.glob("**/*.yml"))
            _LOGGER.debug("Found %d YAML files in automations/", len(yaml_files))
            for yaml_file in yaml_files:
                rel_path = f"config/{yaml_file.relative_to(config_dir)}"
                content = await hass.async_add_executor_job(read_yaml_file, yaml_file)
                autos = normalize_to_list(content)
                for auto in autos:
                    if not isinstance(auto, dict):
                        continue
                    entity_id, f = _process_automation(auto, match_services, source_file=rel_path)
                    if entity_id not in scanned_ids:
                        findings.extend(f)
                        scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.warning("Could not read automations directory: %s", e)

    # Method 4: Packages directory
    packages_dir = config_dir / "packages"
    if packages_dir.is_dir():
        try:
            yaml_files = list(packages_dir.glob("**/*.yaml")) + list(packages_dir.glob("**/*.yml"))
            for yaml_file in yaml_files:
                rel_path = f"config/{yaml_file.relative_to(config_dir)}"
                content = await hass.async_add_executor_job(read_yaml_file, yaml_file)
                if isinstance(content, dict) and "automation" in content:
                    autos = normalize_to_list(content["automation"])
                    _LOGGER.debug("Found %d automations in package %s", len(autos), yaml_file.name)
                    for auto in autos:
                        if not isinstance(auto, dict):
                            continue
                        entity_id, f = _process_automation(auto, match_services, source_file=rel_path)
                        if entity_id not in scanned_ids:
                            findings.extend(f)
                            scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not read packages: %s", e)

    # Method 5: configuration.yaml inline automations
    config_file = config_dir / "configuration.yaml"
    if config_file.exists():
        try:
            content = await hass.async_add_executor_job(read_yaml_file, config_file)
            if isinstance(content, dict) and "automation" in content:
                autos = normalize_to_list(content["automation"])
                if autos:
                    _LOGGER.debug("Found %d inline automations in configuration.yaml", len(autos))
                    for auto in autos:
                        if not isinstance(auto, dict):
                            continue
                        entity_id, f = _process_automation(auto, match_services, source_file="config/configuration.yaml")
                        if entity_id not in scanned_ids:
                            findings.extend(f)
                            scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not check configuration.yaml for automations: %s", e)

    return findings


async def _scan_scripts(hass: HomeAssistant, match_services: list[str]) -> list[dict[str, Any]]:
    """Scan all scripts for notify calls."""
    findings = []
    scanned_ids = set()
    config_dir = Path(hass.config.config_dir)

    # Method 1: UI-created scripts from .storage
    try:
        from homeassistant.helpers.storage import Store
        store = Store(hass, 5, "script.config")
        data = await store.async_load()

        if data and "items" in data:
            _LOGGER.debug("Found %d UI scripts in storage", len(data["items"]))
            for item in data["items"]:
                script_id = item.get("id", "")
                entity_id = f"script.{script_id}"
                f = _process_script(script_id, item, match_services, source_file=".storage/script.config")
                findings.extend(f)
                scanned_ids.add(entity_id)
    except Exception as e:
        _LOGGER.debug("Could not load UI scripts: %s", e)

    # Method 2: YAML - single file (scripts.yaml)
    scripts_file = config_dir / "scripts.yaml"
    if scripts_file.exists():
        try:
            content = await hass.async_add_executor_job(read_yaml_file, scripts_file)
            if isinstance(content, dict):
                _LOGGER.debug("Found %d scripts in scripts.yaml", len(content))
                for script_id, script_config in content.items():
                    if not isinstance(script_config, dict):
                        continue
                    entity_id = f"script.{script_id}"
                    if entity_id not in scanned_ids:
                        f = _process_script(script_id, script_config, match_services, source_file="config/scripts.yaml")
                        findings.extend(f)
                        scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.warning("Could not read scripts.yaml: %s", e)

    # Method 3: YAML - directory (!include_dir_named or !include_dir_merge_named)
    scripts_dir = config_dir / "scripts"
    if scripts_dir.is_dir():
        try:
            yaml_files = list(scripts_dir.glob("**/*.yaml")) + list(scripts_dir.glob("**/*.yml"))
            _LOGGER.debug("Found %d YAML files in scripts/", len(yaml_files))
            for yaml_file in yaml_files:
                rel_path = f"config/{yaml_file.relative_to(config_dir)}"
                content = await hass.async_add_executor_job(read_yaml_file, yaml_file)
                # Could be a dict of scripts or a single script config
                if isinstance(content, dict):
                    # Check if it looks like a script config (has sequence) or dict of scripts
                    if "sequence" in content:
                        # Single script, use filename as ID
                        script_id = yaml_file.stem
                        entity_id = f"script.{script_id}"
                        if entity_id not in scanned_ids:
                            f = _process_script(script_id, content, match_services, source_file=rel_path)
                            findings.extend(f)
                            scanned_ids.add(entity_id)
                    else:
                        # Dict of scripts
                        for script_id, script_config in content.items():
                            if isinstance(script_config, dict):
                                entity_id = f"script.{script_id}"
                                if entity_id not in scanned_ids:
                                    f = _process_script(script_id, script_config, match_services, source_file=rel_path)
                                    findings.extend(f)
                                    scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.warning("Could not read scripts directory: %s", e)

    # Method 4: Packages directory
    packages_dir = config_dir / "packages"
    if packages_dir.is_dir():
        try:
            yaml_files = list(packages_dir.glob("**/*.yaml")) + list(packages_dir.glob("**/*.yml"))
            for yaml_file in yaml_files:
                rel_path = f"config/{yaml_file.relative_to(config_dir)}"
                content = await hass.async_add_executor_job(read_yaml_file, yaml_file)
                if isinstance(content, dict) and "script" in content:
                    scripts = content["script"]
                    if isinstance(scripts, dict):
                        _LOGGER.debug("Found %d scripts in package %s", len(scripts), yaml_file.name)
                        for script_id, script_config in scripts.items():
                            if isinstance(script_config, dict):
                                entity_id = f"script.{script_id}"
                                if entity_id not in scanned_ids:
                                    f = _process_script(script_id, script_config, match_services, source_file=rel_path)
                                    findings.extend(f)
                                    scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not read packages for scripts: %s", e)

    # Method 5: configuration.yaml inline scripts
    config_file = config_dir / "configuration.yaml"
    if config_file.exists():
        try:
            content = await hass.async_add_executor_job(read_yaml_file, config_file)
            if isinstance(content, dict) and "script" in content:
                scripts = content["script"]
                if isinstance(scripts, dict):
                    _LOGGER.debug("Found %d inline scripts in configuration.yaml", len(scripts))
                    for script_id, script_config in scripts.items():
                        if isinstance(script_config, dict):
                            entity_id = f"script.{script_id}"
                            if entity_id not in scanned_ids:
                                f = _process_script(script_id, script_config, match_services, source_file="config/configuration.yaml")
                                findings.extend(f)
                                scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not check configuration.yaml for scripts: %s", e)

    return findings


def _process_automation(
    auto: dict[str, Any], match_services: list[str], source_file: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """Process a single automation config and return (entity_id, findings)."""
    auto_id = auto.get("id", "")
    auto_alias = auto.get("alias", "Unnamed automation")
    auto_desc = auto.get("description", "")

    if auto_id:
        entity_id = f"automation.{auto_id}"
    else:
        entity_id = f"automation.{slugify(auto_alias)}"

    # Support both 'action' (legacy) and 'actions' (current) keys
    actions = auto.get("actions") or auto.get("action", [])
    if not isinstance(actions, list):
        actions = [actions] if actions else []

    findings = _scan_action_sequence(
        actions=actions,
        match_services=match_services,
        source_type=MIGRATE_SOURCE_AUTOMATION,
        source_id=entity_id,
        source_name=auto_alias,
        source_description=auto_desc,
        source_file=source_file,
    )

    return entity_id, findings


def _process_script(
    script_id: str, config: dict[str, Any], match_services: list[str], source_file: str = "",
) -> list[dict[str, Any]]:
    """Process a single script config and return findings."""
    script_alias = config.get("alias", script_id)
    script_desc = config.get("description", "")
    entity_id = f"script.{script_id}"

    sequence = config.get("sequence", [])
    if not isinstance(sequence, list):
        sequence = [sequence] if sequence else []

    return _scan_action_sequence(
        actions=sequence,
        match_services=match_services,
        source_type=MIGRATE_SOURCE_SCRIPT,
        source_id=entity_id,
        source_name=script_alias,
        source_description=script_desc,
        source_file=source_file,
    )


def _scan_action_sequence(
    actions: list[dict[str, Any]], match_services: list[str],
    source_type: str,
    source_id: str,
    source_name: str,
    source_description: str,
    parent_path: str = "",
    source_file: str = "",
) -> list[dict[str, Any]]:
    """Recursively scan an action sequence for notify calls."""
    findings = []

    if not actions:
        return findings

    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            continue

        current_path = f"{parent_path}[{idx}]" if parent_path else f"[{idx}]"
        action_alias = action.get("alias", "")

        # Check if this action is a service call
        # HA uses both "service" and "action" keys
        service = action.get("service") or action.get("action") or ""

        if service and isinstance(service, str):
            service_domain = service.split(".")[0] if "." in service else service
            if service_domain in match_services:
                finding = {
                    "finding_id": str(uuid.uuid4()),
                    "source_type": source_type,
                    "source_id": source_id,
                    "source_name": source_name,
                    "source_description": source_description,
                    "action_path": current_path,
                    "action_index": idx,
                    "action_alias": action_alias,
                    "service": service,
                    "service_data": action.get("data", {}),
                    "target": action.get("target", {}),
                    "source_file": source_file,
                }
                findings.append(finding)

        # Recursively scan nested structures

        # choose blocks
        if "choose" in action and isinstance(action["choose"], list):
            for choice_idx, choice in enumerate(action["choose"]):
                if isinstance(choice, dict):
                    choice_actions = choice.get("sequence", [])
                    if isinstance(choice_actions, list):
                        nested = _scan_action_sequence(
                            actions=choice_actions,
                            match_services=match_services,
                            source_type=source_type,
                            source_id=source_id,
                            source_name=source_name,
                            source_description=source_description,
                            parent_path=f"{current_path}.choose[{choice_idx}].sequence",
                            source_file=source_file,
                        )
                        findings.extend(nested)

            # default branch
            default_actions = action.get("default", [])
            if isinstance(default_actions, list) and default_actions:
                nested = _scan_action_sequence(
                    actions=default_actions,
                    match_services=match_services,
                    source_type=source_type,
                    source_id=source_id,
                    source_name=source_name,
                    source_description=source_description,
                    parent_path=f"{current_path}.default",
                    source_file=source_file,
                )
                findings.extend(nested)

        # if/then/else blocks
        if "if" in action:
            then_actions = action.get("then", [])
            if then_actions:
                if not isinstance(then_actions, list):
                    then_actions = [then_actions]
                nested = _scan_action_sequence(
                    actions=then_actions,
                    match_services=match_services,
                    source_type=source_type,
                    source_id=source_id,
                    source_name=source_name,
                    source_description=source_description,
                    parent_path=f"{current_path}.then",
                    source_file=source_file,
                )
                findings.extend(nested)

            else_actions = action.get("else", [])
            if else_actions:
                if not isinstance(else_actions, list):
                    else_actions = [else_actions]
                nested = _scan_action_sequence(
                    actions=else_actions,
                    match_services=match_services,
                    source_type=source_type,
                    source_id=source_id,
                    source_name=source_name,
                    source_description=source_description,
                    parent_path=f"{current_path}.else",
                    source_file=source_file,
                )
                findings.extend(nested)

        # repeat blocks
        if "repeat" in action and isinstance(action["repeat"], dict):
            repeat_sequence = action["repeat"].get("sequence", [])
            if isinstance(repeat_sequence, list) and repeat_sequence:
                nested = _scan_action_sequence(
                    actions=repeat_sequence,
                    match_services=match_services,
                    source_type=source_type,
                    source_id=source_id,
                    source_name=source_name,
                    source_description=source_description,
                    parent_path=f"{current_path}.repeat.sequence",
                    source_file=source_file,
                )
                findings.extend(nested)

        # parallel blocks
        if "parallel" in action and isinstance(action["parallel"], list):
            for parallel_idx, parallel_item in enumerate(action["parallel"]):
                if isinstance(parallel_item, dict):
                    if "sequence" in parallel_item:
                        nested = _scan_action_sequence(
                            actions=parallel_item["sequence"],
                            match_services=match_services,
                            source_type=source_type,
                            source_id=source_id,
                            source_name=source_name,
                            source_description=source_description,
                            parent_path=f"{current_path}.parallel[{parallel_idx}].sequence",
                            source_file=source_file,
                        )
                    else:
                        nested = _scan_action_sequence(
                            actions=[parallel_item],
                            match_services=match_services,
                            source_type=source_type,
                            source_id=source_id,
                            source_name=source_name,
                            source_description=source_description,
                            parent_path=f"{current_path}.parallel[{parallel_idx}]",
                            source_file=source_file,
                        )
                    findings.extend(nested)

        # sequence blocks (explicit)
        if "sequence" in action and "repeat" not in action and "parallel" not in action:
            seq = action["sequence"]
            if isinstance(seq, list):
                nested = _scan_action_sequence(
                    actions=seq,
                    match_services=match_services,
                    source_type=source_type,
                    source_id=source_id,
                    source_name=source_name,
                    source_description=source_description,
                    parent_path=f"{current_path}.sequence",
                    source_file=source_file,
                )
                findings.extend(nested)

    return findings
