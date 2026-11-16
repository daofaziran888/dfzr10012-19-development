import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const SINK_ENDPOINT = '/api/sink'
const COMPAT_ENDPOINT = '/api/sink/compat'

type SinkRow = {
  id: number
  配置编号: string
  写入模式: string
  契约模式: string
  契约版本: string
  关联格式: string
  status: string
}

type ReportRow = {
  id: number
  report_no: string
  定义编号: string
  候选版本: string
  生效版本: string
  建议版本: string
  结论: string
  状态: string
  消费状态: string
  输出契约: Array<Record<string, string>>
  消费记录: Array<Record<string, string>>
}

type TodoRow = Record<string, string | number | null>

/**
 * 输出配置处理入口：同步读取同一份字段映射兼容报告。
 * 边界只接收一份已校验的草稿报告；候选类型与 append 只读契约冲突时拒绝消费，
 * 不能同时采用候选类型和旧写入模式。
 */
export default function SinkCompatPanel() {
  const [sinks, setSinks] = useState<SinkRow[]>([])
  const [reports, setReports] = useState<ReportRow[]>([])
  const [todos, setTodos] = useState<TodoRow[]>([])
  const [selectedSink, setSelectedSink] = useState<number>(2)
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)

  const reload = useCallback(async () => {
    const [sinkResp, reportResp, todoResp] = await Promise.all([
      request(SINK_ENDPOINT),
      request(COMPAT_ENDPOINT),
      request('/api/schema/compat/todos'),
    ])
    if (sinkResp.ok) setSinks((await sinkResp.json()).items ?? [])
    if (reportResp.ok) setReports((await reportResp.json()).items ?? [])
    if (todoResp.ok) setTodos((await todoResp.json()).items ?? [])
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const currentSink = sinks.find((item) => item.id === selectedSink)

  async function consume(reportId: number) {
    setMessage('')
    const response = await request(`${SINK_ENDPOINT}/${selectedSink}/compat/consume`, {
      method: 'POST',
      body: JSON.stringify({ report_id: reportId, 消费方: '输出配置处理入口' }),
    })
    const payload = await response.json()
    setMessage(payload.message ?? '消费完成')
    setFailed(payload.ok !== true)
    await reload()
  }

  return (
    <section className="compat-panel">
      <h3>输出配置兼容消费</h3>
      <p className="page-desc">
        本入口与格式定义侧读取同一份字段映射兼容报告。处理边界只接收一份已校验的草稿报告；
        候选字段类型与已发布输出契约冲突时，append 只读契约会拒绝同时采用候选类型和旧写入模式。
      </p>

      <div className="filter-bar">
        <label className="filter-item">
          <span>输出配置</span>
          <select value={selectedSink} onChange={(event) => setSelectedSink(Number(event.target.value))}>
            {sinks.map((sink) => (
              <option key={sink.id} value={sink.id}>
                {sink.配置编号}（{sink.写入模式}/{sink.契约模式}/{sink.契约版本}）
              </option>
            ))}
          </select>
        </label>
      </div>

      {currentSink && (
        <p className="page-desc">
          当前输出端 {currentSink.配置编号}：关联格式 {currentSink.关联格式}，写入模式
          {currentSink.写入模式}，契约{currentSink.契约模式}，契约版本 {currentSink.契约版本}
        </p>
      )}

      {message && <p className={failed ? 'error-text' : 'ok-text'}>{message}</p>}

      <table className="data-table">
        <thead>
          <tr>
            <th>报告编号</th>
            <th>定义编号</th>
            <th>结论</th>
            <th>建议版本</th>
            <th>报告状态</th>
            <th>消费状态</th>
            <th>关联待办</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {reports.map((report) => {
            const sinkCode = currentSink?.配置编号
            const todo = todos.find(
              (item) => item.report_no === report.report_no && item.配置编号 === sinkCode,
            )
            const bound = Boolean(todo)
            return (
              <tr key={report.report_no}>
                <td>{report.report_no}</td>
                <td>{report.定义编号}</td>
                <td>{report.结论}</td>
                <td>{report.建议版本}</td>
                <td>{report.状态}</td>
                <td>{report.消费状态}</td>
                <td>{todo ? String(todo.状态) : '未关联'}</td>
                <td className="row-actions">
                  <button
                    className="link"
                    type="button"
                    disabled={!bound}
                    onClick={() => void consume(report.id)}
                  >
                    消费这份报告
                  </button>
                </td>
              </tr>
            )
          })}
          {reports.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={8}>暂无可读取的字段映射兼容报告</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
