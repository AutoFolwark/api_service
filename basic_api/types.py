from pydantic import BaseModel, HttpUrl


class BaseClientIn(BaseModel):
    api_key: str
    header_name: str = "api-key"
    base_url: HttpUrl
