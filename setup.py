"""Packaging config so `pip install -e .` exposes a `vortexvpn` CLI command.

NOTE: `cryptography` is NOT a hard dependency because it cannot be built
on some platforms (notably Termux / Android aarch64 — no Rust toolchain).
Instead, VortexVPN auto-detects which crypto backend is available:
  - `cryptography` (preferred on desktop Linux)
  - `pycryptodome`  (works on Termux/Android)

Install whichever you prefer:
  pip install -e .                       # no crypto deps installed
  pip install -e ".[crypto]"             # adds cryptography
  pip install -e ".[termux]"             # adds pycryptodome (for Termux)
"""
import os
import sys
from setuptools import setup, find_packages


def _is_termux() -> bool:
    """Detect Termux/Android environment."""
    prefix = os.environ.get("PREFIX", "")
    if "com.termux" in prefix:
        return True
    if os.path.isdir("/data/data/com.termux"):
        return True
    return False


# Pick the right crypto extra based on platform
if _is_termux():
    _crypto_extra = ["pycryptodome>=3.20"]
else:
    _crypto_extra = ["cryptography>=42,<46"]


setup(
    name="vortexvpn",
    version="1.0.0",
    description="High-performance multi-language VPN server platform",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.10",
    # Only Flask is a hard dep — crypto is auto-detected at runtime
    install_requires=[
        "flask>=3.0,<4.0",
        "werkzeug>=3.0,<4.0",
    ],
    extras_require={
        "crypto":  _crypto_extra,                   # auto-pick based on platform
        "termux":  ["pycryptodome>=3.20"],          # explicit Termux support
        "desktop": ["cryptography>=42,<46"],        # explicit desktop support
        "argon2":  ["argon2-cffi>=23.1"],           # for Argon2id password hashing
        "dev":     ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov>=5.0"],
        "prod":    ["gunicorn>=22.0"],
    },
    entry_points={
        "console_scripts": [
            "vortexvpn = vortexvpn.cli:main",
        ],
    },
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Operating System :: POSIX :: Linux",
        "Topic :: System :: Networking",
    ],
)
