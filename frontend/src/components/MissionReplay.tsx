import { useState, useEffect, useRef, useMemo, type ReactNode } from 'react';
import { fetchReplay, type ReplayTick } from '../api';

const SPEED_INTERVALS: Record<string, number> = { '×1': 700, '×2': 350, '×4': 175 };

const DRONE_COLORS = ['#38bdf8', '#4ade80', '#fbbf24', '#f87171', '#a78bfa'];

// Colors match Map3D.tsx — unscanned (dark) and scanned (bright)
const TERRAIN_COLORS: Record<string, { unscanned: string; scanned: string; label: string }> = {
  flat:     { unscanned: '#7a6e52', scanned: '#a89b72', label: 'Flat' },
  forest:   { unscanned: '#2a5c35', scanned: '#3a8050', label: 'Forest' },
  mountain: { unscanned: '#7c2f2f', scanned: '#a04545', label: 'Mountain' },
  lake:     { unscanned: '#1e4a7a', scanned: '#2a6aaa', label: 'Lake' },
  city:     { unscanned: '#8a8a7a', scanned: '#b0c0a0', label: 'City' },
};

const STATUS_COLOR: Record<string, string> = {
  SCANNING:   '#4ade80',
  MOVING:     '#38bdf8',
  RETURNING:  '#fbbf24',
  CHARGING:   '#a78bfa',
  STANDBY:    '#fb923c',
  IDLE:       '#475569',
};

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

  // Terrain from first tick (static). Derive actual grid size from data.
  const terrain = useMemo<string[][]>(() => {
    const t = ticks[0]?.terrain;
    if (t && t.length > 0) return t;
    return Array.from({ length: 10 }, () => Array(10).fill('flat'));
  }, [ticks]);

  const GRID_H = terrain.length;
  const GRID_W = terrain[0]?.length ?? 10;

  // Scanned cells: use snapshot if available, else reconstruct from drone history
  const scannedGrid = useMemo((): boolean[][] => {
    const snap = ticks[index]?.scanned;
    if (snap) return snap;
    // fallback: mark cells visited by any drone up to current index
    const grid: boolean[][] = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(false));
    for (let i = 0; i <= index; i++) {
      for (const d of Object.values(ticks[i]?.drones ?? {})) {
        if (d.x >= 0 && d.x < GRID_W && d.y >= 0 && d.y < GRID_H) {
          grid[d.y][d.x] = true;
        }
      }
    }
    return grid;
  }, [ticks, index, GRID_H, GRID_W]);

  const currentTick = ticks[index];
  const droneEntries = Object.entries(currentTick?.drones ?? {});
  const victims = currentTick?.victims ?? [];

  // Map drone IDs to stable colors
  const droneColorMap = useMemo<Record<string, string>>(() => {
    const ids = Object.keys(ticks[0]?.drones ?? {});
    return Object.fromEntries(ids.map((id, i) => [id, DRONE_COLORS[i % DRONE_COLORS.length]]));
  }, [ticks]);

  // Collect all events
  const allEvents = useMemo(() =>
    ticks.flatMap((t, i) =>
      (t.events || []).filter(Boolean).map(e => ({ tick: t.tick, text: e, tickIndex: i }))
    ), [ticks]);

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


  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#080e1a' }}>

      {/* ── Header ───────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px', borderBottom: '1px solid #1e293b', flexShrink: 0,
        background: '#0d1525',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button onClick={onBack} style={{
            background: '#1e293b', color: '#94a3b8', border: '1px solid #2a3550',
            borderRadius: '6px', padding: '4px 10px', cursor: 'pointer', fontSize: '12px'
          }}>
            ← Back
          </button>
          <span style={{ color: '#7eb3ff', fontSize: '13px', fontWeight: 700, letterSpacing: '1px' }}>
            MISSION REPLAY
          </span>
          <span style={{ color: '#475569', fontSize: '11px' }}>
            Tick {currentTick?.tick ?? 0} / {ticks[ticks.length - 1]?.tick ?? 0}
            {' · '}
            <span style={{ color: '#4ade80' }}>{currentTick?.coverage_pct ?? 0}% coverage</span>
          </span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {(['×1', '×2', '×4'] as const).map(s => (
            <button key={s} onClick={() => setSpeed(s)} style={{
              background: speed === s ? '#1e3a5f' : '#1a2535',
              color: speed === s ? '#7eb3ff' : '#475569',
              border: `1px solid ${speed === s ? '#3b6cb7' : '#2a3550'}`,
              borderRadius: '4px', padding: '3px 10px', fontSize: '12px', cursor: 'pointer'
            }}>{s}</button>
          ))}
        </div>
      </div>

      {/* ── Main 3-column layout ─────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr 200px', flex: 1, overflow: 'hidden', minHeight: 0 }}>

        {/* Left: Event timeline */}
        <div ref={timelineRef} style={{
          borderRight: '1px solid #1e293b', overflowY: 'auto',
          padding: '10px 10px', background: '#0a1020',
        }}>
          <div style={{ color: '#475569', fontSize: '10px', letterSpacing: '1px', marginBottom: '8px', fontWeight: 600 }}>
            EVENT TIMELINE
          </div>
          {allEvents.length === 0 && (
            <div style={{ color: '#334155', fontSize: '11px' }}>No events recorded.</div>
          )}
          {allEvents.map((ev, i) => {
            const isActive = ev.tickIndex === index;
            const isSurvivor = ev.text.includes('THERMAL') || ev.text.includes('Survivor') || ev.text.includes('VICTIM') || ev.text.includes('🧍');
            const isComplete = ev.text.includes('complete') || ev.text.includes('COMPLETE') || ev.text.includes('🏁');
            const isRtb = ev.text.includes('RTB') || ev.text.includes('Returning');
            const color = isSurvivor ? '#fb923c' : isComplete ? '#4ade80' : isRtb ? '#fbbf24' : '#4b5563';
            return (
              <div
                key={i}
                className={isActive ? 'timeline-active' : ''}
                onClick={() => setIndex(ev.tickIndex)}
                style={{
                  fontSize: '10px', lineHeight: '1.7', cursor: 'pointer',
                  padding: '3px 6px', borderRadius: '3px', marginBottom: '1px',
                  background: isActive ? '#172033' : 'transparent',
                  borderLeft: `2px solid ${isActive ? '#3b82f6' : 'transparent'}`,
                  color: isActive ? '#93c5fd' : color,
                  transition: 'background 0.1s',
                }}
              >
                <span style={{ color: '#334155', marginRight: '5px', fontWeight: 600 }}>T{ev.tick}</span>
                {ev.text.length > 38 ? ev.text.slice(0, 38) + '…' : ev.text}
              </div>
            );
          })}
        </div>

        {/* Centre: Grid */}
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', padding: '16px', overflow: 'hidden',
          background: '#080e1a',
        }}>
          {/* Zone status badges */}
          <div style={{ display: 'flex', gap: '8px', marginBottom: '10px', flexWrap: 'wrap', justifyContent: 'center' }}>
            {Object.entries(currentTick?.zones ?? {}).map(([zid, status]) => {
              const color = status === 'COMPLETE' ? '#4ade80' : status === 'SCANNING' ? '#38bdf8' : '#475569';
              const bg = status === 'COMPLETE' ? '#0d3d2a' : status === 'SCANNING' ? '#0c1f33' : '#1a2535';
              return (
                <div key={zid} style={{
                  background: bg, border: `1px solid ${color}`, borderRadius: '5px',
                  padding: '2px 9px', fontSize: '10px', color, fontWeight: 600, letterSpacing: '0.5px'
                }}>
                  {zid} <span style={{ opacity: 0.7, fontWeight: 400 }}>{status}</span>
                </div>
              );
            })}
          </div>

          {/* Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${GRID_W}, 1fr)`,
            gap: '1px',
            width: '100%',
            maxWidth: '640px',
            aspectRatio: `${GRID_W} / ${GRID_H}`,
            position: 'relative',
          }}>
            {Array.from({ length: GRID_H }, (_, y) =>
              Array.from({ length: GRID_W }, (_, x) => {
                const terrainType = terrain[y]?.[x] ?? 'flat';
                const terrainColors = TERRAIN_COLORS[terrainType] ?? TERRAIN_COLORS['flat'];
                const isScanned = scannedGrid[y]?.[x];
                const droneHere = droneEntries.find(([, d]) => d.x === x && d.y === y);
                const victimHere = victims.find(v => v.x === x && v.y === y);

                // Base color: clearly different for scanned vs unscanned
                let bg = isScanned ? terrainColors.scanned : terrainColors.unscanned;
                let border = isScanned ? `${terrainColors.scanned}66` : 'transparent';
                let boxShadow = 'none';
                let content: ReactNode = null;

                if (droneHere) {
                  const [droneId] = droneHere;
                  const col = droneColorMap[droneId] ?? '#38bdf8';
                  bg = col;
                  border = '#fff';
                  boxShadow = `0 0 4px ${col}`;
                  const shortId = droneId.replace('ALPHA-', '');
                  content = (
                    <span style={{
                      position: 'absolute', inset: 0, display: 'flex',
                      alignItems: 'center', justifyContent: 'center',
                      fontSize: '8px', fontWeight: 800, color: '#000', lineHeight: 1,
                    }}>
                      {shortId}
                    </span>
                  );
                } else if (victimHere) {
                  const col = victimHere.rescued ? '#4ade80'
                    : victimHere.found ? '#fb923c'
                    : '#ef4444';
                  bg = col;
                  border = '#fff';
                  boxShadow = `0 0 5px ${col}`;
                  content = (
                    <span style={{
                      position: 'absolute', inset: 0, display: 'flex',
                      alignItems: 'center', justifyContent: 'center',
                      fontSize: '8px', fontWeight: 700, lineHeight: 1,
                    }}>
                      {victimHere.rescued ? '✓' : victimHere.found ? '!' : '?'}
                    </span>
                  );
                }

                return (
                  <div key={`${x}-${y}`} style={{
                    position: 'relative', background: bg,
                    border: `1px solid ${border}`,
                    borderRadius: '1px',
                    transition: 'background 0.1s',
                    aspectRatio: '1',
                    boxShadow,
                  }}>
                    {content}
                  </div>
                );
              })
            )}
          </div>

          {/* Legend */}
          <div style={{ marginTop: '12px', display: 'flex', gap: '12px', flexWrap: 'wrap', fontSize: '10px', color: '#64748b', justifyContent: 'center' }}>
            {/* Terrain: show unscanned → scanned pair */}
            {Object.entries(TERRAIN_COLORS).map(([k, v]) => (
              <span key={k} style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                <span style={{ display: 'inline-block', width: '9px', height: '9px', background: v.unscanned, borderRadius: '2px', border: '1px solid #2a3550' }} />
                <span style={{ color: '#475569', fontSize: '8px' }}>→</span>
                <span style={{ display: 'inline-block', width: '9px', height: '9px', background: v.scanned, borderRadius: '2px', border: `1px solid ${v.scanned}88` }} />
                {v.label}
              </span>
            ))}
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span style={{ display: 'inline-block', width: '9px', height: '9px', background: '#ef4444', borderRadius: '2px', boxShadow: '0 0 3px #ef4444' }} />
              Hidden
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span style={{ display: 'inline-block', width: '9px', height: '9px', background: '#fb923c', borderRadius: '2px', boxShadow: '0 0 3px #fb923c' }} />
              Found
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span style={{ display: 'inline-block', width: '9px', height: '9px', background: '#4ade80', borderRadius: '2px', boxShadow: '0 0 3px #4ade80' }} />
              Rescued
            </span>
          </div>
        </div>

        {/* Right: Drone status panel */}
        <div style={{
          borderLeft: '1px solid #1e293b', overflowY: 'auto',
          padding: '10px 10px', background: '#0a1020',
        }}>
          <div style={{ color: '#475569', fontSize: '10px', letterSpacing: '1px', marginBottom: '10px', fontWeight: 600 }}>
            DRONE STATUS
          </div>
          {droneEntries.length === 0 && (
            <div style={{ color: '#334155', fontSize: '11px' }}>No active drones.</div>
          )}
          {droneEntries.map(([id, d]) => {
            const col = droneColorMap[id] ?? '#38bdf8';
            const statusKey = (d.status ?? '').toUpperCase();
            const statusCol = STATUS_COLOR[statusKey] ?? '#475569';
            const batteryCol = d.battery > 50 ? '#4ade80' : d.battery > 25 ? '#fbbf24' : '#f87171';
            const label = d.status_label ?? d.status ?? '—';
            return (
              <div key={id} style={{
                background: '#0d1525', border: `1px solid ${col}33`,
                borderRadius: '8px', padding: '10px 10px', marginBottom: '8px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <span style={{ color: col, fontWeight: 700, fontSize: '12px' }}>{id}</span>
                  <span style={{
                    background: `${statusCol}22`, color: statusCol,
                    fontSize: '9px', fontWeight: 600, padding: '1px 6px',
                    borderRadius: '8px', border: `1px solid ${statusCol}55`,
                  }}>
                    {statusKey || '—'}
                  </span>
                </div>
                {/* Battery bar */}
                <div style={{ marginBottom: '4px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                    <span style={{ color: '#334155', fontSize: '9px' }}>BATTERY</span>
                    <span style={{ color: batteryCol, fontSize: '9px', fontWeight: 600 }}>{d.battery.toFixed(0)}%</span>
                  </div>
                  <div style={{ height: '4px', background: '#1e293b', borderRadius: '2px' }}>
                    <div style={{
                      width: `${Math.max(0, Math.min(100, d.battery))}%`,
                      height: '100%', background: batteryCol, borderRadius: '2px',
                      transition: 'width 0.3s',
                    }} />
                  </div>
                </div>
                {/* Position */}
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px' }}>
                  <span style={{ color: '#334155', fontSize: '9px' }}>POS</span>
                  <span style={{ color: '#64748b', fontSize: '9px' }}>({d.x}, {d.y})</span>
                </div>
                {label !== d.status && (
                  <div style={{ color: '#475569', fontSize: '9px', marginTop: '2px', textAlign: 'right', fontStyle: 'italic' }}>
                    {label.length > 22 ? label.slice(0, 22) + '…' : label}
                  </div>
                )}
              </div>
            );
          })}
          {/* Victim summary */}
          {victims.length > 0 && (
            <div style={{ marginTop: '8px', borderTop: '1px solid #1e293b', paddingTop: '10px' }}>
              <div style={{ color: '#475569', fontSize: '10px', letterSpacing: '1px', marginBottom: '8px', fontWeight: 600 }}>
                VICTIMS
              </div>
              <div style={{ display: 'flex', gap: '6px', justifyContent: 'space-around' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#f87171', fontSize: '16px', fontWeight: 700 }}>
                    {victims.filter(v => !v.found && !v.rescued).length}
                  </div>
                  <div style={{ color: '#334155', fontSize: '9px' }}>Hidden</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#fb923c', fontSize: '16px', fontWeight: 700 }}>
                    {victims.filter(v => v.found && !v.rescued).length}
                  </div>
                  <div style={{ color: '#334155', fontSize: '9px' }}>Found</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: '#4ade80', fontSize: '16px', fontWeight: 700 }}>
                    {victims.filter(v => v.rescued).length}
                  </div>
                  <div style={{ color: '#334155', fontSize: '9px' }}>Rescued</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Scrub bar ─────────────────────────────────────────────── */}
      <div style={{
        padding: '8px 16px', borderTop: '1px solid #1e293b',
        flexShrink: 0, background: '#0d1525',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <button
            onClick={() => setPlaying(p => !p)}
            style={{
              background: playing ? '#1e293b' : '#1e3a5f',
              color: playing ? '#94a3b8' : '#7eb3ff',
              border: `1px solid ${playing ? '#2a3550' : '#3b6cb7'}`,
              borderRadius: '6px', padding: '4px 14px', fontSize: '14px', cursor: 'pointer', flexShrink: 0
            }}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <input
            type="range" min={0} max={ticks.length - 1} value={index}
            onChange={e => { setPlaying(false); setIndex(Number(e.target.value)); }}
            style={{ flex: 1, accentColor: '#3b82f6', cursor: 'pointer' }}
          />
          <span style={{ color: '#7eb3ff', fontSize: '11px', fontWeight: 600, flexShrink: 0, minWidth: '70px', textAlign: 'right' }}>
            T{currentTick?.tick ?? 0} / T{ticks[ticks.length - 1]?.tick ?? 0}
          </span>
        </div>
      </div>
    </div>
  );
}
