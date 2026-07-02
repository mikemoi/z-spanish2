# z-spanish · Core Basics

西语生活基础背诵 + 主动输出训练器（个人自用 PWA）。

核心只做一件事：**中文意图 → 开口说西语 → 手动输入西语 → 系统判定 → 显示标准答案/例句/说明 → 错的进"需要加强" → 按间隔复习反复出现。**

> 设计取舍以"是否真的会被长期使用"为唯一标准。凡是增加操作摩擦、制造焦虑、或"看起来有用但会被用来逃避训练"的功能一律不做。详见 `z-spanish-原始需求.md` 与 `z-spanish-调整补充-v1.md`（两者冲突以调整补充为准）。

## 技术栈

- 后端：FastAPI + SQLite（标准库 sqlite3，零 ORM）
- 前端：原生 HTML/CSS/JS，PWA（iPhone 主屏可添加）
- 部署：Docker Compose；数据存服务器端（不依赖 localStorage，前端只缓存登录 token）

## 目录结构

```
backend/
  app/
    config.py      # PIN(env)、路径、间隔与剂量常量
    schema.sql     # 建表 DDL
    db.py          # 连接 + 初始化 + 首次灌种子
    grading.py     # 四档判定（correct/near_correct/wrong/forgot，宽松判定）
    review.py      # 间隔复习引擎 + 熟练度阶段 + 每日生成算法
    importer.py    # JSON schema 校验（硬错拦截 / 软警告）+ 入库
    main.py        # FastAPI 路由 + Bearer 鉴权 + 静态文件服务
  seed/seed_core.json  # 精准种子词条（首次启动自动导入）
  data/            # 运行时生成的 SQLite（git 忽略）
frontend/
  index.html styles.css app.js   # 五页面（登录/首页/训练/基础库/统计）
  manifest.json sw.js icons/     # PWA
Dockerfile docker-compose.yml scripts/backup.sh
```

## 本地运行（Windows / macOS / Linux）

```bash
cd backend
pip install -r requirements.txt
# 可选：设置自己的 PIN（默认 1234）
#   Windows PowerShell:  $env:Z_SPANISH_PIN="8461"
#   bash:                export Z_SPANISH_PIN=8461
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000 ，输入 PIN 即可。首次启动会自动把 `seed/seed_core.json` 灌入数据库。

## Docker 部署

```bash
# 在服务器目录 /z/apps/z-spanish
export Z_SPANISH_PIN=你的PIN
docker compose up -d --build
```

- SQLite 持久化在宿主机 `/z/apps/z-spanish/data`
- 服务只绑 `127.0.0.1:8000`，前面用 Caddy/Nginx 反代做 HTTPS
- 每日备份：把 `scripts/backup.sh` 加进 crontab（示例见脚本头部注释），备份落 `/z/backup/z-spanish`

Caddy 反代示例：

```
tu-dominio.com {
    reverse_proxy 127.0.0.1:8000
}
```

## 核心逻辑速查

**四档判定**（`grading.py`）
- `correct` 完全正确 / `near_correct` 只差大小写·重音·标点（宽松，算通过）
- `wrong` 词或意思错 / `forgot` 点"我不会"
- correct 与 near_correct 都算"通过"，用于阶段推进

**间隔复习**（`review.py`）：今天 / +2 / +4 / +7 / +14 / +30 / +60 / +90 天

**熟练度阶段**（只在基础库/统计显示，训练页绝不显示）
| 间隔阶段 | 标签 |
|---|---|
| 今天·第2天 | 初识 |
| 第4·7天 | 巩固中 |
| 第14·30天 | 稳固 |
| 第60·90天 | 长期记忆 |
到达间隔答对才进下一阶段；答错/忘记回退一级（不清零）。

**每日生成优先级**：到期复习 → 需要加强 → 混淆组 → 补新内容
- 新内容硬上限 5（状态再好也不放宽）
- 旧内容 ≥ 20：今天不加新内容
- 需要加强池 > 15：当日优先清空，不加新内容
- 超出 20 可"再来一组"，只从到期+加强里挑当天没答对的，不影响明天排期

**静默计时**：进训练页自动开始，界面无秒表；忘记结束时以最后一次答题时间兜底（不是关 App 时间）。只做日/周/月/年记录，不设目标、不比较。

## 词条 JSON schema

```json
{
  "id": "loc_001",
  "category": "方位",
  "type_zh": "副词", "type_es": "adverbio", "subtype": "方位",
  "zh": "这里",
  "es": "aquí",
  "accepted_answers": ["aquí"],
  "example_es": "Estoy aquí.",
  "example_zh": "我在这里。",
  "note": "aquí 是“这里”，不要和 allí 混淆。",
  "tags": ["A1", "必背", "高频"],
  "confusion_group": "aqui_alli",
  "verb_lemma": null, "noun_lemma": null, "prep_lemma": null,
  "is_active": 1
}
```

导入校验（`importer.py`）：
- **硬错（拦截）**：缺 id/category/zh/es/example_es、id 重复。
- **软警告（可继续导入，标记未完成收录）**：同一 `verb_lemma` < 2 条（需人称块+搭配）、同一 `noun_lemma` < 2 条（需冠词块+搭配句）、同一 `prep_lemma` < 2 条短语。

自定义内容走 **App 外生成 → 人工审核 → 基础库底部"批量导入"弱化入口** 粘贴 JSON，校验+预览确认后入库。不做 App 内 AI 一键生成（避免错误数据被间隔复习强化，也避免"加内容逃避训练"的 ADHD 陷阱）。

## 已知取舍 / 第一版不做

- 独立场景页、Bloques/Situaciones 一级页、Yo 大页面、Notas、Textos、Cloze、成长树、多训练模式、语音识别、倒计时、排行榜、连续天数 streak、正确率百分比/进度条 —— 一律不做。
- 底部导航固定 4 个：首页 / 训练 / 基础库 / 统计。
- 每日固定时间系统推送提醒（调整补充第八节）：暂未实现，作为已知取舍记录在此，后续可加一条最简单的固定时间提醒。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/login` | PIN 换 Bearer token |
| GET | `/api/today` | 今日题集 + 首页概览 |
| POST | `/api/answer` | 提交答案/我不会，返回判定+反馈，推进复习 |
| POST | `/api/again` | 再来一组（不影响明天排期） |
| GET | `/api/library` | 基础库（分类/搜索，含阶段标签） |
| POST | `/api/import` | 批量导入（validate / confirm） |
| GET | `/api/stats` | 统计（day/week/month/year） |
| POST | `/api/timer/end` | 静默计时结束（最后活动时间兜底） |
| GET | `/api/copy-gpt` | 生成给 GPT 的今日记忆状态摘要 |
