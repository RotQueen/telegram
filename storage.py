"""Storage layer for project chat bindings."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
import sqlite3


@dataclass
class Project:
    slug: str
    customer_chat_id: Optional[int]
    executor_chat_id: Optional[int]
    is_active: bool


class ProjectRepository:
    def create_project(self, slug: str, executor_chat_id: int) -> Project:
        raise NotImplementedError

    def bind_customer_chat(self, slug: str, chat_id: int) -> Project:
        raise NotImplementedError

    def find_by_slug(self, slug: str) -> Optional[Project]:
        raise NotImplementedError

    def find_by_chat_id(self, chat_id: int) -> Optional[Tuple[Project, str]]:
        raise NotImplementedError

    def list_projects(self) -> List[Project]:
        raise NotImplementedError

    def unlink_chat(self, slug: str, chat_id: int) -> Project:
        raise NotImplementedError


class SQLiteProjectRepository(ProjectRepository):
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    slug TEXT PRIMARY KEY,
                    customer_chat_id INTEGER,
                    executor_chat_id INTEGER,
                    is_active INTEGER DEFAULT 1
                )
                """
            )
            conn.commit()

    def _row_to_project(self, row) -> Project:
        return Project(
            slug=row[0],
            customer_chat_id=row[1],
            executor_chat_id=row[2],
            is_active=bool(row[3]),
        )

    def create_project(self, slug: str, executor_chat_id: int) -> Project:
        with self._get_conn() as conn:
            cur = conn.execute("SELECT slug FROM projects WHERE slug = ?", (slug,))
            if cur.fetchone():
                raise ValueError("Project already exists")
            conn.execute(
                "INSERT INTO projects (slug, customer_chat_id, executor_chat_id, is_active) VALUES (?, NULL, ?, 1)",
                (slug, executor_chat_id),
            )
            conn.commit()
        return Project(slug=slug, customer_chat_id=None, executor_chat_id=executor_chat_id, is_active=True)

    def bind_customer_chat(self, slug: str, chat_id: int) -> Project:
        project = self.find_by_slug(slug)
        if not project:
            raise ValueError("Project not found")
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE projects SET customer_chat_id = ?, is_active = 1 WHERE slug = ?",
                (chat_id, slug),
            )
            conn.commit()
        project.customer_chat_id = chat_id
        project.is_active = True
        return project

    def find_by_slug(self, slug: str) -> Optional[Project]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT slug, customer_chat_id, executor_chat_id, is_active FROM projects WHERE slug = ?",
                (slug,),
            )
            row = cur.fetchone()
            return self._row_to_project(row) if row else None

    def find_by_chat_id(self, chat_id: int) -> Optional[Tuple[Project, str]]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT slug, customer_chat_id, executor_chat_id, is_active FROM projects WHERE customer_chat_id = ? OR executor_chat_id = ?",
                (chat_id, chat_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            project = self._row_to_project(row)
            role = "customer" if project.customer_chat_id == chat_id else "executor"
            return project, role

    def list_projects(self) -> List[Project]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT slug, customer_chat_id, executor_chat_id, is_active FROM projects ORDER BY slug"
            )
            return [self._row_to_project(row) for row in cur.fetchall()]

    def unlink_chat(self, slug: str, chat_id: int) -> Project:
        project = self.find_by_slug(slug)
        if not project:
            raise ValueError("Project not found")
        new_customer = project.customer_chat_id
        new_executor = project.executor_chat_id
        if chat_id == project.customer_chat_id:
            new_customer = None
        if chat_id == project.executor_chat_id:
            new_executor = None
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE projects SET customer_chat_id = ?, executor_chat_id = ?, is_active = 0 WHERE slug = ?",
                (new_customer, new_executor, slug),
            )
            conn.commit()
        project.customer_chat_id = new_customer
        project.executor_chat_id = new_executor
        project.is_active = False
        return project
