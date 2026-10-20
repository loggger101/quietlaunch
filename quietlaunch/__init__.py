# -*- coding: utf-8 -*-
"""quietlaunch: start a Streamlit app with no console window.

A small control window replaces the console: it says what is happening while
the server boots, opens the browser once the port answers, reuses the server it
started earlier, and stops the whole process tree when it is closed. Standard
library only. See `quietlaunch.launcher` for the design and the traps behind it.
"""

# The one place the version is written: pyproject.toml reads it from here, and
# a consumer pinning a git tag compares the tag against it.
__version__ = "0.1.0"

from .launcher import LaunchConfig, launch, main  # noqa: E402

__all__ = ["LaunchConfig", "launch", "main", "__version__"]
