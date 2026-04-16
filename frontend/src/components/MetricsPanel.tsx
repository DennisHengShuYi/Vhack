import { Activity } from 'lucide-react';

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
};


export default function MetricsPanel({ metrics }: Props) {
  if (!metrics) return <div style={{ color: '#6b7280', fontSize: 13, padding: 12 }}>No metrics yet — start a mission.</div>;

  const totalDetections = metrics.true_positives + metrics.false_positives;
  const precision = totalDetections > 0
    ? Math.round((metrics.true_positives / totalDetections) * 100)
    : 100;

  return (
    <div className="metrics-panel" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Thermal detection accuracy */}
      <div className="metric-card">
        <div className="metric-label"><Activity size={12} /> Thermal Detection Accuracy</div>
        <div style={{ display: 'flex', gap: 12, marginTop: 6, flexWrap: 'wrap' }}>
          <div>
            <div className="metric-sub">True Positives</div>
            <div className="metric-value" style={{ fontSize: 15, color: '#4ade80' }}>{metrics.true_positives}</div>
          </div>
          <div>
            <div className="metric-sub">False Positives</div>
            <div className="metric-value" style={{ fontSize: 15, color: '#f87171' }}>{metrics.false_positives}</div>
          </div>
          <div>
            <div className="metric-sub">Precision</div>
            <div className="metric-value" style={{ fontSize: 15 }}>{precision}%</div>
          </div>
          <div>
            <div className="metric-sub">Detection Rate</div>
            <div className="metric-value" style={{ fontSize: 15 }}>{metrics.detection_rate_percent}%</div>
          </div>
        </div>
        <div className="metric-sub" style={{ marginTop: 6 }}>
          Threshold: heat &ge; {metrics.thermal_threshold_config.min_heat} &middot; contrast &ge; {metrics.thermal_threshold_config.min_contrast}
        </div>
      </div>

      {/* Per-drone scan stats */}
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
    </div>
  );
}
