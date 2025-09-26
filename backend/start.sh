#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Run the database migration
echo "Attempting database migration..."
python migrate.py

# Start the Uvicorn server
echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
