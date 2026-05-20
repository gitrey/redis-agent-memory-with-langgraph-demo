from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .memory import RedisAgentMemoryService, load_config, new_session_id
from pydantic import BaseModel, Field


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
def get_service() -> RedisAgentMemoryService:
    return RedisAgentMemoryService(load_config())


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/ready", response_model=ReadinessResponse)
def ready() -> ReadinessResponse:
    # Always ready because ADK's InMemory session and memory services are fully self-contained
    return ReadinessResponse(
        status="ok",
        agent_memory=AgentMemoryHealthResponse(status="ok")
    )


@app.post("/api/sessions", response_model=SessionResponse)
def create_session() -> SessionResponse:
    return SessionResponse(session_id=new_session_id())


@app.get("/api/sessions/{session_id}/memory", response_model=SessionMemoryResponse)
async def get_session_memory(session_id: str) -> SessionMemoryResponse:
    service = get_service()
    try:
        memory = await service.read_session_context(session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SessionMemoryResponse(session_id=session_id, short_term_memory=memory)


@app.delete("/api/sessions/{session_id}/memory", response_model=SessionMemoryResponse)
async def delete_session_memory(session_id: str) -> SessionMemoryResponse:
    service = get_service()
    try:
        await service.delete_session_memory(session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SessionMemoryResponse(session_id=session_id, short_term_memory=[])


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    service = get_service()
    session_id = request.session_id or new_session_id()
    try:
        result = await service.run_turn(session_id, request.message.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(
        session_id=result.session_id,
        user_message=result.user_text,
        assistant_message=result.assistant_text,
        short_term_memory=result.session_context,
        long_term_memory=result.long_term_memories,
        extracted_long_term_memory=result.extracted_memories,
    )
