from pydantic import BaseModel 



class PreCallContextRequest(BaseModel):
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