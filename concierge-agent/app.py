import os
import uuid
import logging
from typing import Dict, Any, List, TypedDict

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from dotenv import load_dotenv

try:
    from langchain_openai import ChatOpenAI
except Exception:  # pragma: no cover
    ChatOpenAI = None


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("concierge-agent")

# Load local .env values if present (safe local configuration only).
load_dotenv()

app = FastAPI(title="Concierge Agent", version="1.0.0")


class UserRequest(BaseModel):
    customer: Dict[str, Any]
    property: Dict[str, Any]
    question: str


class WorkflowState(TypedDict, total=False):
    request_id: str
    customer_payload: Dict[str, Any]
    property_payload: Dict[str, Any]
    user_question: str
    discovered_agents: Dict[str, Dict[str, Any]]
    customer_result: Dict[str, Any]
    deal_result: Dict[str, Any]
    insights_result: Dict[str, Any]
    final_response: str


def _agent_urls() -> List[str]:
    return [
        os.getenv("CUSTOMER_AGENT_URL", "http://localhost:8001"),
        os.getenv("DEAL_AGENT_URL", "http://localhost:8002"),
        os.getenv("MARKETING_AGENT_URL", "http://localhost:8003"),
    ]


def discover_agents(_: WorkflowState) -> WorkflowState:
    discovered = {}
    for base_url in _agent_urls():
        try:
            url = f"{base_url}/.well-known/agent-card.json"
            response = requests.get(url, timeout=8)
            response.raise_for_status()
            card = response.json()
            discovered[card["id"]] = {"base_url": base_url, "agent_card": card}
            logger.info("[concierge:discover] Discovered agent %s at %s", card["id"], base_url)
        except Exception as exc:
            logger.warning("[concierge:discover] Failed to discover from %s: %s", base_url, exc)
    if not discovered:
        raise HTTPException(status_code=503, detail="No agents discovered")
    return {"discovered_agents": discovered}


def onboard_customer(state: WorkflowState) -> WorkflowState:
    agents = state["discovered_agents"]
    customer_agent = agents.get("customer-onboarding-agent")
    if not customer_agent:
        raise HTTPException(status_code=503, detail="Customer agent not available")
    response = requests.post(
        f"{customer_agent['base_url']}/a2a/onboard_customer",
        json=state["customer_payload"],
        timeout=12,
    )
    response.raise_for_status()
    logger.info("[concierge:route] Customer onboarding completed via %s", customer_agent["base_url"])
    return {"customer_result": response.json()}


def onboard_deal(state: WorkflowState) -> WorkflowState:
    agents = state["discovered_agents"]
    deal_agent = agents.get("deal-onboarding-agent")
    if not deal_agent:
        raise HTTPException(status_code=503, detail="Deal agent not available")
    payload = dict(state["property_payload"])
    payload["customer_id"] = state["customer_result"]["customer_id"]
    response = requests.post(
        f"{deal_agent['base_url']}/a2a/onboard_deal",
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    logger.info("[concierge:route] Deal onboarding completed via %s", deal_agent["base_url"])
    return {"deal_result": response.json()}


def query_marketing(state: WorkflowState) -> WorkflowState:
    agents = state["discovered_agents"]
    marketing_agent = agents.get("marketing-intelligence-agent")
    if not marketing_agent:
        raise HTTPException(status_code=503, detail="Marketing agent not available")
    response = requests.post(
        f"{marketing_agent['base_url']}/a2a/query_insights",
        json={
            "property_id": state["deal_result"]["property_id"],
            "query": state["user_question"],
        },
        timeout=20,
    )
    response.raise_for_status()
    logger.info("[concierge:route] Marketing query completed via %s", marketing_agent["base_url"])
    return {"insights_result": response.json()}


def generate_final_response(state: WorkflowState) -> WorkflowState:
    context = (
        f"Customer Result: {state['customer_result']}\n"
        f"Deal Result: {state['deal_result']}\n"
        f"RAG Insights: {state['insights_result']}\n"
        f"User Question: {state['user_question']}"
    )
    prompt = (
        "Create a concise final response for the user using the provided multi-agent context.\n"
        "Include trend, risk, and opportunity in a clear format.\n\n"
        + context
    )

    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()

    try:
        logger.info("[concierge:llm] Generating final response using provider=%s", provider)
        if provider == "huggingface":
            hf_token = os.getenv("HF_API_TOKEN")
            hf_model = os.getenv("HF_MODEL", "google/flan-t5-large")
            hf_api_url = os.getenv("HF_API_URL", "").strip()
            if not hf_token:
                raise HTTPException(
                    status_code=503,
                    detail="HF_API_TOKEN is required when LLM_PROVIDER=huggingface.",
                )

            endpoint = hf_api_url or f"https://router.huggingface.co/hf-inference/models/{hf_model}"
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {hf_token}"},
                json={
                    "inputs": prompt,
                    "parameters": {"max_new_tokens": 220, "temperature": 0.2},
                    "options": {"wait_for_model": False, "use_cache": True},
                },
                timeout=45,
            )
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Hugging Face generation failed: {response.status_code} {response.text}",
                )

            payload = response.json()
            if isinstance(payload, dict) and payload.get("error"):
                estimated = payload.get("estimated_time")
                if estimated is not None:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "Hugging Face model is loading. "
                            f"Estimated time: {estimated} seconds. Retry shortly."
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail=f"Hugging Face generation failed: {payload.get('error')}",
                )
            if isinstance(payload, list) and payload and "generated_text" in payload[0]:
                text = payload[0]["generated_text"].strip()
            elif isinstance(payload, dict) and "generated_text" in payload:
                text = str(payload["generated_text"]).strip()
            else:
                raise HTTPException(
                    status_code=502,
                    detail="Hugging Face response format unexpected; no generated text found.",
                )
        else:
            if not ChatOpenAI:
                raise HTTPException(
                    status_code=503,
                    detail="LLM provider unavailable. Install and configure langchain-openai.",
                )

            if provider == "groq":
                groq_key = os.getenv("GROQ_API_KEY")
                if not groq_key:
                    raise HTTPException(
                        status_code=503,
                        detail="GROQ_API_KEY is required when LLM_PROVIDER=groq.",
                    )
                llm = ChatOpenAI(
                    model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                    temperature=0.2,
                    openai_api_key=groq_key,
                    openai_api_base="https://api.groq.com/openai/v1",
                )
            else:
                if not os.getenv("OPENAI_API_KEY"):
                    raise HTTPException(
                        status_code=503,
                        detail="OPENAI_API_KEY is required when LLM_PROVIDER=openai.",
                    )
                llm = ChatOpenAI(model=os.getenv("CONCIERGE_MODEL", "gpt-4o-mini"), temperature=0.2)
            text = llm.invoke(prompt).content
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[concierge:llm] Final response generation failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail="Final LLM response generation failed. Strict mode requires successful LLM output.",
        )

    if not text:
        raise HTTPException(
            status_code=502,
            detail="LLM returned empty final response in strict mode.",
        )
    return {"final_response": text}


def build_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("discover_agents", discover_agents)
    graph.add_node("onboard_customer", onboard_customer)
    graph.add_node("onboard_deal", onboard_deal)
    graph.add_node("query_marketing", query_marketing)
    graph.add_node("generate_final_response", generate_final_response)

    graph.set_entry_point("discover_agents")
    graph.add_edge("discover_agents", "onboard_customer")
    graph.add_edge("onboard_customer", "onboard_deal")
    graph.add_edge("onboard_deal", "query_marketing")
    graph.add_edge("query_marketing", "generate_final_response")
    graph.add_edge("generate_final_response", END)
    return graph.compile(checkpointer=MemorySaver())


WORKFLOW = build_graph()


@app.get("/.well-known/agent-card.json")
def agent_card():
    return {
        "id": "concierge-agent",
        "name": "Concierge Orchestrator Agent",
        "version": "1.0.0",
        "protocol": "A2A",
        "capabilities": [
            "agent_discovery",
            "request_routing",
            "workflow_orchestration",
            "response_aggregation",
        ],
        "endpoints": {"handle_request": "/a2a/handle_request"},
    }


@app.post("/a2a/handle_request")
def handle_request(request: UserRequest):
    request_id = str(uuid.uuid4())
    state: WorkflowState = {
        "request_id": request_id,
        "customer_payload": request.customer,
        "property_payload": request.property,
        "user_question": request.question,
    }
    config = {"configurable": {"thread_id": request_id}}
    final_state = WORKFLOW.invoke(state, config=config)
    return {
        "request_id": request_id,
        "status": "completed",
        "response": final_state["final_response"],
        "customer_result": final_state["customer_result"],
        "deal_result": final_state["deal_result"],
        "insights_result": final_state["insights_result"],
    }
