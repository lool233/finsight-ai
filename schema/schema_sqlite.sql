-- =====================================================================
--  智析 FinSight AI  本地演示数据库结构脚本（SQLite）
--  文件：schema/schema_sqlite.sql
--  说明：与 MySQL 版表结构一一对应，用于未安装 MySQL 时快速运行演示。
--        正式提交与部署请使用《数据库SQL脚本/01_schema.sql》(MySQL 8.0)。
-- =====================================================================

DROP TABLE IF EXISTS collection_record;
DROP TABLE IF EXISTS repayment_record;
DROP TABLE IF EXISTS loan_record;
DROP TABLE IF EXISTS sales_person;
DROP TABLE IF EXISTS sys_user;
DROP TABLE IF EXISTS ai_chat_log;
DROP TABLE IF EXISTS operation_log;

CREATE TABLE sys_user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(128) NOT NULL,
    real_name     VARCHAR(50)  NOT NULL,
    role          VARCHAR(20)  NOT NULL DEFAULT 'sales',
    dept          VARCHAR(50),
    phone         VARCHAR(20),
    status        INTEGER      NOT NULL DEFAULT 1,
    last_login_at DATETIME,
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sales_person (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_no     VARCHAR(30) NOT NULL UNIQUE,
    name       VARCHAR(50) NOT NULL,
    gender     VARCHAR(4)  DEFAULT '男',
    phone      VARCHAR(20) NOT NULL,
    dept       VARCHAR(50) NOT NULL,
    region     VARCHAR(50),
    job_title  VARCHAR(50) DEFAULT '销售代表',
    entry_date DATE,
    status     VARCHAR(10) NOT NULL DEFAULT '在职',
    remark     VARCHAR(255),
    created_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sales_name ON sales_person (name);
CREATE INDEX idx_sales_dept ON sales_person (dept);

CREATE TABLE loan_record (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_no        VARCHAR(32) NOT NULL UNIQUE,
    sales_id       INTEGER     NOT NULL,
    amount         DECIMAL(12, 2) NOT NULL,
    loan_date      DATE        NOT NULL,
    repay_deadline DATE        NOT NULL,
    loan_type      VARCHAR(30) NOT NULL DEFAULT '差旅借款',
    purpose        VARCHAR(255),
    status         VARCHAR(10) NOT NULL DEFAULT '待还款',
    repaid_amount  DECIMAL(12, 2) NOT NULL DEFAULT 0,
    remark         VARCHAR(255),
    created_by     VARCHAR(50),
    is_deleted     INTEGER     NOT NULL DEFAULT 0,
    created_at     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sales_id) REFERENCES sales_person (id)
);
CREATE INDEX idx_loan_sales ON loan_record (sales_id);
CREATE INDEX idx_loan_date ON loan_record (loan_date);
CREATE INDEX idx_loan_deadline ON loan_record (repay_deadline);
CREATE INDEX idx_loan_status ON loan_record (status);

CREATE TABLE repayment_record (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id      INTEGER NOT NULL,
    repay_amount DECIMAL(12, 2) NOT NULL,
    repay_date   DATE    NOT NULL,
    repay_method VARCHAR(20) NOT NULL DEFAULT '银行转账',
    operator     VARCHAR(50),
    remark       VARCHAR(255),
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loan_id) REFERENCES loan_record (id)
);
CREATE INDEX idx_repay_loan ON repayment_record (loan_id);

CREATE TABLE collection_record (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_no         VARCHAR(32),
    loan_id          INTEGER NOT NULL,
    sales_id         INTEGER NOT NULL,
    overdue_days     INTEGER NOT NULL DEFAULT 0,
    overdue_amount   DECIMAL(12, 2) NOT NULL DEFAULT 0,
    collection_level VARCHAR(10) NOT NULL DEFAULT '一级',
    channel          VARCHAR(10) NOT NULL DEFAULT '短信',
    content          TEXT,
    llm_model        VARCHAR(60),
    generated_by     VARCHAR(10) NOT NULL DEFAULT 'LLM',
    send_status      VARCHAR(20) NOT NULL DEFAULT '待发送',
    need_manual_send INTEGER NOT NULL DEFAULT 1,
    sent_at          DATETIME,
    remark           VARCHAR(255),
    created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loan_id) REFERENCES loan_record (id),
    FOREIGN KEY (sales_id) REFERENCES sales_person (id)
);
CREATE INDEX idx_coll_loan ON collection_record (loan_id);
CREATE INDEX idx_coll_batch ON collection_record (batch_no);

CREATE TABLE ai_chat_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    VARCHAR(64),
    user_id       INTEGER,
    question      VARCHAR(500) NOT NULL,
    intent        VARCHAR(40),
    slots         VARCHAR(500),
    sql_text      TEXT,
    answer        TEXT,
    data_snapshot TEXT,
    llm_model     VARCHAR(60),
    elapsed_ms    INTEGER DEFAULT 0,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE operation_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER,
    username   VARCHAR(50),
    module     VARCHAR(30),
    action     VARCHAR(30),
    target     VARCHAR(100),
    detail     VARCHAR(500),
    ip         VARCHAR(50),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- RAG 知识库：制度文档与切块索引（对应 MySQL 同名表）
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS knowledge_chunk;
DROP TABLE IF EXISTS knowledge_doc;

CREATE TABLE knowledge_doc (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_code   VARCHAR(40) NOT NULL UNIQUE,
    title      VARCHAR(120) NOT NULL,
    category   VARCHAR(100),
    version    VARCHAR(20) DEFAULT 'V1.0',
    file_name  VARCHAR(120),
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE knowledge_chunk (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     INTEGER NOT NULL,
    doc_code   VARCHAR(40) NOT NULL,
    doc_title  VARCHAR(120) NOT NULL,
    heading    VARCHAR(120),
    seq        INTEGER NOT NULL DEFAULT 0,
    content    TEXT NOT NULL,
    char_len   INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doc_id) REFERENCES knowledge_doc (id)
);
CREATE INDEX idx_chunk_doc ON knowledge_chunk (doc_id, seq);

-- Agent 工具调用轨迹（可观测性 / 面试演示用）
DROP TABLE IF EXISTS agent_step_log;
CREATE TABLE agent_step_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id VARCHAR(64),
    question   VARCHAR(500),
    step_no    INTEGER NOT NULL DEFAULT 1,
    action     VARCHAR(40),
    args       VARCHAR(300),
    observation VARCHAR(300),
    elapsed_ms INTEGER DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
