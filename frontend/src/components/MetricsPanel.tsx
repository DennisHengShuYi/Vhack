import { Activity, Download, Clock, Zap, Target, Battery } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

type DroneMetrics = {
  drone_id: string;
  cells_moved: number;
  scans_performed: number;
  battery_used: number;
  charges_count: number;
  idle_ticks: number;
  current_battery: number;
};

type Performance = {
  avg_planning_latency_ms: number;
  first_find_tick: number | null;
  battery_consumed_total: number;
};

type Metrics = {
  total_scannable_cells: number;
  total_victims: number;
  total_cells_scanned: number;
  victims_found: number;
  victims_rescued: number;
  true_positives: number;
  false_positives: number;
  coverage_percent: number;
  detection_rate_percent: number;
  cells_per_full_charge: number;
  thermal_threshold_config: { min_heat: number; min_contrast: number };
  per_drone: Record<string, DroneMetrics>;
  performance?: Performance;
};

type Props = { metrics: Metrics | null; elapsedSec?: number };

function KpiBox({ label, value, icon }: { label: string; value: string; icon: React.ReactNode }) {
  return (
    <div style={{ flex: '1 1 120px', minWidth: 100, background: 'rgba(0,243,255,0.04)', border: '1px solid rgba(0,243,255,0.12)', borderRadius: 6, padding: '6px 8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#9ca3af', fontSize: 10, marginBottom: 3 }}>
        {icon}<span>{label}</span>
      </div>
      <div className="metric-value" style={{ fontSize: 14 }}>{value}</div>
    </div>
  );
}

function fmtMs(ms: number) { return ms < 1000 ? `${ms.toFixed(0)}ms` : `${(ms / 1000).toFixed(1)}s`; }
function fmtTick(t: number | null) { return t == null ? '—' : `T${t}`; }

export default function MetricsPanel({ metrics, elapsedSec = 0 }: Props) {
  if (!metrics) return <div style={{ color: '#6b7280', fontSize: 13, padding: 12 }}>No metrics yet — start a mission.</div>;

  const totalDetections = metrics.true_positives + metrics.false_positives;
  const precision = totalDetections > 0 ? Math.round((metrics.true_positives / totalDetections) * 100) : 100;
  const perf = metrics.performance;

  const elapsedMin = elapsedSec / 60;
  const vicPerMin = elapsedMin > 0 ? (metrics.victims_found / elapsedMin).toFixed(2) : '—';
  const cellsScanned = metrics.total_cells_scanned;
  const battEff = perf && perf.battery_consumed_total > 0
    ? (cellsScanned / perf.battery_consumed_total).toFixed(1)
    : '—';

  const handleExport = async () => {
    const res = await fetch(`${API_BASE}/missions/current/export`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'mission_log.jsonl';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="metrics-panel" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Detection accuracy */}
      <div className="metric-card">
        <div className="metric-label"><Activity size={12} /> Thermal Detection Accuracy</div>
        <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
          <div><div className="metric-sub">True Positives</div><div className="metric-value" style={{ fontSize: 15, color: '#4ade80' }}>{metrics.true_positives}</div></div>
          <div><div className="metric-sub">False Positives</div><div className="metric-value" style={{ fontSize: 15, color: '#f87171' }}>{metrics.false_positives}</div></div>
          <div><div className="metric-sub">Precision</div><div className="metric-value" style={{ fontSize: 15 }}>{precision}%</div></div>
          <div><div className="metric-sub">Detection Rate</div><div className="metric-value" style={{ fontSize: 15 }}>{metrics.detection_rate_percent}%</div></div>
        </div>
        <div className="metric-sub" style={{ marginTop: 6 }}>
          Threshold: heat &ge; {metrics.thermal_threshold_config.min_heat} &middot; contrast &ge; {metrics.thermal_threshold_config.min_contrast}
        </div>
      </div>

      {/* Mission Performance */}
      <div className="metric-card">
        <div className="metric-label" style={{ marginBottom: 8 }}><Zap size={12} /> Mission Performance</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          <KpiBox label="Avg Plan Latency" value={perf ? fmtMs(perf.avg_planning_latency_ms) : '—'} icon={<Clock size={10} />} />
          <KpiBox label="Time to First Find" value={fmtTick(perf?.first_find_tick ?? null)} icon={<Target size={10} />} />
          <KpiBox label="Victims / Min" value={vicPerMin.toString()} icon={<Activity size={10} />} />
          <KpiBox label="Battery Efficiency" value={battEff === '—' ? '—' : `${battEff} cells/%`} icon={<Battery size={10} />} />
        </div>
      </div>

      {/* Per-drone */}
      <div className="metric-label" style={{ paddingLeft: 2 }}>Drone Performance</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {Object.values(metrics.per_drone).map(d => (
          <div key={d.drone_id} className="metric-card drone-card" style={{ minWidth: 120, flex: '1 1 120px' }}>
            <div className="metric-label">{d.drone_id}</div>
            <div className="metric-sub">{d.scans_performed} scans &middot; {d.charges_count} charges</div>
            <div className="metric-sub">{d.cells_moved} cells moved</div>
          </div>
        ))}
      </div>

      {/* Export */}
      <button className="cyber-button secondary" style={{ alignSelf: 'flex-start', gap: 6 }} onClick={handleExport}>
        <Download size={12} /> EXPORT MISSION LOG
      </button>
    </div>
  );
}
