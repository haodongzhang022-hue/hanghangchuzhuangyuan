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
  "provider_ai" DOUBLE PRECISION,
  "provider_hybrid" DOUBLE PRECISION,
  "provider_human" DOUBLE PRECISION,
  "provider_ai_declared" DOUBLE PRECISION,
  "provider_hybrid_declared" DOUBLE PRECISION,
  "provider_human_declared" DOUBLE PRECISION,
  "provider_ai_estimated" DOUBLE PRECISION,
  "provider_hybrid_estimated" DOUBLE PRECISION,
  "provider_human_estimated" DOUBLE PRECISION,
  "access_paid_direct" DOUBLE PRECISION,
  "access_non_market" DOUBLE PRECISION,
  "access_org_internal" DOUBLE PRECISION,
  "access_household" DOUBLE PRECISION,
  "employment_wan" DOUBLE PRECISION,
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
  "weight" DOUBLE PRECISION,
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

CREATE TABLE IF NOT EXISTS "scale_metric" (
  "partition" TEXT,
  "metric" TEXT,
  "value" DOUBLE PRECISION,
  "unit" TEXT,
  "kind" TEXT,
  "basis" TEXT,
  "source" TEXT,
  "confidence" TEXT,
  "missing_reason" TEXT,
  PRIMARY KEY ("partition", "metric"),
  FOREIGN KEY ("partition") REFERENCES "partition"("id")
);

CREATE TABLE IF NOT EXISTS "money_node" (
  "id" TEXT,
  "type" TEXT,
  "sector" TEXT,
  "partition" TEXT,
  "name" TEXT,
  "declared_in_cny" DOUBLE PRECISION,
  "declared_out_cny" DOUBLE PRECISION,
  "source" TEXT,
  PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "money_flow" (
  "src" TEXT,
  "dst" TEXT,
  "kind" TEXT,
  "amount_cny" DOUBLE PRECISION,
  "confidence" TEXT,
  "basis" TEXT,
  PRIMARY KEY ("src", "dst", "kind"),
  FOREIGN KEY ("src") REFERENCES "money_node"("id"),
  FOREIGN KEY ("dst") REFERENCES "money_node"("id")
);

CREATE TABLE IF NOT EXISTS "money_gap" (
  "node" TEXT,
  "kind" TEXT,
  "side" TEXT,
  "amount_cny" DOUBLE PRECISION,
  "reason" TEXT,
  PRIMARY KEY ("node", "kind", "side"),
  FOREIGN KEY ("node") REFERENCES "money_node"("id")
);

CREATE INDEX IF NOT EXISTS "idx_partition_status" ON "partition" ("status");

CREATE INDEX IF NOT EXISTS "idx_partition_kind" ON "partition" ("gdp_kind");

CREATE INDEX IF NOT EXISTS "idx_occupation_provider" ON "occupation" ("provider");

CREATE INDEX IF NOT EXISTS "idx_occupation_baseline" ON "occupation" ("baseline");

CREATE INDEX IF NOT EXISTS "idx_membership_partition" ON "membership" ("partition");

CREATE INDEX IF NOT EXISTS "idx_membership_occupation" ON "membership" ("occupation");

CREATE INDEX IF NOT EXISTS "idx_scale_metric_name" ON "scale_metric" ("metric");

CREATE INDEX IF NOT EXISTS "idx_money_flow_src" ON "money_flow" ("src");

CREATE INDEX IF NOT EXISTS "idx_money_flow_dst" ON "money_flow" ("dst");

CREATE INDEX IF NOT EXISTS "idx_money_flow_kind" ON "money_flow" ("kind");
