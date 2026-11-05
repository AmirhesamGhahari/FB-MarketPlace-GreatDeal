#!/usr/bin/env bash
# Builds the website API Lambda package into api/build/lambda (source + Linux arm64 dependencies).
# Terraform (infra/terraform/modules/api) zips that folder, so run this before `terraform apply`
# whenever the API code or its dependencies change.
#
# Needs: python3 (3.11+, only to read pyproject.toml) and pip. Dependencies are downloaded as
# prebuilt Linux arm64 wheels, so this works from a Mac and needs no Docker.
set -euo pipefail

cd "$(dirname "$0")"
BUILD_DIR="build/lambda"

rm -rf build
mkdir -p "$BUILD_DIR"

# Runtime dependencies come from pyproject.toml (the "dev" extra, e.g. uvicorn, is not included).
python3 -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
  > build/requirements.txt

python3 -m pip install \
  --requirement build/requirements.txt \
  --target "$BUILD_DIR" \
  --platform manylinux2014_aarch64 \
  --platform manylinux_2_28_aarch64 \
  --python-version 3.12 \
  --implementation cp \
  --only-binary=:all: \
  --upgrade \
  --quiet

cp -R src/fb_marketplace_api "$BUILD_DIR/"
find "$BUILD_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "Built $BUILD_DIR ($(du -sh "$BUILD_DIR" | cut -f1) unzipped). Lambda's limit is 250 MB unzipped."
