-- Runs once on first Postgres boot (docker-entrypoint-initdb.d).
-- pgvector powers the knowledge base from Day 5 onward.
CREATE EXTENSION IF NOT EXISTS vector;
