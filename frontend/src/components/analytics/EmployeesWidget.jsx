import React from 'react'
import { getEmployeeAnalytics } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { DataTable, MultiSelect } from './widgetParts'
import { toCsv, downloadCsv } from '../../lib/csv'
import { formatDuration, formatRatio } from '../../lib/format'

// Employee filter lives on this widget only (the one per-employee view).
export default function EmployeesWidget({ slug, from, to, granularity, employeeOptions, employeeIds, onEmployeeIdsChange }) {
  const empCsv = employeeIds.length ? employeeIds.join(',') : undefined
  const { data, loading, error } = useAnalyticsQuery(
    () => getEmployeeAnalytics(slug, { from, to, granularity, employee_ids: empCsv }),
    [slug, from, to, granularity, empCsv],
  )
  const rows = data?.rows || []

  function exportCsv() {
    downloadCsv(`employees_${from}_${to}.csv`, toCsv(rows, [
      { key: 'employee_name', label: 'employee' },
      { key: 'bucket_start', label: 'date' },
      { key: 'scheduled_duration_ms', label: 'scheduled_ms' },
      { key: 'present_duration_ms', label: 'present_ms' },
      { key: 'presence_ratio', label: 'presence_ratio' },
      { key: 'zone_punctuality_delay_ms', label: 'punctuality_delay_ms' },
      { key: 'unassigned_zone_time_ms', label: 'unassigned_ms' },
      { key: 'is_complete', label: 'is_complete' },
    ]))
  }

  return (
    <WidgetFrame
      title="Employee Presence"
      subtitle={data ? `Grain: ${data.grain}` : undefined}
      onExport={exportCsv}
      loading={loading} error={error} isEmpty={!rows.length}
      extraControls={
        <MultiSelect label="Employees" options={employeeOptions} selected={employeeIds} onChange={onEmployeeIdsChange} />
      }
    >
      <DataTable
        rowKey={(r, i) => `${r.employee_id}-${r.bucket_start}-${i}`}
        columns={[
          { key: 'employee_name', label: 'Employee' },
          { key: 'bucket_start', label: 'Date' },
          { key: 'scheduled_duration_ms', label: 'Scheduled', align: 'right', render: (r) => formatDuration(r.scheduled_duration_ms) },
          { key: 'present_duration_ms', label: 'Present', align: 'right', render: (r) => formatDuration(r.present_duration_ms) },
          { key: 'presence_ratio', label: 'Presence', align: 'right', render: (r) => formatRatio(r.presence_ratio) },
          { key: 'zone_punctuality_delay_ms', label: 'Punctuality', align: 'right', render: (r) => formatDuration(r.zone_punctuality_delay_ms) },
        ]}
        rows={rows}
      />
    </WidgetFrame>
  )
}
