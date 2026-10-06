"""Install the plugin into a real Hermes, every way README.md says to.

Nothing here is simulated. The tests run against a Hermes that its official
installer set up in this account — the ``setup-hermes`` action does that in CI —
and run the commands README.md gives, as written. Success is whatever Hermes
reports afterwards: ``hermes plugins list``, and the plugins, tools and
``web_search`` provider its own plugin manager hands the agent (see
``probe.py``, run in Hermes' own Python, which ``hermes_env.py`` finds).

Where the tests depart from the README text, and why:

* the Git install adds ``--ref`` with the commit under test, because the README
  command installs whatever the default branch holds at the time;
* the pinned upgrade starts from the commit of the latest release of this
  plugin, ``INSTALL_PREV_REF``, and moves to the commit under test. That
  release is only the starting point: if it no longer installs on this Hermes,
  the test skips rather than fails, or no fix for it could pass and be released;
* the PyPI install names the wheel about to be published instead of the
  project, so it cannot pick up the release already on PyPI;
* the drop-in archive is the one about to be attached to the release, and its
  ``<version>`` placeholder is filled in;
* the directory copy runs in a fresh copy of the plugin directory, standing in
  for a clone of this repository;
* before an upgrade, the installed copy's manifest is set to version 0.0.0, so
  the version check afterwards proves the upgrade really replaced the files.

The PyPI route applies only to a Hermes in the older layout (its virtualenv in
``~/.hermes/hermes-agent/venv``), the only one README.md gives a PyPI command
for. It runs wherever the installed Hermes has that layout, and is skipped where
pm built it. The ``legacy`` channel, Hermes v2026.9.24, must give the older
layout: there the test fails rather than skips, because the setup is broken.

Each test changes the Hermes it runs against, then puts back what it changed:
the plugin directories, ``config.yaml`` (the enabled plugins and the selected
backend), ``.env``, and a package installed from PyPI. They still install into
a real ``~/.hermes``, so they refuse to run unless
``INSTALL_CHECK_DISPOSABLE_HOME=1`` says that Hermes is a throwaway one.

Deselected by default. The ``Install check`` workflow runs them on every pull
request, every week, and before every release, against Hermes v2026.9.24 (the
``legacy`` channel), the latest Hermes release and Hermes ``main``. To run them
yourself, do it in a disposable container or VM with Hermes installed by its
installer, after building the artifacts the way ``release-build.yml`` does and
pushing the commit under test, which Hermes clones from GitHub::

    INSTALL_CHECK_DISPOSABLE_HOME=1 INSTALL_CHECK_CHANNEL=main INSTALL_DIST=dist \\
    INSTALL_REF="$(git rev-parse HEAD)" \\
    INSTALL_PREV_REF="$(git rev-parse "$(git describe --tags --abbrev=0)^{commit}")" \\
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
#: none of it; README.md says a Hermes set up by its installer normally has both.
DEPENDENCIES = ("httpx", "defusedxml")

# The commands README.md gives. test_readme_gives_the_commands_under_test keeps
# the two in step, so the tests below cannot drift into checking something the
# README does not say.
GIT_INSTALL = (
    "hermes plugins install akinfold/hermes-yandex-search-api/hermes_yandex_search --enable"
)
GIT_UPDATE = "hermes plugins update yandex"
GIT_UPGRADE = GIT_INSTALL + " --force"
#: Moves an install pinned with --ref; ``<commit>`` is a full 40-character SHA.
GIT_REPIN = GIT_UPGRADE + " --ref <commit>"
#: For a Hermes in the older layout only; see README.md, Option C.
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

#: A rival for the plugin, so the README's selection step has something to
#: decide. With nothing selected, Hermes takes the only available backend if
#: there is just one, and otherwise the first available one in its own
#: preference order; keyless free tiers (keenable, exa, firecrawl and others)
#: come in only when neither picks anything. With its credentials set, the
#: plugin can be the only available backend, and selecting it would then change
#: nothing the test could see. Brave's free tier is available as soon as its key is set, and
#: the preference order lists it but not the plugin, so with the rival in place
#: Hermes picks something else until the backend is selected (see
#: ``agent/web_search_registry.py`` in Hermes).
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

    def attempt(
        self, command: str, *, answers: str = "", cwd: Path | None = None
    ) -> tuple[int, str]:
        """Run a shell command as the user would; return its exit status and output."""
        result = subprocess.run(
            ["bash", "-c", command],
            input=answers,
            env=self.env,
            cwd=cwd or self.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
            check=False,
        )
        return result.returncode, result.stdout

    def run(
        self, command: str, *, answers: str = "", check: bool = True, cwd: Path | None = None
    ) -> str:
        """Run a shell command as the user would; fail on a non-zero exit if *check*."""
        status, out = self.attempt(command, answers=answers, cwd=cwd)
        if check:
            assert status == 0, f"`{command}` exited {status}:\n{out}"
        return out

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
        if self.plugins.is_dir():
            shutil.rmtree(self.plugins)
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


def _make_stale(home: Home) -> None:
    """Mark the installed copy as version 0.0.0, so only a real upgrade passes the version check."""
    # The Git install lands in ~/.hermes/plugins/yandex, Option B in plugins/web/yandex.
    places = (home.hermes_home / "plugins" / PLUGIN, home.dropin_dir)
    manifests = [place / "plugin.yaml" for place in places if (place / "plugin.yaml").is_file()]
    assert len(manifests) == 1, f"expected one installed manifest in {places}, found {manifests}"
    text = manifests[0].read_text(encoding="utf-8")
    stale = re.sub(r"(?m)^version:.*$", "version: 0.0.0", text, count=1)
    assert stale != text, "the installed manifest has no version line"
    manifests[0].write_text(stale, encoding="utf-8")


def _assert_loaded(home: Home, *, source: str, version: str | None = VERSION) -> None:
    """Hermes lists the plugin as enabled, loads it, and gives the agent its tools."""
    assert [row["status"] for row in home.listed()] == ["enabled"], home.listed()

    report = home.probe()
    loaded = [plugin for plugin in report["plugins"] if plugin["name"] == PLUGIN]
    assert len(loaded) == 1, report["plugins"]
    plugin = loaded[0]
    assert plugin["error"] is None, plugin["error"]
    assert plugin["enabled"], plugin
    assert plugin["source"] == source, plugin
    if version is None:
        return
    assert plugin["version"] == version, plugin
    assert plugin["tools"] == len(DEFAULT_TOOLS), plugin

    mine = {name: toolset for name, toolset in report["tools"].items() if toolset == TOOLSET}
    assert set(mine) == DEFAULT_TOOLS, sorted(report["tools"])

    # README.md: with the backend selected, `web_search` now goes through Yandex.
    assert report["web_search"] == {"provider": PLUGIN, "available": True}, report["web_search"]


def _assert_pinned(home: Home, commit: str) -> None:
    """``hermes plugins list`` shows the install pinned to *commit*, as ``git pinned@<sha8>``."""
    pin = f"git pinned@{commit.lower()[:8]}"
    assert [row["source"] for row in home.listed()] == [pin], home.listed()


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
        GIT_UPDATE,
        GIT_UPGRADE,
        GIT_REPIN,
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
        # Whole lines: GIT_INSTALL begins GIT_UPGRADE, which begins GIT_REPIN, so
        # a plain substring would survive the shorter command's removal.
        assert re.search(rf"(?m)^{re.escape(command)}$", readme), (
            f"README.md no longer says, on lines of its own:\n{command}"
        )
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
    _make_stale(home)
    out = _flat(home.run(GIT_UPGRADE + ref))
    for name in REQUIRED_ENV:
        assert f"{name}:" not in out, out
    assert home.credentials() == PROMPT_ANSWERS
    _assert_loaded(home, source="user")


@install
def test_git_install_pinned_with_ref_moves_only_with_a_new_ref(home: Home) -> None:
    """README.md: ``--force`` alone keeps a pinned install on its commit; ``--ref`` moves it.

    The install starts pinned to the latest release of this plugin and moves to
    the commit under test. With no earlier commit to start from, it starts on the
    commit under test, and the move is skipped.

    The latest release is setup here, not under test: when Hermes has changed so
    that its install exits non-zero, the test skips. Failing would block every
    fix, and the release of one, since publishing waits for this check. Nor does
    the test check that this release loads; only the commit under test has to.
    """
    ref = _required("INSTALL_REF")
    previous = os.environ.get("INSTALL_PREV_REF", "")
    start = previous if previous and previous != ref else ref
    answers = "".join(PROMPT_ANSWERS[name] + "\n" for name in REQUIRED_ENV)
    command = f"{GIT_INSTALL} --ref {start}"
    if start == ref:
        home.run(command, answers=answers)
    else:
        status, out = home.attempt(command, answers=answers)
        if status != 0:
            pytest.skip(
                f"the latest release, {start[:8]}, no longer installs on this Hermes "
                f"(`{command}` exited {status}), so the pin move is not checked:\n{out}"
            )
    _assert_pinned(home, start)
    # Selected before the moves, so the check at the end shows the move kept it.
    _select_backend(home)

    out = _flat(home.run(GIT_UPDATE, check=False))
    assert "is pinned" in out, f"`{GIT_UPDATE}` did not refuse a pinned install:\n{out}"
    _assert_pinned(home, start)

    # The trap README.md warns about: the plain upgrade installs the pinned commit again.
    _make_stale(home)
    home.run(GIT_UPGRADE)
    _assert_pinned(home, start)
    [plugin] = [plugin for plugin in home.probe()["plugins"] if plugin["name"] == PLUGIN]
    assert plugin["version"] != "0.0.0", f"`{GIT_UPGRADE}` replaced nothing: {plugin}"

    if start == ref:
        pytest.skip(
            "INSTALL_PREV_REF is unset or is the commit under test, so there is no earlier "
            "commit to move the pin from; checked only that --force keeps the pin"
        )
    _make_stale(home)
    home.run(GIT_REPIN.replace("<commit>", ref))
    assert home.credentials() == PROMPT_ANSWERS
    _assert_pinned(home, ref)
    _assert_loaded(home, source="user")


@install
def test_git_install_updates_with_hermes_plugins_update(home: Home) -> None:
    """README.md's usual upgrade for Option A: Hermes' own ``plugins update``.

    It installs from the default branch, not the commit under test, so this
    checks that the command upgrades this plugin's kind of install, not what it
    installs: after it, the manifest marked 0.0.0 must be gone.
    """
    answers = "".join(PROMPT_ANSWERS[name] + "\n" for name in REQUIRED_ENV)
    home.run(GIT_INSTALL, answers=answers)
    _make_stale(home)
    home.run(GIT_UPDATE)
    [plugin] = [plugin for plugin in home.probe()["plugins"] if plugin["name"] == PLUGIN]
    assert plugin["version"] != "0.0.0", f"`{GIT_UPDATE}` replaced nothing: {plugin}"
    _assert_loaded(home, source="user", version=None)


@install
def test_pypi_install_loads(home: Home) -> None:
    if is_pm_install(home.hermes_home):
        if os.environ.get("INSTALL_CHECK_CHANNEL") == "legacy":
            pytest.fail(
                "the legacy channel installs Hermes v2026.9.24, whose installer builds the "
                "older layout, yet this Hermes runs from pm-built environments: the Hermes "
                "setup is broken, and Option C goes unchecked"
            )
        pytest.skip(
            "this Hermes runs from environments its package manager builds; README.md gives "
            "the PyPI command only for a Hermes in the older layout"
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
def test_copy_from_a_clone_loads_and_upgrades(home: Home, tmp_path: Path) -> None:
    _assert_hermes_has_the_dependencies(home)
    clone = tmp_path / "clone"
    shutil.copytree(
        REPO_ROOT / PACKAGE, clone / PACKAGE, ignore=shutil.ignore_patterns("__pycache__")
    )

    home.run(COPY_INSTALL, cwd=clone)
    home.run(ADD_CREDENTIALS)
    _select_backend(home)
    _assert_loaded(home, source="user")

    # README.md's upgrade: the directory's contents over the installed copy.
    _make_stale(home)
    home.run(COPY_UPGRADE, cwd=clone)
    assert not (home.dropin_dir / PACKAGE).exists(), "the upgrade nested a second copy"
    _assert_loaded(home, source="user")


@install
def test_dropin_archive_loads_and_upgrades(home: Home, tmp_path: Path) -> None:
    _assert_hermes_has_the_dependencies(home)
    archive = _one("hermes-yandex-search-plugin-*.zip")
    assert archive.name == f"hermes-yandex-search-plugin-{VERSION}.zip", archive.name
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    shutil.copy(archive, downloads / archive.name)

    home.run(DROPIN_INSTALL.replace("<version>", VERSION), cwd=downloads)
    assert (home.dropin_dir / "plugin.yaml").is_file()
    home.run(ENABLE)
    home.run(ADD_CREDENTIALS)
    _select_backend(home)
    _assert_loaded(home, source="user")

    # README.md's upgrade: unzip the new archive over the old one.
    _make_stale(home)
    home.run(DROPIN_UPGRADE.replace("<version>", VERSION), cwd=downloads)
    _assert_loaded(home, source="user")


@install
def test_repository_root_install_shows_the_documented_symptom(home: Home) -> None:
    """README.md: a warning, no questions, and the plugin listed as not enabled."""
    out = _flat(home.run(f"{ROOT_INSTALL} --ref {_required('INSTALL_REF')}", check=False))

    assert "may not be a valid Hermes plugin" in out, out
    for name in REQUIRED_ENV:
        assert name not in out, out
    assert [row["status"] for row in home.listed()] == ["not enabled"], home.listed()
