import os
import re
import requests
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Shopee Mobile-Style Product API")

# ==============================================================================
# CHỈ CẦN ĐỌC MỖI CHUỖI COOKIE (KHÔNG CẦN JSON PHỨC TẠP NỮA!)
# ==============================================================================
SHOPEE_COOKIE = os.getenv("SHOPEE_COOKIE", "").strip()

def format_price(price_str):
    try:
        price = int(float(str(price_str).replace('₫', '').replace(',', '').replace('.', '')))
        if price > 100000000: 
            return f"{price // 100000:,} ₫"
        return f"{price:,} ₫"
    except:
        return "0 ₫"

def resolve_and_extract(url: str):
    # Dùng User-Agent Mobile để giải nén link ngắn
    mobile_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    try:
        response = requests.get(url, headers={"user-agent": mobile_ua}, allow_redirects=True, timeout=15)
        final_url = response.url
        
        match = re.search(r'/(?:product/|i\.\d+\.|[a-zA-Z0-9_-]+/)?(\d{9,12})/(\d{9,12})', final_url)
        if match:
            return {"shop_id": match.group(1), "item_id": match.group(2)}
        else:
            fallback_match = re.search(r'/(\d{9,12})/(\d{9,12})', final_url)
            if fallback_match:
                return {"shop_id": fallback_match.group(1), "item_id": fallback_match.group(2)}
            return {"error": f"Không thể trích xuất ID. Link: {final_url[:100]}..."}
    except Exception as e:
        return {"error": f"Lỗi giải nén link: {str(e)}"}

@app.get("/api/get-product")
def get_product_info(url: str):
    if not url:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Thiếu tham số 'url'"})

    if not SHOPEE_COOKIE:
        return JSONResponse(status_code=500, content={"status": "error", "message": "Chưa cấu hình biến môi trường SHOPEE_COOKIE trên Render."})

    extracted = resolve_and_extract(url)
    if "error" in extracted:
        return JSONResponse(status_code=400, content={"status": "error", "message": extracted["error"]})

    item_id = extracted["item_id"]
    
    # ==============================================================================
    # ÁP DỤNG PHONG CÁCH "CODE MỚI": TỐI GIẢN, MOBILE USER-AGENT, CHỈ CẦN COOKIE
    # ==============================================================================
    headers = {
        "cookie": SHOPEE_COOKIE,
        "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
        "accept": "application/json, text/plain, */*",
        "referer": f"https://affiliate.shopee.vn/offer/product_offer/{item_id}"
    }
    
    api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    try:
        response = requests.get(api_url, headers=headers, timeout=15)
        
        try:
            data = response.json()
        except Exception:
            return JSONResponse(status_code=response.status_code, content={
                "status": "error",
                "message": f"Shopee trả về HTML (Bị chặn). Nội dung: {response.text[:200]}"
            })
        
        if data.get("error") == 90309999 or data.get("3") == 90309999:
            return JSONResponse(status_code=403, content={
                "status": "error", 
                "message": "🚫 Shopee chặn (90309999). Cookie hết hạn hoặc IP Render bị blacklist."
            })
            
        if data.get("code") != 0:
            return JSONResponse(status_code=400, content={
                "status": "error", 
                "message": f"Shopee API lỗi: {data.get('msg')} (Code: {data.get('code')})"
            })
            
        product = data.get("data", {})
        comm_rate = product.get("commission_rate", {})
        seller_comm = str(product.get("seller_commission", "0"))
        is_xtra = not seller_comm.startswith("0") and seller_comm != "₫0"
        
        result = {
            "status": "success",
            "data": {
                "item_id": item_id,
                "product_name": product.get("name"),
                "shop_name": product.get("shop_name"),
                "price": format_price(product.get("price", 0)),
                "sold": int(product.get("historical_sold", 0)),
                "image": f"https://cf.shopee.vn/file/{product.get('image')}" if product.get('image') else "",
                "affiliate_link": product.get("long_link"),
                "commission": {
                    "total": product.get("commission"),
                    "total_rate": comm_rate.get("max_commission_rate", "0%"),
                    "is_xtra": is_xtra,
                    "seller_amount": product.get("seller_commission"),
                    "shopee_amount": product.get("shopee_commission"),
                }
            }
        }
        return JSONResponse(content=result)
        
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi: {str(e)}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
