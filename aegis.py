# aegis.py — All communication with the Aegis Online reseller API.
#
# The Aegis API uses HMAC-SHA256 signatures for authentication.
# Every request needs:
#   - X-API-KEY: your API key
#   - X-TIMESTAMP: current Unix timestamp (as string)
#   - X-SIGNATURE: HMAC of "METHOD|PATH|TIMESTAMP|BODY" signed with your secret
#
# This module handles all of that automatically so the rest of the bot
# just calls simple functions like `create_order(...)` or `get_balance()`.

import time
import json
import hmac
import hashlib
import aiohttp
import config as cfg


def _sign(method: str, path: str, body_str: str) -> tuple[dict, str]:
    """
    Build the HMAC signature and return the headers + timestamp.
    Returns (headers_dict, timestamp_str).
    """
    timestamp = str(int(time.time()))
    string_to_sign = f"{method}|{path}|{timestamp}|{body_str}"
    signature = hmac.new(
        cfg.AEGIS_API_SECRET.encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": cfg.AEGIS_API_KEY,
        "X-TIMESTAMP": timestamp,
        "X-SIGNATURE": signature,
    }
    return headers, timestamp


async def create_order(category: int, service: int, quantity: int, buyer_name: str) -> dict:
    """
    Place an order on the Aegis API.

    Returns the full parsed JSON response. On success it will contain:
        status, message, data.order_id, data.keys (list), data.balance_before,
        data.balance_after, data.unit_price, data.total_price, data.created_at

    Raises an Exception with a readable message on HTTP or API-level errors.
    """
    path = "/api/v1/order/create.php"
    url = f"{cfg.AEGIS_BASE_URL}{path}"

    body_obj = {
        "category": category,
        "service": service,
        "data": buyer_name,
        "quantity": quantity,
    }
    body_str = json.dumps(body_obj, separators=(",", ":"))
    headers, _ = _sign("POST", path, body_str)

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=body_str) as resp:
            try:
                result = await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                raise Exception(f"Non-JSON response (HTTP {resp.status}): {text[:200]}")

            if resp.status != 200:
                msg = result.get("message", f"HTTP {resp.status}")
                raise Exception(msg)

            if not result.get("status"):
                msg = result.get("message", "Unknown API error")
                data = result.get("data", {})
                if "balance" in data and "required" in data:
                    raise Exception(
                        f"{msg}\n"
                        f"Your Aegis balance: **{data['balance']}**  •  Required: **{data['required']}**"
                    )
                raise Exception(msg)

            return result


async def get_balance() -> dict | None:
    """
    Fetch the current account balance from the Aegis API.
    Returns the parsed JSON or None on failure.
    """
    path = "/api/v1/balance.php"
    url = f"{cfg.AEGIS_BASE_URL}{path}"

    # GET request — empty body
    body_str = ""
    headers, _ = _sign("GET", path, body_str)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json(content_type=None)
                return result if result.get("status") else None
    except Exception as e:
        print(f"[Aegis] get_balance failed: {e}")
        return None


async def list_services() -> list[dict]:
    """
    Fetch the list of available services from the Aegis API.
    Returns a list of service dicts, or [] on failure.
    """
    path = "/api/v1/service/list.php"
    url = f"{cfg.AEGIS_BASE_URL}{path}"
    body_str = ""
    headers, _ = _sign("GET", path, body_str)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return []
                result = await resp.json(content_type=None)
                if not result.get("status"):
                    return []
                # The service list may be nested under data or at root level.
                data = result.get("data") or result.get("services") or []
                return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[Aegis] list_services failed: {e}")
        return []
