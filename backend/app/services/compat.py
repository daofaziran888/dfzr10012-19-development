"""字段映射兼容报告业务规则。

候选格式文件导入后，只读取 SCHE 格式定义里的字段名称、字段类型、格式版本
三个要素，与同一定义编号下已发布（生效）的字段逐条比对，形成字段映射兼容报告。

关键约束：
- 同一格式文件重复导入只生效一次：用文件指纹去重，重复导入只回原报告并补一条上传记录；
- 字段类型冲突时同一定义编号只保留一份草稿兼容报告，旧草稿转为已归档；
- 报告与输出配置待办在一次事务里一起落库，任何一步失败全部回滚；
- 输出配置处理边界只能接收一份已校验报告，不能同时采用候选类型和旧写入模式。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.store import store

REPORT_MODULE = "compat_report"
UPLOAD_MODULE = "compat_upload"
TODO_MODULE = "compat_todo"

# 兼容结论只允许这两种：兼容 / 不兼容（失败报告）。
CONCLUSION_COMPATIBLE = "兼容"
CONCLUSION_INCOMPATIBLE = "不兼容"

REPORT_DRAFT = "草稿"
REPORT_ARCHIVED = "已归档"

# 字段映射结果。
MAPPING_MATCH = "一致"
MAPPING_TYPE_CONFLICT = "类型冲突"
MAPPING_MISSING = "生效契约缺失"
MAPPING_ADDED = "候选新增"

TODO_PENDING = "待处理"
TODO_DONE = "已消费"
TODO_CANCELED = "已取消"

SCHEMA_PUBLISHED = "已发布"


class CompatService:
    """兼容报告链路的全部状态流转都收在这里，路由层不做业务判断。"""

    # ------------------------------------------------------------------ 列表/明细

    def list_reports(
        self,
        *,
        keyword: str | None = None,
        conclusion: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(REPORT_MODULE)
        if keyword:
            rows = [r for r in rows if keyword in str(r.get("定义编号", "")) or keyword in str(r.get("report_no", ""))]
        if conclusion:
            rows = [r for r in rows if r.get("结论") == conclusion]
        if status:
            rows = [r for r in rows if r.get("状态") == status]
        rows = sorted(rows, key=lambda r: int(r.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def list_uploads(
        self,
        *,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(UPLOAD_MODULE)
        if keyword:
            rows = [r for r in rows if keyword in str(r.get("定义编号", "")) or keyword in str(r.get("文件名", ""))]
        rows = sorted(rows, key=lambda r: int(r.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def list_todos(self, *, sink_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(TODO_MODULE)
        if sink_code:
            rows = [r for r in rows if r.get("配置编号") == sink_code]
        return sorted(rows, key=lambda r: int(r.get("id", 0)), reverse=True)

    def get_report(self, report_id: int) -> dict[str, Any] | None:
        return store.find(REPORT_MODULE, report_id)

    def get_report_by_no(self, report_no: str) -> dict[str, Any] | None:
        for row in store.rows(REPORT_MODULE):
            if row.get("report_no") == report_no:
                return row
        return None

    # ------------------------------------------------------------------ 候选导入

    def import_candidate(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """导入候选格式文件并生成字段映射兼容报告。

        返回 (报告, 消息, 是否为重复导入)。校验不通过时报告为 None。
        """
        schema_code = str(payload.get("定义编号") or "").strip()
        candidate_version = str(payload.get("候选版本") or payload.get("格式版本") or "").strip()
        file_name = str(payload.get("文件名") or f"{schema_code}-{candidate_version}.json").strip()
        fields = payload.get("字段列表") or []

        missing: list[str] = []
        if not schema_code:
            missing.append("定义编号")
        if not candidate_version:
            missing.append("候选版本")
        if not isinstance(fields, list) or not fields:
            missing.append("字段列表")
        if missing:
            return None, f"候选格式文件缺少必填内容：{'、'.join(missing)}", False

        # 只读取字段名称、字段类型、格式版本三个要素，其余字段不参与兼容结论。
        candidate_fields: list[dict[str, str]] = []
        for item in fields:
            if not isinstance(item, dict):
                continue
            name = str(item.get("字段名称") or "").strip()
            field_type = str(item.get("字段类型") or "").strip()
            if not name or not field_type:
                return None, "候选字段必须同时给出字段名称和字段类型", False
            candidate_fields.append({"字段名称": name, "字段类型": field_type})
        if not candidate_fields:
            return None, "候选格式文件没有可校验的有效字段", False

        fingerprint = self._fingerprint(schema_code, candidate_version, candidate_fields)

        # 同一格式文件重复导入只生效一次：命中指纹直接回原报告。
        existed = self._find_by_fingerprint(fingerprint)
        if existed is not None:
            self._append_upload(file_name, schema_code, candidate_version, fingerprint, existed,
                                result="重复导入未生效")
            return existed, f"同一格式文件重复导入，兼容报告 {existed['report_no']} 已存在，本次不重复生效", True

        # 只覆盖已发布版本：取同一定义编号下生效（已发布）的字段契约。
        active_rows = [
            row for row in store.rows("schema")
            if str(row.get("定义编号") or "") == schema_code and row.get("status") == SCHEMA_PUBLISHED
        ]
        if not active_rows:
            # 导入动作仍留痕，但明确标记校验失败，不产生报告。
            self._append_upload(file_name, schema_code, candidate_version, fingerprint, None,
                                result="校验失败：无已发布版本")
            return None, f"定义编号 {schema_code} 没有已发布版本，无法形成候选兼容结论", False

        active_version = str(active_rows[0].get("格式版本") or "").strip()
        active_fields = {
            str(row.get("字段名称")): str(row.get("字段类型") or "").strip()
            for row in active_rows
        }

        field_mappings, incompatible_fields = self._build_field_mapping(candidate_fields, active_fields)
        output_contracts = self._build_output_contracts(schema_code)
        has_conflict = bool(incompatible_fields)
        conclusion = CONCLUSION_INCOMPATIBLE if has_conflict else CONCLUSION_COMPATIBLE
        # 失败报告建议继续停留在生效版本；兼容时候选版本可作为建议版本。
        suggested_version = active_version if has_conflict else candidate_version

        report = {
            "report_no": self._next_report_no(),
            "定义编号": schema_code,
            "流名称": str(active_rows[0].get("流名称") or ""),
            "候选版本": candidate_version,
            "生效版本": active_version,
            "建议版本": suggested_version,
            "结论": conclusion,
            "状态": REPORT_DRAFT,
            "文件指纹": fingerprint,
            "不兼容字段": incompatible_fields,
            "输出契约": output_contracts,
            "字段映射": field_mappings,
            "生成时间": self._now(),
            "消费状态": "未消费",
            "消费记录": [],
        }

        todos = self._build_todos(report)
        self._persist_atomically(report, todos)
        # 报告落库后再写上传记录，保证记录里的生效结果与报告编号都准确。
        self._append_upload(file_name, schema_code, candidate_version, fingerprint, report)
        return report, self._success_message(report), False

    def _build_field_mapping(
        self,
        candidate_fields: list[dict[str, str]],
        active_fields: dict[str, str],
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        mappings: list[dict[str, str]] = []
        incompatible: list[dict[str, str]] = []
        for field in candidate_fields:
            name = field["字段名称"]
            candidate_type = field["字段类型"]
            if name not in active_fields:
                result = MAPPING_ADDED
            elif candidate_type != active_fields[name]:
                result = MAPPING_TYPE_CONFLICT
            else:
                result = MAPPING_MATCH
            mapping = {
                "字段名称": name,
                "候选类型": candidate_type,
                "生效类型": active_fields.get(name, ""),
                "映射结果": result,
            }
            mappings.append(mapping)
            if result == MAPPING_TYPE_CONFLICT:
                incompatible.append(mapping)
        # 生效契约里有、候选里删掉的字段同样是不兼容项。
        candidate_names = {field["字段名称"] for field in candidate_fields}
        for name, active_type in active_fields.items():
            if name not in candidate_names:
                mapping = {
                    "字段名称": name,
                    "候选类型": "",
                    "生效类型": active_type,
                    "映射结果": MAPPING_MISSING,
                }
                mappings.append(mapping)
                incompatible.append(mapping)
        return mappings, incompatible

    def _build_output_contracts(self, schema_code: str) -> list[dict[str, Any]]:
        """读取该格式当前绑定的已发布输出契约，原样写进报告。"""
        contracts: list[dict[str, Any]] = []
        for row in store.rows("sink"):
            if str(row.get("关联格式") or "") != schema_code:
                continue
            if row.get("status") not in ("已启用", "已暂停"):
                continue
            contracts.append({
                "配置编号": row.get("配置编号"),
                "契约版本": row.get("契约版本"),
                "写入模式": row.get("写入模式"),
                "契约模式": row.get("契约模式"),
            })
        return contracts

    def _build_todos(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        """报告与输出配置待办必须一起落库：每个关联输出端一份待办。"""
        todos: list[dict[str, Any]] = []
        for contract in report["输出契约"]:
            todos.append({
                "report_id": None,  # 落库时补上报告主键
                "report_no": report["report_no"],
                "定义编号": report["定义编号"],
                "配置编号": contract["配置编号"],
                "结论": report["结论"],
                "状态": TODO_PENDING,
                "创建时间": report["生成时间"],
            })
        return todos

    def _persist_atomically(self, report: dict[str, Any], todos: list[dict[str, Any]]) -> None:
        """报告与待办在一次事务里写入：先做完全部准备，再统一落库；异常整体回滚。"""
        report_rows = store.rows(REPORT_MODULE)
        todo_rows = store.rows(TODO_MODULE)
        snapshot_report = [dict(row) for row in report_rows]
        snapshot_todo = [dict(row) for row in todo_rows]
        # 字段类型冲突时只保留一份草稿：同定义编号的旧草稿归档，并取消其未消费待办。
        archived_report_ids: list[int] = []
        try:
            for old in report_rows:
                if old.get("定义编号") == report["定义编号"] and old.get("状态") == REPORT_DRAFT:
                    old["状态"] = REPORT_ARCHIVED
                    archived_report_ids.append(int(old["id"]))
            for todo in todo_rows:
                if int(todo.get("report_id", 0)) in archived_report_ids and todo.get("状态") == TODO_PENDING:
                    todo["状态"] = TODO_CANCELED

            report["id"] = self._next_id(REPORT_MODULE)
            report_rows.append(report)
            for todo in todos:
                todo["report_id"] = report["id"]
                todo["id"] = self._next_id(TODO_MODULE)
                todo_rows.append(todo)
        except Exception:
            # 回滚到写入前快照，保证不会只落下报告或只落下待办。
            store._tables[REPORT_MODULE] = snapshot_report  # type: ignore[attr-defined]
            store._tables[TODO_MODULE] = snapshot_todo  # type: ignore[attr-defined]
            raise

    # ------------------------------------------------------------------ 下载/导出

    def download_report(self, report_id: int) -> dict[str, Any] | None:
        report = self.get_report(report_id)
        if report is None:
            return None
        # 下载动作在上传记录之外单独留痕，便于核对下载结果。
        store.rows(UPLOAD_MODULE).append({
            "id": self._next_id(UPLOAD_MODULE),
            "文件名": f"{report['report_no']}-字段映射兼容报告.json",
            "定义编号": report["定义编号"],
            "候选版本": report["候选版本"],
            "文件指纹": report["文件指纹"],
            "上传时间": self._now(),
            "生效结果": "已下载",
            "report_no": report["report_no"],
            "重复导入": False,
        })
        return self._serialize_report(report)

    def export_reports(self) -> dict[str, Any]:
        rows = sorted(store.rows(REPORT_MODULE), key=lambda r: int(r.get("id", 0)))
        return {
            "module": "compat_report",
            "total": len(rows),
            "items": [self._serialize_report(row) for row in rows],
        }

    def _serialize_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """报告对外结构：固定保留不兼容字段、输出契约和建议版本三块可核对内容。"""
        return {
            "id": report.get("id"),
            "report_no": report.get("report_no"),
            "定义编号": report.get("定义编号"),
            "流名称": report.get("流名称"),
            "候选版本": report.get("候选版本"),
            "生效版本": report.get("生效版本"),
            "建议版本": report.get("建议版本"),
            "结论": report.get("结论"),
            "状态": report.get("状态"),
            "文件指纹": report.get("文件指纹"),
            "生成时间": report.get("生成时间"),
            "消费状态": report.get("消费状态"),
            "消费记录": report.get("消费记录", []),
            "不兼容字段": report.get("不兼容字段", []),
            "输出契约": report.get("输出契约", []),
            "字段映射": report.get("字段映射", []),
        }

    # ------------------------------------------------------------------ 消费侧

    def consume_report(self, sink_id: int, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """另一个处理入口（输出配置侧）同步读取同一份兼容报告并更新消费记录。"""
        sink = store.find("sink", sink_id)
        if sink is None:
            return None, f"输出配置 {sink_id} 不存在或已归档"

        report_id = payload.get("report_id")
        report_no = str(payload.get("report_no") or "").strip()
        report = self.get_report(int(report_id)) if report_id is not None else self.get_report_by_no(report_no)
        if report is None:
            return None, "未找到对应字段映射兼容报告，请先在格式定义侧完成校验"
        if report.get("状态") != REPORT_DRAFT:
            return None, f"报告 {report['report_no']} 不是草稿状态，处理边界只接收一份已校验的草稿报告"

        # 输出配置处理边界只能接收与本输出端关联的那一份报告。
        todo = next(
            (item for item in store.rows(TODO_MODULE)
             if int(item.get("report_id", 0)) == int(report["id"])
             and item.get("配置编号") == sink.get("配置编号")),
            None,
        )
        if todo is None:
            return None, f"报告 {report['report_no']} 与输出配置 {sink.get('配置编号')} 未建立待办关联，拒绝跨边界消费"
        if todo.get("状态") == TODO_DONE:
            return None, f"报告 {report['report_no']} 在该输出配置上已消费，处理边界不能重复采用"

        # 候选字段类型与已发布输出契约冲突时，不能同时采用候选类型和旧写入模式（append 只读契约）。
        if report["结论"] == CONCLUSION_INCOMPATIBLE and sink.get("写入模式") == "append":
            return None, (
                f"报告 {report['report_no']} 存在不兼容字段，{sink.get('配置编号')} 的 append 契约为"
                "只读，不能同时采用候选类型和旧写入模式；请保持生效版本 v1 读取"
            )

        consumer = str(payload.get("消费方") or f"输出配置 {sink.get('配置编号')}")
        record = {
            "配置编号": sink.get("配置编号"),
            "写入模式": sink.get("写入模式"),
            "契约模式": sink.get("契约模式"),
            "采用版本": report["建议版本"],
            "消费时间": self._now(),
            "消费方": consumer,
        }
        report.setdefault("消费记录", []).append(record)
        report["消费状态"] = "已消费"
        todo["状态"] = TODO_DONE
        todo["消费时间"] = record["消费时间"]
        todo["采用版本"] = record["采用版本"]
        return report, f"输出配置 {sink.get('配置编号')} 已同步消费报告 {report['report_no']}，采用版本 {report['建议版本']}"

    # ------------------------------------------------------------------ 工具方法

    def _find_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        for row in store.rows(REPORT_MODULE):
            if row.get("文件指纹") == fingerprint:
                return row
        return None

    def _append_upload(
        self,
        file_name: str,
        schema_code: str,
        candidate_version: str,
        fingerprint: str,
        report: dict[str, Any] | None,
        *,
        result: str | None = None,
    ) -> dict[str, Any]:
        """追加一条上传记录；生效结果按实际情况标注，重复导入与校验失败都如实留痕。"""
        if result is None:
            result = "已生成兼容报告"
        upload = {
            "id": self._next_id(UPLOAD_MODULE),
            "文件名": file_name,
            "定义编号": schema_code,
            "候选版本": candidate_version,
            "文件指纹": fingerprint,
            "上传时间": self._now(),
            "生效结果": result,
            "report_no": report["report_no"] if report is not None else None,
            "重复导入": result.startswith("重复导入"),
        }
        store.rows(UPLOAD_MODULE).append(upload)
        return upload

    @staticmethod
    def _fingerprint(schema_code: str, version: str, fields: list[dict[str, str]]) -> str:
        # 指纹只由字段名称、字段类型和格式版本决定，和文件本身无关，保证同内容文件只生效一次。
        basis = "|".join(f"{item['字段名称']}:{item['字段类型']}" for item in fields)
        raw = f"{schema_code}#{version}#{basis}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1

    def _next_report_no(self) -> str:
        # 报告编号与表主键共用同一自增序列，预置 18 条后下一份即 rpt-19。
        return f"rpt-{self._next_id(REPORT_MODULE):02d}"

    @staticmethod
    def _success_message(report: dict[str, Any]) -> str:
        if report["结论"] == CONCLUSION_INCOMPATIBLE:
            names = "、".join(item["字段名称"] for item in report["不兼容字段"])
            return f"兼容报告 {report['report_no']} 生成完成：存在不兼容字段 {names}，建议维持 {report['建议版本']}"
        return f"兼容报告 {report['report_no']} 生成完成：候选与生效字段全部兼容，建议版本 {report['建议版本']}"


compat_service = CompatService()
