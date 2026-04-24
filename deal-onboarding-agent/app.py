import json
import uuid
import os
import logging
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("deal-onboarding-agent")

app = FastAPI(title="Deal Onboarding Agent", version="1.0.0")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DEALS_FILE = DATA_DIR / "deals.jsonl"
MARKETING_AGENT_URL = os.getenv("MARKETING_AGENT_URL", "http://localhost:8003")


class DealPayload(BaseModel):
    customer_id: str = Field(min_length=5)
    address: str = Field(min_length=5)
    city: str = Field(min_length=2)
    property_type: str = Field(min_length=2)
    listing_price: float
    area_sqft: float
    bedrooms: int
    bathrooms: int
    description: Optional[str] = None


@app.get("/.well-known/agent-card.json")
def agent_card():
    return {
        "id": "deal-onboarding-agent",
        "name": "Deal Onboarding Agent",
        "version": "1.0.0",
        "protocol": "A2A",
        "capabilities": [
            "validate_property_data",
            "normalize_property_data",
            "persist_property_data",
            "trigger_marketing_agent",
        ],
        "endpoints": {"onboard_deal": "/a2a/onboard_deal"},
    }


@app.post("/a2a/onboard_deal")
def onboard_deal(payload: DealPayload):
    if payload.listing_price <= 0 or payload.area_sqft <= 0:
        raise HTTPException(status_code=400, detail="Price and area must be greater than zero")
    if payload.bedrooms < 0 or payload.bathrooms < 0:
        raise HTTPException(status_code=400, detail="Bedroom and bathroom counts cannot be negative")

    property_id = f"PROP-{uuid.uuid4().hex[:10].upper()}"
    record = {
        "property_id": property_id,
        "customer_id": payload.customer_id,
        "address": payload.address.strip(),
        "city": payload.city.strip().title(),
        "property_type": payload.property_type.strip().lower(),
        "listing_price": payload.listing_price,
        "area_sqft": payload.area_sqft,
        "bedrooms": payload.bedrooms,
        "bathrooms": payload.bathrooms,
        "description": payload.description or "",
    }

    with DEALS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    logger.info("Deal onboarded: %s", property_id)

    try:
        m_response = requests.post(
            f"{MARKETING_AGENT_URL}/a2a/analyze_property",
            json=record,
            timeout=20,
        )
        m_response.raise_for_status()
        marketing_result = m_response.json()
    except Exception as exc:
        logger.exception("Failed to trigger marketing agent: %s", exc)
        raise HTTPException(status_code=502, detail="Deal stored, but marketing trigger failed")

    return {
        "status": "success",
        "property_id": property_id,
        "property": record,
        "marketing_trigger": marketing_result,
    }
