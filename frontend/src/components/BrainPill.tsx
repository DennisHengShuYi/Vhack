import { useState, useEffect } from 'react';
import { Cpu } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

type Brain = { mode: string; active: string };

const MODE_COLOR: Record<string, string> = {
  CLOUD: '#00f3ff',
  EDGE: '#a78bfa',
  RULES: '#fbbf24',
};

const DOT_COLOR = (active: string, mode: string) => {
  if (active === 'RULES') return '#fbbf24';
  if (active !== 'CLOUD' && mode === 'AUTO') return '#fbbf24'; // degraded
  return '#4ade80';
};

export default function BrainPill() {
  const [brain, setBrain] = useState<Brain>({ mode: 'AUTO', active: 'CLOUD' });
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/brain/status`);
        if (res.ok) setBrain(await res.json());
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const setMode = async (mode: string) => {
    await fetch(`${API_BASE}/brain/mode?mode=${mode}`, { method: 'POST' });
    setBrain(b => ({ ...b, mode }));
    setOpen(false);
  };

  const dotColor = DOT_COLOR(brain.active, brain.mode);
  const labelColor = MODE_COLOR[brain.active] ?? '#fff';

  return (
    <div style={{ position: 'relative' }}>
      <button
        className="cyber-button secondary"
        style={{ gap: 5, fontSize: 11, padding: '3px 8px' }}
        onClick={() => setOpen(o => !o)}
        title={`Brain: ${brain.mode} mode, using ${brain.active}`}
      >
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: dotColor, display: 'inline-block', flexShrink: 0 }} />
        <Cpu size={12} />
        <span style={{ color: labelColor }}>BRAIN: {brain.active}</span>
        <span style={{ color: '#6b7280', fontSize: 9 }}>▼</span>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: '100%', right: 0, marginTop: 4,
          background: '#0d1117', border: '1px solid rgba(0,243,255,0.2)',
          borderRadius: 6, padding: 6, zIndex: 100, minWidth: 140,
        }}>
          {['AUTO', 'CLOUD', 'EDGE', 'RULES'].map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                background: brain.mode === m ? 'rgba(0,243,255,0.1)' : 'none',
                border: 'none', color: brain.mode === m ? '#00f3ff' : '#9ca3af',
                padding: '4px 8px', fontSize: 11, cursor: 'pointer', borderRadius: 4,
              }}
            >{m}</button>
          ))}
          <div style={{ fontSize: 9, color: '#6b7280', padding: '4px 8px', borderTop: '1px solid rgba(255,255,255,0.06)', marginTop: 4 }}>
            Current: {brain.active}
          </div>
        </div>
      )}
    </div>
  );
}
