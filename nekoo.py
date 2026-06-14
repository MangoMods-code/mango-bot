# nekoo.py — Nekoo Reseller API module.
# Base URL: https://apis.nekoo.eu.org/api/v1
# Auth: X-API-Key header

import aiohttp
import config as cfg

BASE = "https://apis.nekoo.eu.org/api/v1"


async def _get(path: str, params: dict = None) -> dict:
    headers = {"X-API-Key": cfg.NEKOO_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE}{path}", headers=headers, params=params) as resp:
            data = await resp.json(content_type=None)
            if not data.get("ok"):
                raise Exception(data.get("error", "unknown_error") + (f": {data['detail']}" if data.get("detail") else ""))
            return data


async def _post(path: str, body: dict) -> dict:
    headers = {"X-API-Key": cfg.NEKOO_API_KEY, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{BASE}{path}", headers=headers, json=body) as resp:
            data = await resp.json(content_type=None)
            if not data.get("ok"):
                raise Exception(data.get("error", "unknown_error") + (f": {data['detail']}" if data.get("detail") else ""))
            return data


async def get_me() -> dict:
    """Get account profile and balance."""
    return await _get("/me")


async def get_plans(device: str = None) -> list:
    """Get available plans. Optionally filter by device: 'iphone' or 'ipad'."""
    params = {"device": device} if device else None
    data = await _get("/plans", params=params)
    return data.get("plans", [])


async def register(udid: str, plan_id: str) -> dict:
    """Register a certificate for a UDID. Returns full cert data including base64 files."""
    return await _post("/register", {"udid": udid, "plan": plan_id})


async def get_certificate(udid: str = None, certificate_id: str = None) -> dict:
    """Retrieve certificate data by UDID or certificate ID."""
    if not udid and not certificate_id:
        raise ValueError("Must provide either udid or certificate_id")
    params = {}
    if udid:
        params["udid"] = udid
    if certificate_id:
        params["certificate_id"] = certificate_id
    return await _get("/certificate", params=params)


async def get_usage(limit: int = 50) -> dict:
    """Get usage history and stats."""
    return await _get("/usage", params={"limit": limit})
