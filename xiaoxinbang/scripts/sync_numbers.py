#!/usr/bin/env python3
"""
校信邦选号系统 - 号码同步脚本
从飞书多维表拉取"可选"状态的号码，生成 numbers.json 供前端使用
由 GitHub Actions 定时触发（每5分钟）
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime

# 配置
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
BASE_TOKEN = os.environ.get("BASE_TOKEN", "")
TABLE_ID = os.environ.get("TABLE_ID", "")
NUMBER_FIELD = os.environ.get("NUMBER_FIELD", "号码")
STATUS_FIELD = os.environ.get("STATUS_FIELD", "状态")
AVAILABLE_STATUS = os.environ.get("AVAILABLE_STATUS", "可选")
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "numbers.json")


def get_tenant_access_token():
    """获取飞书 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("code") != 0:
        raise Exception(f"获取token失败: {result}")
    return result["tenant_access_token"]


def get_available_numbers(token):
    """获取全部可选号码（自动翻页）"""
    records = []
    page_token = ""
    base_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/search"
    
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        
        body = json.dumps({
            "filter": {
                "conjunction": "and",
                "conditions": [{
                    "field_name": STATUS_FIELD,
                    "operator": "is",
                    "value": [AVAILABLE_STATUS]
                }]
            }
        }).encode("utf-8")
        
        url = base_url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        
        if result.get("code") != 0:
            raise Exception(f"获取记录失败: {result}")
        
        data = result.get("data", {})
        records.extend(data.get("items", []))
        
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    
    # 解析号码
    numbers = []
    for r in records:
        fields = r.get("fields", {})
        num_val = fields.get(NUMBER_FIELD, "")
        # 飞书文本字段是数组格式 [{'text': 'xxx', 'type': 'text'}]
        if isinstance(num_val, list) and len(num_val) > 0:
            num_val = num_val[0].get("text", "")
        if num_val:
            numbers.append(str(num_val).strip())
    
    numbers.sort()
    return numbers


def main():
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("错误: 缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET 环境变量")
        sys.exit(1)
    
    if not BASE_TOKEN or not TABLE_ID:
        print("错误: 缺少 BASE_TOKEN 或 TABLE_ID 环境变量")
        sys.exit(1)
    
    print(f"开始同步号码... base={BASE_TOKEN}, table={TABLE_ID}")
    
    # 获取token
    token = get_tenant_access_token()
    print("✓ 获取access_token成功")
    
    # 获取可选号码
    numbers = get_available_numbers(token)
    print(f"✓ 获取到 {len(numbers)} 个可选号码")
    
    # 写入JSON
    output = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(numbers),
        "numbers": numbers
    }
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✓ 已写入 {OUTPUT_FILE}")
    print(f"::set-output name=total::{len(numbers)}")


if __name__ == "__main__":
    main()
