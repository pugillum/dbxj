from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dbxj import auth
from dbxj.auth import AuthError, available_profiles, config_path, connect


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "databrickscfg"
    monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(path))
    return path


def test_config_path_default(monkeypatch):
    monkeypatch.delenv("DATABRICKS_CONFIG_FILE", raising=False)
    assert config_path() == Path("~/.databrickscfg").expanduser()


def test_config_path_from_env(config_file):
    assert config_path() == config_file


def test_available_profiles_missing_file(config_file):
    assert available_profiles() == []


def test_available_profiles_with_default(config_file):
    config_file.write_text(
        "[DEFAULT]\nhost = https://a\n\n"
        "[dev]\nhost = https://b\n\n"
        "[__settings__]\ndefault_profile = dev\n\n"
        "[prod]\nhost = https://c\n"
    )
    assert available_profiles() == ["DEFAULT", "dev", "prod"]


def test_available_profiles_without_default(config_file):
    config_file.write_text("[dev]\nhost = https://b\n")
    assert available_profiles() == ["dev"]


def test_connect(monkeypatch):
    client = MagicMock()
    client.current_user.me.return_value.user_name = "someone@example.com"
    client.get_workspace_id.return_value = 123
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(auth, "WorkspaceClient", factory)

    assert connect("dev") == (client, 123, "someone@example.com")
    factory.assert_called_once_with(profile="dev")


def test_connect_unknown_user(monkeypatch):
    client = MagicMock()
    client.current_user.me.return_value.user_name = None
    monkeypatch.setattr(auth, "WorkspaceClient", MagicMock(return_value=client))
    assert connect(None)[2] == "Unknown"


def test_connect_wraps_errors(monkeypatch):
    monkeypatch.setattr(auth, "WorkspaceClient", MagicMock(side_effect=ValueError("bad token")))
    with pytest.raises(AuthError, match="bad token") as exc_info:
        connect("dev")
    assert isinstance(exc_info.value.__cause__, ValueError)
