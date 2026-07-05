import json

from categories import load_categories

from backlog_tools import (
    create_backlog_item,
    delete_backlog_item,
    list_backlog,
    update_backlog_item,
)
from calendar_tools import create_event, delete_event, list_events, update_event
from tasks_tools import create_task, delete_task, list_tasks, update_task
from tracking_tools import create_timeblock, delete_timeblock, list_timeblocks, update_timeblock
from tracking_state import start_tracking, stop_tracking

REQUIRE_CONFIRMATION = {"delete_event", "delete_task", "delete_backlog_item", "delete_timeblock"}

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
                "Register a past time interval in the Tracking calendar. "
                "Both start and end must be before the current time. "
                "Overlapping timeblocks are rejected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string"},
                    "start":    {"type": "string", "description": "ISO 8601 with offset"},
                    "end":      {"type": "string", "description": "ISO 8601 with offset"},
                    "notes":    {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": list(load_categories().keys()),
                        "description": "Activity category.",
                    },
                },
                "required": ["activity", "start", "end", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_timeblocks",
            "description": "Query timeblocks in the Tracking calendar between two datetimes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_min": {"type": "string", "description": "ISO 8601 with offset"},
                    "time_max": {"type": "string", "description": "ISO 8601 with offset"},
                },
                "required": ["time_min", "time_max"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_timeblock",
            "description": "Edit an existing timeblock. New times must be in the past.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "activity": {"type": "string"},
                    "start":    {"type": "string", "description": "ISO 8601 with offset"},
                    "end":      {"type": "string", "description": "ISO 8601 with offset"},
                    "notes":    {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": list(load_categories().keys()),
                    },
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
                "Start a live tracking session. "
                "Use started_at when the user says they already started a while ago. "
                "The bot will show a widget with duration options."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string"},
                    "started_at": {
                        "type": "string",
                        "description": "Optional. ISO 8601 with offset. Use when activity already started before now.",
                    },
                    "category": {
                        "type": "string",
                        "enum": list(load_categories().keys()),
                        "description": "Activity category.",
                    },
                },
                "required": ["activity", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_tracking",
            "description": "Stop the current live tracking session and log it to Google Calendar.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ── Dispatcher ────────────────────────────────────────────────────────────────

def _stop_and_log() -> dict:
    from tracking_tools import create_timeblock as _create_timeblock
    final = stop_tracking()
    try:
        _create_timeblock(
            final["activity"],
            final["started_at"],
            final["ended_at"],
            category=final.get("category", "unclassified"),
        )
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).warning("Failed to create timeblock on LLM stop")
    return final


_SYNC_DISPATCH: dict = {
    "create_event":        create_event,
    "list_events":         lambda **kw: [
                               {k: e[k] for k in ("id", "summary", "start", "end", "description", "location") if k in e}
                               for e in list_events(**kw)
                           ],
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
    "stop_tracking":       lambda **_: _stop_and_log(),
}


def dispatch(name: str, arguments_json: str) -> str:
    args = json.loads(arguments_json)
    fn = _SYNC_DISPATCH[name]
    result = fn(**args)
    return json.dumps(result, default=str)
