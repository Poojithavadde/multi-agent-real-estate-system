import json
import logging
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_chroma import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("marketing-intelligence-agent")

app = FastAPI(title="Marketing Intelligence Agent", version="1.0.0")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
INSIGHTS_FILE = DATA_DIR / "insights.jsonl"
PROCESSED_FILE = DATA_DIR / "processed_properties.json"
VECTOR_DIR = DATA_DIR / "chroma_store"


class PropertyPayload(BaseModel):
    property_id: str
    customer_id: str
    address: str
    city: str
    property_type: str
    listing_price: float
    area_sqft: float
    bedrooms: int
    bathrooms: int
    description: str = ""


class InsightQuery(BaseModel):
    property_id: str
    query: str


def _load_processed() -> List[str]:
    if not PROCESSED_FILE.exists():
        return []
    return json.loads(PROCESSED_FILE.read_text(encoding="utf-8"))


def _save_processed(processed: List[str]) -> None:
    PROCESSED_FILE.write_text(json.dumps(processed, indent=2), encoding="utf-8")


def _embedder():
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def _vectordb():
    return Chroma(
        collection_name="property_insights",
        embedding_function=_embedder(),
        persist_directory=str(VECTOR_DIR),
    )


def _chunk_text(text: str, chunk_size: int = 220) -> List[str]:
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i + chunk_size])
    return chunks


def _generate_insight(p: Dict[str, Any]) -> str:
    price_per_sqft = p["listing_price"] / max(p["area_sqft"], 1)
    trend = "stable"
    if price_per_sqft > 350:
        trend = "premium growth micro-market"
    elif price_per_sqft < 150:
        trend = "value-driven buyer market"
    risk = "moderate inventory risk"
    if p["bedrooms"] >= 4 and p["bathrooms"] <= 1:
        risk = "layout risk due to bathroom mismatch"
    opportunity = f"Opportunity for {p['property_type']} buyers in {p['city']}"
    return (
        f"Property {p['property_id']} at {p['address']} shows a {trend}. "
        f"Estimated price per sqft is {price_per_sqft:.2f}. "
        f"Risk signal: {risk}. "
        f"Opportunity indicator: {opportunity}. "
        "Synthetic market comparables suggest demand is strongest for well-priced listings."
    )


@app.get("/.well-known/agent-card.json")
def agent_card():
    return {
        "id": "marketing-intelligence-agent",
        "name": "Marketing Intelligence Agent",
        "version": "1.0.0",
        "protocol": "A2A",
        "capabilities": [
            "analyze_property",
            "generate_market_insights",
            "embed_and_store_insights",
            "rag_retrieval_for_queries",
        ],
        "endpoints": {
            "analyze_property": "/a2a/analyze_property",
            "query_insights": "/a2a/query_insights",
        },
    }


@app.post("/a2a/analyze_property")
def analyze_property(payload: PropertyPayload):
    if payload.listing_price <= 0 or payload.area_sqft <= 0:
        raise HTTPException(status_code=400, detail="Missing or invalid property financial metrics")

    processed = _load_processed()
    if payload.property_id in processed:
        logger.info("Skipping duplicate analysis for %s", payload.property_id)
        return {"status": "skipped", "reason": "duplicate_property", "property_id": payload.property_id}

    insight_text = _generate_insight(payload.dict())
    chunks = _chunk_text(insight_text)
    docs = [f"{payload.property_id} :: {chunk}" for chunk in chunks]
    metadatas = [{"property_id": payload.property_id, "chunk_index": i} for i, _ in enumerate(chunks)]
    ids = [f"{payload.property_id}-chunk-{i}" for i, _ in enumerate(chunks)]

    vectordb = _vectordb()
    vectordb.add_texts(docs, metadatas=metadatas, ids=ids)

    record = {"property_id": payload.property_id, "insight": insight_text, "chunks": len(chunks)}
    with INSIGHTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    processed.append(payload.property_id)
    _save_processed(processed)
    logger.info("Analyzed and embedded property: %s", payload.property_id)
    return {"status": "success", "property_id": payload.property_id, "chunks_stored": len(chunks)}


@app.post("/a2a/query_insights")
def query_insights(request: InsightQuery):
    vectordb = _vectordb()
    query = f"{request.property_id} {request.query}"
    matches = vectordb.similarity_search(query, k=4)
    if not matches:
        return {"status": "success", "answer": "No insight records found for the requested context.", "sources": []}

    # Keep sources focused on the requested property and avoid duplicate fragments.
    snippets = [m.page_content for m in matches]
    filtered = [s for s in snippets if s.startswith(f"{request.property_id} :: ")] or snippets
    deduped = list(dict.fromkeys(filtered))

    cleaned = []
    for s in deduped:
        cleaned.append(s.split("::", 1)[1].strip() if "::" in s else s.strip())

    answer = "\n".join(f"- {line}" for line in cleaned)
    logger.info("[marketing] Insight query served for property_id=%s with %d unique chunks", request.property_id, len(cleaned))
    return {"status": "success", "answer": answer, "sources": deduped}
