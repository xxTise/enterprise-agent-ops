"""IT procurement tools for the IT Agent (watsonx Orchestrate ADK)."""

import json
from pathlib import Path

from ibm_watsonx_orchestrate.agent_builder.tools import tool

CATALOG_FILE = Path(__file__).resolve().parent.parent / "data" / "hardware_catalog.json"


@tool
def order_hardware(quantity: int, model: str) -> str:
    """Prices a laptop order from the hardware catalog and returns the invoice.

    Args:
        quantity (int): Number of laptops to order (must be at least 1).
        model (str): Laptop model name or catalog id, e.g. "Dell Latitude 7450" or "LT-300".

    Returns:
        str: A JSON invoice with model, unit_price, quantity and total_invoice,
            or a JSON error listing the valid models if the model is unknown.
    """
    try:
        qty = int(quantity)
    except (TypeError, ValueError):
        raise ValueError(f"quantity must be an integer, got {quantity!r}")
    if qty < 1:
        raise ValueError("quantity must be at least 1")

    catalog = json.loads(CATALOG_FILE.read_text())
    wanted = str(model).strip().lower()
    for item in catalog["laptops"]:
        if wanted in (item["model"].lower(), item["id"].lower()):
            return json.dumps({
                "id": item["id"],
                "model": item["model"],
                "unit_price": item["unit_price"],
                "quantity": qty,
                "total_invoice": item["unit_price"] * qty,
                "currency": catalog["currency"],
            })

    return json.dumps({
        "status": "error",
        "reason": f"unknown model: {model}",
        "valid_models": [item["model"] for item in catalog["laptops"]],
    })
