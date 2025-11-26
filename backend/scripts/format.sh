#!/bin/sh -e
set -x

ruff check werefa --fix
ruff format werefa
