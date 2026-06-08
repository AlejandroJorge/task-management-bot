import json

from backlog_tools import (
    create_backlog_item,
    delete_backlog_item,
    list_backlog,
    update_backlog_item,
)
from calendar_tools import create_event, delete_event, list_events, update_event
from tasks_tools import create_task, delete_task, list_tasks, update_task
from tracking_tools import create_timeblock, delete_timeblock, list_timeblocks, update_timeblock
from tracking_state import get_state as get_tracking_status, start_tracking, stop_tracking

# Tools that require explicit user confirmation before execution
REQUIRE_CONFIRMATION = {"delete_event", "delete_task", "delete_backlog_item", "delete_timeblock"}

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
                    "tz":          {"type": "string", "default": "America/Lima"},
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
    {
        "type": "function",
        "function": {
            "name": "create_backlog_item",
            "description": "Add a long-term idea or project to the backlog.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title":       {"type": "string"},
                    "description": {"type": "string", "description": "Optional details or motivation"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_backlog",
            "description": "List all items in the backlog.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_backlog_item",
            "description": "Edit a backlog item's title or description by its doc_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id":      {"type": "integer"},
                    "title":       {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_backlog_item",
            "description": "Permanently delete a backlog item by its doc_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer"},
                },
                "required": ["doc_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_timeblock",
            "description": (
                "Register a past time interval spent on an activity in the Tracking calendar. "
                "Both start and end must be before the current time. "
                "Overlapping timeblocks are rejected. "
                "Use ISO 8601 with UTC offset, e.g. 2026-06-07T16:34:00-05:00."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string", "description": "Name of the activity"},
                    "start":    {"type": "string", "description": "Start datetime, ISO 8601 with offset"},
                    "end":      {"type": "string", "description": "End datetime, ISO 8601 with offset"},
                    "notes":    {"type": "string", "description": "Optional notes"},
                },
                "required": ["activity", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_timeblocks",
            "description": "Query all timeblocks in the Tracking calendar between two datetimes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_min": {"type": "string", "description": "Start of range, ISO 8601 with offset"},
                    "time_max": {"type": "string", "description": "End of range, ISO 8601 with offset"},
                },
                "required": ["time_min", "time_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_timeblock",
            "description": (
                "Edit an existing timeblock. Any new start/end times must still be in the past. "
                "Overlapping timeblocks are rejected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "activity": {"type": "string"},
                    "start":    {"type": "string", "description": "ISO 8601 with offset"},
                    "end":      {"type": "string", "description": "ISO 8601 with offset"},
                    "notes":    {"type": "string"},
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_timeblock",
            "description": "Permanently delete a timeblock from the Tracking calendar.",
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
            "name": "start_tracking",
            "description": (
                "Start a live tracking session for an activity. "
                "Creates an event in the Tracking calendar immediately and keeps its end time updated every 5 minutes. "
                "Fails if a session is already active — call stop_tracking first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string", "description": "Name of the activity to track"},
                },
                "required": ["activity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_tracking",
            "description": "Stop the current live tracking session. Records the exact end time in Google Calendar.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tracking_status",
            "description": "Return the current tracking state: LIBRE (nothing active) or ACTIVO with activity name and elapsed time in minutes.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ── Dispatcher ────────────────────────────────────────────────────────────────

_SYNC_DISPATCH: dict = {
    "create_event":        create_event,
    "list_events":         list_events,
    "update_event":        lambda **kw: update_event(kw.pop("event_id"), **kw),
    "delete_event":        delete_event,
    "create_task":         create_task,
    "list_tasks":          list_tasks,
    "update_task":         lambda **kw: update_task(kw.pop("doc_id"), **kw),
    "delete_task":         delete_task,
    "create_backlog_item": create_backlog_item,
    "list_backlog":        list_backlog,
    "update_backlog_item": lambda **kw: update_backlog_item(kw.pop("doc_id"), **kw),
    "delete_backlog_item": delete_backlog_item,
    "create_timeblock":    create_timeblock,
    "list_timeblocks":     list_timeblocks,
    "update_timeblock":    lambda **kw: update_timeblock(kw.pop("event_id"), **kw),
    "delete_timeblock":    delete_timeblock,
    "start_tracking":      start_tracking,
    "stop_tracking":       stop_tracking,
    "get_tracking_status": get_tracking_status,
}


def dispatch(name: str, arguments_json: str) -> str:
    """Call a tool by name with JSON arguments. Returns result as a JSON string."""
    args = json.loads(arguments_json)
    fn = _SYNC_DISPATCH[name]
    result = fn(**args)
    return json.dumps(result, default=str)
