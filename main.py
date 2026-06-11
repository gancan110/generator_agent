"""
Agnes AI 小说生成 Agent — 主入口

全自动小说创作引擎，通过四层记忆架构 + Skill 题材系统 + 多阶段生成策略，
实现从题材输入到完整长篇（100+ 章）的自动化生产。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

命令一览:
    python main.py init                                        # 初始化数据库
    python main.py test                                        # 测试 DB 和 LLM 连接
    python main.py create  -t "标题" -g "题材"                   # 创建项目（不生成）
    python main.py start   -t "标题" -g "题材" --chapters 50     # 创建并开始生成
    python main.py continue -p <项目ID>                          # 续写已有项目
    python main.py status  [-p <项目ID>]                         # 查看项目状态

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

命令详解:

    init
        初始化 MySQL 数据库，创建所有表（幂等操作，可重复执行）。
        注意：不会给已有表添加新列，升级时请运行 scripts/migrate_p4.py。
        示例:
            python main.py init

    test
        测试数据库连接和 LLM API 连接是否正常。
        示例:
            python main.py test

    create  -t TITLE -g GENRE [--theme THEME] [--chapters N]
        创建新项目，执行初始化（Skill匹配、子系统创建）但不生成章节。
        参数:
            -t, --title     小说标题（必填）
            -g, --genre     小说题材（必填），用于 Skill 自动匹配
            --theme         小说主题（可选），影响知识采集方向，默认同 genre
            --chapters      目标章节数（可选），默认读取 .env 中 DEFAULT_CHAPTERS
        示例:
            python main.py create -t "破天" -g "玄幻修仙" --chapters 50
            python main.py create -t "重生之巅峰" -g "都市重生" --theme "商战复仇"
            python main.py create -t "幸福小区" -g "规则怪谈" --chapters 20

    start   -t TITLE -g GENRE [--theme THEME] [--chapters N]
        创建项目并立即开始生成。参数与 create 一致。
        生成流程: 知识采集 → 世界观生成 → 大纲规划 → 逐章生成（含记忆注入+质量评估+重写）
        示例:
            python main.py start -t "破天" -g "玄幻修仙" --chapters 50
            python main.py start -t "映道" -g "末日系统" --chapters 10
            python main.py start -t "星环纪元" -g "科幻星际" --theme "AI觉醒" --chapters 40

    continue -p PROJECT_ID [--add-chapters N] [-n N] [--from-chapter N]
        续写已有项目。自动跳过知识采集和世界观生成，从 DB 恢复上下文。
        参数:
            -p, --project-id    项目 ID（必填）
            --add-chapters      在原有目标基础上多写 N 章（默认 0 = 不扩展）
            -n, --num-chapters  本次只生成 N 章（默认 0 = 写到目标数）
            --from-chapter      从指定章节开始续写（默认 0 = 自动接最后一章）
        示例:
            python main.py continue -p 7                        # 继续写到原目标
            python main.py continue -p 7 --add-chapters 10      # 多写 10 章
            python main.py continue -p 7 -n 3                   # 本次只写 3 章
            python main.py continue -p 7 --from-chapter 5       # 从第 5 章开始
            python main.py continue -p 7 --from-chapter 5 -n 10 --add-chapters 10

    status  [-p PROJECT_ID]
        查看项目状态。不指定 -p 则列出所有项目，指定 -p 则显示详情（含章节列表）。
        示例:
            python main.py status           # 列出所有项目
            python main.py status -p 7      # 查看项目 7 的详情

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

环境变量配置 (.env):

    # LLM 配置（必填）
    AGNES_API_KEY=sk-xxxxx
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

    # 路径配置（可选）
    VECTOR_DB_PATH=./vector_db
    LOG_DIR=./logs
    OUTPUT_DIR=./output

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

升级说明:
    从旧版本升级到 P4（四层记忆系统）后，需运行数据库迁移:
        python scripts/migrate_p4.py
    该脚本会添加 memory_archive 表和 character_library.history 字段。

依赖:
    pip install -r requirements.txt

版本:
    包含 P4 四层记忆架构、Skill 系统、资产集成、重写机制、11 步后处理。
"""

from novel_agent.cli.main import main

if __name__ == "__main__":
    main()
