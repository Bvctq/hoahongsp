import os
import json
import re
import copy
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Shopee Auto Extract & Affiliate API v4")

# ==============================================================================
# ĐỌC HEADER TỪ BIẾN MÔI TRƯỜNG
# ==============================================================================
headers_json_str = os.getenv("SHOPEE_HEADERS_JSON", "{}")
try:
    DEFAULT_HEADERS = json.loads(headers_json_str)
    if not DEFAULT_HEADERS:
        print("⚠️ CẢNH BÁO: Biến SHOPEE_HEADERS_JSON đang trống.")
except json.JSONDecodeError:
    DEFAULT_HEADERS = {}
    print("❌ LỖI: SHOPEE_HEADERS_JSON không phải là JSON hợp lệ!")

# ==============================================================================
# CÁC HÀM XỬ LÝ
# ==============================================================================
def format_price(price_str):
    try:
        price = int(float(str(price_str).replace('₫', '').replace(',', '').replace('.', '')))
        if price > 100000000: 
            return f"{price // 100000:,} ₫"
        return f"{price:,} ₫"
    except:
        return "0 ₫"

async def resolve_and_extract(url: str):
    try:
        headers_to_use = copy.deepcopy(DEFAULT_HEADERS)
        if "user-agent" not in headers_to_use:
            headers_to_use["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url, headers=headers_to_use)
            final_url = str(response.url)
            
            # Regex bắt 2 dãy số dài (shop_id và item_id)
            match = re.search(r'/(?:product/|i\.\d+\.|[a-zA-Z0-9_-]+/)?(\d{9,12})/(\d{9,12})', final_url)
            if match:
                return {"shop_id": match.group(1), "item_id": match.group(2), "final_url": final_url}
            else:
                fallback_match = re.search(r'/(\d{9,12})/(\d{9,12})', final_url)
                if fallback_match:
                    return {"shop_id": fallback_match.group(1), "item_id": fallback_match.group(2), "final_url": final_url}
                return {"error": f"Không thể trích xuất ID. Link đích: {final_url[:100]}..."}
    except Exception as e:
        return {"error": f"Lỗi giải nén link: {str(e)}"}

# ==============================================================================
# API ENDPOINT CHÍNH
# ==============================================================================
@app.get("/api/get-product")
async def get_product_info(url: str):
    if not url:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Thiếu tham số 'url'"})

    extracted = await resolve_and_extract(url)
    if "error" in extracted:
        return JSONResponse(status_code=400, content={"status": "error", "message": extracted["error"]})

    item_id = extracted["item_id"]
    
    if not DEFAULT_HEADERS:
        return JSONResponse(status_code=500, content={"status": "error", "message": "Server chưa cấu hình Header."})
    
    request_headers = copy.deepcopy(DEFAULT_HEADERS)
    request_headers["referer"] = f"https://affiliate.shopee.vn/offer/product_offer/{item_id}"
    
    api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, headers=request_headers, timeout=15.0)
            
            # === CƠ CHẾ BẮT LỖI CHI TIẾT ===
            try:
                data = response.json()
            except Exception:
                # Nếu không parse được JSON, nghĩa là Shopee trả về HTML (trang chặn/Captcha)
                return JSONResponse(status_code=response.status_code, content={
                    "status": "error",
                    "message": f"Shopee trả về HTML (Bị chặn/WAF), không phải JSON. Nội dung: {response.text[:300]}"
                })
            
            if data.get("code") != 0:
                return JSONResponse(status_code=400, content={
                    "status": "error", 
                    "message": f"Shopee API báo lỗi. Chi tiết dữ liệu trả về: {str(data)[:500]}"
                })
            # ==============================
                
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
            
    except httpx.HTTPStatusError as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi HTTP {e.response.status_code}: {e.response.text[:200]}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi máy chủ: {str(e)}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
