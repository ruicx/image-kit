"""Check system upgrade selection without modifying the host operating system."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def bash() -> str:
    """Locate a Bash executable suitable for capability tests.

    Returns
    -------
    str
        Git Bash on Windows or the system Bash.
    """
    for candidate in ("C:/h/Git/bin/bash.exe", "C:/Program Files/Git/bin/bash.exe"):
        if Path(candidate).is_file():
            return candidate
    executable = shutil.which("bash")
    if executable is None:
        pytest.skip()
    return executable


@pytest.mark.parametrize("upgrade", [None, "false", "False", "true", "True", "invalid"])
def test_upgrade_selection(bash: str, tmp_path: Path, upgrade: str | None) -> None:
    """Upgrade only when explicitly requested and reject malformed policies.

    Parameters
    ----------
    bash : str
        Bash executable.
    tmp_path : pathlib.Path
        Isolated timezone data and configuration.
    upgrade : str or None
        Requested policy, or None to exercise the default.
    """
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/system/system.sh").read_text(encoding="utf-8")
    (tmp_path / "UTC").write_text("timezone fixture", encoding="utf-8")
    script = script.replace("/usr/share/zoneinfo/", tmp_path.as_posix() + "/")
    script = script.replace("/etc/timezone", '"${TEST_TIMEZONE}"')
    preamble = """
apt-get() { printf '%s\\n' "$*"; }
uname() { echo x86_64; }; chmod() { :; }; ln() { :; }
locale-gen() { :; }; rm() { :; }
TEST_TIMEZONE="$1"; shift
"""
    args = [(tmp_path / "timezone").as_posix(), "--timezone", "UTC"]
    if upgrade is not None:
        args += ["--upgrade", upgrade]
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-s", "--", *args],
        input=preamble + script,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if upgrade == "invalid":
        assert result.returncode == 64
        assert not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert ("-y upgrade" in result.stdout) == (upgrade in ("true", "True"))
        assert (tmp_path / "timezone").read_text(encoding="utf-8") == "UTC\n"


def test_shared_privilege_tools(bash: str) -> None:
    """Include gosu and sudo in the common package installation transaction.

    Parameters
    ----------
    bash : str
        Bash executable.
    """
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts/dev/dev-tools.sh").read_text(encoding="utf-8")
    preamble = """
apt-get() { printf '%s\\n' "$@"; }; uname() { echo x86_64; }
ln() { :; }; rm() { :; }; git() { :; }; update-alternatives() { :; }
command() { if [ "$1" = -v ]; then printf '/usr/bin/%s' "$2"; else return 1; fi; }
"""
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-s"],
        input=preamble + script,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "\ngosu\n" in result.stdout
    assert "\nsudo\n" in result.stdout
    assert "landscape-common" not in result.stdout
