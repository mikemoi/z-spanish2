-- z-spanish SQLite schema
-- 设计原则：内容准确性最高优先级；错误数据会被间隔复习反复强化，宁少勿错。

-- 词条主表
CREATE TABLE IF NOT EXISTS entries (
  id               TEXT PRIMARY KEY,
  category         TEXT NOT NULL,
  type_zh          TEXT,
  type_es          TEXT,
  subtype          TEXT,
  zh               TEXT NOT NULL,           -- 中文意图（提示，不是逐字翻译）
  es               TEXT NOT NULL,           -- 标准答案
  accepted_answers TEXT NOT NULL DEFAULT '[]', -- JSON 数组：等价的满分答案
  example_es       TEXT NOT NULL,           -- 非空硬校验
  example_zh       TEXT,
  note             TEXT,                    -- <=1 句
  tags             TEXT DEFAULT '[]',       -- JSON 数组
  confusion_group  TEXT,
  verb_lemma       TEXT,                    -- 动词原形，用于"同动词>=2条"校验
  noun_lemma       TEXT,                    -- 名词，用于"同名词>=2条"校验
  prep_lemma       TEXT,                    -- 介词，用于"同介词>=2短语"校验
  is_active        INTEGER NOT NULL DEFAULT 1,
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(category);
CREATE INDEX IF NOT EXISTS idx_entries_confusion ON entries(confusion_group);

-- 每条词块的复习/熟练度状态
CREATE TABLE IF NOT EXISTS review_state (
  entry_id      TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
  interval_idx  INTEGER NOT NULL DEFAULT 0,   -- 0..7 对应 今天/第2/4/7/14/30/60/90 天
  due_date      TEXT NOT NULL,                -- 下次到期日 YYYY-MM-DD
  stage         TEXT NOT NULL,                -- 初识/巩固中/稳固/长期记忆
  in_reinforce  INTEGER NOT NULL DEFAULT 0,   -- 是否在"需要加强"池
  last_result   TEXT,                         -- correct/near_correct/wrong/forgot
  last_reviewed TEXT,
  first_seen    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_due ON review_state(due_date);
CREATE INDEX IF NOT EXISTS idx_review_reinforce ON review_state(in_reinforce);

-- 每次答题流水
CREATE TABLE IF NOT EXISTS attempts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id    TEXT NOT NULL REFERENCES entries(id),
  ts          TEXT NOT NULL,
  result      TEXT NOT NULL,                  -- correct/near_correct/wrong/forgot
  user_answer TEXT,
  day         TEXT NOT NULL                   -- 归属训练日 YYYY-MM-DD
);
CREATE INDEX IF NOT EXISTS idx_attempts_day ON attempts(day);

-- 每日训练记录（本月完成天数 / 当日题集）
CREATE TABLE IF NOT EXISTS daily_log (
  day             TEXT PRIMARY KEY,
  item_ids        TEXT NOT NULL DEFAULT '[]', -- 当日固定题集(JSON)，刷新不重排
  new_count       INTEGER NOT NULL DEFAULT 0,
  review_count    INTEGER NOT NULL DEFAULT 0,
  reinforce_count INTEGER NOT NULL DEFAULT 0,
  total           INTEGER NOT NULL DEFAULT 0,
  completed       INTEGER NOT NULL DEFAULT 0
);

-- 时长明细（按日聚合，周/月/年查询时 SUM）
CREATE TABLE IF NOT EXISTS time_log (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  day      TEXT NOT NULL,
  minutes  INTEGER NOT NULL,
  start_ts TEXT,
  end_ts   TEXT
);
CREATE INDEX IF NOT EXISTS idx_time_day ON time_log(day);

-- 登录会话（Bearer token）
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);
