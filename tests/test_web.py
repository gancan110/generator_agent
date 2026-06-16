"""
Web模块全流程测试
测试Flask Web应用的所有API端点和核心功能
"""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from flask import Flask

# 设置测试环境
os.environ["MYSQL_HOST"] = "localhost"
os.environ["MYSQL_PORT"] = "3306"
os.environ["MYSQL_USER"] = "test_user"
os.environ["MYSQL_PASSWORD"] = "test_password"
os.environ["MYSQL_DATABASE"] = "test_novel"
os.environ["AGNES_API_KEY"] = "test_api_key"
os.environ["AGNES_BASE_URL"] = "https://test.api.com/v1"
os.environ["AGNES_MODEL"] = "test-model"
os.environ["VECTOR_DB_PATH"] = "./test_vector_db"
os.environ["LOG_DIR"] = "./test_logs"
os.environ["OUTPUT_DIR"] = "./test_output"


@pytest.fixture
def app():
    """创建测试应用"""
    from web.server import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    """创建测试客户端"""
    return app.test_client()


@pytest.fixture
def mock_llm():
    """模拟LLM客户端"""
    with patch("novel_agent.utils.llm_client.llm_client") as mock:
        mock.generate.return_value = "测试生成内容"
        mock.generate_stream.return_value = iter(["测试", "流式", "内容"])
        yield mock


@pytest.fixture
def mock_db():
    """模拟数据库客户端"""
    with patch("novel_agent.database.mysql_client.db_client") as mock:
        mock.init_db.return_value = None
        mock.add.return_value = 1
        mock.get_by_id.return_value = MagicMock(
            id=1,
            title="测试项目",
            status="initialized",
            current_chapter=1,
        )
        mock.update.return_value = None
        mock.get_all.return_value = []
        yield mock


class TestFrontendRoutes:
    """前端路由测试"""

    def test_index(self, client):
        """测试首页"""
        response = client.get("/")
        assert response.status_code == 200

    def test_static_files(self, client):
        """测试静态文件"""
        response = client.get("/app.js")
        assert response.status_code == 200

    def test_css(self, client):
        """测试CSS文件"""
        response = client.get("/style.css")
        assert response.status_code == 200


class TestWizardSession:
    """Wizard会话管理测试"""

    def test_create_session(self, client):
        """测试创建会话"""
        response = client.post("/api/wizard/create")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert "session_id" in data
        assert data["step"] == "title_input"
        assert data["step_idx"] == 0

    def test_get_session(self, client):
        """测试获取会话"""
        # 先创建会话
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        # 获取会话
        response = client.get(f"/api/wizard/{session_id}")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["session_id"] == session_id

    def test_get_nonexistent_session(self, client):
        """测试获取不存在的会话"""
        response = client.get("/api/wizard/nonexistent")
        assert response.status_code == 404

    def test_get_steps(self, client):
        """测试获取步骤列表"""
        # 先创建会话
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        # 获取步骤
        response = client.get(f"/api/wizard/{session_id}/steps")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert "steps" in data
        assert len(data["steps"]) == 12  # WIZARD_STEPS有12个步骤


class TestWizardPrompt:
    """Wizard Prompt模板测试"""

    def test_title_input_prompt(self, client):
        """测试标题输入prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/title_input")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "form"
        assert len(data["fields"]) == 1

    def test_genre_input_prompt(self, client, mock_db):
        """测试题材输入prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/genre_input")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "model"
        assert "fields" in data

    def test_writing_style_prompt(self, client, mock_db):
        """测试写作风格prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/writing_style")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "model"

    def test_worldview_prompt(self, client, mock_db):
        """测试世界观prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/worldview")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "model"

    def test_skill_prompt(self, client, mock_db):
        """测试技能prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/skill")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "model"

    def test_import_novel_prompt(self, client):
        """测试导入小说prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/import_novel")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "form"

    def test_project_init_prompt(self, client):
        """测试项目初始化prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/project_init")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "action"

    def test_outline_prompt(self, client, mock_db):
        """测试大纲prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/outline")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "model"
        assert "fields" in data

    def test_chapter_config_prompt(self, client):
        """测试章节配置prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/chapter_config")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "form"
        assert len(data["fields"]) == 3

    def test_chapter_gen_prompt(self, client, mock_db):
        """测试章节生成prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/chapter_gen")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "model"

    def test_chapter_review_prompt(self, client, mock_db):
        """测试章节审核prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/chapter_review")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "model"

    def test_chapter_update_prompt(self, client):
        """测试章节更新prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/chapter_update")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["type"] == "action"

    def test_unknown_step_prompt(self, client):
        """测试未知步骤prompt"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/prompt/unknown_step")
        assert response.status_code == 400


class TestWizardSave:
    """Wizard数据保存测试"""

    def test_save_title(self, client):
        """测试保存标题"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(
            f"/api/wizard/{session_id}/save",
            json={"step": "title_input", "data": {"title": "测试小说"}},
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["ok"] is True

    def test_save_genre(self, client):
        """测试保存题材"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(
            f"/api/wizard/{session_id}/save",
            json={"step": "genre_input", "data": {"genre": "玄幻修仙", "result": "题材分析结果"}},
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["ok"] is True

    def test_save_outline(self, client):
        """测试保存大纲"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(
            f"/api/wizard/{session_id}/save",
            json={
                "step": "outline",
                "data": {
                    "chapter_count": 20,
                    "result": "大纲内容",
                    "suspense_tension": 8,
                },
            },
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["ok"] is True

    def test_save_chapter_config(self, client):
        """测试保存章节配置"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(
            f"/api/wizard/{session_id}/save",
            json={
                "step": "chapter_config",
                "data": {
                    "chapters_per_batch": 5,
                    "start_chapter": 1,
                    "total_chapters": 50,
                },
            },
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["ok"] is True

    def test_save_chapter_gen(self, client):
        """测试保存章节生成数据"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(
            f"/api/wizard/{session_id}/save",
            json={
                "step": "chapter_gen",
                "data": {
                    "result": "章节内容",
                    "chapter_number": 1,
                    "target_words": 3000,
                },
            },
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["ok"] is True


class TestWizardConfirm:
    """Wizard确认步骤测试"""

    def test_confirm_title(self, client):
        """测试确认标题"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(
            f"/api/wizard/{session_id}/confirm",
            json={"step": "title_input", "data": {"title": "测试小说"}},
            content_type="application/json",
        )
        data = json.loads(response.data)
        assert response.status_code == 200
        assert data["ok"] is True
        assert data["confirmed"]["title_input"] is True

    def test_confirm_unknown_session(self, client):
        """测试确认不存在的会话"""
        response = client.post(
            "/api/wizard/nonexistent/confirm",
            json={"step": "title_input"},
            content_type="application/json",
        )
        assert response.status_code == 404


class TestOutlineData:
    """大纲数据API测试"""

    def test_get_outline_data(self, client):
        """测试获取大纲数据"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.get(f"/api/wizard/{session_id}/outline-data")
        data = json.loads(response.data)
        assert response.status_code == 200
        assert "outline" in data
        assert "current_chapter" in data
        assert "total_chapters" in data
        assert "completed_chapters" in data


class TestProjectAPI:
    """项目API测试"""

    def test_list_projects(self, client, mock_db):
        """测试列出项目"""
        response = client.get("/api/projects")
        assert response.status_code == 200

    def test_get_chapter_not_found(self, client):
        """测试获取不存在的章节"""
        response = client.get("/api/chapter?path=nonexistent.txt")
        assert response.status_code == 404

    def test_export_not_found(self, client):
        """测试导出不存在的项目"""
        response = client.get("/api/export/nonexistent_project")
        assert response.status_code == 404


class TestPathTraversal:
    """路径遍历安全测试"""

    def test_path_traversal_attack(self, client):
        """测试路径遍历攻击防护"""
        response = client.get("/api/chapter?path=../../../etc/passwd")
        # 应该返回400或404，而不是文件内容
        assert response.status_code in [400, 404]


class TestSessionCleanup:
    """会话清理测试"""

    def test_cleanup_expired_sessions(self, client):
        """测试过期会话清理"""
        from web.server import _wizard_sessions, _cleanup_expired_sessions, _sessions_lock, _last_cleanup
        from datetime import datetime, timedelta
        import time

        # 重置清理时间戳，确保清理会执行
        import web.server as server_module
        server_module._last_cleanup = 0  # 重置为0，确保下次调用会执行清理

        # 创建一个过期的会话
        expired_session = {
            "id": "expired1",
            "step_idx": 0,
            "step": "title_input",
            "status": "idle",
            "project_id": None,
            "project_name": "",
            "data": {},
            "confirmed": {},
            "created_at": (datetime.now() - timedelta(hours=2)).isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        with _sessions_lock:
            _wizard_sessions["expired1"] = expired_session

        # 执行清理
        _cleanup_expired_sessions()

        # 验证过期会话已被清理
        with _sessions_lock:
            assert "expired1" not in _wizard_sessions


class TestGenerateAPI:
    """生成API测试"""

    def test_generate_nonexistent_session(self, client):
        """测试生成不存在的会话"""
        response = client.get("/api/wizard/nonexistent/generate/outline")
        assert response.status_code == 200  # SSE响应返回200
        # 检查是否返回错误事件
        data = response.data.decode()
        assert "error" in data or "Session not found" in data


class TestStartGeneration:
    """开始生成测试"""

    def test_start_generation_no_project(self, client):
        """测试无项目时开始生成"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(f"/api/wizard/{session_id}/start-generation")
        assert response.status_code == 400


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_session_data(self, client):
        """测试空会话数据"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        # 获取当前步骤数据（应为空）
        response = client.get(f"/api/wizard/{session_id}")
        data = json.loads(response.data)
        assert response.status_code == 200

    def test_invalid_json_body(self, client):
        """测试无效JSON请求体"""
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        response = client.post(
            f"/api/wizard/{session_id}/save",
            data="not json",
            content_type="text/plain",
        )
        # 应该返回错误
        assert response.status_code in [400, 415, 500]


class TestIntegration:
    """集成测试"""

    def test_full_wizard_flow(self, client, mock_db, mock_llm):
        """测试完整Wizard流程"""
        # 1. 创建会话
        create_resp = client.post("/api/wizard/create")
        session_id = json.loads(create_resp.data)["session_id"]

        # 2. 保存标题
        save_resp = client.post(
            f"/api/wizard/{session_id}/save",
            json={"step": "title_input", "data": {"title": "测试小说"}},
            content_type="application/json",
        )
        assert json.loads(save_resp.data)["ok"] is True

        # 3. 确认标题
        confirm_resp = client.post(
            f"/api/wizard/{session_id}/confirm",
            json={"step": "title_input", "data": {"title": "测试小说"}},
            content_type="application/json",
        )
        confirm_data = json.loads(confirm_resp.data)
        assert confirm_data["ok"] is True
        assert confirm_data["confirmed"]["title_input"] is True

        # 4. 获取当前状态
        state_resp = client.get(f"/api/wizard/{session_id}")
        state_data = json.loads(state_resp.data)
        assert state_data["step"] == "genre_input"  # 应该前进到下一步

        # 5. 获取下一步prompt
        prompt_resp = client.get(f"/api/wizard/{session_id}/prompt/genre_input")
        prompt_data = json.loads(prompt_resp.data)
        assert prompt_data["type"] == "model"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
