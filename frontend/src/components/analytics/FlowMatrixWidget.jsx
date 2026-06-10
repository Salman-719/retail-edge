import React, { useState } from 'react'
import { Sankey, Tooltip, ResponsiveContainer } from 'recharts'
import { getFlowMatrix } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { DataTable } from './widgetParts'
import { toCsv, downloadCsv } from '../../lib/csv'
import { formatNumber, formatRatio } from '../../lib/format'

const zoneLabel = (name, kind) => name || (kind === 'from' ? '(entry)' : '(exit)')

export default function FlowMatrixWidget({ slug, from, to }) {
  const [view, setView] = useState('table')
  const { data, loading, error } = useAnalyticsQuery(
    () => getFlowMatrix(slug, { from, to }),
    [slug, from, to],
  )
  const rows = data?.rows || []

  // Sankey needs an acyclic node/link graph: drop self-loops and null endpoints.
  const sankeyRows = rows.filter((r) => r.from_zone_id && r.to_zone_id && r.from_zone_id !== r.to_zone_id)
  const names = [...new Set(sankeyRows.flatMap((r) => [r.from_zone_name, r.to_zone_name]))]
  const idx = Object.fromEntries(names.map((n, i) => [n, i]))
  const sankeyData = {
    nodes: names.map((n) => ({ name: n })),
    links: sankeyRows.map((r) => ({ source: idx[r.from_zone_name], target: idx[r.to_zone_name], value: r.transition_count })),
  }

  function exportCsv() {
    downloadCsv(`flow-matrix_${from}_${to}.csv`, toCsv(rows, [
      { key: 'from_zone_name', label: 'from' },
      { key: 'to_zone_name', label: 'to' },
      { key: 'transition_count', label: 'count' },
      { key: 'probability', label: 'probability' },
    ]))
  }

  return (
    <WidgetFrame
      title="Zone Flow"
      views={[{ key: 'table', label: 'Matrix' }, { key: 'sankey', label: 'Sankey' }]}
      view={view} onView={setView}
      onExport={exportCsv}
      loading={loading} error={error} isEmpty={!rows.length}
    >
      {view === 'sankey' ? (
        sankeyData.links.length ? (
          <ResponsiveContainer width="100%" height={320}>
            <Sankey
              data={sankeyData}
              nodePadding={24}
              link={{ stroke: '#93c5fd' }}
              node={{ fill: '#3b82f6' }}
              margin={{ top: 8, right: 80, bottom: 8, left: 8 }}
            >
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
            </Sankey>
          </ResponsiveContainer>
        ) : (
          <div className="flex items-center justify-center h-40 text-sm text-gray-400 bg-gray-50 rounded-lg">
            No zone-to-zone transitions to chart
          </div>
        )
      ) : (
        <DataTable
          rowKey={(r, i) => `${r.from_zone_id}-${r.to_zone_id}-${i}`}
          columns={[
            { key: 'from', label: 'From', render: (r) => zoneLabel(r.from_zone_name, 'from') },
            { key: 'to', label: 'To', render: (r) => zoneLabel(r.to_zone_name, 'to') },
            { key: 'transition_count', label: 'Count', align: 'right', render: (r) => formatNumber(r.transition_count) },
            { key: 'probability', label: 'Probability', align: 'right', render: (r) => formatRatio(r.probability) },
          ]}
          rows={rows}
        />
      )}
    </WidgetFrame>
  )
}
