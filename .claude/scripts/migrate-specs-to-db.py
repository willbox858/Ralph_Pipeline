#!/usr/bin/env python3
"""
Ralph Spec Migration Script

Imports existing file-based specs from Specs/Active/ into the Ralph database.
Handles nested specs (parent/children/child/spec.json structure).

Usage:
    python migrate-specs-to-db.py [--dry-run] [--clear]

Options:
    --dry-run   Preview what would be imported without writing to DB
    --clear     Wipe database before importing (requires confirmation)

Example:
    python .claude/scripts/migrate-specs-to-db.py --dry-run
    python .claude/scripts/migrate-specs-to-db.py --clear
"""

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from ralph_db import RalphDB, get_default_db_path


# =============================================================================
# DIRECT DATABASE ACCESS (bypasses RalphDB to avoid locking issues)
# =============================================================================

class MigrationDB:
    """Direct database access for migration to avoid nested connection issues."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None

    def connect(self):
        """Open persistent connection for migration."""
        self.conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def close(self):
        """Close connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def _init_schema(self):
        """Ensure schema exists."""
        self.conn.executescript("""
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

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_id TEXT REFERENCES specs(id),
                type TEXT NOT NULL,
                data JSON,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_events_spec ON events(spec_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
        """)
        self.conn.commit()

    def create_spec(self, name: str, parent_id: Optional[str], data: dict,
                    is_leaf: Optional[bool], depth: int, status: str) -> str:
        """Create a spec directly."""
        spec_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()

        self.conn.execute("""
            INSERT INTO specs (id, name, parent_id, status, is_leaf, depth, data, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (spec_id, name, parent_id, status, is_leaf, depth, json.dumps(data), now, now))

        return spec_id

    def log_event(self, spec_id: str, event_type: str, data: dict):
        """Log an event directly."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("""
            INSERT INTO events (spec_id, type, data, created_at)
            VALUES (?, ?, ?, ?)
        """, (spec_id, event_type, json.dumps(data), now))

    def commit(self):
        """Commit transaction."""
        self.conn.commit()

    def clear_all(self):
        """Clear all data."""
        self.conn.execute("DELETE FROM events")
        self.conn.execute("DELETE FROM specs")
        self.conn.commit()


# =============================================================================
# DISCOVERY
# =============================================================================

def find_all_specs(base_dir: Path) -> list[Path]:
    """Find all spec.json files under the base directory."""
    specs = []

    # Use rglob for cross-platform recursive search
    for spec_path in base_dir.rglob("spec.json"):
        specs.append(spec_path)

    return sorted(specs)


def determine_depth(spec_path: Path, base_dir: Path) -> int:
    """Determine spec depth based on directory structure.

    Depth 0: Specs/Active/feature/spec.json
    Depth 1: Specs/Active/feature/children/child/spec.json
    Depth 2: Specs/Active/feature/children/child/children/grandchild/spec.json
    """
    try:
        rel_path = spec_path.parent.relative_to(base_dir)
        parts = rel_path.parts

        # Count "children" directories in path
        depth = 0
        for part in parts:
            if part == "children":
                depth += 1

        return depth
    except ValueError:
        return 0


def find_parent_spec(spec_path: Path, base_dir: Path) -> Optional[Path]:
    """Find the parent spec's path based on directory hierarchy.

    For Specs/Active/feature/children/child/spec.json,
    parent is Specs/Active/feature/spec.json
    """
    try:
        rel_path = spec_path.parent.relative_to(base_dir)
        parts = list(rel_path.parts)

        # Walk up to find parent
        # Looking for pattern: .../children/childname -> parent is .../
        if "children" in parts:
            # Find last occurrence of "children"
            for i in range(len(parts) - 1, -1, -1):
                if parts[i] == "children":
                    # Parent is everything before "children"
                    parent_parts = parts[:i]
                    if parent_parts:
                        parent_dir = base_dir.joinpath(*parent_parts)
                        parent_spec = parent_dir / "spec.json"
                        if parent_spec.exists():
                            return parent_spec
                    break

        return None
    except ValueError:
        return None


def get_spec_name_from_path(spec_path: Path) -> str:
    """Extract spec name from directory name."""
    return spec_path.parent.name


# =============================================================================
# SPEC LOADING
# =============================================================================

def load_spec_data(spec_path: Path) -> Optional[dict]:
    """Load spec JSON data, returning None if invalid."""
    try:
        content = spec_path.read_text(encoding='utf-8')
        data = json.loads(content)
        return data
    except (json.JSONDecodeError, UnicodeDecodeError, IOError) as e:
        print(f"  WARNING: Failed to load {spec_path}: {e}")
        return None


def extract_spec_fields(data: dict, spec_path: Path, depth: int) -> dict:
    """Extract key fields from spec data for database storage."""
    # Get name from spec or directory
    name = data.get("name", get_spec_name_from_path(spec_path))

    # Get status
    status = data.get("status", "draft")

    # Get is_leaf from structure
    structure = data.get("structure", {})
    is_leaf = structure.get("is_leaf")  # May be None, True, or False

    # Runtime depth can override calculated depth
    runtime = data.get("runtime", {})
    spec_depth = runtime.get("depth", depth)

    return {
        "name": name,
        "status": status,
        "is_leaf": is_leaf,
        "depth": spec_depth,
        "data": data  # Store full spec content
    }


# =============================================================================
# RELATED FILE LOADING
# =============================================================================

def load_related_files(spec_path: Path) -> list[dict]:
    """Load related files as events (research.json, verification.json, decisions.jsonl)."""
    events = []
    spec_dir = spec_path.parent

    # research.json -> "research" event
    research_path = spec_dir / "research.json"
    if research_path.exists():
        try:
            data = json.loads(research_path.read_text(encoding='utf-8'))
            events.append({
                "type": "research",
                "data": data,
                "source": str(research_path)
            })
        except (json.JSONDecodeError, IOError) as e:
            print(f"  WARNING: Failed to load {research_path}: {e}")

    # verification.json -> "verification" event
    verification_path = spec_dir / "verification.json"
    if verification_path.exists():
        try:
            data = json.loads(verification_path.read_text(encoding='utf-8'))
            events.append({
                "type": "verification",
                "data": data,
                "source": str(verification_path)
            })
        except (json.JSONDecodeError, IOError) as e:
            print(f"  WARNING: Failed to load {verification_path}: {e}")

    # decisions.jsonl -> multiple "decision" events
    decisions_path = spec_dir / "decisions.jsonl"
    if decisions_path.exists():
        try:
            content = decisions_path.read_text(encoding='utf-8')
            for line_num, line in enumerate(content.strip().split('\n'), 1):
                if line.strip():
                    try:
                        data = json.loads(line)
                        events.append({
                            "type": "decision",
                            "data": data,
                            "source": f"{decisions_path}:{line_num}"
                        })
                    except json.JSONDecodeError as e:
                        print(f"  WARNING: Failed to parse line {line_num} in {decisions_path}: {e}")
        except IOError as e:
            print(f"  WARNING: Failed to load {decisions_path}: {e}")

    return events


# =============================================================================
# MIGRATION
# =============================================================================

def migrate_specs(base_dir: Path, db: MigrationDB, dry_run: bool = False) -> dict:
    """Migrate all specs from base_dir to database.

    Returns summary statistics.
    """
    stats = {
        "total_found": 0,
        "imported": 0,
        "skipped": 0,
        "events_imported": 0,
        "errors": []
    }

    # Find all specs
    spec_paths = find_all_specs(base_dir)
    stats["total_found"] = len(spec_paths)

    if not spec_paths:
        print(f"No spec.json files found in {base_dir}")
        return stats

    print(f"\nFound {len(spec_paths)} spec(s) to import\n")

    # Build path -> id mapping for parent resolution
    path_to_id: dict[Path, str] = {}

    # Sort by depth to ensure parents are created before children
    spec_paths_with_depth = [
        (spec_path, determine_depth(spec_path, base_dir))
        for spec_path in spec_paths
    ]
    spec_paths_with_depth.sort(key=lambda x: x[1])

    for spec_path, depth in spec_paths_with_depth:
        print(f"{'  ' * depth}Processing: {spec_path.parent.name}")

        # Load spec data
        data = load_spec_data(spec_path)
        if data is None:
            stats["skipped"] += 1
            stats["errors"].append(f"Failed to load: {spec_path}")
            continue

        # Extract fields
        fields = extract_spec_fields(data, spec_path, depth)

        # Resolve parent
        parent_path = find_parent_spec(spec_path, base_dir)
        parent_id = path_to_id.get(parent_path) if parent_path else None

        if dry_run:
            print(f"{'  ' * depth}  -> Would import: {fields['name']} (status={fields['status']}, "
                  f"is_leaf={fields['is_leaf']}, depth={fields['depth']}, "
                  f"parent={'found' if parent_id else 'none'})")
            stats["imported"] += 1

            # Check for related files
            events = load_related_files(spec_path)
            if events:
                print(f"{'  ' * depth}     + {len(events)} event(s): {[e['type'] for e in events]}")
                stats["events_imported"] += len(events)

            # Generate fake ID for parent resolution
            path_to_id[spec_path] = f"dry-run-{len(path_to_id)}"
        else:
            try:
                # Create spec in database
                spec_id = db.create_spec(
                    name=fields["name"],
                    parent_id=parent_id,
                    data=fields["data"],
                    is_leaf=fields["is_leaf"],
                    depth=fields["depth"],
                    status=fields["status"]
                )

                path_to_id[spec_path] = spec_id
                stats["imported"] += 1

                print(f"{'  ' * depth}  -> Imported: {fields['name']} (id={spec_id})")

                # Import related files as events
                events = load_related_files(spec_path)
                for event in events:
                    db.log_event(spec_id, event["type"], event["data"])
                    stats["events_imported"] += 1

                if events:
                    print(f"{'  ' * depth}     + {len(events)} event(s)")

            except Exception as e:
                stats["skipped"] += 1
                stats["errors"].append(f"Failed to import {spec_path}: {e}")
                print(f"{'  ' * depth}  -> ERROR: {e}")

    return stats


def clear_database(db: MigrationDB, dry_run: bool = False) -> bool:
    """Clear all data from the database."""
    if dry_run:
        print("Would clear database (dry-run)")
        return True

    # Get confirmation
    print("\nWARNING: This will delete ALL specs and events from the database.")
    confirm = input("Type 'yes' to confirm: ")
    if confirm.lower() != 'yes':
        print("Aborted.")
        return False

    db.clear_all()
    print("Database cleared.\n")
    return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Migrate file-based specs to Ralph database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be imported without writing to DB"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Wipe database before importing (requires confirmation)"
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source directory (default: Specs/Active)"
    )

    args = parser.parse_args()

    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent  # .claude/scripts -> project root

    # Determine source directory
    if args.source:
        base_dir = Path(args.source)
        if not base_dir.is_absolute():
            base_dir = project_root / base_dir
    else:
        base_dir = project_root / "Specs" / "Active"

    if not base_dir.exists():
        print(f"Source directory not found: {base_dir}")
        print("No specs to migrate.")
        sys.exit(0)

    db_path = get_default_db_path()

    print("=" * 60)
    print("RALPH SPEC MIGRATION")
    print("=" * 60)
    print(f"Source: {base_dir}")
    print(f"Database: {db_path}")
    if args.dry_run:
        print("Mode: DRY RUN (no changes will be made)")
    print("=" * 60)

    # Initialize database (unless dry-run)
    db = None
    if not args.dry_run:
        db = MigrationDB(db_path)
        db.connect()

    try:
        # Clear if requested
        if args.clear:
            if db:
                if not clear_database(db, args.dry_run):
                    sys.exit(1)
            else:
                print("Would clear database (dry-run)")

        # Run migration
        stats = migrate_specs(base_dir, db, args.dry_run)

        # Commit all changes
        if db:
            db.commit()

    finally:
        if db:
            db.close()

    # Print summary
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"Total specs found:    {stats['total_found']}")
    print(f"Specs imported:       {stats['imported']}")
    print(f"Specs skipped:        {stats['skipped']}")
    print(f"Events imported:      {stats['events_imported']}")

    if stats['errors']:
        print(f"\nErrors ({len(stats['errors'])}):")
        for error in stats['errors']:
            print(f"  - {error}")

    if args.dry_run:
        print("\n(Dry run - no changes were made)")

    print("=" * 60)

    # Exit with error code if there were failures
    if stats['skipped'] > 0:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
