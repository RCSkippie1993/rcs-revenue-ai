from __future__ import annotations
import asyncio
from dotenv import load_dotenv
from agents import Runner
from rich.console import Console
from rich.panel import Panel
from .agents import manager

load_dotenv()
console = Console()

START_PROMPT = """
Start Revenue Sprint 001.
Research current opportunities and select the best initial experiment for a South African operator
with strengths in professional services, B2B commercial work, contract/document workflows,
business development and online content. Keep legal/professional outputs behind human review.
Target: first R10,000 of attributable online revenue with low upfront capital.
Build the offer and lead-generation plan, but do not publish, send outreach or spend money.
"""

async def main():
    result = await Runner.run(manager, START_PROMPT)
    if result.interruptions:
        console.print(Panel("Run paused for human approval. No external action was executed.", title="Approval Required"))
        for item in result.interruptions:
            console.print(item)
        return
    console.print(Panel(str(result.final_output), title="Revenue Sprint 001"))

if __name__ == "__main__":
    asyncio.run(main())
