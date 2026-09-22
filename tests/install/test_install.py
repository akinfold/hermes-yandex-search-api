"""Install the plugin into a real Hermes, every way README.md says to.

Nothing here is simulated. Each test lays out a fresh home directory the way
the official Hermes installer does — the Hermes checkout and its virtualenv
under ``~/.hermes/hermes-agent``, Hermes' own ``uv`` at ``~/.hermes/bin/uv``,
the ``hermes`` launcher in ``~/.local/bin`` — and runs the commands README.md
gives, as written, with ``HOME`` pointing there. Success is whatever Hermes
reports afterwards: ``hermes plugins list``, and the plugins and tools its own
plugin manager hands the agent (see ``probe.py``).

Where the tests depart from the README text, and why:

* the Git install adds ``--ref`` with the commit under test, because the README
  command installs whatever the default branch holds at the time;
* the PyPI install names the wheel about to be published instead of the
  project, so it cannot pick up the release already on PyPI;
* the drop-in archive is the one about to be attached to the release, and its
  ``<version>`` placeholder is filled in;
* the directory copy runs in a fresh copy of the plugin directory, standing in
  for a clone of this repository.

Deselected by default. The ``Install check`` workflow runs it before every
release, against the latest Hermes release and against Hermes ``main``, which
is what the installer checks out. To run it locally, build the artifacts the
way ``release-build.yml`` does, then point it at a Hermes checkout that has its
virtualenv in ``venv/``, at a ``uv`` binary, and at a commit GitHub has::

    HERMES_CHECKOUT=~/.hermes/hermes-agent UV="$(command -v uv)" \\
    INSTALL_DIST=dist INSTALL_REF="$(git rev-parse HEAD)" \\
    python -m pytest -m install
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

# The commands README.md gives. test_readme_gives_the_commands_under_test keeps
# the two in step, so the tests below cannot drift into checking something the
# README does not say.
GIT_INSTALL = (
    "hermes plugins install akinfold/hermes-yandex-search-api/hermes_yandex_search --enable"
)
PYPI_INSTALL = (
    "~/.hermes/bin/uv pip install --python ~/.hermes/hermes-agent/venv/bin/python"
    " hermes-yandex-search-api"
)
COPY_INSTALL = (
    "mkdir -p ~/.hermes/plugins/web\n"
    "cp -r hermes_yandex_search ~/.hermes/plugins/web/yandex\n"
    "hermes plugins enable yandex"
)
DROPIN_INSTALL = "unzip hermes-yandex-search-plugin-<version>.zip -d ~/.hermes/plugins/web/"
ENABLE = "hermes plugins enable yandex"
ADD_CREDENTIALS = (
    "printf 'YANDEX_API_KEY=%s\\nYANDEX_FOLDER_ID=%s\\n' 'your-api-key' 'your-folder-id'"
    " >> ~/.hermes/.env"
)
SELECT_BACKEND = "hermes config set web.search_backend yandex"

#: A backend Hermes picks on its own when nothing is selected — Brave's free
#: tier, available as soon as its key is set. Left alone, Hermes would pick the
#: plugin anyway, having no other backend, and the selection step could be a
#: no-op without any test noticing.
RIVAL_BACKEND = "BRAVE_SEARCH_API_KEY=install-check-not-a-key"
#: What README.md says to run if the plugin fails to load for want of defusedxml.
ADD_DEFUSEDXML = (
    "~/.hermes/bin/uv pip install --python ~/.hermes/hermes-agent/venv/bin/python 'defusedxml>=0.7'"
)

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

# Variables that would let the developer's own setup leak into the sandbox.
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
    """A home directory laid out like the official Hermes installer's."""

    path: Path
    env: dict[str, str]

    @property
    def hermes_home(self) -> Path:
        return self.path / ".hermes"

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
        python = self.hermes_home / "hermes-agent" / "venv" / "bin" / "python"
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


@pytest.fixture
def home(tmp_path: Path) -> Home:
    checkout = Path(_required("HERMES_CHECKOUT")).expanduser().resolve()
    uv = Path(_required("UV")).expanduser().resolve()
    root = tmp_path / "home"
    (root / ".hermes" / "bin").mkdir(parents=True)
    (root / ".hermes" / "bin" / "uv").symlink_to(uv)
    (root / ".hermes" / "hermes-agent").symlink_to(checkout)
    (root / ".local" / "bin").mkdir(parents=True)
    (root / ".local" / "bin" / "hermes").symlink_to(checkout / "venv" / "bin" / "hermes")

    env = {key: value for key, value in os.environ.items() if not _LEAKY_ENV.match(key)}
    env.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
    env.update(
        HOME=str(root),
        HERMES_HOME=str(root / ".hermes"),
        PATH=os.pathsep.join([str(root / ".local" / "bin"), env.get("PATH", "")]),
        COLUMNS="500",
        NO_COLOR="1",
    )
    home = Home(root, env)
    assert home.listed() == [], f"{PLUGIN} is already visible to this Hermes before the install"
    return home


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
        PYPI_INSTALL,
        COPY_INSTALL,
        DROPIN_INSTALL,
        ENABLE,
        ADD_CREDENTIALS,
        SELECT_BACKEND,
        ADD_DEFUSEDXML,
    )
    for command in commands:
        assert command in readme, f"README.md no longer says:\n{command}"
    assert f"~/.hermes/plugins/web/{PLUGIN}/plugin.yaml" in readme


@install
def test_git_install_asks_for_credentials_and_loads(home: Home) -> None:
    answers = "".join(PROMPT_ANSWERS[name] + "\n" for name in REQUIRED_ENV)
    out = _flat(home.run(f"{GIT_INSTALL} --ref {_required('INSTALL_REF')}", answers=answers))

    assert "may not be a valid Hermes plugin" not in out, out
    for name in REQUIRED_ENV:
        assert f"{name}:" in out, f"the install never asked for {name}:\n{out}"
    assert home.dotenv() == PROMPT_ANSWERS
    _select_backend(home)
    _assert_loaded(home, source="user")


@install
def test_pypi_install_loads(home: Home) -> None:
    wheel = _one("*.whl")
    try:
        home.run(PYPI_INSTALL.removesuffix(PROJECT) + str(wheel))
        home.run(ENABLE)
        home.run(ADD_CREDENTIALS)
        _select_backend(home)
        _assert_loaded(home, source="entrypoint")
    finally:
        # One virtualenv serves every test in a local run; leave it as found.
        home.run(
            "~/.hermes/bin/uv pip uninstall --python ~/.hermes/hermes-agent/venv/bin/python "
            + PROJECT,
            check=False,
        )


@install
def test_copy_from_a_clone_loads(home: Home) -> None:
    shutil.copytree(
        REPO_ROOT / PACKAGE,
        home.path / PACKAGE,
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    home.run(COPY_INSTALL)
    home.run(ADD_CREDENTIALS)
    _select_backend(home)
    # The copy brings no dependencies; a standard Hermes already has them.
    _assert_loaded(home, source="user")


@install
def test_dropin_archive_loads(home: Home) -> None:
    archive = _one("hermes-yandex-search-plugin-*.zip")
    assert archive.name == f"hermes-yandex-search-plugin-{VERSION}.zip", archive.name
    shutil.copy(archive, home.path / archive.name)

    home.run(DROPIN_INSTALL.replace("<version>", VERSION))
    assert (home.hermes_home / "plugins" / "web" / PLUGIN / "plugin.yaml").is_file()
    home.run(ENABLE)
    home.run(ADD_CREDENTIALS)
    _select_backend(home)
    _assert_loaded(home, source="user")
    # The README's remedy for a Hermes that lacks defusedxml must itself work.
    home.run(ADD_DEFUSEDXML)


@install
def test_repository_root_install_shows_the_documented_symptom(home: Home) -> None:
    """README.md: it looks like success, asks for nothing, and lists as not enabled."""
    out = _flat(home.run(f"{ROOT_INSTALL} --ref {_required('INSTALL_REF')}"))

    assert "may not be a valid Hermes plugin" in out, out
    for name in REQUIRED_ENV:
        assert name not in out, out
    assert [row["status"] for row in home.listed()] == ["not enabled"], home.listed()
