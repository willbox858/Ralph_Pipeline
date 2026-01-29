"""
FileOwnershipTracker - Track file ownership in database to prevent conflicts.

Prevents multiple specs from modifying the same files concurrently.
Uses glob patterns for ownership claims.
"""

import fnmatch
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ClaimResult:
    """Result of a file claim operation."""
    success: bool
    patterns: Optional[list[str]] = None
    conflicts: Optional[list[dict]] = None
    message: str = ""


@dataclass
class OwnerInfo:
    """Information about a file's owner."""
    spec_path: str
    pattern: str
    claimed_at: str


class FileOwnershipTracker:
    """
    Tracks file ownership in database to prevent conflicts.

    Uses glob patterns (e.g., 'src/parser/*.py') for ownership claims.
    Multiple specs cannot claim overlapping file patterns simultaneously.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize FileOwnershipTracker.

        Args:
            db_path: Path to SQLite database. Defaults to .ralph/ralph.db
        """
        self.db_path = db_path or self._get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_default_db_path(self) -> Path:
        """Get the default database path."""
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / ".claude").is_dir():
                return parent / ".ralph" / "ralph.db"
        return cwd / ".ralph" / "ralph.db"

    @contextmanager
    def _connection(self):
        """Get a database connection with proper cleanup."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Initialize database schema for file ownership."""
        with self._connection() as conn:
            conn.executescript("""
                -- File ownership claims table
                CREATE TABLE IF NOT EXISTS file_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spec_path TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    claimed_at TEXT DEFAULT (datetime('now')),
                    released_at TEXT,
                    UNIQUE(spec_path, pattern)
                );

                CREATE INDEX IF NOT EXISTS idx_file_claims_spec ON file_claims(spec_path);
                CREATE INDEX IF NOT EXISTS idx_file_claims_status ON file_claims(status);
                CREATE INDEX IF NOT EXISTS idx_file_claims_pattern ON file_claims(pattern);
            """)

    def _patterns_overlap(self, pattern1: str, pattern2: str) -> bool:
        """
        Check if two glob patterns could match the same file.

        This is a conservative check - it may return True for patterns
        that don't actually overlap, but it won't return False when they do.

        Args:
            pattern1: First glob pattern
            pattern2: Second glob pattern

        Returns:
            True if patterns might overlap
        """
        # Normalize patterns to use forward slashes
        p1 = pattern1.replace('\\', '/')
        p2 = pattern2.replace('\\', '/')

        # If one pattern matches the other's literal form, they overlap
        if fnmatch.fnmatch(p1, p2) or fnmatch.fnmatch(p2, p1):
            return True

        # Check if patterns share a common prefix that could overlap
        # Split into directory parts
        parts1 = p1.split('/')
        parts2 = p2.split('/')

        # Check each part for potential overlap
        min_len = min(len(parts1), len(parts2))

        for i in range(min_len):
            part1 = parts1[i]
            part2 = parts2[i]

            # If either part is a wildcard that matches the other, continue checking
            if fnmatch.fnmatch(part1, part2) or fnmatch.fnmatch(part2, part1):
                continue

            # If parts are wildcards, they might overlap
            if '*' in part1 or '*' in part2 or '?' in part1 or '?' in part2:
                # Conservative: assume they could overlap
                continue

            # Literal parts that don't match = no overlap
            if part1 != part2:
                return False

        # If we get here, patterns might overlap
        return True

    def _file_matches_pattern(self, file_path: str, pattern: str) -> bool:
        """
        Check if a file path matches a glob pattern.

        Args:
            file_path: Path to check
            pattern: Glob pattern

        Returns:
            True if file matches pattern
        """
        # Normalize to forward slashes
        file_path = file_path.replace('\\', '/')
        pattern = pattern.replace('\\', '/')

        # Try direct match
        if fnmatch.fnmatch(file_path, pattern):
            return True

        # Handle ** patterns (match any number of directories)
        if '**' in pattern:
            # fnmatch doesn't handle ** well, use a simple recursive approach
            pattern_parts = pattern.split('**')
            if len(pattern_parts) == 2:
                prefix, suffix = pattern_parts
                prefix = prefix.rstrip('/')
                suffix = suffix.lstrip('/')

                # File must start with prefix (if any)
                if prefix and not file_path.startswith(prefix):
                    return False

                # File must end with a pattern that matches suffix
                if suffix:
                    # Get the part after prefix
                    remainder = file_path[len(prefix):].lstrip('/')
                    # Check if any suffix matches
                    return fnmatch.fnmatch(remainder, suffix) or fnmatch.fnmatch(
                        remainder.split('/')[-1], suffix.split('/')[-1]
                    )
                return True

        return False

    def claim_files(self, spec_path: str, file_patterns: list[str]) -> ClaimResult:
        """
        Register file ownership. Fails if already claimed by another active spec.

        Args:
            spec_path: Path to the spec claiming ownership
            file_patterns: List of glob patterns to claim (e.g., ['src/parser/*.py'])

        Returns:
            ClaimResult with success status and any conflicts
        """
        if not file_patterns:
            return ClaimResult(success=True, patterns=[], message="No patterns to claim")

        conflicts = []

        with self._connection() as conn:
            # Get all active claims from other specs
            existing = conn.execute("""
                SELECT spec_path, pattern
                FROM file_claims
                WHERE status = 'active' AND spec_path != ?
            """, (spec_path,)).fetchall()

            # Check for conflicts
            for pattern in file_patterns:
                for row in existing:
                    if self._patterns_overlap(pattern, row['pattern']):
                        conflicts.append({
                            'pattern': pattern,
                            'owner': row['spec_path'],
                            'owner_pattern': row['pattern']
                        })

            if conflicts:
                return ClaimResult(
                    success=False,
                    conflicts=conflicts,
                    message=f"Conflict with {len(conflicts)} existing claim(s)"
                )

            # Register claims (use INSERT OR REPLACE to handle reclaiming)
            now = datetime.now(timezone.utc).isoformat()
            for pattern in file_patterns:
                conn.execute("""
                    INSERT INTO file_claims (spec_path, pattern, status, claimed_at)
                    VALUES (?, ?, 'active', ?)
                    ON CONFLICT(spec_path, pattern) DO UPDATE SET
                        status = 'active',
                        claimed_at = excluded.claimed_at,
                        released_at = NULL
                """, (spec_path, pattern, now))

        return ClaimResult(
            success=True,
            patterns=file_patterns,
            message=f"Claimed {len(file_patterns)} pattern(s)"
        )

    def check_ownership(self, file_path: str) -> Optional[OwnerInfo]:
        """
        Check who owns a file.

        Args:
            file_path: Path to check

        Returns:
            OwnerInfo if claimed, None if unclaimed
        """
        with self._connection() as conn:
            # Get all active claims
            claims = conn.execute("""
                SELECT spec_path, pattern, claimed_at
                FROM file_claims
                WHERE status = 'active'
            """).fetchall()

            # Check each claim
            for row in claims:
                if self._file_matches_pattern(file_path, row['pattern']):
                    return OwnerInfo(
                        spec_path=row['spec_path'],
                        pattern=row['pattern'],
                        claimed_at=row['claimed_at']
                    )

        return None

    def release_files(self, spec_path: str) -> None:
        """
        Release all claims for spec on completion.

        Args:
            spec_path: Path to the spec releasing ownership
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._connection() as conn:
            conn.execute("""
                UPDATE file_claims
                SET status = 'released', released_at = ?
                WHERE spec_path = ? AND status = 'active'
            """, (now, spec_path))

    def get_claims(self, spec_path: str) -> list[str]:
        """
        Get all active patterns claimed by a spec.

        Args:
            spec_path: Path to the spec

        Returns:
            List of claimed patterns
        """
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT pattern FROM file_claims
                WHERE spec_path = ? AND status = 'active'
            """, (spec_path,)).fetchall()

            return [row['pattern'] for row in rows]

    def get_all_active_claims(self) -> list[dict]:
        """
        Get all active claims across all specs.

        Returns:
            List of dicts with spec_path, pattern, claimed_at
        """
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT spec_path, pattern, claimed_at
                FROM file_claims
                WHERE status = 'active'
                ORDER BY spec_path, pattern
            """).fetchall()

            return [
                {
                    'spec_path': row['spec_path'],
                    'pattern': row['pattern'],
                    'claimed_at': row['claimed_at']
                }
                for row in rows
            ]
