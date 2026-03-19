import { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Cpu,
  Search,
  Battery,
  Activity,
  Map as MapIcon,
  History,
  AlertTriangle,
  Crosshair,
  Navigation,
  CheckCircle2,
  RefreshCcw,
  Send,
  Zap,
  Power,
  Wifi,
  WifiOff,
  Info,
  X,
  Mic,
  Radio
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Map3D from './components/Map3D';

// --- Constants ---
const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const GRID_W = 20;
const GRID_H = 15;
const POLL_INTERVAL_MS = 800;
const LOW_BATTERY_PCT = 25;

// --- Components ---

/** Renders a single line of AI reasoning with structured highlight labels */
function StructuredLogText({ text }: { text: string }) {
  const lines = text.split('\n');
  return (
    <div className="structured-log">
      {lines.map((line, i) => {
        const t = line.trim();
        if (!t) return <div key={i} className="log-spacer" />;

        // DRONE header line
        if (/^DRONE\s+\S+\s+@/.test(t)) {
          return <div key={i} className="slog-drone-header">{t}</div>;
        }
        // TRADEOFF line
        if (t.startsWith('TRADEOFF:')) {
          return (
            <div key={i} className="slog-row">
              <span className="slog-badge tradeoff">TRADEOFF</span>
              <span className="slog-text">{t.slice('TRADEOFF:'.length).trim()}</span>
            </div>
          );
        }
        // DECISION line
        if (t.startsWith('DECISION →') || t.startsWith('DECISION →')) {
          const zoneMatch = t.match(/→\s*(\w+)\s*[:\-]/);
          const zone = zoneMatch ? zoneMatch[1] : '';
          const rest = t.replace(/^DECISION\s*→\s*\w+\s*[:\-]?\s*/, '');
          return (
            <div key={i} className="slog-row">
              <span className="slog-badge decision">DECISION</span>
              {zone && <span className="slog-zone">{zone}</span>}
              <span className="slog-text">{rest}</span>
            </div>
          );
        }
        // MISSION PULSE line
        if (t.startsWith('MISSION PULSE:')) {
          return (
            <div key={i} className="slog-row pulse-row">
              <span className="slog-badge pulse">PULSE</span>
              <span className="slog-text">{t.slice('MISSION PULSE:'.length).trim()}</span>
            </div>
          );
        }
        // System badges: [AUTO], [ROUTING], [RTB], [SENTINEL], ⚠️, 🏁, 📡
        if (t.startsWith('[AUTO]')) return <div key={i} className="slog-system auto">{t}</div>;
        if (t.startsWith('[ROUTING]')) return <div key={i} className="slog-system routing">{t}</div>;
        if (t.startsWith('[RTB]')) return <div key={i} className="slog-system rtb">{t}</div>;
        if (t.startsWith('[SENTINEL]') || t.startsWith('🏁')) return <div key={i} className="slog-system complete">{t}</div>;
        if (t.startsWith('⚠️')) return <div key={i} className="slog-system warn">{t}</div>;
        if (t.startsWith('📡')) return <div key={i} className="slog-system dispatch">{t}</div>;
        if (t.startsWith('🔁')) return <div key={i} className="slog-system rtb">{t}</div>;

        // Default: render with **bold** markdown
        return (
          <div key={i} className="slog-plain" dangerouslySetInnerHTML={{
            __html: t
              .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          }} />
        );
      })}
    </div>
  );
}

/** Single log entry card */
function LogEntry({ entry }: { entry: any }) {
  const isAi = entry.level?.toLowerCase() === 'ai';
  return (
    <div className={`log-entry ${entry.level?.toLowerCase() ?? ''}`}>
      {isAi ? (
        <>
          <div className="ai-log-header">
            <span className="ai-log-label">⬡ SENTINEL AI</span>
            <span className="log-ts">{entry.ts}</span>
          </div>
          <div className="ai-log-body">
            <StructuredLogText text={entry.text || ""} />
          </div>
        </>
      ) : (
        <>
          <span className="log-ts">[{entry.ts}]</span>
          {entry.drone && <span className="log-drone">[{entry.drone}]</span>}
          <span className="log-text" dangerouslySetInnerHTML={{
            __html: (entry.text || "")
              .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
              .replace(/\n/g, '<br />')
          }} />
        </>
      )}
    </div>
  );
}

// ─── Triage CSS class helper ────────────────────────────────────────────────
function triageCssClass(triage: string): string {
  if (triage === "P1-CRITICAL") return "p1_critical";
  if (triage === "P2-URGENT")   return "p2_urgent";
  if (triage === "P3-STABLE")   return "p3_stable";
  return "p3_stable";
}

// ─── Victim List Panel ───────────────────────────────────────────────────────
function VictimListPanel({
  survivors,
  highlighted,
  onSelect,
}: {
  survivors: any[];
  highlighted: { x: number; y: number } | null;
  onSelect: (pos: { x: number; y: number } | null) => void;
}) {
  const TRIAGE_ORDER: Record<string, number> = {
    "P1-CRITICAL": 0,
    "P2-URGENT":   1,
    "P3-STABLE":   2,
  };

  const sorted = [...survivors]
    .filter(s => s.found)
    .sort((a, b) => {
      const ta = TRIAGE_ORDER[a.triage_priority] ?? 3;
      const tb = TRIAGE_ORDER[b.triage_priority] ?? 3;
      if (ta !== tb) return ta - tb;
      if (a.rescued !== b.rescued) return a.rescued ? 1 : -1;
      return 0;
    });

  if (sorted.length === 0) {
    return (
      <div className="victim-list-empty">
        <Search size={22} style={{ opacity: 0.4 }} />
        <span>No victims located yet</span>
      </div>
    );
  }

  return (
    <div className="victim-list">
      {sorted.map(v => {
        const isHighlighted = highlighted?.x === v.x && highlighted?.y === v.y;
        return (
          <div
            key={v.id}
            className={`victim-item ${triageCssClass(v.triage_priority)}${v.rescued ? " rescued" : ""}${isHighlighted ? " map-highlighted" : ""}`}
            onClick={() => onSelect(isHighlighted ? null : { x: v.x, y: v.y })}
            title="Click to highlight on map"
          >
            <div className="victim-item-header">
              <span className={`triage-badge ${triageCssClass(v.triage_priority)}`}>{v.triage_priority}</span>
              <span className="victim-id">{v.id}</span>
              <span className="victim-coord">({v.x},{v.y})</span>
              {isHighlighted && <Crosshair size={11} style={{ marginLeft: 'auto', color: 'var(--accent-cyan)', opacity: 0.8 }} />}
            </div>
            <div className="victim-condition">{(v.condition ?? "UNKNOWN").replace(/_/g, " ")}</div>
            <div className="victim-report-text">"{v.report}"</div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Main Sentinel Mission Dashboard
 */
export default function App() {
  const [state, setState] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected'>('disconnected');
  const [operatorMsg, setOperatorMsg] = useState("");
  const [isDeploying, setIsDeploying] = useState(false);
  const [activeDroneId, setActiveDroneId] = useState<string | null>(null);
  const [logFilter, setLogFilter] = useState<'all' | 'warn' | 'error' | 'victim_found' | 'ai'>('ai');
  const [showRtbOnly, setShowRtbOnly] = useState(false);
  const [is3DView, setIs3DView] = useState(false);
  const [victimCount, setVictimCount] = useState(10);
  const [showAssumptions, setShowAssumptions] = useState(false);
  const [leftTab, setLeftTab] = useState<'fleet' | 'victims'>('fleet');
  const [highlightedVictim, setHighlightedVictim] = useState<{ x: number; y: number } | null>(null);
  const [missionComplete, setMissionComplete] = useState(false);
  const celebrationFiredRef = useRef(false);
  const celebrationCanvasRef = useRef<HTMLCanvasElement>(null);
  const prevMissionActiveRef = useRef(false);

  const [wsStreamText, setWsStreamText] = useState("");
  const wsRef = useRef<WebSocket | null>(null);

  const logEndRef = useRef<HTMLDivElement>(null);
  const logScrollRef = useRef<HTMLDivElement>(null);
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  const recognitionRef = useRef<any>(null);
  const autoRescuedRef = useRef<Set<string>>(new Set());

  // Victim popup handling + auto-switch to VICTIMS tab on detection
  useEffect(() => {
    const waiting = state?.drones?.find((d: any) => d.is_waiting_response);
    if (waiting) {
      setActiveDroneId(waiting.id);
      setLeftTab('victims');
    }
  }, [state]);

  // Mission completion detection
  useEffect(() => {
    const s = state?.stats;
    if (!s) return;
    const wasActive = prevMissionActiveRef.current;
    prevMissionActiveRef.current = s.mission_active;

    if (!s.mission_active) {
      // Mission just stopped: celebrate only if all survivors were rescued
      if (wasActive && !celebrationFiredRef.current && s.total_victims > 0 && s.victims_rescued === s.total_victims) {
        celebrationFiredRef.current = true;
        setMissionComplete(true);
      }
      return;
    }
    // Mission (re)started: clear any prior celebration and reset guard
    if (s.victims_rescued === 0) {
      celebrationFiredRef.current = false;
      setMissionComplete(false);
    }
  }, [state]);

  // Canvas particle celebration
  useEffect(() => {
    if (!missionComplete) return;
    const canvas = celebrationCanvasRef.current;
    if (!canvas) return;
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    const ctx = canvas.getContext('2d')!;

    const COLORS = ['#00f3ff', '#00ff88', '#ffb300', '#ffffff', '#7dd3fc'];
    interface Particle {
      x: number; y: number; vx: number; vy: number;
      w: number; h: number; color: string;
      life: number; decay: number; rotation: number; rotSpeed: number;
    }
    const particles: Particle[] = Array.from({ length: 160 }, () => ({
      x: Math.random() * canvas.width,
      y: canvas.height + 10,
      vx: (Math.random() - 0.5) * 5,
      vy: -(Math.random() * 9 + 5),
      w: Math.random() * 8 + 3,
      h: Math.random() * 4 + 2,
      color: COLORS[Math.floor(Math.random() * COLORS.length)],
      life: 1,
      decay: Math.random() * 0.008 + 0.004,
      rotation: Math.random() * Math.PI * 2,
      rotSpeed: (Math.random() - 0.5) * 0.18,
    }));

    let animId: number;
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      let anyAlive = false;
      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.15; // gravity
        p.life -= p.decay;
        p.rotation += p.rotSpeed;
        if (p.life <= 0) continue;
        anyAlive = true;
        ctx.save();
        ctx.globalAlpha = p.life;
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rotation);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h);
        ctx.restore();
      }
      if (anyAlive) animId = requestAnimationFrame(animate);
    };
    animate();
    return () => cancelAnimationFrame(animId);
  }, [missionComplete]);

  // WebSocket connection for live agent token streaming
  useEffect(() => {
    const WS_URL = API_BASE.replace(/^http/, 'ws') + '/ws/stream';
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        setWsStreamText(event.data);
      };

      ws.onclose = () => {
        // Auto-reconnect after 2s
        reconnectTimer = setTimeout(connect, 2000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  // Auto-scroll log to bottom when new entries arrive (unless user scrolled up)
  useEffect(() => {
    if (!userScrolledUp && logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
    }
  }, [state, wsStreamText, logFilter, userScrolledUp]);

  // Poll state every 800ms
  useEffect(() => {
    const fetchData = async () => {
      try {
        const resp = await fetch(`${API_BASE}/state`);
        const data = await resp.json();
        setState(data);
        setIsLoading(false);
        setConnectionStatus('connected');
      } catch (err) {
        console.error("Fetch failed:", err);
        setConnectionStatus('disconnected');
      }
    };

    fetchData();
    const interval = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const runMission = async () => {
    setIsDeploying(true);
    await fetch(`${API_BASE}/run-mission`, { method: 'POST' });
    setTimeout(() => setIsDeploying(false), 2000);
  };

  const [isTalking, setIsTalking] = useState<boolean | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [transcription, setTranscription] = useState("");
  const [speechError, setSpeechError] = useState<string | null>(null);

  const toggleVoiceCapture = () => {
    setSpeechError(null);
    if (isRecording) {
      if (recognitionRef.current) {
        recognitionRef.current.onend = null;
        recognitionRef.current.stop();
      }
      setIsRecording(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (SpeechRecognition) {
      try {
        const recognition = new SpeechRecognition();
        recognitionRef.current = recognition;
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
          setIsRecording(true);
        };

        recognition.onresult = (event: any) => {
          let currentTranscription = '';
          for (let i = 0; i < event.results.length; i++) {
            currentTranscription += event.results[i][0].transcript;
          }
          if (currentTranscription) {
            setTranscription(currentTranscription);
            setOperatorMsg(currentTranscription);
          }
        };

        recognition.onerror = (event: any) => {
          setSpeechError(`Error: ${event.error}. Check microphone permissions.`);
          setIsRecording(false);
        };

        recognition.onend = () => {
          setIsRecording(false);
        };

        recognition.start();
      } catch (_err) {
        setSpeechError("Failed to initialize speech recognition.");
        setIsRecording(false);
      }
    } else {
      setSpeechError("Web Speech API not supported in this browser.");
      setIsRecording(true);
      setTimeout(() => {
        setTranscription("Simulated: My friend is at grid 10");
        setOperatorMsg("My friend is at grid 10");
        setIsRecording(false);
      }, 3000);
    }
  };

  const stopMission = async () => {
    await fetch(`${API_BASE}/stop-mission`, { method: 'POST' });
  };

  const resetMission = async () => {
    await fetch(`${API_BASE}/reset?num_victims=${victimCount}`, { method: 'POST' });
    setActiveDroneId(null);
    setIsTalking(null);
  };

  const respondToVictim = async (droneId: string) => {
    await fetch(`${API_BASE}/victim-response?drone_id=${droneId}&operator_message=${encodeURIComponent(operatorMsg)}`, { method: 'POST' });
    setOperatorMsg("");
    setIsTalking(null);
    setTranscription("");
  };

  const guideVictim = async (droneId: string) => {
    await fetch(`${API_BASE}/guide-victim?drone_id=${droneId}`, { method: 'POST' });
    setIsTalking(null);
  };


  if (isLoading) return <div className="loading-container"><Zap className="animate-pulse" /> INITIALIZING SENTINEL...</div>;

  const { stats, drones, zone, log, base_station } = state || {};
  // Prefer live WebSocket stream; fall back to polling value if WS not yet connected
  const streaming_text = wsStreamText || state?.streaming_text || "";
  const baseX = base_station?.x ?? 0;
  const baseY = base_station?.y ?? 0;
const waitingDrone = drones?.find((d: any) => d.is_waiting_response);
  const isReturningDrone = (drone: any) =>
    drone?.returning_to_base ||
    String(drone?.status_label || '').toLowerCase().includes('rtb') ||
    String(drone?.status || '').toLowerCase() === 'returning';
  const displayedDrones = showRtbOnly ? (drones || []).filter(isReturningDrone) : (drones || []);
  const filteredLog = (log || []).filter((entry: any) => {
    if (logFilter === 'all') return true;
    return entry.level?.toLowerCase() === logFilter;
  });

  return (
    <div className="app-container">
      {/* --- HUD HEADER --- */}
      <header className="hud-header glass">
        <div className="brand">
          <Shield className="brand-logo" />
          <div className="brand-text">
<<<<<<< HEAD
            <h1>RescueSwarm</h1>
            <span className="subtitle">AI Drone Search & Rescue Simulation</span>
=======
            <h1>RESCUE SWARM</h1>
            <span className="subtitle">First Responder Swarm Intelligence v2.0.0</span>
>>>>>>> 6b93e1abd8c3329dd18bf63253404734fb1243ba
          </div>
        </div>

        <div className="global-stats">
          <div className={`conn-badge ${connectionStatus}`}>
            {connectionStatus === 'connected'
              ? <><Wifi size={13} /> ONLINE</>
              : <><WifiOff size={13} /> OFFLINE</>}
          </div>
          <StatBox icon={<MapIcon size={14} />} label="COVERAGE" value={`${stats.coverage_pct}%`} color="cyan" />
          <StatBox icon={<Search size={14} />} label="FOUND" value={`${stats.victims_found}/${stats.total_victims}`} color="amber" />
          <StatBox icon={<CheckCircle2 size={14} />} label="RESCUED" value={`${stats.victims_rescued}`} color="success" />
          <div className="mission-timer font-mono">{stats.elapsed_ts}</div>
        </div>

        <div className="header-actions">
          {stats.mission_active ? (
            <button className="cyber-button danger" onClick={stopMission}>STOP MISSION</button>
          ) : (
            <button className="cyber-button primary" onClick={runMission} disabled={isDeploying}>
              {isDeploying ? <RefreshCcw className="animate-spin" size={14} /> : <Zap size={14} />}
              {isDeploying ? ' DEPLOYING…' : ' DEPLOY SWARM'}
            </button>
          )}

          <div className="header-divider" />

          {/* Victim count — only changeable when mission not active; applies on Reset */}
          <div className={`victim-inline ${stats.mission_active ? 'locked' : ''}`}>
            <span className="victim-inline-label">SURVIVORS</span>
            <div className="victim-inline-controls">
              <button className="vic-adj" disabled={stats.mission_active} onClick={() => setVictimCount(c => Math.max(1, c - 1))}>−</button>
              <span className="vic-count font-mono">{victimCount}</span>
              <button className="vic-adj" disabled={stats.mission_active} onClick={() => setVictimCount(c => Math.min(50, c + 1))}>+</button>
            </div>
          </div>
          <button
            className="cyber-button secondary reset-btn"
            onClick={resetMission}
            disabled={stats.mission_active}
            title={`Reset map with ${victimCount} survivors`}
          >
            <RefreshCcw size={13} /> RESET
          </button>

          <div className="header-divider" />

          <button className={`cyber-button toggle-3d ${is3DView ? 'active' : ''}`} onClick={() => setIs3DView(p => !p)}>3D</button>
          <button className="cyber-button info-btn" onClick={() => setShowAssumptions(true)} title="Simulation Parameters"><Info size={15} /></button>
        </div>
      </header>

      {/* --- MAIN LAYOUT --- */}
      <main className="main-content">

        {/* Left Side: Fleet Status / Victims */}
        <section className="side-panel">
          {/* Tab switcher */}
          <div className="left-tab-bar glass">
            <button className={`left-tab-btn ${leftTab === 'fleet' ? 'active' : ''}`} onClick={() => setLeftTab('fleet')}>
              <Activity size={12} /> FLEET
              <span className="tab-count">{(drones || []).length}</span>
            </button>
            <button className={`left-tab-btn ${leftTab === 'victims' ? 'active' : ''}`} onClick={() => setLeftTab('victims')}>
              <AlertTriangle size={12} /> VICTIMS
              <span className={`tab-count ${(zone?.survivors || []).filter((s: any) => s.found && !s.rescued).length > 0 ? 'urgent' : ''}`}>
                {(zone?.survivors || []).filter((s: any) => s.found && !s.rescued).length}
              </span>
            </button>
          </div>
          {/* Fleet controls sub-row */}
          {leftTab === 'fleet' && (
            <div className="fleet-controls-bar glass">
              <button className={`toggle-btn ${showRtbOnly ? 'active' : ''}`} onClick={() => setShowRtbOnly((v) => !v)}>
                {showRtbOnly ? 'RTB ONLY' : 'ALL'}
              </button>
              <span className="telemetry-count">{displayedDrones.length}</span>
            </div>
          )}
          <div className="tab-content glass scroll-area">
            {leftTab === 'victims' ? (
              <VictimListPanel survivors={zone?.survivors || []} highlighted={highlightedVictim} onSelect={setHighlightedVictim} />
            ) : (
            <div className="drone-list">
              {displayedDrones.map((drone: any) => {
                const isOffline = !drone.is_active;
                return (
                <motion.div
                  key={drone.id}
                  className={`drone-card ${activeDroneId === drone.id ? 'active' : ''} ${drone.is_waiting_response ? 'alert' : ''} ${isOffline ? 'offline' : ''}`}
                  whileHover={{ scale: 1.02 }}
                  onClick={() => setActiveDroneId(drone.id)}
                >
                  <div className="drone-card-header">
                    <div className="flex-row gap-2 items-center">
                      <span className={`heartbeat-dot ${isOffline ? 'offline' : 'online'}`} title={isOffline ? 'No signal' : 'Connected'} />
                      <span className="drone-id font-mono">{drone.id}</span>
                    </div>
                    <div className="flex-row gap-2 items-center">
                      <span className="text-xs opacity-60">{drone.battery.toFixed(0)}%</span>
                      <div className={`status-dot ${drone.status_label.toLowerCase().replace(/ /g, '-')}`}></div>
                    </div>
                  </div>
                  {isOffline ? (
                    <div className="drone-offline-body">
                      <WifiOff size={18} className="offline-icon" />
                      <span className="offline-label">AWAITING HEARTBEAT</span>
                      <span className="offline-sublabel">Joining swarm mesh network…</span>
                    </div>
                  ) : (
                  <div className="drone-card-body">
                    <div className="drone-telemetry">
                      <div className="tel-row">
                        <Battery size={14} />
                        <div className="battery-bar-container">
                          <div className={`battery-fill ${drone.battery < LOW_BATTERY_PCT ? 'critical' : ''}`} style={{ width: `${drone.battery}%` }}></div>
                        </div>
                        <span className="font-mono text-xs">{drone.battery.toFixed(0)}%</span>
                      </div>
                      <div className="tel-row">
                        <Navigation size={14} />
                        <span className="font-mono text-xs">({drone.x}, {drone.y}) · {drone.terrain?.toUpperCase() ?? 'N/A'}</span>
                      </div>
                      <div className={`status-chip ${drone.status_label.toLowerCase().replace(/ /g, '-').replace(/[^a-z0-9-]/g, '')}`}>
                        {drone.status_label}
                      </div>
                    </div>
                  </div>
                  )}
                </motion.div>
                );
              })}
            </div>
            )}
          </div>
        </section>

        {/* Center: Map */}
        <section className={`center-map glass ${is3DView ? 'view-3d' : ''}`}>
          <div className="map-overlay-header">
            <span className="font-mono text-xs"><Crosshair size={12} /> OVERLAY</span>
            <div className="legend">
              <>
                <span className="legend-item"><div className="dot" style={{ background: '#8a8a7a' }}></div> CITY</span>
                <span className="legend-item"><div className="dot" style={{ background: '#2a5c35' }}></div> FOREST</span>
                <span className="legend-item"><div className="dot" style={{ background: '#355f8b' }}></div> LAKE</span>
                <span className="legend-item"><div className="dot" style={{ background: 'rgba(55,145,80,0.68)', border: '1px solid rgba(0,220,200,0.45)' }}></div> SCANNED</span>
                <span className="legend-item"><div className="dot" style={{ background: '#00f3ff' }}></div> BASE</span>
                <span className="legend-item"><div className="dot" style={{ background: 'rgba(0, 243, 255, 0.7)' }}></div> DRONE</span>
                {stats.mission_active && <>
                  <span className="legend-item"><div className="dot" style={{ background: '#ff3d3d', boxShadow: '0 0 5px #ff3d3d' }}></div> VICTIM</span>
                  <span className="legend-item"><div className="dot" style={{ background: 'var(--accent-success)', boxShadow: '0 0 5px var(--accent-success)' }}></div> RESCUED</span>
                </>}
              </>
            </div>
          </div>

          {is3DView ? (
            <div className="map-3d-wrapper" style={{ flex: 1, position: 'relative', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(0, 243, 255, 0.2)' }}>
              <Map3D
                zone={zone}
                drones={drones || []}
                baseX={baseX}
                baseY={baseY}
                showRtbOnly={showRtbOnly}
              />
            </div>
          ) : (
            <div className="grid-container">
              {Array.from({ length: GRID_W * GRID_H }).map((_, i) => {
                const x = i % GRID_W;
                const y = Math.floor(i / GRID_W);
                const isScanned = zone.scanned_cells[y][x];
                const isBase = x === baseX && y === baseY;
                const dronesAtPos = drones.filter((d: any) => d.x === x && d.y === y);
                // Permanent victim color: include rescued survivors so the cell stays colored
                const survivorAtPos = stats.mission_active
                  ? zone.survivors.find((s: any) => s.x === x && s.y === y)
                  : null;
                const isVictimFound = !!survivorAtPos?.found;
                const isVictimRescued = !!survivorAtPos?.rescued;

                const terrain = zone.terrain_types[y][x];
                const hazard = zone.hazard_cells[y][x];

                let cellClass = "";
                if (terrain === 'city') cellClass += " city-terrain";
                else if (terrain === 'forest') cellClass += " forest-terrain";
                else if (terrain === 'lake') cellClass += " lake";
                // hazard only for non-lake cells (lakes are naturally impassable, not red)
                if (hazard && terrain !== 'lake') cellClass += " hazard";

                // Scanned applies on top of terrain — NOT mutually exclusive
                if (isScanned) cellClass += " scanned";
                if (isBase) cellClass += " base-cell";
                else if (survivorAtPos) {
                  if (isVictimRescued) cellClass += " rescued-cell";
                  else cellClass += " victim-cell";
                }
                if (highlightedVictim?.x === x && highlightedVictim?.y === y) cellClass += " victim-pinned";

                return (
                  <div key={i} className={`grid-cell${cellClass}`}>
                    {isScanned && <div className="scan-tick" />}
                    {stats.mission_active && zone.survivors.find((s: any) => s.x === x && s.y === y && !s.found && !s.rescued) && (
                      <div className="victim-dot" />
                    )}
                    <AnimatePresence>
                      {survivorAtPos && !isVictimRescued && (
                        <motion.div
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          className="victim-found-marker"
                          style={{ position: 'absolute', zIndex: 12 }}
                        >
                          <Crosshair className="animate-pulse" size={13} />
                        </motion.div>
                      )}
                    </AnimatePresence>

                    {dronesAtPos.length === 1 && (() => {
                      const d = dronesAtPos[0];
                      const returning = isReturningDrone(d);
                      const offline = !d.is_active;
                      return (
                        <motion.div
                          layoutId={`drone-${d.id}`}
                          className={`drone-marker ${d.is_waiting_response ? 'special' : ''} ${returning ? 'returning' : ''} ${offline ? 'offline' : ''} ${showRtbOnly && !returning ? 'dimmed' : ''}`}
                          title={offline ? `${d.id} — OFFLINE` : d.id}
                        >
                          <div className="content-wrapper">
                            {offline ? <WifiOff size={11} /> : <Cpu size={14} />}
                            <span className="d-label font-mono">{d.id.split('-')[1]}</span>
                          </div>
                        </motion.div>
                      );
                    })()}
                    {dronesAtPos.length > 1 && (
                      <div
                        className={`drone-marker multi ${dronesAtPos.some(isReturningDrone) ? 'returning' : ''} ${showRtbOnly && !dronesAtPos.some(isReturningDrone) ? 'dimmed' : ''}`}
                        title={dronesAtPos.map((d: any) => d.id).join(', ')}
                      >
                        <div className="content-wrapper">
                          <span className="d-label font-mono">×{dronesAtPos.length}</span>
                          <span className="d-label font-mono" style={{ fontSize: '0.55rem', opacity: 0.85 }}>
                            {dronesAtPos.map((d: any) => d.id.split('-')[1]).join('·')}
                          </span>
                        </div>
                      </div>
                    )}
                    {isBase && (
                      <div className="base-marker">
                        <Power size={11} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Right Side: Agent Reasoning Log */}
        <section className="log-panel">
          <div className="panel-section-header glass">
            <History size={14} /> SENTINEL REASONING LOG
            <div className="log-filter-group">
              <button className={`log-filter-btn ${logFilter === 'ai' ? 'active' : ''}`} onClick={() => setLogFilter('ai')}>AI</button>
              <button className={`log-filter-btn ${logFilter === 'all' ? 'active' : ''}`} onClick={() => setLogFilter('all')}>ALL</button>
              <button className={`log-filter-btn ${logFilter === 'warn' ? 'active' : ''}`} onClick={() => setLogFilter('warn')}>WARN</button>
              <button className={`log-filter-btn ${logFilter === 'victim_found' ? 'active' : ''}`} onClick={() => setLogFilter('victim_found')}>VICTIM</button>
            </div>
          </div>
          <div
            className="log-scroll glass"
            ref={logScrollRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
              setUserScrolledUp(!nearBottom);
            }}
          >
            {userScrolledUp && (
              <button
                className="scroll-to-latest-btn"
                onClick={() => {
                  if (logScrollRef.current) logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight;
                  setUserScrolledUp(false);
                }}
              >
                ↓ Latest
              </button>
            )}
            <div className="mission-log font-mono">
              {filteredLog.length === 0 && !streaming_text && (
                <div className="log-empty"><Cpu size={20} className="animate-pulse" /><span>Awaiting SENTINEL activity...</span></div>
              )}
              {filteredLog.map((entry: any) => (
                <LogEntry key={entry.id} entry={entry} />
              ))}
              {/* Live streaming card — shows LLM tokens as they arrive */}
              {streaming_text && (
                <div className="log-entry ai streaming-entry">
                  <div className="ai-log-header">
                    <span className="ai-log-label streaming-label">
                      <span className="streaming-dot" />
                      ⬡ SENTINEL AI — REASONING
                    </span>
                  </div>
                  <div className="ai-log-body streaming-body">
                    <StructuredLogText text={streaming_text} />
                    <span className="streaming-cursor" />
                  </div>
                </div>
              )}
              <div ref={logEndRef} />
            </div>
          </div>
        </section>
      </main>

      {/* --- VICTIM COMMUNICATION POPUP --- */}
      <AnimatePresence>
        {waitingDrone && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="victim-popup-overlay"
          >
            <motion.div
              initial={{ scale: 0.9, y: 20, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.9, y: 20, opacity: 0 }}
              className="victim-popup glass"
            >
              <div className="popup-header">
                <div className="brand">
                  <AlertTriangle className="text-amber animate-pulse" size={24} />
                  <div>
                    <h2>VICTIM CONTACT</h2>
                    <span className="subtitle">TRANSCEIVER CHANNEL ACTIVE</span>
                  </div>
                </div>
                <div className="popup-drone-id font-mono">
                  {waitingDrone.id}
                </div>
              </div>

              <div className="popup-body">
                {/* Thermal scan intel */}
                {waitingDrone?.last_thermal_scan && (
                  <div className="scan-intel-block">
                    <div className="scan-intel-row">
                      <span className="scan-intel-label">GRID REF</span>
                      <span className="scan-intel-value font-mono">({waitingDrone.last_thermal_scan.x}, {waitingDrone.last_thermal_scan.y})</span>
                    </div>
                    <div className="scan-intel-row">
                      <span className="scan-intel-label">CONFIDENCE</span>
                      <span className="scan-intel-value font-mono">{waitingDrone.last_thermal_scan.confidence}%</span>
                    </div>
                    <div className="scan-intel-row">
                      <span className="scan-intel-label">TRIAGE</span>
                      <span className={`triage-badge ${triageCssClass(waitingDrone.last_thermal_scan.triage ?? '')}`}>
                        {waitingDrone.last_thermal_scan.triage}
                      </span>
                      <span className="scan-condition-name">
                        {(waitingDrone.last_thermal_scan.condition ?? 'UNKNOWN').replace(/_/g, ' ')}
                      </span>
                    </div>
                    <div className="scan-intel-report">"{waitingDrone.last_thermal_scan.report}"</div>
                  </div>
                )}
                <div className="comms-segment">
                  <div className="segment-label"><Radio size={11} /> SURVIVOR INTEL</div>

                  {!isRecording && !transcription && (
                    <div className="comms-options">
                      <p className="comms-hint">Does the survivor report additional casualties? Log their coordinates to dispatch a drone.</p>
                      <div className="flex-row gap-2 mt-4">
                        <button className="cyber-button primary full-w" onClick={toggleVoiceCapture}>
                          <Mic size={16} /> LOG SURVIVOR REPORT
                        </button>
                        <button className="cyber-button secondary full-w" onClick={() => respondToVictim(waitingDrone.id)}>
                          <CheckCircle2 size={16} /> CONFIRM & RESUME
                        </button>
                      </div>
                    </div>
                  )}

                  {(isRecording || transcription) && (
                    <div className="voice-interface">
                      <div className="voice-status">
                        {isRecording ? (
                          <div className="flex items-center gap-2 text-amber">
                            <div className="recording-dot"></div>
                            <span>RECORDING REPORT...</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 text-success">
                            <CheckCircle2 size={14} />
                            <span>REPORT CAPTURED</span>
                          </div>
                        )}
                        <button className="reset-voice" onClick={() => { setTranscription(""); setOperatorMsg(""); if (isRecording) toggleVoiceCapture(); }}>
                          RESET
                        </button>
                      </div>

                      <div className="transcription-area font-mono">
                        {transcription || (isRecording ? "..." : "")}
                      </div>

                      {speechError && <div className="speech-error">{speechError}</div>}

                      {transcription && !isRecording && (
                        <p className="comms-dispatch-hint">Coordinates will be parsed and the nearest available drone dispatched.</p>
                      )}

                      <div className="flex-row gap-2 mt-4">
                        {isRecording ? (
                          <button className="cyber-button amber full-w" onClick={toggleVoiceCapture}>
                            STOP RECORDING
                          </button>
                        ) : (
                          <button className="cyber-button primary full-w" onClick={() => respondToVictim(waitingDrone.id)}>
                            <Send size={16} /> DISPATCH DRONE & CONFIRM
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* --- MISSION COMPLETE CELEBRATION --- */}
      <canvas
        ref={celebrationCanvasRef}
        className="celebration-canvas"
        style={{ display: missionComplete ? 'block' : 'none' }}
      />
      <AnimatePresence>
        {missionComplete && (
          <motion.div
            className="mission-complete-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setMissionComplete(false)}
          >
            <motion.div
              className="mission-complete-card"
              initial={{ scale: 0.7, opacity: 0, y: 40 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.8, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 260, damping: 20 }}
              onClick={e => e.stopPropagation()}
            >
              <div className="mc-glow-ring" />
              <div className="mc-icon"><CheckCircle2 size={40} /></div>
              <h2 className="mc-title">MISSION ACCOMPLISHED</h2>
              <p className="mc-subtitle">ALL SURVIVORS ACCOUNTED FOR</p>
              <div className="mc-stats">
                <div className="mc-stat">
                  <span className="mc-stat-value">{state?.stats?.total_victims ?? 0}</span>
                  <span className="mc-stat-label">SURVIVORS</span>
                </div>
                <div className="mc-stat-divider" />
                <div className="mc-stat">
                  <span className="mc-stat-value">{state?.stats?.victims_rescued ?? 0}</span>
                  <span className="mc-stat-label">CONFIRMED</span>
                </div>
                <div className="mc-stat-divider" />
                <div className="mc-stat">
                  <span className="mc-stat-value">{state?.stats?.coverage_pct ?? 0}%</span>
                  <span className="mc-stat-label">COVERAGE</span>
                </div>
                <div className="mc-stat-divider" />
                <div className="mc-stat">
                  <span className="mc-stat-value">{state?.stats?.elapsed_ts ?? '--'}</span>
                  <span className="mc-stat-label">ELAPSED</span>
                </div>
              </div>
              <button className="cyber-button secondary mc-dismiss" onClick={() => setMissionComplete(false)}>
                DISMISS
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* --- ASSUMPTIONS MODAL --- */}
      <AnimatePresence>
        {showAssumptions && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="assumptions-overlay"
            onClick={() => setShowAssumptions(false)}
          >
            <motion.div
              initial={{ scale: 0.92, y: 24, opacity: 0 }}
              animate={{ scale: 1, y: 0, opacity: 1 }}
              exit={{ scale: 0.92, y: 24, opacity: 0 }}
              className="assumptions-modal glass"
              onClick={e => e.stopPropagation()}
            >
              <div className="assumptions-header">
                <div className="brand">
                  <Info size={20} style={{ color: 'var(--accent-cyan)' }} />
                  <div>
                    <h2>SIMULATION PARAMETERS</h2>
                    <span className="subtitle">Design assumptions &amp; engine constants</span>
                  </div>
                </div>
                <button className="close-btn" onClick={() => setShowAssumptions(false)}><X size={18} /></button>
              </div>

              <div className="assumptions-body">
                {/* Terrain */}
                <div className="assump-section">
                  <div className="assump-section-title">🗺️ TERRAIN SYSTEM</div>
                  <table className="assump-table">
                    <thead>
                      <tr><th>Terrain</th><th>Survivor Weight</th><th>Passable</th><th>Battery / Move</th><th>Visual</th></tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td><span className="terrain-badge city">CITY</span></td>
                        <td className="highlight">5× (dense population)</td>
                        <td className="ok">✓ Yes</td>
                        <td>1.0%</td>
                        <td><div className="swatch" style={{ background: '#8a8a7a' }}></div></td>
                      </tr>
                      <tr>
                        <td><span className="terrain-badge forest">FOREST</span></td>
                        <td>2× (hikers / campers)</td>
                        <td className="ok">✓ Yes</td>
                        <td className="warn-text">1.5% ↑</td>
                        <td><div className="swatch" style={{ background: '#2a5c35' }}></div></td>
                      </tr>
                      <tr>
                        <td><span className="terrain-badge flat">FLAT</span></td>
                        <td>1× (baseline)</td>
                        <td className="ok">✓ Yes</td>
                        <td>1.0%</td>
                        <td><div className="swatch" style={{ background: '#4b6b4f' }}></div></td>
                      </tr>
                      <tr>
                        <td><span className="terrain-badge lake">LAKE</span></td>
                        <td className="muted">0 (nobody in water)</td>
                        <td className="err">✗ No</td>
                        <td className="muted">—</td>
                        <td><div className="swatch" style={{ background: '#355f8b' }}></div></td>
                      </tr>
                    </tbody>
                  </table>
                </div>

              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* --- CSS - Inline specifically for the dashboard components --- */}
      <style>{`
        .app-container {
          display: flex;
          flex-direction: column;
          height: 100vh;
          width: 100vw;
          padding: 1rem;
          gap: 1rem;
          background: radial-gradient(circle at top right, #10101a 0%, #050508 100%);
        }

        .hud-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem 2rem;
          min-height: 80px;
        }

        .brand {
          display: flex;
          align-items: center;
          gap: 1rem;
        }
        .brand-logo { color: var(--accent-cyan); width: 32px; height: 32px; filter: drop-shadow(0 0 8px var(--accent-cyan)); }
        .brand-text h1 { font-size: 1.5rem; margin: 0; line-height: 1; }
        .brand-text .subtitle { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; }

        .global-stats {
          display: flex;
          gap: 2rem;
          align-items: center;
        }

        .mission-timer {
          font-size: 1.5rem;
          color: var(--accent-cyan);
          text-shadow: 0 0 10px rgba(0, 243, 255, 0.5);
          min-width: 120px;
          text-align: center;
        }

        .main-content {
          display: grid;
          grid-template-columns: 260px 1fr 420px;
          gap: 1rem;
          flex: 1;
          overflow: hidden;
        }

        .side-panel { display: flex; flex-direction: column; gap: 0.5rem; height: 100%; overflow: hidden; }
        .log-panel { display: flex; flex-direction: column; gap: 0.5rem; height: 100%; overflow: hidden; }

        .panel-section-header {
          display: flex; align-items: center; gap: 8px;
          padding: 10px 14px; font-family: 'Orbitron', sans-serif;
          font-size: 0.75rem; color: var(--accent-cyan);
          border-radius: 8px 8px 0 0; flex-shrink: 0;
        }
        .fleet-controls { margin-left: auto; display: flex; align-items: center; gap: 8px; }
        .log-filter-group { margin-left: auto; display: flex; gap: 4px; }

        .tab-content { flex: 1; padding: 1rem; position: relative; overflow: hidden; }
        .scroll-area { overflow-y: auto; }
        .log-scroll { flex: 1; padding: 1rem; overflow-y: auto; position: relative; }
        .scroll-to-latest-btn {
          position: sticky; top: 0; left: 50%; transform: translateX(-50%);
          display: block; margin: 0 auto 8px;
          background: rgba(165, 243, 252, 0.15); color: #a5f3fc;
          border: 1px solid rgba(165, 243, 252, 0.4); border-radius: 999px;
          padding: 4px 14px; font-size: 0.7rem; cursor: pointer; z-index: 10;
          font-family: 'Orbitron', sans-serif; letter-spacing: 0.05em;
          backdrop-filter: blur(4px);
        }
        .scroll-to-latest-btn:hover { background: rgba(165, 243, 252, 0.25); }

        .telemetry-toolbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 10px;
          gap: 8px;
        }
        .toggle-btn {
          font-size: 0.68rem;
          padding: 5px 10px;
          border-radius: 999px;
          border: 1px solid rgba(255,255,255,0.25);
          color: var(--text-muted);
          background: rgba(255,255,255,0.04);
          cursor: pointer;
        }
        .toggle-btn.active {
          color: #ffe8b5;
          border-color: var(--accent-amber);
          background: rgba(255, 179, 0, 0.14);
        }
        .telemetry-count { font-size: 0.75rem; color: var(--text-muted); }

        .drone-card {
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);
          border-radius: 8px; padding: 12px; margin-bottom: 0.8rem; cursor: pointer;
        }
        .drone-card.active { border-color: var(--accent-cyan); background: rgba(0, 243, 255, 0.05); }
        .drone-card.alert { border-color: var(--accent-amber); background: rgba(255, 179, 0, 0.1); box-shadow: 0 0 15px rgba(255, 179, 0, 0.2); }
        .drone-card.offline { border-color: rgba(255,255,255,0.08); background: rgba(0,0,0,0.25); opacity: 0.65; }

        /* Heartbeat indicator dot */
        .heartbeat-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .heartbeat-dot.online { background: var(--accent-success); box-shadow: 0 0 6px var(--accent-success); animation: hb-pulse 2s ease-in-out infinite; }
        .heartbeat-dot.offline { background: #555; box-shadow: none; }
        @keyframes hb-pulse { 0%,100%{opacity:1;box-shadow:0 0 4px var(--accent-success);} 50%{opacity:0.5;box-shadow:0 0 10px var(--accent-success);} }

        /* Offline card body */
        .drone-offline-body { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px 0 6px; color: rgba(255,255,255,0.35); }
        .offline-icon { opacity: 0.4; }
        .offline-label { font-family: 'Orbitron', monospace; font-size: 0.6rem; letter-spacing: 0.12em; color: rgba(255,255,255,0.4); }
        .offline-sublabel { font-size: 0.6rem; opacity: 0.4; animation: ellipsis-blink 1.4s step-end infinite; }
        @keyframes ellipsis-blink { 0%,100%{opacity:0.4;} 50%{opacity:0.15;} }

        /* Offline drone marker on map */
        .drone-marker.offline { background: rgba(80,80,80,0.6) !important; box-shadow: none !important; border: 1px dashed rgba(255,255,255,0.2) !important; opacity: 0.5; }
        .drone-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .drone-id { font-size: 1rem; font-weight: bold; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #444; }
        .status-dot.ready { background: var(--accent-success); box-shadow: 0 0 5px var(--accent-success); }
        .status-dot.navigating, .status-dot.resuming { background: var(--accent-cyan); }
        .status-dot.scanning { background: var(--accent-amber); animation: pulse 1s infinite; }
        .status-dot.victim_detected, .status-dot.alert { background: var(--accent-red); }

        .battery-bar-container { flex: 1; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; }
        .battery-fill { height: 100%; background: var(--accent-success); border-radius: 2px; }
        .battery-fill.critical { background: var(--accent-red); }
        .tel-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
        .status-chip {
          display: inline-flex;
          margin-top: 6px;
          padding: 3px 8px;
          border-radius: 999px;
          font-size: 0.72rem;
          color: #dff9ff;
          background: rgba(0, 243, 255, 0.12);
          border: 1px solid rgba(0, 243, 255, 0.35);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .status-chip.charging { color: #ffe8b5; background: rgba(255, 179, 0, 0.12); border-color: rgba(255, 179, 0, 0.35); }
        .status-chip.victim-detected, .status-chip.victim-standby { color: #ffd2d2; background: rgba(255, 61, 61, 0.15); border-color: rgba(255, 61, 61, 0.4); }
        .status-chip.ready, .status-chip.awaiting-orders { color: #ccffe8; background: rgba(0, 255, 136, 0.1); border-color: rgba(0, 255, 136, 0.35); }
        .status-chip.rtb--complete, .status-chip.guiding-to-base { color: #ffe8b5; background: rgba(255, 179, 0, 0.12); border-color: rgba(255, 179, 0, 0.35); }

        .log-controls { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
        .log-filter-btn {
          font-size: 0.68rem;
          padding: 4px 8px;
          border-radius: 999px;
          border: 1px solid rgba(255,255,255,0.2);
          color: var(--text-muted);
          background: rgba(255,255,255,0.04);
          cursor: pointer;
        }
        .log-filter-btn.active {
          color: var(--text-primary);
          border-color: var(--accent-cyan);
          background: rgba(0, 243, 255, 0.12);
        }
        .mission-log { font-size: 0.8rem; line-height: 1.6; color: var(--text-primary); }
        .log-entry { margin-bottom: 4px; display: flex; gap: 6px; }
        .log-ts { color: var(--accent-cyan); opacity: 0.85; }
        .log-drone { color: var(--accent-amber); }
        .log-entry.verbal { color: #00f3ff; font-style: italic; border-left: 3px solid #00f3ff; padding-left: 10px; margin: 4px 0; text-shadow: 0 0 5px rgba(0, 243, 255, 0.3); }
        .log-entry.victim_found { color: #ffb300; font-weight: bold; background: rgba(255, 179, 0, 0.15); padding: 5px 8px; border-radius: 4px; margin: 6px 0; border: 1px solid rgba(255, 179, 0, 0.3); box-shadow: 0 0 10px rgba(255, 179, 0, 0.2); }
        .log-entry.ai {
          display: block;
          background: rgba(165, 243, 252, 0.05);
          border: 1px solid rgba(165, 243, 252, 0.18);
          border-left: 3px solid #a5f3fc;
          border-radius: 0 6px 6px 0;
          padding: 8px 10px;
          margin: 8px 0;
        }
        .ai-log-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
          padding-bottom: 5px;
          border-bottom: 1px solid rgba(165, 243, 252, 0.12);
        }
        .ai-log-label {
          font-size: 0.68rem;
          color: #a5f3fc;
          letter-spacing: 0.08em;
          font-family: 'Orbitron', sans-serif;
        }
        .ai-log-header .log-ts { color: rgba(165, 243, 252, 0.45); font-size: 0.68rem; }
        .ai-log-body {
          color: #dff9ff;
          font-size: 0.78rem;
          line-height: 1.75;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .log-entry.warn { color: #ffb300; opacity: 0.9; }
        .log-entry.error { color: #ff3d3d; font-weight: bold; background: rgba(255, 61, 61, 0.1); padding: 2px 4px; }
        .log-entry.success { color: #00ff88; text-shadow: 0 0 5px rgba(0, 255, 136, 0.3); }
        .log-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; opacity: 0.35; padding: 2rem; font-family: 'Orbitron', sans-serif; font-size: 0.75rem; }

        /* ── Streaming Entry ── */
        .streaming-entry {
          border-left-color: #a5f3fc !important;
          background: rgba(165,243,252,0.08) !important;
          animation: stream-glow 1.5s ease-in-out infinite alternate;
        }
        @keyframes stream-glow {
          from { box-shadow: none; }
          to   { box-shadow: 0 0 12px rgba(165,243,252,0.15); }
        }
        .streaming-label { display: flex; align-items: center; gap: 8px; }
        .streaming-dot {
          display: inline-block; width: 7px; height: 7px; border-radius: 50%;
          background: #a5f3fc;
          animation: dot-pulse 0.8s ease-in-out infinite alternate;
        }
        @keyframes dot-pulse {
          from { opacity: 1; transform: scale(1); }
          to   { opacity: 0.3; transform: scale(0.7); }
        }
        .streaming-body { opacity: 0.92; }
        .streaming-cursor {
          display: inline-block; width: 2px; height: 0.9em;
          background: #a5f3fc; margin-left: 2px; vertical-align: text-bottom;
          animation: blink 0.7s step-end infinite;
        }
        @keyframes blink { 50% { opacity: 0; } }

        /* ── Structured Log Text ── */
        .structured-log { display: flex; flex-direction: column; gap: 2px; }
        .log-spacer { height: 5px; }
        .slog-drone-header {
          font-family: 'Orbitron', sans-serif; font-size: 0.67rem; font-weight: 700;
          color: #a5f3fc; margin: 7px 0 3px;
          padding: 3px 7px; background: rgba(165,243,252,0.08); border-radius: 4px;
          letter-spacing: 0.04em;
        }
        .slog-row { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
        .pulse-row { margin-top: 7px; padding-top: 5px; border-top: 1px solid rgba(165,243,252,0.1); }
        .slog-badge {
          font-family: 'Orbitron', sans-serif; font-size: 0.57rem; font-weight: 700;
          letter-spacing: 0.06em; padding: 1px 6px; border-radius: 3px; flex-shrink: 0; white-space: nowrap;
        }
        .slog-badge.tradeoff { background: rgba(255,179,0,0.13); color: #ffb300; border: 1px solid rgba(255,179,0,0.28); }
        .slog-badge.decision { background: rgba(0,255,136,0.1); color: #00ff88; border: 1px solid rgba(0,255,136,0.28); }
        .slog-badge.pulse    { background: rgba(165,243,252,0.1); color: #a5f3fc; border: 1px solid rgba(165,243,252,0.22); }
        .slog-zone {
          font-family: 'Orbitron', sans-serif; font-size: 0.65rem; font-weight: 700;
          color: #00ff88; background: rgba(0,255,136,0.09);
          border: 1px solid rgba(0,255,136,0.22); border-radius: 3px; padding: 0 5px;
        }
        .slog-text { opacity: 0.82; line-height: 1.45; flex: 1; min-width: 0; }
        .slog-plain { opacity: 0.78; }
        .slog-system {
          font-family: 'Orbitron', sans-serif; font-size: 0.64rem;
          padding: 2px 7px; border-radius: 3px; margin: 1px 0;
        }
        .slog-system.auto     { color: #a5f3fc; background: rgba(165,243,252,0.07); }
        .slog-system.routing  { color: #00ff88; background: rgba(0,255,136,0.06); }
        .slog-system.rtb      { color: #ffb300; background: rgba(255,179,0,0.06); }
        .slog-system.complete { color: #00ff88; background: rgba(0,255,136,0.1); font-weight: 700; }
        .slog-system.warn     { color: #ff3d3d; background: rgba(255,61,61,0.07); }
        .slog-system.dispatch { color: #a5f3fc; background: rgba(165,243,252,0.07); }

        .center-map { display: flex; flex-direction: column; position: relative; padding: 1rem; }
        .map-overlay-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
        .legend { display: flex; gap: 1rem; font-size: 0.72rem; }
        .legend-item { display: flex; align-items: center; gap: 4px; opacity: 0.8; }
        .dot { width: 6px; height: 6px; border-radius: 50%; }
        .dot.base { background: var(--accent-cyan); }
        .dot.scanned { background: rgba(0, 243, 255, 0.2); }
        .dot.victim { background: var(--accent-amber); }
        .dot.hazard { background: rgba(255, 61, 61, 0.3); }

        .grid-container {
          display: grid;
          grid-template-columns: repeat(20, 1fr);
          grid-template-rows: repeat(15, 1fr);
          gap: 2px;
          flex: 1;
          background: rgba(255,255,255,0.02);
          border: 1px solid rgba(255,255,255,0.1);
          padding: 2px;
          transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.8s ease, border 0.8s ease, clip-path 0.8s ease;
          transform-style: preserve-3d;
        }

        .center-map.view-3d {
          perspective: 1200px;
        }

        .center-map.view-3d .grid-container {
          transform: rotateX(60deg) rotateZ(-45deg);
          box-shadow: -20px 30px 40px rgba(0,0,0,0.6);
          border: 1px solid rgba(0, 243, 255, 0.4);
          transform-origin: center center;
          align-self: center;
          justify-self: center;
          width: 80%;
          margin: 20px auto;
        }

        .grid-cell {
          background: rgba(14, 14, 28, 0.6);
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 1px solid rgba(255,255,255,0.03);
          transform-style: preserve-3d;
          transition: background-color 0.4s;
        }
        /* ── Scanned state — clearly visible over every terrain type ── */
        .grid-cell.scanned {
          border-color: rgba(0, 220, 200, 0.45) !important;
        }
        /* Flat scanned: cyan wash */
        .grid-cell.scanned:not(.city-terrain):not(.forest-terrain):not(.lake) {
          background: rgba(0, 180, 160, 0.28);
        }
        /* City scanned: bleached concrete — much lighter than unscanned grey */
        .grid-cell.city-terrain.scanned {
          background: rgba(195, 200, 178, 0.65) !important;
        }
        /* Forest scanned: bright canopy green — clearly lighter than deep forest */
        .grid-cell.forest-terrain.scanned {
          background: rgba(55, 145, 80, 0.68) !important;
        }
        /* Diagonal scan-lines overlay on all scanned cells */
        .grid-cell.scanned::after {
          content: '' !important;
          position: absolute !important; inset: 0 !important;
          background: repeating-linear-gradient(
            -45deg,
            transparent 0px, transparent 4px,
            rgba(0, 220, 200, 0.10) 4px, rgba(0, 220, 200, 0.10) 5px
          ) !important;
          pointer-events: none !important; z-index: 2 !important;
        }
        /* Small scan-complete dot in top-right corner */
        .scan-tick {
          position: absolute; top: 1px; right: 1px;
          width: 4px; height: 4px; border-radius: 50%;
          background: rgba(0, 220, 200, 0.85);
          box-shadow: 0 0 3px rgba(0, 220, 200, 0.7);
          z-index: 6; pointer-events: none;
        }
        .grid-cell.victim-cell {
          background: rgba(255, 160, 0, 0.22) !important;
          border-color: rgba(255, 160, 0, 0.4) !important;
          box-shadow: inset 0 0 6px rgba(255, 160, 0, 0.2);
        }
        .grid-cell.victim-cell {
          background: rgba(255, 61, 61, 0.15) !important;
          border-color: rgba(255, 61, 61, 0.3) !important;
          box-shadow: inset 0 0 10px rgba(255, 61, 61, 0.1);
          animation: pulse-red 2s infinite;
        }

        .grid-cell.rescued-cell {
          background: rgba(0, 200, 100, 0.15) !important;
          border-color: rgba(0, 200, 100, 0.3) !important;
        }

        .grid-cell.city-terrain {
          background: rgba(138, 138, 122, 0.45);
          border-color: rgba(180, 180, 160, 0.25);
        }
        .grid-cell.city-terrain::after {
          content: '';
          position: absolute; inset: 1px;
          background: repeating-linear-gradient(
            90deg,
            transparent 0px,
            transparent 3px,
            rgba(200,200,180,0.08) 3px,
            rgba(200,200,180,0.08) 4px
          );
          pointer-events: none;
        }
        .grid-cell.forest-terrain {
          background: rgba(42, 92, 53, 0.55);
          border-color: rgba(42, 120, 60, 0.3);
        }
        .grid-cell.forest-terrain::after {
          content: '';
          position: absolute; inset: 1px;
          background: radial-gradient(circle at 30% 40%, rgba(30,80,40,0.35) 30%, transparent 70%),
                      radial-gradient(circle at 70% 65%, rgba(20,70,30,0.3) 25%, transparent 60%);
          pointer-events: none;
        }
        .grid-cell.lake {
          background: rgba(30, 80, 140, 0.65);
          border-color: rgba(53, 130, 200, 0.35);
          box-shadow: inset 0 0 8px rgba(53, 95, 139, 0.35);
        }
        .grid-cell.lake::after {
          content: '';
          position: absolute; inset: 1px;
          background: repeating-linear-gradient(
            155deg,
            transparent 0px,
            transparent 4px,
            rgba(100, 180, 255, 0.06) 4px,
            rgba(100, 180, 255, 0.06) 5px
          );
          pointer-events: none;
        }
        .grid-cell.hazard { border: 1.5px solid rgba(255, 61, 61, 0.6) !important; background: rgba(124, 47, 47, 0.3); }

        .grid-cell.hidden-victim-cell {
          background: rgba(255, 61, 61, 0.12) !important;
          border-color: rgba(255, 61, 61, 0.25) !important;
          box-shadow: inset 0 0 10px rgba(255, 61, 61, 0.1);
          animation: pulse-red 2s infinite;
        }
        @keyframes pulse-red {
          0% { background: rgba(255, 61, 61, 0.08); }
          50% { background: rgba(255, 61, 61, 0.18); }
          100% { background: rgba(255, 61, 61, 0.08); }
        }
        .drone-marker.multi {
          width: 34px; height: 34px;
          background: rgba(0, 243, 255, 0.75);
          outline: 2px solid rgba(255, 243, 0, 0.8);
          box-shadow: 0 0 14px var(--accent-cyan), 0 0 6px rgba(255,243,0,0.4);
        }
        .grid-cell.base-cell {
          background: rgba(0, 243, 255, 0.18) !important;
          border: 1px solid rgba(0, 243, 255, 0.5) !important;
          box-shadow: inset 0 0 8px rgba(0, 243, 255, 0.25), 0 0 6px rgba(0, 243, 255, 0.3);
        }
        .base-marker {
          position: absolute; z-index: 10;
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          color: var(--accent-cyan);
          filter: drop-shadow(0 0 6px var(--accent-cyan));
          animation: pulse 1.8s ease-in-out infinite;
        }
        .grid-cell:hover { background: rgba(255,255,255,0.04); }

        .content-wrapper {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
          transform-style: preserve-3d;
        }

        .center-map.view-3d .content-wrapper {
          transform: rotateZ(45deg) rotateX(-60deg) translateY(-15px);
          filter: drop-shadow(-8px 10px 6px rgba(0,0,0,0.6));
        }


        .drone-marker {
          width: 30px; height: 30px; background: rgba(0, 243, 255, 0.8); color: black;
          border-radius: 4px; display: flex; flex-direction: column; align-items: center; justify-content: center;
          box-shadow: 0 0 15px var(--accent-cyan); z-index: 10;
        }
        .drone-marker.special { background: var(--accent-amber); box-shadow: 0 0 15px var(--accent-amber); }
        .drone-marker.returning { outline: 2px solid var(--accent-amber); box-shadow: 0 0 18px rgba(255, 179, 0, 0.55); }
        .drone-marker.dimmed { opacity: 0.2; }
        .d-label { font-size: 0.7rem; line-height: 1; font-weight: bold; }
        .victim-dot {
          position: absolute; z-index: 8;
          width: 5px; height: 5px; border-radius: 50%;
          background: #ff3d3d;
          box-shadow: 0 0 3px #ff3d3d;
        }
        .victim-found-marker {
          position: absolute; z-index: 12;
          color: var(--accent-amber);
          filter: drop-shadow(0 0 5px var(--accent-amber));
        }
        .dot.victim-hidden { background: rgba(255,179,0,0.4); }
        .dot.victim-found-dot { background: var(--accent-amber); box-shadow: 0 0 4px var(--accent-amber); }

        /* ── Compact victim inline control ── */
        .victim-inline {
          display: flex; flex-direction: column; align-items: center; gap: 2px;
        }
        .victim-inline.locked { opacity: 0.35; pointer-events: none; }
        .victim-inline-label {
          font-family: 'Orbitron', sans-serif; font-size: 0.55rem;
          letter-spacing: 0.12em; color: var(--accent-amber); opacity: 0.7;
        }
        .victim-inline-controls { display: flex; align-items: center; gap: 6px; }
        .vic-adj {
          width: 22px; height: 22px; border-radius: 5px;
          border: 1px solid rgba(255,179,0,0.45);
          background: rgba(255,179,0,0.08);
          color: var(--accent-amber); font-size: 1rem; line-height: 1;
          cursor: pointer; display: flex; align-items: center; justify-content: center;
          transition: background 0.12s;
        }
        .vic-adj:hover:not(:disabled) { background: rgba(255,179,0,0.22); }
        .vic-adj:disabled { opacity: 0.35; cursor: default; }
        .vic-count {
          font-size: 1.1rem; font-weight: bold;
          color: var(--accent-amber); min-width: 26px; text-align: center;
        }
        .reset-btn { display: flex; align-items: center; gap: 5px; }
        .header-divider {
          width: 1px; height: 28px;
          background: rgba(255,255,255,0.08); margin: 0 2px;
        }
        .stepper-btn {
          width: 20px; height: 20px; border-radius: 3px;
          border: 1px solid rgba(255,179,0,0.4);
          background: rgba(255,179,0,0.08);
          color: var(--accent-amber); font-size: 1rem; line-height: 1;
          cursor: pointer; display: flex; align-items: center; justify-content: center;
          transition: background 0.15s;
        }
        .stepper-btn:hover { background: rgba(255,179,0,0.2); }
        .base-icon { color: var(--accent-cyan); opacity: 0.5; }
        .toggle-3d { margin-left: 1rem; margin-right: 15px; border-color: rgba(255,255,255,0.2); }
        .toggle-3d.active { background: rgba(0,243,255,0.15); border-color: var(--accent-cyan); color: var(--accent-cyan); box-shadow: 0 0 10px rgba(0,243,255,0.3); }

        .log-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 40px 0; color: var(--text-muted); opacity: 0.35; font-size: 0.8rem; font-family: 'Orbitron', sans-serif; }

        .flex-row { display: flex; }
        .gap-2 { gap: 0.5rem; }
        .full-w { width: 100%; }
        .mt-4 { margin-top: 1rem; }
        .header-actions { display: flex; align-items: center; gap: 0.5rem; }

        .conn-badge {
          display: flex;
          align-items: center;
          gap: 5px;
          font-family: 'Orbitron', sans-serif;
          font-size: 0.68rem;
          padding: 4px 10px;
          border-radius: 999px;
          border: 1px solid;
          letter-spacing: 0.05em;
        }
        .conn-badge.connected { color: var(--accent-success); border-color: var(--accent-success); background: rgba(0, 255, 136, 0.08); box-shadow: 0 0 8px rgba(0, 255, 136, 0.2); }
        .conn-badge.disconnected { color: #ff3d3d; border-color: #ff3d3d; background: rgba(255, 61, 61, 0.08); animation: pulse 1.5s infinite; }

        @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; } 100% { opacity: 0.4; } }
        .loading-container { height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; font-family: 'Orbitron'; font-size: 1.2rem; color: var(--accent-cyan); }
        .animate-pulse { animation: pulse 1s infinite; }
        .text-cyan { color: var(--accent-cyan); }
        .text-muted { color: var(--text-muted); }
        .text-success { color: var(--accent-success); }
        .text-amber { color: var(--accent-amber); }
        .text-xs { font-size: 0.75rem; }
        .mb-2 { margin-bottom: 0.5rem; }
        .mb-3 { margin-bottom: 0.75rem; }
        .mb-4 { margin-bottom: 1rem; }
        .font-bold { font-weight: bold; }
        .text-sm { font-size: 0.875rem; }
        .items-center { align-items: center; }
        .opacity-60 { opacity: 0.6; }
        .opacity-70 { opacity: 0.7; }
        .italic { font-style: italic; }
        .panel-header { display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1rem; font-size: 0.8rem; font-family: 'Orbitron'; }
        .drone-list {}

        /* Victim Popup Styles — HUD Toast Mode */
        .victim-popup-overlay {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          background: transparent;
          display: flex; align-items: flex-end; justify-content: flex-end;
          z-index: 1000;
          pointer-events: none;
          padding: 2rem;
        }
        /* Separate overlay for assumptions modal — needs pointer-events so clicks register */
        .assumptions-overlay {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0, 0, 0, 0.65);
          backdrop-filter: blur(4px);
          display: flex; align-items: center; justify-content: center;
          z-index: 1100;
          pointer-events: auto;
        }
        .victim-popup {
          width: 420px; padding: 0; 
          background: rgba(10, 10, 18, 0.95);
          backdrop-filter: blur(16px);
          border: 1px solid rgba(255, 179, 0, 0.6);
          border-radius: 12px;
          overflow: hidden; 
          box-shadow: 0 20px 50px rgba(0, 0, 0, 0.8), 0 0 20px rgba(255, 179, 0, 0.15);
          pointer-events: auto;
        }
        .popup-header {
          padding: 1.25rem; background: rgba(255, 179, 0, 0.15);
          border-bottom: 1px solid rgba(255, 179, 0, 0.25);
          display: flex; justify-content: space-between; align-items: center;
        }
        .popup-header h2 { margin: 0; font-size: 1.1rem; color: var(--accent-amber); font-family: 'Orbitron'; letter-spacing: 0.05em; }
        .popup-drone-id { padding: 4px 10px; background: var(--accent-amber); color: black; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }
        
        .popup-body { padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem; }
        .segment-label {
          font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase;
          letter-spacing: 0.12em; margin-bottom: 0.25rem; font-family: 'Orbitron';
        }
        .victim-report {
          font-style: italic; color: #ffe8b5; font-size: 1rem; line-height: 1.5;
          padding: 1rem; background: rgba(255, 255, 255, 0.03); border-radius: 6px;
          border: 1px solid rgba(255, 255, 255, 0.05);
        }
        
        .comms-interface { margin-top: 0.25rem; }
        .comms-hint { color: var(--text-muted); font-size: 0.8rem; text-align: center; line-height: 1.4; }
        .comms-dispatch-hint { color: var(--accent-cyan); font-size: 0.7rem; opacity: 0.7; text-align: center; letter-spacing: 0.03em; }
        
        .voice-interface { display: flex; flex-direction: column; gap: 0.75rem; }
        .voice-status { display: flex; justify-content: space-between; align-items: center; font-size: 0.7rem; font-weight: bold; }
        .recording-dot { width: 8px; height: 8px; background: #ff3d3d; border-radius: 50%; animation: pulse 1s infinite; }
        .transcription-area {
          min-height: 60px; padding: 0.85rem; background: rgba(0, 0, 0, 0.4);
          border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 6px;
          color: var(--accent-cyan); font-size: 0.85rem; line-height: 1.4;
          box-shadow: inset 0 2px 4px rgba(0,0,0,0.5);
        }
        .reset-voice { background: none; border: none; color: var(--text-muted); font-size: 0.65rem; cursor: pointer; text-decoration: underline; }
        .speech-error { color: #ff3d3d; font-size: 0.75rem; padding: 8px; background: rgba(255, 61, 61, 0.1); border-radius: 4px; }
        
        .flex-row { display: flex; }
        .gap-2 { gap: 0.5rem; }
        .full-w { width: 100%; }
        .mt-4 { margin-top: 1rem; }

        /* ── Info button ── */
        .cyber-button.info-btn {
          background: rgba(165, 243, 252, 0.08);
          border-color: rgba(165, 243, 252, 0.35);
          color: #a5f3fc;
          display: flex; align-items: center; gap: 6px;
        }
        .cyber-button.info-btn:hover {
          background: rgba(165, 243, 252, 0.16);
          border-color: #a5f3fc;
        }

        /* ── Assumptions Modal ── */
        .assumptions-modal {
          width: min(860px, 95vw);
          max-height: 85vh;
          display: flex;
          flex-direction: column;
          border-radius: 12px;
          border: 1px solid rgba(165, 243, 252, 0.25);
          overflow: hidden;
        }
        .assumptions-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1.2rem 1.5rem;
          border-bottom: 1px solid rgba(165, 243, 252, 0.12);
          flex-shrink: 0;
        }
        .close-btn {
          background: none; border: 1px solid rgba(255,255,255,0.15);
          border-radius: 6px; color: var(--text-muted);
          width: 32px; height: 32px;
          display: flex; align-items: center; justify-content: center;
          cursor: pointer;
        }
        .close-btn:hover { border-color: rgba(255,255,255,0.4); color: #fff; }
        .assumptions-body {
          overflow-y: auto;
          padding: 1.25rem 1.5rem;
          display: flex;
          flex-direction: column;
          gap: 1.5rem;
        }
        .assump-section-title {
          font-family: 'Orbitron', sans-serif;
          font-size: 0.72rem;
          color: #a5f3fc;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          margin-bottom: 0.75rem;
          padding-bottom: 0.4rem;
          border-bottom: 1px solid rgba(165, 243, 252, 0.1);
        }
        .assump-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.8rem;
        }
        .assump-table th {
          text-align: left;
          padding: 6px 10px;
          font-size: 0.68rem;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.06em;
          border-bottom: 1px solid rgba(255,255,255,0.08);
        }
        .assump-table td {
          padding: 8px 10px;
          border-bottom: 1px solid rgba(255,255,255,0.04);
          color: var(--text-primary);
          vertical-align: middle;
        }
        .assump-table tr:last-child td { border-bottom: none; }
        .assump-table tr:hover td { background: rgba(255,255,255,0.03); }
        .terrain-badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 0.72rem;
          font-family: 'Orbitron', sans-serif;
          letter-spacing: 0.06em;
        }
        .terrain-badge.city { background: rgba(138,138,122,0.35); color: #d0d0b8; border: 1px solid rgba(180,180,160,0.4); }
        .terrain-badge.forest { background: rgba(42,92,53,0.45); color: #7dce8a; border: 1px solid rgba(60,140,70,0.45); }
        .terrain-badge.flat { background: rgba(75,107,79,0.35); color: #a0c8a4; border: 1px solid rgba(100,150,100,0.35); }
        .terrain-badge.lake { background: rgba(53,95,139,0.45); color: #7ab8e8; border: 1px solid rgba(80,140,200,0.45); }
        .pri-badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 0.72rem;
          font-family: 'Orbitron', sans-serif;
        }
        .pri-badge.high { background: rgba(255,61,61,0.18); color: #ff9090; border: 1px solid rgba(255,61,61,0.4); }
        .pri-badge.medium { background: rgba(255,179,0,0.18); color: #ffcc66; border: 1px solid rgba(255,179,0,0.4); }
        .pri-badge.low { background: rgba(100,100,100,0.2); color: #aaa; border: 1px solid rgba(150,150,150,0.3); }
        .swatch {
          width: 20px; height: 20px;
          border-radius: 4px;
          border: 1px solid rgba(255,255,255,0.15);
        }
        .assump-kv-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 4px 16px;
        }
        .kv-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 0.8rem;
          padding: 6px 10px;
          border-radius: 4px;
          background: rgba(255,255,255,0.02);
          border: 1px solid rgba(255,255,255,0.05);
        }
        .kv-row span:first-child { color: var(--text-muted); }
        .kv-val { font-family: 'Courier New', monospace; font-size: 0.78rem; color: #dff9ff; }
        .highlight { color: #ffd700 !important; font-weight: bold; }
        .warn-text { color: #ffb300 !important; }
        .ok { color: var(--accent-success) !important; }
        .err { color: var(--accent-red, #ff3d3d) !important; }
        .muted { color: var(--text-muted) !important; opacity: 0.6; }

        /* ── Mission Complete Celebration ── */
        .celebration-canvas {
          position: fixed; inset: 0; width: 100vw; height: 100vh;
          pointer-events: none; z-index: 9998;
        }
        .mission-complete-overlay {
          position: fixed; inset: 0; z-index: 9999;
          display: flex; align-items: center; justify-content: center;
          background: rgba(0, 0, 0, 0.55); backdrop-filter: blur(4px);
        }
        .mission-complete-card {
          position: relative; overflow: hidden;
          background: linear-gradient(145deg, rgba(10,20,35,0.98), rgba(5,15,25,0.98));
          border: 1px solid rgba(0, 255, 136, 0.35);
          border-radius: 16px; padding: 2.5rem 3rem;
          text-align: center; min-width: 380px;
          box-shadow: 0 0 60px rgba(0,255,136,0.15), 0 0 120px rgba(0,243,255,0.08);
        }
        .mc-glow-ring {
          position: absolute; inset: -1px; border-radius: 16px;
          background: transparent;
          box-shadow: inset 0 0 30px rgba(0,255,136,0.08);
          pointer-events: none;
          animation: mc-ring-pulse 2s ease-in-out infinite;
        }
        @keyframes mc-ring-pulse {
          0%, 100% { box-shadow: inset 0 0 30px rgba(0,255,136,0.08); }
          50%       { box-shadow: inset 0 0 50px rgba(0,255,136,0.18); }
        }
        .mc-icon {
          color: #00ff88; margin-bottom: 1rem;
          filter: drop-shadow(0 0 12px rgba(0,255,136,0.6));
          animation: mc-icon-pop 0.5s cubic-bezier(0.34,1.56,0.64,1) both;
        }
        @keyframes mc-icon-pop {
          from { transform: scale(0); opacity: 0; }
          to   { transform: scale(1); opacity: 1; }
        }
        .mc-title {
          font-family: 'Orbitron', sans-serif; font-size: 1.35rem;
          font-weight: 900; letter-spacing: 0.12em;
          color: #00ff88; margin: 0 0 0.4rem;
          text-shadow: 0 0 20px rgba(0,255,136,0.5);
        }
        .mc-subtitle {
          font-family: 'Orbitron', sans-serif; font-size: 0.7rem;
          letter-spacing: 0.18em; color: var(--text-muted); margin: 0 0 1.75rem;
        }
        .mc-stats {
          display: flex; align-items: center; justify-content: center;
          gap: 0; margin-bottom: 1.75rem;
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
          border-radius: 10px; padding: 1rem 0.5rem;
        }
        .mc-stat { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; }
        .mc-stat-value {
          font-family: 'Orbitron', sans-serif; font-size: 1.3rem; font-weight: 700;
          color: var(--accent-cyan);
        }
        .mc-stat-label {
          font-family: 'Orbitron', sans-serif; font-size: 0.55rem;
          letter-spacing: 0.1em; color: var(--text-muted);
        }
        .mc-stat-divider { width: 1px; height: 36px; background: rgba(255,255,255,0.1); flex-shrink: 0; }
        .mc-dismiss { margin-top: 0; width: 100%; }

        /* ── Victim map highlight ── */
        .victim-item { cursor: pointer; transition: outline 0.15s ease; }
        .victim-item.map-highlighted {
          outline: 1px solid var(--accent-cyan);
          box-shadow: 0 0 8px rgba(0,243,255,0.25);
        }
        .grid-cell.victim-pinned {
          outline: 2px solid var(--accent-cyan) !important;
          outline-offset: -2px;
          box-shadow: 0 0 12px rgba(0,243,255,0.6), inset 0 0 8px rgba(0,243,255,0.2) !important;
          animation: ping-cyan 1.2s ease-in-out infinite !important;
          z-index: 10;
        }
        @keyframes ping-cyan {
          0%, 100% { box-shadow: 0 0 10px rgba(0,243,255,0.5), inset 0 0 6px rgba(0,243,255,0.15); }
          50%       { box-shadow: 0 0 22px rgba(0,243,255,0.9), inset 0 0 12px rgba(0,243,255,0.3); }
        }

        /* ── Left Panel Tab Bar ── */
        .left-tab-bar {
          display: flex; border-radius: 8px 8px 0 0; overflow: hidden; flex-shrink: 0;
        }
        .left-tab-btn {
          flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;
          padding: 10px 6px; font-family: 'Orbitron', sans-serif; font-size: 0.65rem;
          letter-spacing: 0.06em; background: transparent; border: none;
          color: var(--text-muted); cursor: pointer; border-bottom: 2px solid transparent;
          transition: all 0.2s ease;
        }
        .left-tab-btn.active { color: var(--accent-cyan); border-bottom-color: var(--accent-cyan); background: rgba(0,243,255,0.06); }
        .left-tab-btn:not(.active):hover { background: rgba(255,255,255,0.04); }
        .tab-count {
          font-size: 0.62rem; background: rgba(255,255,255,0.08); border-radius: 999px;
          padding: 1px 6px; min-width: 18px; text-align: center;
        }
        .tab-count.urgent { background: rgba(255,61,61,0.2); color: var(--accent-red, #ff3d3d); border: 1px solid rgba(255,61,61,0.35); }
        .fleet-controls-bar {
          display: flex; align-items: center; padding: 6px 14px; gap: 8px;
          border-radius: 0; flex-shrink: 0; justify-content: flex-end;
        }

        /* ── Victim List ── */
        .victim-list { display: flex; flex-direction: column; gap: 0.55rem; }
        .victim-list-empty {
          display: flex; flex-direction: column; align-items: center; gap: 10px;
          opacity: 0.35; padding: 2.5rem 1rem; font-family: 'Orbitron', sans-serif; font-size: 0.72rem;
        }
        .victim-item {
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
          border-left: 3px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 9px 10px;
        }
        .victim-item.p1_critical { border-left-color: #ff3d3d; background: rgba(255,61,61,0.06); }
        .victim-item.p2_urgent   { border-left-color: #ffb300; background: rgba(255,179,0,0.05); }
        .victim-item.p3_stable   { border-left-color: #00ff88; background: rgba(0,255,136,0.04); }
        .victim-item.rescued     { opacity: 0.42; filter: grayscale(55%); border-left-color: rgba(255,255,255,0.12) !important; }

        .victim-item-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
        .victim-id { font-family: 'Orbitron', sans-serif; font-size: 0.78rem; font-weight: 700; color: var(--text-primary); }
        .victim-coord { font-size: 0.63rem; opacity: 0.5; margin-left: auto; font-family: 'Courier New', monospace; }

        .triage-badge {
          font-family: 'Orbitron', sans-serif; font-size: 0.53rem; font-weight: 700;
          letter-spacing: 0.05em; padding: 2px 7px; border-radius: 3px; flex-shrink: 0;
        }
        .triage-badge.p1_critical { background: rgba(255,61,61,0.18); color: #ff7070; border: 1px solid rgba(255,61,61,0.4); }
        .triage-badge.p2_urgent   { background: rgba(255,179,0,0.15); color: #ffb300; border: 1px solid rgba(255,179,0,0.4); }
        .triage-badge.p3_stable   { background: rgba(0,255,136,0.12); color: #00ff88; border: 1px solid rgba(0,255,136,0.35); }

        .victim-condition {
          font-family: 'Orbitron', sans-serif; font-size: 0.6rem; letter-spacing: 0.04em;
          color: var(--text-muted); margin-bottom: 3px; text-transform: uppercase;
        }
        .victim-report-text { font-size: 0.7rem; opacity: 0.7; font-style: italic; margin-bottom: 6px; }
        .victim-status-row { display: flex; }
        .victim-chip {
          font-family: 'Orbitron', sans-serif; font-size: 0.56rem; letter-spacing: 0.04em;
          padding: 2px 8px; border-radius: 999px;
        }
        .victim-chip.rescued  { background: rgba(0,255,136,0.1); color: #00ff88; border: 1px solid rgba(0,255,136,0.3); }
        .victim-chip.mobile   { background: rgba(0,243,255,0.1); color: var(--accent-cyan); border: 1px solid rgba(0,243,255,0.3); }
        .victim-chip.awaiting { background: rgba(255,179,0,0.1); color: #ffb300; border: 1px solid rgba(255,179,0,0.3); }

        /* ── Popup Scan Intel Block ── */
        .scan-intel-block {
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
          border-radius: 8px; padding: 10px 14px; margin-bottom: 0;
        }
        .scan-intel-row { display: flex; align-items: center; gap: 8px; margin-bottom: 5px; }
        .scan-intel-label { font-family: 'Orbitron', sans-serif; font-size: 0.58rem; color: var(--text-muted); width: 82px; flex-shrink: 0; letter-spacing: 0.05em; }
        .scan-intel-value { font-family: 'Courier New', monospace; font-size: 0.78rem; color: var(--text-primary); }
        .scan-condition-name { font-size: 0.7rem; opacity: 0.72; text-transform: uppercase; letter-spacing: 0.04em; }
        .scan-intel-report { font-style: italic; font-size: 0.72rem; opacity: 0.62; margin-top: 7px; padding-top: 7px; border-top: 1px solid rgba(255,255,255,0.07); }
      `}</style>
    </div>
  );
}

function StatBox({ icon, label, value, color }: { icon: any, label: string, value: string, color: 'cyan' | 'amber' | 'success' }) {
  const colors = {
    cyan: 'var(--accent-cyan)',
    amber: 'var(--accent-amber)',
    success: 'var(--accent-success)'
  };
  return (
    <div className="stat-box">
      <div className="stat-label">
        <span style={{ color: colors[color] }}>{icon}</span> {label}
      </div>
      <div className="stat-value font-mono" style={{ color: colors[color] }}>{value}</div>
      <style>{`
        .stat-box { display: flex; flex-direction: column; align-items: flex-start; }
        .stat-label { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; display: flex; align-items: center; gap: 4px; }
        .stat-value { font-size: 1.1rem; font-weight: bold; }
      `}</style>
    </div>
  );
}

