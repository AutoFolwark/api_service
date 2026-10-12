from auction_api.api import AuctionApiClient


async def get_auction_api_service() -> AuctionApiClient:
    return AuctionApiClient()
