# 实时流数据处理中心

面向实时数据处理团队的流式计算与管理中心。覆盖流数据源接入、流处理算子编排、窗口计算配置、状态后端管理、检查点恢复、反压监控、延迟追踪与流作业运维的完整实时计算链路。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 流数据源接入 | `streamin` | 流数据源 | 源编号、源名称、消息队列 |
| 流处理算子 | `operator` | 算子定义 | 算子编号、算子名称、输入流 |
| 窗口计算配置 | `window` | 窗口定义 | 窗口编号、数据流名称、窗口类型 |
| 状态后端管理 | `state` | 后端配置 | 配置编号、后端类型、存储路径 |
| 检查点恢复 | `checkpoint` | 检查点记录 | 记录编号、流作业名、检查点ID |
| 反压监控面板 | `backpress` | 反压指标 | 指标编号、流作业名、反压级别 |
| 延迟追踪管理 | `latency` | 延迟记录 | 记录编号、流作业名、端到端延迟 |
| 流作业运维 | `jobops` | 作业实例 | 实例编号、作业名称、运行节点 |
| 流数据输出端 | `sink` | 输出配置 | 配置编号、输出类型、目标地址 |
| 流数据格式定义 | `schema` | 格式定义 | 定义编号、流名称、字段名称 |
| 水位线管理 | `watermark` | 水位线配置 | 配置编号、流名称、时间字段 |
| 并行度调优 | `parallel` | 调优记录 | 记录编号、流算子名、当前并行度 |
| 流作业指标采集 | `metric` | 指标采集器 | 采集器编号、作业名称、指标名称 |
| 流告警规则 | `alarm` | 告警规则 | 规则编号、监控指标、告警条件 |
| 自定义函数库 | `udf` | 函数定义 | 函数编号、函数名称、输入参数 |
| 流处理日志中心 | `log` | 日志记录 | 记录编号、流作业名、日志级别 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 字段映射兼容报告

流数据格式定义新增候选版本的字段级兼容报告能力，代码在 `app/services/compat.py` 与
`app/routers/compat.py`，前端入口分别挂在「流数据格式定义」与「流数据输出端」页面。

- 候选格式文件只按**字段名称、字段类型、格式版本**三个要素，与同一定义编号下**已发布**
  字段逐条校验，生成字段映射兼容报告，报告固定保留**不兼容字段、输出契约和建议版本**。
- 同一格式文件（同字段/同版本指纹）重复导入只生效一次，每次导入与下载都在上传记录留痕。
- 字段类型冲突时同一定义编号只保留一份草稿兼容报告，旧草稿自动归档；报告与输出配置待办
  在同一事务里一起落库，任一步失败整体回滚。
- 输出配置侧（`/api/sink/.../compat/consume`）同步读取同一份报告并更新消费记录；处理边界
  只接收一份已校验的草稿报告，候选类型与 append 只读契约冲突时拒绝同时采用候选类型和旧
  写入模式，v1 契约保持可读。

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/schema/compat/import` | 导入候选格式文件并生成兼容报告 |
| GET | `/api/schema/compat/reports` | 兼容报告列表（可按结论/状态过滤） |
| GET | `/api/schema/compat/reports/{id}` | 报告明细（含不兼容字段、输出契约、建议版本） |
| GET | `/api/schema/compat/reports/{id}/download` | 下载报告（附件形式） |
| GET | `/api/schema/compat/uploads` | 上传/下载留痕记录 |
| GET | `/api/schema/compat/todos` | 报告与输出配置待办 |
| GET | `/api/schema/compat/export` | 导出全量兼容报告 |
| GET | `/api/sink/compat/reports` | 输出配置入口读取同一份报告 |
| POST | `/api/sink/{sink_id}/compat/consume` | 消费侧更新对应记录 |

验收脚本：`backend/tests/test_compat_acceptance.py`（依赖 `httpx`，用 TestClient 跑全链路）。
验收样例：SCHE-0002 的 amount 从 int 改为 string 后生成失败报告 rpt-19，SINK-0002 的
append 契约保持只读、消费被拒绝，v1 仍可读取。

领域：数据工程
子方向：数仓与数据湖
