import os
import json
import re
import copy
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Shopee Auto Extract & Affiliate API")

# ==============================================================================
# ĐỌC HEADER TỪ BIẾN MÔI TRƯỜNG (KHÔNG bao gồm 'referer' cố định)
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
# CÁC HÀM XỬ LÝ TỰ ĐỘNG
# ==============================================================================
def format_price(price_str):
    try:
        price = int(float(str(price_str).replace('₫', '').replace(',', '').replace('.', '')))
        # Shopee lưu giá nhân 100,000. Nếu giá trị đã là VND thật, ta giữ nguyên, nếu là định dạng Shopee thì chia
        if price > 100000000: 
            return f"{price // 100000:,} ₫"
        return f"{price:,} ₫"
    except:
        return "0 ₫"

async def resolve_and_extract(url: str):
    """Tự động mở link ngắn, theo dõi redirect và trích xuất shop_id, item_id"""
    try:
        # follow_redirects=True là chìa khóa để mở được vn.shp.ee hoặc s.shopee.vn
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url)
            final_url = str(response.url)
            
            # Regex tìm kiếm định dạng: shopee.vn/product/[shop_id]/[item_id]
            match = re.search(r'shopee\.vn/product/(\d+)/(\d+)', final_url)
            if match:
                return {
                    "shop_id": match.group(1),
                    "item_id": match.group(2),
                    "final_url": final_url
                }
            else:
                return None
    except Exception as e:
        raise Exception(f"Không thể mở link hoặc link không hợp lệ: {str(e)}")

# ==============================================================================
# API ENDPOINT CHÍNH
# ==============================================================================
@app.get("/api/get-product")
async def get_product_info(url: str):
    if not url:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Thiếu tham số 'url'"})

    # Bước 1: Tự động giải nén link ngắn và lấy ID
    extracted = await resolve_and_extract(url)
    if not extracted:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Link không phải là link sản phẩm Shopee hợp lệ hoặc không thể giải nén."})

    item_id = extracted["item_id"]
    shop_id = extracted["shop_id"]

    # Bước 2: Chuẩn bị Header động (Quan trọng: Referer phải khớp với item_id)
    if not DEFAULT_HEADERS:
        return JSONResponse(status_code=500, content={"status": "error", "message": "Server chưa được cấu hình Header (SHOPEE_HEADERS_JSON)."})
    
    request_headers = copy.deepcopy(DEFAULT_HEADERS)
    request_headers["referer"] = f"https://affiliate.shopee.vn/offer/product_offer/{item_id}"
    
    # Bước 3: Gọi API Affiliate của Shopee
    api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, headers=request_headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != 0:
                return JSONResponse(status_code=400, content={"status": "error", "message": f"Shopee trả về lỗi: {data.get('msg')}. Có thể Cookie/Header đã hết hạn."})
                
            product = data.get("data", {})
            comm_rate = product.get("commission_rate", {})
            
            seller_comm = str(product.get("seller_commission", "0"))
            is_xtra = not seller_comm.startswith("0") and seller_comm != "₫0"
            
            # Bước 4: Trả về dữ liệu đã được làm sạch cho PHP
            result = {
                "status": "success",
                "data": {
                    "item_id": item_id,
                    "shop_id": shop_id,
                    "product_name": product.get("name"),
                    "shop_name": product.get("shop_name"),
                    "price": format_price(product.get("price", 0)),
                    "price_raw": int(product.get("price", 0)) // 100000 if product.get("price") else 0,
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
            }
            return JSONResponse(content=result)
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code in [401, 403]:
            return JSONResponse(status_code=403, content={"status": "error", "message": "Lỗi 403: Header/Cookie trên Render đã hết hạn. Cần cập nhật lại biến môi trường."})
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi kết nối Shopee: {e.response.status_code}"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Lỗi máy chủ: {str(e)}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
