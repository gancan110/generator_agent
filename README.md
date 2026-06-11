# Agnes AI 小说生成 Agent

基于 Agnes AI 大模型的全自动小说创作引擎。通过四层记忆架构、Skill 题材系统、多阶段生成策略、资产闭环管理和质量重写机制，实现从题材输入到完整长篇的自动化生产，支持 100+ 章的超长篇连贯创作。

## 项目特性

- **四层记忆架构**：工作记忆 / 短期记忆 / 长期记忆 / 永久记忆，分层注入 LLM 上下文，解决超长篇（100+ 章）记忆遗忘问题
- **Skill 题材系统**：预置题材写作风格包（JSON），覆盖玄幻修仙、都市异能、规则怪谈等题材，支持 LLM 自动生成未知题材的 Skill
- **分阶段生成**：知识采集 → 世界观构建 → 大纲规划 → 逐章创作，每阶段独立质量控制
- **断点续写**：支持从已有章节继续生成，自动恢复知识库、资产状态和向量存储，无需重新采集
- **低分自动重写**：章节评分低于 0.70 时触发重写机制，基于诊断结果定向修复，重写后重新评估和后处理
- **多源知识采集**：自动采集世界观设定、传统文化、人物塑造、写作手法、风格分析、竞品分析等 7 个维度的创作知识
- **悬念闭环管理**：S/A/B 三级悬念体系，LLM 自动检测悬念产生与解决，超期预警
- **资产深度集成**：角色档案 LLM 批量更新、物品自动提取入库、PlotPoint 剧情节点记录、世界设定一致性校验
- **分层上下文注入**：记忆系统构建四层上下文（带前缀标记 ★◆◇○），合并知识库静态设定后注入 LLM
- **AI 痕迹后处理**：11 步后处理管线，覆盖瞬间降频、比喻去重、英文泄露修复、段落合并、禁用模式替换等
- **写作质量铁律**：15 项禁止清单 + 10 项风格要求（含幽默密度和对话占比），Skill 可覆盖题材特有规则
- **动态参数优化**：根据质量评分自动调整生成温度和检索深度
- **向量语义检索**：基于 sentence-transformers 的知识向量化与余弦相似度检索，支持 metadata 过滤和索引清理

## 系统架构

```
初始化 → Skill匹配/自动生成 → 多源知识采集(7维度) → 世界观生成(4组件) → 初始大纲(黄金三章)
    |
    v
  主循环 ──────────────────────────────────────────────────────────
    |                                                                 |
    |-> 构建分层记忆上下文(4层: 工作/短期/长期/永久)                   |
    |-> 扁平化记忆 + 知识库合并 → 注入 LLM                            |
    |-> 章节内容生成(分段生成 + Skill定制 + 分层上下文注入)             |
    |-> 11步后处理管线(禁用模式+瞬间降频+段落合并+Skill扩展)            |
    |-> 知识库更新(向量存储)                                          |
    |-> 资产更新(角色LLM批量更新+历史追踪/物品提取/PlotPoint/盘点)      |
    |-> 悬念管理(LLM检测新悬念+回收已解决悬念+超期检查)                 |
    |-> 记忆时间线追加                                                |
    |-> 质量评估(4维本地+LLM综合评分)                                   |
    |-> 低分重写(评分<0.70 → 诊断 → 定向重写 → 重新后处理)            |
    |-> 世界设定一致性检查(每5章)                                       |
    |-> 动态参数调整(温度/检索深度)                                     |
    |-> 定期大纲更新(每5章)                                             |
    |-> 定期记忆维护(每10章: 卷压缩+角色弧线归档+悬念归档+向量清理)     |
    └─────────────────────────────────────────────────────────────────┘

续写流程 (continue):
  加载项目 → 恢复Skill → 恢复知识上下文(跳过LLM采集) → 重建向量存储 → 生成续写大纲 → 主循环
```

## 项目结构

```
agnesAi/
├── .env                          # 环境变量配置（API密钥/数据库/生成参数）
├── main.py                       # 主入口（唯一允许的根目录 .py 文件）
├── requirements.txt              # Python 依赖
├── novel_agent/                  # 主包
│   ├── config.py                 # 配置管理 (LLM/MySQL/生成参数/Skill/向量库/调度器)
│   ├── database/                 # 数据库模块
│   │   ├── models.py             #   ORM 模型 (10张表: projects/chapters/characters/items/memory_archive/...)
│   │   └── mysql_client.py       #   MySQL 客户端 (CRUD封装)
│   ├── memory/                   # 分层记忆系统 (P4)
│   │   ├── __init__.py           #   包导出 (MemoryManager)
│   │   └── manager.py            #   四层记忆管理器 (构建/压缩/归档/时间线)
│   ├── scheduler/                # 任务调度系统
│   │   ├── queue.py              #   优先级队列
│   │   ├── executor.py           #   并发执行器
│   │   └── retry.py              #   重试策略 (指数退避)
│   ├── knowledge/                # 知识管理
│   │   ├── collector.py          #   多源知识采集器 (7维度)
│   │   ├── knowledge_base.py     #   知识库管理器
│   │   └── vector_store.py       #   向量存储与检索 (metadata过滤+cleanup+单例+预加载)
│   ├── outline/                  # 大纲系统
│   │   ├── generator.py          #   初始大纲生成 (多重JSON解析+文本回退)
│   │   └── updater.py            #   动态大纲更新 (续写大纲生成)
│   ├── skills/                   # Skill 题材系统
│   │   ├── loader.py             #   Skill JSON 加载器
│   │   ├── registry.py           #   Skill 注册表 (题材匹配)
│   │   ├── context.py            #   Skill 上下文 (注入到生成/后处理各阶段)
│   │   ├── generator.py          #   LLM 自动生成 Skill (无匹配题材时)
│   │   ├── data/                 #   Skill 数据文件
│   │   │   ├── _base.json                # 默认兜底 Skill
│   │   │   ├── xuanhuan_xianxia.json     # 玄幻修仙
│   │   │   ├── dushi_yineng.json         # 都市异能
│   │   │   ├── guize_guaitan.json        # 规则怪谈
│   │   │   └── generated_*.json          # LLM 自动生成的 Skill
│   │   └── overrides/            #   项目级 Skill 覆盖配置
│   ├── generation/               # 核心生成
│   │   ├── chapter_generator.py  #   章节内容生成 (11步后处理+Skill定制+记忆前缀放宽截断)
│   │   ├── rewriter.py           #   低分重写器 (诊断→定向重写→重写日志)
│   │   └── pipeline.py           #   完整生成流水线 (含 resume 续写+记忆系统集成)
│   ├── assets/                   # 剧情资产管理
│   │   ├── character.py          #   角色档案库 (LLM批量更新+变化历史追踪+上下文生成)
│   │   ├── item.py               #   物品与功法库 (LLM提取+盘点+膨胀检测)
│   │   └── world_setting.py      #   世界设定集 (一致性校验+上下文注入)
│   ├── suspense/                 # 悬念管理
│   │   └── manager.py            #   S/A/B 三级悬念生命周期 (鲁棒JSON解析+结果追踪)
│   ├── evaluation/               # 评估与优化
│   │   ├── quality.py            #   多维质量评估 (4维本地+LLM综合+诊断+重写判定)
│   │   └── optimizer.py          #   动态参数优化器
│   ├── utils/                    # 工具模块
│   │   ├── llm_client.py         #   LLM API 客户端 (generate + generate_structured)
│   │   └── logger.py             #   日志工具
│   └── cli/                      # 命令行接口
│       └── main.py               #   CLI 命令定义 (init/create/start/continue/status/test)
├── test/                         # 测试与验证
│   ├── e2e_memory_test.py        #   端到端集成测试（记忆系统全链路）
│   ├── verify_*.py               #   集成验证脚本 (memory_system, asset_integration, fixes)
│   ├── test_*.py                 #   单元/功能测试 (skill_system, evaluator, fixes, optimizations 等)
│   ├── compare_*.py              #   版本/项目对比脚本
│   ├── evaluate_*.py             #   项目评估脚本
│   └── results/                  #   测试输出结果 (json/txt)
├── scripts/                      # 工具与辅助脚本
│   ├── analyze_*.py              #   数据分析脚本 (analyze_chapters.py, analyze_p10.py 等)
│   ├── migrate_p4.py             #   P4 记忆系统迁移 (memory_archive 表 + history 字段)
│   └── migrate_skill_columns.py  #   Skill 系统迁移 (skill_id + skill_overrides 字段)
├── doc/                          # 开发文档
│   ├── skill_system_design.md    #   Skill 系统设计文档
│   ├── long_term_memory_analysis.md  #   长期记忆分析报告 (P4 设计依据)
│   ├── analysis_report.md        #   技术分析报告
│   └── analysis_report_p8.md     #   P8 分析报告
├── reports/                      # 项目评估报告 (按项目归档)
├── bak/                          # 历史备份 (旧版本代码/文档归档)
├── output/                       # 生成输出目录（按项目自动创建子目录）
├── vector_db/                    # 向量数据库存储（按项目自动创建 project_{ID}/ 子目录）
└── logs/                         # 日志目录 (含 rewrite_history.jsonl)
```

## 项目目录规范

所有文件必须按以下规则放置，禁止在根目录散落临时脚本：

| 文件类型 | 放置位置 | 命名规范 | 说明 |
|----------|----------|----------|------|
| 业务模块代码 | `novel_agent/` 子包内 | 按职责分包 | 核心代码，严禁放根目录 |
| 单元测试/功能测试 | `test/` | `test_*.py` | pytest 风格或独立脚本 |
| 集成验证/回归测试 | `test/` | `verify_*.py` | 验证多模块集成正确性 |
| 端到端测试 | `test/` | `e2e_*.py` | 完整流程集成测试 |
| 版本对比/评估 | `test/` | `compare_*.py` / `evaluate_*.py` | 不同版本/项目的横向对比 |
| 测试输出结果 | `test/results/` | `*_result*.{json,txt}` | 测试产物，不纳入版本控制 |
| 数据分析脚本 | `scripts/` | `analyze_*.py` | 章节分析、统计等辅助工具 |
| 数据库迁移脚本 | `scripts/` | `migrate_*.py` | 表结构变更、数据迁移 |
| 技术设计文档 | `doc/` | `*_design.md` / `*_report.md` | 系统设计方案、技术分析报告 |
| 项目评估报告 | `reports/` | `*_report.md` | 按项目编号或功能归档的评估报告 |
| 历史代码/文档 | `bak/` | 保留原目录结构 | 被替代的旧版本归档 |
| 生成输出 | `output/` | `{标题}_{ID}/chapters/` | 按项目自动创建子目录 |
| 向量数据 | `vector_db/` | `project_{ID}/` | 按项目自动创建子目录 |
| 日志文件 | `logs/` | `novel_agent_*.log` / `pipeline_p*.log` | 按日期或项目自动命名 |
| 项目入口 | 根目录 | `main.py` | 唯一允许的根目录 .py 文件 |
| 配置文件 | 根目录 | `.env` / `requirements.txt` | 项目级配置 |
| 项目说明 | 根目录 | `README.md` | 项目入口文档 |

**规则要点：**

1. **根目录仅保留** `main.py`、`README.md`、`.env`、`requirements.txt` 等项目级文件
2. **新增测试** 必须放 `test/`，禁止在根目录创建 `test_*.py`
3. **新增文档** 必须放 `doc/`，禁止在根目录创建 `.md` 文件（README.md 除外）
4. **一次性脚本**（分析、迁移、数据清洗）放 `scripts/`
5. **Skill 数据文件** 放 `novel_agent/skills/data/`，JSON 命名 `{genre}_{theme}.json`
6. **临时实验** 放 `bak/` 归档，不污染主目录结构

---

## 快速开始

### 1. 环境要求

- **Python** >= 3.10
- **MySQL** >= 5.7
- **内存** >= 8GB（sentence-transformers 模型加载需要约 2GB）

建议先创建虚拟环境，避免依赖冲突：

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

> 如需启用 ONNX 加速嵌入推理（可选），额外安装：
> ```bash
> pip install optimum onnxruntime
> ```

### 3. 配置环境变量

编辑 `.env` 文件，设置 API 密钥和数据库连接（完整配置项参考见 [环境变量参考](#环境变量参考)）：

```env
# Agnes AI 配置（必填）
AGNES_API_KEY=your-api-key
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
AGNES_MODEL=agnes-2.0-flash

# MySQL 配置（必填）
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=agnes_novel

# 生成参数（可选，有默认值）
DEFAULT_CHAPTERS=100
WORDS_PER_CHAPTER=8000
WORDS_PER_SEGMENT=3000
```

### 4. 初始化数据库

```bash
python main.py init
```

> **升级用户**：如果是从旧版本升级，还需运行数据库迁移脚本（均为幂等操作，可重复执行）：
> ```bash
> # P4 记忆系统迁移：添加 memory_archive 表 + character_library.history 字段
> python scripts/migrate_p4.py
> # Skill 系统迁移：添加 projects.skill_id + projects.skill_overrides 字段
> python scripts/migrate_skill_columns.py
> ```

### 5. 测试连接

```bash
python main.py test
```

预期输出：
```
Testing database connection...
  [OK] Database connection successful
Testing LLM API connection...
  [OK] LLM API response: OK
```

### 6. 开始生成

```bash
# 生成玄幻修仙小说，50章
python main.py start -t "破天" -g "玄幻修仙" --chapters 50

# 生成都市重生小说，30章，指定主题"商战复仇"
python main.py start -t "重生之巅峰" -g "都市重生" --theme "商战复仇" --chapters 30

# 生成末日系统小说，10章（自动匹配/生成 Skill）
python main.py start -t "映道" -g "末日系统" --chapters 10

# 生成规则怪谈小说，不指定章节数（使用 .env 中 DEFAULT_CHAPTERS）
python main.py start -t "幸福小区住户手册" -g "规则怪谈"

# 生成科幻星际小说，指定主题
python main.py start -t "星环纪元" -g "科幻星际" --theme "星际殖民与AI觉醒" --chapters 40

python main.py start -t "敲代码" -g "代码随写，系统修复，使用代码能力修复显示世界的事故，错误，异常等等，程序员被ai代替悲惨的命运的齿轮" --theme "使用面板修复世界真实的错误" --chapters 5

```

### 7. 续写已有项目

```bash
# 从最后章节继续，写到原目标章节数
python main.py continue -p 7

# 扩展目标：在原有基础上多写 10 章
python main.py continue -p 7 --add-chapters 10

# 本次只生成 3 章（无论目标多少）
python main.py continue -p 7 -n 3

# 从指定章节开始（覆盖/重写某章）
python main.py continue -p 7 --from-chapter 3

# 从第 5 章开始，再写 10 章
python main.py continue -p 7 --from-chapter 5 -n 10 --add-chapters 10
```

续写流程会自动跳过知识采集和世界观生成（直接从数据库恢复），仅执行大纲更新和章节生成，因此续写速度远快于首次生成。

> **提示**：也可以先用 `create` 创建项目（不生成），记下项目 ID 后再用 `continue` 开始生成：
> ```bash
> python main.py create -t "敲代码" -g "代码随写，系统修复，使用代码能力修复显示世界的事故，错误，异常等等，程序员被ai代替悲惨的命运的齿轮" --theme "使用面板修复世界真实的错误" --chapters 5
> # 输出: Project created. ID: 15
> python main.py continue -p 15
> ```

### 8. 查看项目状态

```bash
# 查看所有项目列表
python main.py status

# 查看指定项目详情（含最近 10 章的标题、字数和质量评分）
python main.py status -p 7
```

输出示例：
```
  ID | Title                | Genre        | Status       | Progress
------------------------------------------------------------------------
   5 | 破天                   | 玄幻修仙         | completed    | 50/50
   7 | 映道                   | 末日系统         | completed    | 10/10
   8 | 幸福小区住户手册             | 规则怪谈         | completed    | 5/5
```

> **查看所有可用命令和参数**：
> ```bash
> python main.py --help            # 查看帮助
> python main.py <command> --help  # 查看某命令的详细参数
> ```

---

## CLI 命令参考

```bash
python main.py --help            # 查看所有命令帮助
python main.py <command> --help  # 查看某命令的详细参数说明
```

| 命令 | 说明 | 示例 |
|------|------|------|
| `init` | 初始化数据库，创建所有表（幂等操作） | `python main.py init` |
| `create` | 创建新项目（仅初始化，不生成） | `python main.py create -t "标题" -g "题材"` |
| `start` | 创建项目并开始生成 | `python main.py start -t "标题" -g "题材" --chapters 50` |
| `continue` | 续写已有项目 | `python main.py continue -p 7 --add-chapters 10` |
| `status` | 查看项目状态和章节列表 | `python main.py status -p 1` |
| `test` | 测试数据库和 LLM API 连接 | `python main.py test` |

### 各命令参数详解

#### `start` — 创建并生成

| 参数 | 必填 | 说明 | 默认值 | 示例 |
|------|------|------|--------|------|
| `-t / --title` | 是 | 小说标题 | — | `-t "破天"` |
| `-g / --genre` | 是 | 小说题材（用于 Skill 匹配） | — | `-g "玄幻修仙"` |
| `--theme` | 否 | 小说主题（影响知识采集方向） | 同 genre | `--theme "废柴逆袭"` |
| `--chapters` | 否 | 目标章节数 | `.env` 中 `DEFAULT_CHAPTERS` | `--chapters 50` |

#### `create` — 仅创建项目

参数与 `start` 完全一致。仅执行初始化（创建项目记录、Skill 匹配、子系统创建），不进入生成循环。适合需要先创建项目、检查配置后再开始生成的场景。

```bash
# 创建项目，获取项目 ID
python main.py create -t "破天" -g "玄幻修仙" --chapters 50
# 输出: Project created. ID: 15

# 后续可用 continue 开始生成
python main.py continue -p 15
```

#### `continue` — 续写

| 参数 | 必填 | 说明 | 默认值 | 示例 |
|------|------|------|--------|------|
| `-p / --project-id` | 是 | 要续写的项目 ID | — | `-p 7` |
| `--add-chapters N` | 否 | 将目标章节数扩展 N 章 | 0（不扩展） | `--add-chapters 10` |
| `-n / --num-chapters N` | 否 | 本次只生成 N 章 | 0（写到目标） | `-n 3` |
| `--from-chapter N` | 否 | 从第 N 章开始续写 | 0（自动接上） | `--from-chapter 5` |

#### `status` — 查看状态

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `-p / --project-id` | 否 | 指定项目 ID（不填则列出所有） | `-p 7` |

---

## 环境变量参考

所有配置项通过 `.env` 文件或系统环境变量设置，由 `novel_agent/config.py` 统一加载（`EMBEDDING_BACKEND` 除外，由 `vector_store.py` 直接读取）。

### LLM 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `AGNES_API_KEY` | LLM API 密钥 | （空） | `sk-xxxxx...` |
| `AGNES_BASE_URL` | API 端点 | `https://apihub.agnes-ai.com/v1` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `AGNES_MODEL` | 模型名称 | `agnes-2.0-flash` | `qwen-max` |

### MySQL 配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `MYSQL_HOST` | 数据库主机 | `localhost` | `127.0.0.1` |
| `MYSQL_PORT` | 数据库端口 | `3306` | `3306` |
| `MYSQL_USER` | 数据库用户 | `root` | `novel_user` |
| `MYSQL_PASSWORD` | 数据库密码 | `123456` | `my_secure_pw` |
| `MYSQL_DATABASE` | 数据库名 | `agnes_novel` | `my_novels` |

### 生成参数配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `DEFAULT_CHAPTERS` | 未指定时的默认目标章节数 | `100` | `50` |
| `WORDS_PER_CHAPTER` | 每章目标字数 | `8000` | `6000` |
| `WORDS_PER_SEGMENT` | 分段生成时每段字数 | `3000` | `2000` |

### 向量存储配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `VECTOR_DB_PATH` | 向量数据库存储路径（按项目自动创建子目录） | `./vector_db` | `/data/vector_db` |
| `EMBEDDING_BACKEND` | 嵌入推理后端，设为 `onnx` 启用 ONNX 加速（需安装 `optimum` + `onnxruntime`） | （空，使用 PyTorch） | `onnx` |

### 应用配置

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|--------|------|
| `LOG_DIR` | 日志输出目录 | `./logs` | `/var/log/novel_agent` |
| `LOG_LEVEL` | 日志级别（`DEBUG` / `INFO` / `WARNING` / `ERROR`） | `INFO` | `DEBUG` |
| `OUTPUT_DIR` | 小说输出目录（按项目自动创建 `{标题}_{ID}/chapters/` 子目录） | `./output` | `/data/novels` |

### 完整 `.env` 示例

```env
# ===== LLM 配置 =====
AGNES_API_KEY=sk-your-api-key-here
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
AGNES_MODEL=agnes-2.0-flash

# ===== MySQL 配置 =====
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=agnes_novel

# ===== 生成参数 =====
DEFAULT_CHAPTERS=100
WORDS_PER_CHAPTER=8000
WORDS_PER_SEGMENT=3000

# ===== 向量存储 =====
VECTOR_DB_PATH=./vector_db
# EMBEDDING_BACKEND=onnx    # 取消注释启用 ONNX 加速（需额外安装 optimum + onnxruntime）

# ===== 应用配置 =====
LOG_DIR=./logs
LOG_LEVEL=INFO
OUTPUT_DIR=./output
```

---

## 核心模块说明

### 四层记忆架构 (memory/manager.py)

P4 实现的核心模块，解决超长篇（100+ 章）小说的记忆连贯性问题。四层记忆按优先级从高到低注入 LLM 上下文：

```
┌─────────────────────────────────────────────────┐
│  永久记忆 (Permanent)  ~2K tokens  始终注入      │  ★ 前缀
│  ├─ 世界观核心设定 (力量体系/势力)               │
│  ├─ 主角核心档案                                 │
│  └─ 主线悬念 (S 级)                              │
├─────────────────────────────────────────────────┤
│  工作记忆 (Working)   ~3K tokens  每章注入      │  ◆ 前缀
│  ├─ 上章结尾 500 字                              │
│  ├─ 最近 5 章摘要链                              │
│  ├─ 当前活跃悬念 (前 5 条)                       │
│  └─ 本章大纲 + 关键事件                          │
├─────────────────────────────────────────────────┤
│  短期记忆 (Short-term) ~4K tokens  语义检索      │  ◇ 前缀
│  ├─ 向量检索: 本章相关历史片段 (top 3-5)         │
│  ├─ 角色关联检索: 出场角色的历史场景              │
│  └─ 物品关联检索: 涉及物品的历史                  │
├─────────────────────────────────────────────────┤
│  长期记忆 (Long-term)  ~3K tokens  定期压缩      │  ○ 前缀
│  ├─ 卷摘要 (每 10 章压缩为 200 字)               │
│  ├─ 角色弧线归档 (关键转折)                      │
│  ├─ 世界设定变更日志                             │
│  └─ 已解决悬念归档 (防止重复)                    │
└─────────────────────────────────────────────────┘
```

**Token 预算分配：** 总预算 18000 字（约 12000 tokens），永久 3000 + 工作 4500 + 短期 6000 + 长期 4500。

**关键接口：**

| 方法 | 说明 | 调用时机 |
|------|------|----------|
| `build_full_context()` | 构建四层上下文 | 每章生成前 |
| `flatten_context()` | 扁平化为带前缀标记的字典 | 合并到 knowledge_context |
| `compress_volume()` | LLM 压缩 N 章为 200 字卷摘要 | 每 10 章 |
| `archive_character_arc()` | 归档角色变化历史 | 每 10 章 |
| `archive_resolved_suspense()` | 归档已解决悬念 | 每 10 章 |
| `periodic_maintenance()` | 定期维护（压缩+归档+向量清理） | 每 10 章 |
| `append_timeline()` | 追加章节时间线 | 每章生成后 |

**记忆上下文注入流程（替换旧的 `_build_asset_context`）：**

```
章节生成前:
  memory_manager.build_full_context(current_chapter, chapter_outline, pending_suspense)
      ├─ build_working_memory()     → 最近5章摘要链 + 活跃悬念 + 大纲
      ├─ build_short_term_memory()  → 向量检索相关历史 + 角色关联 + 物品关联
      ├─ build_long_term_memory()   → 卷摘要 + 角色弧线 + 已解决悬念
      └─ build_permanent_memory()   → 力量体系 + 势力 + 主角 + S级悬念

  memory_manager.flatten_context(layered_context)
      → 按优先级合并，加前缀标记 (★◆◇○)

  combined_context = knowledge_context + memory_context
      → 注入 ChapterGenerator
```

`chapter_generator.py` 识别记忆前缀标记，对 ★◆◇○ 开头的条目放宽截断限制（3000 字符 vs 普通 1500 字符）。

### Skill 题材系统 (skills/)

Skill 是题材特有的写作风格包，以 JSON 文件形式定义，覆盖以下维度：

| 维度 | 说明 | 示例 |
|------|------|------|
| 题材身份 | 作者身份定位和行文基调 | "你是一个写了十年玄幻的老手..." |
| 写作规则 | 题材特有的风格要求 | 仙侠重意境、都市重对话节奏 |
| 时间体系 | 时间表达方式 | 十二时辰制、现代24小时制 |
| 禁用模式 | 题材特有的禁用词汇/句式 | 仙侠禁用现代科技词 |
| 同义词池 | 题材特有的词汇替换 | 功法类词汇替换池 |
| 禁止术语 | 绝对不可出现的现代词 | "手机""网络""APP" |

**Skill 匹配策略（3 级降级）：**

1. 从 Registry 自动匹配预置 Skill（如"玄幻修仙" → `xuanhuan_xianxia`）
2. LLM 自动生成 Skill（`SkillGenerator`），保存到 `skills/data/generated_*.json`
3. 使用默认兜底 Skill（`_base.json`）

预置 Skill 文件：`xuanhuan_xianxia`（玄幻修仙）、`dushi_yineng`（都市异能）、`guize_guaitan`（规则怪谈）。

### 知识采集 (knowledge/collector.py)

从 7 个维度自动采集创作知识：

1. **世界观设定** — 主流小说的世界架构、力量体系
2. **传统文化** — 道家、佛家、易经、山海经、神话传说
3. **人物塑造** — 主角/配角/反派设计方法论
4. **场景设定** — 地理环境、势力分布、特殊场景
5. **写作手法** — 叙事结构、节奏控制、黄金三章
6. **风格分析** — 知名作者风格拆解（Skill 可定制参考作家列表）
7. **竞品分析** — 头部作品成功要素、商业写作套路

### 章节生成与后处理 (generation/chapter_generator.py)

**分段生成策略**：将一章分为多个 segment 依次生成，每段传递前段末尾内容保持连贯，并提取场景指纹防止跨段重复。

**11 步后处理管线**（按执行顺序）：

| 步骤 | 方法 | 说明 |
|------|------|------|
| 1 | `_clean_chapter_ending` | 截断抒情/哲理/决心宣誓式结尾 |
| 2 | `_deduplicate_paragraphs` | 移除连续和非连续重复段落 |
| 3 | `_replace_banned_patterns` | 替换禁用模式（嘴角/眼中闪过/猛地/在这个世界里） |
| 4 | `_fix_english_leaks` | 修复英文泄露（映射表+白名单+自动翻译） |
| 5 | `_diversify_actions` | 动作词同义替换（咬紧牙关/深吸一口气/握紧拳头） |
| 6 | `_reduce_similes` | 降低"像"类比喻密度（保留33%，其余轮换替换） |
| 7 | `_reduce_shunjian` | "瞬间"降频（保留第1个，10种同义词轮换） |
| 8 | `_reduce_fangfu` | "仿佛"降频（保留前3个，6种同义词轮换） |
| 9 | `_diversify_openings` | 段落开头多样化（"他"/"林默"开头变换） |
| 10 | `_merge_short_lines` | 碎片化短句行合并为正常段落 |
| 11 | Skill extras | 题材特有的禁用模式和同义词池（来自 Skill JSON） |

### 低分重写机制 (generation/rewriter.py)

当质量评分低于 0.70 时自动触发重写：

1. **诊断**：`QualityEvaluator.diagnose()` 分析问题维度（对话不足/AI痕迹/风格偏差/综合质量）
2. **定向重写**：根据诊断结果构建针对性重写提示（如"增加对话""减少比喻""加强幽默"）
3. **后处理**：重写内容重新走完整 11 步后处理管线
4. **重新评估**：重写后重新打分，更新数据库记录
5. **日志记录**：重写历史保存到 `logs/rewrite_history.jsonl`

每章最多重写 1 次，避免无限循环。

### 剧情资产管理 (assets/)

**角色档案 (character.py)**：

- `ensure_character()`：确保角色存在，不存在则创建
- `batch_update_from_chapter()`：一次 LLM 调用批量提取多个角色的境界、功法、关系、高光时刻变化
- `get_active_character_context()`：生成活跃角色摘要，含近期变化历史，注入 LLM 上下文
- **变化历史追踪**：每次 `batch_update` 自动记录 `{chapter, changes, snapshot}` 到 `CharacterLibrary.history` 字段，保留最近 20 条

**物品与功法 (item.py)**：

- `extract_items_from_chapter()`：LLM 提取章节中新出现的物品/功法，自动入库去重
- `get_active_item_context()`：生成活跃物品摘要，注入 LLM 上下文
- `prevent_inflation()`：每 10 章执行物品盘点，防止法宝通货膨胀

**世界设定 (world_setting.py)**：

- `get_brief_world_context()`：生成世界观摘要，注入 LLM 上下文
- `verify_consistency()`：LLM 校验章节内容与世界设定的一致性（每 5 章执行）

### 悬念管理 (suspense/manager.py)

三级悬念体系，完整生命周期：

| 等级 | 类型 | 解决期限 | 示例 |
|------|------|----------|------|
| S | 主线悬念 | 贯穿全书（+100章） | 主角身世、天道阴谋 |
| A | 卷级悬念 | 当前地图（+30章） | 区域核心谜团 |
| B | 章级悬念 | 几章内（+5章） | 短期小谜团 |

流程：**记录** → **追踪**（LLM 自动检测新悬念和已解决悬念）→ **回收**（标记解决并记录方式）→ **超期预警**

`process_chapter_suspense()` 返回处理结果（`{new_suspense_titles, resolved_suspense_ids, overdue_count}`），用于更新 Chapter 记录和记忆归档。

鲁棒 JSON 解析：5 重策略（直接解析 → 代码块提取 → 最外层匹配 → 错误修复 → 截断修复），单条悬念独立容错。

### 质量评估 (evaluation/quality.py)

多维评估体系，加权计算综合评分：

| 维度 | 权重 | 评估方式 | 说明 |
|------|------|----------|------|
| AI 痕迹 | 30% | 本地正则检测 | 瞬间/仿佛/嘴角/比喻密度/英文泄露等 |
| 对话密度 | 15% | 本地正则匹配 | 多种引号格式，阶梯式评分 |
| 风格质量 | 15% | 本地关键词检测 | 幽默关键词/比喻密度/段落开头重复 |
| LLM 综合 | 40% | 单次 LLM 调用 | 连贯性/角色一致性/世界观统一性/文笔质量 |

`diagnose()` 方法返回结构化问题列表（维度/严重度/原因/修复建议），供重写器使用。`needs_rewrite()` 方法在评分低于 `REWRITE_THRESHOLD`（0.70）时返回 True。

### 向量存储 (knowledge/vector_store.py)

| 功能 | 说明 |
|------|------|
| 模块级单例 | 全局只加载一次模型，跨实例共享 |
| 后台预加载 | `preload_embedding_model()` 在初始化时立即启动 |
| 批量编码 | 大文档集自动分批（batch_size=64） |
| 向量缓存 | `_get_vectors_matrix()` 缓存 numpy 矩阵 |
| metadata 过滤 | `search()` 支持 `chapter_number_lt/gt`、`type`、`exclude_chapters` 过滤 |
| 索引清理 | `cleanup()` 去重（content hash）+ 容量控制（max_documents=2000） |
| ONNX 可选 | 设置 `EMBEDDING_BACKEND=onnx` 启用（需额外安装 `optimum` + `onnxruntime`） |

### 大纲系统 (outline/)

**初始大纲生成器 (generator.py)**：

- 多重 JSON 解析：直接解析 → 代码块提取 → 最外层匹配 → 常见错误修复 → 纯文本回退
- 升级节奏铁律：金手指限制、战斗挫折、悬念衔接规则
- 中文数字解析：支持"第一章"到"第十九章"自动转换

**动态大纲更新器 (updater.py)**：

- 续写大纲生成：基于当前进度、悬念状态和最近章节摘要
- 与初始生成器共用增强 JSON 解析策略

---

## 数据库设计

10 张核心数据表：

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `projects` | 小说项目 | title, genre, skill_id, current_chapter, target_chapters |
| `world_settings` | 世界观设定 | category, title, content |
| `character_library` | 角色档案 | name, personality, cultivation_level, skills, relationships, status, **history** |
| `item_library` | 物品与功法库 | name, item_type, grade, current_holder, status |
| `plot_points` | 剧情节点 | chapter_number, plot_type, characters_involved |
| `suspense_manager` | 悬念记录 | level(S/A/B), status, hints_planted, expected_resolve_chapter |
| `outlines` | 小说大纲 | phase(initial/update), key_events, suspense_points |
| `chapters` | 章节正文 | content, quality_score, new_characters, new_items, new_suspense, resolved_suspense |
| `task_records` | 任务执行记录 | task_type, priority, status, retry_count |
| `memory_archive` | **长期记忆归档** | archive_type(volume_summary/character_arc/world_change/suspense_archive), content, chapter_start, chapter_end, token_estimate |

**`character_library.history` 字段**（P4 新增）：

JSON 数组，记录角色在每章的变化历史，最多保留 20 条：

```json
[
  {
    "chapter": 1,
    "changes": ["cultivation_level", "skills", "status"],
    "snapshot": {"cultivation_level": "炼气一层", "status": "黑铁矿奴"}
  },
  {
    "chapter": 2,
    "changes": ["cultivation_level", "core_items"],
    "snapshot": {"cultivation_level": "炼气三层"}
  }
]
```

**`memory_archive` 表**（P4 新增）：

每 10 章由 `MemoryManager.periodic_maintenance()` 自动归档：

| archive_type | 说明 | 生成频率 |
|-------------|------|---------|
| `volume_summary` | 每 10 章压缩为 200 字摘要 | 每 10 章 |
| `character_arc` | 角色关键转折点归档 | 每 10 章 |
| `world_change` | 世界设定变更记录 | 按需 |
| `suspense_archive` | 已解决悬念及其解决方式 | 每 10 章 |

---

## 技术栈

| 组件 | 技术 |
|------|------|
| LLM 引擎 | Agnes AI (OpenAI 兼容接口) |
| 数据库 | MySQL + SQLAlchemy ORM |
| 向量化 | sentence-transformers (模块级单例 + 后台预加载) |
| ONNX 加速 | optimum + onnxruntime (可选) |
| 向量索引 | numpy 矩阵运算 (余弦相似度) |
| 中文分词 | jieba |
| 配置管理 | pydantic + python-dotenv |
| 任务调度 | 自研优先级队列 + ThreadPoolExecutor |
| 终端输出 | rich (格式化输出与进度展示) |
| 日志 | logging (控制台 + 文件双输出) |

## 测试

```bash
# 端到端测试（生成 2 章 + 验证记忆系统全链路）
python test/e2e_memory_test.py

# 记忆系统静态验证（不生成小说，仅检查代码结构）
python test/verify_memory_system.py

# 资产集成验证（角色/物品/世界设定模块协作）
python test/verify_asset_integration.py

# Skill 题材系统测试（加载/匹配/上下文注入）
python test/test_skill_system.py

# 质量评估模块测试
python test/test_new_evaluator.py

# 修复验证（回归测试，确认 bug 修复后行为正确）
python test/verify_fixes.py
python test/test_fixes.py

# 优化效果测试
python test/test_optimizations.py

# 单章生成测试（快速验证生成流程）
python test/test_ch5.py

# 项目间横向对比
python test/compare_projects.py
python test/compare_p11_p12.py

# 单项目评估
python test/evaluate_p11.py
```

> 测试输出结果保存在 `test/results/` 目录，不纳入版本控制。

## 下一步优化

### 1. 内容生成的优化

**功能描述**：针对内容生成模块进行系统性改进，全面提升生成文本的质量、上下文连贯性和生成效率。

**技术实现思路**：

- **文本质量提升**：引入更精细的质量评估维度，在现有 11 步后处理管线基础上，增加风格一致性检测和情感节奏分析模块；基于历史重写数据训练质量预测模型，提前识别潜在低分章节
- **上下文连贯性增强**：优化四层记忆架构的检索策略，引入注意力机制改进短期记忆的向量检索相关性；增加跨卷（每 10 章）的事件因果链追踪，确保长篇故事的情节连续性
- **生成效率优化**：实现基于章节类型的差异化生成策略（战斗场景重描写、对话场景重交互），根据场景类型动态调整分段策略和 token 分配；引入生成缓存机制，对相似场景描述进行复用

**预期效果**：章节质量评分均值从当前水平提升 10-15%，低分章节（<0.70）重写率降低 30%，单章生成时间缩短 20%。

---

### 2. 评估审查的优化

**功能描述**：建立更完善的内容质量评估指标体系和人工审查流程，引入自动化评估工具提升审查效率。

**技术实现思路**：

- **质量评估指标体系完善**：新增多维度评分指标，包括情感波动曲线（避免平淡如水）、冲突密度（每章至少 1 个有效冲突）、角色台词辨识度（通过角色语言特征模型评估区分度）；建立评分权重动态调整机制，根据题材特性自动优化各维度权重
- **人工审查流程优化**：设计分级复审机制，对评分临界章节（0.68-0.72）自动触发人工复核；开发可视化审查面板，支持审查者快速标注问题类型和位置，自动汇总同类问题
- **自动化评估工具引入**：集成基于规则的正则检测和基于模型的语义分析，实现 AI 痕迹、逻辑漏洞、事实不一致的自动识别；建立问题样本库，持续迭代检测规则

**预期效果**：自动化检测覆盖率提升至 95%，人工审查工作量减少 50%，评估标准一致性提升 40%。

---

### 3. 用户对章节大纲的干预及向量数据库优化

**功能描述**：实现用户对章节大纲的直接干预功能，同时对向量数据库进行全面优化以支撑更大规模的知识检索。

**技术实现思路**：

- **大纲干预功能**：
  - 提供大纲编辑接口，支持用户在章节生成前修改章节大纲（标题、核心事件、悬念设置、角色安排）
  - 实现大纲版本管理，记录用户修改历史，支持版本对比和一键回滚
  - 建立大纲变更影响分析，自动评估修改对后续章节的潜在影响并预警

- **向量数据库优化**：
  - **数据结构改进**：引入分层索引结构，按章节类型、题材领域、角色关联等维度建立多级索引；支持混合检索（向量相似度 + 关键词精确匹配）
  - **检索效率提升**：实现 ANN（近似最近邻）索引算法（如 HNSW），将检索速度提升 10 倍以上；引入查询结果缓存和预热机制
  - **存储优化**：实现向量压缩（量化压缩），降低存储成本 60%；支持增量索引更新，避免全量重建；设计冷热数据分离策略，历史数据自动归档

**预期效果**：用户可在 3 步操作内完成大纲修改，修改后章节与用户意图匹配度提升至 90%；向量检索延迟从 200ms 降至 20ms，单项目支持 500+ 章的向量化知识库。

---

### 4. 支持本地小说风格分析与注入管理

**功能描述**：新增对本地小说文件的风格特征提取与分析功能，建立风格管理系统支持风格注入，并在写作管理模块中整合风格控制功能。

**技术实现思路**：

- **本地小说风格特征提取**：
  - 开发本地小说解析器，支持 TXT、EPUB、UMD 等常见小说格式自动解析
  - 基于 NLP 技术提取风格特征维度：叙事视角使用频率、对话密度与占比、场景描写密度、情感词汇分布、修辞手法频率、章节节奏曲线
  - 建立风格向量表征，将提取的风格特征映射为高维向量，支持风格相似度计算

- **风格管理系统**：
  - 设计风格库数据结构，支持风格指纹存储、检索和复用
  - 实现风格注入机制，在章节生成时将目标风格向量与当前题材 Skill 融合，生成兼顾题材规范与目标风格的文本
  - 提供风格预览功能，生成前展示风格匹配度预测

- **写作管理模块整合**：
  - 在项目管理中新增"风格管理"面板，支持选择/上传目标风格样本
  - 实现风格一致性监控，在生成过程中检测风格漂移并预警
  - 支持风格模板导出，可将成功项目的风格配置复用到新项目

**预期效果**：用户可在 5 分钟内完成本地小说风格导入，风格匹配度达 85%以上；同一题材下可产出多种风格变体，扩展项目风格表现力。

---

## License

MIT
