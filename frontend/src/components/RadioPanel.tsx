import { useState, useRef } from 'react';
import { Radio, Mic, MicOff, RotateCcw } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

type Lead = {
  id: string;
  tick: number;
  lang: string;
  raw: string;
  english: string;
  x: number | null;
  y: number | null;
  urgency: string;
  status: string;
};

const LANGUAGES = [
  { code: 'en-MY', label: 'EN' },
  { code: 'ms-MY', label: 'BM' },
  { code: 'tl-PH', label: 'TL' },
  { code: 'id-ID', label: 'ID' },
  { code: 'th-TH', label: 'TH' },
];

const URGENCY_COLOR: Record<string, string> = {
  CRITICAL: '#f87171',
  URGENT: '#fbbf24',
  STABLE: '#4ade80',
};

type Props = { leads: Lead[] };

export default function RadioPanel({ leads }: Props) {
  const [lang, setLang] = useState('en-MY');
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState('');
  const recognitionRef = useRef<any>(null);

  const startRecording = () => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) { setStatus('Speech API not supported'); return; }
    const rec = new SpeechRecognition();
    rec.lang = lang;
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = async (e: any) => {
      const transcript = e.results[0][0].transcript;
      setStatus(`Sending: "${transcript}"`);
      try {
        const params = new URLSearchParams({ lang: lang.split('-')[0].toUpperCase(), text: transcript });
        await fetch(`${API_BASE}/radio-intel?${params}`, { method: 'POST' });
        setStatus('Intel submitted.');
      } catch {
        setStatus('Send failed.');
      }
    };
    rec.onerror = () => { setStatus('Mic error.'); setIsRecording(false); };
    rec.onend = () => setIsRecording(false);
    recognitionRef.current = rec;
    rec.start();
    setIsRecording(true);
    setStatus('Listening…');
  };

  const stopRecording = () => {
    recognitionRef.current?.stop();
    setIsRecording(false);
  };

  const retryLead = async (lead: Lead) => {
    const params = new URLSearchParams({ lang: lead.lang, text: lead.raw });
    await fetch(`${API_BASE}/radio-intel?${params}`, { method: 'POST' });
  };

  const recent = [...leads].reverse().slice(0, 8);

  return (
    <div className="radio-panel" style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <Radio size={13} className="text-cyan" />
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: 1, color: '#00f3ff' }}>FIELD RADIO</span>
      </div>

      {/* Language selector */}
      <div style={{ display: 'flex', gap: 4 }}>
        {LANGUAGES.map(l => (
          <button
            key={l.code}
            className={`log-filter-btn ${lang === l.code ? 'active' : ''}`}
            style={{ fontSize: 10, padding: '2px 6px' }}
            onClick={() => setLang(l.code)}
          >{l.label}</button>
        ))}
      </div>

      {/* Push-to-talk */}
      <button
        className={`cyber-button ${isRecording ? 'danger' : 'primary'}`}
        style={{ width: '100%', justifyContent: 'center', gap: 6 }}
        onClick={isRecording ? stopRecording : startRecording}
      >
        {isRecording ? <MicOff size={14} /> : <Mic size={14} />}
        {isRecording ? 'STOP' : 'PUSH TO TALK'}
      </button>
      {status && <div style={{ fontSize: 10, color: '#9ca3af', textAlign: 'center' }}>{status}</div>}

      {/* Transcript feed */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
        {recent.length === 0 && (
          <div style={{ fontSize: 11, color: '#6b7280', textAlign: 'center', padding: 8 }}>
            No intel yet — activate radio to relay field reports
          </div>
        )}
        {recent.map(lead => (
          <div key={lead.id} className="metric-card" style={{ padding: '6px 8px', fontSize: 11 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#9ca3af' }}>{lead.id} · {lead.lang} · T{lead.tick}</span>
              <span style={{ color: URGENCY_COLOR[lead.urgency] ?? '#fff', fontWeight: 700, fontSize: 10 }}>
                {lead.urgency}
              </span>
            </div>
            <div style={{ color: '#d1d5db', marginTop: 2 }}>{lead.raw}</div>
            {lead.english && lead.english !== lead.raw && (
              <div style={{ color: '#9ca3af', fontStyle: 'italic', fontSize: 10 }}>{lead.english}</div>
            )}
            <div style={{ marginTop: 3, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                color: lead.status === 'GROUNDED' ? '#4ade80' : lead.status === 'UNGROUNDED' ? '#f87171' : '#fbbf24',
                fontSize: 10, fontWeight: 600
              }}>{lead.status}</span>
              {lead.x !== null && <span style={{ color: '#00f3ff', fontSize: 10 }}>({lead.x},{lead.y})</span>}
              {lead.status === 'UNGROUNDED' && (
                <button
                  style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af' }}
                  title="Retry grounding"
                  onClick={() => retryLead(lead)}
                ><RotateCcw size={11} /></button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
