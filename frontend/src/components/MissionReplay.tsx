import { useState, useEffect, useRef, useCallback } from 'react';
import { fetchReplay, ReplayTick } from '../api';

const GRID_W = 20;
const GRID_H = 15;
const SPEED_INTERVALS: Record<string, number> = { '×1': 700, '×2': 350, '×4': 175 };

interface Props {
  missionId: string;
  onBack: () => void;
}

export default function MissionReplay({ missionId, onBack }: Props) {
  const [ticks, setTicks] = useState<ReplayTick[]>([]);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<'×1' | '×2' | '×4'>('×1');
  const [loading, setLoading] = useState(true);
  const timelineRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchReplay(missionId)
      .then(data => { setTicks(data); setIndex(0); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [missionId]);

  // Auto-scroll timeline to current event
  useEffect(() => {
    if (timelineRef.current) {
      const active = timelineRef.current.querySelector('.timeline-active');
      active?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [index]);

  // Playback interval
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (playing && ticks.length > 0) {
      intervalRef.current = setInterval(() => {
        setIndex(i => {
          if (i >= ticks.length - 1) { setPlaying(false); return i; }
          return i + 1;
        });
      }, SPEED_INTERVALS[speed]);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [playing, speed, ticks.length]);

  const currentTick = ticks[index];

  // Build scanned coverage from ticks up to current index
  const scannedCells = useCallback(() => {
    const grid: boolean[][] = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(false));
    for (let i = 0; i <= index; i++) {
      const t = ticks[i];
      if (!t) continue;
      for (const d of Object.values(t.drones)) {
        if (d.x >= 0 && d.x < GRID_W && d.y >= 0 && d.y < GRID_H) {
          grid[d.y][d.x] = true;
        }
      }
    }
    return grid;
  }, [ticks, index]);

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '300px', color: '#475569' }}>
      Loading replay data...
    </div>
  );

  if (!ticks.length) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '300px', color: '#475569' }}>
      No replay data available for this mission.
    </div>
  );

  // Collect all events with tick + index
  const allEvents = ticks.flatMap((t, i) =>
    (t.events || []).filter(Boolean).map(e => ({ tick: t.tick, text: e, tickIndex: i }))
  );

  const scanned = scannedCells();
  const dronePositions = Object.entries(currentTick?.drones ?? {});

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '0' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid #1e293b', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button onClick={onBack} style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #2a3550', borderRadius: '6px', padding: '5px 10px', cursor: 'pointer', fontSize: '12px' }}>
            ← Back
          </button>
          <span style={{ color: '#7eb3ff', fontSize: '12px', fontWeight: 600 }}>MISSION REPLAY</span>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          {(['×1', '×2', '×4'] as const).map(s => (
            <button key={s} onClick={() => setSpeed(s)} style={{
              background: speed === s ? '#1e3a5f' : '#1a2535',
              color: speed === s ? '#7eb3ff' : '#94a3b8',
              border: `1px solid ${speed === s ? '#3b6cb7' : '#2a3550'}`,
              borderRadius: '4px', padding: '3px 8px', fontSize: '11px', cursor: 'pointer'
            }}>{s}</button>
          ))}
        </div>
      </div>

      {/* Main content */}
      <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', flex: 1, overflow: 'hidden' }}>

        {/* Event timeline */}
        <div ref={timelineRef} style={{ borderRight: '1px solid #1e293b', overflowY: 'auto', padding: '10px 12px' }}>
          <div style={{ color: '#94a3b8', fontSize: '10px', letterSpacing: '1px', marginBottom: '8px' }}>EVENT TIMELINE</div>
          {allEvents.length === 0 && (
            <div style={{ color: '#475569', fontSize: '11px' }}>No events recorded.</div>
          )}
          {allEvents.map((ev, i) => {
            const isActive = ev.tickIndex === index;
            const isSurvivor = ev.text.includes('THERMAL') || ev.text.includes('Survivor') || ev.text.includes('VICTIM');
            const isComplete = ev.text.includes('complete') || ev.text.includes('COMPLETE');
            const color = isSurvivor ? '#fb923c' : isComplete ? '#4ade80' : '#64748b';
            return (
              <div
                key={i}
                className={isActive ? 'timeline-active' : ''}
                onClick={() => setIndex(ev.tickIndex)}
                style={{
                  fontSize: '11px', lineHeight: '1.8', cursor: 'pointer', padding: '2px 6px', borderRadius: '3px',
                  background: isActive ? '#1e2d3d' : 'transparent',
                  borderLeft: isActive ? '2px solid #3b82f6' : '2px solid transparent',
                  color: isActive ? '#7eb3ff' : color,
                }}
              >
                <span style={{ color: '#475569', marginRight: '6px' }}>T{ev.tick}</span>
                {ev.text.length > 45 ? ev.text.slice(0, 45) + '…' : ev.text}
                {isActive && <span style={{ color: '#3b82f6', marginLeft: '6px', fontSize: '10px' }}>← now</span>}
              </div>
            );
          })}
        </div>

        {/* 2D grid */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '16px', overflow: 'hidden' }}>
          <div style={{ color: '#94a3b8', fontSize: '10px', letterSpacing: '1px', marginBottom: '10px', alignSelf: 'flex-start' }}>
            GRID SNAPSHOT — TICK {currentTick?.tick ?? 0}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${GRID_W}, 1fr)`, gap: '2px', width: '100%', maxWidth: '500px' }}>
            {Array.from({ length: GRID_H }, (_, y) =>
              Array.from({ length: GRID_W }, (_, x) => {
                const isDrone = dronePositions.some(([, d]) => d.x === x && d.y === y);
                const isScanned = scanned[y]?.[x];
                let bg = '#0d1117';
                if (isDrone) bg = '#2563eb';
                else if (isScanned) bg = '#1e3a2f';
                return (
                  <div key={`${x}-${y}`} style={{ height: '14px', background: bg, borderRadius: '1px', transition: 'background 0.2s' }} />
                );
              })
            )}
          </div>

          {/* Legend */}
          <div style={{ marginTop: '10px', display: 'flex', gap: '12px', flexWrap: 'wrap', fontSize: '10px', color: '#94a3b8' }}>
            {[
              { color: '#1e3a2f', label: 'Scanned' },
              { color: '#0d1117', label: 'Unscanned', border: '1px solid #2a3550' },
              { color: '#2563eb', label: 'Drone' },
            ].map(l => (
              <span key={l.label} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span style={{ display: 'inline-block', width: '10px', height: '10px', background: l.color, borderRadius: '2px', border: l.border ?? undefined }} />
                {l.label}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Scrub bar */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid #1e293b', flexShrink: 0, background: '#0f172a' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={() => setPlaying(p => !p)}
            style={{ background: playing ? '#1e293b' : '#1e3a5f', color: playing ? '#94a3b8' : '#7eb3ff', border: `1px solid ${playing ? '#2a3550' : '#3b6cb7'}`, borderRadius: '6px', padding: '5px 12px', fontSize: '13px', cursor: 'pointer', flexShrink: 0 }}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <span style={{ color: '#94a3b8', fontSize: '11px', flexShrink: 0 }}>Tick</span>
          <input
            type="range" min={0} max={ticks.length - 1} value={index}
            onChange={e => { setPlaying(false); setIndex(Number(e.target.value)); }}
            style={{ flex: 1, accentColor: '#3b82f6', cursor: 'pointer' }}
          />
          <span style={{ color: '#7eb3ff', fontSize: '11px', fontWeight: 600, flexShrink: 0 }}>
            {currentTick?.tick ?? 0} / {ticks[ticks.length - 1]?.tick ?? 0}
          </span>
        </div>
      </div>
    </div>
  );
}
