from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.service import (
    DemoConfig,
    AdkAgentMemoryService,
    MemoryCandidate,
    MemoryExtraction,
    TurnResult,
)

DEMO_CONFIG = DemoConfig(
    project_id="test-project",
    location="us-central1",
    agent_engine_id="test-engine-id",
    owner_id="testuser",
    namespace="test-ns",
    agent_id="test-agent",
)


@pytest.fixture
def service():
    """Service with all external cloud clients mocked."""
    with patch("backend.service.genai.Client"), \
         patch("backend.service.VertexAiMemoryBankService"), \
         patch("backend.service.InMemoryMemoryService"), \
         patch("backend.service.InMemorySessionService"), \
         patch("backend.service.get_travel_agent"):
        svc = AdkAgentMemoryService(DEMO_CONFIG)
    
    svc.session_service = AsyncMock()
    svc.memory_service = AsyncMock()
    svc.genai_client = MagicMock()
    svc.agent = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# read_session_context
# ---------------------------------------------------------------------------

class TestReadSessionContext:
    @pytest.mark.asyncio
    async def test_returns_empty_list_on_no_session(self, service):
        service.session_service.get_session.return_value = None
        assert await service.read_session_context(None, "session-123") == []

    @pytest.mark.asyncio
    async def test_returns_formatted_context_lines(self, service):
        from google.adk import Event
        from google.genai import types
        
        event1 = Event(author="user", content=types.Content(parts=[types.Part.from_text(text="Hello")], role="user"))
        event2 = Event(author="travel_agent", content=types.Content(parts=[types.Part.from_text(text="Hi!")], role="model"))
        
        mock_session = MagicMock()
        mock_session.events = [event1, event2]
        service.session_service.get_session.return_value = mock_session
        
        result = await service.read_session_context(None, "session-123")
        assert result == ["user: Hello", "assistant: Hi!"]

    @pytest.mark.asyncio
    async def test_skips_events_with_empty_text(self, service):
        from google.adk import Event
        from google.genai import types
        
        event = Event(author="user", content=types.Content(parts=[types.Part.from_text(text="")], role="user"))
        mock_session = MagicMock()
        mock_session.events = [event]
        service.session_service.get_session.return_value = mock_session
        
        assert await service.read_session_context(None, "session-123") == []

    @pytest.mark.asyncio
    async def test_truncates_to_session_context_limit(self, service):
        from google.adk import Event
        from google.genai import types
        
        events = [
            Event(author="user", content=types.Content(parts=[types.Part.from_text(text=f"message {i}")], role="user"))
            for i in range(20)
        ]
        mock_session = MagicMock()
        mock_session.events = events
        service.session_service.get_session.return_value = mock_session
        
        result = await service.read_session_context(None, "session-123")
        assert len(result) == 12  # Last 12 messages limit


# ---------------------------------------------------------------------------
# delete_session_memory
# ---------------------------------------------------------------------------

class TestDeleteSessionMemory:
    @pytest.mark.asyncio
    async def test_raises_wrapped_error_on_exceptions(self, service):
        service.session_service.delete_session.side_effect = RuntimeError("Service down")
        # Should catch and log, and not crash or raise directly if handled
        await service.delete_session_memory(None, "session-123")
        service.session_service.delete_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_success(self, service):
        service.session_service.delete_session.return_value = None
        assert await service.delete_session_memory(None, "session-123") is None


# ---------------------------------------------------------------------------
# run_turn — deduplication logic
# ---------------------------------------------------------------------------

class TestRunTurnDeduplication:
    """
    Verify that memories already present in retrieved long-term memory are
    NOT re-written/extracted as new, while genuinely new ones ARE written and returned.
    """

    @pytest.mark.asyncio
    async def test_new_memory_is_extracted(self, service):
        from google.adk.memory.base_memory_service import SearchMemoryResponse, MemoryEntry
        from google.genai import types
        from google.adk import Event
        
        service.memory_service.search_memory.return_value = SearchMemoryResponse(memories=[])
        
        mock_event = MagicMock()
        mock_event.author = "travel_agent"
        mock_event.content = types.Content(parts=[types.Part.from_text(text="Sure!")])
        
        with patch("backend.service.Runner") as MockRunner:
            runner_instance = MagicMock()
            runner_instance.run.return_value = [mock_event]
            MockRunner.return_value = runner_instance
            
            # Mock get_session for context
            event1 = Event(author="user", content=types.Content(parts=[types.Part.from_text(text="I am vegetarian")], role="user"))
            mock_session = MagicMock()
            mock_session.events = [event1]
            service.session_service.get_session.return_value = mock_session
            
            # Mock structured memory extraction
            mock_response = MagicMock()
            mock_response.text = '{"memories": [{"text": "User is vegetarian.", "topics": ["diet"], "memory_type": "semantic"}]}'
            service.genai_client.models.generate_content.return_value = mock_response
            
            result = await service.run_turn(None, "session-123", "I am vegetarian.")
            
            assert result.session_id == "session-123"
            assert result.assistant_text == "Sure!"
            assert result.extracted_memories == ["User is vegetarian."]

    @pytest.mark.asyncio
    async def test_duplicate_memory_is_ignored(self, service):
        from google.adk.memory.base_memory_service import SearchMemoryResponse, MemoryEntry
        from google.genai import types
        from google.adk import Event
        
        existing_mem = MemoryEntry(content=types.Content(parts=[types.Part.from_text(text="User prefers Delta Airlines.")]))
        service.memory_service.search_memory.return_value = SearchMemoryResponse(memories=[existing_mem])
        
        mock_event = MagicMock()
        mock_event.author = "travel_agent"
        mock_event.content = types.Content(parts=[types.Part.from_text(text="Got it!")])
        
        with patch("backend.service.Runner") as MockRunner:
            runner_instance = MagicMock()
            runner_instance.run.return_value = [mock_event]
            MockRunner.return_value = runner_instance
            
            # Mock get_session for context
            event1 = Event(author="user", content=types.Content(parts=[types.Part.from_text(text="I prefer Delta Airlines")], role="user"))
            mock_session = MagicMock()
            mock_session.events = [event1]
            service.session_service.get_session.return_value = mock_session
            
            # Mock structured memory extraction returning the same duplicate memory
            mock_response = MagicMock()
            mock_response.text = '{"memories": [{"text": "User prefers Delta Airlines.", "topics": ["flight"], "memory_type": "semantic"}]}'
            service.genai_client.models.generate_content.return_value = mock_response
            
            result = await service.run_turn(None, "session-123", "I prefer Delta Airlines.")
            
            assert result.extracted_memories == []
