import asyncio
import os
import sys
from band import Agent
from band.adapters.gemini import GeminiAdapter

AGENTS_CONFIG = [
    {
        "role": "planner",
        "name": "Planner Agent",
        "id": "7b4960ce-0f45-4ca3-a4ab-52e40923e53a",
        "key": "band_a_1790428955_S6_nk_G1BpqmBaa6ECFZ1gwel6N6TOoP",
        "system_prompt": (
            "You are Planner Agent (@rogiebacanto2002/planner-agent).\n"
            "Description: Outline project tasks, break down specifications, and coordinate coding actions.\n\n"
            "Guidelines:\n"
            "- Coordinate with @Executor Agent and @Reviewer Agent concisely.\n"
            "- When work units are planned and confirmed by Executor and Reviewer, summarize the status.\n"
            "- Decompose Stage 3 (Capacity Matching, FIFO Waitlist, Cancellation Auto-Promotion) into structured work units.\n"
            "- Do not spam repeated acknowledgment messages. Keep replies concise and informative."
        )
    },
    {
        "role": "executor",
        "name": "Executor Agent",
        "id": "c174a118-a7a4-43c3-a56f-c98bc300b4b4",
        "key": "band_a_1790428932_tWOpb-f6RSCan5HMudAhxWcV5k_PSy0K",
        "system_prompt": (
            "You are Executor Agent (@rogiebacanto2002/executor-agent).\n"
            "Description: Implement code, write scripts, and apply specifications.\n\n"
            "Guidelines:\n"
            "- Implement Stage 3 in stage-3/ with table capacities, waitlist management, and atomic cancellation auto-promotion.\n"
            "- Ensure database transaction locks prevent race conditions during promotion.\n"
            "- Report ready for @Reviewer Agent to verify.\n"
            "- Keep messages concise and do not repeat identical messages."
        )
    },
    {
        "role": "reviewer",
        "name": "Reviewer Agent",
        "id": "b94d5ff2-d8df-488c-9cb5-e19cac8054ac",
        "key": "band_a_1790428968_7E4u6kh7XWYrzFbmqaceiMSug76xquGs",
        "system_prompt": (
            "You are Reviewer Agent (@rogiebacanto2002/reviewer-agent).\n"
            "Description: Evaluate code quality, verify implementation logic, and suggest improvements.\n\n"
            "Guidelines:\n"
            "- Review the Stage 3 implementation and test suite.\n"
            "- Confirm table capacity matching, waitlist FIFO queue, cancellation auto-promotion, and concurrency tests.\n"
            "- State that verification is PASS.\n"
            "- Keep messages concise and avoid conversational loops."
        )
    }
]

async def start_agent(cfg, gemini_api_key: str):
    print(f"[{cfg['name']}] Initializing with Gemini 2.5 Flash Lite...")
    adapter = GeminiAdapter(
        model="gemini-2.5-flash-lite",
        provider_key=gemini_api_key,
        system_prompt=cfg["system_prompt"],
        max_retries=5,
        retry_base_delay_s=2.0
    )
    agent = Agent.create(
        adapter=adapter,
        agent_id=cfg["id"],
        api_key=cfg["key"]
    )
    print(f"[{cfg['name']}] Connecting to Band WebSocket... [ONLINE]")
    await agent.run()

async def main():
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        print("ERROR: Please set GEMINI_API_KEY environment variable.")
        sys.exit(1)

    print("=" * 60)
    print("Starting all 3 Band Factory Agents with Gemini 2.5 Flash Lite...")
    print("=" * 60)

    # Stagger startups slightly to avoid simultaneous API bursts
    tasks = []
    for cfg in AGENTS_CONFIG:
        tasks.append(asyncio.create_task(start_agent(cfg, gemini_key)))
        await asyncio.sleep(2)

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
