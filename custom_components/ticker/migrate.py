"""Migration wizard for Ticker integration."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    MIGRATE_SOURCE_AUTOMATION,
    MIGRATE_SOURCE_SCRIPT,
    MIGRATE_SERVICES,
)

# Services to check for duplicates (migration targets + ticker.notify)
DUPLICATE_CHECK_SERVICES = MIGRATE_SERVICES + [DOMAIN]

_LOGGER = logging.getLogger(__name__)


async def async_scan_for_notifications(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Scan automations and scripts for notify service calls."""
    findings = []
    
    # Scan automations
    auto_findings = await _scan_automations(hass)
    findings.extend(auto_findings)
    _LOGGER.info("Found %d notification calls in automations", len(auto_findings))
    
    # Scan scripts
    script_findings = await _scan_scripts(hass)
    findings.extend(script_findings)
    _LOGGER.info("Found %d notification calls in scripts", len(script_findings))
    
    # Mark adjacent duplicates
    _mark_adjacent_duplicates(findings)
    
    _LOGGER.info("Migration scan found %d notification calls total", len(findings))
    return findings


async def _scan_automations(hass: HomeAssistant) -> list[dict[str, Any]]:
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
                entity_id, f = _process_automation(auto, source_file=".storage/automation.config")
                findings.extend(f)
                scanned_ids.add(entity_id)
    except Exception as e:
        _LOGGER.debug("Could not load UI automations: %s", e)
    
    # Method 2: YAML - single file (automations.yaml)
    automations_file = config_dir / "automations.yaml"
    if automations_file.exists():
        try:
            content = await hass.async_add_executor_job(_read_yaml_file, automations_file)
            if isinstance(content, list):
                _LOGGER.debug("Found %d automations in automations.yaml", len(content))
                for auto in content:
                    if not isinstance(auto, dict):
                        continue
                    entity_id, f = _process_automation(auto, source_file="config/automations.yaml")
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
                content = await hass.async_add_executor_job(_read_yaml_file, yaml_file)
                autos = _normalize_to_list(content)
                for auto in autos:
                    if not isinstance(auto, dict):
                        continue
                    entity_id, f = _process_automation(auto, source_file=rel_path)
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
                content = await hass.async_add_executor_job(_read_yaml_file, yaml_file)
                if isinstance(content, dict) and "automation" in content:
                    autos = _normalize_to_list(content["automation"])
                    _LOGGER.debug("Found %d automations in package %s", len(autos), yaml_file.name)
                    for auto in autos:
                        if not isinstance(auto, dict):
                            continue
                        entity_id, f = _process_automation(auto, source_file=rel_path)
                        if entity_id not in scanned_ids:
                            findings.extend(f)
                            scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not read packages: %s", e)
    
    # Method 5: configuration.yaml inline automations
    config_file = config_dir / "configuration.yaml"
    if config_file.exists():
        try:
            content = await hass.async_add_executor_job(_read_yaml_file, config_file)
            if isinstance(content, dict) and "automation" in content:
                autos = _normalize_to_list(content["automation"])
                if autos:
                    _LOGGER.debug("Found %d inline automations in configuration.yaml", len(autos))
                    for auto in autos:
                        if not isinstance(auto, dict):
                            continue
                        entity_id, f = _process_automation(auto, source_file="config/configuration.yaml")
                        if entity_id not in scanned_ids:
                            findings.extend(f)
                            scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not check configuration.yaml for automations: %s", e)
    
    return findings


async def _scan_scripts(hass: HomeAssistant) -> list[dict[str, Any]]:
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
                f = _process_script(script_id, item, source_file=".storage/script.config")
                findings.extend(f)
                scanned_ids.add(entity_id)
    except Exception as e:
        _LOGGER.debug("Could not load UI scripts: %s", e)
    
    # Method 2: YAML - single file (scripts.yaml)
    scripts_file = config_dir / "scripts.yaml"
    if scripts_file.exists():
        try:
            content = await hass.async_add_executor_job(_read_yaml_file, scripts_file)
            if isinstance(content, dict):
                _LOGGER.debug("Found %d scripts in scripts.yaml", len(content))
                for script_id, script_config in content.items():
                    if not isinstance(script_config, dict):
                        continue
                    entity_id = f"script.{script_id}"
                    if entity_id not in scanned_ids:
                        f = _process_script(script_id, script_config, source_file="config/scripts.yaml")
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
                content = await hass.async_add_executor_job(_read_yaml_file, yaml_file)
                # Could be a dict of scripts or a single script config
                if isinstance(content, dict):
                    # Check if it looks like a script config (has sequence) or dict of scripts
                    if "sequence" in content:
                        # Single script, use filename as ID
                        script_id = yaml_file.stem
                        entity_id = f"script.{script_id}"
                        if entity_id not in scanned_ids:
                            f = _process_script(script_id, content, source_file=rel_path)
                            findings.extend(f)
                            scanned_ids.add(entity_id)
                    else:
                        # Dict of scripts
                        for script_id, script_config in content.items():
                            if isinstance(script_config, dict):
                                entity_id = f"script.{script_id}"
                                if entity_id not in scanned_ids:
                                    f = _process_script(script_id, script_config, source_file=rel_path)
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
                content = await hass.async_add_executor_job(_read_yaml_file, yaml_file)
                if isinstance(content, dict) and "script" in content:
                    scripts = content["script"]
                    if isinstance(scripts, dict):
                        _LOGGER.debug("Found %d scripts in package %s", len(scripts), yaml_file.name)
                        for script_id, script_config in scripts.items():
                            if isinstance(script_config, dict):
                                entity_id = f"script.{script_id}"
                                if entity_id not in scanned_ids:
                                    f = _process_script(script_id, script_config, source_file=rel_path)
                                    findings.extend(f)
                                    scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not read packages for scripts: %s", e)
    
    # Method 5: configuration.yaml inline scripts
    config_file = config_dir / "configuration.yaml"
    if config_file.exists():
        try:
            content = await hass.async_add_executor_job(_read_yaml_file, config_file)
            if isinstance(content, dict) and "script" in content:
                scripts = content["script"]
                if isinstance(scripts, dict):
                    _LOGGER.debug("Found %d inline scripts in configuration.yaml", len(scripts))
                    for script_id, script_config in scripts.items():
                        if isinstance(script_config, dict):
                            entity_id = f"script.{script_id}"
                            if entity_id not in scanned_ids:
                                f = _process_script(script_id, script_config, source_file="config/configuration.yaml")
                                findings.extend(f)
                                scanned_ids.add(entity_id)
        except Exception as e:
            _LOGGER.debug("Could not check configuration.yaml for scripts: %s", e)
    
    return findings


def _process_automation(auto: dict[str, Any], source_file: str = "") -> tuple[str, list[dict[str, Any]]]:
    """Process a single automation config and return (entity_id, findings)."""
    auto_id = auto.get("id", "")
    auto_alias = auto.get("alias", "Unnamed automation")
    auto_desc = auto.get("description", "")
    
    if auto_id:
        entity_id = f"automation.{auto_id}"
    else:
        entity_id = f"automation.{_slugify(auto_alias)}"
    
    # Support both 'action' (legacy) and 'actions' (current) keys
    actions = auto.get("actions") or auto.get("action", [])
    if not isinstance(actions, list):
        actions = [actions] if actions else []
    
    findings = _scan_action_sequence(
        actions=actions,
        source_type=MIGRATE_SOURCE_AUTOMATION,
        source_id=entity_id,
        source_name=auto_alias,
        source_description=auto_desc,
        source_file=source_file,
    )
    
    return entity_id, findings


def _process_script(script_id: str, config: dict[str, Any], source_file: str = "") -> list[dict[str, Any]]:
    """Process a single script config and return findings."""
    script_alias = config.get("alias", script_id)
    script_desc = config.get("description", "")
    entity_id = f"script.{script_id}"
    
    sequence = config.get("sequence", [])
    if not isinstance(sequence, list):
        sequence = [sequence] if sequence else []
    
    return _scan_action_sequence(
        actions=sequence,
        source_type=MIGRATE_SOURCE_SCRIPT,
        source_id=entity_id,
        source_name=script_alias,
        source_description=script_desc,
        source_file=source_file,
    )


def _normalize_to_list(content: Any) -> list:
    """Normalize content to a list."""
    if content is None:
        return []
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        return [content]
    return []


def _read_yaml_file(path: Path) -> Any:
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


def _scan_action_sequence(
    actions: list[dict[str, Any]],
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
            if service_domain in MIGRATE_SERVICES:
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
                    source_type=source_type,
                    source_id=source_id,
                    source_name=source_name,
                    source_description=source_description,
                    parent_path=f"{current_path}.sequence",
                    source_file=source_file,
                )
                findings.extend(nested)
    
    return findings


def _slugify(text: str) -> str:
    """Create a slug from text."""
    import re
    text = str(text).lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text


# =============================================================================
# Duplicate detection functions
# =============================================================================

def _normalize_value(value: Any) -> Any:
    """Normalize a value for comparison.
    
    Treats None, empty string, and missing as equivalent.
    """
    if value is None or value == "":
        return None
    return value


def _normalize_data_for_comparison(data: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a data dict for comparison.
    
    Removes keys with None/empty values and normalizes remaining values.
    """
    if not data:
        return {}
    
    normalized = {}
    for key, value in data.items():
        norm_value = _normalize_value(value)
        if norm_value is not None:
            normalized[key] = norm_value
    return normalized


def _are_duplicates(finding1: dict[str, Any], finding2: dict[str, Any]) -> bool:
    """Check if two findings are duplicates.
    
    For notify.*/persistent_notification.* services:
        Compare title, message, and data fields (ignore service and target).
    
    For ticker.notify:
        Compare category, title, message, and data fields.
    
    Empty string, None, and missing field are treated as equal.
    """
    service1 = finding1.get("service", "")
    service2 = finding2.get("service", "")
    
    # Get service domains
    domain1 = service1.split(".")[0] if "." in service1 else service1
    domain2 = service2.split(".")[0] if "." in service2 else service2
    
    # Both must be notification-related services
    if domain1 not in DUPLICATE_CHECK_SERVICES or domain2 not in DUPLICATE_CHECK_SERVICES:
        return False
    
    data1 = finding1.get("service_data", {})
    data2 = finding2.get("service_data", {})
    
    # Compare title and message
    title1 = _normalize_value(data1.get("title"))
    title2 = _normalize_value(data2.get("title"))
    message1 = _normalize_value(data1.get("message"))
    message2 = _normalize_value(data2.get("message"))
    
    if title1 != title2 or message1 != message2:
        return False
    
    # For ticker.notify, also compare category
    is_ticker1 = domain1 == DOMAIN
    is_ticker2 = domain2 == DOMAIN
    
    if is_ticker1 and is_ticker2:
        cat1 = _normalize_value(data1.get("category"))
        cat2 = _normalize_value(data2.get("category"))
        if cat1 != cat2:
            return False
    
    # Compare data fields (excluding title, message, category)
    extra_keys = {"title", "message", "category"}
    extra_data1 = _normalize_data_for_comparison(
        {k: v for k, v in data1.items() if k not in extra_keys}
    )
    extra_data2 = _normalize_data_for_comparison(
        {k: v for k, v in data2.items() if k not in extra_keys}
    )
    
    return extra_data1 == extra_data2


def _mark_adjacent_duplicates(findings: list[dict[str, Any]]) -> None:
    """Mark findings that have adjacent duplicates.
    
    Modifies findings in-place to add duplicate metadata:
    - has_duplicate: bool
    - duplicate_finding_id: str (finding_id of the duplicate)
    - is_first_in_duplicate_pair: bool
    
    Only checks immediately adjacent findings within the same source and action path parent.
    """
    if len(findings) < 2:
        return
    
    # Group findings by source_id and parent path for adjacency check
    # Adjacent means same source and sequential action_index in same parent path
    for i in range(len(findings) - 1):
        current = findings[i]
        next_finding = findings[i + 1]
        
        # Skip if already marked as duplicate
        if current.get("has_duplicate") or next_finding.get("has_duplicate"):
            continue
        
        # Must be in same source (same automation/script)
        if current.get("source_id") != next_finding.get("source_id"):
            continue
        
        # Check if they're adjacent (sequential indices in same parent path)
        if not _are_adjacent(current, next_finding):
            continue
        
        # Check if they're duplicates
        if _are_duplicates(current, next_finding):
            current["has_duplicate"] = True
            current["duplicate_finding_id"] = next_finding["finding_id"]
            current["is_first_in_duplicate_pair"] = True
            
            next_finding["has_duplicate"] = True
            next_finding["duplicate_finding_id"] = current["finding_id"]
            next_finding["is_first_in_duplicate_pair"] = False
            
            _LOGGER.debug(
                "Found duplicate notifications in %s: indices %s and %s",
                current["source_id"],
                current["action_path"],
                next_finding["action_path"],
            )


def _are_adjacent(finding1: dict[str, Any], finding2: dict[str, Any]) -> bool:
    """Check if two findings are immediately adjacent in the action sequence.
    
    Adjacent means:
    - Same parent path (e.g., both in root actions, or both in same then: block)
    - Sequential action indices (e.g., [0] and [1], not [0] and [2])
    """
    path1 = finding1.get("action_path", "")
    path2 = finding2.get("action_path", "")
    idx1 = finding1.get("action_index", -1)
    idx2 = finding2.get("action_index", -1)
    
    # Extract parent path (everything before the last [index])
    # e.g., "[0].then[1]" -> parent is "[0].then", index is 1
    import re
    
    match1 = re.match(r"^(.*)\[(\d+)\]$", path1)
    match2 = re.match(r"^(.*)\[(\d+)\]$", path2)
    
    if not match1 or not match2:
        return False
    
    parent1, leaf_idx1 = match1.groups()
    parent2, leaf_idx2 = match2.groups()
    
    # Must have same parent path
    if parent1 != parent2:
        return False
    
    # Must be sequential (difference of 1)
    return abs(int(leaf_idx1) - int(leaf_idx2)) == 1


# =============================================================================
# Conversion functions
# =============================================================================

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
        if item_id == auto_id or _slugify(item_alias) == auto_id:
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
    content = await hass.async_add_executor_job(_read_yaml_file, file_path)
    
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
                if item_id == auto_id or _slugify(item_alias) == auto_id:
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
    await hass.async_add_executor_job(_write_yaml_file, file_path, content)
    
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


def _write_yaml_file(path: Path, content: Any) -> None:
    """Write content to a YAML file."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(content, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


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
    parent = None
    last_index = None
    
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
                parent = current
                last_index = idx
                current = current[idx]
        elif key_str:
            if isinstance(current, dict) and key_str in current:
                parent = current
                current = current[key_str]


# =============================================================================
# Deletion functions
# =============================================================================

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
        if item_id == auto_id or _slugify(item_alias) == auto_id:
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
    content = await hass.async_add_executor_job(_read_yaml_file, file_path)
    
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
                if item_id == auto_id or _slugify(item_alias) == auto_id:
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
    await hass.async_add_executor_job(_write_yaml_file, file_path, content)
    
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
