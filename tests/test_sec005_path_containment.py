"""SEC-005 — path containment in the migration converter.

``migrate/converter.py::_apply_to_yaml_file`` (reached via the public
``apply_to_automation`` / ``apply_to_script`` entry points when the source is a
YAML file) builds an on-disk ``file_path`` from the scanner-supplied
``finding["source_file"]``. Before v1.8.2 a crafted ``source_file`` — an
absolute path or a ``..`` traversal — could steer the backup/read/write onto a
file OUTSIDE the HA config directory.

The fix resolves the candidate path and rejects anything that is not contained
within ``config_dir``::

    resolved_path = file_path.resolve()
    if not resolved_path.is_relative_to(config_dir.resolve()):
        raise ValueError(f"Source file escapes config directory: ...")

These tests assert:

1. Escaping ``source_file`` values raise ``ValueError`` mentioning
   "escapes config directory" AND perform NO filesystem work — no backup dir is
   created and ``hass.async_add_executor_job`` (backup copy / read / write) is
   never invoked. The guard must fire before any I/O.
2. A legitimate ``source_file`` under the config dir passes the containment
   check. It may still fail later (e.g. file-not-found), but the raised error
   must NOT be the containment ValueError — proving legitimate migrations are
   not broken by the guard.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.ticker.migrate.converter import apply_to_automation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass(config_dir):
    """Build a mock hass whose config dir is ``config_dir`` (a tmp_path).

    ``async_add_executor_job`` and ``services.async_call`` are AsyncMocks so we
    can assert they are never touched when the containment guard fires.
    """
    hass = MagicMock()
    hass.config.config_dir = str(config_dir)
    hass.async_add_executor_job = AsyncMock()
    hass.services.async_call = AsyncMock()
    return hass


def _make_finding(source_file: str) -> dict:
    """Scanner-shaped YAML-automation finding pointing at ``source_file``."""
    return {
        "source_type": "automation",
        "source_id": "automation.test_notify",
        "source_file": source_file,
        "action_path": "[0]",
        "action_index": 0,
        "service_data": {"title": "T", "message": "M"},
        "action_alias": None,
    }


_NEW_ACTION = {"service": "ticker.notify", "data": {"category": "Alerts"}}


# ---------------------------------------------------------------------------
# 1. Escaping source_file → containment ValueError, no I/O
# ---------------------------------------------------------------------------

class TestEscapingSourceFileRejected:
    """Crafted paths that leave config_dir must be rejected before any I/O."""

    @pytest.mark.asyncio
    async def test_dotdot_traversal_with_config_prefix_rejected(self, tmp_path):
        """``config/../../../etc/passwd`` collapses to outside config_dir."""
        hass = _make_hass(tmp_path)
        finding = _make_finding("config/../../../etc/passwd")

        with pytest.raises(ValueError) as exc:
            await apply_to_automation(hass, finding, _NEW_ACTION)

        assert "escapes config directory" in str(exc.value)
        # No backup, no read, no write, no reload.
        hass.async_add_executor_job.assert_not_awaited()
        hass.services.async_call.assert_not_awaited()
        assert not (tmp_path / "ticker_migration_backups").exists()

    @pytest.mark.asyncio
    async def test_dotdot_traversal_no_prefix_rejected(self, tmp_path):
        """A bare ``../..`` traversal (no ``config/`` prefix) also escapes."""
        hass = _make_hass(tmp_path)
        finding = _make_finding("../../../../etc/passwd")

        with pytest.raises(ValueError) as exc:
            await apply_to_automation(hass, finding, _NEW_ACTION)

        assert "escapes config directory" in str(exc.value)
        hass.async_add_executor_job.assert_not_awaited()
        hass.services.async_call.assert_not_awaited()
        assert not (tmp_path / "ticker_migration_backups").exists()

    @pytest.mark.asyncio
    async def test_absolute_path_outside_config_rejected(self, tmp_path):
        """An absolute path (with root/drive) outside config_dir is rejected.

        ``config_dir / abs_path`` discards the config anchor entirely, so the
        resolved path lands on the sibling directory — outside config.
        """
        outside = tmp_path.parent / "evil_sibling" / "steal.yaml"
        hass = _make_hass(tmp_path)
        finding = _make_finding(str(outside))

        with pytest.raises(ValueError) as exc:
            await apply_to_automation(hass, finding, _NEW_ACTION)

        assert "escapes config directory" in str(exc.value)
        hass.async_add_executor_job.assert_not_awaited()
        hass.services.async_call.assert_not_awaited()
        assert not (tmp_path / "ticker_migration_backups").exists()


# ---------------------------------------------------------------------------
# 2. Legitimate source_file under config passes the containment check
# ---------------------------------------------------------------------------

class TestLegitimateSourceFilePasses:
    """A path inside config_dir must clear the guard (may fail later, but
    NOT with the containment error)."""

    @pytest.mark.asyncio
    async def test_config_relative_path_passes_containment(self, tmp_path):
        """``config/automations.yaml`` is contained; the only error is the
        downstream file-not-found, never the containment ValueError."""
        hass = _make_hass(tmp_path)
        finding = _make_finding("config/automations.yaml")

        # The file does not exist, so _apply_to_yaml_file raises
        # "Source file not found" AFTER passing containment. That is the
        # expected non-containment failure.
        with pytest.raises(ValueError) as exc:
            await apply_to_automation(hass, finding, _NEW_ACTION)

        message = str(exc.value)
        assert "escapes config directory" not in message, (
            "Legitimate in-config path was wrongly flagged as escaping: "
            f"{message}"
        )
        assert "not found" in message

    @pytest.mark.asyncio
    async def test_bare_relative_path_passes_containment(self, tmp_path):
        """A bare relative path (no ``config/`` prefix) resolving inside the
        config dir must also clear the guard."""
        hass = _make_hass(tmp_path)
        finding = _make_finding("automations.yaml")

        with pytest.raises(ValueError) as exc:
            await apply_to_automation(hass, finding, _NEW_ACTION)

        message = str(exc.value)
        assert "escapes config directory" not in message
        assert "not found" in message

    @pytest.mark.asyncio
    async def test_existing_in_config_file_reaches_backup_stage(self, tmp_path):
        """When the contained file actually exists, execution proceeds past the
        guard into the backup stage (async_add_executor_job invoked) — proving
        the guard does not block real migrations."""
        # Create a real automations.yaml under the config dir.
        target = tmp_path / "automations.yaml"
        target.write_text("[]\n", encoding="utf-8")

        hass = _make_hass(tmp_path)
        # read_yaml_file / write_yaml_file / shutil.copy2 run via the executor;
        # return an empty automation list so the "not found" branch raises after
        # the backup — confirming we got well past the containment guard.
        hass.async_add_executor_job = AsyncMock(return_value=[])
        finding = _make_finding("config/automations.yaml")

        with pytest.raises(ValueError) as exc:
            await apply_to_automation(hass, finding, _NEW_ACTION)

        message = str(exc.value)
        assert "escapes config directory" not in message
        # Backup (shutil.copy2) + read both dispatched to the executor.
        assert hass.async_add_executor_job.await_count >= 1
        # Backup directory was created inside config_dir (contained).
        assert (tmp_path / "ticker_migration_backups").exists()
