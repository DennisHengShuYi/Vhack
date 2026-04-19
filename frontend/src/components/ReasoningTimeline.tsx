import { useState } from 'react';
import { GitBranch, ChevronDown, ChevronRight } from 'lucide-react';

type TimelineEvent = {
  id: string;
  tick: number;
  ts: string;
  kind: string;
  brain: string;
  duration_ms: number;
  payload: Record<string, any>;
};

const KIND_COLOR: Record<string, string> = {
  DECISION: '#00f3ff',
  LEAD_INVESTIGATE: '#fbbf24',
  BRAIN_SWITCH: '#a78bfa',
  CONTRACT: '#f87171',
  ERROR: '#ef4444',
  TOOL_CALL: '#4ade80',
};

const FILTERS = ['ALL', 'DECISIONS', 'LEADS', 'BRAIN', 'CONTRACTS', 'ERRORS'] as const;
type Filter = typeof FILTERS[number];

function filterMatches(ev: TimelineEvent, f: Filter) {
  if (f === 'ALL') return true;
  if (f === 'DECISIONS') return ev.kind === 'DECISION';
  if (f === 'LEADS') return ev.kind === 'LEAD_INVESTIGATE';
  if (f === 'BRAIN') return ev.kind === 'BRAIN_SWITCH';
  if (f === 'CONTRACTS') return ev.kind === 'CONTRACT';
  if (f === 'ERRORS') return ev.kind === 'ERROR';
  return true;
}

function EventRow({ ev }: { ev: TimelineEvent }) {
  const [open, setOpen] = useState(false);
  const color = KIND_COLOR[ev.kind] ?? '#9ca3af';
  const ts = new Date(ev.ts).toLocaleTimeString('en-MY', { hour12: false });

  return (
    <div style={{ borderLeft: `2px solid ${color}`, paddingLeft: 8, marginBottom: 6 }}>
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}
        onClick={() => setOpen(o => !o)}
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        <span style={{ color, fontSize: 10, fontWeight: 700, minWidth: 90 }}>{ev.kind}</span>
        <span style={{ color: '#6b7280', fontSize: 10 }}>T{ev.tick} · {ts}</span>
        <span style={{ marginLeft: 'auto', color: '#6b7280', fontSize: 10 }}>{ev.brain}</span>
        {ev.duration_ms > 0 && (
          <span style={{ color: '#9ca3af', fontSize: 10 }}>{ev.duration_ms.toFixed(0)}ms</span>
        )}
      </div>
      {open && (
        <pre style={{ fontSize: 10, color: '#d1d5db', margin: '4px 0 0 16px', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {JSON.stringify(ev.payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

type Props = { events: TimelineEvent[] };

export default function ReasoningTimeline({ events }: Props) {
  const [filter, setFilter] = useState<Filter>('ALL');
  const filtered = [...events].reverse().filter(e => filterMatches(e, filter));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <GitBranch size={12} style={{ color: '#00f3ff' }} />
        <span style={{ fontSize: 11, fontWeight: 600, color: '#00f3ff', letterSpacing: 1 }}>REASONING TIMELINE</span>
      </div>

      {/* Filter chips */}
      <div style={{ display: 'flex', gap: 4, padding: '6px 8px', flexWrap: 'wrap' }}>
        {FILTERS.map(f => (
          <button
            key={f}
            className={`log-filter-btn ${filter === f ? 'active' : ''}`}
            style={{ fontSize: 9, padding: '2px 5px' }}
            onClick={() => setFilter(f)}
          >{f}</button>
        ))}
      </div>

      {/* Event list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '4px 8px' }}>
        {filtered.length === 0 && (
          <div style={{ color: '#6b7280', fontSize: 11, textAlign: 'center', padding: 16 }}>
            No events yet — start a mission
          </div>
        )}
        {filtered.map(ev => <EventRow key={ev.id} ev={ev} />)}
      </div>
    </div>
  );
}
