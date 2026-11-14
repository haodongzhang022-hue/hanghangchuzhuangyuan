-- ⚠️ 本文件由 scripts/export_industry_db.py 生成，请勿手改。
-- 数据（10-data.sql）由 `industry export` 生成，不随结构进版本库。
CREATE TABLE IF NOT EXISTS "dataset_meta" (
  "key" TEXT NOT NULL,
  "value" TEXT,
  PRIMARY KEY ("key")
);

CREATE TABLE IF NOT EXISTS "partition" (
  "id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "aliases" TEXT,
  "status" TEXT NOT NULL,
  "unit_id" TEXT,
  "priority" TEXT,
  "gdp_cny" INTEGER,
  "gdp_kind" TEXT NOT NULL,
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
  "member_count" INTEGER NOT NULL,
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
  "code" TEXT NOT NULL,
  "id" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "deliverable" TEXT,
  "provider" TEXT,
  "billing" TEXT,
  "access" TEXT NOT NULL,
  "baseline" INTEGER NOT NULL,
  "gb_code" TEXT,
  "gb_name" TEXT,
  "note" TEXT,
  PRIMARY KEY ("id"),
  UNIQUE ("code")
);

CREATE TABLE IF NOT EXISTS "membership" (
  "occupation" TEXT NOT NULL,
  "partition" TEXT NOT NULL,
  "axis" TEXT NOT NULL,
  "weight" REAL NOT NULL,
  "unit_role" TEXT,
  PRIMARY KEY ("occupation", "partition", "axis"),
  FOREIGN KEY ("occupation") REFERENCES "occupation"("id"),
  FOREIGN KEY ("partition") REFERENCES "partition"("id")
);

CREATE TABLE IF NOT EXISTS "gb_catalog" (
  "code" TEXT NOT NULL,
  "name" TEXT NOT NULL,
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
  "partition" TEXT NOT NULL,
  "metric" TEXT NOT NULL,
  "value" REAL,
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
  "id" TEXT NOT NULL,
  "type" TEXT NOT NULL,
  "sector" TEXT,
  "partition" TEXT,
  "name" TEXT NOT NULL,
  "declared_in_cny" INTEGER,
  "declared_out_cny" INTEGER,
  "source" TEXT,
  PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "money_flow" (
  "src" TEXT NOT NULL,
  "dst" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "amount_cny" INTEGER,
  "confidence" TEXT,
  "basis" TEXT,
  "memo" INTEGER NOT NULL,
  PRIMARY KEY ("src", "dst", "kind"),
  FOREIGN KEY ("src") REFERENCES "money_node"("id"),
  FOREIGN KEY ("dst") REFERENCES "money_node"("id")
);

CREATE TABLE IF NOT EXISTS "baseline_series" (
  "benchmark" TEXT NOT NULL,
  "name" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "axis" TEXT,
  "year" INTEGER NOT NULL,
  "value_cny" INTEGER,
  "source" TEXT,
  "confidence" TEXT,
  "note" TEXT,
  PRIMARY KEY ("benchmark", "year")
);

CREATE TABLE IF NOT EXISTS "baseline_link" (
  "partition" TEXT NOT NULL,
  "benchmark" TEXT NOT NULL,
  "relation" TEXT NOT NULL,
  "value_added_benchmark" TEXT,
  "tolerance" REAL,
  "reason" TEXT,
  "status" TEXT NOT NULL,
  "year" INTEGER,
  "year_source" TEXT,
  "part_value_cny" INTEGER,
  "bench_value_cny" INTEGER,
  "deviation" REAL,
  PRIMARY KEY ("partition"),
  FOREIGN KEY ("partition") REFERENCES "partition"("id")
);

CREATE TABLE IF NOT EXISTS "io_account" (
  "partition" TEXT NOT NULL,
  "year" INTEGER,
  "output_cny" INTEGER,
  "value_added_cny" INTEGER,
  "intermediate_cny" INTEGER,
  "intermediate_derived" INTEGER NOT NULL,
  "va_ratio" REAL,
  "identity_status" TEXT NOT NULL,
  "deviation" REAL,
  "anchor" TEXT,
  "pool_status" TEXT,
  "missing_reason" TEXT,
  PRIMARY KEY ("partition"),
  FOREIGN KEY ("partition") REFERENCES "partition"("id")
);

CREATE TABLE IF NOT EXISTS "money_gap" (
  "node" TEXT NOT NULL,
  "kind" TEXT NOT NULL,
  "side" TEXT,
  "amount_cny" INTEGER,
  "reason" TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS "idx_money_flow_memo" ON "money_flow" ("memo");

CREATE INDEX IF NOT EXISTS "idx_baseline_series_year" ON "baseline_series" ("year");

CREATE INDEX IF NOT EXISTS "idx_baseline_link_status" ON "baseline_link" ("status");

CREATE INDEX IF NOT EXISTS "idx_io_identity" ON "io_account" ("identity_status");

CREATE INDEX IF NOT EXISTS "idx_io_pool" ON "io_account" ("pool_status");
