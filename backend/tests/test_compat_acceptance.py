"""字段映射兼容报告链路的端到端验收脚本。

覆盖需求里的全部可核对点：
1. SCHE-0002 的 amount 从 int 改为 string 后生成失败报告 rpt-19，
   报告保留不兼容字段、输出契约和建议版本；
2. 同一格式文件重复导入只生效一次（文件指纹去重，上传记录留痕）；
3. 字段类型冲突时同一定义编号只保留一份草稿兼容报告，旧草稿归档；
4. 报告与输出配置待办在一次事务里一起落库；
5. 上传记录、导出内容、下载结果可核对；
6. 另一个处理入口（输出配置侧）同步读取同一份报告，消费侧更新对应记录；
7. 候选字段类型与已发布输出契约冲突时，append 只读契约拒绝同时采用
   候选类型和旧写入模式，SINK-0002 仍按 v1 读取；
8. 完全兼容的候选给出兼容结论与候选建议版本。
"""
from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
failures: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" -> {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(f"{name}: {detail}")


def import_candidate(schema_code: str, version: str, fields: list[dict[str, str]], file_name: str | None = None):
    payload = {"定义编号": schema_code, "候选版本": version, "字段列表": fields}
    if file_name:
        payload["文件名"] = file_name
    return client.post("/api/schema/compat/import", json=payload)


# ------------------------------------------------------------ 场景 1：验收样例 rpt-19

candidate_v2 = [
    {"字段名称": "payment_id", "字段类型": "string"},
    {"字段名称": "amount", "字段类型": "string"},   # 生效契约里是 int
    {"字段名称": "currency", "字段类型": "string"},
]
resp = import_candidate("SCHE-0002", "v2", candidate_v2, "payment-v2.json")
body = resp.json()
check("导入接口返回成功", resp.status_code == 200 and body["ok"] is True, body)
report19 = body["entry"]["report"]
check("失败报告编号为 rpt-19", report19["report_no"] == "rpt-19", report19["report_no"])
check("兼容结论为不兼容", report19["结论"] == "不兼容", report19["结论"])

incompatible = report19["不兼容字段"]
check("报告保留不兼容字段 amount", len(incompatible) == 1 and incompatible[0]["字段名称"] == "amount", incompatible)
check("不兼容字段记录候选/生效类型",
      incompatible[0]["候选类型"] == "string" and incompatible[0]["生效类型"] == "int", incompatible)
check("不兼容字段标注为类型冲突", incompatible[0]["映射结果"] == "类型冲突", incompatible)

contracts = report19["输出契约"]
sink0002 = next((c for c in contracts if c["配置编号"] == "SINK-0002"), None)
check("报告保留输出契约 SINK-0002", sink0002 is not None, contracts)
check("SINK-0002 为 append 写入模式", sink0002 and sink0002["写入模式"] == "append", sink0002)
check("SINK-0002 append 契约保持只读", sink0002 and sink0002["契约模式"] == "只读", sink0002)

check("报告保留建议版本", report19["建议版本"] == "v1", report19["建议版本"])
check("生效版本仍为 v1 可读取", report19["生效版本"] == "v1", report19["生效版本"])
check("报告状态为草稿", report19["状态"] == "草稿", report19["状态"])

mapping = {m["字段名称"]: m for m in report19["字段映射"]}
check("字段映射覆盖全部候选字段",
      all(name in mapping for name in ("payment_id", "amount", "currency")), report19["字段映射"])
check("未冲突字段映射结果为一致", mapping["payment_id"]["映射结果"] == "一致", mapping["payment_id"])

# ------------------------------------------------------------ 场景 2：重复导入只生效一次

resp_dup = import_candidate("SCHE-0002", "v2", candidate_v2, "payment-v2-copy.json")
dup_body = resp_dup.json()
check("重复导入接口仍返回 ok", dup_body["ok"] is True, dup_body)
check("重复导入标记为重复", dup_body["entry"]["重复导入"] is True, dup_body)
check("重复导入回原报告 rpt-19", dup_body["entry"]["report"]["report_no"] == "rpt-19", dup_body)

reports = client.get("/api/schema/compat/reports").json()
check("重复导入不新增报告（仍为 19 条）", reports["total"] == 19, reports["total"])

uploads = client.get("/api/schema/compat/uploads").json()["items"]
check("两次导入各留一条上传记录", len(uploads) == 2, len(uploads))
check("首条记录标记已生成兼容报告", any(u["生效结果"] == "已生成兼容报告" for u in uploads), uploads)
check("重复导入记录标记未生效", any(u["重复导入"] is True and u["生效结果"] == "重复导入未生效" for u in uploads), uploads)
check("上传记录带文件指纹", all(u["文件指纹"] for u in uploads), uploads)

# ------------------------------------------------------------ 场景 3：类型冲突只保留一份草稿

candidate_v2b = [
    {"字段名称": "payment_id", "字段类型": "string"},
    {"字段名称": "amount", "字段类型": "double"},  # 又一种冲突类型
    {"字段名称": "currency", "字段类型": "string"},
]
resp_b = import_candidate("SCHE-0002", "v2", candidate_v2b, "payment-v2b.json")
report_b = resp_b.json()["entry"]["report"]
check("第二份冲突报告生成", report_b["report_no"] == "rpt-20", report_b["report_no"])

drafts = [r for r in client.get("/api/schema/compat/reports", params={"status": "草稿"}).json()["items"]
          if r["定义编号"] == "SCHE-0002"]
check("同一格式只保留一份草稿", len(drafts) == 1 and drafts[0]["report_no"] == "rpt-20", drafts)

old = client.get("/api/schema/compat/reports/19").json()
check("旧草稿 rpt-19 已归档", old["状态"] == "已归档", old["状态"])

# ------------------------------------------------------------ 场景 4：报告与待办一起落库

todos = client.get("/api/schema/compat/todos").json()["items"]
todos_20 = [t for t in todos if t["report_no"] == "rpt-20"]
check("新报告与输出配置待办一起落库", len(todos_20) >= 1 and all(t["状态"] == "待处理" for t in todos_20), todos_20)
bound_sinks = {t["配置编号"] for t in todos_20}
check("待办按输出契约逐端生成", bound_sinks == {"SINK-0002"}, todos_20)
todos_19 = [t for t in todos if t["report_no"] == "rpt-19"]
check("旧草稿待办随归档一并取消", todos_19 and all(t["状态"] == "已取消" for t in todos_19), todos_19)

# ------------------------------------------------------------ 场景 5：导出与下载可核对

exported = client.get("/api/schema/compat/export").json()
exp19 = next((r for r in exported["items"] if r["report_no"] == "rpt-19"), None)
check("导出清单包含 rpt-19", exp19 is not None)
check("导出内容含不兼容字段/输出契约/建议版本",
      exp19 and exp19["不兼容字段"] and exp19["输出契约"] and exp19["建议版本"], exp19)

dl = client.get("/api/schema/compat/reports/19/download")
check("下载返回 200 且带附件头",
      dl.status_code == 200 and "attachment" in dl.headers.get("content-disposition", ""), dl.headers)
dl_body = dl.json()
check("下载结果含不兼容字段、输出契约、建议版本",
      dl_body["不兼容字段"][0]["字段名称"] == "amount"
      and any(c["配置编号"] == "SINK-0002" for c in dl_body["输出契约"])
      and dl_body["建议版本"] == "v1", dl_body)
uploads_after_dl = client.get("/api/schema/compat/uploads").json()["items"]
check("下载动作在上传记录表留痕", any(u["生效结果"] == "已下载" for u in uploads_after_dl), uploads_after_dl)

# ------------------------------------------------------------ 场景 6：另一个入口读同一份报告

sink_view = client.get("/api/sink/compat/reports", params={"keyword": "SCHE-0002"}).json()
check("输出配置入口同步读到同一份报告",
      any(r["report_no"] == "rpt-20" for r in sink_view["items"]), sink_view["total"])

# 已归档报告不能被消费（边界只接收一份已校验的草稿报告）
stale = client.post("/api/sink/2/compat/consume", json={"report_no": "rpt-19"})
check("已归档报告被消费边界拒绝", stale.status_code == 200 and stale.json()["ok"] is False, stale.json())

# 候选类型与 append 只读契约冲突：不能同时采用候选类型和旧写入模式
blocked = client.post("/api/sink/2/compat/consume", json={"report_id": report_b["id"]})
blocked_body = blocked.json()
check("append 只读契约拒绝冲突报告", blocked_body["ok"] is False, blocked_body)
check("拒绝原因写明旧写入模式冲突", "append" in blocked_body["message"] and "只读" in blocked_body["message"], blocked_body)

# 待办仍然存在，报告未被消费
todo_still = [t for t in client.get("/api/schema/compat/todos", params={"sink_code": "SINK-0002"}).json()["items"]
              if t["report_no"] == "rpt-20"]
check("被拒绝后待办保持待处理", todo_still and todo_still[0]["状态"] == "待处理", todo_still)

# SINK-0002 本身没有被改动，v1 契约仍可读取
sink0002_row = client.get("/api/sink/2").json()
check("SINK-0002 仍为已启用 append 只读",
      sink0002_row["写入模式"] == "append" and sink0002_row["契约模式"] == "只读"
      and sink0002_row["契约版本"] == "v1", sink0002_row)

# 兼容报告可以被正常消费：用 SCHE-0001 全兼容候选 + SINK-0001（upsert 可读写）
ok_payload = [
    {"字段名称": "order_id", "字段类型": "string"},
    {"字段名称": "order_time", "字段类型": "timestamp"},
]
ok_resp = import_candidate("SCHE-0001", "v2", ok_payload, "order-v2.json")
ok_report = ok_resp.json()["entry"]["report"]
check("全兼容候选结论为兼容", ok_report["结论"] == "兼容", ok_report)
check("兼容候选建议版本为 v2", ok_report["建议版本"] == "v2", ok_report)
check("兼容报告不兼容字段为空", ok_report["不兼容字段"] == [], ok_report)

consume = client.post("/api/sink/1/compat/consume", json={"report_id": ok_report["id"], "消费方": "消费侧批处理任务"})
consume_body = consume.json()
check("兼容报告消费成功", consume_body["ok"] is True, consume_body)
check("消费侧更新采用版本", consume_body["entry"]["report"]["建议版本"] == "v2", consume_body)
check("报告消费状态更新为已消费",
      consume_body["entry"]["report"]["消费状态"] == "已消费"
      and consume_body["entry"]["report"]["消费记录"], consume_body["entry"]["report"])

done_todo = [t for t in client.get("/api/schema/compat/todos", params={"sink_code": "SINK-0001"}).json()["items"]
             if t["report_no"] == ok_report["report_no"]]
check("待办同步更新为已消费", done_todo and done_todo[0]["状态"] == "已消费", done_todo)

# 同一份报告不能在同一输出端重复消费
again = client.post("/api/sink/1/compat/consume", json={"report_id": ok_report["id"]})
check("报告不能在同一输出端重复消费", again.json()["ok"] is False, again.json())

# 跨边界消费：拿 SINK-0001 的报告去 SINK-0002 消费，应被拒绝
cross = client.post("/api/sink/2/compat/consume", json={"report_id": ok_report["id"]})
check("未建立待办关联的跨边界消费被拒绝", cross.json()["ok"] is False, cross.json())

# ------------------------------------------------------------ 场景 7：入参校验

bad = client.post("/api/schema/compat/import", json={"定义编号": "SCHE-0002", "候选版本": "v3", "字段列表": []})
check("空字段列表被拦下", bad.json()["ok"] is False, bad.json())
no_active = import_candidate("SCHE-9999", "v1", [{"字段名称": "x", "字段类型": "int"}])
check("无已发布版本时拒绝出报告", no_active.json()["ok"] is False, no_active.json())

# ------------------------------------------------------------ 汇总

print()
if failures:
    print(f"共 {len(failures)} 项失败：")
    for item in failures:
        print(" -", item)
    sys.exit(1)
print("全部验收项通过。")
