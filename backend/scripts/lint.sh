#!/usr/bin/env bash

set -e
set -x

mypy werefa
ty check werefa
ruff check werefa
ruff format werefa --check
