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
    Transform a raw upstream lead payload into the structured context
    payload consumed by the voice module for prompt injection and the
    personalized greeting.

    Two shapes are understood, and can be mixed (our own fields take
    priority when both are present):

    - Our own hand-built brief: lead_name, company_name, role, industry,
      use_case, phone_number, lead_summary, product_details,
      lead_enriched_data, company_input_data.
    - LeadForge's lead-search response, forwarded here verbatim: firstName/
      lastName/fullName, jobTitle, phone, location{city,state,country},
      company{name,domain,website,linkedinUrl}. LeadForge has no
      industry/use_case/lead_summary equivalent, so those stay blank unless
      also supplied via the fields above.
    """
    enriched = raw.get("lead_enriched_data") or {}
    company_input = raw.get("company_input_data") or {}
    leadforge_company = raw.get("company") or {}
    leadforge_location = raw.get("location") or {}
    sources = (raw, enriched, company_input)

    def pick(*keys: str, default: str = "") -> str:
        # String values only — `company` on a LeadForge-shaped payload is a
        # nested {name, domain, ...} object, not the plain string this was
        # originally written for, and would otherwise win over the
        # leadforge_company.get("name") fallback below.
        for src in sources:
            for key in keys:
                value = src.get(key)
                if isinstance(value, str) and value:
                    return value
        return default

    leadforge_name = raw.get("fullName") or " ".join(
        part for part in (raw.get("firstName"), raw.get("lastName")) if part
    )
    leadforge_location_str = ", ".join(
        part for part in (
            leadforge_location.get("city"),
            leadforge_location.get("state"),
            leadforge_location.get("country"),
        )
        if part
    )

    context = {
        "lead_name": pick("lead_name", "name", default="") or leadforge_name or _DEFAULTS["lead_name"],
        "company_name": (
            pick("company_name", "company", default="")
            or leadforge_company.get("name")
            or _DEFAULTS["company_name"]
        ),
        "role": pick("role", "designation", "title", default="") or raw.get("jobTitle") or _DEFAULTS["role"],
        "industry": pick("industry", default=_DEFAULTS["industry"]),
        "use_case": pick("use_case", "relevant_use_case", default=_DEFAULTS["use_case"]),
        "phone_number": raw.get("phone_number") or raw.get("phone") or "",
        "lead_summary": raw.get("lead_summary", ""),
        "product_details": raw.get("product_details", {}),
        "enriched_data": enriched,
        "email": raw.get("email", ""),
        "location": leadforge_location_str,
        "linkedin_url": raw.get("linkedinUrl", ""),
        "company_domain": leadforge_company.get("domain", ""),
        "company_website": leadforge_company.get("website", ""),
        "company_linkedin_url": leadforge_company.get("linkedinUrl", ""),
    }

    missing = [
        field for field in ("lead_name", "company_name")
        if context[field] == _DEFAULTS[field]
    ]
    if missing:
        logger.info(f"Lead context missing fields, using defaults: {missing}")

    logger.info(f"Conditioned lead context for lead={context['lead_name']} company={context['company_name']}")
    return context