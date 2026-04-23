import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Cpu } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

type Brain = { mode: string; active: string };

const MODE_COLOR: Record<string, string> = {
  CLOUD: '#00f3ff',
  EDGE: '#a78bfa',
  RULES: '#fbbf24',
};

const MODE_BLURB: Record<string, string> = {
  AUTO: 'LLM first, rule-based fallback on error',
  CLOUD: 'Cloud LLM (OpenAI / Gemini)',
  EDGE: 'Edge / local LLM (labeled EDGE)',
  RULES: 'Deterministic WeightedPlanner only',
};

const DOT_COLOR = (active: string, mode: string) => {
  if (active === 'RULES') return '#fbbf24';
  if (active !== 'CLOUD' && mode === 'AUTO') return '#fbbf24';
  return '#4ade80';
};

export default function BrainPill() {
  const [brain, setBrain] = useState<Brain>({ mode: 'AUTO', active: 'CLOUD' });
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  // Poll brain status so the pill reflects actual in-use engine.
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/brain/status`);
        if (res.ok) setBrain(await res.json());
      } catch {
        // retry next tick
      }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  // Measure button before painting the dropdown.
  useLayoutEffect(() => {
    if (!open || !btnRef.current) return;
    const r = btnRef.current.getBoundingClientRect();
    setPos({ top: r.bottom + 6, left: r.right - 180 });
  }, [open]);

  // Close on outside click — check both button AND dropdown refs.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (btnRef.current?.contains(target)) return;
      if (dropRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const setMode = async (mode: string) => {
    // Optimistic: flip label immediately. Deterministic modes also flip `active`.
    setBrain(b => ({
      mode,
      active: mode === 'AUTO' ? b.active : mode,
    }));
    try {
      const res = await fetch(`${API_BASE}/brain/mode?mode=${mode}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data && data.mode) {
          setBrain({ mode: data.mode, active: data.active ?? data.mode });
        }
      }
    } catch {
      // leave optimistic state — next poll will reconcile
    } finally {
      setOpen(false);
    }
  };

  const dotColor = DOT_COLOR(brain.active, brain.mode);
  const labelColor = MODE_COLOR[brain.active] ?? '#fff';

  return (
    <>
      <button
        ref={btnRef}
        className="cyber-button secondary"
        style={{ gap: 5, fontSize: 11, padding: '3px 8px' }}
        onClick={() => setOpen(o => !o)}
        title={`Brain: ${brain.mode} mode, using ${brain.active}`}
      >
        <span
          style={{
            width: 7, height: 7, borderRadius: '50%',
            background: dotColor, display: 'inline-block', flexShrink: 0,
          }}
        />
        <Cpu size={12} />
        <span style={{ color: labelColor }}>BRAIN: {brain.active}</span>
        <span style={{ color: '#6b7280', fontSize: 9 }}>▼</span>
      </button>

      {open && pos && createPortal(
        <div
          ref={dropRef}
          role="menu"
          style={{
            position: 'fixed',
            top: pos.top,
            left: Math.max(8, pos.left),
            minWidth: 220,
            background: '#0d1117',
            border: '1px solid rgba(0,243,255,0.35)',
            borderRadius: 8,
            padding: 8,
            zIndex: 10000,
            boxShadow: '0 10px 30px rgba(0,0,0,0.6)',
            fontFamily: 'inherit',
          }}
        >
          <div style={{
            fontSize: 9, color: '#6b7280', textTransform: 'uppercase',
            padding: '2px 8px 6px', letterSpacing: 1,
          }}>
            Brain mode
          </div>
          {(['AUTO', 'CLOUD', 'EDGE', 'RULES'] as const).map(m => {
            const active = brain.mode === m;
            return (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  background: active ? 'rgba(0,243,255,0.12)' : 'transparent',
                  border: active ? '1px solid rgba(0,243,255,0.4)' : '1px solid transparent',
                  color: active ? '#00f3ff' : '#d1d5db',
                  padding: '6px 10px',
                  fontSize: 11,
                  cursor: 'pointer',
                  borderRadius: 5,
                  marginBottom: 2,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: active ? 700 : 500 }}>{m}</span>
                  {active && <span style={{ fontSize: 9, opacity: 0.8 }}>active</span>}
                </div>
                <div style={{ fontSize: 9, color: '#6b7280', marginTop: 2 }}>
                  {MODE_BLURB[m]}
                </div>
              </button>
            );
          })}
          <div style={{
            fontSize: 9, color: '#6b7280',
            padding: '6px 10px 2px',
            borderTop: '1px solid rgba(255,255,255,0.08)',
            marginTop: 4,
          }}>
            In use: <span style={{ color: MODE_COLOR[brain.active] ?? '#fff' }}>{brain.active}</span>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
