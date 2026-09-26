"""Install the plugin into a real Hermes, every way README.md says to.

Nothing here is simulated. The tests run against a Hermes that its official
installer set up in this account — the ``setup-hermes`` action does that in CI —
and run the commands README.md gives, as written. Success is whatever Hermes
reports afterwards: ``hermes plugins list``, and the plugins, tools and
``web_search`` provider its own plugin manager hands the agent (see
``probe.py``, run in Hermes' own Python, which ``hermes_env.py`` finds for
either installer).

Where the tests depart from the README text, and why:

* the Git install adds ``--ref`` with the commit under test, because the README
  command installs whatever the default branch holds at the time;
* the PyPI install names the wheel about to be published instead of the
  project, so it cannot pick up the release already on PyPI;
* the drop-in archive is the one about to be attached to the release, and its
  ``<version>`` placeholder is filled in;
* the directory copy runs in a fresh copy of the plugin directory, standing in
  for a clone of this repository.

The PyPI route runs only on a Hermes from the 0.21-era installer, which is the
only one README.md gives a PyPI command for; on a pm-built Hermes it is skipped.

Each test changes the Hermes it runs against, then puts back what it changed:
the plugin directories, ``config.yaml`` (the enabled plugins and the selected
backend), ``.env``, and a package installed from PyPI. They still install into
a real ``~/.hermes``, so they refuse to run unless
``INSTALL_CHECK_DISPOSABLE_HOME=1`` says that Hermes is a throwaway one.

Deselected by default. The ``Install check`` workflow runs them before every
release, against the latest Hermes release and against Hermes ``main``. To run
them yourself, do it in a container or VM with Hermes installed by its
installer, after building the artifacts the way ``release-build.yml`` does::

    INSTALL_CHECK_DISPOSABLE_HOME=1 INSTALL_DIST=dist \\
    INSTALL_REF="$(git rev-parse HEAD)" python -m pytest -m install
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

from .hermes_env import hermes_python, is_pm_install

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
    "version"
]

PLUGIN = "yandex"
TOOLSET = "yandex_search"
PACKAGE = "hermes_yandex_search"
PROJECT = "hermes-yandex-search-api"
REQUIRED_ENV = ("YANDEX_API_KEY", "YANDEX_FOLDER_ID")

#: The plugin's own tool. Its other half, the ``web_search`` backend, is
#: checked separately: see _assert_loaded.
DEFAULT_TOOLS = {"yandex_generative_search"}

#: What the plugin imports beyond the standard library. Options A and B install
#: none of it; README.md says a Hermes set up by its installer already has both.
DEPENDENCIES = ("httpx", "defusedxml")

# The commands README.md gives. test_readme_gives_the_commands_under_test keeps
# the two in step, so the tests below cannot drift into checking something the
# README does not say.
GIT_INSTALL = (
    "hermes plugins install akinfold/hermes-yandex-search-api/hermes_yandex_search --enable"
)
GIT_UPGRADE = GIT_INSTALL + " --force"
#: For a Hermes from the 0.21-era installer only; see README.md, Option C.
PYPI_INSTALL = (
    "~/.hermes/bin/uv pip install --python ~/.hermes/hermes-agent/venv/bin/python"
    " hermes-yandex-search-api"
)
COPY_INSTALL = (
    "mkdir -p ~/.hermes/plugins/web\n"
    "cp -r hermes_yandex_search ~/.hermes/plugins/web/yandex\n"
    "hermes plugins enable yandex"
)
#: The copy's contents over the installed one: running COPY_INSTALL again would
#: nest the new copy inside the old, as ``yandex/hermes_yandex_search``.
COPY_UPGRADE = "cp -r hermes_yandex_search/. ~/.hermes/plugins/web/yandex/"
DROPIN_INSTALL = "unzip hermes-yandex-search-plugin-<version>.zip -d ~/.hermes/plugins/web/"
DROPIN_UPGRADE = DROPIN_INSTALL.replace("unzip ", "unzip -o ")
ENABLE = "hermes plugins enable yandex"
ADD_CREDENTIALS = (
    "printf 'YANDEX_API_KEY=%s\\nYANDEX_FOLDER_ID=%s\\n' 'your-api-key' 'your-folder-id'"
    " >> ~/.hermes/.env"
)
SELECT_BACKEND = "hermes config set web.search_backend yandex"

#: A backend Hermes can pick on its own when nothing is selected — Brave's free
#: tier, available as soon as its key is set. What Hermes picks without it
#: varies with the Hermes and what it finds configured (keenable, exa and
#: firecrawl have all been seen), and on a Hermes with no other backend it is
#: the plugin itself; with a rival in place, the selection step cannot be a
#: no-op without the test noticing.
RIVAL_BACKEND = "BRAVE_SEARCH_API_KEY=install-check-not-a-key"

#: Not a README command: the mistake README.md warns about, pointing Hermes at
#: the repository root instead of the plugin directory.
ROOT_INSTALL = GIT_INSTALL.replace("/hermes_yandex_search ", " ")

#: Answers typed at the credential prompts of the Git install. Nothing here
#: ever reaches Yandex: no test calls a tool.
PROMPT_ANSWERS = {
    "YANDEX_API_KEY": "install-check-not-a-key",
    "YANDEX_FOLDER_ID": "install-check-folder",
}

install = pytest.mark.install

# Variables that would let the developer's own setup leak into the commands.
_LEAKY_ENV = re.compile(r"^(YANDEX_|HERMES_|VIRTUAL_ENV$|CONDA_|PYTHONPATH$|PYTHONHOME$)")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"{name} is not set; see the docstring of {Path(__file__).name}")
    return value


def _one(pattern: str) -> Path:
    found = sorted(Path(_required("INSTALL_DIST")).resolve().glob(pattern))
    assert len(found) == 1, f"expected exactly one {pattern} in INSTALL_DIST, found {found}"
    return found[0]


@dataclass
class Home:
    """The account the official Hermes installer set Hermes up in."""

    path: Path
    env: dict[str, str]

    @property
    def hermes_home(self) -> Path:
        return self.path / ".hermes"

    @property
    def dropin_dir(self) -> Path:
        """Where Option B puts the plugin: ``~/.hermes/plugins/web/yandex``."""
        return self.hermes_home / "plugins" / "web" / PLUGIN

    def run(self, command: str, *, answers: str = "", check: bool = True) -> str:
        """Run a shell command as the user would; fail on a non-zero exit if *check*."""
        result = subprocess.run(
            ["bash", "-c", command],
            input=answers,
            env=self.env,
            cwd=self.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
            check=False,
        )
        if check:
            assert result.returncode == 0, (
                f"`{command}` exited {result.returncode}:\n{result.stdout}"
            )
        return result.stdout

    def listed(self) -> list[dict]:
        """Rows for this plugin in ``hermes plugins list``."""
        out = self.run("hermes plugins list --json --no-bundled")
        rows = json.loads(out[out.index("[") :])
        return [row for row in rows if row["name"] == PLUGIN]

    def probe(self) -> dict:
        """What Hermes' own plugin manager loaded; see probe.py."""
        python = hermes_python(self.hermes_home)
        out = self.run(f"'{python}' '{Path(__file__).with_name('probe.py')}'")
        line = next(line for line in reversed(out.splitlines()) if line.startswith("PROBE "))
        report = json.loads(line.removeprefix("PROBE "))
        assert "probe_error" not in report, (
            "probe.py could not read Hermes' state — has Hermes changed its internals?\n"
            + report["probe_error"]
        )
        return report

    def dotenv(self) -> dict[str, str]:
        path = self.hermes_home / ".env"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return dict(line.split("=", 1) for line in lines if "=" in line and line[0] != "#")

    def credentials(self) -> dict[str, str]:
        """This plugin's variables in ``~/.hermes/.env``; the installer writes its own there too."""
        return {key: value for key, value in self.dotenv().items() if key in REQUIRED_ENV}


class _Snapshot:
    """The parts of ``~/.hermes`` an install changes, to put back afterwards."""

    def __init__(self, hermes_home: Path, keep: Path) -> None:
        self.hermes_home = hermes_home
        self.plugins = hermes_home / "plugins"
        self.saved_plugins = keep / "plugins"
        if self.plugins.is_dir():
            shutil.copytree(self.plugins, self.saved_plugins, symlinks=True)
        self.files = {
            name: (hermes_home / name).read_bytes() if (hermes_home / name).exists() else None
            for name in ("config.yaml", ".env")
        }

    def restore(self) -> None:
        shutil.rmtree(self.plugins, ignore_errors=True)
        if self.saved_plugins.is_dir():
            shutil.copytree(self.saved_plugins, self.plugins, symlinks=True)
        for name, content in self.files.items():
            path = self.hermes_home / name
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)


@pytest.fixture
def home(tmp_path: Path):
    if os.environ.get("INSTALL_CHECK_DISPOSABLE_HOME") != "1":
        pytest.fail(
            "these tests install into the real ~/.hermes; set INSTALL_CHECK_DISPOSABLE_HOME=1 "
            "only where that Hermes is a throwaway one (see the module docstring)"
        )
    root = Path.home()
    env = {key: value for key, value in os.environ.items() if not _LEAKY_ENV.match(key)}
    env.update(
        PATH=os.pathsep.join([str(root / ".local" / "bin"), env.get("PATH", "")]),
        COLUMNS="500",
        NO_COLOR="1",
    )
    home = Home(root, env)
    assert home.listed() == [], f"{PLUGIN} is already visible to this Hermes before the install"
    assert home.credentials() == {}, "credentials are already in ~/.hermes/.env"
    snapshot = _Snapshot(home.hermes_home, tmp_path)
    try:
        yield home
    finally:
        snapshot.restore()


def _flat(text: str) -> str:
    return " ".join(text.split())


def _assert_loaded(home: Home, *, source: str) -> None:
    """Hermes lists the plugin as enabled, loads it, and gives the agent its tools."""
    assert [row["status"] for row in home.listed()] == ["enabled"], home.listed()

    report = home.probe()
    loaded = [plugin for plugin in report["plugins"] if plugin["name"] == PLUGIN]
    assert len(loaded) == 1, report["plugins"]
    plugin = loaded[0]
    assert plugin["error"] is None, plugin["error"]
    assert plugin["enabled"], plugin
    assert plugin["source"] == source, plugin
    assert plugin["version"] == VERSION, plugin
    assert plugin["tools"] == len(DEFAULT_TOOLS), plugin

    mine = {name: toolset for name, toolset in report["tools"].items() if toolset == TOOLSET}
    assert set(mine) == DEFAULT_TOOLS, sorted(report["tools"])

    # README.md: with the backend selected, `web_search` now goes through Yandex.
    assert report["web_search"] == {"provider": PLUGIN, "available": True}, report["web_search"]


def _assert_hermes_has_the_dependencies(home: Home) -> None:
    """README.md: Options A and B install no dependencies, and Hermes needs none."""
    home.run(f"'{hermes_python(home.hermes_home)}' -c 'import {', '.join(DEPENDENCIES)}'")


def _select_backend(home: Home) -> None:
    """Run the README's selection step where it has something to decide."""
    home.run(f"echo {RIVAL_BACKEND} >> ~/.hermes/.env")
    unselected = home.probe()["web_search"]
    assert unselected["provider"] != PLUGIN, f"the rival backend did not take over: {unselected}"
    home.run(SELECT_BACKEND)


def test_readme_gives_the_commands_under_test() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    commands = (
        GIT_INSTALL,
        GIT_UPGRADE,
        PYPI_INSTALL,
        COPY_INSTALL,
        COPY_UPGRADE,
        DROPIN_INSTALL,
        DROPIN_UPGRADE,
        ENABLE,
        ADD_CREDENTIALS,
        SELECT_BACKEND,
    )
    for command in commands:
        assert command in readme, f"README.md no longer says:\n{command}"
    assert f"~/.hermes/plugins/web/{PLUGIN}/plugin.yaml" in readme


@install
def test_git_install_asks_for_credentials_loads_and_upgrades(home: Home) -> None:
    ref = f" --ref {_required('INSTALL_REF')}"
    answers = "".join(PROMPT_ANSWERS[name] + "\n" for name in REQUIRED_ENV)
    out = _flat(home.run(GIT_INSTALL + ref, answers=answers))

    assert "may not be a valid Hermes plugin" not in out, out
    for name in REQUIRED_ENV:
        assert f"{name}:" in out, f"the install never asked for {name}:\n{out}"
    assert home.credentials() == PROMPT_ANSWERS
    _select_backend(home)
    _assert_loaded(home, source="user")

    # README.md's upgrade: the same command with --force. The credentials are
    # already there, so nothing is asked again, and the backend stays selected.
    out = _flat(home.run(GIT_UPGRADE + ref))
    for name in REQUIRED_ENV:
        assert f"{name}:" not in out, out
    assert home.credentials() == PROMPT_ANSWERS
    _assert_loaded(home, source="user")


@install
def test_pypi_install_loads(home: Home) -> None:
    if is_pm_install(home.hermes_home):
        pytest.skip(
            "this Hermes runs from environments its package manager builds; README.md gives "
            "the PyPI command only for a Hermes from the 0.21-era installer"
        )
    wheel = _one("*.whl")
    try:
        home.run(PYPI_INSTALL.removesuffix(PROJECT) + str(wheel))
        home.run(ENABLE)
        home.run(ADD_CREDENTIALS)
        _select_backend(home)
        _assert_loaded(home, source="entrypoint")
    finally:
        home.run(
            "~/.hermes/bin/uv pip uninstall --python ~/.hermes/hermes-agent/venv/bin/python "
            + PROJECT,
            check=False,
        )


@install
def test_copy_from_a_clone_loads_and_upgrades(home: Home) -> None:
    _assert_hermes_has_the_dependencies(home)
    clone = home.path / PACKAGE
    shutil.copytree(REPO_ROOT / PACKAGE, clone, ignore=shutil.ignore_patterns("__pycache__"))
    try:
        home.run(COPY_INSTALL)
        home.run(ADD_CREDENTIALS)
        _select_backend(home)
        _assert_loaded(home, source="user")

        # README.md's upgrade: the directory's contents over the installed copy.
        home.run(COPY_UPGRADE)
        assert not (home.dropin_dir / PACKAGE).exists(), "the upgrade nested a second copy"
        _assert_loaded(home, source="user")
    finally:
        shutil.rmtree(clone, ignore_errors=True)


@install
def test_dropin_archive_loads_and_upgrades(home: Home) -> None:
    _assert_hermes_has_the_dependencies(home)
    archive = _one("hermes-yandex-search-plugin-*.zip")
    assert archive.name == f"hermes-yandex-search-plugin-{VERSION}.zip", archive.name
    shutil.copy(archive, home.path / archive.name)
    try:
        home.run(DROPIN_INSTALL.replace("<version>", VERSION))
        assert (home.dropin_dir / "plugin.yaml").is_file()
        home.run(ENABLE)
        home.run(ADD_CREDENTIALS)
        _select_backend(home)
        _assert_loaded(home, source="user")

        # README.md's upgrade: unzip the new archive over the old one.
        home.run(DROPIN_UPGRADE.replace("<version>", VERSION))
        _assert_loaded(home, source="user")
    finally:
        (home.path / archive.name).unlink(missing_ok=True)


@install
def test_repository_root_install_shows_the_documented_symptom(home: Home) -> None:
    """README.md: a warning, no questions, and the plugin listed as not enabled."""
    out = _flat(home.run(f"{ROOT_INSTALL} --ref {_required('INSTALL_REF')}", check=False))

    assert "may not be a valid Hermes plugin" in out, out
    for name in REQUIRED_ENV:
        assert name not in out, out
    assert [row["status"] for row in home.listed()] == ["not enabled"], home.listed()
