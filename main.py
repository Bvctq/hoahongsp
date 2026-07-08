import os
import re
import traceback
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SHOPEE_AFFILIATE_COOKIE = os.environ.get('SHOPEE_AFFILIATE_COOKIE', '')

HEADERS_TEMPLATE = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    try:
        session = requests.Session()
        session.headers.update(headers)
        resp = session.get(short_url, allow_redirects=True, timeout=20)
        return resp.url
    except Exception as e:
        print(f"Error resolving short link: {e}")
        return None

@app.get("/")
def home():
    return {"message": "Shopee Product Info API"}

@app.get("/get-product-info")
def get_product_info(url: str):
    try:
        if not url:
            raise HTTPException(status_code=400, detail="Thiếu tham số url")

        final_url = resolve_short_link(url)
        if not final_url:
            raise HTTPException(status_code=400, detail="Không thể phân giải link rút gọn")

        shop_id, item_id = extract_shop_item_ids(final_url)
        if not item_id:
            return {
                "error": "Không tìm thấy item_id trong URL đích",
                "resolved_url": final_url
            }

        aff_api = f'https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}'
        aff_headers = {
            **HEADERS_TEMPLATE,
            'Cookie': SHOPEE_AFFILIATE_COOKIE,
            'Referer': 'https://affiliate.shopee.vn/',
            'Accept': 'application/json',
            'x-requested-with': 'XMLHttpRequest',
            'x-api-source': 'pc',
        }

        csrf_match = re.search(r'csrftoken=([^;]+)', SHOPEE_AFFILIATE_COOKIE)
        if csrf_match:
            aff_headers['x-csrftoken'] = csrf_match.group(1)

        print(f"Calling affiliate API: {aff_api}")
        aff_resp = requests.get(aff_api, headers=aff_headers, timeout=30)
        print(f"Affiliate API response status: {aff_resp.status_code}")

        if aff_resp.status_code == 403:
            return {"error": "Affiliate API từ chối (403). Cookie có thể vẫn thiếu quyền hoặc IP bị chặn."}
        if aff_resp.status_code != 200:
            return {"error": f"Affiliate API lỗi HTTP {aff_resp.status_code}"}

        data = aff_resp.json()
        if data.get('code') != 0:
            return {"error": data.get('msg', 'Lỗi từ Shopee Affiliate')}

        product = data['data']
        batch = product.get('batch_item_for_item_card_full', {})
        comm = product.get('commission_rate', {})

        return {
            'item_id': product.get('item_id'),
            'shop_id': batch.get('shopid') or shop_id,
            'shop_name': batch.get('shop_name'),
            'product_name': batch.get('name'),
            'price': batch.get('price'),
            'price_before_discount': batch.get('price_before_discount'),
            'discount': batch.get('discount'),
            'historical_sold': batch.get('historical_sold'),
            'rating_star': batch.get('item_rating', {}).get('rating_star'),
            'stock': batch.get('stock'),
            'commission': product.get('commission'),
            'commission_details': {
                'max_commission_rate': comm.get('max_commission_rate'),
                'seller_commission_rate': comm.get('seller_commission_rate'),
                'seller_commission': comm.get('seller_commission'),
                'shopee_commission_rate': comm.get('shopee_commission_rate'),
                'shopee_commission': comm.get('shopee_commission'),
                'default_commission_rate': comm.get('default_commission_rate'),
                'default_commission': comm.get('default_commission'),
                'commission_cap': comm.get('commission_cap'),
                'shopee_new_user_commission_cap': comm.get('shopee_new_user_commission_cap'),
                'web_exist_commission': comm.get('web_exist_commission'),
                'web_new_commission': comm.get('web_new_commission'),
                'app_exist_commission': comm.get('app_exist_commission'),
                'app_new_commission': comm.get('app_new_commission'),
                'exist_platform_commission_rate': comm.get('exist_platform_commission_rate'),
                'new_platform_commission_rate': comm.get('new_platform_commission_rate')
            },
            'affiliate_link': product.get('product_link'),
            'long_link': product.get('long_link'),
            'shop_rating': batch.get('shop_rating'),
            'is_official_shop': batch.get('is_official_shop'),
            'is_preferred_plus_seller': batch.get('is_preferred_plus_seller'),
        }
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"Unhandled exception: {error_trace}")
        return {"error": f"Lỗi máy chủ: {str(e)}", "traceback": error_trace}
