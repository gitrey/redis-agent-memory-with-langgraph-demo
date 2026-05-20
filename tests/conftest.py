"""Shared fixtures and helpers for the test suite."""
from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from redis_agent_memory.errors.notfounderrorresponsecontent import (
    NotFoundErrorResponseContent,
    NotFoundErrorResponseContentData,
)
from redis_agent_memory.models.notfounderrortype import NotFoundErrorType


def make_not_found_error() -> NotFoundErrorResponseContent:
    """Build a real NotFoundErrorResponseContent with a mocked httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 404
    response.text = "not found"
    response.headers = httpx.Headers()
    data = NotFoundErrorResponseContentData(
        title="Not Found",
        type=NotFoundErrorType.ROOT_ERRORS_RESOURCE_NOT_FOUND,
    )
    return NotFoundErrorResponseContent(data=data, raw_response=response)


@pytest.fixture(autouse=True, scope="session")
def mock_gemini_calls():
    """Globally mock Gemini model async content generation to avoid real API calls."""
    import google.adk.models.google_llm
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    original_generate = google.adk.models.google_llm.Gemini.generate_content_async

    async def mock_generate_content_async(self, llm_request, stream=False):
        yield LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text="I am a helpful travel concierge. How can I help you today?")]
            ),
            partial=False,
            turn_complete=True,
        )

    google.adk.models.google_llm.Gemini.generate_content_async = mock_generate_content_async
    yield
    google.adk.models.google_llm.Gemini.generate_content_async = original_generate

