from pydantic import BaseModel


class LeadForgeLocation(BaseModel):
    city: str | None = None
    state: str | None = None
    country: str | None = None


class LeadForgeCompany(BaseModel):
    id: str | None = None
    name: str | None = None
    website: str | None = None
    domain: str | None = None
    linkedinUrl: str | None = None


class PreCallContextRequest(BaseModel):
    # Hand-built brief, as sent by the browser BriefForm or any caller that
    # already knows our field names.
    lead_name: str | None = None
    company_name: str | None = None
    role: str | None = None
    industry: str | None = None
    use_case: str | None = None
    phone_number: str | None = None
    lead_summary: str | None = None
    product_details: dict | None = None
    lead_enriched_data: dict | None = None
    company_input_data: dict | None = None

    # LeadForge lead-search response fields. LeadForge's own response
    # payload is expected to be forwarded here verbatim as the request body
    # when a call is triggered straight off a LeadForge search result —
    # condition_lead_context() remaps these into the fields above. LeadForge
    # has no industry/use_case/lead_summary equivalents, so those stay blank
    # unless the caller also supplies them.
    id: str | None = None
    firstName: str | None = None
    lastName: str | None = None
    fullName: str | None = None
    jobTitle: str | None = None
    linkedinUrl: str | None = None
    email: str | None = None
    phone: str | None = None
    location: LeadForgeLocation | None = None
    company: LeadForgeCompany | None = None