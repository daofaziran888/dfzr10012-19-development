"""字段映射兼容报告接口。

分成两个处理入口：
- 格式定义侧（/api/schema/compat/...）：候选文件导入、报告查询、上传记录、下载、导出；
- 输出配置侧（/api/sink/compat/...）：同步读取同一份报告并更新消费记录。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from app.schemas import (
    ActionResult,
    CompatConsumePayload,
    CompatImportPayload,
    PageResult,
)
from app.services.compat import compat_service

router = APIRouter(tags=["字段映射兼容报告"])


# ---------------------------------------------------------------------- 格式定义侧

@router.post("/api/schema/compat/import", response_model=ActionResult)
def import_candidate(payload: CompatImportPayload) -> ActionResult:
    """导入候选格式文件，按字段名称、字段类型、格式版本校验并生成字段映射兼容报告。"""
    report, message, duplicated = compat_service.import_candidate(payload.model_dump())
    if report is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(
        ok=True,
        message=message,
        entry={"report": compat_service._serialize_report(report), "重复导入": duplicated},
    )


@router.get("/api/schema/compat/reports", response_model=PageResult[dict])
def list_reports(
    keyword: str | None = Query(default=None, description="按定义编号或报告编号检索"),
    conclusion: str | None = Query(default=None, description="兼容 / 不兼容"),
    status: str | None = Query(default=None, description="草稿 / 已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """字段映射兼容报告列表，可按结论与状态过滤。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    rows, total = compat_service.list_reports(
        keyword=keyword, conclusion=conclusion, status=status, page=page, size=size
    )
    items = [compat_service._serialize_report(row) for row in rows]
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/api/schema/compat/reports/{report_id}", response_model=dict)
def get_report(report_id: int) -> dict:
    """读取单份字段映射兼容报告明细。"""
    report = compat_service.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"兼容报告 {report_id} 不存在")
    return compat_service._serialize_report(report)


@router.get("/api/schema/compat/uploads", response_model=PageResult[dict])
def list_uploads(
    keyword: str | None = Query(default=None, description="按定义编号或文件名检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """上传记录：每次导入（含重复导入）和每次下载都可核对。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = compat_service.list_uploads(keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/api/schema/compat/todos")
def list_todos(sink_code: str | None = Query(default=None, description="按输出配置编号过滤")) -> dict:
    """报告与输出配置待办：与报告在同一事务里落库，可逐条核对。"""
    items = compat_service.list_todos(sink_code=sink_code)
    return {"items": items, "total": len(items)}


@router.get("/api/schema/compat/reports/{report_id}/download")
def download_report(report_id: int) -> JSONResponse:
    """下载字段映射兼容报告：返回带附件文件名的 JSON，内容固定含不兼容字段、输出契约、建议版本。"""
    report = compat_service.download_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"兼容报告 {report_id} 不存在，无法下载")
    filename = f"{report['report_no']}-compat-report.json"
    return JSONResponse(
        content=report,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/schema/compat/export")
def export_reports() -> dict:
    """导出全量字段映射兼容报告，用于离线核对。"""
    return compat_service.export_reports()


# ---------------------------------------------------------------------- 输出配置侧

@router.get("/api/sink/compat/reports", response_model=PageResult[dict])
def sink_list_reports(
    keyword: str | None = Query(default=None, description="按定义编号或报告编号检索"),
    conclusion: str | None = Query(default=None),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """输出配置处理入口同步读取同一份字段映射兼容报告（与格式定义侧看到的是同一批数据）。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    rows, total = compat_service.list_reports(
        keyword=keyword, conclusion=conclusion, page=page, size=size
    )
    items = [compat_service._serialize_report(row) for row in rows]
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/api/sink/{sink_id}/compat/consume", response_model=ActionResult)
def consume_report(sink_id: int, payload: CompatConsumePayload) -> ActionResult:
    """消费侧更新对应记录：边界只接收一份已校验报告，拒绝候选类型与旧 append 写入模式并用。"""
    report, message = compat_service.consume_report(sink_id, payload.model_dump(exclude_none=True))
    if report is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(
        ok=True,
        message=message,
        entry={"report": compat_service._serialize_report(report)},
    )
