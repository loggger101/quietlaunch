# -*- coding: utf-8 -*-
"""The package's own rules: standard library only, ASCII only, documented.

The rules are samebytes' (`samebytes.source`, `samebytes.docs`), the one copy
the repositories in this family share; what they read is this package's.
"""

import dataclasses
import os

import pytest
from samebytes import docs, source

import quietlaunch

PKG = os.path.dirname(os.path.abspath(quietlaunch.__file__))
ROOT = os.path.dirname(PKG)
SOURCES = sorted(os.path.join(PKG, f) for f in os.listdir(PKG)
                 if f.endswith(".py"))


def test_sources_found():
    """The rules below read real files, not an empty directory."""
    assert {os.path.basename(p) for p in SOURCES} >= {"__init__.py", "__main__.py",
                                                     "launcher.py"}


@pytest.mark.parametrize("path", SOURCES, ids=os.path.basename)
def test_standard_library_only(path):
    """The supervisor must not fail, so it imports nothing it could lack."""
    assert source.imports(ROOT, [path])[0] == []


@pytest.mark.parametrize("path", SOURCES, ids=os.path.basename)
def test_ascii_only(path):
    """Windows picks cp1252 for a redirected stdout; nothing here may need more."""
    assert source.non_ascii(ROOT, [path]) == ([], 1)


@pytest.mark.parametrize("path", SOURCES, ids=os.path.basename)
def test_every_definition_has_a_docstring(path):
    """The code is mostly Windows traps; a definition without its why gets
    "simplified" back into the trap."""
    bad, n = source.docstrings(ROOT, [path])
    assert bad == [] and n >= 1


def test_version_is_the_one_pyproject_reads():
    """pyproject.toml takes its version from `quietlaunch.__version__`."""
    assert source.version_written_once(ROOT, "quietlaunch") == ([], 1)


def test_every_config_field_has_help():
    """Every `LaunchConfig` field carries a help comment.

    Read by samebytes' `source.field_docs`: the block directly above a field,
    to the first blank line, banner or bare rule, plus a trailing comment. A
    block explains only the field below it, so `port_tries`, under the
    comment written for both port fields, had none until this test.
    """
    from quietlaunch.launcher import LaunchConfig
    fields = [f.name for f in dataclasses.fields(LaunchConfig)]
    bad, n = source.missing_help(ROOT, "quietlaunch/launcher.py", "LaunchConfig", fields=fields)
    assert bad == [] and n == len(fields), "; ".join(bad)


def test_git_pins_agree():
    """Every `github.com/loggger101/<repo>@<ref>` names one ref per repository.

    samebytes is pinned in pyproject's test extra and in CI's hooks job; the
    hooks job sat on v0.1.0 while the test extra moved to v0.3.0. CHANGELOG is
    left out: an old pin there is history.
    """
    files = ["pyproject.toml", ".github/workflows/tests.yml", "README.md", "CLAUDE.md"]
    bad, n = docs.pins(ROOT, files, "loggger101")
    assert bad == [] and n >= 3, "; ".join(bad)
