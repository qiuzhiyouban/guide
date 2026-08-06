#!/usr/bin/env python3
"""
校信邦选号系统 - 号码同步 & 自动锁定脚本
功能：
1. 扫描表中所有记录，发现新提交的表单记录（状态为空/未设置的）
2. 将其信息合并到对应的可选号码记录上，标记为"已锁定"
3. 删除重复的表单提交记录
4. 导出所有"可选"号码到 numbers.json
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

# 字段名
F_NUMBER = "号码"
F_STATUS = "状态"
F_NAME = "选号人姓名"
F_PHONE = "选号人手机号"
F_TIME = "选号时间"

STATUS_AVAILABLE = "可选"
STATUS_LOCKED = "已锁定"

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


def get_all_records(token):
    """获取全部记录（自动翻页）"""
    records = []
    page_token = ""
    base_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/search"
    
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        
        body = json.dumps({}).encode("utf-8")
        
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
    
    return records


def get_field_text(value):
    """解析飞书字段的文本值（可能是数组 [{'text':'xxx'}] 或纯文本）"""
    if value is None:
        return ""
    if isinstance(value, list) and len(value) > 0:
        return value[0].get("text", "")
    return str(value)


def update_record(token, record_id, fields):
    """更新记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
    body = json.dumps({"fields": fields}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("code") != 0:
        raise Exception(f"更新记录失败: {result}")
    return result


def delete_record(token, record_id):
    """删除记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("code") != 0:
        raise Exception(f"删除记录失败: {result}")
    return result


def process_new_submissions(token, records):
    """
    处理新提交的表单记录：
    - 找到所有状态为空/未设置的记录（表单新提交的）
    - 找到对应号码的"可选"记录
    - 把信息合并过去，标记已锁定
    - 删除表单提交的重复记录
    """
    # 按号码分组
    by_number = {}
    for r in records:
        fields = r.get("fields", {})
        num = get_field_text(fields.get(F_NUMBER))
        status = get_field_text(fields.get(F_STATUS))
        if num not in by_number:
            by_number[num] = []
        by_number[num].append({"record": r, "status": status})
    
    locked_count = 0
    
    for num, entries in by_number.items():
        # 找可选的那条（原始号码记录）
        available_record = None
        # 找新提交的记录（状态为空）
        new_records = []
        
        for e in entries:
            if e["status"] == STATUS_AVAILABLE:
                available_record = e["record"]
            elif not e["status"] or e["status"] == "":
                new_records.append(e["record"])
        
        # 如果有新提交 + 有可选记录 → 合并锁定
        if available_record and new_records:
            # 取第一条新提交的信息
            new_record = new_records[0]
            new_fields = new_record.get("fields", {})
            
            name = get_field_text(new_fields.get(F_NAME))
            phone = get_field_text(new_fields.get(F_PHONE))
            
            # 更新可选记录
            update_fields = {
                F_STATUS: STATUS_LOCKED,
                F_TIME: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if name:
                update_fields[F_NAME] = name
            if phone:
                update_fields[F_PHONE] = phone
            
            update_record(token, available_record["record_id"], update_fields)
            print(f"  ✓ 锁定号码 {num}，客户：{name} ({phone})")
            
            # 删除所有重复的新提交记录
            for nr in new_records:
                delete_record(token, nr["record_id"])
                print(f"  ✓ 删除重复记录 {nr['record_id']}")
            
            locked_count += 1
    
    return locked_count


def export_available_numbers(token):
    """导出所有可选号码到 JSON"""
    records = get_all_records(token)
    numbers = []
    
    for r in records:
        fields = r.get("fields", {})
        status = get_field_text(fields.get(F_STATUS))
        if status == STATUS_AVAILABLE:
            num = get_field_text(fields.get(F_NUMBER))
            if num:
                numbers.append(num.strip())
    
    numbers.sort()
    return numbers


def main():
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        print("错误: 缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET 环境变量")
        sys.exit(1)
    
    if not BASE_TOKEN or not TABLE_ID:
        print("错误: 缺少 BASE_TOKEN 或 TABLE_ID 环境变量")
        sys.exit(1)
    
    print(f"开始处理... base={BASE_TOKEN}, table={TABLE_ID}")
    
    # 获取token
    token = get_tenant_access_token()
    print("✓ 获取access_token成功")
    
    # 获取全部记录
    all_records = get_all_records(token)
    print(f"✓ 共 {len(all_records)} 条记录")
    
    # 处理新提交
    print("正在处理新提交的选号申请...")
    locked = process_new_submissions(token, all_records)
    if locked > 0:
        print(f"✓ 本次新锁定 {locked} 个号码")
    else:
        print("  无新提交")
    
    # 导出可选号码
    print("正在导出可选号码...")
    numbers = export_available_numbers(token)
    print(f"✓ 当前可选 {len(numbers)} 个号码")
    
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
    print(f"::set-output name=locked::{locked}")


if __name__ == "__main__":
    main()
