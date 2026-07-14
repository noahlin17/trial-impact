#!/usr/bin/env bash
# Build fpocket from a pinned source tag and install it to a prefix.
#
# fpocket (geometric pocket detection) is the Tier-C fallback for the docking box when
# no drug-bound co-crystal is available. It is NOT on conda-forge/bioconda, so it cannot
# live in environment-sim.yml / the conda lock; this script builds it deterministically
# from source instead. Invoked by the environment blueprint and reproducible locally.
#
# Usage: install_fpocket.sh [PREFIX]   (PREFIX defaults to /usr/local)
set -euo pipefail

FPOCKET_TAG="${FPOCKET_TAG:-4.2.2}"
PREFIX="${1:-/usr/local}"
SRC="${FPOCKET_SRC:-/tmp/fpocket-${FPOCKET_TAG}}"

if command -v fpocket >/dev/null 2>&1; then
  echo "fpocket already on PATH: $(command -v fpocket)"; exit 0
fi

# Build deps: fpocket needs a C toolchain and libnetcdf.
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq build-essential libnetcdf-dev git
fi

rm -rf "$SRC"
git clone --depth 1 --branch "$FPOCKET_TAG" https://github.com/Discngine/fpocket.git "$SRC"
# Build serially: the fpocket Makefile has an install-before-link race under -j.
make -C "$SRC"
test -x "$SRC/bin/fpocket" || { echo "fpocket build did not produce bin/fpocket" >&2; exit 1; }
sudo make -C "$SRC" PREFIX="$PREFIX" install
command -v fpocket >/dev/null 2>&1 || { echo "fpocket not on PATH after install" >&2; exit 1; }
echo "fpocket installed: $(command -v fpocket)"
