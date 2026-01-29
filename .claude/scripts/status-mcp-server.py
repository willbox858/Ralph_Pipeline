#!/usr/bin/env python3
"""
Ralph Status MCP Server

A standalone MCP server that provides status information about Ralph pipelines.
User-facing Claude connects to this server to check pipeline status, list specs,
and view items needing review.

This server uses the ralph_db module to read from the SQLite database at
.ralph/ralph.db - it doesn't require the orchestrator to be running.

Usage:
    python status-mcp-server.py

Configure in Claude Code settings to auto-start this server.
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import asdict

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from ralph_db import get_db, Spec, Message, Event


def spec_to_dict(spec: Spec) -> dict:
    """Convert a Spec dataclass to a dictionary for JSON serialization."""
    return {
        "id": spec.id,
        "name": spec.name,
        "parent_id": spec.parent_id,
        "status": spec.status,
        "is_leaf": spec.is_leaf,
        "depth": spec.depth,
        "data": spec.data,
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }


def message_to_dict(msg: Message) -> dict:
    """Convert a Message dataclass to a dictionary for JSON serialization."""
    return {
        "id": msg.id,
        "from_spec": msg.from_spec,
        "to_spec": msg.to_spec,
        "type": msg.type,
        "payload": msg.payload,
        "priority": msg.priority,
        "status": msg.status,
        "created_at": msg.created_at,
        "delivered_at": msg.delivered_at,
        "response": msg.response,
    }


def event_to_dict(event: Event) -> dict:
    """Convert an Event dataclass to a dictionary for JSON serialization."""
    return {
        "id": event.id,
        "spec_id": event.spec_id,
        "type": event.type,
        "data": event.data,
        "created_at": event.created_at,
    }


def collect_specs(status_filter: Optional[str] = None) -> list[dict]:
    """Collect all specs from the database."""
    db = get_db()
    specs = db.list_specs(status=status_filter)
    return [spec_to_dict(s) for s in specs]


def get_spec_details(spec_id: Optional[str] = None, spec_name: Optional[str] = None) -> dict:
    """Get detailed information about a specific spec."""
    db = get_db()

    # Find spec by ID or name
    spec = None
    if spec_id:
        spec = db.get_spec(spec_id)
    elif spec_name:
        spec = db.get_spec_by_name(spec_name)

    if not spec:
        return {"error": f"Spec not found: {spec_id or spec_name}"}

    # Get related data
    children = db.get_children(spec.id)
    events = db.get_events(spec_id=spec.id, limit=50)
    agent_runs = db.get_agent_runs(spec.id)

    return {
        "spec": spec_to_dict(spec),
        "children": [{"id": c.id, "name": c.name, "status": c.status} for c in children],
        "recent_events": [event_to_dict(e) for e in events[:10]],
        "agent_runs": [
            {
                "id": r.id,
                "agent_type": r.agent_type,
                "status": r.status,
                "iteration": r.iteration,
                "started_at": r.started_at,
                "completed_at": r.completed_at,
            }
            for r in agent_runs
        ],
    }


def get_review_queue() -> list[dict]:
    """Get specs that need human review."""
    db = get_db()

    review_items = []

    # Get blocked specs
    blocked = db.list_specs(status="blocked")
    for spec in blocked:
        review_items.append({
            "spec_id": spec.id,
            "spec_name": spec.name,
            "status": "blocked",
            "reason": "Spec is blocked and needs human intervention",
            "updated_at": spec.updated_at,
        })

    # Get failed specs
    failed = db.list_specs(status="failed")
    for spec in failed:
        review_items.append({
            "spec_id": spec.id,
            "spec_name": spec.name,
            "status": "failed",
            "reason": "Spec implementation failed",
            "updated_at": spec.updated_at,
        })

    return review_items


def get_pipeline_summary() -> dict:
    """Get a summary of all pipeline activity."""
    db = get_db()
    return db.get_pipeline_summary()


def get_pending_messages(spec_id: str) -> list[dict]:
    """Get pending messages for a spec."""
    db = get_db()
    messages = db.get_pending_messages(spec_id)
    return [message_to_dict(m) for m in messages]


def get_events(spec_id: Optional[str] = None, event_type: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Get event history for a spec or all specs."""
    db = get_db()
    events = db.get_events(spec_id=spec_id, type=event_type, limit=limit)
    return [event_to_dict(e) for e in events]


def get_spec_tree(root_id: Optional[str] = None) -> list[dict]:
    """Get hierarchical spec tree."""
    db = get_db()
    return db.get_spec_tree(root_id)


def cleanup_stale_runs() -> dict:
    """Clean up stale/orphaned agent runs."""
    db = get_db()
    return db.cleanup_stale_runs()


# =============================================================================
# MCP SERVER
# =============================================================================

def create_status_server():
    """Create the MCP server with status tools."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent
    except ImportError:
        print("ERROR: pip install mcp", file=sys.stderr)
        sys.exit(1)

    server = Server("ralph-status")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="ralph_list_specs",
                description="List all specs in the Ralph pipeline",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status_filter": {
                            "type": "string",
                            "description": "Filter by status (draft, ready, in_progress, complete, failed, blocked)"
                        }
                    }
                }
            ),
            Tool(
                name="ralph_get_spec",
                description="Get detailed information about a specific spec including children, events, and agent runs",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spec_id": {
                            "type": "string",
                            "description": "ID of the spec"
                        },
                        "spec_name": {
                            "type": "string",
                            "description": "Name of the spec (will search for it)"
                        }
                    }
                }
            ),
            Tool(
                name="ralph_pipeline_summary",
                description="Get a summary of all pipeline activity including spec counts, pending messages, and running agents",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="ralph_review_queue",
                description="Get specs that need human review (blocked/failed)",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="ralph_get_messages",
                description="Get pending messages for a spec",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spec_id": {
                            "type": "string",
                            "description": "ID of the spec to get messages for"
                        }
                    },
                    "required": ["spec_id"]
                }
            ),
            Tool(
                name="ralph_get_events",
                description="Get event history for a spec or all specs",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spec_id": {
                            "type": "string",
                            "description": "ID of the spec (optional, omit for all specs)"
                        },
                        "event_type": {
                            "type": "string",
                            "description": "Filter by event type (e.g., spec_created, spec_updated, message_sent)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of events to return (default: 50)"
                        }
                    }
                }
            ),
            Tool(
                name="ralph_spec_tree",
                description="Get hierarchical spec tree showing parent-child relationships",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "root_id": {
                            "type": "string",
                            "description": "ID of the root spec (optional, omit for full tree)"
                        }
                    }
                }
            ),
            Tool(
                name="ralph_cleanup_stale",
                description="Clean up stale/orphaned agent runs. Call this when no orchestrator is running to mark abandoned 'running' agent records as 'stale'.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        if name == "ralph_list_specs":
            status_filter = arguments.get("status_filter")
            specs = collect_specs(status_filter)
            return [TextContent(
                type="text",
                text=json.dumps(specs, indent=2)
            )]

        elif name == "ralph_get_spec":
            spec_id = arguments.get("spec_id")
            spec_name = arguments.get("spec_name")

            if not spec_id and not spec_name:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "Either spec_id or spec_name is required"})
                )]

            details = get_spec_details(spec_id=spec_id, spec_name=spec_name)
            return [TextContent(
                type="text",
                text=json.dumps(details, indent=2)
            )]

        elif name == "ralph_pipeline_summary":
            summary = get_pipeline_summary()
            return [TextContent(
                type="text",
                text=json.dumps(summary, indent=2)
            )]

        elif name == "ralph_review_queue":
            queue = get_review_queue()
            return [TextContent(
                type="text",
                text=json.dumps(queue, indent=2)
            )]

        elif name == "ralph_get_messages":
            spec_id = arguments.get("spec_id")
            if not spec_id:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "spec_id is required"})
                )]

            messages = get_pending_messages(spec_id)
            return [TextContent(
                type="text",
                text=json.dumps(messages, indent=2)
            )]

        elif name == "ralph_get_events":
            spec_id = arguments.get("spec_id")
            event_type = arguments.get("event_type")
            limit = arguments.get("limit", 50)

            events = get_events(spec_id=spec_id, event_type=event_type, limit=limit)
            return [TextContent(
                type="text",
                text=json.dumps(events, indent=2)
            )]

        elif name == "ralph_spec_tree":
            root_id = arguments.get("root_id")
            tree = get_spec_tree(root_id)
            return [TextContent(
                type="text",
                text=json.dumps(tree, indent=2)
            )]

        elif name == "ralph_cleanup_stale":
            result = cleanup_stale_runs()
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]

        else:
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"})
            )]

    return server


async def main():
    """Run the MCP server."""
    from mcp.server.stdio import stdio_server

    server = create_status_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
