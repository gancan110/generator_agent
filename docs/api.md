# Agnes AI 小说生成Agent - API文档

## CLI 命令行接口

### 初始化数据库

```bash
python main.py init
```

**功能**: 初始化MySQL数据库，创建所有表（幂等操作，可重复执行）

**输出**: 
```
正在初始化数据库表...
数据库表初始化完成
```

### 测试连接

```bash
python main.py test
```

**功能**: 测试数据库连接和LLM API连接是否正常

**输出**:
```
数据库连接测试成功
LLM API连接测试成功
```

### 创建项目

```bash
python main.py create -t "标题" -g "题材" [--theme "主题"] [--chapters N]
```

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `-t, --title` | string | 是 | 小说标题 |
| `-g, --genre` | string | 是 | 小说题材（如"玄幻修仙"、"都市重生"） |
| `--theme` | string | 否 | 小说主题，默认同genre |
| `--chapters` | int | 否 | 目标章节数，默认读取.env配置 |

**示例**:
```bash
python main.py create -t "破天" -g "玄幻修仙" --chapters 50
python main.py create -t "重生之巅峰" -g "都市重生" --theme "商战复仇"
```

### 开始生成

```bash
python main.py start -t "标题" -g "题材" [--theme "主题"] [--chapters N]
```

**功能**: 创建项目并立即开始生成

**生成流程**: 知识采集 → 世界观生成 → 大纲规划 → 逐章生成（含记忆注入+质量评估+重写）

**示例**:
```bash
python main.py start -t "破天" -g "玄幻修仙" --chapters 50
python main.py start -t "映道" -g "末日系统" --chapters 10
```

### 续写项目

```bash
python main.py continue -p <项目ID> [--add-chapters N] [-n N] [--from-chapter N]
```

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `-p, --project-id` | int | 是 | 项目ID |
| `--add-chapters` | int | 否 | 在原有目标基础上多写N章（默认0） |
| `-n, --num-chapters` | int | 否 | 本次只生成N章（默认0=写到目标数） |
| `--from-chapter` | int | 否 | 从指定章节开始续写（默认0=自动检测） |

**示例**:
```bash
python main.py continue -p 7                        # 继续写到原目标
python main.py continue -p 7 --add-chapters 10      # 多写10章
python main.py continue -p 7 -n 3                   # 本次只写3章
python main.py continue -p 7 --from-chapter 5       # 从第5章开始
```

### 查看状态

```bash
python main.py status [-p <项目ID>]
```

**功能**: 查看项目状态

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `-p, --project-id` | int | 否 | 项目ID，不指定则列出所有项目 |

**示例**:
```bash
python main.py status           # 列出所有项目
python main.py status -p 7      # 查看项目7的详情
```

---

## Web API 接口

### 基础URL

```
http://localhost:5000/api
```

### 创建向导会话

**端点**: `POST /wizard/create`

**请求体**: 无

**响应**:
```json
{
    "session_id": "abc12345",
    "step": "title_input",
    "step_idx": 0
}
```

### 获取向导状态

**端点**: `GET /wizard/<session_id>`

**响应**:
```json
{
    "session_id": "abc12345",
    "step": "genre_input",
    "step_idx": 1,
    "status": "idle",
    "project_id": 1,
    "project_name": "我的小说_abc1",
    "confirmed": {
        "title_input": true,
        "genre_input": false
    },
    "data": {},
    "steps": ["title_input", "genre_input", "..."]
}
```

### 获取步骤提示词

**端点**: `GET /wizard/<session_id>/prompt/<step>`

**步骤列表**:
1. `title_input` - 输入小说标题
2. `genre_input` - 输入小说题材
3. `writing_style` - 设定写作风格
4. `worldview` - 生成世界观
5. `skill` - 生成写作技巧指南
6. `import_novel` - 导入已有小说
7. `project_init` - 初始化项目
8. `outline` - 生成大纲
9. `chapter_config` - 章节参数配置
10. `chapter_gen` - 生成章节内容
11. `chapter_review` - 章节审核
12. `chapter_update` - 更新数据库

**响应示例** (genre_input):
```json
{
    "type": "model",
    "system_prompt": "你是一位资深的网文编辑...",
    "user_prompt": "请分析玄幻修仙类型小说的特点...",
    "temperature": 0.7,
    "description": "请输入小说题材，系统将自动分析该题材的特点",
    "fields": [
        {
            "name": "genre",
            "label": "小说题材",
            "type": "text",
            "required": true,
            "placeholder": "如：玄幻修仙、都市异能、规则怪谈"
        }
    ]
}
```

### 保存步骤数据

**端点**: `POST /wizard/<session_id>/save`

**请求体**:
```json
{
    "step": "genre_input",
    "data": {
        "genre": "玄幻修仙",
        "result": "玄幻修仙小说特点分析...",
        "user_prompt": "编辑后的提示词..."
    }
}
```

**响应**:
```json
{
    "ok": true
}
```

### 生成内容

**端点**: `GET /wizard/<session_id>/generate/<step>`

**响应**: Server-Sent Events (SSE) 流

**事件格式**:
```
data: {"type": "chunk", "text": "生成的文本片段"}

data: {"type": "done", "text": "完整的生成内容"}

data: {"type": "error", "text": "错误信息"}
```

### 确认步骤

**端点**: `POST /wizard/<session_id>/confirm`

**请求体**:
```json
{
    "step": "genre_input",
    "data": {}
}
```

**响应**:
```json
{
    "ok": true,
    "next_step": "writing_style",
    "next_step_idx": 2,
    "confirmed": {
        "title_input": true,
        "genre_input": true
    },
    "loop_back": false
}
```

### 获取大纲数据

**端点**: `GET /wizard/<session_id>/outline-data`

**响应**:
```json
{
    "outline": "大纲内容...",
    "current_chapter": 1,
    "total_chapters": 10,
    "completed_chapters": [1, 2, 3]
}
```

---

## Python API 接口

### GenerationPipeline

```python
from novel_agent.generation.pipeline import GenerationPipeline

# 创建流水线
pipeline = GenerationPipeline(
    title="小说标题",
    genre="玄幻修仙",
    theme="修仙",
    target_chapters=100,
    skill_id=None,  # 自动匹配
)

# 初始化
pipeline.initialize()

# 运行完整生成
pipeline.run()

# 或续写已有项目
pipeline.resume(
    project_id=1,
    add_chapters=10,
    from_chapter=0,
)
```

### VectorStore

```python
from novel_agent.knowledge.vector_store import VectorStore

# 创建向量存储
vs = VectorStore(project_id=1)

# 添加文档
vs.add_documents([
    {"content": "文档内容", "metadata": {"type": "chapter", "chapter_number": 1}}
])

# 搜索
results = vs.search("查询内容", top_k=5, filters={"type": "chapter"})

# 清理
vs.cleanup(max_documents=2000)

# 清空
vs.clear()
```

### MemoryManager

```python
from novel_agent.memory.manager import MemoryManager

# 创建记忆管理器
mm = MemoryManager(project_id=1, vector_store=vector_store)

# 构建完整上下文
context = mm.build_full_context(
    current_chapter=10,
    chapter_outline={"title": "第10章", "summary": "..."},
    pending_suspense=[],
)

# 扁平化上下文
flat_context = mm.flatten_context(context)

# 追加时间线
mm.append_timeline(chapter_data, suspense_result)

# 定期维护
mm.periodic_maintenance(current_chapter=10)
```

### QualityEvaluator

```python
from novel_agent.evaluation.quality import QualityEvaluator

# 创建评估器
evaluator = QualityEvaluator(genre="玄幻修仙")

# 评估内容
score = evaluator.evaluate(
    content="章节内容...",
    chapter_number=1,
)

# 检查是否需要重写
if evaluator.needs_rewrite():
    issues = evaluator.diagnose()
    print(f"需要重写，问题: {issues}")

# 获取报告
report = evaluator.get_last_report()
```

### Skill系统

```python
from novel_agent.skills import SkillRegistry, SkillContext, SkillGenerator

# 注册所有预置Skill
SkillRegistry.register_all()

# 匹配Skill
skill_id = SkillRegistry.match("玄幻修仙")

# 创建Skill上下文
skill_context = SkillContext(skill_id)

# 自动生成Skill
generated_id = SkillGenerator.generate("玄幻修仙", "修仙")
```

---

## 配置项说明

### 生成参数配置 (GenerationConfig)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `default_chapters` | 100 | 默认章节数 |
| `words_per_chapter` | 8000 | 每章字数 |
| `words_per_segment` | 3000 | 每段字数 |
| `outline_temperature` | 0.3 | 大纲生成温度 |
| `chapter_temperature` | 0.7 | 章节写作温度 |
| `evaluation_temperature` | 0.1 | 评估温度 |
| `quality_threshold` | 0.7 | 质量阈值 |
| `rewrite_threshold` | 0.70 | 重写阈值 |
| `outline_update_interval` | 5 | 大纲更新间隔（章） |

### 记忆系统预算

| 记忆层 | 预算(字符) | 约Token数 |
|--------|------------|-----------|
| 永久记忆 | 3000 | ~2000 |
| 长期记忆 | 4500 | ~3000 |
| 短期记忆 | 6000 | ~4000 |
| 工作记忆 | 4500 | ~3000 |

### 向量数据库配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `db_path` | ./vector_db | 存储路径 |
| `chunk_size` | 2000 | 文档切片大小 |
| `chunk_overlap` | 200 | 切片重叠字符数 |
| `embedding_model` | paraphrase-multilingual-MiniLM-L12-v2 | 嵌入模型 |
