"""
MySQL 数据库客户端

负责数据库连接管理、会话管理和 CRUD 操作。
"""

import logging
from typing import Optional, List, Type, TypeVar
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine

from novel_agent.config import config
from novel_agent.database.models import Base

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Base)


class MySQLClient:
    """MySQL 数据库客户端，管理连接和 CRUD 操作"""

    def __init__(self):
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None

    @property
    def engine(self) -> Engine:
        """延迟初始化数据库引擎"""
        if self._engine is None:
            self._engine = create_engine(
                config.mysql.connection_url,
                pool_size=5,
                max_overflow=10,
                pool_recycle=3600,
                echo=False,
            )
            logger.info("数据库引擎已创建")
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        """延迟初始化会话工厂"""
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        return self._session_factory

    def init_db(self):
        """初始化数据库，创建所有表"""
        logger.info("正在初始化数据库表...")
        Base.metadata.create_all(self.engine)
        logger.info("数据库表初始化完成")

    def drop_all(self):
        """删除所有表（危险操作，仅用于开发环境）"""
        logger.warning("正在删除所有数据库表...")
        Base.metadata.drop_all(self.engine)
        logger.info("所有表已删除")

    @contextmanager
    def session(self):
        """
        上下文管理器，提供数据库会话

        Usage:
            with db_client.session() as session:
                session.add(obj)
        """
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            session.close()

    def add(self, obj: Base):
        """添加单个对象到数据库"""
        with self.session() as session:
            session.add(obj)
            session.flush()
            obj_id = obj.id
            return obj_id

    def add_all(self, objects: List[Base]):
        """批量添加对象到数据库"""
        with self.session() as session:
            session.add_all(objects)
            session.flush()

    def get_by_id(self, model_class: Type[T], obj_id: int) -> Optional[T]:
        """根据 ID 查询对象"""
        with self.session() as session:
            return session.query(model_class).filter_by(id=obj_id).first()

    def get_all(self, model_class: Type[T], **filters) -> List[T]:
        """查询所有匹配的对象"""
        with self.session() as session:
            query = session.query(model_class)
            if filters:
                query = query.filter_by(**filters)
            return query.all()

    def update(self, obj: Base):
        """更新对象"""
        with self.session() as session:
            session.merge(obj)

    def delete_by_id(self, model_class: Type[T], obj_id: int):
        """根据 ID 删除对象"""
        with self.session() as session:
            obj = session.query(model_class).filter_by(id=obj_id).first()
            if obj:
                session.delete(obj)

    def execute_raw(self, sql: str, params: dict = None):
        """执行原始 SQL 语句"""
        with self.session() as session:
            result = session.execute(text(sql), params or {})
            return result

    def test_connection(self) -> bool:
        """测试数据库连接"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("数据库连接测试成功")
            return True
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            return False


# 全局数据库客户端单例
db_client = MySQLClient()
