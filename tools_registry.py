import json

from calendar_tools import create_event, delete_event, list_events, update_event
from tasks_tools import create_task, delete_task, list_tasks, update_task

# Tools that require explicit user confirmation before execution
REQUIRE_CONFIRMATION = {"delete_event", "delete_task"}

# ── Tool schemas (OpenAI/DeepSeek function-calling format) ────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Create a Google Calendar event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary":     {"type": "string", "description": "Event title"},
                    "start":       {"type": "string", "description": "Start datetime, ISO 8601 with offset e.g. 2026-06-07T14:00:00-05:00"},
                    "end":         {"type": "string", "description": "End datetime, ISO 8601 with offset"},
                    "description": {"type": "string"},
                    "location":    {"type": "string"},
                    "timezone":    {"type": "string", "default": "UTC"},
                },
                "required": ["summary", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List upcoming Google Calendar events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "default": 10},
                    "time_min":    {"type": "string", "description": "ISO 8601 lower bound (default: now)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_event",
            "description": "Edit an existing Google Calendar event by its event_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id":    {"type": "string"},
                    "summary":     {"type": "string"},
                    "description": {"type": "string"},
                    "location":    {"type": "string"},
                    "start":       {"type": "string", "description": "ISO 8601 with offset"},
                    "end":         {"type": "string", "description": "ISO 8601 with offset"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_event",
            "description": "Permanently delete a Google Calendar event by its event_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a task in the task list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "notes": {"type": "string"},
                    "due":   {"type": "string", "description": "RFC 3339 datetime e.g. 2026-06-10T00:00:00Z"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List pending tasks. Set show_done=true to include completed tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "show_done": {"type": "boolean", "default": False},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task",
            "description": "Edit or mark a task as done by its doc_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer"},
                    "title":  {"type": "string"},
                    "notes":  {"type": "string"},
                    "due":    {"type": "string"},
                    "done":   {"type": "boolean"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Permanently delete a task by its doc_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer"},
                },
                "required": ["doc_id"],
            },
        },
    },
]

# ── Dispatcher ────────────────────────────────────────────────────────────────

_SYNC_DISPATCH: dict = {
    "create_event": create_event,
    "list_events":  list_events,
    "update_event": lambda **kw: update_event(kw.pop("event_id"), **kw),
    "delete_event": delete_event,
    "create_task":  create_task,
    "list_tasks":   list_tasks,
    "update_task":  lambda **kw: update_task(kw.pop("doc_id"), **kw),
    "delete_task":  delete_task,
}


def dispatch(name: str, arguments_json: str) -> str:
    """Call a tool by name with JSON arguments. Returns result as a JSON string."""
    args = json.loads(arguments_json)
    fn = _SYNC_DISPATCH[name]
    result = fn(**args)
    return json.dumps(result, default=str)
