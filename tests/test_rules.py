# -*- coding: utf-8 -*-
"""The package's own rules: standard library only, ASCII only, documented."""

import ast
import os
import sys

import pytest

import quietlaunch

PKG = os.path.dirname(os.path.abspath(quietlaunch.__file__))
SOURCES = sorted(os.path.join(PKG, f) for f in os.listdir(PKG)
                 if f.endswith(".py"))


def _tree(path):
    """Parse one package source."""
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), path)


@pytest.mark.skipif(sys.version_info < (3, 10),
                    reason="sys.stdlib_module_names is 3.10+")
@pytest.mark.parametrize("path", SOURCES, ids=os.path.basename)
def test_standard_library_only(path):
    """The supervisor must not fail, so it imports nothing it could lack."""
    bad = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top not in sys.stdlib_module_names and top != "__future__":
                bad.append(name)
    assert not bad


@pytest.mark.parametrize("path", SOURCES, ids=os.path.basename)
def test_ascii_only(path):
    """Windows picks cp1252 for a redirected stdout; nothing here may need more."""
    with open(path, "rb") as f:
        data = f.read()
    bad = [i for i, b in enumerate(data) if b > 127]
    assert not bad, "non-ASCII byte at offset %d" % bad[0]


@pytest.mark.parametrize("path", SOURCES, ids=os.path.basename)
def test_every_definition_has_a_docstring(path):
    """The code is mostly Windows traps; a definition without its why gets
    "simplified" back into the trap."""
    tree = _tree(path)
    missing = [n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.ClassDef))
               and not ast.get_docstring(n)]
    assert ast.get_docstring(tree)
    assert not missing


def test_version_is_the_one_pyproject_reads():
    """pyproject.toml takes its version from `quietlaunch.__version__`."""
    root = os.path.dirname(PKG)
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
        text = f.read()
    assert 'version = { attr = "quietlaunch.__version__" }' in text
    assert quietlaunch.__version__.count(".") == 2
