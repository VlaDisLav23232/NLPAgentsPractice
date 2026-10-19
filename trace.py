import asyncio, sys
from flatmarket.agent_a import build_agent

async def main():
    agent = await build_agent()
    async for step in agent.astream({"messages": [("user", sys.argv[1])]}, stream_mode="updates"):
        for node, update in step.items():
            print(f"\n===== {node} =====")
            for m in update.get("messages", []):
                m.pretty_print()

asyncio.run(main())
