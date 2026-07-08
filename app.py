import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Lấy cookie từ biến môi trường Render
SHOPEE_AFFILIATE_COOKIE = os.environ.get('SHOPEE_AFFILIATE_COOKIE', '')

HEADERS_TEMPLATE = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def extract_shop_item_ids(url: str):
    """
    Trích xuất shop_id & item_id từ URL sản phẩm Shopee.
    Có 2 dạng:
      - /product/<shop_id>/<item_id>
      - /i.<shop_id>.<item_id>
    """
    # Dạng 1: /product/shop_id/item_id
    match = re.search(r'/product/(\d+)/(\d+)', url)
    if match:
        return match.group(1), match.group(2)

    # Dạng 2: i.shop_id.item_id
    match = re.search(r'i\.(\d+)\.(\d+)', url)
    if match:
        return match.group(1), match.group(2)

    return None, None

def resolve_short_link(short_url: str):
    """Theo tất cả redirect để lấy URL cuối cùng."""
    try:
        resp = requests.get(
            short_url,
            headers=HEADERS_TEMPLATE,
            allow_redirects=True,
            timeout=15
        )
        return resp.url
    except Exception as e:
        print(f"Error resolving short link: {e}")
        return None

@app.route('/get-product-info')
def get_product_info():
    original_url = request.args.get('url', '').strip()
    if not original_url:
        return jsonify({'error': 'Thiếu tham số url'}), 400

    # 1. Phân giải link rút gọn -> link đích
    final_url = resolve_short_link(original_url)
    if not final_url:
        return jsonify({'error': 'Không thể phân giải link rút gọn'}), 400

    shop_id, item_id = extract_shop_item_ids(final_url)
    if not item_id:
        return jsonify({'error': 'Không tìm thấy item_id trong URL đích', 'resolved_url': final_url}), 400

    # 2. Gọi API Affiliate chính thức
    aff_api = f'https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}'
    aff_headers = {
        **HEADERS_TEMPLATE,
        'Cookie': SHOPEE_AFFILIATE_COOKIE,
        'Referer': 'https://affiliate.shopee.vn/',
        'Accept': 'application/json',
    }

    try:
        aff_resp = requests.get(aff_api, headers=aff_headers, timeout=15)
        if aff_resp.status_code != 200:
            return jsonify({'error': f'Affiliate API lỗi HTTP {aff_resp.status_code}'}), 502

        data = aff_resp.json()
        if data.get('code') != 0:
            return jsonify({'error': data.get('msg', 'Lỗi từ Shopee Affiliate')}), 502

        product = data['data']
        batch = product.get('batch_item_for_item_card_full', {})
        comm = product.get('commission_rate', {})

        # 3. Trả về dữ liệu tinh gọn, đúng các trường bạn cần
        result = {
            'item_id': product.get('item_id'),
            'shop_id': batch.get('shopid'),
            'shop_name': batch.get('shop_name'),
            'product_name': batch.get('name'),
            'price': batch.get('price'),                       # giá hiện tại (đơn vị nhỏ nhất của VND, cần chia 100000)
            'price_before_discount': batch.get('price_before_discount'),
            'discount': batch.get('discount'),                 # ví dụ "20%"
            'historical_sold': batch.get('historical_sold'),
            'rating_star': batch.get('item_rating', {}).get('rating_star'),
            'stock': batch.get('stock'),
            'commission': product.get('commission'),           # tổng hoa hồng hiển thị (VD: "₫18.305")
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
            'affiliate_link': product.get('product_link'),      # link sản phẩm gốc
            'long_link': product.get('long_link'),              # link affiliate dài
            'shop_rating': batch.get('shop_rating'),
            'is_official_shop': batch.get('is_official_shop'),
            'is_preferred_plus_seller': batch.get('is_preferred_plus_seller'),
        }

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': f'Lỗi xử lý: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
