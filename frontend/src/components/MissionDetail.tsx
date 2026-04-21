import { useState, useEffect, type CSSProperties } from 'react';
import {
  LineChart, Line, AreaChart, Area,
  PieChart, Pie, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend
} from 'recharts';
import { fetchMissionDetail, fetchReplay, formatDuration, formatDate, type MissionDetail, type ReplayTick } from '../api';

interface Props {
  missionId: string;
  missionIndex: number;
  onBack: () => void;
  onReplay: () => void;
}

const PRIORITY_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  'P1-CRITICAL': { bg: '#1a0e0e', border: '#7f1d1d', text: '#fca5a5' },
  'P2-URGENT': { bg: '#1a130a', border: '#78350f', text: '#fed7aa' },
  'P3-STABLE': { bg: '#0a1a0e', border: '#14532d', text: '#bbf7d0' },
};

function ProgressBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ height: '5px', background: '#1e293b', borderRadius: '3px', overflow: 'hidden' }}>
      <div style={{ width: `${Math.min(value, 100)}%`, height: '100%', background: color, borderRadius: '3px', transition: 'width 0.6s ease' }} />
    </div>
  );
}

function StatRow({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ marginBottom: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
        <span style={{ color: '#94a3b8', fontSize: '11px' }}>{label}</span>
        <span style={{ color, fontSize: '11px', fontWeight: 600 }}>{value}</span>
      </div>
    </div>
  );
}

export default function MissionDetailView({ missionId, missionIndex, onBack, onReplay }: Props) {
  const [detail, setDetail] = useState<MissionDetail | null>(null);
  const [replay, setReplay] = useState<ReplayTick[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchMissionDetail(missionId), fetchReplay(missionId)])
      .then(([d, r]) => { setDetail(d); setReplay(r); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [missionId]);

  if (loading || !detail) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '300px', color: '#475569' }}>
      Loading mission detail...
    </div>
  );

  const duration = formatDuration(detail.started_at, detail.ended_at);
  const avgS = detail.avg_time_to_find_s || 0;
  const avgDisplay = avgS >= 60 ? `${Math.floor(avgS / 60)}m ${Math.round(avgS % 60)}s` : `${Math.round(avgS)}s`;

  const droneList = Object.entries(detail.per_drone || {});
  const numDrones = droneList.length || 1;
  const maxBattery = Math.max(...droneList.map(([, d]) => d.battery_used || 0), 1);

  const avgUtilisation = droneList.reduce((acc, [, d]) => acc + (d.utilisation_pct || 0), 0) / numDrones;
  const idlePct = Math.max(0, 100 - avgUtilisation);
  const totalScans = droneList.reduce((acc, [, d]) => acc + (d.scans_performed || 0), 0);
  const totalCharges = droneList.reduce((acc, [, d]) => acc + (d.charges_count || 0), 0);
  const mostActiveDrone = [...droneList].sort((a, b) => (b[1].scans_performed || 0) - (a[1].scans_performed || 0))[0];

  const safeSurvivors = detail.survivors || [];
  const p1Survivors = safeSurvivors.filter(s => s.priority === 'P1-CRITICAL');
  const firstContactTick = safeSurvivors.length > 0 ? Math.min(...safeSurvivors.map(s => s.tick || 0)) : 0;
  
  const zoneSorted = Object.entries(detail.zone_times || {}).sort((a, b) => (a[1].duration_s || 0) - (b[1].duration_s || 0));
  const maxZoneDuration = Math.max(...zoneSorted.map(([, z]) => z.duration_s), 1);

  // Chart data
  const coverageData = replay.map(t => ({ tick: t.tick, coverage: t.coverage_pct }));
  const survivorsData = (() => {
    let count = 0;
    return safeSurvivors
      .sort((a, b) => (a.tick || 0) - (b.tick || 0))
      .map(s => { count++; return { tick: s.tick || 0, found: count }; });
  })();
  const victimsPieData = [
    { name: 'Rescued', value: detail.victims_rescued, color: '#4ade80' },
    { name: 'Missed', value: Math.max(0, detail.total_victims - detail.victims_found), color: '#f87171' },
    { name: 'Failed', value: Math.max(0, detail.victims_found - detail.victims_rescued), color: '#fbbf24' },
  ].filter(d => d.value > 0);

  // Terrain Analytics
  const terrainStats: Record<string, { totalCells: number; scannedCells: number; totalVictims: number; foundVictims: number }> = {
    'city': { totalCells: 0, scannedCells: 0, totalVictims: 0, foundVictims: 0 },
    'forest': { totalCells: 0, scannedCells: 0, totalVictims: 0, foundVictims: 0 },
    'hazard': { totalCells: 0, scannedCells: 0, totalVictims: 0, foundVictims: 0 },
    'flat': { totalCells: 0, scannedCells: 0, totalVictims: 0, foundVictims: 0 },
    'lake': { totalCells: 0, scannedCells: 0, totalVictims: 0, foundVictims: 0 },
  };

  const terrainGrid = replay[0]?.terrain;
  const finalScanned = replay[replay.length - 1]?.scanned;
  const finalVictims = replay[replay.length - 1]?.victims || [];

  if (terrainGrid && finalScanned) {
    for (let y = 0; y < terrainGrid.length; y++) {
      for (let x = 0; x < terrainGrid[y].length; x++) {
        const type = terrainGrid[y][x];
        if (terrainStats[type]) {
          terrainStats[type].totalCells++;
          if (finalScanned[y] && finalScanned[y][x]) {
            terrainStats[type].scannedCells++;
          }
        }
      }
    }
  }

  finalVictims.forEach(v => {
    if (terrainGrid && v.y < terrainGrid.length && v.x < terrainGrid[0].length) {
      const type = terrainGrid[v.y][v.x];
      if (terrainStats[type]) {
        terrainStats[type].totalVictims++;
        if (v.found) terrainStats[type].foundVictims++;
      }
    }
  });

  const totalGridCells = terrainGrid ? terrainGrid.length * terrainGrid[0].length : 1;
  const terrainColors: Record<string, string> = {
    'city': '#cbd5e1',    // light gray
    'forest': '#4ade80',  // green
    'hazard': '#ef4444',  // red
    'flat': '#a1a1aa',    // darker gray
    'lake': '#3b82f6',    // blue
  };

  const batteryChartData = replay.map(t => {
    const entry: Record<string, number | string> = { tick: t.tick };
    for (const [id, d] of Object.entries(t.drones)) {
      entry[id] = d.battery;
    }
    return entry;
  });
  const droneColors = ['#38bdf8', '#4ade80', '#fbbf24', '#f87171', '#a78bfa'];

  const panel: CSSProperties = {
    background: '#0f172a', border: '1px solid #1e293b', borderRadius: '10px', padding: '14px'
  };
  const panelTitle = (color: string, label: string) => (
    <div style={{ color: '#e2e8f0', fontSize: '13px', fontWeight: 600, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ color }}>◈</span> {label}
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', padding: '16px', overflowY: 'auto', height: '100%' }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button onClick={onBack} style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #2a3550', borderRadius: '6px', padding: '5px 10px', cursor: 'pointer', fontSize: '12px' }}>
            ← Back
          </button>
          <div>
            <div style={{ color: '#7eb3ff', fontSize: '12px', fontWeight: 600 }}>MISSION #{missionIndex} — {formatDate(detail.started_at)}</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={onReplay} style={{ background: '#2d1f4e', color: '#a78bfa', border: '1px solid #7c3aed', borderRadius: '6px', padding: '6px 14px', fontSize: '12px', cursor: 'pointer' }}>
            ▶ Replay Mission
          </button>
          <div style={{
            background: detail.status === 'COMPLETE' ? '#0d3d2a' : '#3d2a0d',
            color: detail.status === 'COMPLETE' ? '#4ade80' : '#facc15',
            fontSize: '11px', padding: '6px 12px', borderRadius: '6px',
            border: `1px solid ${detail.status === 'COMPLETE' ? '#4ade80' : '#facc15'}`
          }}>
            ✓ {detail.status}
          </div>
        </div>
      </div>

      {/* Hero stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px' }}>
        {[
          { label: 'MISSION TIME', value: duration, color: '#0ea5e9', bg: '#0f2027', border: '#0ea5e9' },
          { label: 'SURVIVORS FOUND', value: `${detail.victims_found} / ${detail.total_victims}`, color: '#4ade80', bg: '#0f2027', border: '#4ade80' },
          { label: 'AVG TIME TO FIND', value: avgDisplay, color: '#a78bfa', bg: '#0f2027', border: '#a78bfa' },
          { label: 'COVERAGE', value: `${detail.coverage_pct.toFixed(1)}%`, color: '#fbbf24', bg: '#0f2027', border: '#fbbf24' },
        ].map(s => (
          <div key={s.label} style={{ background: `linear-gradient(135deg, ${s.bg}, #1a2a3a)`, border: `1px solid ${s.border}`, borderRadius: '10px', padding: '14px', textAlign: 'center' }}>
            <div style={{ color: s.color, fontSize: '22px', fontWeight: 700 }}>{s.value}</div>
            <div style={{ color: '#94a3b8', fontSize: '10px', letterSpacing: '1px', marginTop: '4px' }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Performance + AI Decisions */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>

        <div style={panel}>
          {panelTitle('#0ea5e9', 'Performance')}
          <StatRow label="Detection Rate" value={`${detail.detection_rate_pct.toFixed(1)}%`} color="#4ade80" />
          <ProgressBar value={detail.detection_rate_pct} color="linear-gradient(90deg,#16a34a,#4ade80)" />
          <div style={{ marginBottom: '8px' }} />
          <StatRow label="Rescue Rate" value={`${detail.victims_rescued}/${detail.victims_found} (${detail.victims_found > 0 ? Math.round(detail.victims_rescued / detail.victims_found * 100) : 0}%)`} color="#38bdf8" />
          <ProgressBar value={detail.victims_found > 0 ? detail.victims_rescued / detail.victims_found * 100 : 0} color="linear-gradient(90deg,#0369a1,#38bdf8)" />
          <div style={{ marginBottom: '8px' }} />
          <StatRow label="Coverage" value={`${detail.coverage_pct.toFixed(1)}%`} color="#fbbf24" />
          <ProgressBar value={detail.coverage_pct} color="linear-gradient(90deg,#b45309,#fbbf24)" />
          <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
            <div style={{ flex: 1, background: '#1e293b', borderRadius: '6px', padding: '8px', textAlign: 'center' }}>
              <div style={{ color: '#f87171', fontSize: '14px', fontWeight: 700 }}>{detail.false_positives}</div>
              <div style={{ color: '#64748b', fontSize: '10px' }}>False positives</div>
            </div>
            <div style={{ flex: 1, background: '#1e293b', borderRadius: '6px', padding: '8px', textAlign: 'center' }}>
              <div style={{ color: '#4ade80', fontSize: '14px', fontWeight: 700 }}>{detail.victims_rescued}</div>
              <div style={{ color: '#64748b', fontSize: '10px' }}>Rescued</div>
            </div>
          </div>
        </div>

        <div style={panel}>
          {panelTitle('#a78bfa', 'Operational Analytics')}
          <StatRow label="Fleet Utilisation" value={`${avgUtilisation.toFixed(1)}%`} color="#a78bfa" />
          <div style={{ height: '6px', background: '#1e293b', borderRadius: '3px', overflow: 'hidden', display: 'flex', marginBottom: '14px' }}>
            <div style={{ width: `${avgUtilisation}%`, background: 'linear-gradient(90deg, #7c3aed, #a78bfa)' }} />
            <div style={{ width: `${idlePct}%`, background: '#374151' }} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
            <div style={{ background: '#1e1133', border: '1px solid #7c3aed', borderRadius: '6px', padding: '10px', textAlign: 'center' }}>
              <div style={{ color: '#a78bfa', fontSize: '18px', fontWeight: 700 }}>{totalScans}</div>
              <div style={{ color: '#8b5cf6', fontSize: '10px', marginTop: '2px' }}>Total Scans</div>
            </div>
            <div style={{ background: '#331b11', border: '1px solid #ea580c', borderRadius: '6px', padding: '10px', textAlign: 'center' }}>
              <div style={{ color: '#fb923c', fontSize: '18px', fontWeight: 700 }}>{totalCharges}</div>
              <div style={{ color: '#ea580c', fontSize: '10px', marginTop: '2px' }}>Total Base Charges</div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginBottom: '12px' }}>
            <div style={{ background: '#0e1c26', border: '1px solid #0284c7', borderRadius: '6px', padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' }}>
              <div style={{ color: '#38bdf8', fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px' }}>MOST ACTIVE</div>
              <div style={{ color: '#7dd3fc', fontSize: '13px', fontWeight: 700 }}>{mostActiveDrone?.[0] || 'N/A'}</div>
            </div>
            <div style={{ background: '#2a1215', border: '1px solid #e11d48', borderRadius: '6px', padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' }}>
              <div style={{ color: '#fb7185', fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px' }}>P1-CRITICAL SECURED</div>
              <div style={{ color: '#ffe4e6', fontSize: '13px', fontWeight: 700 }}>{p1Survivors.length} found</div>
            </div>
            <div style={{ background: '#1c1917', border: '1px solid #d97706', borderRadius: '6px', padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' }}>
              <div style={{ color: '#fbbf24', fontSize: '10px', fontWeight: 700, letterSpacing: '0.5px' }}>FIRST CONTACT</div>
              <div style={{ color: '#fef3c7', fontSize: '13px', fontWeight: 700 }}>Tick {firstContactTick}</div>
            </div>
          </div>

          {detail.contract_violations > 0 ? (
            <div style={{ background: '#2d1515', border: '1px solid #7f1d1d', borderRadius: '6px', padding: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: '#f87171', fontSize: '16px' }}>⚠</span>
              <div>
                <div style={{ color: '#fca5a5', fontSize: '11px', fontWeight: 600 }}>{detail.contract_violations} Contract Violation{detail.contract_violations > 1 ? 's' : ''}</div>
                <div style={{ color: '#64748b', fontSize: '10px' }}>Coverage pace or idle drone alerts triggered</div>
              </div>
            </div>
          ) : (
            <div style={{ background: '#0d3d2a', border: '1px solid #14532d', borderRadius: '6px', padding: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: '#4ade80', fontSize: '16px' }}>✓</span>
              <div>
                <div style={{ color: '#bbf7d0', fontSize: '11px', fontWeight: 600 }}>0 Contract Violations</div>
                <div style={{ color: '#4ade80', fontSize: '10px' }}>Swarm cleanly adhered to SLA</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Per-drone table */}
      <div style={panel}>
        {panelTitle('#38bdf8', 'Per-Drone Breakdown')}
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1e293b' }}>
              {['Drone', 'Battery used', 'Utilisation', 'Cells moved', 'Scans', 'Charges'].map(h => (
                <th key={h} style={{ color: '#475569', fontWeight: 500, textAlign: h === 'Drone' ? 'left' : 'center', padding: '6px 10px' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {droneList.map(([id, d], i) => {
              return (
                <tr key={id} style={{ borderBottom: '1px solid #0f172a', background: i % 2 === 1 ? '#0c1525' : 'transparent' }}>
                  <td style={{ padding: '8px 10px', color: '#7eb3ff', fontWeight: 600 }}>{id}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                      <div style={{ width: '50px', height: '4px', background: '#1e293b', borderRadius: '2px' }}>
                        <div style={{ width: `${(d.battery_used || 0) / maxBattery * 100}%`, height: '100%', background: (d.battery_used || 0) > 200 ? '#f87171' : '#fbbf24', borderRadius: '2px' }} />
                      </div>
                      <span style={{ color: (d.battery_used || 0) > 200 ? '#f87171' : '#fbbf24', fontSize: '11px' }}>{(d.battery_used || 0).toFixed(0)}%</span>
                    </div>
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <span style={{ color: (d.utilisation_pct || 0) >= 80 ? '#4ade80' : (d.utilisation_pct || 0) >= 60 ? '#fbbf24' : '#f87171', fontSize: '11px' }}>
                      {(d.utilisation_pct || 0).toFixed(0)}%
                    </span>
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#e2e8f0' }}>{d.cells_moved || 0}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#e2e8f0' }}>{d.scans_performed || 0}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <span style={{ background: '#1e293b', color: '#94a3b8', padding: '2px 8px', borderRadius: '10px', fontSize: '11px' }}>
                      {d.charges_count || 0}×
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Terrain Analytics */}
      <div style={panel}>
        {panelTitle('#f59e0b', 'Terrain & Victim Distribution')}
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1e293b' }}>
              {['Terrain', 'Grid Area %', 'Scanned', 'Victims (Found/Total)', 'Discovery Success'].map(h => (
                <th key={h} style={{ color: '#475569', fontWeight: 500, textAlign: h === 'Terrain' ? 'left' : 'center', padding: '6px 10px' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(terrainStats).map(([type, stats], i) => {
              if (stats.totalCells === 0) return null;
              const areaPct = (stats.totalCells / totalGridCells) * 100;
              const scannedPct = (stats.scannedCells / stats.totalCells) * 100;
              const foundPct = stats.totalVictims > 0 ? (stats.foundVictims / stats.totalVictims) * 100 : 0;
              
              return (
                <tr key={type} style={{ borderBottom: '1px solid #0f172a', background: i % 2 === 1 ? '#0c1525' : 'transparent' }}>
                  <td style={{ padding: '8px 10px', color: terrainColors[type], fontWeight: 600, textTransform: 'capitalize' }}>{type}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#e2e8f0' }}>{areaPct.toFixed(1)}%</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <span style={{ color: scannedPct >= 99 ? '#4ade80' : scannedPct >= 50 ? '#fbbf24' : '#f87171', fontSize: '11px' }}>
                      {scannedPct.toFixed(1)}%
                    </span>
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#e2e8f0' }}>
                    {stats.totalVictims > 0 ? (
                      <span><strong style={{color: stats.foundVictims === stats.totalVictims ? '#4ade80' : '#fbbf24'}}>{stats.foundVictims}</strong> / {stats.totalVictims}</span>
                    ) : (
                      <span style={{color: '#475569'}}>-</span>
                    )}
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    {stats.totalVictims > 0 ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}>
                        <div style={{ width: '40px', height: '4px', background: '#1e293b', borderRadius: '2px' }}>
                          <div style={{ width: `${foundPct}%`, height: '100%', background: foundPct === 100 ? '#4ade80' : '#fbbf24', borderRadius: '2px' }} />
                        </div>
                        <span style={{ color: foundPct === 100 ? '#4ade80' : '#fbbf24', fontSize: '11px' }}>{foundPct.toFixed(0)}%</span>
                      </div>
                    ) : (
                      <span style={{color: '#475569'}}>-</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Zone times + Survivor timeline */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>

        <div style={panel}>
          {panelTitle('#fbbf24', 'Zone Completion Times')}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {zoneSorted.map(([zid, z], i) => {
              const durPercent = Math.max(10, ((z.duration_s || 0) / maxZoneDuration) * 100);
              const barColor = z.duration_s < 45 ? '#4ade80' : z.duration_s < 90 ? '#fbbf24' : '#f87171';
              const m = Math.floor(z.duration_s / 60), sec = Math.floor(z.duration_s % 60).toString().padStart(2, '0');
              const label = m > 0 ? `${m}m ${sec}s` : `${z.duration_s.toFixed(1)}s`;
              return (
                <div key={zid} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ width: '36px', height: '36px', background: '#172033', border: `1px solid ${barColor}40`, borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: barColor, fontSize: '12px', fontWeight: 700, flexShrink: 0 }}>
                    {zid}
                  </div>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
                      <span style={{ color: '#94a3b8', fontSize: '11px' }}>{z.drone}</span>
                      <span style={{ color: barColor, fontSize: '11px', fontWeight: 600 }}>{label}</span>
                    </div>
                    <div style={{ height: '4px', background: '#1e293b', borderRadius: '2px' }}>
                      <div style={{ width: `${durPercent}%`, height: '100%', background: barColor, borderRadius: '2px', transition: 'width 1s ease' }} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div style={panel}>
          {panelTitle('#4ade80', 'Survivor Discovery')}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', overflowY: 'auto', maxHeight: '220px' }}>
            {safeSurvivors.sort((a, b) => (a.tick || 0) - (b.tick || 0)).map((s, i) => {
              const c = PRIORITY_COLORS[s.priority || 'P3-STABLE'] ?? PRIORITY_COLORS['P3-STABLE'];
              return (
                <div key={i} style={{ background: c.bg, border: `1px solid ${c.border}`, borderRadius: '8px', padding: '9px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ background: c.border, color: c.text, fontSize: '10px', fontWeight: 700, padding: '2px 7px', borderRadius: '10px' }}>
                      {s.priority.split('-')[0]}
                    </span>
                    <div>
                      {(() => {
                        const t = (s.tick || 0) * 0.7;
                        const timeStr = `T+${Math.floor(t / 60).toString().padStart(2, '0')}:${Math.floor(t % 60).toString().padStart(2, '0')}`;
                        return <div style={{ color: '#e2e8f0', fontSize: '11px', fontWeight: 600 }}>{timeStr} · {s.drone}</div>;
                      })()}
                      <div style={{ color: '#64748b', fontSize: '10px' }}>{s.condition.replace(/_/g, ' ')}</div>
                    </div>
                  </div>
                  <span style={{ color: c.text, fontSize: '11px', fontWeight: 600 }}>{s.rescue_s}s rescue</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Charts */}
      <div style={panel}>
        {panelTitle('#a78bfa', 'Mission Charts')}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>

          <div>
            <div style={{ color: '#64748b', fontSize: '10px', marginBottom: '6px', letterSpacing: '1px' }}>COVERAGE % OVER TIME</div>
            <ResponsiveContainer width="100%" height={120}>
              <AreaChart data={coverageData}>
                <XAxis dataKey="tick" hide />
                <YAxis domain={[0, 100]} hide />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }} />
                <Area type="monotone" dataKey="coverage" stroke="#fbbf24" fill="#78350f" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div>
            <div style={{ color: '#64748b', fontSize: '10px', marginBottom: '6px', letterSpacing: '1px' }}>SURVIVORS FOUND (STEP)</div>
            <ResponsiveContainer width="100%" height={120}>
              <LineChart data={survivorsData}>
                <XAxis dataKey="tick" hide />
                <YAxis hide />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }} />
                <Line type="stepAfter" dataKey="found" stroke="#4ade80" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div>
            <div style={{ color: '#64748b', fontSize: '10px', marginBottom: '6px', letterSpacing: '1px' }}>DRONE BATTERY LEVELS</div>
            <ResponsiveContainer width="100%" height={120}>
              <LineChart data={batteryChartData}>
                <XAxis dataKey="tick" hide />
                <YAxis domain={[0, 100]} hide />
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }} />
                {droneList.map(([id], i) => (
                  <Line key={id} type="monotone" dataKey={id} stroke={droneColors[i % droneColors.length]} strokeWidth={1.5} dot={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ color: '#64748b', fontSize: '10px', marginBottom: '6px', letterSpacing: '1px', alignSelf: 'flex-start' }}>VICTIM OUTCOMES</div>
            <ResponsiveContainer width="100%" height={120}>
              <PieChart>
                <Pie data={victimsPieData} cx="50%" cy="50%" innerRadius={30} outerRadius={50} paddingAngle={3} dataKey="value">
                  {victimsPieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                </Pie>
                <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: '11px' }} />
                <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: '10px' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>

        </div>
      </div>
    </div>
  );
}
