import re
import unicodedata

from pydantic_core import PydanticCustomError

from auction_api.utils import AuctionApiUtils

# Must stay in lockstep with frontend/utils/lotUrl.js. The lot page redirects
# unless the requested path equals buildLotPath, so sitemap URLs have to match.
_COMBINING_MARKS = re.compile(r"[\u0300-\u036f]")
_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")


def slug_part(value: object) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = _COMBINING_MARKS.sub("", text)
    text = _NON_ALNUM.sub("-", text)
    return text.strip("-")


def lot_slug(
    year: object,
    make: object,
    model: object,
    vin: object,
) -> str:
    parts = [slug_part(part) for part in (year, make, model, vin)]
    return "-".join(part for part in parts if part) or "lot"


def lot_site_name(base_site: object, site: object) -> str | None:
    if base_site:
        name = str(base_site).strip().lower()
        if name == "all":
            return None
        if name:
            return name
    if site is None or site == "":
        return None
    try:
        name = AuctionApiUtils.num_to_auction_name(int(site))
    except (PydanticCustomError, TypeError, ValueError):
        return None
    if name == "all":
        return None
    return name


def lot_path(
    lot_id: object,
    base_site: object,
    site: object,
    year: object,
    make: object,
    model: object,
    vin: object,
) -> str | None:
    site_name = lot_site_name(base_site, site)
    if site_name is None or lot_id is None:
        return None
    lot_text = str(lot_id).strip()
    if not lot_text.isdigit():
        return None
    # BasicLot.lot_id is an int, so the frontend drops leading zeros.
    normalized_id = str(int(lot_text))
    return f"/lot/{site_name}/{normalized_id}/{lot_slug(year, make, model, vin)}"
