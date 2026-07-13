import os
import json
import re
import copy
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Shopee Affiliate Product Info API")

# ==============================================================================
# ĐỌC TOÀN BỘ HEADER TỪ 1 BIẾN MÔI TRƯỜNG DUY NHẤT
# ==============================================================================
headers_json_str = os.getenv("SHOPEE_HEADERS_JSON", "{}")

try:
    DEFAULT_HEADERS = json.loads(headers_json_str)
    if not DEFAULT_HEADERS:
        print("⚠️ CẢNH BÁO: Biến SHOPEE_HEADERS_JSON đang trống hoặc không đúng định dạng JSON.")
except json.JSONDecodeError:
    DEFAULT_HEADERS = {}
    print("❌ LỖI: SHOPEE_HEADERS_JSON không phải là JSON hợp lệ!")

# ==============================================================================
# CÁC HÀM XỬ LÝ DỮ LIỆU
# ==============================================================================
def format_price(price_str):
    try:
        price = int(float(price_str))
        return f"{price // 100000:,} ₫"
    except (ValueError, TypeError):
        return "0 ₫"

def extract_item_id_from_url(url: str) -> str:
    match = re.search(r'/product/\d+/(\d+)', url)
    if match:
        return match.group(1)
    return url

# ==============================================================================
# ROUTES
# ==============================================================================
@app.get("/", response_class=HTMLResponse)
async def read_root():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Shopee Affiliate API</title>
        <style>
            body { font-family: system-ui, sans-serif; margin: 40px; background: #f9fafb; color: #1f2937; }
            .container { background: white; padding: 32px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 800px; margin: auto; }
            h1 { color: #ee4d2d; }
            code { background: #f3f4f6; padding: 4px 8px; border-radius: 6px; color: #dc2626; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Shopee Affiliate Product Data API</h1>
            <p>API đã được cập nhật để tự động điều chỉnh Referer theo từng sản phẩm.</p>
            <h3>Cách sử dụng:</h3>
            <p><code>GET /api/product-info?item_id=50812656268</code></p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/api/product-info")
async def get_product_info(item_id: str = None, url: str = None):
    if not item_id and not url:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp 'item_id' hoặc 'url'")
    
    if url and not item_id:
        item_id = extract_item_id_from_url(url)
        if not item_id or not item_id.isdigit():
            raise HTTPException(status_code=400, detail="Không thể trích xuất item_id hợp lệ từ URL")

    if not DEFAULT_HEADERS:
        raise HTTPException(status_code=500, detail="Server chưa được cấu hình Header.")

    # === QUAN TRỌNG: Tạo bản sao của header và cập nhật referer động ===
    request_headers = copy.deepcopy(DEFAULT_HEADERS)
    request_headers["referer"] = f"https://affiliate.shopee.vn/offer/product_offer/{item_id}"
    
    # Loại bỏ trace cũ nếu có, để tránh bị Shopee check mismatch
    if "referer" in request_headers and "?trace=" in request_headers["referer"]:
        request_headers["referer"] = request_headers["referer"].split("?trace=")[0]
    # ================================================================

    api_url = f"https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(api_url, headers=request_headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != 0:
                raise HTTPException(status_code=400, detail=f"Lỗi từ API Shopee: {data.get('msg')}.")
                
            product = data.get("data", {})
            comm_rate = product.get("commission_rate", {})
            
            seller_comm = product.get("seller_commission", "₫0")
            is_xtra = not str(seller_comm).startswith("₫0") and str(seller_comm) != "0"
            
            result = {
                "itemId": int(product.get("item_id", 0)),
                "productName": product.get("name"),
                "shopName": product.get("shop_name"),
                "price": int(product.get("price", 0)) // 100000 if product.get("price") else 0,
                "sales": int(product.get("historical_sold", 0)),
                "imageUrl": f"https://cf.shopee.vn/file/{product.get('image')}" if product.get('image') else "",
                "productLink": product.get("product_link"),
                "affiliateLink": product.get("long_link"),
                "commission": {
                    "total": product.get("commission"),
                    "isXtra": is_xtra,
                    "cap": format_price(comm_rate.get("commission_cap", "0")),
                    "seller": {
                        "amount": product.get("seller_commission"),
                        "rate": product.get("seller_commission_rate")
                    },
                    "shopee": {
                        "amount": product.get("shopee_commission"),
                        "rate": product.get("shopee_commission_rate")
                    }
                }
            }
            return JSONResponse(content=result)
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code in [401, 403]:
                raise HTTPException(status_code=403, detail="Lỗi 403: Header/Cookie đã hết hạn.")
            raise HTTPException(status_code=e.response.status_code, detail=f"Lỗi HTTP: {e.response.status_code}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Lỗi máy chủ: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port)
