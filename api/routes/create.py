from fastapi import APIRouter

from models.firms_nominatim_models import RequestFirmsCSVDataURL, RequestNominatimSearchURL
from services.firms_nominatim_service import create_firms_csv_urls, create_nominatim_search_url

router = APIRouter(prefix="/create")


@router.post(
    "/nominatim_search_url",
    description="Create Nominatim's search URL based on the queried country code",
    status_code=201,
)
def request_nominatim_search_url(input: RequestNominatimSearchURL):
    return create_nominatim_search_url(input.country_code)


@router.post(
    "/firms_csv_urls",
    description="Create FIRMS CSV Data URL based on inputed country code",
    status_code=201,
)
def request_firms_csv_url(input: RequestFirmsCSVDataURL):
    return create_firms_csv_urls(input.firms_key)
