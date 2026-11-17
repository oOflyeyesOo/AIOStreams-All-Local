-- Automatically create databases for Zilean and AIOMetadata on first Postgres initialization
SELECT 'CREATE DATABASE zilean' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zilean')\gexec
SELECT 'CREATE DATABASE aiometadata' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'aiometadata')\gexec
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aio') THEN CREATE USER aio WITH PASSWORD 'aio_local_secret' SUPERUSER; END IF; END $$;
