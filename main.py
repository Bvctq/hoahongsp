import os
import re
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class LinkRequest(BaseModel):
    url: str
    cookie: str = None # Truyền cookie từ PHP sang, hoặc dùng biến môi trường trên Render

@app.post("/api/extract")
async def extract_info(req: LinkRequest):
    short_url = req.url.strip()
    # Ưu tiên dùng cookie truyền từ PHP, nếu không có thì lấy từ biến môi trường SHOPEE_COOKIE trên Render
    cookie = req.cookie or os.environ.get("SHOPEE_COOKIE", "")
    
    if not cookie:
        raise HTTPException(status_code=400, detail="Thiếu Cookie Shopee Affiliate. Vui lòng truyền vào request hoặc set biến môi trường SHOPEE_COOKIE.")

    headers_req = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    # 1. Resolve link rút gọn (s.shopee.vn, vn.shp.ee) về link gốc
    try:
        response = requests.get(short_url, headers=headers_req, allow_redirects=True, timeout=15)
        final_url = response.url
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lỗi khi resolve link: {str(e)}")
        
    # 2. Trích xuất shopid và itemid từ URL gốc
    # Format: https://shopee.vn/product/542068555/45011781634
    match = re.search(r'/product/(\d+)/(\d+)', final_url)
    if not match:
        match = re.search(r'(\d{6,})/(\d{6,})', final_url) # Fallback
        
    if not match:
        raise HTTPException(status_code=400, detail=f"Không tìm thấy shopid và itemid từ link: {final_url}")
        
    shopid = match.group(1)
    itemid = match.group(2)
    
    # 3. Gọi API Shopee Affiliate để lấy thông tin hoa hồng
    affiliate_api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={itemid}"
    headers_api = {
        "User-Agent": headers_req["User-Agent"],
        "Cookie": cookie,
        "Accept": "application/json",
        "Referer": "https://affiliate.shopee.vn/"
    }
    
    try:
        aff_response = requests.get(affiliate_api_url, headers=headers_api, timeout=15)
        aff_data = aff_response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi gọi API Shopee: {str(e)}")
        
    if aff_data.get("code") != 0:
        raise HTTPException(status_code=400, detail=f"Shopee API lỗi: {aff_data.get('msg', 'Unknown error')}")
        
    data = aff_data.get("data", {})
    item_info = data.get("batch_item_for_item_card_full", {})
    commission_rate_info = data.get("commission_rate", {})
    commission_rate_detail = data.get("commission_rate_detail", {})
    
    # 4. Xử lý dữ liệu giá (Shopee lưu giá nhân với 100,000)
    raw_price = int(item_info.get("price", 0))
    price_vnd = raw_price / 100000
    
    raw_price_before = int(item_info.get("price_before_discount", 0))
    price_before_vnd = raw_price_before / 100000
    
    # 5. Xử lý dữ liệu hoa hồng
    seller_commission_rate_str = commission_rate_info.get("seller_commission_rate", "0%")
    seller_commission_str = commission_rate_info.get("seller_commission", "₫0")
    
    # Hoa hồng cơ bản từ Shopee (thường nằm trong social_media_item_base_exist_commission_rate)
    shopee_base_rate_raw = 0
    shopee_detail = commission_rate_detail.get("shopee_commission_detail", {})
    if shopee_detail:
        shopee_base_rate_raw = shopee_detail.get("social_media_item_base_exist_commission_rate", 0)
        if not shopee_base_rate_raw:
            shopee_base_rate_raw = shopee_detail.get("shopee_video_item_base_exist_commission_rate", 0)
            
    shopee_commission_rate_str = f"{shopee_base_rate_raw / 1000}%"
    
    # Tính tổng tỷ lệ hoa hồng
    try:
        seller_rate_val = float(seller_commission_rate_str.replace('%', '').replace(',', '.'))
        shopee_rate_val = float(shopee_commission_rate_str.replace('%', '').replace(',', '.'))
        total_rate_str = f"{seller_rate_val + shopee_rate_val}%"
    except:
        total_rate_str = "N/A"
        
    # 6. Trả về JSON sạch
    result = {
        "item_id": itemid,
        "shop_id": shopid,
        "product_name": item_info.get("name", ""),
        "image_url": f"https://cf.shopee.vn/file/{item_info.get('image', '')}",
        "price_vnd": price_vnd,
        "price_before_discount_vnd": price_before_vnd,
        "discount": item_info.get("discount", "0%"),
        "seller_commission_rate": seller_commission_rate_str,
        "seller_commission": seller_commission_str,
        "shopee_base_commission_rate": shopee_commission_rate_str,
        "total_commission_rate": total_rate_str,
        "sold": item_info.get("historical_sold", 0),
        "stock": item_info.get("stock", 0),
        "rating_star": item_info.get("item_rating", {}).get("rating_star", 0),
        "product_link": f"https://shopee.vn/product/{shopid}/{itemid}",
        "affiliate_link": data.get("long_link", "")
    }
    
    return {"code": 0, "msg": "success", "data": result}
