import os
import re
import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Cho phép mọi origin gọi API
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_shop_item_ids(url: str):
    match = re.search(r'/product/(\d+)/(\d+)', url)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r'i\.(\d+)\.(\d+)', url)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r'/opaanlp/(\d+)/(\d+)', url)
    if match:
        return match.group(1), match.group(2)
    return None, None

def resolve_short_link(short_url: str):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'vi-VN,vi;q=0.9',
    }
    try:
        session = requests.Session()
        session.headers.update(headers)
        resp = session.get(short_url, allow_redirects=True, timeout=20)
        return resp.url
    except Exception:
        return None

@app.get("/api/resolve")
def resolve(url: str = Query(...)):
    final_url = resolve_short_link(url)
    if not final_url:
        return {"error": "Không thể phân giải link"}
    shop_id, item_id = extract_shop_item_ids(final_url)
    if not item_id:
        return {"error": "Không tìm thấy item_id", "resolved_url": final_url}
    return {
        "item_id": item_id,
        "shop_id": shop_id,
        "resolved_url": final_url
    }
