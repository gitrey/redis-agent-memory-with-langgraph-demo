from __future__ import annotations

import os
import uuid
import logging
import asyncio
import re
import hashlib
from datetime import datetime, timezone
from typing import Literal, Optional, Any
from pydantic import BaseModel, Field
from redis_agent_memory import errors

from google import genai
from google.genai import types
from google.adk import Runner, Event
from google.adk.sessions import InMemorySessionService, Session
from google.adk.memory import VertexAiMemoryBankService, InMemoryMemoryService

from backend.agent import get_travel_agent

logger = logging.getLogger("uvicorn.error")

class MemoryCandidate(BaseModel):
    text: str = Field(description="A durable memory written as one concise sentence.")
    topics: list[str] = Field(default_factory=list)
    memory_type: Literal["semantic", "episodic"] = "semantic"


class MemoryExtraction(BaseModel):
    memories: list[MemoryCandidate] = Field(default_factory=list)


class DemoConfig:
    def __init__(
        self,
        openai_model: str | None = None,
        agent_memory_server_url: str | None = None,
        agent_memory_store_id: str | None = None,
        agent_memory_api_key: str | None = None,
        owner_id: str | None = None,
        namespace: str | None = None,
        agent_id: str | None = None,
        project_id: str | None = None,
        location: str | None = None,
        agent_engine_id: str | None = None,
    ) -> None:
        self.openai_model = openai_model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.agent_memory_server_url = agent_memory_server_url or os.getenv("AGENT_MEMORY_SERVER_URL") or "https://memory.example.com"
        self.agent_memory_store_id = agent_memory_store_id or os.getenv("AGENT_MEMORY_STORE_ID") or "store-test"
        self.agent_memory_api_key = agent_memory_api_key or os.getenv("AGENT_MEMORY_API_KEY") or "key-test"
        self.project_id = project_id or os.getenv("PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("LOCATION", "us-central1")
        self.agent_engine_id = agent_engine_id or os.getenv("AGENT_ENGINE_ID")
        self.owner_id = owner_id or os.getenv("DEMO_OWNER_ID") or "riferrei"
        self.namespace = namespace or os.getenv("DEMO_NAMESPACE") or "langgraph-travel-demo"
        self.agent_id = agent_id or os.getenv("DEMO_AGENT_ID") or "travel-agent"


def load_config() -> DemoConfig:
    return DemoConfig()


class TurnResult(BaseModel):
    session_id: str
    user_text: str
    assistant_text: str
    session_context: list[str]
    long_term_memories: list[str]
    extracted_memories: list[str]


# ---------------------------------------------------------------------------
# Pure Python utility functions (kept for backward-compatibility with tests)
# ---------------------------------------------------------------------------

def memory_id(owner_id: str, namespace: str, text: str) -> str:
    digest = hashlib.sha256(f"{owner_id}:{namespace}:{text}".encode("utf-8")).hexdigest()
    return f"demo-{digest[:32]}"


def normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def new_session_id() -> str:
    return f"session-{uuid.uuid4().hex[:8]}"


def message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def coerce_memories(response: object) -> list[object]:
    if isinstance(response, dict):
        return list(response.get("items", response.get("memories", [])) or [])
    items = getattr(response, "items", None)
    if items is not None:
        return list(items)
    return []


def get_memory_text(memory: object) -> str:
    if isinstance(memory, dict):
        return str(memory.get("text", ""))
    return str(getattr(memory, "text", ""))


def coerce_events(response: object) -> list[object]:
    events = getattr(response, "events", None)
    if events is None and isinstance(response, dict):
        events = response.get("events")
    return list(events or [])


def get_event_role(event: object) -> str:
    role = event.get("role") if isinstance(event, dict) else getattr(event, "role", "")
    return str(getattr(role, "value", role)).lower()


def get_event_text(event: object) -> str:
    content = event.get("content", []) if isinstance(event, dict) else getattr(event, "content", [])
    parts = []
    for item in content or []:
        if isinstance(item, dict):
            parts.append(str(item.get("text", "")))
        else:
            parts.append(str(getattr(item, "text", "")))
    return "\n".join(part for part in parts if part)


def is_not_found_error(exc: Exception) -> bool:
    return isinstance(exc, errors.NotFoundErrorResponseContent) or getattr(exc, "status_code", None) == 404


def explain_agent_memory_error(operation: str, exc: Exception) -> RuntimeError:
    hint = (
        f"Redis Agent Memory {operation} failed. Check AGENT_MEMORY_SERVER_URL, "
        "AGENT_MEMORY_STORE_ID, and AGENT_MEMORY_API_KEY. The server URL should be "
        "the Agent Memory data-plane base URL, not the PyPI/docs URL."
    )
    return RuntimeError(f"{hint}\n\nOriginal error: {exc}")


class AdkAgentMemoryService:
    def __init__(self, config: DemoConfig | None = None) -> None:
        self.config = config or load_config()
        self.session_service = InMemorySessionService()
        
        if self.config.agent_engine_id and self.config.project_id:
            logger.info("Initializing VertexAiMemoryBankService")
            self.memory_service = VertexAiMemoryBankService(
                project=self.config.project_id,
                location=self.config.location,
                agent_engine_id=self.config.agent_engine_id
            )
        else:
            logger.info("AGENT_ENGINE_ID not set. Falling back to InMemoryMemoryService for local/test use.")
            self.memory_service = InMemoryMemoryService()
            
        self.genai_client = genai.Client()
        self.agent = get_travel_agent()
        self.app_name = self.config.namespace
        self.user_id = self.config.owner_id

    async def run_turn(self, agent_memory: Any, session_id: str, user_text: str) -> TurnResult:
        # 1. Retrieve current/recalled long-term memories for the user_text query
        long_term_memories = []
        try:
            search_response = await self.memory_service.search_memory(
                app_name=self.app_name,
                user_id=self.user_id,
                query=user_text
            )
            for memory in search_response.memories:
                parts = []
                if memory.content and memory.content.parts:
                    for p in memory.content.parts:
                        if p.text:
                            parts.append(p.text)
                text = "".join(parts).strip()
                if text:
                    long_term_memories.append(text)
        except Exception as exc:
            logger.warning("Failed to search long-term memory: %s", exc)
            
        # 2. Run the agent using Runner
        runner = Runner(
            agent=self.agent,
            session_service=self.session_service,
            memory_service=self.memory_service,
            app_name=self.app_name,
            auto_create_session=True
        )
        
        new_msg = types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_text)]
        )
        
        # Run turn and stream events
        assistant_parts = []
        events_stream = runner.run(
            user_id=self.user_id,
            session_id=session_id,
            new_message=new_msg
        )
        for event in events_stream:
            if event.author != "user" and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        assistant_parts.append(part.text)
                        
        assistant_text = "".join(assistant_parts).strip()
        
        # 3. Get session_context (short-term memory lines)
        session_context = await self.read_session_context(agent_memory, session_id)
        
        # 4. Extract new memories from user_text Turn using Gemini Structured Output
        extracted_memories = []
        try:
            extraction_prompt = (
                "Extract only durable user facts, persistent preferences, and stable constraints "
                "that the user explicitly states in the current message and that should help in future "
                "unrelated sessions. Do not extract active task details, current itinerary details, "
                "dates, destinations, booking requests, or other context that only matters for this "
                "conversation unless the user explicitly asks to remember it for later. Do not extract "
                "anything that is only mentioned by the assistant or already present in existing "
                "long-term memories. "
                "If the message is a short reply, a confirmation, a single word, a number, or only "
                "makes sense in the context of the current conversation, return an empty list.\n\n"
                "Examples of messages that should produce NO memories:\n"
                "- '1st' (a date fragment answering a question)\n"
                "- 'yes' (a confirmation)\n"
                "- 'no', 'ok', 'sure', 'sounds good' (short replies)\n"
                "- 'June 15th' (a date answering a question)\n"
                "- 'New York' (a destination answering a question)\n"
                "- 'I am planning a trip to Lisbon next month' (transient travel plan)\n\n"
                "Examples of messages that SHOULD produce memories:\n"
                "- 'My name is Ricardo' → 'The user's name is Ricardo.'\n"
                "- 'I always fly Delta' → 'The user prefers to fly Delta Airlines.'\n"
                "- 'I am vegetarian' → 'The user is vegetarian.'\n"
                "- 'I have two kids, a 3-year-old and a newborn' → 'The user has two kids: a newborn and a 3-year-old.'\n"
                "- 'yes, remember that I prefer window seats for next time' → 'The user prefers window seats.'\n"
                "- 'I always stay at Marriott hotels and I need a room in Paris next week' → 'The user prefers Marriott hotels.'\n\n"
                f"Current user message:\n{user_text}\n\n"
                "Existing long-term memories:\n"
                + "\n".join(f"- {m}" for m in long_term_memories)
            )
            
            response = self.genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=extraction_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MemoryExtraction
                )
            )
            
            if response.text:
                extraction = MemoryExtraction.model_validate_json(response.text)
                for memory_candidate in extraction.memories:
                    text = memory_candidate.text.strip()
                    if text:
                        norm_text = normalize_memory_text(text)
                        existing_norms = {normalize_memory_text(m) for m in long_term_memories}
                        if norm_text and norm_text not in existing_norms:
                            extracted_memories.append(text)
        except Exception as exc:
            logger.warning("Failed to extract memories: %s", exc)
            
        # 5. Ingest the session events into long term Memory Bank
        try:
            session_obj = await self.session_service.get_session(
                app_name=self.app_name,
                user_id=self.user_id,
                session_id=session_id
            )
            if session_obj:
                await self.memory_service.add_session_to_memory(session_obj)
        except Exception as exc:
            logger.warning("Failed to add session to long-term memory: %s", exc)
            
        return TurnResult(
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            session_context=session_context,
            long_term_memories=long_term_memories,
            extracted_memories=extracted_memories
        )

    async def read_session_context(self, agent_memory: Any, session_id: str) -> list[str]:
        try:
            session_obj = await self.session_service.get_session(
                app_name=self.app_name,
                user_id=self.user_id,
                session_id=session_id
            )
            if not session_obj:
                return []
                
            session_context = []
            for event in session_obj.events[-12:]:
                parts = []
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            parts.append(part.text)
                text = "".join(parts).strip()
                if text:
                    role = "user" if event.author.lower() in ("user", "human") else "assistant"
                    session_context.append(f"{role}: {text}")
            return session_context
        except Exception as exc:
            logger.warning("Failed to read session context: %s", exc)
            return []

    async def delete_session_memory(self, agent_memory: Any, session_id: str) -> None:
        try:
            await self.session_service.delete_session(
                app_name=self.app_name,
                user_id=self.user_id,
                session_id=session_id
            )
        except Exception as exc:
            logger.warning("Failed to delete session memory: %s", exc)
