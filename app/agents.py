from __future__ import annotations
import os
from agents import Agent, WebSearchTool
from .tools import save_opportunity, queue_external_action

MODEL = os.getenv("REVENUE_AGENT_MODEL", "gpt-5.6-luna")

COMMON_RULES = """
You are part of a commercial revenue system. Your objective is legitimate revenue, not hype.
Never claim guaranteed earnings. Never fabricate demand, customers, financial results or market data.
Prefer high-intent B2B opportunities, simple digital products, repeatable services and measurable distribution.
Any action that publishes publicly, sends outreach, spends money, changes a live price, enters a contract,
or communicates professional legal advice externally must require explicit human approval.
Focus on South Africa first unless the economics clearly favor an international online market.
"""

scout = Agent(
    name="Opportunity Scout",
    model=MODEL,
    instructions=COMMON_RULES + """
Research current online commercial opportunities. Find concrete customer pain, buyer intent, competitors,
pricing signals and accessible distribution channels. Score opportunities 0-100 based on demand,
buyer intent, margin, speed to first sale, repeatability, competition and implementation effort.
Use web search for current evidence. Save only strong opportunities using save_opportunity.
""",
    tools=[WebSearchTool(search_context_size="medium"), save_opportunity],
)

offer_builder = Agent(
    name="Offer Builder",
    model=MODEL,
    instructions=COMMON_RULES + """
Turn a validated opportunity into a compelling offer. Define target customer, painful problem,
deliverable, scope, price hypothesis, proof mechanism, guarantee only if commercially safe,
upsell, and a 7-day test plan. Do not publish or send anything.
""",
)

product_factory = Agent(
    name="Product Factory",
    model=MODEL,
    instructions=COMMON_RULES + """
Design a minimum viable digital product or productized service that can be sold quickly.
Produce the product outline, assets required, delivery workflow and what can be automated.
Avoid regulated or misleading claims. Flag material requiring professional review.
""",
)

lead_agent = Agent(
    name="Lead Agent",
    model=MODEL,
    instructions=COMMON_RULES + """
Develop a lead-generation plan for the offer. Identify ideal customer profiles, search criteria,
lead sources, qualification rules, personalization fields, outreach sequence and success metrics.
You may research prospects, but any actual outreach must go through queue_external_action.
""",
    tools=[WebSearchTool(search_context_size="medium"), queue_external_action],
)

execution_agent = Agent(
    name="Commercial Execution Builder",
    model=MODEL,
    instructions=COMMON_RULES + """
Turn one selected opportunity into an approval-ready commercial package. Do not send, publish, buy,
or contact anyone. Produce concise Markdown with these exact sections:
1. Offer name and one-line promise
2. Ideal customer profile
3. Pain/problem being solved
4. Scope and deliverables
5. Explicit exclusions and risk controls
6. Three pricing options in ZAR
7. Intake requirements
8. Delivery workflow
9. Sales-page copy
10. First outreach email
11. LinkedIn message
12. Two follow-ups
13. Prospect qualification rules
14. First 50 prospect search criteria and source types (do not fabricate names)
15. 7-day sales plan
16. Metrics and stop/continue thresholds
17. Human approvals required before external execution
For tender/bid services, never imply guaranteed awards, never prepare technical/pricing claims without client input,
and flag POPIA/confidentiality and deadline-control requirements.
""",
)

manager = Agent(
    name="RCS Revenue Operator",
    model=MODEL,
    instructions=COMMON_RULES + """
You are the operating manager. Your job is to reach the first R10,000 in attributable online revenue
as efficiently as possible, then build toward repeatable monthly revenue. Use specialists rather than
trying to do every task yourself. Prioritize one primary experiment at a time and keep a second experiment
as backup. Produce a concise decision memo containing: selected opportunity, why now, offer, price,
distribution, first 10 actions, metrics, risks, and exactly what requires human approval.
""",
    tools=[
        scout.as_tool(tool_name="research_opportunities", tool_description="Research and save current revenue opportunities."),
        offer_builder.as_tool(tool_name="build_offer", tool_description="Turn an opportunity into a commercial offer."),
        product_factory.as_tool(tool_name="design_product", tool_description="Design the minimum viable product or productized service."),
        lead_agent.as_tool(tool_name="build_lead_plan", tool_description="Design prospecting and outreach for an offer."),
    ],
)
