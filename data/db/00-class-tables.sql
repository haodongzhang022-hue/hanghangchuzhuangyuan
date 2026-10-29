-- ⚠️ 本文件由 scripts/export_class_db.py 生成，请勿手改。
CREATE TABLE IF NOT EXISTS "industry_class" (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    kind              TEXT NOT NULL,
    label             TEXT,
    is_entity         INTEGER NOT NULL,
    source_file       TEXT NOT NULL,
    UNIQUE ("name")
);

-- 别名：同一个东西的多种叫法收敛到一个 class_name
CREATE TABLE IF NOT EXISTS "class_alias" (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name        TEXT NOT NULL,
    alias             TEXT NOT NULL,
    source_file       TEXT NOT NULL,
    UNIQUE ("alias"),
    FOREIGN KEY ("class_name") REFERENCES "industry_class"("name")
);

-- 索引源：这个类去哪个系统、用什么查询式查具体公司（只存检索方式）
CREATE TABLE IF NOT EXISTS "class_index_src" (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name        TEXT NOT NULL,
    source            TEXT NOT NULL,
    query_expr        TEXT NOT NULL,
    FOREIGN KEY ("class_name") REFERENCES "industry_class"("name")
);

-- 岗位引用：哪个岗位的哪个字段引用了什么（类目/接口/岗位三类落点）
CREATE TABLE IF NOT EXISTS "role_chain_ref" (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id           TEXT NOT NULL,
    role_name         TEXT NOT NULL,
    field             TEXT NOT NULL,
    raw_value         TEXT NOT NULL,
    class_name        TEXT NOT NULL,
    ref_kind          TEXT NOT NULL,
    ref_unit          TEXT,
    ref               TEXT,
    ref_index         TEXT,
    ref_note          TEXT
);

-- 行业单元（M2 注册表落库）：一个行业一套岗位










CREATE INDEX IF NOT EXISTS idx_chain_ref_class ON "role_chain_ref"("class_name");
CREATE INDEX IF NOT EXISTS idx_chain_ref_role ON "role_chain_ref"("unit_id", "role_name");
CREATE INDEX IF NOT EXISTS idx_index_src_class ON "class_index_src"("class_name");
CREATE INDEX IF NOT EXISTS idx_alias_class ON "class_alias"("class_name");
