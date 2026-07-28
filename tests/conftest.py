"""Shared pytest config."""
import sys
import pathlib

# Make `vortexvpn` package importable when running from repo root
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
