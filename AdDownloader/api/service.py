"""FastAPI service exposing AdDownloader metadata and media download workflows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, root_validator, validator

from AdDownloader.adlib_api import AdLibAPI
from AdDownloader.helpers import update_access_token
from AdDownloader.media_download import start_media_download


class DateRange(BaseModel):
    """Simple date range helper for request validation."""

    start: Optional[date] = Field(default=None, alias="min")
    end: Optional[date] = Field(default=None, alias="max")

    @root_validator
    def validate_range(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        start, end = values.get("start"), values.get("end")
        if start and end and start > end:
            raise ValueError("The start date must be before the end date.")
        return values

    class Config:
        allow_population_by_field_name = True


class DownloadRequest(BaseModel):
    """Schema describing the payload required for the download endpoint."""

    access_token: str
    project_name: Optional[str] = None
    ad_reached_countries: Optional[Union[List[str], str]] = None
    date_range: Optional[DateRange] = None
    page_ids: Optional[Union[List[str], str]] = None
    ad_library_ids: Optional[List[str]] = None
    ad_type: str = "ALL"
    fields: Optional[str] = None
    media_limit: Optional[int] = Field(default=None, gt=0)
    media_ad_ids: Optional[List[str]] = None
    random_sample_media: bool = True
    additional_parameters: Dict[str, Any] = Field(default_factory=dict)

    @validator("ad_reached_countries", "page_ids", pre=True)
    def _ensure_list(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @validator("additional_parameters", pre=True, always=True)
    def _default_additional_params(cls, value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return value or {}

    @root_validator
    def _ensure_identifiers(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        page_ids = values.get("page_ids")
        ad_library_ids = values.get("ad_library_ids")
        if not page_ids and not ad_library_ids:
            raise ValueError("Either `page_ids` or `ad_library_ids` must be provided.")
        return values

    class Config:
        anystr_strip_whitespace = True
        extra = "forbid"


app = FastAPI(title="AdDownloader API", version="1.0.0")


def _format_countries(countries: Optional[Union[List[str], str]]) -> str:
    if countries is None:
        return "NL"
    if isinstance(countries, str):
        countries_list = [countries]
    else:
        countries_list = countries
    countries_list = [country.strip().upper() for country in countries_list if country]
    return ",".join(dict.fromkeys(countries_list)) or "NL"


def _as_list(values: Optional[Union[List[str], str]]) -> Optional[List[str]]:
    if values is None:
        return None
    if isinstance(values, str):
        iterable = [values]
    else:
        iterable = values
    processed = [str(value).strip() for value in iterable if str(value).strip()]
    return processed or None


@app.post("/download")
def download_ads(request: DownloadRequest) -> Dict[str, Any]:
    """Download metadata from the Ad Library and optionally fetch creative assets."""

    project_name = request.project_name or datetime.utcnow().strftime("%Y%m%d%H%M%S")

    try:
        api = AdLibAPI(access_token=request.access_token, project_name=project_name)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=400, detail=f"Failed to initialise Ad Library client: {exc}") from exc

    date_min = request.date_range.start.strftime("%Y-%m-%d") if request.date_range and request.date_range.start else "2023-01-01"
    date_max = request.date_range.end.strftime("%Y-%m-%d") if request.date_range and request.date_range.end else datetime.utcnow().strftime("%Y-%m-%d")

    countries = _format_countries(request.ad_reached_countries)
    page_ids = _as_list(request.page_ids)
    search_terms = _as_list(request.ad_library_ids)

    try:
        api.add_parameters(
            fields=request.fields,
            ad_reached_countries=countries,
            ad_delivery_date_min=date_min,
            ad_delivery_date_max=date_max,
            search_page_ids=page_ids,
            search_terms=search_terms,
            ad_type=request.ad_type,
            **request.additional_parameters,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to prepare request parameters: {exc}") from exc

    try:
        data = api.start_download()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to execute download: {exc}") from exc

    if data is None or len(data) == 0:
        raise HTTPException(status_code=404, detail="No ads were returned for the supplied parameters.")

    if "ad_snapshot_url" in data.columns:
        data = update_access_token(data, request.access_token)

    records = jsonable_encoder(data.to_dict(orient="records"))

    media_details: Dict[str, Any] = {
        "ads_requested": 0,
        "ads_succeeded": 0,
        "ads_failed": 0,
        "assets": [],
    }

    if "ad_snapshot_url" in data.columns:
        media_df = data.copy()
        if request.media_ad_ids:
            requested_ids = {str(ad_id) for ad_id in request.media_ad_ids}
            media_df = media_df[media_df["id"].astype(str).isin(requested_ids)]

        if len(media_df) > 0:
            media_limit = request.media_limit or len(media_df)
            random_sample = request.random_sample_media and not request.media_ad_ids
            try:
                media_details = start_media_download(
                    project_name,
                    nr_ads=media_limit,
                    data=media_df,
                    random_sample=random_sample,
                )
            except Exception as exc:  # pragma: no cover - Selenium edge cases
                media_details = {
                    "ads_requested": media_limit,
                    "ads_succeeded": 0,
                    "ads_failed": media_limit,
                    "assets": [],
                    "error": str(exc),
                }

    response_body = {
        "project": {
            "name": project_name,
            "requested_at": datetime.utcnow().isoformat() + "Z",
            "parameters": api.get_parameters(),
        },
        "summary": {
            "total_ads": len(data),
            "media": media_details,
        },
        "ads": records,
    }

    return response_body
