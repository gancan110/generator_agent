"""
命令行入口模块

提供 CLI 接口，支持项目创建、生成启动、状态查看、断点续写等操作。

命令列表:
    init      — 初始化数据库表
    create    — 创建项目（仅初始化，不生成）
    start     — 创建项目并开始生成
    continue  — 续写已有项目
    status    — 查看项目状态
    test      — 测试 DB 和 LLM 连接

用法:
    python main.py <command> [options]
    python main.py --help            # 查看帮助
    python main.py <command> --help  # 查看命令帮助
"""

import argparse
import sys
import logging

from novel_agent.config import config
from novel_agent.generation.pipeline import GenerationPipeline
from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Project

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """
    创建命令行参数解析器。

    注册 6 个子命令（init / create / start / continue / status / test），
    每个子命令独立定义参数、类型和帮助文本。

    Returns:
        argparse.ArgumentParser: 顶层解析器
    """
    parser = argparse.ArgumentParser(
        prog="novel_agent",
        description="Agnes AI - 全自动小说生成 Agent",
        epilog=(
            "示例:\n"
            "  python main.py init\n"
            "  python main.py start -t \"破天\" -g \"玄幻修仙\" --chapters 50\n"
            "  python main.py continue -p 7 --add-chapters 10\n"
            "  python main.py status -p 7\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ---- init ----
    subparsers.add_parser(
        "init",
        help="初始化数据库，创建所有表",
        description="初始化 MySQL 数据库，创建所有表（幂等操作）。注意：不会给已有表添加新列，升级时请运行 scripts/migrate_p4.py。",
    )

    # ---- create ----
    cp = subparsers.add_parser(
        "create",
        help="创建新项目（仅初始化，不生成）",
        description="创建项目并执行初始化（Skill匹配、子系统创建），但不进入生成循环。可用 continue 命令后续开始生成。",
    )
    cp.add_argument("-t", "--title", required=True,
                    help="小说标题，如 -t \"破天\"")
    cp.add_argument("-g", "--genre", required=True,
                    help="小说题材（用于 Skill 自动匹配），如 -g \"玄幻修仙\"、\"都市异能\"、\"规则怪谈\"")
    cp.add_argument("--theme", default="",
                    help="小说主题（影响知识采集方向，默认同 genre），如 --theme \"废柴逆袭\"")
    cp.add_argument("--chapters", type=int, default=None,
                    help="目标章节数（默认读取 .env 中 DEFAULT_CHAPTERS），如 --chapters 50")

    # ---- start ----
    sp = subparsers.add_parser(
        "start",
        help="创建项目并开始生成",
        description=(
            "创建项目并立即开始完整生成流程：\n"
            "知识采集(7维度) → 世界观生成(4组件) → 大纲规划 → 逐章生成(含四层记忆注入+质量评估+重写)"
        ),
    )
    sp.add_argument("-t", "--title", required=True,
                    help="小说标题，如 -t \"破天\"")
    sp.add_argument("-g", "--genre", required=True,
                    help="小说题材（用于 Skill 自动匹配），如 -g \"玄幻修仙\"")
    sp.add_argument("--theme", default="",
                    help="小说主题（影响知识采集方向，默认同 genre），如 --theme \"商战复仇\"")
    sp.add_argument("--chapters", type=int, default=None,
                    help="目标章节数（默认读取 .env 中 DEFAULT_CHAPTERS），如 --chapters 50")

    # ---- status ----
    st = subparsers.add_parser(
        "status",
        help="查看项目状态和章节列表",
        description="查看项目状态。不指定 -p 则列出所有项目，指定 -p 则显示该项目详情（含最近10章的标题、字数和质量评分）。",
    )
    st.add_argument("-p", "--project-id", type=int,
                    help="项目 ID（不填则列出所有项目），如 -p 7")

    # ---- continue ----
    ct = subparsers.add_parser(
        "continue",
        help="续写已有项目",
        description=(
            "从已有项目继续生成章节。自动跳过知识采集和世界观生成（从 DB 恢复），\n"
            "仅执行大纲更新和章节生成，速度远快于首次生成。\n"
            "示例:\n"
            "  python main.py continue -p 7                       # 继续写到原目标\n"
            "  python main.py continue -p 7 --add-chapters 10     # 多写 10 章\n"
            "  python main.py continue -p 7 -n 3                  # 本次只写 3 章\n"
            "  python main.py continue -p 7 --from-chapter 5      # 从第 5 章开始"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ct.add_argument("-p", "--project-id", type=int, required=True,
                    help="要续写的项目 ID（必填），如 -p 7")
    ct.add_argument("--add-chapters", type=int, default=0,
                    help="在原有目标基础上多写 N 章（默认 0 = 不扩展），如 --add-chapters 10")
    ct.add_argument("--from-chapter", type=int, default=0,
                    help="从第 N 章开始续写（默认 0 = 自动接最后一章），如 --from-chapter 5")
    ct.add_argument("-n", "--num-chapters", type=int, default=0,
                    help="本次只生成 N 章（默认 0 = 写到目标数），如 -n 3")

    # ---- test ----
    subparsers.add_parser(
        "test",
        help="测试数据库和 LLM API 连接",
        description="测试 MySQL 数据库连接和 LLM API 连接是否正常。",
    )

    return parser


def cmd_init(args):
    """
    执行数据库初始化。

    调用 db_client.init_db() 创建所有表。
    幂等操作，可重复执行。不会修改已有表结构。

    Args:
        args: argparse 解析后的参数（init 无额外参数）
    """
    print("Initializing database...")
    db_client.init_db()
    print("Database initialized successfully.")


def cmd_create(args):
    """
    创建新项目（仅初始化，不生成）。

    执行流程：
    1. Skill 匹配/自动生成
    2. 创建 DB 项目记录
    3. 初始化所有子系统（知识库、向量存储、大纲生成器、记忆管理器等）

    创建完成后可通过 continue 命令开始生成。

    Args:
        args: 包含 title, genre, theme, chapters
    """
    print(f"Creating project: {args.title} ({args.genre})")

    pipeline = GenerationPipeline(
        title=args.title,
        genre=args.genre,
        theme=args.theme,
        target_chapters=args.chapters,
    )
    pipeline.initialize()
    print(f"Project created. ID: {pipeline.project_id}")


def cmd_start(args):
    """
    创建项目并开始完整生成流程。

    执行流程：
    1. 初始化（同 cmd_create）
    2. 知识采集（7 个维度）
    3. 世界观生成（4 个组件）
    4. 初始大纲生成
    5. 主循环：逐章生成（含四层记忆注入 + 质量评估 + 低分重写 + 资产更新 + 悬念管理）

    Args:
        args: 包含 title, genre, theme, chapters
    """
    print(f"Starting generation: {args.title} ({args.genre})")

    pipeline = GenerationPipeline(
        title=args.title,
        genre=args.genre,
        theme=args.theme,
        target_chapters=args.chapters,
    )
    pipeline.initialize()
    pipeline.run()


def cmd_status(args):
    """
    查看项目状态。

    - 不指定 project_id：列出所有项目的 ID、标题、题材、状态和进度
    - 指定 project_id：显示项目详情 + 最近 10 章的标题、字数和质量评分

    Args:
        args: 包含 project_id（可选）
    """
    if args.project_id:
        project = db_client.get_by_id(Project, args.project_id)
        if project:
            print(f"Project: {project.title}")
            print(f"  Genre:    {project.genre}")
            print(f"  Theme:    {project.theme or '-'}")
            print(f"  Status:   {project.status}")
            print(f"  Progress: {project.current_chapter}/{project.target_chapters}")
            print(f"  Created:  {project.created_at}")

            # 显示已有章节列表（最近 10 章）
            from novel_agent.database.models import Chapter
            chapters = db_client.get_all(Chapter, project_id=project.id)
            chapters.sort(key=lambda c: c.chapter_number)
            if chapters:
                print(f"\n  Chapters ({len(chapters)}):")
                for ch in chapters[-10:]:
                    score = f"{ch.quality_score:.2f}" if ch.quality_score else "-"
                    print(f"    #{ch.chapter_number:>3}  {ch.title:<30}  "
                          f"{ch.word_count:>5} chars  score={score}")
                if len(chapters) > 10:
                    print(f"    ... ({len(chapters) - 10} more)")
        else:
            print(f"Project not found: ID={args.project_id}")
    else:
        projects = db_client.get_all(Project)
        if not projects:
            print("No projects found.")
        else:
            print(f"{'ID':>4} | {'Title':<20} | {'Genre':<12} | {'Status':<12} | {'Progress':>8}")
            print("-" * 72)
            for p in projects:
                print(
                    f"{p.id:>4} | {p.title:<20} | {p.genre:<12} | "
                    f"{p.status:<12} | {p.current_chapter}/{p.target_chapters}"
                )


def cmd_continue(args):
    """
    续写已有项目。

    执行流程：
    1. 从 DB 加载项目（恢复 title/genre/theme/skill_id）
    2. 确定续写起始章节（自动或指定）
    3. 初始化子系统（含记忆管理器）
    4. 恢复知识上下文（跳过 LLM 采集）
    5. 重建向量存储
    6. 生成续写大纲
    7. 进入主循环

    参数组合说明：
    - 仅 -p：从最后章节续写到原目标
    - -p + --add-chapters 10：从最后章节续写，目标增加 10 章
    - -p + -n 3：从最后章节续写，本次只写 3 章
    - -p + --from-chapter 5：从第 5 章开始（覆盖/重写）
    - -p + --from-chapter 5 + -n 10 + --add-chapters 10：从第 5 章开始，写 10 章，目标扩展 10 章

    Args:
        args: 包含 project_id, add_chapters, from_chapter, num_chapters
    """
    print(f"Continuing project ID={args.project_id}...")

    pipeline = GenerationPipeline(
        title="",  # 将从 DB 恢复
        genre="",  # 将从 DB 恢复
        target_chapters=None,
        skip_skill_init=True,  # 跳过 Skill 初始化，由 resume() 从 DB 恢复
    )

    # 确定本次续写的目标章节数
    # 如果用户指定了 -n (num-chapters) 但未指定 --add-chapters，
    # 需先查看当前进度以判断是否需要扩展目标
    add_chapters = args.add_chapters
    if args.num_chapters > 0 and add_chapters == 0:
        db_client.init_db()
        project = db_client.get_by_id(Project, args.project_id)
        if project:
            needed = (project.current_chapter + args.num_chapters) - project.target_chapters
            if needed > 0:
                add_chapters = needed

    pipeline.resume(
        project_id=args.project_id,
        add_chapters=add_chapters,
        from_chapter=args.from_chapter,
    )


def cmd_test(args):
    """
    测试数据库和 LLM API 连接。

    依次测试：
    1. MySQL 数据库连接
    2. LLM API 连接（发送简单请求并检查响应）

    Args:
        args: argparse 解析后的参数（test 无额外参数）
    """
    print("Testing database connection...")
    if db_client.test_connection():
        print("  [OK] Database connection successful")
    else:
        print("  [FAIL] Database connection failed")

    print("Testing LLM API connection...")
    try:
        from novel_agent.utils.llm_client import llm_client
        result = llm_client.generate("reply with: OK", max_tokens=20)
        print(f"  [OK] LLM API response: {result.strip()[:60]}")
    except Exception as e:
        print(f"  [FAIL] LLM API error: {e}")


def main():
    """
    CLI 主入口函数。

    解析命令行参数，路由到对应的命令处理函数。
    无命令时打印帮助信息。

    命令路由表:
        init     → cmd_init
        create   → cmd_create
        start    → cmd_start
        continue → cmd_continue
        status   → cmd_status
        test     → cmd_test
    """
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "init": cmd_init,
        "create": cmd_create,
        "start": cmd_start,
        "continue": cmd_continue,
        "status": cmd_status,
        "test": cmd_test,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
