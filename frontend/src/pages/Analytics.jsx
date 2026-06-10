import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getActiveVersion, listEmployees } from '../api'
import { usePageTitle } from '../components/PageMeta'
import AnalyticsControls from '../components/analytics/AnalyticsControls'
import StoreSeriesWidget from '../components/analytics/StoreSeriesWidget'
import ZonesWidget from '../components/analytics/ZonesWidget'
import CompositionWidget from '../components/analytics/CompositionWidget'
import DistributionWidget from '../components/analytics/DistributionWidget'
import EmployeesWidget from '../components/analytics/EmployeesWidget'
import FlowMatrixWidget from '../components/analytics/FlowMatrixWidget'
import AlertsTimeseriesWidget from '../components/analytics/AlertsTimeseriesWidget'
import HeatmapWidget from '../components/analytics/HeatmapWidget'

const isoDay = (d) => d.toISOString().slice(0, 10)

export default function Analytics() {
  const { slug } = useParams()
  usePageTitle('Analytics')

  const [from, setFrom] = useState(isoDay(new Date(Date.now() - 6 * 86400000)))
  const [to, setTo] = useState(isoDay(new Date()))
  const [granularity, setGranularity] = useState('auto')
  const [zoneIds, setZoneIds] = useState([])
  const [employeeIds, setEmployeeIds] = useState([])

  const [zoneOptions, setZoneOptions] = useState([])
  const [employeeOptions, setEmployeeOptions] = useState([])

  useEffect(() => {
    getActiveVersion(slug)
      .then((v) => setZoneOptions((v?.zones || []).map((z) => ({ id: z.id, name: z.name }))))
      .catch(() => setZoneOptions([]))
    listEmployees(slug)
      .then((emps) => setEmployeeOptions((Array.isArray(emps) ? emps : emps?.employees || []).map((e) => ({ id: e.id, name: e.name }))))
      .catch(() => setEmployeeOptions([]))
  }, [slug])

  const common = { slug, from, to, granularity }

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <h1 className="page-title">Analytics</h1>
        <p className="page-subtitle">Historical traffic patterns and zone performance</p>
      </header>

      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        <AnalyticsControls
          from={from} to={to} granularity={granularity}
          zoneOptions={zoneOptions} zoneIds={zoneIds}
          onRangeChange={(f, t) => { setFrom(f); setTo(t) }}
          onGranularityChange={setGranularity}
          onZoneIdsChange={setZoneIds}
        />

        <StoreSeriesWidget {...common} />

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2"><ZonesWidget {...common} zoneIds={zoneIds} /></div>
          <div className="lg:col-span-1"><CompositionWidget {...common} /></div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <DistributionWidget slug={slug} from={from} to={to} />
          <FlowMatrixWidget slug={slug} from={from} to={to} />
        </div>

        <EmployeesWidget
          {...common}
          employeeOptions={employeeOptions}
          employeeIds={employeeIds}
          onEmployeeIdsChange={setEmployeeIds}
        />

        <AlertsTimeseriesWidget {...common} />

        <HeatmapWidget {...common} />
      </div>
    </div>
  )
}
