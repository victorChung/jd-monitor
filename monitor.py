import json
import time
import random
import requests
from datetime import datetime
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 京东价格接口
PRICE_API = "https://p.3.cn/prices/mgets?skuIds=J_{}"

# 请求头，模拟真实浏览器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
    "Connection": "keep-alive",
}

def get_session_with_retries():
    """创建带重试机制的 requests Session"""
    session = requests.Session()
    retries = Retry(
        total=2,                       # 最多重试2次
        backoff_factor=1,             # 重试间隔 1s, 2s, 4s...
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_price_data(data_file):
    if Path(data_file).exists():
        with open(data_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_price_data(data, data_file):
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def fetch_current_price(sku_id, session=None):
    """获取当前价格（单位：元），带重试"""
    url = PRICE_API.format(sku_id)
    if session is None:
        session = get_session_with_retries()
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data and "p" in data[0]:
            return float(data[0]["p"])
    except Exception as e:
        print(f"获取商品 {sku_id} 价格失败: {e}")
    return None

def fetch_product_name(sku_id):
    """备用：从商品页面获取名称（如果 config 中没有提供 name）"""
    url = f"https://item.jd.com/{sku_id}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        import re
        title_match = re.search(r'<title>(.*?)</title>', resp.text)
        if title_match:
            title = title_match.group(1).strip()
            # 去除后缀 "【京东】" 等，取前50字符
            return title.split("-")[0][:50]
    except:
        pass
    return f"商品 {sku_id}"

def generate_html(items_info, output_file, threshold_ratio):
    """生成美观的 HTML 报告，修复了花括号转义问题"""
    # 注意：HTML 模板中的 { 和 } 全部双写转义，除了占位符
    html_template = """
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>京东自营图书降价监控</title>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f5f5f5;
                margin: 0;
                padding: 20px;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                padding: 20px;
            }}
            h1 {{
                color: #e4393c;
                border-left: 5px solid #e4393c;
                padding-left: 15px;
                margin-top: 0;
            }}
            .update-time {{
                color: #666;
                font-size: 0.9em;
                margin-bottom: 20px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
            }}
            th, td {{
                padding: 12px 15px;
                text-align: left;
                border-bottom: 1px solid #ddd;
            }}
            th {{
                background-color: #f2f2f2;
                font-weight: 600;
            }}
            tr:hover {{
                background-color: #f9f9f9;
            }}
            .triggered {{
                background-color: #ffe6e6 !important;
                font-weight: bold;
                color: #e4393c;
            }}
            .price-current {{
                font-weight: bold;
                color: #e4393c;
            }}
            .price-lowest {{
                color: #2c7a2c;
            }}
            .badge {{
                background-color: #ff9800;
                color: white;
                padding: 2px 8px;
                border-radius: 20px;
                font-size: 0.8em;
            }}
            footer {{
                margin-top: 30px;
                text-align: center;
                font-size: 0.8em;
                color: #999;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📚 京东自营图书降价监控</h1>
            <div class="update-time">最后更新：{update_time}</div>
            <table>
                <thead>
                    <tr>
                        <th>商品名称</th>
                        <th>当前价格 (¥)</th>
                        <th>历史最低价 (¥)</th>
                        <th>触发阈值 (¥)</th>
                        <th>状态</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
            <footer>触发条件：当前价格 < 历史最低价 × {threshold_ratio}<br>数据自动更新，每小时一次</footer>
        </div>
    </body>
    </html>
    """
    # 生成表格行
    if not items_info:
        rows_html = """
        <tr>
            <td colspan="5" style="text-align:center; color:#999;">暂无商品数据，请检查网络或稍后重试</td>
        </tr>
        """
    else:
        rows_html = ""
        for item in items_info:
            triggered = item["triggered"]
            row_class = 'class="triggered"' if triggered else ""
            status_text = "🔥 降价中" if triggered else "正常"
            rows_html += f"""
            <tr {row_class}>
                <td>{item["name"]}</td>
                <td class="price-current">¥{item["current_price"]:.2f}</td>
                <td class="price-lowest">¥{item["history_low"]:.2f}</td>
                <td>¥{item["history_low"] * item["threshold_ratio"]:.2f}</td>
                <td>{status_text}</td>
            </tr>
            """
    
    html_content = html_template.format(
        update_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        rows=rows_html,
        threshold_ratio=threshold_ratio
    )
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML 报告已生成：{output_file}")

def main():
    config = load_config()
    threshold_ratio = config["threshold_ratio"]
    items_config = config["items"]
    html_output = config["html_output"]
    data_file = config["data_file"]
    
    price_data = load_price_data(data_file)
    session = get_session_with_retries()   # 共享 session，复用连接
    
    items_info = []
    for idx, item_cfg in enumerate(items_config):
        sku_id = str(item_cfg["skuId"])
        name = item_cfg.get("name", fetch_product_name(sku_id))
        
        current_price = fetch_current_price(sku_id, session)
        if current_price is None:
            print(f"跳过 {name}，无法获取价格")
            continue
        
        # 获取历史最低价
        history_low = price_data.get(sku_id, {}).get("history_low", current_price)
        if current_price < history_low:
            history_low = current_price
            price_data[sku_id] = {
                "history_low": history_low,
                "last_update": datetime.now().isoformat()
            }
        
        triggered = current_price < (history_low * threshold_ratio)
        items_info.append({
            "name": name,
            "sku_id": sku_id,
            "current_price": current_price,
            "history_low": history_low,
            "threshold_ratio": threshold_ratio,
            "triggered": triggered
        })
        
        time.sleep(random.uniform(1, 2))   # 礼貌延时
    
    # 保存历史价格
    save_price_data(price_data, data_file)
    
    # 生成 HTML，传递 threshold_ratio 用于页脚显示
    generate_html(items_info, html_output, threshold_ratio)
    print("监控完成。")

if __name__ == "__main__":
    main()