import os
import re
import traceback
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SHOPEE_AFFILIATE_COOKIE = os.environ.get('SHOPEE_AFFILIATE_COOKIE', '')

HEADERS_TEMPLATE = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def extract_shop_item_ids(url: str):
    # Giữ nguyên các pattern cũ
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

@app.route('/get-product-info')
def get_product_info():
    try:
        original_url = request.args.get('url', '').strip()
        if not original_url:
            return jsonify({'error': 'Thiếu tham số url'}), 400

        # Resolve link
        final_url = resolve_short_link(original_url)
        if not final_url:
            return jsonify({'error': 'Không thể phân giải link rút gọn'}), 400

        shop_id, item_id = extract_shop_item_ids(final_url)
        if not item_id:
            return jsonify({
                'error': 'Không tìm thấy item_id trong URL đích',
                'resolved_url': final_url
            }), 400

        # Chuẩn bị gọi affiliate API
        aff_api = f'https://affiliate.shopee.vn/api/v3/offer/product?item_id={item_id}'
        aff_headers = {
            **HEADERS_TEMPLATE,
            'Cookie': SHOPEE_AFFILIATE_COOKIE,
            'Referer': 'https://affiliate.shopee.vn/',
            'Accept': 'application/json',
            'x-requested-with': 'XMLHttpRequest',  # Quan trọng: giả lập AJAX request
            'x-api-source': 'pc',                   # Thêm header thường thấy
        }

        # Thêm csrftoken nếu có
        csrf_match = re.search(r'csrftoken=([^;]+)', SHOPEE_AFFILIATE_COOKIE)
        if csrf_match:
            aff_headers['x-csrftoken'] = csrf_match.group(1)

        # Gửi request đến affiliate API
        print(f"Calling affiliate API: {aff_api}")  # In ra log Render
        aff_resp = requests.get(aff_api, headers=aff_headers, timeout=30)  # Tăng timeout

        # Ghi log mã trạng thái và một phần body để debug
        print(f"Affiliate API response status: {aff_resp.status_code}")
        if aff_resp.status_code != 200:
            print(f"Response body (first 500 chars): {aff_resp.text[:500]}")

        # Nếu affiliate API trả về 403, cookie vẫn có vấn đề
        if aff_resp.status_code == 403:
            return jsonify({
                'error': 'Affiliate API từ chối (403). Cookie có thể vẫn thiếu quyền hoặc IP bị chặn.',
                'detail': 'Thử cập nhật cookie đầy đủ hơn và kiểm tra IP của Render.'
            }), 502

        # Nếu lỗi khác
        if aff_resp.status_code != 200:
            return jsonify({
                'error': f'Affiliate API lỗi HTTP {aff_resp.status_code}'
            }), 502

        # Parse JSON
        data = aff_resp.json()
        if data.get('code') != 0:
            return jsonify({'error': data.get('msg', 'Lỗi từ Shopee Affiliate')}), 502

        # Trích xuất dữ liệu như cũ
        product = data['data']
        batch = product.get('batch_item_for_item_card_full', {})
        comm = product.get('commission_rate', {})

        result = {
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
        return jsonify(result)

    except Exception as e:
        # Bắt toàn bộ exception, in traceback vào log, trả về 502 kèm thông tin lỗi
        error_trace = traceback.format_exc()
        print(f"Unhandled exception: {error_trace}")
        return jsonify({
            'error': f'Lỗi máy chủ: {str(e)}',
            'traceback': error_trace  # Chỉ nên để debug, sau khi sửa lỗi có thể ẩn đi
        }), 502

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
