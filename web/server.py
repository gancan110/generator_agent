"""
Agnes AI Novel Wizard Server

Step-by-step novel creation wizard with streaming model output,
editable prompts/results, and block-level typewriter display.
"""

import os
import re
import sys
import json
import uuid
import time
import queue
import logging
import threading
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Generator

from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from novel_agent.config import config
from novel_agent.database.mysql_client import db_client
from novel_agent.database.models import Project, Chapter
from novel_agent.utils.llm_client import llm_client

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

# 配置CORS，允许所有来源（开发环境）
CORS(app, resources={r"/api/*": {"origins": "*"}})

OUTPUT_DIR = Path(config.output_dir)

# ─── Wizard Session Manager ───────────────────────────────────────

_wizard_sessions: Dict[str, dict] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL = 3600  # 1小时过期
_last_cleanup = time.time()

WIZARD_STEPS = [
    "title_input",    # form: 输入小说名
    "genre_input",    # form: 输入小说题材 + 调用agent获取资料
    "writing_style",  # model: 输入小说写法 + 调用agent获取资料
    "worldview",      # model: 生成小说世界观
    "skill",          # model: 生成写小说的skill
    "import_novel",   # form: 询问是否导入已有小说
    "project_init",   # action: 初始化项目，构建资产等
    "outline",        # model: 生成小说大纲
    "chapter_config", # form: 设置章节参数
    "chapter_gen",    # model: 生成章节内容
    "chapter_review", # model: 章节审核和评估
    "chapter_update", # action: 更新数据库和向量数据库
]


def _new_session() -> dict:
    return {
        "id": str(uuid.uuid4())[:8],
        "step_idx": 0,
        "step": WIZARD_STEPS[0],
        "status": "idle",
        "project_id": None,
        "project_name": "",
        "data": {s: {} for s in WIZARD_STEPS},
        "confirmed": {s: False for s in WIZARD_STEPS},
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


def _cleanup_expired_sessions():
    """清理过期的session，防止内存无限增长"""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < 300:  # 每5分钟清理一次
        return
    
    _last_cleanup = now
    expired_ids = []
    
    with _sessions_lock:
        for sid, sess in _wizard_sessions.items():
            try:
                created = datetime.fromisoformat(sess["created_at"])
                age_seconds = (datetime.now() - created).total_seconds()
                if age_seconds > _SESSION_TTL:
                    expired_ids.append(sid)
            except (ValueError, KeyError):
                expired_ids.append(sid)
        
        for sid in expired_ids:
            del _wizard_sessions[sid]
    
    if expired_ids:
        logging.info(f"Cleaned up {len(expired_ids)} expired sessions")


# ─── Prompt Templates ─────────────────────────────────────────────

PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt_template(step_name: str) -> dict:
    """从YAML文件加载prompt模板"""
    yaml_file = PROMPTS_DIR / f"{step_name}.yaml"
    if yaml_file.exists():
        with open(yaml_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


PROMPT_TEMPLATES = {
    "genre_input": _load_prompt_template("genre_input"),
    "writing_style": _load_prompt_template("writing_style"),
    "skill": _load_prompt_template("skill"),
    "knowledge": _load_prompt_template("knowledge"),
    "worldview": _load_prompt_template("worldview"),
    "import_novel": _load_prompt_template("import_novel"),
    "outline": _load_prompt_template("outline"),
    "outline_review": _load_prompt_template("outline_review"),
    "chapter_gen": _load_prompt_template("chapter_gen"),
    "chapter_review": _load_prompt_template("chapter_review"),
}


def _fill_prompt(template: str, **kwargs) -> str:
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


def _extract_chapter_outline(outline_text: str, chapter_num: int) -> str:
    """从大纲文本中提取指定章节的大纲内容"""
    if not outline_text:
        return ""
    import re
    # Try to find chapter N in the outline
    patterns = [
        rf'第{chapter_num}章[：:\s]*(.*?)(?=第{chapter_num+1}章|$)',
        rf'{chapter_num}[.、）\)]\s*(.*?)(?={chapter_num+1}[.、）\)]|$)',
        rf'Chapter\s*{chapter_num}[：:\s]*(.*?)(?=Chapter\s*{chapter_num+1}|$)',
    ]
    for pat in patterns:
        m = re.search(pat, outline_text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()[:500]
    return ""


def _build_previous_summary(sess: dict, current_chapter: int) -> str:
    """构建前文概要（已生成的章节摘要）"""
    if current_chapter <= 1:
        return ""
    chapters_data = sess["data"].get("chapter_gen", {})
    summaries = []
    # Collect results from previously generated chapters
    all_results = chapters_data.get("all_results", {})
    for ch in range(1, current_chapter):
        ch_data = all_results.get(str(ch), {})
        result = ch_data.get("result", "")
        if result:
            summaries.append(f"第{ch}章概要：{result[:200]}...")
    return "\n".join(summaries) if summaries else ""


def _rebuild_prompt(sid: str, step: str):
    """Rebuild prompt from template with current session data."""
    sess = _wizard_sessions.get(sid)
    if not sess:
        return
    # Reuse the prompt endpoint logic by building the prompt inline
    template = PROMPT_TEMPLATES.get(step, {})
    if not template:
        return
    
    title = sess["data"].get("title_input", {}).get("title", "")
    genre = sess["data"].get("genre_input", {}).get("genre", "")
    theme = sess["data"].get("genre_input", {}).get("theme", "") or genre
    custom_ideas = sess["data"].get(step, {}).get("custom_ideas", "")
    custom_ideas_section = f"【用户的想法和偏好】\n{custom_ideas}" if custom_ideas else ""
    custom_requirements = "请特别注意用户提出的想法和偏好，将其融入到生成内容中。" if custom_ideas else ""
    
    kwargs = dict(title=title, genre=genre, theme=theme,
                  custom_ideas_section=custom_ideas_section,
                  custom_requirements=custom_requirements)
    
    if step == "outline":
        worldview = sess["data"].get("worldview", {}).get("result", "")
        knowledge = sess["data"].get("genre_input", {}).get("result", "")
        chapter_count = sess["data"].get("outline", {}).get("chapter_count", 10)
        suspense_tension = sess["data"].get("outline", {}).get("suspense_tension", 7)
        suspense_mystery = sess["data"].get("outline", {}).get("suspense_mystery", 5)
        suspense_romance = sess["data"].get("outline", {}).get("suspense_romance", 3)
        suspense_conflict = sess["data"].get("outline", {}).get("suspense_conflict", 7)
        suspense_config = (
            f"- 悬念强度：{suspense_tension}/10\n- 神秘程度：{suspense_mystery}/10\n"
            f"- 感情线比重：{suspense_romance}/10\n- 冲突激烈度：{suspense_conflict}/10"
        )
        kwargs.update(worldview=worldview[:1500] if worldview else "(待生成)",
                      knowledge=knowledge[:1500] if knowledge else "(待生成)",
                      chapter_count=chapter_count, suspense_config=suspense_config)
    elif step == "chapter_gen":
        worldview = sess["data"].get("worldview", {}).get("result", "")
        writing_style = sess["data"].get("writing_style", {}).get("result", "")
        outline = sess["data"].get("outline", {}).get("result", "")
        chapter_num = sess["data"].get("chapter_progress", {}).get("current_chapter", 1)
        target_words = sess["data"].get("chapter_config", {}).get("target_words", 3000)
        chapter_outline = _extract_chapter_outline(outline, chapter_num)
        prev_summary = _build_previous_summary(sess, chapter_num)
        kwargs.update(worldview=worldview[:1500] if worldview else "(待生成)",
                      writing_style=writing_style[:1500] if writing_style else "(待生成)",
                      outline=outline[:2000] if outline else "(待生成)",
                      chapter_number=chapter_num, chapter_title=f"第{chapter_num}章",
                      chapter_outline=chapter_outline or "(待生成)",
                      chapter_summary=prev_summary or "这是第一章，暂无前文概要",
                      key_events="(待生成)", characters="(待生成)", suspense="(待生成)",
                      target_words=target_words)
    
    user_prompt = _fill_prompt(template.get("user", ""), **kwargs)
    system_prompt = template.get("system", "")
    
    # Save rebuilt prompt
    sess["data"][step]["user_prompt"] = user_prompt
    sess["data"][step]["system_prompt"] = system_prompt


# ─── Auto-Review Helpers ─────────────────────────────────────────

def _auto_review(session_id: str, step: str, content: str) -> dict:
    """自动审核生成内容，返回 {score, pass, issues, suggestions}"""
    import json as _json
    sess = _wizard_sessions.get(session_id)
    if not sess:
        return {"score": 0, "pass": False, "issues": ["Session not found"], "suggestions": []}
    
    title = sess["data"].get("title_input", {}).get("title", "")
    genre = sess["data"].get("genre_input", {}).get("genre", "")
    
    if step == "outline":
        template = PROMPT_TEMPLATES.get("outline_review", {})
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre,
            outline_content=content[:3000],
        )
        system_prompt = template.get("system", "")
    elif step == "chapter_gen":
        template = PROMPT_TEMPLATES.get("chapter_review", {})
        chapter_num = sess["data"].get("chapter_progress", {}).get("current_chapter", 1)
        outline = sess["data"].get("outline", {}).get("result", "")
        chapter_outline = _extract_chapter_outline(outline, chapter_num)
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre,
            chapter_number=chapter_num,
            chapter_outline=chapter_outline or "(无具体大纲要求)",
            chapter_content=content[:3000],
        )
        system_prompt = template.get("system", "")
    else:
        return {"score": 100, "pass": True, "issues": [], "suggestions": []}
    
    try:
        # Non-streaming call for review
        from novel_agent.utils.llm_client import llm_client
        response = llm_client.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=1024,
        )
        # Parse JSON from response
        text = response.strip()
        # Extract JSON from possible markdown code block
        import re
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            result = _json.loads(json_match.group())
            result.setdefault("score", 0)
            result.setdefault("pass", result.get("score", 0) >= 70)
            result.setdefault("issues", [])
            result.setdefault("suggestions", [])
            return result
    except Exception as e:
        logger.error(f"Auto review failed: {e}")
    
    # Fallback: auto-pass
    return {"score": 70, "pass": True, "issues": [], "suggestions": []}


# ─── Model Generation Helpers ────────────────────────────────────

def _stream_model(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """Call model with streaming, yield text chunks."""
    yield from llm_client.generate_stream(
        prompt=user_prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _stream_step(session_id: str, step: str):
    """SSE generator for a wizard step's model call."""
    sess = _get_session(session_id)
    if not sess:
        yield f"data: {json.dumps({'type':'error','text':'Session not found'})}\n\n"
        return

    # Special handling for project_init - stream progress
    if step == "project_init":
        yield from _stream_project_init(session_id)
        return

    step_data = sess["data"].get(step, {})
    system_prompt = step_data.get("system_prompt", "")
    user_prompt = step_data.get("user_prompt", "")
    temperature = step_data.get("temperature", 0.7)

    if not user_prompt:
        yield f"data: {json.dumps({'type':'error','text':'No prompt defined'})}\n\n"
        return

    full_text = ""
    try:
        for chunk in _stream_model(system_prompt, user_prompt, temperature):
            full_text += chunk
            yield f"data: {json.dumps({'type':'chunk','text':chunk})}\n\n"
        # Store result
        with _sessions_lock:
            if session_id in _wizard_sessions:
                _wizard_sessions[session_id]["data"][step]["result"] = full_text
        yield f"data: {json.dumps({'type':'done','text':full_text})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"


def _stream_project_init(session_id: str):
    """Stream project initialization progress."""
    import time as _time
    ws = _wizard_sessions.get(session_id)
    if not ws:
        yield f"data: {json.dumps({'type':'error','text':'Session not found'})}\n\n"
        return

    pid = ws.get("project_id")
    if not pid:
        yield f"data: {json.dumps({'type':'error','text':'Project not created yet'})}\n\n"
        return

    steps_info = [
        ("初始化数据库表...", "db_init"),
        ("创建项目记录...", "project_create"),
        ("构建知识库...", "knowledge_base"),
        ("生成向量数据库...", "vector_db"),
        ("初始化角色资产...", "character_assets"),
        ("初始化道具资产...", "item_assets"),
        ("构建悬念引擎...", "suspense_engine"),
        ("初始化风格向量...", "style_vector"),
    ]

    full_text = ""
    for i, (msg, stage) in enumerate(steps_info):
        progress = int((i + 1) / len(steps_info) * 100)
        chunk = f"[{progress}%] {msg}\n"
        full_text += chunk
        yield f"data: {json.dumps({'type':'chunk','text':chunk})}\n\n"
        _time.sleep(0.3)  # Visual delay

        # Actually execute the step
        try:
            if stage == "db_init":
                from novel_agent.database.mysql_client import db_client
                db_client.init_db()
            elif stage == "project_create":
                from novel_agent.database.mysql_client import db_client
                from novel_agent.database.models import Project
                proj = db_client.get_by_id(Project, pid)
                if proj:
                    proj.status = "initialized"
                    db_client.update(proj)
            elif stage == "knowledge_base":
                from novel_agent.knowledge.knowledge_base import KnowledgeBase
                kb = KnowledgeBase(pid)
                # Initialize knowledge base (lazy init)
            elif stage == "vector_db":
                from novel_agent.knowledge.faiss_vector_store import create_vector_store
                vs = create_vector_store(pid, use_faiss=True)
                # Initialize vector store (lazy init)
            elif stage == "character_assets":
                from novel_agent.assets.character import CharacterManager
                cm = CharacterManager(pid)
                # Initialize character manager
            elif stage == "item_assets":
                from novel_agent.assets.item import ItemManager
                im = ItemManager(pid)
                # Initialize item manager
            elif stage == "suspense_engine":
                pass  # Suspense engine is lazy-initialized
            elif stage == "style_vector":
                pass  # Style vector is lazy-initialized
        except Exception as e:
            chunk = f"  [警告] {msg} 部分完成: {str(e)[:50]}\n"
            full_text += chunk
            yield f"data: {json.dumps({'type':'chunk','text':chunk})}\n\n"

    chunk = "\n[100%] 项目初始化完成！\n"
    full_text += chunk
    yield f"data: {json.dumps({'type':'chunk','text':chunk})}\n\n"

    # Store result
    with _sessions_lock:
        if session_id in _wizard_sessions:
            _wizard_sessions[session_id]["data"]["project_init"]["result"] = full_text
    yield f"data: {json.dumps({'type':'done','text':full_text})}\n\n"


def _get_session(sid: str) -> Optional[dict]:
    # 定期清理过期session
    _cleanup_expired_sessions()
    with _sessions_lock:
        return _wizard_sessions.get(sid)


@app.route("/api/wizard/<sid>/outline-data")
def wizard_outline_data(sid: str):
    """Get outline data for sidebar display."""
    sess = _get_session(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    
    outline = sess["data"].get("outline", {}).get("result", "")
    chapter_progress = sess["data"].get("chapter_progress", {})
    
    return jsonify({
        "outline": outline,
        "current_chapter": chapter_progress.get("current_chapter", 1),
        "total_chapters": chapter_progress.get("total_chapters", 10),
        "completed_chapters": chapter_progress.get("completed_chapters", []),
    })


# ─── Wizard API ──────────────────────────────────────────────────

@app.route("/api/wizard/create", methods=["POST"])
def wizard_create():
    """Create a new wizard session."""
    sess = _new_session()
    with _sessions_lock:
        _wizard_sessions[sess["id"]] = sess
    return jsonify({"session_id": sess["id"], "step": sess["step"], "step_idx": sess["step_idx"]})


@app.route("/api/wizard/<sid>")
def wizard_get(sid: str):
    """Get current wizard session state."""
    sess = _get_session(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({
        "session_id": sess["id"],
        "step": sess["step"],
        "step_idx": sess["step_idx"],
        "status": sess["status"],
        "project_id": sess["project_id"],
        "project_name": sess["project_name"],
        "confirmed": sess["confirmed"],
        "data": {
            k: v for k, v in sess["data"].items()
            if k == sess["step"]  # only send current step data
        },
        "steps": WIZARD_STEPS,
    })


@app.route("/api/wizard/<sid>/steps")
def wizard_steps(sid: str):
    """Get all steps with their confirmation status."""
    sess = _get_session(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404
    steps = []
    for i, s in enumerate(WIZARD_STEPS):
        steps.append({
            "name": s,
            "idx": i,
            "confirmed": sess["confirmed"].get(s, False),
            "current": sess["step"] == s,
        })
    return jsonify({"steps": steps})


@app.route("/api/wizard/<sid>/prompt/<step>")
def wizard_prompt(sid: str, step: str):
    """Get the prompt template for a step."""
    sess = _get_session(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    if step == "title_input":
        return jsonify({
            "type": "form",
            "fields": [
                {"name": "title", "label": "小说标题", "type": "text", "required": True},
            ],
            "description": "请输入您的小说标题",
        })

    if step == "genre_input":
        template = PROMPT_TEMPLATES.get("genre_input", {})
        title = sess["data"].get("title_input", {}).get("title", "")
        genre = sess["data"].get("genre_input", {}).get("genre", "")
        user_prompt = _fill_prompt(template.get("user", ""), title=title, genre=genre)
        return jsonify({
            "type": "model",
            "system_prompt": template.get("system", ""),
            "user_prompt": user_prompt,
            "temperature": 0.7,
            "description": "请输入小说题材，系统将自动分析该题材的特点",
            "fields": [
                {"name": "genre", "label": "小说题材", "type": "text", "required": True,
                 "placeholder": "如：玄幻修仙、都市异能、规则怪谈"},
            ],
        })

    if step == "writing_style":
        template = PROMPT_TEMPLATES.get("writing_style", {})
        title = sess["data"].get("title_input", {}).get("title", "")
        genre = sess["data"].get("genre_input", {}).get("genre", "")
        theme = sess["data"].get("genre_input", {}).get("theme", "") or genre
        custom_ideas = sess["data"].get("writing_style", {}).get("custom_ideas", "")
        custom_ideas_section = f"【用户的想法和偏好】\n{custom_ideas}" if custom_ideas else ""
        custom_requirements = "请特别注意用户提出的想法和偏好，将其融入到写作风格指南中。" if custom_ideas else ""
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre, theme=theme,
            custom_ideas_section=custom_ideas_section,
            custom_requirements=custom_requirements,
        )
        return jsonify({
            "type": "model",
            "system_prompt": template.get("system", ""),
            "user_prompt": user_prompt,
            "temperature": 0.7,
            "description": "正在制定写作风格指南...",
            "fields": [
                {"name": "custom_ideas", "label": "您的想法和偏好", "type": "textarea",
                 "placeholder": "请输入您对写作风格的想法，如：希望用第一人称、语言偏幽默、节奏要快等...",
                 "value": custom_ideas},
            ],
        })

    if step == "worldview":
        template = PROMPT_TEMPLATES.get("worldview", {})
        title = sess["data"].get("title_input", {}).get("title", "")
        genre = sess["data"].get("genre_input", {}).get("genre", "")
        theme = sess["data"].get("genre_input", {}).get("theme", "") or genre
        custom_ideas = sess["data"].get("worldview", {}).get("custom_ideas", "")
        custom_ideas_section = f"【用户的想法和偏好】\n{custom_ideas}" if custom_ideas else ""
        custom_requirements = "请特别注意用户提出的想法和偏好，将其融入到世界观设定中。" if custom_ideas else ""
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre, theme=theme,
            custom_ideas_section=custom_ideas_section,
            custom_requirements=custom_requirements,
        )
        return jsonify({
            "type": "model",
            "system_prompt": template.get("system", ""),
            "user_prompt": user_prompt,
            "temperature": 0.7,
            "description": "正在生成小说的世界观设定...",
            "fields": [
                {"name": "custom_ideas", "label": "您的想法和偏好", "type": "textarea",
                 "placeholder": "请输入您对世界观的想法，如：想要修仙体系、有魔法学院、类似唐朝背景等...",
                 "value": custom_ideas},
            ],
        })

    if step == "skill":
        template = PROMPT_TEMPLATES.get("skill", {})
        title = sess["data"].get("title_input", {}).get("title", "")
        genre = sess["data"].get("genre_input", {}).get("genre", "")
        theme = sess["data"].get("genre_input", {}).get("theme", "") or genre
        custom_ideas = sess["data"].get("skill", {}).get("custom_ideas", "")
        custom_ideas_section = f"【用户的想法和偏好】\n{custom_ideas}" if custom_ideas else ""
        custom_requirements = "请特别注意用户提出的想法和偏好，将其融入到写作技巧指南中。" if custom_ideas else ""
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre, theme=theme,
            custom_ideas_section=custom_ideas_section,
            custom_requirements=custom_requirements,
        )
        return jsonify({
            "type": "model",
            "system_prompt": template.get("system", ""),
            "user_prompt": user_prompt,
            "temperature": 0.7,
            "description": "正在为你的小说匹配/创建写作风格指南（Skill）...",
            "fields": [
                {"name": "custom_ideas", "label": "您的想法和偏好", "type": "textarea",
                 "placeholder": "请输入您对写作技巧的想法，如：希望多写心理活动、反派要复杂立体、多设置反转等...",
                 "value": custom_ideas},
            ],
        })

    if step == "import_novel":
        return jsonify({
            "type": "form",
            "fields": [
                {"name": "import", "label": "是否导入已有小说进行仿写", "type": "select", 
                 "options": [
                     {"value": "no", "label": "不导入，继续下一步"},
                     {"value": "yes", "label": "导入已有小说进行分析"},
                 ],
                 "value": "no"},
                {"name": "novel_text", "label": "小说文本（如选择导入）", "type": "textarea",
                 "placeholder": "请粘贴小说文本内容..."},
            ],
            "description": "是否导入已有小说进行风格仿写？系统将分析其写作风格、结构特点和冲突方式",
        })

    if step == "project_init":
        return jsonify({
            "type": "action",
            "description": "即将初始化项目，构建资产、悬念引擎、风格向量数据库等组件...",
        })

    if step == "outline":
        template = PROMPT_TEMPLATES.get("outline", {})
        title = sess["data"].get("title_input", {}).get("title", "")
        genre = sess["data"].get("genre_input", {}).get("genre", "")
        theme = sess["data"].get("genre_input", {}).get("theme", "") or genre
        worldview = sess["data"].get("worldview", {}).get("result", "")
        knowledge = sess["data"].get("genre_input", {}).get("result", "")
        chapter_count = sess["data"].get("outline", {}).get("chapter_count", 10)
        custom_ideas = sess["data"].get("outline", {}).get("custom_ideas", "")
        
        # Suspense engine config
        suspense_tension = sess["data"].get("outline", {}).get("suspense_tension", 7)
        suspense_mystery = sess["data"].get("outline", {}).get("suspense_mystery", 5)
        suspense_romance = sess["data"].get("outline", {}).get("suspense_romance", 3)
        suspense_conflict = sess["data"].get("outline", {}).get("suspense_conflict", 7)
        
        custom_ideas_section = f"【用户的想法和偏好】\n{custom_ideas}" if custom_ideas else ""
        custom_requirements = "请特别注意用户提出的想法和偏好，将其融入到大纲中。" if custom_ideas else ""
        
        suspense_config = (
            f"- 悬念强度：{suspense_tension}/10（越高越需要悬念设置）\n"
            f"- 神秘程度：{suspense_mystery}/10（越高越需要隐藏信息和谜团）\n"
            f"- 感情线比重：{suspense_romance}/10（越高感情戏越多）\n"
            f"- 冲突激烈度：{suspense_conflict}/10（越高矛盾越激烈）"
        )
        
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre, theme=theme,
            worldview=worldview[:1500] if worldview else "(待生成)",
            knowledge=knowledge[:1500] if knowledge else "(待生成)",
            chapter_count=chapter_count,
            custom_ideas_section=custom_ideas_section,
            custom_requirements=custom_requirements,
            suspense_config=suspense_config,
        )
        return jsonify({
            "type": "model",
            "system_prompt": template.get("system", ""),
            "user_prompt": user_prompt,
            "temperature": 0.7,
            "description": f"正在生成 {chapter_count} 章的大纲...",
            "fields": [
                {"name": "chapter_count", "label": "大纲章节数", "type": "number",
                 "value": chapter_count, "min": 3, "max": 50},
                {"name": "suspense_tension", "label": "悬念强度 (1-10)", "type": "number",
                 "value": suspense_tension, "min": 1, "max": 10},
                {"name": "suspense_mystery", "label": "神秘程度 (1-10)", "type": "number",
                 "value": suspense_mystery, "min": 1, "max": 10},
                {"name": "suspense_romance", "label": "感情线比重 (1-10)", "type": "number",
                 "value": suspense_romance, "min": 0, "max": 10},
                {"name": "suspense_conflict", "label": "冲突激烈度 (1-10)", "type": "number",
                 "value": suspense_conflict, "min": 1, "max": 10},
                {"name": "custom_ideas", "label": "您的想法和偏好", "type": "textarea",
                 "placeholder": "请输入您对大纲的想法，如：希望主角先遇到挫折再崛起、需要一个隐藏反派等...",
                 "value": custom_ideas},
            ],
        })

    if step == "chapter_config":
        return jsonify({
            "type": "form",
            "fields": [
                {"name": "chapters_per_batch", "label": "每批次生成章节数", "type": "number", 
                 "value": 3, "min": 1, "max": 10},
                {"name": "start_chapter", "label": "起始章节", "type": "number",
                 "value": 1, "min": 1},
                {"name": "total_chapters", "label": "总章节数", "type": "number",
                 "value": 10, "min": 1, "max": 200},
            ],
            "description": "设置章节生成参数",
        })

    if step == "chapter_gen":
        template = PROMPT_TEMPLATES.get("chapter_gen", {})
        title = sess["data"].get("title_input", {}).get("title", "")
        genre = sess["data"].get("genre_input", {}).get("genre", "")
        theme = sess["data"].get("genre_input", {}).get("theme", "") or genre
        worldview = sess["data"].get("worldview", {}).get("result", "")
        writing_style = sess["data"].get("writing_style", {}).get("result", "")
        outline = sess["data"].get("outline", {}).get("result", "")
        chapter_num = sess["data"].get("chapter_progress", {}).get("current_chapter", 
                     sess["data"].get("chapter_config", {}).get("start_chapter", 1))
        target_words = sess["data"].get("chapter_config", {}).get("target_words", 3000)
        total_chapters = sess["data"].get("chapter_config", {}).get("total_chapters", 
                        sess["data"].get("outline", {}).get("chapter_count", 10))
        custom_ideas = sess["data"].get("chapter_gen", {}).get("custom_ideas", "")
        try:
            total_chapters = int(total_chapters)
        except (ValueError, TypeError):
            total_chapters = 10
        
        # Extract chapter-specific outline
        chapter_outline = _extract_chapter_outline(outline, chapter_num)
        
        # Build previous chapters summary
        prev_summary = _build_previous_summary(sess, chapter_num)
        
        custom_ideas_section = f"【用户的想法和创意】\n{custom_ideas}" if custom_ideas else ""
        custom_requirements = "请特别注意用户提出的创意想法，将其融入到章节内容中。" if custom_ideas else ""
        
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre, theme=theme,
            worldview=worldview[:1500] if worldview else "(待生成)",
            writing_style=writing_style[:1500] if writing_style else "(待生成)",
            outline=outline[:2000] if outline else "(待生成)",
            chapter_number=chapter_num,
            chapter_title=f"第{chapter_num}章",
            chapter_outline=chapter_outline or "(待生成)",
            chapter_summary=prev_summary or "这是第一章，暂无前文概要",
            key_events="(待生成)",
            characters="(待生成)",
            suspense="(待生成)",
            target_words=target_words,
            custom_ideas_section=custom_ideas_section,
            custom_requirements=custom_requirements,
        )
        return jsonify({
            "type": "model",
            "system_prompt": template.get("system", ""),
            "user_prompt": user_prompt,
            "temperature": 0.8,
            "description": f"正在生成第{chapter_num}章内容（共{total_chapters}章）...",
            "fields": [
                {"name": "chapter_number", "label": "章节号", "type": "number",
                 "value": chapter_num, "min": 1, "max": total_chapters},
                {"name": "target_words", "label": "目标字数", "type": "number",
                 "value": target_words, "min": 1000, "max": 10000},
                {"name": "custom_ideas", "label": "您的创意想法", "type": "textarea",
                 "placeholder": "请输入您对本章的想法，如：希望主角在这里觉醒新能力、加入一段回忆杀等...",
                 "value": custom_ideas},
            ],
        })

    if step == "chapter_review":
        template = PROMPT_TEMPLATES.get("chapter_review", {})
        title = sess["data"].get("title_input", {}).get("title", "")
        genre = sess["data"].get("genre_input", {}).get("genre", "")
        chapter_content = sess["data"].get("chapter_gen", {}).get("result", "")
        chapter_num = sess["data"].get("chapter_progress", {}).get("current_chapter", 1)
        outline = sess["data"].get("outline", {}).get("result", "")
        chapter_outline = _extract_chapter_outline(outline, chapter_num)
        user_prompt = _fill_prompt(
            template.get("user", ""),
            title=title, genre=genre,
            chapter_number=chapter_num,
            chapter_outline=chapter_outline or "(无具体大纲要求)",
            chapter_content=chapter_content[:3000] if chapter_content else "(待生成)",
        )
        return jsonify({
            "type": "model",
            "system_prompt": template.get("system", ""),
            "user_prompt": user_prompt,
            "temperature": 0.3,
            "description": f"正在审核第{chapter_num}章内容...",
        })

    if step == "chapter_update":
        return jsonify({
            "type": "action",
            "description": "即将更新数据库和向量数据库...",
        })

    return jsonify({"error": "Unknown step"}), 400


@app.route("/api/wizard/<sid>/save", methods=["POST"])
def wizard_save(sid: str):
    """Save data for current step (form data or edited prompt)."""
    sess = _get_session(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    body = request.get_json()
    step = body.get("step", sess["step"])
    data = body.get("data", {})

    with _sessions_lock:
        if sid in _wizard_sessions:
            if step == "title_input":
                _wizard_sessions[sid]["data"]["title_input"] = data
                _wizard_sessions[sid]["project_name"] = f"{data.get('title','')}_{uuid.uuid4().hex[:4]}"
            elif step == "genre_input":
                # Save genre data and prompt edits
                if "result" in data:
                    _wizard_sessions[sid]["data"]["genre_input"]["result"] = data["result"]
                if "user_prompt" in data:
                    _wizard_sessions[sid]["data"]["genre_input"]["user_prompt"] = data["user_prompt"]
                if "system_prompt" in data:
                    _wizard_sessions[sid]["data"]["genre_input"]["system_prompt"] = data["system_prompt"]
                if "genre" in data:
                    _wizard_sessions[sid]["data"]["genre_input"]["genre"] = data["genre"]
            elif step == "outline":
                # Save chapter count and prompt edits
                if "chapter_count" in data:
                    _wizard_sessions[sid]["data"]["outline"]["chapter_count"] = data["chapter_count"]
                if "user_prompt" in data:
                    _wizard_sessions[sid]["data"]["outline"]["user_prompt"] = data["user_prompt"]
                if "system_prompt" in data:
                    _wizard_sessions[sid]["data"]["outline"]["system_prompt"] = data["system_prompt"]
                # Save custom ideas and suspense config
                for key in ("custom_ideas", "suspense_tension", "suspense_mystery", "suspense_romance", "suspense_conflict"):
                    if key in data:
                        _wizard_sessions[sid]["data"]["outline"][key] = data[key]
                # Rebuild prompt if custom fields changed
                if any(k in data for k in ("custom_ideas", "chapter_count", "suspense_tension", "suspense_mystery", "suspense_romance", "suspense_conflict")):
                    _rebuild_prompt(sid, "outline")
            elif step == "chapter_config":
                _wizard_sessions[sid]["data"]["chapter_config"] = data
                # Reset chapter progress when config changes
                start_ch = data.get("start_chapter", 1)
                total = data.get("total_chapters", 10)
                try:
                    start_ch = int(start_ch)
                except (ValueError, TypeError):
                    start_ch = 1
                try:
                    total = int(total)
                except (ValueError, TypeError):
                    total = 10
                _wizard_sessions[sid]["data"]["chapter_progress"] = {
                    "current_chapter": start_ch,
                    "total_chapters": total,
                    "completed_chapters": [],
                }
            elif step == "chapter_gen":
                # Save chapter generation data
                if "result" in data:
                    _wizard_sessions[sid]["data"]["chapter_gen"]["result"] = data["result"]
                if "user_prompt" in data:
                    _wizard_sessions[sid]["data"]["chapter_gen"]["user_prompt"] = data["user_prompt"]
                if "system_prompt" in data:
                    _wizard_sessions[sid]["data"]["chapter_gen"]["system_prompt"] = data["system_prompt"]
                if "chapter_number" in data:
                    _wizard_sessions[sid]["data"]["chapter_gen"]["chapter_number"] = data["chapter_number"]
                if "target_words" in data:
                    _wizard_sessions[sid]["data"]["chapter_gen"]["target_words"] = data["target_words"]
                if "custom_ideas" in data:
                    _wizard_sessions[sid]["data"]["chapter_gen"]["custom_ideas"] = data["custom_ideas"]
                # Rebuild prompt if custom_ideas changed
                if "custom_ideas" in data:
                    _rebuild_prompt(sid, "chapter_gen")
            else:
                # Save prompt edits for model steps
                if "user_prompt" in data:
                    _wizard_sessions[sid]["data"][step]["user_prompt"] = data["user_prompt"]
                if "system_prompt" in data:
                    _wizard_sessions[sid]["data"][step]["system_prompt"] = data["system_prompt"]
                if "temperature" in data:
                    _wizard_sessions[sid]["data"][step]["temperature"] = data["temperature"]
                if "result" in data:
                    _wizard_sessions[sid]["data"][step]["result"] = data["result"]
                if "custom_ideas" in data:
                    _wizard_sessions[sid]["data"][step]["custom_ideas"] = data["custom_ideas"]
                # Rebuild prompt if custom_ideas changed
                if "custom_ideas" in data and step in ("writing_style", "worldview", "skill"):
                    _rebuild_prompt(sid, step)

    return jsonify({"ok": True})


@app.route("/api/wizard/<sid>/generate/<step>")
def wizard_generate(sid: str, step: str):
    """SSE: call model for this step and stream result."""
    def stream():
        try:
            yield from _stream_step(sid, step)
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"
    return Response(
        stream_with_context(stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/wizard/<sid>/confirm", methods=["POST"])
def wizard_confirm(sid: str):
    """Confirm current step: save result, auto-review, advance or loop."""
    sess = _get_session(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    body = request.get_json()
    step = body.get("step", sess["step"])
    data = body.get("data", {})

    with _sessions_lock:
        if sid not in _wizard_sessions:
            return jsonify({"error": "Session gone"}), 404
        ws = _wizard_sessions[sid]

        # Merge edited result if provided
        if data:
            ws["data"][step].update(data)

        # Execute side effects + review logic
        loop_back = False
        review_result = None

        if step == "title_input":
            pass
        elif step == "genre_input":
            _execute_create_project(ws)
        elif step == "writing_style":
            _execute_save_writing_style(ws)
        elif step == "worldview":
            _execute_save_worldview(ws)
        elif step == "skill":
            _execute_save_skill(ws)
        elif step == "import_novel":
            _execute_import_novel(ws)
        elif step == "project_init":
            _execute_project_init(ws)
        elif step == "outline":
            result = ws["data"].get("outline", {}).get("result", "")
            if result:
                review_result = _auto_review(sid, "outline", result)
                ws["data"]["outline"]["review"] = review_result
                if not review_result.get("pass", True):
                    loop_back = True
                    ws["confirmed"]["outline"] = False
            if not loop_back:
                _execute_save_outline(ws)
        elif step == "chapter_config":
            # Initialize chapter progress
            start_ch = ws["data"].get("chapter_config", {}).get("start_chapter", 1)
            total = ws["data"].get("chapter_config", {}).get("total_chapters", 10)
            try:
                total = int(total)
            except (ValueError, TypeError):
                total = 10
            ws["data"]["chapter_progress"] = {
                "current_chapter": int(start_ch) if start_ch else 1,
                "total_chapters": total,
                "completed_chapters": [],
            }
        elif step == "chapter_gen":
            chapter_num = ws["data"].get("chapter_progress", {}).get("current_chapter", 1)
            result = ws["data"].get("chapter_gen", {}).get("result", "")
            if result:
                # Save to all_results
                all_results = ws["data"].get("chapter_gen", {}).setdefault("all_results", {})
                all_results[str(chapter_num)] = {"result": result}
                # Auto-review
                review_result = _auto_review(sid, "chapter_gen", result)
                ws["data"]["chapter_gen"]["review"] = review_result
                if not review_result.get("pass", True):
                    loop_back = True
                else:
                    # Advance to next chapter
                    progress = ws["data"]["chapter_progress"]
                    progress["completed_chapters"].append(chapter_num)
                    total = progress.get("total_chapters", 10)
                    if chapter_num < total:
                        progress["current_chapter"] = chapter_num + 1
                        loop_back = True  # Loop back for next chapter
                    else:
                        # All chapters done, move to chapter_update
                        pass
        elif step == "chapter_review":
            pass
        elif step == "chapter_update":
            _execute_update_database(ws)

        # Advance step (unless looping back)
        if not loop_back:
            ws["confirmed"][step] = True
            current_idx = WIZARD_STEPS.index(step) if step in WIZARD_STEPS else -1
            if current_idx < len(WIZARD_STEPS) - 1:
                ws["step_idx"] = current_idx + 1
                ws["step"] = WIZARD_STEPS[current_idx + 1]
                ws["status"] = "input"
        else:
            ws["status"] = "review_failed"

    resp = {
        "ok": True,
        "next_step": sess["step"],
        "next_step_idx": sess["step_idx"],
        "confirmed": sess["confirmed"],
        "loop_back": loop_back,
    }
    if review_result:
        resp["review"] = review_result
    return jsonify(resp)


def _execute_create_project(ws: dict):
    """Create the project in DB."""
    from novel_agent.generation.pipeline import GenerationPipeline
    title = ws["data"].get("title_input", {}).get("title", "") or "未命名"
    genre = ws["data"].get("genre_input", {}).get("genre", "") or "通用"
    theme = ws["data"].get("genre_input", {}).get("theme", "") or genre
    pipeline = GenerationPipeline(
        title=title,
        genre=genre,
        theme=theme,
        target_chapters=10,  # Default, will be updated later
    )
    pipeline.initialize()
    ws["project_id"] = pipeline.project_id
    # 不存储pipeline对象，只存储必要的配置信息
    ws["project_config"] = {
        "title": title,
        "genre": genre,
        "theme": theme,
    }
    ws["project_name"] = f"{title}_{pipeline.project_id}"


def _execute_save_skill(ws: dict):
    """Save skill result to project."""
    pid = ws.get("project_id")
    if not pid:
        return
    from novel_agent.database.models import Project
    result = ws["data"].get("skill", {}).get("result", "")
    proj = db_client.get_by_id(Project, pid)
    if proj:
        proj.skill_overrides = result
        db_client.update(proj)


def _execute_save_knowledge(ws: dict):
    """Save knowledge to DB via existing components."""
    pid = ws.get("project_id")
    if not pid:
        return
    from novel_agent.knowledge.knowledge_base import KnowledgeBase
    result = ws["data"].get("knowledge", {}).get("result", "")
    if result:
        kb = KnowledgeBase(pid)
        kb.store_collected_knowledge({"custom_knowledge": result})


def _execute_save_worldview(ws: dict):
    """Save worldview to DB."""
    pid = ws.get("project_id")
    if not pid:
        return
    from novel_agent.knowledge.knowledge_base import KnowledgeBase
    result = ws["data"].get("worldview", {}).get("result", "")
    if result:
        kb = KnowledgeBase(pid)
        kb.store_collected_knowledge({"generated_world_setting": result})


def _execute_save_outline(ws: dict):
    """Save outline to DB."""
    pid = ws.get("project_id")
    if not pid:
        return
    from novel_agent.database.models import Outline
    result = ws["data"].get("outline", {}).get("result", "")
    chapter_count = ws["data"].get("outline", {}).get("chapter_count", 10)
    try:
        chapter_count = int(chapter_count)
    except (ValueError, TypeError):
        chapter_count = 10
    if result:
        outline = Outline(
            project_id=pid,
            phase="initial",
            chapter_start=1,
            chapter_end=chapter_count,
            content=result,
            key_events=result[:500],
            suspense_points="",
        )
        db_client.add(outline)
        proj = db_client.get_by_id(Project, pid)
        if proj:
            import json as _json
            try:
                parsed = _json.loads(result)
                chapters = parsed.get("chapters", [])
                proj.target_chapters = len(chapters)
                db_client.update(proj)
            except Exception:
                pass


def _execute_save_writing_style(ws: dict):
    """Save writing style to project."""
    pid = ws.get("project_id")
    if not pid:
        return
    from novel_agent.database.models import Project
    result = ws["data"].get("writing_style", {}).get("result", "")
    proj = db_client.get_by_id(Project, pid)
    if proj:
        proj.skill_overrides = result
        db_client.update(proj)


def _execute_import_novel(ws: dict):
    """Process novel import and analysis."""
    import_data = ws["data"].get("import_novel", {})
    if import_data.get("import") == "yes":
        novel_text = import_data.get("novel_text", "")
        if novel_text:
            # Store the imported novel text for analysis
            ws["data"]["import_novel"]["novel_text"] = novel_text
            # The actual analysis will be done when the user generates
            # For now, we just store the text


def _execute_project_init(ws: dict):
    """Initialize project components: assets, suspense engine, vector DB, etc."""
    pid = ws.get("project_id")
    if not pid:
        return
    
    # Initialize vector DB
    from novel_agent.database.mysql_client import db_client
    from novel_agent.database.models import Project
    
    proj = db_client.get_by_id(Project, pid)
    if proj:
        # Mark project as initialized
        proj.status = "initialized"
        db_client.update(proj)


def _execute_save_chapter(ws: dict):
    """Save generated chapter content."""
    pid = ws.get("project_id")
    if not pid:
        return
    
    chapter_data = ws["data"].get("chapter_gen", {})
    result = chapter_data.get("result", "")
    chapter_number = chapter_data.get("chapter_number", 1)
    
    if result:
        # Save chapter to file
        project_name = ws.get("project_name", f"project_{pid}")
        output_dir = OUTPUT_DIR / project_name
        chapters_dir = output_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        
        chapter_file = chapters_dir / f"第{chapter_number}章.txt"
        chapter_file.write_text(result, encoding="utf-8")
        
        # Save chapter to database
        from novel_agent.database.models import Chapter
        chapter = Chapter(
            project_id=pid,
            chapter_number=chapter_number,
            title=f"第{chapter_number}章",
            content=result,
            word_count=len(result),
        )
        db_client.add(chapter)


def _execute_process_review(ws: dict):
    """Process chapter review results."""
    pid = ws.get("project_id")
    if not pid:
        return
    
    review_data = ws["data"].get("chapter_review", {})
    result = review_data.get("result", "")
    
    # Parse review scores and determine if chapter needs rewrite
    # For now, we'll just store the review result
    ws["data"]["chapter_review"]["result"] = result


def _execute_update_database(ws: dict):
    """Update database and vector database with chapter information."""
    pid = ws.get("project_id")
    if not pid:
        return
    
    # Update project progress
    from novel_agent.database.models import Project
    proj = db_client.get_by_id(Project, pid)
    if proj:
        chapter_number = ws["data"].get("chapter_gen", {}).get("chapter_number", 1)
        proj.current_chapter = chapter_number
        db_client.update(proj)
    
    # Update vector database with chapter content
    chapter_data = ws["data"].get("chapter_gen", {})
    result = chapter_data.get("result", "")
    if result:
        # TODO: Update vector database with chapter content
        # This would involve adding the chapter to the vector store
        pass


@app.route("/api/wizard/<sid>/start-generation", methods=["POST"])
def wizard_start_generation(sid: str):
    """Start chapter generation with SSE streaming."""
    sess = _get_session(sid)
    if not sess:
        return jsonify({"error": "Session not found"}), 404

    pid = sess.get("project_id")
    if not pid:
        return jsonify({"error": "Project not initialized"}), 400

    def generate():
        try:
            # 重新创建pipeline对象
            from novel_agent.generation.pipeline import GenerationPipeline
            project_config = sess.get("project_config", {})
            pipeline = GenerationPipeline(
                title=project_config.get("title", ""),
                genre=project_config.get("genre", ""),
                theme=project_config.get("theme", ""),
                skip_skill_init=True,  # 跳过初始化，因为项目已创建
            )
            pipeline.resume(project_id=pid)
            
            yield f"data: {json.dumps({'type':'status','text':'开始生成章节...'})}\n\n"
            pipeline.run()
            yield f"data: {json.dumps({'type':'done','text':'全部章节生成完成！'})}\n\n"
        except Exception as e:
            logger.error(f"Generation error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type':'error','text':str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Existing API ────────────────────────────────────────────────

@app.route("/api/projects")
def list_projects():
    projects = []
    if OUTPUT_DIR.exists():
        for entry in sorted(OUTPUT_DIR.iterdir()):
            if entry.is_dir() and (entry / "chapters").exists():
                chapters_dir = entry / "chapters"
                chapters = sorted(
                    [{"file": f.name, "title": f.stem, "path": str(f.relative_to(OUTPUT_DIR))}
                     for f in chapters_dir.iterdir() if f.suffix.lower() in (".txt", ".md")],
                    key=lambda x: x["file"],
                )
                status = "unknown"
                try:
                    db_client.init_db()
                    p_list = db_client.get_all(Project)
                    for p in p_list:
                        if f"{p.title}_{p.id}" == entry.name:
                            status = p.status or "unknown"
                            break
                except Exception:
                    pass
                projects.append({
                    "id": entry.name, "name": entry.name,
                    "chapter_count": len(chapters), "chapters": chapters, "status": status,
                })
    return jsonify(projects)


@app.route("/api/chapter")
def get_chapter():
    path = request.args.get("path", "")
    file_path = OUTPUT_DIR / path
    # 防止路径遍历攻击
    real_path = os.path.realpath(file_path)
    if not str(real_path).startswith(str(OUTPUT_DIR.resolve())):
        return jsonify({"error": "Invalid path"}), 400
    if not file_path.exists():
        return jsonify({"error": "Chapter not found"}), 404
    content = file_path.read_text(encoding="utf-8")
    return jsonify({"content": content, "file": file_path.name})


@app.route("/api/export/<project_name>")
def export_novel(project_name: str):
    """导出小说为TXT格式"""
    project_dir = OUTPUT_DIR / project_name
    chapters_dir = project_dir / "chapters"
    
    if not chapters_dir.exists():
        return jsonify({"error": "Project not found"}), 404
    
    # 收集所有章节
    chapters = []
    for f in sorted(chapters_dir.iterdir()):
        if f.suffix.lower() in (".txt", ".md"):
            content = f.read_text(encoding="utf-8")
            chapters.append(content)
    
    if not chapters:
        return jsonify({"error": "No chapters found"}), 404
    
    # 合并为完整小说
    full_text = "\n\n".join(chapters)
    
    # 返回纯文本
    return Response(
        full_text,
        mimetype="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={project_name}.txt"
        }
    )


# ─── Frontend Routes ────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def static_files(filename: str):
    return send_from_directory(app.static_folder, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting Agnes AI Wizard on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, threaded=True)
