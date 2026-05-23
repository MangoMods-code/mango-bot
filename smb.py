# smb.py — SMBPanel API module.
# All requests are POST to https://smbpanel.net/api/v2
# Authentication is via API key in the request body.

import aiohttp
import config as cfg

SMB_URL = "https://smbpanel.net/api/v2"


async def _post(payload: dict) -> dict:
    """Send a POST request to the SMB API with the given payload."""
    payload["key"] = cfg.SMB_API_KEY
    async with aiohttp.ClientSession() as session:
        async with session.post(SMB_URL, data=payload) as resp:
            try:
                result = await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                raise Exception(f"Non-JSON response (HTTP {resp.status}): {text[:200]}")
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}: {result}")
            return result


async def get_balance() -> dict:
    """Get current SMB account balance.
    Returns: {"balance": "100.84", "currency": "USD"}
    """
    return await _post({"action": "balance"})


async def list_services() -> list:
    """Fetch the full service list from SMB.
    Returns a list of service dicts.
    """
    result = await _post({"action": "services"})
    return result if isinstance(result, list) else []


async def add_order(service_id: int, link: str, quantity: int) -> dict:
    """Place an order.
    Returns: {"order": 23501}
    """
    return await _post({
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity,
    })


async def get_order_status(order_id: int) -> dict:
    """Get the status of a single order.
    Returns: {"charge": "0.27", "start_count": "3572", "status": "Partial", ...}
    """
    return await _post({"action": "status", "order": order_id})


async def cancel_orders(order_ids: list[int]) -> list:
    """Cancel one or more orders."""
    return await _post({"action": "cancel", "orders": ",".join(str(i) for i in order_ids)})
