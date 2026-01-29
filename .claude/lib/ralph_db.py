"""
Ralph Database Module

Central data layer for the Ralph pipeline. Uses SQLite for:
- Spec storage and state management
- Inter-agent messaging
- Event logging and audit trail
- Agent run tracking

All components (orchestrator, MCP servers, hooks) import this module
to access the shared database.

Usage:
    from ralph_db import RalphDB

    db = RalphDB()  # Uses default path, creates if missing

    # Specs
    spec_id = db.create_spec("my-feature", parent_id=None, data={...})
    spec = db.get_spec(spec_id)
    db.update_spec_status(spec_id, "in_progress")

    # Messages
    msg_id = db.send_message(from_spec="parent", to_spec="child", type="decision", payload={...})
    messages = db.get_pending_messages("child")
    db.mark_message_delivered(msg_id)

    # Events
    db.log_event(spec_id, "verification", {"verdict": "pass", ...})
    events = db.get_events(spec_id, type="verification")
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_default_db_path() -> Path:
    """Get the default database path."""
    # Look for project root (contains .claude/)
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".claude").is_dir():
            return parent / ".ralph" / "ralph.db"

    # Fallback to cwd
    return cwd / ".ralph" / "ralph.db"


# =============================================================================
# DATA TYPES
# =============================================================================

class SpecStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class MessageStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    PROCESSED = "processed"


class MessagePriority(str, Enum):
    NORMAL = "normal"
    HIGH = "high"
    BLOCKING = "blocking"


@dataclass
class Spec:
    id: str
    name: str
    parent_id: Optional[str]
    status: str
    is_leaf: Optional[bool]
    depth: int
    data: dict
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: str
    from_spec: str
    to_spec: str
    type: str
    payload: dict
    priority: str
    status: str
    created_at: str
    delivered_at: Optional[str] = None
    response: Optional[dict] = None


@dataclass
class Event:
    id: int
    spec_id: str
    type: str
    data: dict
    created_at: str


@dataclass
class AgentRun:
    id: int
    spec_id: str
    agent_type: str
    status: str
    iteration: int
    started_at: str
    completed_at: Optional[str] = None
    result: Optional[dict] = None


# =============================================================================
# DATABASE CLASS
# =============================================================================

class RalphDB:
    """
    Central database for Ralph pipeline state.

    Thread-safe for SQLite (uses connection per operation).
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self):
        """Get a database connection with proper cleanup."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")  # Better concurrency
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Initialize database schema."""
        with self._connection() as conn:
            conn.executescript("""
                -- Specs table
                CREATE TABLE IF NOT EXISTS specs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    parent_id TEXT REFERENCES specs(id),
                    status TEXT DEFAULT 'draft',
                    is_leaf BOOLEAN,
                    depth INTEGER DEFAULT 0,
                    data JSON,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_specs_status ON specs(status);
                CREATE INDEX IF NOT EXISTS idx_specs_parent ON specs(parent_id);
                CREATE INDEX IF NOT EXISTS idx_specs_name ON specs(name);

                -- Messages table (inter-agent communication)
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    from_spec TEXT NOT NULL,
                    to_spec TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload JSON,
                    priority TEXT DEFAULT 'normal',
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now')),
                    delivered_at TEXT,
                    response JSON
                );

                CREATE INDEX IF NOT EXISTS idx_messages_to_spec ON messages(to_spec, status);
                CREATE INDEX IF NOT EXISTS idx_messages_from_spec ON messages(from_spec);

                -- Events table (audit log)
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spec_id TEXT REFERENCES specs(id),
                    type TEXT NOT NULL,
                    data JSON,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_events_spec ON events(spec_id);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

                -- Agent runs table
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spec_id TEXT REFERENCES specs(id),
                    agent_type TEXT NOT NULL,
                    status TEXT DEFAULT 'running',
                    iteration INTEGER DEFAULT 1,
                    started_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT,
                    result JSON
                );

                CREATE INDEX IF NOT EXISTS idx_agent_runs_spec ON agent_runs(spec_id);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status);
            """)

    # =========================================================================
    # SPEC OPERATIONS
    # =========================================================================

    def create_spec(
        self,
        name: str,
        parent_id: Optional[str] = None,
        data: Optional[dict] = None,
        is_leaf: Optional[bool] = None,
        depth: int = 0
    ) -> str:
        """Create a new spec and return its ID."""
        spec_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        with self._connection() as conn:
            conn.execute("""
                INSERT INTO specs (id, name, parent_id, status, is_leaf, depth, data, created_at, updated_at)
                VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?)
            """, (spec_id, name, parent_id, is_leaf, depth, json.dumps(data or {}), now, now))

        self.log_event(spec_id, "spec_created", {"name": name, "parent_id": parent_id})
        return spec_id

    def get_spec(self, spec_id: str) -> Optional[Spec]:
        """Get a spec by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM specs WHERE id = ?", (spec_id,)
            ).fetchone()

            if row:
                return Spec(
                    id=row["id"],
                    name=row["name"],
                    parent_id=row["parent_id"],
                    status=row["status"],
                    is_leaf=row["is_leaf"],
                    depth=row["depth"],
                    data=json.loads(row["data"]) if row["data"] else {},
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
        return None

    def get_spec_by_name(self, name: str) -> Optional[Spec]:
        """Get a spec by name."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM specs WHERE name = ?", (name,)
            ).fetchone()

            if row:
                return Spec(
                    id=row["id"],
                    name=row["name"],
                    parent_id=row["parent_id"],
                    status=row["status"],
                    is_leaf=row["is_leaf"],
                    depth=row["depth"],
                    data=json.loads(row["data"]) if row["data"] else {},
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
        return None

    def update_spec(
        self,
        spec_id: str,
        status: Optional[str] = None,
        is_leaf: Optional[bool] = None,
        data: Optional[dict] = None
    ) -> bool:
        """Update spec fields. Returns True if updated."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if is_leaf is not None:
            updates.append("is_leaf = ?")
            params.append(is_leaf)
        if data is not None:
            updates.append("data = ?")
            params.append(json.dumps(data))

        if not updates:
            return False

        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(spec_id)

        updated = False
        with self._connection() as conn:
            result = conn.execute(
                f"UPDATE specs SET {', '.join(updates)} WHERE id = ?",
                params
            )
            updated = result.rowcount > 0

        # Log event outside connection context to avoid nested connections
        if updated:
            self.log_event(spec_id, "spec_updated", {
                "status": status,
                "is_leaf": is_leaf,
                "data_updated": data is not None
            })
        return updated

    def update_spec_status(self, spec_id: str, status: str) -> bool:
        """Update just the spec status."""
        return self.update_spec(spec_id, status=status)

    def update_spec_data(self, spec_id: str, data: dict) -> bool:
        """Update just the spec data."""
        return self.update_spec(spec_id, data=data)

    def list_specs(
        self,
        status: Optional[str] = None,
        parent_id: Optional[str] = None,
        is_leaf: Optional[bool] = None
    ) -> list[Spec]:
        """List specs with optional filters."""
        query = "SELECT * FROM specs WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if parent_id is not None:
            if parent_id == "":
                query += " AND parent_id IS NULL"
            else:
                query += " AND parent_id = ?"
                params.append(parent_id)
        if is_leaf is not None:
            query += " AND is_leaf = ?"
            params.append(is_leaf)

        query += " ORDER BY depth, name"

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                Spec(
                    id=row["id"],
                    name=row["name"],
                    parent_id=row["parent_id"],
                    status=row["status"],
                    is_leaf=row["is_leaf"],
                    depth=row["depth"],
                    data=json.loads(row["data"]) if row["data"] else {},
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]

    def get_children(self, spec_id: str) -> list[Spec]:
        """Get child specs of a parent."""
        return self.list_specs(parent_id=spec_id)

    def delete_spec(self, spec_id: str) -> bool:
        """Delete a spec and its children."""
        with self._connection() as conn:
            # Delete children first
            conn.execute("DELETE FROM specs WHERE parent_id = ?", (spec_id,))
            result = conn.execute("DELETE FROM specs WHERE id = ?", (spec_id,))
            return result.rowcount > 0

    # =========================================================================
    # MESSAGE OPERATIONS
    # =========================================================================

    def send_message(
        self,
        from_spec: str,
        to_spec: str,
        type: str,
        payload: dict,
        priority: str = "normal"
    ) -> str:
        """Send a message from one spec to another. Returns message ID."""
        msg_id = str(uuid.uuid4())[:8]

        with self._connection() as conn:
            conn.execute("""
                INSERT INTO messages (id, from_spec, to_spec, type, payload, priority, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """, (msg_id, from_spec, to_spec, type, json.dumps(payload), priority,
                  datetime.now(timezone.utc).isoformat()))

        self.log_event(from_spec, "message_sent", {
            "message_id": msg_id,
            "to": to_spec,
            "type": type,
            "priority": priority
        })

        return msg_id

    def get_pending_messages(self, spec_id: str) -> list[Message]:
        """Get pending messages for a spec (for delivery via hooks)."""
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT * FROM messages
                WHERE to_spec = ? AND status = 'pending'
                ORDER BY
                    CASE priority
                        WHEN 'blocking' THEN 1
                        WHEN 'high' THEN 2
                        ELSE 3
                    END,
                    created_at
            """, (spec_id,)).fetchall()

            return [
                Message(
                    id=row["id"],
                    from_spec=row["from_spec"],
                    to_spec=row["to_spec"],
                    type=row["type"],
                    payload=json.loads(row["payload"]) if row["payload"] else {},
                    priority=row["priority"],
                    status=row["status"],
                    created_at=row["created_at"],
                    delivered_at=row["delivered_at"],
                    response=json.loads(row["response"]) if row["response"] else None
                )
                for row in rows
            ]

    def mark_message_delivered(self, message_id: str) -> bool:
        """Mark a message as delivered."""
        with self._connection() as conn:
            result = conn.execute("""
                UPDATE messages
                SET status = 'delivered', delivered_at = ?
                WHERE id = ? AND status = 'pending'
            """, (datetime.now(timezone.utc).isoformat(), message_id))
            return result.rowcount > 0

    def mark_message_processed(self, message_id: str, response: Optional[dict] = None) -> bool:
        """Mark a message as processed with optional response."""
        with self._connection() as conn:
            result = conn.execute("""
                UPDATE messages
                SET status = 'processed', response = ?
                WHERE id = ?
            """, (json.dumps(response) if response else None, message_id))
            return result.rowcount > 0

    def get_message(self, message_id: str) -> Optional[Message]:
        """Get a specific message by ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()

            if row:
                return Message(
                    id=row["id"],
                    from_spec=row["from_spec"],
                    to_spec=row["to_spec"],
                    type=row["type"],
                    payload=json.loads(row["payload"]) if row["payload"] else {},
                    priority=row["priority"],
                    status=row["status"],
                    created_at=row["created_at"],
                    delivered_at=row["delivered_at"],
                    response=json.loads(row["response"]) if row["response"] else None
                )
        return None

    # =========================================================================
    # EVENT LOGGING
    # =========================================================================

    def log_event(self, spec_id: str, type: str, data: dict) -> int:
        """Log an event. Returns event ID."""
        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT INTO events (spec_id, type, data, created_at)
                VALUES (?, ?, ?, ?)
            """, (spec_id, type, json.dumps(data), datetime.now(timezone.utc).isoformat()))
            return cursor.lastrowid

    def get_events(
        self,
        spec_id: Optional[str] = None,
        type: Optional[str] = None,
        limit: int = 100
    ) -> list[Event]:
        """Get events with optional filters."""
        query = "SELECT * FROM events WHERE 1=1"
        params = []

        if spec_id:
            query += " AND spec_id = ?"
            params.append(spec_id)
        if type:
            query += " AND type = ?"
            params.append(type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                Event(
                    id=row["id"],
                    spec_id=row["spec_id"],
                    type=row["type"],
                    data=json.loads(row["data"]) if row["data"] else {},
                    created_at=row["created_at"]
                )
                for row in rows
            ]

    # =========================================================================
    # AGENT RUN TRACKING
    # =========================================================================

    def start_agent_run(self, spec_id: str, agent_type: str, iteration: int = 1) -> int:
        """Record an agent run starting. Returns run ID."""
        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT INTO agent_runs (spec_id, agent_type, status, iteration, started_at)
                VALUES (?, ?, 'running', ?, ?)
            """, (spec_id, agent_type, iteration, datetime.now(timezone.utc).isoformat()))
            return cursor.lastrowid

    def complete_agent_run(self, run_id: int, status: str, result: Optional[dict] = None) -> bool:
        """Record an agent run completing."""
        with self._connection() as conn:
            res = conn.execute("""
                UPDATE agent_runs
                SET status = ?, completed_at = ?, result = ?
                WHERE id = ?
            """, (status, datetime.now(timezone.utc).isoformat(),
                  json.dumps(result) if result else None, run_id))
            return res.rowcount > 0

    def get_agent_runs(self, spec_id: str) -> list[AgentRun]:
        """Get agent runs for a spec."""
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT * FROM agent_runs WHERE spec_id = ?
                ORDER BY started_at DESC
            """, (spec_id,)).fetchall()

            return [
                AgentRun(
                    id=row["id"],
                    spec_id=row["spec_id"],
                    agent_type=row["agent_type"],
                    status=row["status"],
                    iteration=row["iteration"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    result=json.loads(row["result"]) if row["result"] else None
                )
                for row in rows
            ]

    # =========================================================================
    # SUMMARY / STATUS
    # =========================================================================

    def get_pipeline_summary(self) -> dict:
        """Get overall pipeline status summary."""
        with self._connection() as conn:
            # Count by status
            status_counts = {}
            for row in conn.execute(
                "SELECT status, COUNT(*) as count FROM specs GROUP BY status"
            ).fetchall():
                status_counts[row["status"]] = row["count"]

            # Count pending messages
            pending_messages = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE status = 'pending'"
            ).fetchone()[0]

            # Count running agents
            running_agents = conn.execute(
                "SELECT COUNT(*) FROM agent_runs WHERE status = 'running'"
            ).fetchone()[0]

            # Recent events
            recent_events = conn.execute("""
                SELECT type, COUNT(*) as count
                FROM events
                WHERE created_at > datetime('now', '-1 hour')
                GROUP BY type
            """).fetchall()

            return {
                "total_specs": sum(status_counts.values()),
                "by_status": status_counts,
                "pending_messages": pending_messages,
                "running_agents": running_agents,
                "recent_events": {row["type"]: row["count"] for row in recent_events},
                "needs_review": status_counts.get("blocked", 0) + status_counts.get("failed", 0)
            }

    def get_spec_tree(self, root_id: Optional[str] = None) -> list[dict]:
        """Get spec hierarchy as a tree structure."""
        specs = self.list_specs(parent_id=root_id if root_id else "")

        def build_tree(parent_id: Optional[str]) -> list[dict]:
            children = [s for s in self.list_specs() if s.parent_id == parent_id]
            return [
                {
                    "id": s.id,
                    "name": s.name,
                    "status": s.status,
                    "is_leaf": s.is_leaf,
                    "children": build_tree(s.id)
                }
                for s in children
            ]

        if root_id:
            root = self.get_spec(root_id)
            if root:
                return [{
                    "id": root.id,
                    "name": root.name,
                    "status": root.status,
                    "is_leaf": root.is_leaf,
                    "children": build_tree(root.id)
                }]

        return build_tree(None)


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

import threading

_db_instance: Optional[RalphDB] = None
_db_lock = threading.Lock()


def get_db(db_path: Optional[Path] = None) -> RalphDB:
    """Get the singleton database instance (thread-safe)."""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            # Double-check locking pattern
            if _db_instance is None:
                _db_instance = RalphDB(db_path)
    return _db_instance


def reset_db():
    """Reset the singleton (for testing)."""
    global _db_instance
    _db_instance = None
