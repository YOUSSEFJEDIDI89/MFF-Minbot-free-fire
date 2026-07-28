# Makefile for the VortexVPN C++ crypto accelerator.
#
# Requirements: python3-dev, pybind11-dev, libssl-dev
#   Debian/Ubuntu:  sudo apt install python3-dev pybind11-dev libssl-dev
#   Fedora:         sudo dnf install python3-devel pybind11-devel openssl-devel
#
# Usage:
#   make            # build the extension
#   make test       # round-trip test
#   make clean

PYTHON      ?= python3
PYBIND11    ?= $(shell $(PYTHON) -c "import pybind11; print(pybind11.get_include())" 2>/dev/null)
PY_INCLUDE  ?= $(shell $(PYTHON) -c "import sysconfig; print(sysconfig.get_path('include'))")
CXX         ?= c++
CXXFLAGS    := -O3 -std=c++17 -Wall -Wextra -shared -fPIC \
               -I$(PY_INCLUDE) -I$(PYBIND11) \
               $(shell pkg-config --cflags openssl 2>/dev/null)
LDFLAGS     := $(shell pkg-config --libs openssl 2>/dev/null)

EXT_SUFFIX  := $(shell $(PYTHON) -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")
TARGET      := vortex_accel$(EXT_SUFFIX)

.PHONY: all test clean install

all: $(TARGET)

$(TARGET): vortex_accel.cpp
	@echo "[CXX] $< -> $@"
	@$(CXX) $(CXXFLAGS) $< -o $@ $(LDFLAGS)

test: $(TARGET)
	@$(PYTHON) -c "import sys; sys.path.insert(0, '.'); \
		import vortex_accel, os; \
		k=os.urandom(32); n=os.urandom(12); \
		ct=vortex_accel.aes_gcm_encrypt(k,n,b'hello world',b''); \
		pt=vortex_accel.aes_gcm_decrypt(k,n,ct,b''); \
		assert pt==b'hello world', 'roundtrip failed'; \
		print('OK: AES-256-GCM round-trip works:', pt.decode())"

install: $(TARGET)
	@$(PYTHON) -c "import site, shutil, os; \
		d=site.getusersitepackages(); os.makedirs(d, exist_ok=True); \
		shutil.copy('$(TARGET)', d); print('installed to', d)"

clean:
	rm -f $(TARGET)
