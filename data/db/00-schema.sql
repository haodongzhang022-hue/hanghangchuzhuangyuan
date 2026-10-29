-- ⚠️ 本文件由 scripts/export_class_db.py 生成，请勿手改。
-- ===========================================================================
-- 行业类与利益链条 · 结构（由 scripts/export_class_db.py 生成，勿手改）
--
-- 三张主表 + 两张关联表，回答四个问题：
--   1. industry_class   有哪些类目，分别是什么 kind
--   2. class_alias      同一个类目的其他叫法（收敛同义词，防止一地鸡毛）
--   3. class_index_src  这个类目去哪个系统、用什么查询式查具体公司
--   4. role_chain_ref   哪个岗位的哪个字段引用了哪个类目（反查靠它）
--
-- **本 schema 不含公司名录表**。企业名录/客户档案住在 CRM / ATS / 企业名录里，
-- 靠 class_index_src 声明的来源去查。把名录塞进仓库既不合规也不通用。
-- ===========================================================================

CREATE TABLE IF NOT EXISTS industry_class (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,     -- 类目名：钢材加工 / 品牌方 / 用人部门
    kind        TEXT    NOT NULL,            -- 制造/服务/渠道/机构/内部组织/需求方/阻碍/单元
    label       TEXT,                        -- 展示名（单元类目用中文行业名）
    is_entity   INTEGER NOT NULL DEFAULT 1,  -- 1=实体（可查到公司） 0=原因/接口/输入
    source_file TEXT    NOT NULL             -- 声明它的文件，改词表时知道动哪
);

CREATE TABLE IF NOT EXISTS class_alias (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,                -- 归到哪个类目
    alias      TEXT NOT NULL UNIQUE,         -- 别名/旧叫法
    source_file TEXT NOT NULL,
    FOREIGN KEY (class_name) REFERENCES industry_class(name)
);

CREATE TABLE IF NOT EXISTS class_index_src (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT    NOT NULL,
    source     TEXT    NOT NULL,             -- CRM / 企业名录 / ATS / 内部主数据
    query_expr TEXT    NOT NULL,             -- 查询式：钢材{加工|剪切|开平}
    FOREIGN KEY (class_name) REFERENCES industry_class(name)
);

CREATE TABLE IF NOT EXISTS role_chain_ref (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id    TEXT    NOT NULL,             -- 行业单元
    role_name  TEXT    NOT NULL,             -- 岗位
    field      TEXT    NOT NULL,             -- upstream/downstream/beneficiaries/blockers
    raw_value  TEXT    NOT NULL,             -- 画像里原本写的东西
    class_name TEXT    NOT NULL,             -- 归一后的类目
    FOREIGN KEY (class_name) REFERENCES industry_class(name)
);

CREATE INDEX IF NOT EXISTS idx_chain_ref_class ON role_chain_ref(class_name);
CREATE INDEX IF NOT EXISTS idx_chain_ref_role  ON role_chain_ref(unit_id, role_name);
CREATE INDEX IF NOT EXISTS idx_index_src_class ON class_index_src(class_name);
