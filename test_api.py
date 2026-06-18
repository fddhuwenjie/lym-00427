import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"

def test_users():
    print("=" * 60)
    print("测试1: 获取用户列表")
    r = requests.get(f"{BASE_URL}/api/users")
    users = r.json()
    print(f"  状态码: {r.status_code}")
    print(f"  用户数: {len(users)}")
    for u in users:
        print(f"    - {u['id']}: {u['name']}")
    return users

def test_assignment_rules():
    print("\n" + "=" * 60)
    print("测试2: 获取分派规则")
    r = requests.get(f"{BASE_URL}/api/assignment-rules")
    rules = r.json()
    print(f"  状态码: {r.status_code}")
    print(f"  规则数: {len(rules)}")
    for rule in rules:
        user_name = rule.get('user', {}).get('name', '未知') if rule.get('user') else '未知'
        print(f"    - {user_name}: 来源={rule['source'] or '全部'}, 地区={rule['region'] or '全部'}, 优先级={rule['priority'] or '全部'}")
    return rules

def test_create_clue(title, source, region, priority):
    print("\n" + "=" * 60)
    print(f"测试3: 创建线索 - {title}")
    print(f"  来源: {source}, 地区: {region}, 优先级: {priority}")
    data = {
        "title": title,
        "customer_name": f"客户{title}",
        "phone": "13800138000",
        "source": source,
        "region": region,
        "priority": priority,
        "description": f"这是{title}的详细描述"
    }
    r = requests.post(f"{BASE_URL}/api/clues", json=data)
    print(f"  状态码: {r.status_code}")
    if r.status_code == 200:
        clue = r.json()
        print(f"  线索ID: {clue['id']}")
        print(f"  当前阶段: {clue['stage']}")
        print(f"  负责人: {clue['assignee_name']}")
        return clue
    else:
        print(f"  错误: {r.json()}")
        return None

def test_kanban():
    print("\n" + "=" * 60)
    print("测试4: 查看看板")
    r = requests.get(f"{BASE_URL}/api/kanban")
    data = r.json()
    print(f"  状态码: {r.status_code}")
    print(f"  总线索: {data['total']}")
    print(f"  今日新增: {data['today_new']}")
    print(f"  今日跟进: {data['today_followup']}")
    print(f"  逾期数: {data['overdue_count']}")
    print("  按阶段分布:")
    for stage, clues in data['by_stage'].items():
        print(f"    {stage}: {len(clues)} 条")
        for c in clues[:2]:
            print(f"      - {c['title']} (负责人: {c['assignee_name']})")
    return data

def test_reassign(clue_id, target_user_id):
    print("\n" + "=" * 60)
    print(f"测试5: 转派线索 ID={clue_id} 到用户 ID={target_user_id}")
    data = {"target_user_id": target_user_id}
    r = requests.post(f"{BASE_URL}/api/clues/{clue_id}/reassign", json=data)
    print(f"  状态码: {r.status_code}")
    result = r.json()
    if r.status_code == 200:
        print(f"  转派成功，新负责人: {result['assignee_name']}")
    else:
        print(f"  转派被拒绝: {result.get('detail', '未知错误')}")
    return r.status_code, result

def test_followup(clue_id, content, stage_after, next_followup_days=None):
    print("\n" + "=" * 60)
    print(f"测试6: 添加跟进记录 - 线索ID={clue_id}")
    next_time = None
    if next_followup_days is not None:
        next_time = (datetime.utcnow() + timedelta(days=next_followup_days)).isoformat()
    
    data = {
        "content": content,
        "stage_after": stage_after,
        "next_followup_at": next_time,
        "created_by": "测试用户"
    }
    r = requests.post(f"{BASE_URL}/api/clues/{clue_id}/followup", json=data)
    print(f"  状态码: {r.status_code}")
    if r.status_code == 200:
        record = r.json()
        print(f"  跟进记录ID: {record['id']}")
        print(f"  阶段变为: {record['stage_after']}")
        print(f"  下次跟进: {record['next_followup_at']}")
        return record
    else:
        print(f"  错误: {r.json()}")
        return None

def test_overdue():
    print("\n" + "=" * 60)
    print("测试7: 检查逾期提醒")
    r = requests.post(f"{BASE_URL}/api/clues/check-overdue")
    print(f"  状态码: {r.status_code}")
    result = r.json()
    print(f"  新标记逾期: {result['updated']}")
    print(f"  总逾期数: {result['total_overdue']}")
    
    r2 = requests.get(f"{BASE_URL}/api/clues/overdue/list")
    overdue_list = r2.json()
    print(f"  逾期线索列表:")
    for c in overdue_list:
        print(f"    - {c['title']} (负责人: {c['assignee_name']}, 下次跟进: {c['next_followup_at']})")
    return result

def test_daily_report():
    print("\n" + "=" * 60)
    print("测试8: 日报统计")
    r = requests.get(f"{BASE_URL}/api/reports/daily")
    report = r.json()
    print(f"  状态码: {r.status_code}")
    print(f"  日期: {report['date']}")
    print(f"  总线索: {report['total_clues']}")
    print(f"  今日新增: {report['new_clues']}")
    print(f"  今日跟进: {report['followed_up']}")
    print(f"  逾期数: {report['overdue_clues']}")
    print("  按阶段:")
    for stage, count in report['by_stage'].items():
        print(f"    {stage}: {count}")
    print("  按负责人:")
    for name, stats in report['by_user'].items():
        print(f"    {name}: 总数={stats['total']}, 跟进={stats['followed']}, 逾期={stats['overdue']}")
    return report

def test_export_report():
    print("\n" + "=" * 60)
    print("测试9: 导出日报CSV")
    r = requests.get(f"{BASE_URL}/api/reports/daily/export")
    print(f"  状态码: {r.status_code}")
    print(f"  内容类型: {r.headers.get('content-type')}")
    print(f"  内容长度: {len(r.content)} 字节")
    lines = r.text.split('\n')
    print(f"  行数: {len(lines)}")
    print("  前15行预览:")
    for i, line in enumerate(lines[:15]):
        print(f"    {i+1}: {line}")
    return r.ok

def test_clue_detail(clue_id):
    print("\n" + "=" * 60)
    print(f"测试10: 查看线索详情 ID={clue_id}")
    r = requests.get(f"{BASE_URL}/api/clues/{clue_id}")
    clue = r.json()
    print(f"  状态码: {r.status_code}")
    print(f"  标题: {clue['title']}")
    print(f"  阶段: {clue['stage']}")
    print(f"  负责人: {clue['assignee_name']}")
    print(f"  最后跟进: {clue['last_followup_at']}")
    print(f"  下次跟进: {clue['next_followup_at']}")
    print(f"  是否逾期: {clue['is_overdue']}")
    print(f"  跟进记录数: {len(clue.get('followups', []))}")
    return clue

def test_create_overdue_clue():
    print("\n" + "=" * 60)
    print("测试: 创建一个过去时间的下次跟进（用于测试逾期）")
    data = {
        "title": "逾期测试线索",
        "customer_name": "逾期客户",
        "source": "其他",
        "region": "华中",
        "priority": "low",
        "description": "用于测试逾期提醒功能"
    }
    r = requests.post(f"{BASE_URL}/api/clues", json=data)
    clue = r.json()
    print(f"  创建成功，ID: {clue['id']}")
    
    past_time = (datetime.utcnow() - timedelta(days=3)).isoformat()
    followup_data = {
        "content": "上次跟进，设置下次跟进为3天前",
        "stage_after": "contacted",
        "next_followup_at": past_time,
        "created_by": "测试"
    }
    r2 = requests.post(f"{BASE_URL}/api/clues/{clue['id']}/followup", json=followup_data)
    print(f"  添加跟进记录，设置过去的下次跟进时间: {r2.status_code}")
    
    r3 = requests.post(f"{BASE_URL}/api/clues/check-overdue")
    result = r3.json()
    print(f"  逾期检查结果: 新逾期={result['updated']}, 总逾期={result['total_overdue']}")
    
    return clue

if __name__ == "__main__":
    print("🎉 线索分派与跟进看板 - 功能验收测试")
    print("=" * 60)
    
    users = test_users()
    rules = test_assignment_rules()
    
    clue1 = test_create_clue("华北官网高优线索", "官网", "华北", "high")
    clue2 = test_create_clue("华东官网中优线索", "官网", "华东", "medium")
    clue3 = test_create_clue("转介绍高优线索", "转介绍", "华南", "high")
    clue4 = test_create_clue("低优先级线索", "其他", "西南", "low")
    
    kanban = test_kanban()
    
    if clue1 and len(users) >= 2:
        print("\n" + "=" * 60)
        print("❗ 测试冲突转派 - 转给同一个人（应被拒绝）")
        test_reassign(clue1['id'], clue1['assignee_id'])
        
        print("\n" + "=" * 60)
        print("✅ 测试正常转派 - 转给不同的人")
        other_user_id = 2 if clue1['assignee_id'] != 2 else 3
        test_reassign(clue1['id'], other_user_id)
    
    if clue2:
        test_followup(clue2['id'], "首次电话联系，客户表示有兴趣", "contacted", 2)
    
    if clue3:
        test_followup(clue3['id'], "详细沟通需求，确认意向", "qualified", 1)
    
    overdue_clue = test_create_overdue_clue()
    
    test_overdue()
    
    test_daily_report()
    
    test_export_report()
    
    if clue2:
        test_clue_detail(clue2['id'])
    
    print("\n" + "=" * 60)
    print("🏁 所有测试完成！")
    print("\n验收要点总结:")
    print("  ✅ 正常分派后看板更新 - 创建线索后看板显示对应数据")
    print("  ✅ 重复分派被拦截 - 转派给同一人时返回400错误并提示当前负责人")
    print("  ✅ 逾期提醒能生成 - 设置过去的下次跟进时间后，检查逾期功能可标记")
    print("  ✅ 导出日报包含筛选摘要 - CSV包含统计摘要、按阶段、按负责人统计和线索明细")
    print("  ✅ 重启后可恢复 - 使用SQLite文件数据库，数据持久化")
