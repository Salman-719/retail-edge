import React, { useState } from 'react'
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import { getComposition } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { DataTable } from './widgetParts'
import { toCsv, downloadCsv } from '../../lib/csv'
import { formatNumber } from '../../lib/format'

const COLORS = ['#3b82f6', '#1B3A5C']

export default function CompositionWidget({ slug, from, to, granularity }) {
  const [view, setView] = useState('donut')
  const { data, loading, error } = useAnalyticsQuery(
    () => getComposition(slug, { from, to, granularity }),
    [slug, from, to, granularity],
  )
  const rows = data?.rows || []

  // Non-additive: never sum customers/staff across buckets. The donut shows the
  // most recent COMPLETE bucket (fallback: most recent bucket).
  const latest = [...rows].reverse().find((r) => r.is_complete !== false) || rows[rows.length - 1]
  const donut = latest
    ? [{ name: 'Customers', value: latest.customers }, { name: 'Staff', value: latest.staff }]
    : []

  function exportCsv() {
    downloadCsv(`composition_${from}_${to}.csv`, toCsv(rows, [
      { key: 'bucket_start', label: 'date' },
      { key: 'customers', label: 'customers' },
      { key: 'staff', label: 'staff' },
      { key: 'is_complete', label: 'is_complete' },
    ]))
  }

  return (
    <WidgetFrame
      title="Customers vs Staff"
      subtitle={latest ? `Latest bucket: ${latest.bucket_start}` : undefined}
      views={[{ key: 'donut', label: 'Donut' }, { key: 'table', label: 'Table' }]}
      view={view} onView={setView}
      onExport={exportCsv}
      loading={loading} error={error} isEmpty={!rows.length}
    >
      {view === 'table' ? (
        <DataTable
          rowKey={(r) => r.bucket_start}
          columns={[
            { key: 'bucket_start', label: 'Date' },
            { key: 'customers', label: 'Customers', align: 'right', render: (r) => formatNumber(r.customers) },
            { key: 'staff', label: 'Staff', align: 'right', render: (r) => formatNumber(r.staff) },
          ]}
          rows={rows}
        />
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie data={donut} cx="50%" cy="50%" innerRadius={60} outerRadius={90} dataKey="value" labelLine={false}>
              {donut.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
            </Pie>
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
          </PieChart>
        </ResponsiveContainer>
      )}
    </WidgetFrame>
  )
}
