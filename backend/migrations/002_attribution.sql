-- 多层归属分摊：节点、版本化关系边、计算冻结版本。
-- 全新环境仍由 SQLAlchemy metadata 直接建表；本文件用于既有部署的显式迁移审查。
CREATE TABLE IF NOT EXISTS attribution_nodes (
    id    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    node  VARCHAR(60) NOT NULL UNIQUE,
    kind  VARCHAR(16) NOT NULL,          -- channel 来源渠道 / hub 中间节点 / region 终点区域
    label VARCHAR(60) NOT NULL
);
CREATE TABLE IF NOT EXISTS attribution_edges (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source     VARCHAR(60) NOT NULL,
    target     VARCHAR(60) NOT NULL,
    weight     DOUBLE PRECISION NOT NULL,
    start_date VARCHAR(10) NOT NULL,     -- ISO 日期，闭区间起点
    end_date   VARCHAR(10),              -- NULL 表示长期有效
    owner      VARCHAR(120) NOT NULL,
    created_at VARCHAR(40) NOT NULL
);
-- 同一对节点允许存在多条不重叠有效期的版本；重叠与否由服务层全量图校验，
-- 这里只建检索索引，不加会误伤历史版本的唯一约束。
CREATE INDEX IF NOT EXISTS attribution_edges_window_idx
    ON attribution_edges (source, target, start_date);
CREATE TABLE IF NOT EXISTS attribution_versions (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot   JSONB NOT NULL,           -- 入队时冻结的全部关系边
    terminals  JSONB NOT NULL DEFAULT '[]',
    note       VARCHAR(200) NOT NULL DEFAULT '',
    created_at VARCHAR(40) NOT NULL,
    owner      VARCHAR(120) NOT NULL
);
ALTER TABLE report_runs
    ADD COLUMN IF NOT EXISTS attribution_version_id INTEGER
    REFERENCES attribution_versions (id);
CREATE INDEX IF NOT EXISTS report_runs_attribution_version_idx
    ON report_runs (attribution_version_id);
