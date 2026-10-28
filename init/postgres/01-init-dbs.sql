-- Automatically create databases for Zilean, MediaFusion, and AIOMetadata on first Postgres initialization
SELECT 'CREATE DATABASE zilean' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zilean')\gexec
SELECT 'CREATE DATABASE mediafusion' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mediafusion')\gexec
SELECT 'CREATE DATABASE aiometadata' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'aiometadata')\gexec
