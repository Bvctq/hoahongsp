import os
import re
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Shopee Affiliate Extractor")

class LinkRequest(BaseModel):
    url: str

def resolve_short_url(short_url: str) -> str:
    """Mẹo Bypass: Chặn không cho bẻ hướng tự động để húp cái Location header luôn"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }
        # Đặt allow_redirects=False để lấy ngay header bẻ hướng trước khi bị chặn
        response = requests.get(short_url, headers=headers, allow_redirects=False, timeout=10)
        
        if response.status_code in [301, 302] and "Location" in response.headers:
            return response.headers["Location"]
        
        return response.url
    except Exception:
        return None

def extract_ids(url: str):
    """Trích xuất shop_id và item_id từ URL gốc bằng Regex"""
    # Pattern 1: product/shop_id/item_id
    match1 = re.search(r'product/(\d+)/(\d+)', url)
    if match1:
        return match1.group(1), match1.group(2)
    
    # Pattern 2: i.shop_id.item_id
    match2 = re.search(r'i\.(\d+)\.(\d+)', url)
    if match2:
        return match2.group(1), match2.group(2)
        
    return None, None

@app.post("/api/extract")
def extract_shopee_info(payload: LinkRequest):
    url_input = payload.url.strip()
    
    # 1. Kiểm tra cấu hình Cookie trên Render trước
    shopee_cookie = os.getenv("SHOPEE_COOKIE", "").strip()
    if not shopee_cookie:
        return {
            "status": "error",
            "msg": "Hệ thống chưa cấu hình biến môi trường SHOPEE_COOKIE trên Render!"
        }
    
    # 2. Giải mã link rút gọn bằng cơ chế chặn redirect
    if "shp.ee" in url_input or "s.shopee.vn" in url_input:
        long_url = resolve_short_url(url_input)
    else:
        long_url = url_input
        
    if not long_url:
        raise HTTPException(status_code=400, detail="Không thể phân giải bẻ hướng link rút gọn Shopee.")
    
    # 3. Trích xuất ID từ link dài
    shop_id, item_id = extract_ids(long_url)
    if not item_id:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy shop_id hoặc item_id. Link phân giải được: {long_url}")

    # 4. Gọi API Affiliate Shopee
    affiliate_api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": shopee_cookie,
        "Referer": "https://affiliate.shopee.vn/",
        "Accept": "application/json, text/plain, */*"
    }
    
    try:
        res = requests.get(affiliate_api_url, headers=headers, timeout=10)
        
        # Nếu dính 403 hoặc 401 thì chắc chắn do Cookie tèo hoặc bị chặn diện rộng
        if res.status_code == 403:
            return {
                "status": "error",
                "msg": "Shopee API chặn lỗi 403. Phiên đăng nhập (Cookie) đã hết hạn hoặc không hợp lệ. Hãy F5 lấy lại Cookie mới gán vào Render.",
                "extracted": {"shop_id": shop_id, "item_id": item_id}
            }
            
        if res.status_code != 200:
            return {
                "status": "error",
                "msg": f"Shopee API phản hồi lỗi HTTP {res.status_code}.",
                "extracted": {"shop_id": shop_id, "item_id": item_id}
            }
        
        shopee_data = res.json()
        if shopee_data.get("code") != 0 or "data" not in shopee_data:
            return {
                "status": "error",
                "msg": shopee_data.get("msg", "Lỗi dữ liệu từ Shopee API hỏng hoặc hết phiên."),
                "extracted": {"shop_id": shop_id, "item_id": item_id}
            }
            
        data = shopee_data["data"]
        comm_rate = data.get("commission_rate", {})
        card_full = data.get("batch_item_for_item_card_full", {})
        
        raw_price = card_full.get("price", "0")
        try:
            clean_price = int(raw_price) // 100000
        except ValueError:
            clean_price = 0

        return {
            "status": "success",
            "data": {
                "item_id": data.get("item_id"),
                "shop_id": shop_id,
                "product_name": card_full.get("name"),
                "price": clean_price,
                "total_commission_value": data.get("commission"),
                "max_commission_rate": comm_rate.get("max_commission_rate"),
                "seller_commission_rate": comm_rate.get("seller_commission_rate"),
                "shopee_commission_rate": comm_rate.get("shopee_commission_rate"),
                "xtra_commission_rate": comm_rate.get("exist_platform_commission_rate", "0%")
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống trục API: {str(e)}")
