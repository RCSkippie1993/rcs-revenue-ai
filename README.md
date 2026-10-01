# RCS Revenue AI — MVP

A code-first AI revenue operator built on the OpenAI Agents SDK. It researches current opportunities, builds offers, designs products, creates lead-generation plans and stores an opportunity pipeline. External actions are deliberately gated for human approval.

## What v1 does

- Live web research through the OpenAI hosted web-search tool
- Opportunity scoring and persistence to SQLite
- Specialist agents for opportunity research, offers, products and leads
- Manager agent coordinating the specialists
- Human-approval gate for external actions
- Streamlit dashboard for opportunities, approvals and logged revenue

## Safety / commercial controls

The system does **not** guarantee income. It is designed to run experiments and measure actual results. It must not autonomously spend money, enter contracts, publish professional advice, change live prices, or send outreach without approval.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.run
```

Dashboard:

```bash
streamlit run dashboard.py
```

## Deploy on Render

Required secret: `OPENAI_API_KEY`.

The deployed dashboard includes a **Run Revenue Sprint 001** button. External actions remain approval-gated.

> v1 uses SQLite. For durable production history across redeploys, attach a persistent disk or migrate to Postgres in a later iteration.
