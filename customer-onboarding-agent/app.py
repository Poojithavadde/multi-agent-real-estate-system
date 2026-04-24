import json
import uuid
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("customer-onboarding-agent")

app = FastAPI(title="Customer Onboarding Agent", version="1.0.0")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
CUSTOMER_FILE = DATA_DIR / "customers.jsonl"


class CustomerPayload(BaseModel):
    full_name: str = Field(min_length=2)
    email: EmailStr
    phone: str = Field(min_length=7)
    budget: float
    preferred_location: str = Field(min_length=2)
    notes: Optional[str] = None


@app.get("/.well-known/agent-card.json")
def agent_card():
    return {
        "id": "customer-onboarding-agent",
        "name": "Customer Onboarding Agent",
        "version": "1.0.0",
        "protocol": "A2A",
        "capabilities": [
            "validate_customer_input",
            "structure_customer_data",
            "persist_customer_data",
            "return_customer_id",
        ],
        "endpoints": {"onboard_customer": "/a2a/onboard_customer"},
    }


@app.post("/a2a/onboard_customer")
def onboard_customer(payload: CustomerPayload):
    if payload.budget <= 0:
        raise HTTPException(status_code=400, detail="Budget must be greater than zero")
    if payload.budget > 100000000:
        raise HTTPException(status_code=400, detail="Budget exceeds allowed range")

    customer_id = f"CUST-{uuid.uuid4().hex[:10].upper()}"
    record = {"customer_id": customer_id, **payload.dict()}

    with CUSTOMER_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    logger.info("Customer onboarded: %s", customer_id)
    return {"status": "success", "customer_id": customer_id, "customer": record}
