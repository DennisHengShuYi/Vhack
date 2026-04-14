import { Battery, Target, Scan, Activity, Clock } from 'lucide-react';

type DroneMetrics = {
  drone_id: string;
  cells_moved: number;
  scans_performed: number;
  battery_used: number;
  charges_count: number;
  idle_ticks: number;
  current_battery: number;
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
};

type Props = {
  metrics: Metrics | null;
  elapsedTs: string;
  staleSightings?: number;
};

function ProgressBar({ value, color = '#4ade80' }: { value: number; color?: string }) {
  return (
    <div style={{ background: '#1a2a1a', borderRadius: 4, height: 8, overflow: 'hidden' }}>
      <div style={{ width: `${Math.min(100, value)}%`, height: '100%', background: color, transition: 'width 0.5s ease' }} />
    </div>
  );
}

export default function MetricsPanel({ metrics, elapsedTs, staleSightings }: Props) {
  if (!metrics) return null;

  const totalDetections = metrics.true_positives + metrics.false_positives;
  const precision = totalDetections > 0
    ? Math.round((metrics.true_positives / totalDetections) * 100)
    : 100;

  return (
    <div className="metrics-panel" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Header row: timer + coverage + victims */}
      <div style={{ display: 'flex', gap: 12 }}>
        <div className="metric-card" style={{ flex: 1 }}>
          <div className="metric-label"><Clock size={12} /> Mission Time</div>
          <div className="metric-value">{elapsedTs}</div>
        </div>
        <div className="metric-card" style={{ flex: 2 }}>
          <div className="metric-label"><Scan size={12} /> Grid Coverage</div>
          <div className="metric-value">{metrics.coverage_percent}%</div>
          <ProgressBar value={metrics.coverage_percent} />
          <div className="metric-sub">{metrics.total_cells_scanned} / {metrics.total_scannable_cells} cells</div>
        </div>
        <div className="metric-card" style={{ flex: 1 }}>
          <div className="metric-label"><Target size={12} /> Victims</div>
          <div className="metric-value">{metrics.victims_found} / {metrics.total_victims}</div>
          <div className="metric-sub">{metrics.victims_rescued} rescued</div>
          {staleSightings !== undefined && staleSightings > 0 && (
            <div className="metric-sub" style={{ color: '#f97316' }}>&#x26A0; {staleSightings} stale sighting{staleSightings > 1 ? 's' : ''}</div>
          )}
        </div>
      </div>

      {/* Thermal detection stats */}
      <div className="metric-card">
        <div className="metric-label"><Activity size={12} /> Thermal Detector</div>
        <div style={{ display: 'flex', gap: 16, marginTop: 6 }}>
          <div>
            <div className="metric-sub">Threshold</div>
            <div className="metric-value" style={{ fontSize: 13 }}>
              heat &ge; {metrics.thermal_threshold_config.min_heat} &middot; contrast &ge; {metrics.thermal_threshold_config.min_contrast}
            </div>
          </div>
          <div>
            <div className="metric-sub">True Positives</div>
            <div className="metric-value" style={{ fontSize: 13, color: '#4ade80' }}>{metrics.true_positives}</div>
          </div>
          <div>
            <div className="metric-sub">False Positives</div>
            <div className="metric-value" style={{ fontSize: 13, color: '#f87171' }}>{metrics.false_positives}</div>
          </div>
          <div>
            <div className="metric-sub">Precision</div>
            <div className="metric-value" style={{ fontSize: 13 }}>{precision}%</div>
          </div>
          <div>
            <div className="metric-sub">Detection Rate</div>
            <div className="metric-value" style={{ fontSize: 13 }}>{metrics.detection_rate_percent}%</div>
          </div>
        </div>
      </div>

      {/* Battery endurance */}
      <div className="metric-card">
        <div className="metric-label"><Battery size={12} /> Fleet Endurance</div>
        <div className="metric-value" style={{ fontSize: 13 }}>
          {metrics.cells_per_full_charge} cells/charge &nbsp;&middot;&nbsp; RTB threshold: 25%
        </div>
      </div>

      {/* Per-drone cards */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {Object.values(metrics.per_drone).map(d => (
          <div key={d.drone_id} className="metric-card drone-card" style={{ minWidth: 110 }}>
            <div className="metric-label">{d.drone_id}</div>
            <ProgressBar
              value={d.current_battery}
              color={d.current_battery < 25 ? '#f87171' : d.current_battery < 50 ? '#fbbf24' : '#4ade80'}
            />
            <div className="metric-sub">{d.current_battery.toFixed(0)}% batt</div>
            <div className="metric-sub">{d.scans_performed} scans &middot; {d.charges_count} charges</div>
          </div>
        ))}
      </div>
    </div>
  );
}
