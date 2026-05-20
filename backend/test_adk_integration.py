import asyncio
import sys
from backend.memory import RedisAgentMemoryService, load_config, new_session_id


async def run_integration_tests():
    print("=========================================")
    print("RUNNING ADK 2.0 AGENT INTEGRATION TESTS...")
    print("=========================================")

    # 1. Load config and instantiate service
    config = load_config()
    print(f"Loaded config: owner_id={config.owner_id}, namespace={config.namespace}")
    
    service = RedisAgentMemoryService(config)
    session_id = new_session_id()
    print(f"Allocated test session_id: {session_id}")

    # 2. Reset session memory to ensure clean state
    await service.delete_session_memory(session_id)
    print("Reset session memory.")

    # 3. Turn 1: Introduce permanent preferences
    user_text_1 = "Hi! My name is Ricardo. I prefer window seats and always fly Delta. I'm vegetarian."
    print(f"\n--- Turn 1 (User): {user_text_1}")
    
    result_1 = await service.run_turn(session_id, user_text_1)
    
    print(f"Turn 1 (Assistant): {result_1.assistant_text}")
    print(f"Turn 1 (Retrieved LTM): {result_1.long_term_memories}")
    print(f"Turn 1 (Extracted LTM): {result_1.extracted_memories}")
    print(f"Turn 1 (STM events count): {len(result_1.session_context)}")

    # Assertions for Turn 1
    assert result_1.assistant_text, "Assistant response should not be empty."
    assert len(result_1.extracted_memories) > 0, "Should extract some long term memories."
    assert any("Ricardo" in m for m in result_1.extracted_memories), "Should extract name fact."
    assert any("Delta" in m or "fly" in m for m in result_1.extracted_memories), "Should extract airline preference."
    assert any("vegetarian" in m for m in result_1.extracted_memories), "Should extract dietary restriction."
    print("Turn 1 assertion checks: PASSED")

    # 4. Turn 2: Repeat preferences to verify deduplication
    user_text_2 = "Yes, remember that I prefer window seats."
    print(f"\n--- Turn 2 (User): {user_text_2}")
    
    result_2 = await service.run_turn(session_id, user_text_2)
    
    print(f"Turn 2 (Assistant): {result_2.assistant_text}")
    print(f"Turn 2 (Retrieved LTM): {result_2.long_term_memories}")
    print(f"Turn 2 (Extracted LTM): {result_2.extracted_memories}")

    # Assertions for Turn 2
    assert not result_2.extracted_memories, "Should NOT extract duplicate window seat preference."
    print("Turn 2 assertion checks (Deduplication): PASSED")

    # 5. Start Session 2: Verify Long-Term Memory recall across sessions!
    session_id_2 = new_session_id()
    print(f"\nAllocated new session_id: {session_id_2}")
    
    user_text_3 = "Can you suggest some travel ideas or dinner plans for tonight?"
    print(f"--- Turn 3 in New Session (User): {user_text_3}")
    
    result_3 = await service.run_turn(session_id_2, user_text_3)
    
    print(f"Turn 3 (Assistant): {result_3.assistant_text}")
    print(f"Turn 3 (Retrieved LTM): {result_3.long_term_memories}")
    print(f"Turn 3 (Extracted LTM): {result_3.extracted_memories}")

    # Assertions for Turn 3
    assert len(result_3.long_term_memories) > 0, "Should retrieve long term memories from profile."
    assert any("vegetarian" in m for m in result_3.long_term_memories), "Should retrieve vegetarian preference."
    assert "meat" not in result_3.assistant_text.lower(), "Assistant should respect vegetarian restriction."
    print("Turn 3 assertion checks (LTM Recall & Personalization): PASSED")

    # 6. Cleanup
    await service.delete_session_memory(session_id)
    await service.delete_session_memory(session_id_2)
    print("\nCleaned up all session memories.")
    print("=========================================")
    print("ALL ADK 2.0 INTEGRATION TESTS COMPLETED SUCCESSFULLY!")
    print("=========================================")


if __name__ == "__main__":
    try:
        asyncio.run(run_integration_tests())
    except Exception as e:
        print(f"\nTest Execution FAILED with error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
