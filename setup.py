"""Packaging config so `pip install -e .` exposes a `vortexvpn` CLI command."""
from setuptools import setup, find_packages

setup(
    name="vortexvpn",
    version="1.0.0",
    description="High-performance multi-language VPN server platform",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.10",
    install_requires=[
        "cryptography>=42,<46",
        "flask>=3.0,<4.0",
        "werkzeug>=3.0,<4.0",
        "argon2-cffi>=23.1",
    ],
    extras_require={
        "dev": ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-cov>=5.0"],
        "prod": ["gunicorn>=22.0"],
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
