-- 002_roles_and_privs.sql (fixed, idempotent)

BEGIN;

-- 1) 角色先创建（幂等）
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ingest') THEN
    CREATE ROLE ingest NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent') THEN
    CREATE ROLE agent NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'read_only') THEN
    CREATE ROLE read_only NOINHERIT;
  END IF;
END$$;

-- 2) 架构与基础授权
CREATE SCHEMA IF NOT EXISTS derived;

REVOKE ALL ON SCHEMA core    FROM PUBLIC;
REVOKE ALL ON SCHEMA derived FROM PUBLIC;

GRANT USAGE ON SCHEMA core    TO ingest, agent, read_only;
GRANT USAGE ON SCHEMA derived TO agent, read_only;
GRANT CREATE ON SCHEMA derived TO agent;

-- 3) 表级权限
GRANT SELECT, INSERT ON core.events TO ingest;
GRANT SELECT         ON core.events TO agent, read_only;

-- 4) 事件字典可读（让看板/审计能读事件定义）
GRANT SELECT ON core.event_type_registry TO ingest, agent, read_only;

-- 5) 默认权限（derived 下新表默认 read_only 可读）
ALTER DEFAULT PRIVILEGES IN SCHEMA derived
  GRANT SELECT ON TABLES TO read_only;
ALTER DEFAULT PRIVILEGES FOR ROLE agent IN SCHEMA derived
  GRANT SELECT ON TABLES TO read_only;

-- 6) 示例用户（幂等）
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ingest_user') THEN
    CREATE USER ingest_user WITH PASSWORD 'ingest_pwd';
    GRANT ingest TO ingest_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='agent_user') THEN
    CREATE USER agent_user WITH PASSWORD 'agent_pwd';
    GRANT agent TO agent_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ro_user') THEN
    CREATE USER ro_user WITH PASSWORD 'ro_pwd';
    GRANT read_only TO ro_user;
  END IF;
END$$;

COMMIT;
