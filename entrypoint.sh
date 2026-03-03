#!/bin/bash
# Ensure .env files exist (create empty if not mounted or mounted as directory)
[ ! -f /app/.env.base ] && touch /app/.env.base
[ ! -f /app/.env ] && touch /app/.env

exec "$@"
