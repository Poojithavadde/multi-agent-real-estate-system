# Federated Multi-Agent Real Estate System (A2A)

This implementation follows the task requirements for a federated multi-agent real estate platform using A2A communication, LangGraph orchestration, RAG memory, persistence, and observability logging.

## Repositories (Folders)

1. `concierge-agent`
2. `customer-onboarding-agent`
3. `deal-onboarding-agent`
4. `marketing-intelligence-agent`
5. `shared-utils`

Each agent is independently deployable.

## Architecture Explanation

- **Concierge Agent (Orchestrator)**:
  - Discovers agents dynamically via `/.well-known/agent-card.json`
  - Routes requests to specialized agents
  - Runs a LangGraph StateGraph workflow:
    - `Discover -> Customer Onboarding -> Deal Onboarding -> Marketing Query -> Final Response`
  - Uses LangGraph `MemorySaver` checkpointing
  - Aggregates all outputs into one final response

- **Customer Onboarding Agent**:
  - Validates customer input fields
  - Enforces budget range checks
  - Stores customer records in persistent JSONL storage
  - Returns a unique `customer_id`

- **Deal Onboarding Agent**:
  - Validates and normalizes property data
  - Persists property data in JSONL storage
  - Returns unique `property_id`
  - Automatically triggers Marketing Intelligence Agent after successful onboarding

- **Marketing Intelligence Agent**:
  - Prevents duplicate processing of the same property
  - Generates market insights (trend, risk, opportunity)
  - Chunks insight text
  - Creates embeddings using HuggingFace sentence-transformers
  - Stores embeddings in ChromaDB (persistent directory)
  - Exposes RAG query endpoint for downstream retrieval

## A2A Communication

- Protocol style: REST-based A2A endpoints
- Every agent provides:
  - Agent Card endpoint: `/.well-known/agent-card.json`
  - A2A function endpoints under `/a2a/...`

## Tech Stack Mapping

- Orchestration: LangGraph (`StateGraph`)
- Protocol: A2A (Agent-to-Agent via REST)
- Framework: LangChain + FastAPI
- Vector Database: ChromaDB
- Embedding Model: HuggingFace (`all-MiniLM-L6-v2`)
- LLM: OpenAI (optional, used by concierge when `OPENAI_API_KEY` is available)
- Persistence: File-based JSON/JSONL
- Checkpointing: LangGraph `MemorySaver`
- Logging: Python standard logging in every service

## Setup Instructions

From root folder:

### 1) Create and activate Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) Install dependencies per agent

```powershell
pip install -r .\customer-onboarding-agent\requirements.txt
pip install -r .\deal-onboarding-agent\requirements.txt
pip install -r .\marketing-intelligence-agent\requirements.txt
pip install -r .\concierge-agent\requirements.txt
```

### 3) Optional environment variables

```powershell
$env:LLM_PROVIDER="huggingface"
$env:HF_API_TOKEN="your_hf_token_here"
$env:HF_MODEL="google/flan-t5-large"

$env:OPENAI_API_KEY="your_key_here"
$env:CUSTOMER_AGENT_URL="http://localhost:8001"
$env:DEAL_AGENT_URL="http://localhost:8002"
$env:MARKETING_AGENT_URL="http://localhost:8003"
```

Notes:
- Set `LLM_PROVIDER=huggingface` to use Hugging Face Inference API for Concierge final response generation.
- Set `LLM_PROVIDER=groq` with `GROQ_API_KEY` (and optional `GROQ_MODEL`) to use Groq.
- Set `LLM_PROVIDER=openai` to use OpenAI.

### 4) Recommended secure local `.env` setup (Concierge)

```powershell
copy .env.example .env
```

Then edit `.env` and set your real `OPENAI_API_KEY` locally.  
`concierge-agent/app.py` loads `.env` automatically using `python-dotenv`.

## Execution Steps

Run each service in separate terminals:

### One-command startup (PowerShell)

From project root:

```powershell
.\run-all.ps1
```

This opens separate PowerShell windows and starts all four agents with the verified ports.

### Terminal 1 - Customer Agent

```powershell
cd customer-onboarding-agent
python -m uvicorn app:app --host 0.0.0.0 --port 8101 --reload
```

### Terminal 2 - Deal Agent

```powershell
cd deal-onboarding-agent
$env:MARKETING_AGENT_URL="http://127.0.0.1:8103"
python -m uvicorn app:app --host 0.0.0.0 --port 8102 --reload
```

### Terminal 3 - Marketing Agent

```powershell
cd marketing-intelligence-agent
python -m uvicorn app:app --host 0.0.0.0 --port 8103 --reload
```

### Terminal 4 - Concierge Agent

```powershell
cd concierge-agent
$env:CUSTOMER_AGENT_URL="http://127.0.0.1:8101"
$env:DEAL_AGENT_URL="http://127.0.0.1:8102"
$env:MARKETING_AGENT_URL="http://127.0.0.1:8103"
python -m uvicorn app:app --host 0.0.0.0 --port 8104 --reload
```

If you configured `.env`, you can run Concierge with:

```powershell
cd concierge-agent
python -m uvicorn app:app --host 0.0.0.0 --port 8214 --reload
```

## Sample Test Cases

### 1) End-to-end workflow via Concierge

```powershell
curl -X POST "http://127.0.0.1:8104/a2a/handle_request" `
  -H "Content-Type: application/json" `
  -d '{
    "customer": {
      "full_name": "Asha Mehta",
      "email": "asha@example.com",
      "phone": "9876543210",
      "budget": 120000,
      "preferred_location": "Austin",
      "notes": "Wants good rental upside"
    },
    "property": {
      "address": "214 River Rd",
      "city": "Austin",
      "property_type": "condo",
      "listing_price": 115000,
      "area_sqft": 820,
      "bedrooms": 2,
      "bathrooms": 2,
      "description": "Close to metro and tech hub"
    },
    "question": "What are the key risks and opportunities for this listing?"
  }'
```

Expected:
- Concierge discovers agents
- Customer onboarding returns `customer_id`
- Deal onboarding returns `property_id`
- Deal agent auto-triggers marketing analysis
- Marketing insights are stored in ChromaDB and retrieved via query
- Concierge returns aggregated final response

Note:
- If `8000-8003` are already in use on your machine, use the `8101-8104` ports above.

### 2) Customer validation error

Send customer payload with negative budget and verify HTTP 400 from customer agent.

### 3) Duplicate marketing processing prevention

Call marketing analysis twice for same `property_id` and verify second call is `status=skipped`.

## Deliverable Checklist Coverage

- Concierge Agent: implemented
- Deal Onboarding Agent (A2A Server): implemented
- Marketing Intelligence Agent (A2A Server): implemented
- Customer Onboarding Agent (A2A Server): implemented
- Valid Agent Cards for all agents: implemented (`agent_card.json` + endpoint)
- Shared utilities: included (`shared-utils`)
- README with setup, execution, tests, architecture: included
