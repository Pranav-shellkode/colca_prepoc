import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "lead_name": "there",
    "company_name": "your company",
    "role": "",
    "industry": "",
    "use_case": "",
}


def condition_lead_context(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Transform a raw upstream lead payload (company input data, lead enriched
    data, lead summary, product details) into the structured context payload
    consumed by the voice module for prompt injection and the personalized
    greeting.
    """
    enriched = raw.get("lead_enriched_data") or {}
    company_input = raw.get("company_input_data") or {}
    sources = (raw, enriched, company_input)

    def pick(*keys: str, default: str = "") -> str:
        for src in sources:
            for key in keys:
                value = src.get(key)
                if value:
                    return value
        return default

    context = {
        "lead_name": pick("lead_name", "name", default=_DEFAULTS["lead_name"]),
        "company_name": pick("company_name", "company", default=_DEFAULTS["company_name"]),
        "role": pick("role", "designation", "title", default=_DEFAULTS["role"]),
        "industry": pick("industry", default=_DEFAULTS["industry"]),
        "use_case": pick("use_case", "relevant_use_case", default=_DEFAULTS["use_case"]),
        "phone_number": raw.get("phone_number", ""),
        "lead_summary": raw.get("lead_summary", ""),
        "product_details": raw.get("product_details", {}),
        "enriched_data": enriched,
    }

    missing = [
        field for field in ("lead_name", "company_name")
        if context[field] == _DEFAULTS[field]
    ]
    if missing:
        logger.info(f"Lead context missing fields, using defaults: {missing}")

    logger.info(f"Conditioned lead context for lead={context['lead_name']} company={context['company_name']}")
    return context