import asyncio
import os
import sys
from band import Agent
from band.adapters.gemini import GeminiAdapter
from google.genai.errors import ClientError, ServerError
import httpx

# Shared rate-limiting lock so the 3 agents don't burst the free tier API simultaneously
api_lock = asyncio.Lock()


class RobustGeminiAdapter(GeminiAdapter):
    """
    Subclasses GeminiAdapter to handle ClientError (429 Rate Limits / Quotas)
    and serializes requests across the factory seats to eliminate 'Internal error' drops.
    """
    async def _generate_with_retry(self, contents, config):
        max_attempts = 6
        client = self._ensure_client()
        for attempt in range(1, max_attempts + 1):
            try:
                async with api_lock:
                    res = await client.aio.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=config,
                    )
                    await asyncio.sleep(0.5)  # Pace calls
                    return res
            except (ClientError, ServerError, httpx.TimeoutException, httpx.TransportError) as e:
                if attempt >= max_attempts:
                    print(f"[{self.model}] Exhausted retries ({max_attempts}): {e}")
                    raise
                delay_s = 2.0 * (2 ** (attempt - 1))
                print(f"[{self.model}] Rate limit / transient error on attempt {attempt}: retrying in {delay_s:.1f}s...")
                await asyncio.sleep(delay_s)
        raise AssertionError("unreachable")


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
            "- Track progress across stages and coordinate testing.\n"
            "- Keep replies concise and informative."
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
            "- Implement project code and requirements.\n"
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
            "- Review implementation and test suites.\n"
            "- Confirm all tests pass.\n"
            "- Keep messages concise and avoid conversational loops."
        )
    }
]


async def start_agent(cfg, gemini_api_key: str):
    print(f"[{cfg['name']}] Initializing with RobustGeminiAdapter...")
    adapter = RobustGeminiAdapter(
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
    print("Starting all 3 Band Factory Agents with Robust Rate Limiting...")
    print("=" * 60)

    tasks = []
    for cfg in AGENTS_CONFIG:
        tasks.append(asyncio.create_task(start_agent(cfg, gemini_key)))
        await asyncio.sleep(2)

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
