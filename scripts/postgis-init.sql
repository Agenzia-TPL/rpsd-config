\connect rpsd

-- Enable PostGIS extension on the default database for spatial types.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Optionally prepare a dedicated schema for Django models if you plan to use one.
-- CREATE SCHEMA IF NOT EXISTS django;
