# Agnes AI 小说生成Agent

全自动长篇小说创作引擎，支持100+章自动化生产。

## 功能特性

- **四层记忆架构**: Working/Short-term/Long-term/Permanent分层管理，解决超长篇上下文丢失问题
- **动态质量控制**: 评分低于阈值自动重写，参数动态调整
- **资产全生命周期**: 角色/物品/悬念状态完整追踪
- **Skill系统**: 预置题材匹配 + LLM自动生成
- **Web向导**: 12步交互式创作流程

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境

复制 `.env.example` 为 `.env` 并填入配置：

```bash
# MySQL 配置
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DATABASE=agnes_novel

# LLM 配置
AGNES_API_KEY=sk-xxxxx
AGNES_BASE_URL=https://apihub.agnes-ai.com/v1
AGNES_MODEL=agnes-2.0-flash
```

### 初始化数据库

```bash
python main.py init
```

### 创建并开始生成

```bash
python main.py start -t "破天" -g "玄幻修仙" --chapters 50
```

### 启动Web界面

```bash
python web/server.py
```

访问 http://localhost:5000

## 项目结构

```
agnesAi_v2/
├── main.py                    # CLI主入口
├── requirements.txt           # 依赖列表
├── .env                       # 环境变量配置
├── novel_agent/               # 核心模块
│   ├── config.py             # 配置管理
│   ├── core/                 # 核心事件系统
│   ├── database/             # 数据库模型和客户端
│   ├── knowledge/            # 知识管理和向量存储
│   ├── memory/               # 四层记忆系统
│   ├── generation/           # 章节生成和重写
│   ├── outline/              # 大纲生成和更新
│   ├── assets/               # 角色/物品/世界设定管理
│   ├── suspense/             # 悬念管理系统
│   ├── evaluation/           # 质量评估和参数优化
│   ├── skills/               # Skill题材适配系统
│   ├── scheduler/            # 任务调度器
│   ├── utils/                # 工具函数和异常处理
│   └── cli/                  # CLI命令行接口
├── web/                      # Web界面
│   ├── server.py             # Flask服务器
│   ├── static/               # 静态资源
│   └── prompts/              # Prompt模板
├── tests/                    # 单元测试
├── docs/                     # 文档
│   ├── architecture.md       # 架构文档
│   └── api.md                # API文档
├── vector_db/                # 向量数据库存储
├── output/                   # 生成的小说输出
└── logs/                     # 日志文件
```

## CLI命令

| 命令 | 说明 |
|------|------|
| `python main.py init` | 初始化数据库 |
| `python main.py test` | 测试连接 |
| `python main.py create -t "标题" -g "题材"` | 创建项目（不生成） |
| `python main.py start -t "标题" -g "题材" --chapters N` | 创建并开始生成 |
| `python main.py continue -p <项目ID>` | 续写已有项目 |
| `python main.py status [-p <项目ID>]` | 查看项目状态 |

## 核心模块

### 记忆系统

四层记忆架构，为超长篇小说提供连贯的创作上下文：

- **工作记忆**: 每章注入，包含上章结尾、最近摘要、活跃悬念
- **短期记忆**: 语义检索，基于向量相似度匹配历史片段
- **长期记忆**: 定期压缩，卷摘要、角色弧线、已解决悬念
- **永久记忆**: 始终注入，世界观核心设定、主角档案

### 质量控制

- 质量评估器自动评分
- 低于阈值触发重写
- 参数动态调整

### 资产管理

- **角色**: 档案创建、状态追踪、人际关系、高光时刻
- **物品**: 追踪持有/损毁/赠送/遗失、品阶分类
- **悬念**: S/A/B三级管理、状态追踪

## 文档

- [架构文档](docs/architecture.md)
- [API文档](docs/api.md)

## 测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_vector_store.py -v
```

## 许可证

MIT License
