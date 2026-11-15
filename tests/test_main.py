import sys
from typing import ClassVar

import pytest

from dbxj import main as main_module
from dbxj.main import main, parse_args


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dbxj"])
    monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
    args = parse_args()
    assert args.offline is False
    assert args.profile is None


def test_parse_args_profile_from_env(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dbxj"])
    monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "dev")
    assert parse_args().profile == "dev"


@pytest.mark.parametrize("flag", ["--offline", "--demo"])
def test_parse_args_offline(monkeypatch, flag):
    monkeypatch.setattr(sys, "argv", ["dbxj", flag, "--profile", "prod"])
    args = parse_args()
    assert args.offline is True
    assert args.profile == "prod"


class FakeApp:
    instances: ClassVar[list["FakeApp"]] = []

    def __init__(self, offline: bool, profile: str | None) -> None:
        self.offline = offline
        self.profile = profile
        self.ran = False
        FakeApp.instances.append(self)

    def run(self) -> None:
        self.ran = True


@pytest.fixture
def fake_app(monkeypatch):
    FakeApp.instances = []
    monkeypatch.setattr(main_module, "DbxjApp", FakeApp)
    monkeypatch.setattr(main_module, "available_profiles", lambda: ["DEFAULT", "dev"])
    monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
    return FakeApp.instances


def test_main_unknown_profile_exits(monkeypatch, fake_app, capsys):
    monkeypatch.setattr(sys, "argv", ["dbxj", "--profile", "nope"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Profile 'nope' not found" in err
    assert "DEFAULT, dev" in err
    assert fake_app == []


def test_main_unknown_profile_allowed_offline(monkeypatch, fake_app):
    monkeypatch.setattr(sys, "argv", ["dbxj", "--offline", "--profile", "nope"])
    main()
    assert fake_app[0].ran and fake_app[0].offline


def test_main_known_profile(monkeypatch, fake_app):
    monkeypatch.setattr(sys, "argv", ["dbxj", "--profile", "dev"])
    main()
    assert fake_app[0].profile == "dev"
    assert fake_app[0].ran
