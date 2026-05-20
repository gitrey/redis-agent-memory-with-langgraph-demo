from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


from .service import AdkAgentMemoryService, load_config, new_session_id

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Google ADK 2.0 Agent Memory Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str


class ChatResponse(BaseModel):
    session_id: str
    user_message: str
    assistant_message: str
    short_term_memory: list[str]
    long_term_memory: list[str]
    extracted_long_term_memory: list[str]


class SessionMemoryResponse(BaseModel):
    session_id: str
    short_term_memory: list[str]


class HealthResponse(BaseModel):
    status: str


class AgentMemoryHealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    agent_memory: AgentMemoryHealthResponse


@lru_cache
def get_service() -> AdkAgentMemoryService:
    return AdkAgentMemoryService(load_config())


def agent_memory_client(service: AdkAgentMemoryService) -> Any:
    # Dummy/mock client since ADK does not require a manual client connection
    return object()


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/ready", response_model=ReadinessResponse)
async def ready() -> ReadinessResponse:
    service = get_service()
    try:
        # Check if service is initialized
        if service.memory_service is None:
            raise RuntimeError("Memory service not initialized")
    except Exception as exc:
        logger.warning("ADK Agent Memory readiness check failed", exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="ADK Agent Memory is not ready",
        ) from exc

    return ReadinessResponse(status="ok", agent_memory=AgentMemoryHealthResponse(status="ok"))


@app.post("/api/sessions", response_model=SessionResponse)
async def create_session() -> SessionResponse:
    return SessionResponse(session_id=new_session_id())


@app.get("/api/sessions/{session_id}/memory", response_model=SessionMemoryResponse)
async def get_session_memory(session_id: str) -> SessionMemoryResponse:
    service = get_service()
    try:
        memory = await service.read_session_context(None, session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SessionMemoryResponse(session_id=session_id, short_term_memory=memory)


@app.delete("/api/sessions/{session_id}/memory", response_model=SessionMemoryResponse)
async def delete_session_memory(session_id: str) -> SessionMemoryResponse:
    service = get_service()
    try:
        await service.delete_session_memory(None, session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SessionMemoryResponse(session_id=session_id, short_term_memory=[])


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    service = get_service()
    session_id = request.session_id or new_session_id()
    try:
        result = await service.run_turn(None, session_id, request.message.strip())
    except Exception as exc:
        logger.exception("Error in chat turn processing")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        session_id=result.session_id,
        user_message=result.user_text,
        assistant_message=result.assistant_text,
        short_term_memory=result.session_context,
        long_term_memory=result.long_term_memories,
        extracted_long_term_memory=result.extracted_memories,
    )
