from __future__ import annotations

import os
import uuid
import asyncio
from dataclasses import dataclass
from typing import Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from google import genai
from google.genai import types

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import Gemini
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.sessions import InMemorySessionService
from google.adk.memory import InMemoryMemoryService
from google.adk.runners import Runner


# Persistent local development services
_session_service = InMemorySessionService()
_memory_service = InMemoryMemoryService()
_user_extracted_facts: dict[str, list[str]] = {}


@dataclass(frozen=True)
class DemoConfig:
    owner_id: str
    namespace: str
    agent_id: str
    openai_model: str = "gemini-2.5-flash"
    agent_memory_server_url: str = "in-memory"
    agent_memory_store_id: str = "in-memory"
    agent_memory_api_key: str = "in-memory"


@dataclass(frozen=True)
class TurnResult:
    session_id: str
    user_text: str
    assistant_text: str
    session_context: list[str]
    long_term_memories: list[str]
    extracted_memories: list[str]


def load_config() -> DemoConfig:
    load_dotenv()
    return DemoConfig(
        owner_id=os.getenv("DEMO_OWNER_ID", "riferrei"),
        namespace=os.getenv("DEMO_NAMESPACE", "travel-demo"),
        agent_id=os.getenv("DEMO_AGENT_ID", "travel-agent"),
    )


def new_session_id() -> str:
    return f"session-{uuid.uuid4().hex[:8]}"


async def generate_memories_callback(callback_context: CallbackContext):
    """Sends the session's events to Memory Bank for memory generation."""
    await callback_context.add_session_to_memory()
    return None


# travel_agent holds the ADK Agent definition with PreloadMemoryTool and Memory Bank Callback
travel_agent = Agent(
    name="travel_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are a polished travel concierge.
Use short-term memory for continuity within the current session.
Use long-term memory for durable user facts, preferences, and constraints.
Do not mention implementation details.
Keep answers concise, specific, and naturally personalized.
""",
    tools=[
        PreloadMemoryTool(),
    ],
    after_agent_callback=generate_memories_callback,
)


class RedisAgentMemoryService:
    """FastAPI programmatic adapter wrapping ADK's Runner and Services."""

    def __init__(self, config: DemoConfig) -> None:
        self.config = config
        self._genai_client = genai.Client()
        self.runner = Runner(
            agent=travel_agent,
            session_service=_session_service,
            memory_service=_memory_service,
            app_name=config.namespace,
        )

    async def run_turn(self, session_id: str, user_text: str) -> TurnResult:
        user_id = self.config.owner_id
        app_name = self.config.namespace
        user_key = f"{app_name}/{user_id}"

        # 1. Fetch short-term memory (session history) BEFORE running the turn
        session = await _session_service.get_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
        if not session:
            session = await _session_service.create_session(
                app_name=app_name, user_id=user_id, session_id=session_id
            )

        session_context = []
        for event in session.events:
            if event.content and event.content.parts:
                text = "\n".join([p.text for p in event.content.parts if p.text]).strip()
                if text:
                    role = "user" if event.author == "user" else "assistant"
                    session_context.append(f"{role}: {text}")

        # 2. Match relevant existing long-term facts for the side panel
        existing_facts = _user_extracted_facts.get(user_key, [])
        long_term_memories = []
        if existing_facts:
            # Simple keyword associations for local simulation
            food_words = {"dinner", "lunch", "breakfast", "meal", "food", "eat", "restaurant", "dining", "vegetarian", "vegan"}
            travel_words = {"travel", "fly", "flight", "airlines", "delta", "seat", "window", "trip", "vacation"}
            
            words_in_query = set(user_text.lower().replace("?", "").replace(".", "").replace(",", "").split())
            has_food = bool(words_in_query.intersection(food_words))
            has_travel = bool(words_in_query.intersection(travel_words))
            
            for fact in existing_facts:
                fact_lower = fact.lower()
                fact_words = set(fact_lower.replace(".", "").replace(",", "").split())
                
                # Direct intersection match
                if words_in_query.intersection(fact_words):
                    long_term_memories.append(fact)
                # Globally relevant facts (like user's name) are always matched
                elif "name" in fact_lower or "called" in fact_lower:
                    long_term_memories.append(fact)
                # Category match: query has food words, and fact has food-related concepts
                elif has_food and ("vegetarian" in fact_lower or "diet" in fact_lower or "eat" in fact_lower or "food" in fact_lower or "vegan" in fact_lower):
                    long_term_memories.append(fact)
                # Category match: query has travel words, and fact has travel-related concepts
                elif has_travel and ("fly" in fact_lower or "seat" in fact_lower or "delta" in fact_lower or "hotel" in fact_lower or "travel" in fact_lower):
                    long_term_memories.append(fact)
            
            # If no semantic or keyword match, return up to 5 general facts to keep visual panels populated
            if not long_term_memories:
                long_term_memories = existing_facts[:5]

        # 3. Run turn with ADK Runner
        message_content = types.Content(
            role="user", parts=[types.Part.from_text(text=user_text)]
        )
        
        events = []
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message_content,
        ):
            events.append(event)

        assistant_text = ""
        for event in events:
            if event.author != "user" and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        assistant_text += part.text

        # Fetch updated session after turn
        updated_session = await _session_service.get_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
        
        updated_session_context = []
        for event in updated_session.events:
            if event.content and event.content.parts:
                text = "\n".join([p.text for p in event.content.parts if p.text]).strip()
                if text:
                    role = "user" if event.author == "user" else "assistant"
                    updated_session_context.append(f"{role}: {text}")

        # 4. Extract new durable memories using the structured extraction pipeline
        class MemoryCandidate(BaseModel):
            text: str = Field(description="A durable memory written as one concise sentence.")

        class MemoryExtraction(BaseModel):
            memories: list[MemoryCandidate] = Field(default_factory=list)

        extracted_memories = []
        try:
            extraction_prompt = f"""Extract only durable user facts, persistent preferences, and stable constraints
that the user explicitly states in the current message and that should help in future
unrelated sessions. Do not extract active task details, current itinerary details,
dates, destinations, booking requests, or other context that only matters for this
conversation unless the user explicitly asks to remember it for later. Do not extract
anything that is only mentioned by the assistant or already present in existing
long-term memories.
If the message is a short reply, a confirmation, a single word, a number, or only
makes sense in the context of the current conversation, return an empty list.

Examples of messages that should produce NO memories:
- '1st' (a date fragment answering a question)
- 'yes' (a confirmation)
- 'no', 'ok', 'sure', 'sounds good' (short replies)
- 'June 15th' (a date answering a question)
- 'New York' (a destination answering a question)
- 'I am planning a trip to Lisbon next month' (transient travel plan)

Examples of messages that SHOULD produce memories:
- 'My name is Ricardo' -> 'The user's name is Ricardo.'
- 'I always fly Delta' -> 'The user prefers to fly Delta Airlines.'
- 'I am vegetarian' -> 'The user is vegetarian.'
- 'I have two kids, a 3-year-old and a newborn' -> 'The user has two kids: a newborn and a 3-year-old.'
- 'yes, remember that I prefer window seats for next time' -> 'The user prefers window seats.'
- 'I always stay at Marriott hotels and I need a room in Paris next week' -> 'The user prefers Marriott hotels.'
"""
            contents = [
                types.Content(role="user", parts=[
                    types.Part.from_text(text=f"Current user message: {user_text}\n\nExisting long-term memories:\n" + "\n".join(f"- {f}" for f in existing_facts))
                ])
            ]
            
            response = self._genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=MemoryExtraction,
                    system_instruction=extraction_prompt,
                )
            )
            
            extraction_data = MemoryExtraction.model_validate_json(response.text)
            normalized_existing = {f.lower().strip().replace(".", "") for f in existing_facts}
            
            for candidate in extraction_data.memories:
                text = candidate.text.strip()
                if not text:
                    continue
                norm_cand = text.lower().replace(".", "")
                if norm_cand not in normalized_existing:
                    extracted_memories.append(text)
                    
            if extracted_memories:
                if user_key not in _user_extracted_facts:
                    _user_extracted_facts[user_key] = []
                _user_extracted_facts[user_key].extend(extracted_memories)
                
        except Exception as exc:
            print(f"Error during memory extraction: {exc}")

        return TurnResult(
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            session_context=updated_session_context,
            long_term_memories=long_term_memories,
            extracted_memories=extracted_memories,
        )

    async def read_session_context(self, session_id: str) -> list[str]:
        user_id = self.config.owner_id
        app_name = self.config.namespace
        session = await _session_service.get_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
        if not session:
            return []
            
        session_context = []
        for event in session.events:
            if event.content and event.content.parts:
                text = "\n".join([p.text for p in event.content.parts if p.text]).strip()
                if text:
                    role = "user" if event.author == "user" else "assistant"
                    session_context.append(f"{role}: {text}")
        return session_context

    async def delete_session_memory(self, session_id: str) -> None:
        user_id = self.config.owner_id
        app_name = self.config.namespace
        await _session_service.delete_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
