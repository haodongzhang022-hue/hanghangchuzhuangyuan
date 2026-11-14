-- ⚠️ 本文件由 scripts/export_industry_db.py 生成，请勿手改。
-- 数据（10-data.sql）由 `industry export` 生成，不随结构进版本库。
CREATE TABLE IF NOT EXISTS "dataset_meta" (
  "key" TEXT,
  "value" TEXT,
  PRIMARY KEY ("key")
);

CREATE TABLE IF NOT EXISTS "partition" (
  "id" TEXT,
  "name" TEXT,
  "aliases" TEXT,
  "status" TEXT,
  "unit_id" TEXT,
  "priority" TEXT,
  "gdp_cny" INTEGER,
  "gdp_kind" TEXT,
  "gdp_confidence" TEXT,
  "gdp_scope" TEXT,
  "gdp_source" TEXT,
  "provider_ai" REAL,
  "provider_hybrid" REAL,
  "provider_human" REAL,
  "provider_ai_declared" REAL,
  "provider_hybrid_declared" REAL,
  "provider_human_declared" REAL,
  "provider_ai_estimated" REAL,
  "provider_hybrid_estimated" REAL,
  "provider_human_estimated" REAL,
  "access_paid_direct" REAL,
  "access_non_market" REAL,
  "access_org_internal" REAL,
  "access_household" REAL,
  "employment_wan" REAL,
  "member_count" INTEGER,
  "axes" TEXT,
  "axis_edges" TEXT,
  "planned_roles" TEXT,
  "demand_side" TEXT,
  "cluster_basis" TEXT,
  "channels" TEXT,
  "note" TEXT,
  PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "occupation" (
  "code" TEXT,
  "id" TEXT,
  "name" TEXT,
  "deliverable" TEXT,
  "provider" TEXT,
  "billing" TEXT,
  "access" TEXT,
  "baseline" INTEGER,
  "gb_code" TEXT,
  "gb_name" TEXT,
  "note" TEXT,
  PRIMARY KEY ("id"),
  UNIQUE ("code")
);

CREATE TABLE IF NOT EXISTS "membership" (
  "occupation" TEXT,
  "partition" TEXT,
  "axis" TEXT,
  "weight" REAL,
  "unit_role" TEXT,
  PRIMARY KEY ("occupation", "partition", "axis"),
  FOREIGN KEY ("occupation") REFERENCES "occupation"("id"),
  FOREIGN KEY ("partition") REFERENCES "partition"("id")
);

CREATE TABLE IF NOT EXISTS "gb_catalog" (
  "code" TEXT,
  "name" TEXT,
  "gbm" TEXT,
  "major" TEXT,
  "middle" TEXT,
  "minor" TEXT,
  "marks" TEXT,
  "path" TEXT,
  "desc" TEXT,
  PRIMARY KEY ("code")
);

CREATE INDEX IF NOT EXISTS "idx_partition_status" ON "partition" ("status");

CREATE INDEX IF NOT EXISTS "idx_partition_kind" ON "partition" ("gdp_kind");

CREATE INDEX IF NOT EXISTS "idx_occupation_provider" ON "occupation" ("provider");

CREATE INDEX IF NOT EXISTS "idx_occupation_baseline" ON "occupation" ("baseline");

CREATE INDEX IF NOT EXISTS "idx_membership_partition" ON "membership" ("partition");

CREATE INDEX IF NOT EXISTS "idx_membership_occupation" ON "membership" ("occupation");
