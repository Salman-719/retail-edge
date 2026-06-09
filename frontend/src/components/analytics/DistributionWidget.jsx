import React, { useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { getDistribution } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { DataTable } from './widgetParts'
import { toCsv, downloadCsv } from '../../lib/csv'
import { formatNumber } from '../../lib/format'

// Visit-duration histogram — buckets are daily-summed by the API (additive).
export default function DistributionWidget({ slug, from, to }) {
  const [view, setView] = useState('chart')
  const { data, loading, error } = useAnalyticsQuery(
    () => getDistribution(slug, { from, to }),
    [slug, from, to],
  )
  const rows = data?.rows || []

  function exportCsv() {
    downloadCsv(`distribution_${from}_${to}.csv`, toCsv(rows, [
      { key: 'bucket_label', label: 'bucket' },
      { key: 'bucket_min_ms', label: 'min_ms' },
      { key: 'bucket_max_ms', label: 'max_ms' },
      { key: 'visit_count', label: 'visit_count' },
    ]))
  }

  return (
    <WidgetFrame
      title="Visit Duration Distribution"
      views={[{ key: 'chart', label: 'Chart' }, { key: 'table', label: 'Table' }]}
      view={view} onView={setView}
      onExport={exportCsv}
      loading={loading} error={error} isEmpty={!rows.length}
    >
      {view === 'table' ? (
        <DataTable
          rowKey={(r) => r.bucket_label}
          columns={[
            { key: 'bucket_label', label: 'Bucket' },
            { key: 'visit_count', label: 'Visits', align: 'right', render: (r) => formatNumber(r.visit_count) },
          ]}
          rows={rows}
        />
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={rows} margin={{ top: 4, right: 24, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="bucket_label" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              formatter={(v) => [formatNumber(v), 'Visits']}
            />
            <Bar dataKey="visit_count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </WidgetFrame>
  )
}
