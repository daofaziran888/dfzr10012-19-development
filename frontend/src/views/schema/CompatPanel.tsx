import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/schema/compat'

type ReportRow = {
  id: number
  report_no: string
  定义编号: string
  流名称: string
  候选版本: string
  生效版本: string
  建议版本: string
  结论: string
  状态: string
  生成时间: string
  消费状态: string
  不兼容字段: Array<Record<string, string>>
  输出契约: Array<Record<string, string>>
  字段映射: Array<Record<string, string>>
}

type UploadRow = Record<string, string | number | boolean | null>

const reportColumns = [
  '报告编号',
  '定义编号',
  '候选版本',
  '生效版本',
  '建议版本',
  '结论',
  '状态',
  '消费状态',
  '生成时间',
]

export default function CompatPanel() {
  const [reports, setReports] = useState<ReportRow[]>([])
  const [uploads, setUploads] = useState<UploadRow[]>([])
  const [keyword, setKeyword] = useState('')
  const [conclusion, setConclusion] = useState('')
  const [detail, setDetail] = useState<ReportRow | null>(null)
  const [message, setMessage] = useState('')

  // 候选导入表单：只收字段名称、字段类型和格式版本三个要素。
  const [schemaCode, setSchemaCode] = useState('SCHE-0002')
  const [candidateVersion, setCandidateVersion] = useState('v2')
  const [fileName, setFileName] = useState('payment-v2.json')
  const [fieldText, setFieldText] = useState(
    'payment_id:string\namount:string\ncurrency:string',
  )

  const reload = useCallback(async () => {
    const query = new URLSearchParams()
    if (keyword) query.set('keyword', keyword)
    if (conclusion) query.set('conclusion', conclusion)
    const [reportResp, uploadResp] = await Promise.all([
      request(`${ENDPOINT}/reports?${query.toString()}`),
      request(`${ENDPOINT}/uploads`),
    ])
    if (reportResp.ok) setReports((await reportResp.json()).items ?? [])
    if (uploadResp.ok) setUploads((await uploadResp.json()).items ?? [])
  }, [keyword, conclusion])

  useEffect(() => {
    void reload()
  }, [reload])

  async function handleImport() {
    setMessage('')
    const fields = fieldText
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [字段名称, 字段类型] = line.split(':').map((part) => part.trim())
        return { 字段名称, 字段类型 }
      })
    if (fields.some((field) => !field.字段名称 || !field.字段类型)) {
      setMessage('字段清单格式应为「字段名称:字段类型」，每行一个字段')
      return
    }
    const response = await request(`${ENDPOINT}/import`, {
      method: 'POST',
      body: JSON.stringify({
        定义编号: schemaCode,
        候选版本: candidateVersion,
        文件名: fileName || undefined,
        字段列表: fields,
      }),
    })
    const payload = await response.json()
    setMessage(payload.message ?? '导入完成')
    if (payload.ok) setDetail(payload.entry.report)
    await reload()
  }

  async function openDetail(id: number) {
    const response = await request(`${ENDPOINT}/reports/${id}`)
    if (response.ok) setDetail(await response.json())
  }

  return (
    <section className="compat-panel">
      <h3>字段映射兼容报告</h3>
      <p className="page-desc">
        导入候选格式文件后按字段名称、字段类型、格式版本与已发布字段校验，生成可下载的字段映射兼容报告；
        报告保留不兼容字段、输出契约和建议版本，同一文件重复导入只生效一次。
      </p>

      <div className="compat-import">
        <label className="filter-item">
          <span>定义编号</span>
          <input value={schemaCode} onChange={(e) => setSchemaCode(e.target.value)} />
        </label>
        <label className="filter-item">
          <span>候选版本</span>
          <input value={candidateVersion} onChange={(e) => setCandidateVersion(e.target.value)} />
        </label>
        <label className="filter-item">
          <span>文件名</span>
          <input value={fileName} onChange={(e) => setFileName(e.target.value)} />
        </label>
        <label className="filter-item compat-fields">
          <span>候选字段（字段名称:字段类型，每行一条）</span>
          <textarea rows={4} value={fieldText} onChange={(e) => setFieldText(e.target.value)} />
        </label>
        <button className="btn primary" type="button" onClick={() => void handleImport()}>
          导入并校验候选格式
        </button>
      </div>

      <div className="filter-bar">
        <label className="filter-item">
          <span>定义编号/报告编号</span>
          <input
            value={keyword}
            placeholder="按定义编号或报告编号检索"
            onChange={(e) => setKeyword(e.target.value)}
          />
        </label>
        <label className="filter-item">
          <span>兼容结论</span>
          <select value={conclusion} onChange={(e) => setConclusion(e.target.value)}>
            <option value="">全部</option>
            <option value="兼容">兼容</option>
            <option value="不兼容">不兼容</option>
          </select>
        </label>
        <button className="btn" type="button" onClick={() => void reload()}>查询</button>
        <button
          className="btn ghost"
          type="button"
          onClick={() => { setKeyword(''); setConclusion('') }}
        >
          重置条件
        </button>
        <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
          导出兼容报告
        </button>
      </div>

      {message && <p className="error-text">{message}</p>}

      <table className="data-table">
        <thead>
          <tr>
            {reportColumns.map((column) => <th key={column}>{column}</th>)}
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {reports.map((row) => (
            <tr key={row.report_no}>
              <td>{row.report_no}</td>
              <td>{row.定义编号}</td>
              <td>{row.候选版本}</td>
              <td>{row.生效版本}</td>
              <td>{row.建议版本}</td>
              <td>{row.结论}</td>
              <td>{row.状态}</td>
              <td>{row.消费状态}</td>
              <td>{row.生成时间}</td>
              <td className="row-actions">
                <button className="link" type="button" onClick={() => void openDetail(row.id)}>查看报告</button>
                <button
                  className="link"
                  type="button"
                  onClick={() => window.open(`${ENDPOINT}/reports/${row.id}/download`, '_blank')}
                >
                  下载报告
                </button>
              </td>
            </tr>
          ))}
          {reports.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={reportColumns.length + 1}>暂无字段映射兼容报告</td>
            </tr>
          )}
        </tbody>
      </table>

      <h4>上传记录（含重复导入与下载留痕）</h4>
      <table className="data-table">
        <thead>
          <tr>
            <th>文件名</th>
            <th>定义编号</th>
            <th>候选版本</th>
            <th>文件指纹</th>
            <th>上传时间</th>
            <th>生效结果</th>
            <th>关联报告</th>
          </tr>
        </thead>
        <tbody>
          {uploads.map((row) => (
            <tr key={String(row.id)}>
              <td>{row.文件名 ?? '—'}</td>
              <td>{row.定义编号 ?? '—'}</td>
              <td>{row.候选版本 ?? '—'}</td>
              <td>{String(row.文件指纹 ?? '—').slice(0, 12)}</td>
              <td>{row.上传时间 ?? '—'}</td>
              <td>{row.生效结果 ?? '—'}</td>
              <td>{row.report_no ?? '—'}</td>
            </tr>
          ))}
          {uploads.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={7}>暂无上传记录</td>
            </tr>
          )}
        </tbody>
      </table>

      {detail && (
        <div className="compat-detail" role="dialog">
          <div className="compat-detail-head">
            <h4>报告明细 {detail.report_no}</h4>
            <button className="btn ghost" type="button" onClick={() => setDetail(null)}>关闭</button>
          </div>
          <p>
            结论：{detail.结论} ｜ 建议版本：{detail.建议版本} ｜ 生效版本：{detail.生效版本}
          </p>
          <h5>不兼容字段</h5>
          {detail.不兼容字段.length === 0 ? (
            <p>无不兼容字段</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>字段名称</th><th>候选类型</th><th>生效类型</th><th>映射结果</th></tr>
              </thead>
              <tbody>
                {detail.不兼容字段.map((field) => (
                  <tr key={field.字段名称}>
                    <td>{field.字段名称}</td>
                    <td>{field.候选类型 || '—'}</td>
                    <td>{field.生效类型 || '—'}</td>
                    <td>{field.映射结果}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h5>输出契约</h5>
          <table className="data-table">
            <thead>
              <tr><th>配置编号</th><th>契约版本</th><th>写入模式</th><th>契约模式</th></tr>
            </thead>
            <tbody>
              {detail.输出契约.map((contract) => (
                <tr key={String(contract.配置编号)}>
                  <td>{contract.配置编号}</td>
                  <td>{contract.契约版本}</td>
                  <td>{contract.写入模式}</td>
                  <td>{contract.契约模式}</td>
                </tr>
              ))}
              {detail.输出契约.length === 0 && (
                <tr><td className="empty-state" colSpan={4}>无关联输出契约</td></tr>
              )}
            </tbody>
          </table>
          <h5>全部字段映射</h5>
          <table className="data-table">
            <thead>
              <tr><th>字段名称</th><th>候选类型</th><th>生效类型</th><th>映射结果</th></tr>
            </thead>
            <tbody>
              {detail.字段映射.map((field) => (
                <tr key={field.字段名称}>
                  <td>{field.字段名称}</td>
                  <td>{field.候选类型 || '—'}</td>
                  <td>{field.生效类型 || '—'}</td>
                  <td>{field.映射结果}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
