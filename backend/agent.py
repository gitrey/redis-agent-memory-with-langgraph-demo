from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.load_memory_tool import load_memory_tool

SYSTEM_PROMPT = """You are a polished travel concierge.

Use short-term memory (your session history) for continuity within the current session.
Use your long-term memory tool to search and retrieve durable user facts, persistent preferences, and stable constraints (like preferred airlines, dietary restrictions, name, family members) using relevant search queries.
Do not mention implementation details.
Keep answers concise, specific, and naturally personalized.
"""

def get_travel_agent() -> LlmAgent:
    """Initialize and return the Travel Agent as an ADK LlmAgent."""
    return LlmAgent(
        name="travel_agent",
        model="gemini-2.5-flash",
        instruction=SYSTEM_PROMPT,
        tools=[load_memory_tool],
        mode="chat",
    )

