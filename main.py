import os
import re
import copy
import random
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Shopee Mobile Masquerade API")

# ==============================================================================
# 1. CẤU HÌNH: CHỈ CẦN COOKIE (Không cần x-sap-sec, af-ac-enc...)
# ==============================================================================
SHOPEE_COOKIE = os.getenv("SHOPEE_COOKIE", "").strip()

# Bộ header giả lập iPhone (Đã chứng minh là vượt qua WAF ở code tạo link)
MOBILE_HEADERS = {
    "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "accept": "application/json, text/plain, */*",
    "accept-language": "vi-VN,vi;q=0.9",
    "cookie": SHOPEE_COOKIE,
    "referer": "https://affiliate.shopee.vn/"
}

# ==============================================================================
# 2. CÁC HÀM XỬ LÝ
# ==============================================================================
def format_price(price_str):
    try:
        price = int(float(str(price_str).replace('₫', '').replace(',', '').replace('.', '')))
        if price > 100000000: 
            return f"{price // 100000:,} ₫"
        return f"{price:,} ₫"
    except:
        return "0 ₫"

async def resolve_short_link(url: str):
    """Mở link rút gọn để lấy item_id"""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            # Dùng mobile header để mở link rút gọn cho tự nhiên
            response = await client.get(url, headers=MOBILE_HEADERS)
            final_url = str(response.url)
            
            # Regex bắt shop_id và item_id
            match = re.search(r'/(?:product/|i\.\d+\.|[a-zA-Z0-9_-]+/)?(\d{9,12})/(\d{9,12})', final_url)
            if match:
                return {"shop_id": match.group(1), "item_id": match.group(2), "final_url": final_url}
            
            fallback = re.search(r'/(\d{9,12})/(\d{9,12})', final_url)
            if fallback:
                return {"shop_id": fallback.group(1), "item_id": fallback.group(2), "final_url": final_url}
                
            return {"error": f"Không tìm thấy ID trong URL: {final_url[:100]}..."}
    except Exception as e:
        return {"error": f"Lỗi mạng khi mở link: {str(e)}"}

# ==============================================================================
# 3. API ENDPOINT CHÍNH
# ==============================================================================
@app.get("/api/get-product")
async def get_product_info(url: str):
    if not url:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Thiếu tham số 'url'"})

    if not SHOPEE_COOKIE:
        return JSONResponse(status_code=500, content={"status": "error", "message": "Chưa cấu hình biến môi trường SHOPEE_COOKIE trên Render."})

    # Bước 1: Giải nén link
    extracted = await resolve_short_link(url)
    if "error" in extracted:
        return JSONResponse(status_code=400, content={"status": "error", "message": extracted["error"]})

    item_id = extracted["item_id"]
    shop_id = extracted["shop_id"]

    # Bước 2: Gọi API lấy thông tin sản phẩm (Dùng giao diện Mobile)
    api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    # Tạo header riêng cho request này (thêm referer động)
    req_headers = copy.deepcopy(MOBILE_HEADERS)
    req_headers["referer"] = f"https://affiliate.shopee.vn/offer/product_offer/{item_id}"
    
    try:
        # Delay ngẫu nhiên 1 chút để giống người thật lướt điện thoại
        await httpx.sleep(random.uniform(0.5, 1.2))
        
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, headers=req_headers, timeout=15.0)
            
            # Kiểm tra xem có bị trả về HTML (WAF chặn) không
            if "text/html" in response.headers.get("content-type", ""):
                return JSONResponse(status_code=403, content={
                    "status": "error", 
                    "message": "Bị Shopee chặn (WAF HTML). Endpoint này có thể bắt buộc phải có token Desktop (x-sap-sec)."
                })
                
            data = response.json()
            
            # Bắt lỗi 90309999
            if data.get("error") == 90309999 or data.get("3") == 90309999:
                return JSONResponse(status_code=403, content={
                    "status": "error", 
                    "message": "Shopee chặn request (Mã 90309999). Cookie đã hết hạn hoặc IP Render bị blacklist."
                })
                
            if data.get("code") != 0:
                return JSONResponse(status_code=400, content={
                    "status": "error", 
                    "message": f"API Shopee báo lỗi: {data.get('msg')} (Code: {data.get('code')})"
                })
                
            # Bước 3: Trích xuất dữ liệu
            product = data.get("data", {})
            comm_rate = product.get("commission_rate", {})
            seller_comm = str(product.get("seller_commission", "0"))
            is_xtra = not seller_comm.startswith("0") and seller_comm != "₫0"
            
            return JSONResponse(content={
                "status": "success",
                "data": {
                    "item_id": item_id,
                    "shop_id": shop_id,
                    "product_name": product.get("name"),
                    "shop_name": product.get("shop_name"),
                    "price": format_price(product.get("price", 0)),
                    "sold": int(product.get("historical_sold", 0)),
                    "image": f"https://cf.shopee.vn/file/{product.get('image')}" if product.get('image') else "",
                    "product_link": extracted["final_url"],
                    "affiliate_link": product.get("long_link"),
                    "commission": {
                        "total": product.get("commission"),
                        "total_rate": comm_rate.get("max_commission_rate", "0%"),
                        "is_xtra": is_xtra,
                        "cap": format_price(comm_rate.get("commission_cap", "0")),
                        "seller_amount": product.get("seller_commission"),
                        "seller_rate": product.get("seller_commission_rate"),
                        "shopee_amount": product.get("shopee_commission"),
                        "shopee_rate": product.get("shopee_commission_rate")
                    }
                }
            })
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi hệ thống: {str(e)}"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
