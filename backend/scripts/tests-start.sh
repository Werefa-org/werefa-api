#! /usr/bin/env bash
set -e
set -x

python werefa/tests_pre_start.py

bash scripts/test.sh "$@"
