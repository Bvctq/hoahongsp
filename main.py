import os
import re
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Shopee Affiliate Extractor")

class LinkRequest(BaseModel):
    url: str

def resolve_short_url(short_url: str) -> str:
    """Mẹo Bypass: Dùng luôn UA Mobile và chặn redirect để húp Location header cực nhanh"""
    try:
        headers = {
            "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        # Không cho tự động bẻ hướng để né Akamai quét IP
        response = requests.get(short_url, headers=headers, allow_redirects=False, timeout=10)
        
        if response.status_code in [301, 302] and "Location" in response.headers:
            return response.headers["Location"]
        
        return response.url
    except Exception:
        return None

def extract_ids(url: str):
    """Trích xuất shop_id và item_id bằng Regex"""
    match1 = re.search(r'product/(\d+)/(\d+)', url)
    if match1:
        return match1.group(1), match1.group(2)
    
    match2 = re.search(r'i\.(\d+)\.(\d+)', url)
    if match2:
        return match2.group(1), match2.group(2)
        
    return None, None

@app.post("/api/extract")
def extract_shopee_info(payload: LinkRequest):
    url_input = payload.url.strip()
    
    # 1. Lấy Cookie từ môi trường Render
    shopee_cookie = os.getenv("SHOPEE_COOKIE", "").replace('"', '').replace("'", "").strip()
    if not shopee_cookie:
        return {
            "status": "error",
            "msg": "Chưa cấu hình biến môi trường SHOPEE_COOKIE trên Render!"
        }
    
    # 2. Xử lý link rút gọn
    if "shp.ee" in url_input or "s.shopee.vn" in url_input:
        long_url = resolve_short_url(url_input)
    else:
        long_url = url_input
        
    if not long_url:
        raise HTTPException(status_code=400, detail="Không thể phân giải bẻ hướng link rút gọn Shopee.")
    
    # 3. Trích xuất ID
    shop_id, item_id = extract_ids(long_url)
    if not item_id:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy shop_id hoặc item_id. Link phân giải được: {long_url}")

    # 4. Gọi API lấy dữ liệu hoa hồng sản phẩm
    affiliate_api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    # Áp dụng chuẩn đống Headers chạy ngon từ code tham khảo của bạn
    headers = {
        "content-type": "application/json",
        "cookie": shopee_cookie,
        "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    }
    
    try:
        res = requests.get(affiliate_api_url, headers=headers, timeout=10)
        
        if res.status_code != 200:
            return {
                "status": "error",
                "msg": f"Shopee API trả về lỗi HTTP {res.status_code}. Vui lòng kiểm tra lại Cookie gán trên Render.",
                "extracted": {"shop_id": shop_id, "item_id": item_id}
            }
        
        shopee_data = res.json()
        if shopee_data.get("code") != 0 or "data" not in shopee_data:
            return {
                "status": "error",
                "msg": shopee_data.get("msg", "Lỗi phiên đăng nhập hoặc dữ liệu từ Shopee API hỏng."),
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
