-- Automatically create databases for Zilean, AIOMetadata, and Sootio on first Postgres initialization
SELECT 'CREATE DATABASE zilean' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zilean')\gexec
SELECT 'CREATE DATABASE aiometadata' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'aiometadata')\gexec
SELECT 'CREATE DATABASE sootio' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'sootio')\gexec
