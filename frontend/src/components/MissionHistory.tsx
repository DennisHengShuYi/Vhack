import { useState, useEffect } from 'react';
import { fetchMissions, formatDuration, formatDate, MissionSummary } from '../api';

interface Props {
  onViewDetail: (id: string) => void;
  onViewReplay: (id: string) => void;
}

export default function MissionHistory({ onViewDetail, onViewReplay }: Props) {
  const [missions, setMissions] = useState<MissionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMissions()
      .then(setMissions)
      .catch(() => setError("Failed to load mission history"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: '#475569' }}>
      Loading mission history...
    </div>
  );

  if (error) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: '#f87171' }}>
      {error}
    </div>
  );

  if (missions.length === 0) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '200px', color: '#475569' }}>
      No missions recorded yet. Complete a mission to see history here.
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '16px', overflowY: 'auto', height: '100%' }}>
      {missions.map((m, idx) => {
        const duration = formatDuration(m.started_at, m.ended_at);
        const avgS = m.avg_time_to_find_s;
        const avgDisplay = avgS >= 60 ? `${Math.floor(avgS / 60)}m ${Math.round(avgS % 60)}s` : `${Math.round(avgS)}s`;
        return (
          <div key={m.id} style={{
            background: '#1a1f2e', border: '1px solid #2a3550', borderRadius: '8px',
            padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px'
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ color: '#7eb3ff', fontSize: '11px', fontWeight: 600, letterSpacing: '1px', marginBottom: '4px' }}>
                MISSION #{missions.length - idx} — {formatDate(m.started_at)}
              </div>
              <div style={{ color: '#e0e6ff', fontSize: '13px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                <span>⏱ <strong>{duration}</strong></span>
                <span>🧍 <strong>{m.victims_found} / {m.total_victims}</strong> found</span>
                <span>⏳ avg <strong>{avgDisplay}</strong> to find</span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexShrink: 0 }}>
              <div style={{
                background: m.status === 'COMPLETE' ? '#0d3d2a' : '#3d2a0d',
                color: m.status === 'COMPLETE' ? '#4ade80' : '#facc15',
                fontSize: '11px', padding: '3px 10px', borderRadius: '12px',
                border: `1px solid ${m.status === 'COMPLETE' ? '#4ade80' : '#facc15'}`
              }}>
                {m.status}
              </div>
              <button
                onClick={() => onViewDetail(m.id)}
                style={{
                  background: '#1e3a5f', color: '#7eb3ff', border: '1px solid #3b6cb7',
                  borderRadius: '6px', padding: '5px 12px', fontSize: '12px', cursor: 'pointer'
                }}
              >
                View Details
              </button>
              <button
                onClick={() => onViewReplay(m.id)}
                style={{
                  background: '#2d1f4e', color: '#a78bfa', border: '1px solid #7c3aed',
                  borderRadius: '6px', padding: '5px 12px', fontSize: '12px', cursor: 'pointer'
                }}
              >
                ▶ Replay
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
