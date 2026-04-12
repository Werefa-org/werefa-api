#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python werefa/backend_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python werefa/initial_data.py
