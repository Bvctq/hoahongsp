import os
import re
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Shopee Affiliate Extractor")

class LinkRequest(BaseModel):
    url: str

def resolve_short_url(short_url: str) -> str:
    """Theo vết chuyển hướng để lấy URL sản phẩm gốc"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # Thực hiện request để lấy link đích cuối cùng
        response = requests.get(short_url, headers=headers, allow_redirects=True, timeout=10)
        return response.url
    except Exception:
        return None

def extract_ids(url: str):
    """Trích xuất shop_id và item_id từ URL gốc bằng Regex"""
    # Pattern dạng: product/shop_id/item_id
    match1 = re.search(r'product/(\d+)/(\d+)', url)
    if match1:
        return match1.group(1), match1.group(2)
    
    # Pattern dạng thông thường công khai: i.shop_id.item_id
    match2 = re.search(r'i\.(\d+)\.(\d+)', url)
    if match2:
        return match2.group(1), match2.group(2)
        
    return None, None

@app.post("/api/extract")
def extract_shopee_info(payload: LinkRequest):
    url_input = payload.url.strip()
    
    # 1. Giải mã link rút gọn
    long_url = resolve_short_url(url_input) if "shp.ee" in url_input or "s.shopee.vn" in url_input else url_input
    if not long_url:
        raise HTTPException(status_code=400, detail="Không thể phân giải link rút gọn Shopee.")
    
    # 2. Trích xuất ID từ link dài
    shop_id, item_id = extract_ids(long_url)
    if not item_id:
        raise HTTPException(status_code=400, detail="Không tìm thấy shop_id hoặc item_id trong cấu trúc link.")

    # 3. Chuẩn bị gọi API Affiliate Shopee
    affiliate_api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    # Lấy Cookie và CSRFToken cấu hình sẵn từ Render Environment bọc bảo mật
    shopee_cookie = os.getenv("SHOPEE_COOKIE", "")
    shopee_csrf = os.getenv("SHOPEE_CSRF", "")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": shopee_cookie,
        "X-CSRFToken": shopee_csrf,
        "Referer": "https://affiliate.shopee.vn/",
        "Accept": "application/json, text/plain, */*"
    }
    
    try:
        res = requests.get(affiliate_api_url, headers=headers, timeout=10)
        if res.status_code != 200:
            return {
                "status": "error",
                "msg": f"Shopee API phản hồi lỗi HTTP {res.status_code}. Vui lòng kiểm tra Cookie/CSRF.",
                "extracted": {"shop_id": shop_id, "item_id": item_id}
            }
        
        shopee_data = res.json()
        if shopee_data.get("code") != 0 or "data" not in shopee_data:
            return {
                "status": "error",
                "msg": shopee_data.get("msg", "Lỗi dữ liệu từ Shopee API hỏng hoặc hết phiên nhập."),
                "extracted": {"shop_id": shop_id, "item_id": item_id}
            }
            
        data = shopee_data["data"]
        comm_rate = data.get("commission_rate", {})
        card_full = data.get("batch_item_for_item_card_full", {})
        
        # Định dạng lại giá gốc (Shopee thường nhân thêm 100.000 đơn vị trong DB JSON gốc)
        raw_price = card_full.get("price", "0")
        try:
            clean_price = int(raw_price) // 100000
        except ValueError:
            clean_price = 0

        # Trả về cấu trúc JSON rút gọn, sạch sẽ cho PHP dễ xử lý
        return {
            "status": "success",
            "data": {
                "item_id": data.get("item_id"),
                "shop_id": shop_id,
                "product_name": card_full.get("name"),
                "price": clean_price,
                "total_commission_value": data.get("commission"), # Ví dụ: ₫18.305
                "max_commission_rate": comm_rate.get("max_commission_rate"), # 10%
                "seller_commission_rate": comm_rate.get("seller_commission_rate"), # 10%
                "shopee_commission_rate": comm_rate.get("shopee_commission_rate"), # 0%
                "xtra_commission_rate": comm_rate.get("exist_platform_commission_rate", "0%")
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống trục API: {str(e)}")
