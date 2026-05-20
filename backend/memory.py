from __future__ import annotations

# Import and expose services and types from backend/service.py
from .service import (
    DemoConfig,
    load_config,
    new_session_id,
    MemoryCandidate,
    MemoryExtraction,
    TurnResult,
    AdkAgentMemoryService,
    memory_id,
    normalize_memory_text,
    message_text,
    coerce_memories,
    get_memory_text,
    coerce_events,
    get_event_role,
    get_event_text,
    is_not_found_error,
    explain_agent_memory_error,
)

# Alias for backward compatibility with tests/existing modules
RedisAgentMemoryService = AdkAgentMemoryService

__all__ = [
    "DemoConfig",
    "load_config",
    "new_session_id",
    "MemoryCandidate",
    "MemoryExtraction",
    "TurnResult",
    "AdkAgentMemoryService",
    "RedisAgentMemoryService",
    "memory_id",
    "normalize_memory_text",
    "message_text",
    "coerce_memories",
    "get_memory_text",
    "coerce_events",
    "get_event_role",
    "get_event_text",
    "is_not_found_error",
    "explain_agent_memory_error",
]
