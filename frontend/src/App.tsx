import { useState, useEffect, useRef } from 'react';
import { Zap } from 'lucide-react';
import Map3D from './components/Map3D';
import DashboardHeader from './components/DashboardHeader';
import FleetStatus from './components/FleetStatus';
import ReasoningLog from './components/ReasoningLog';
import GridMap from './components/GridMap';
import VictimPopup from './components/VictimPopup';
import './App.css';

// --- Constants ---
const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const GRID_W = 20;
const GRID_H = 15;
const POLL_INTERVAL_MS = 800;
const LOW_BATTERY_PCT = 25;

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
  const [isRecording, setIsRecording] = useState(false);
  const [transcription, setTranscription] = useState("");
  const [speechError, setSpeechError] = useState<string | null>(null);

  const logEndRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);

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
    await fetch(`${API_BASE}/reset?num_victims=${victimCount}`, { method: 'POST' });
    await fetch(`${API_BASE}/run-mission`, { method: 'POST' });
    setTimeout(() => setIsDeploying(false), 2000);
  };

  const stopMission = async () => {
    await fetch(`${API_BASE}/stop-mission`, { method: 'POST' });
  };

  const resetMission = async () => {
    await fetch(`${API_BASE}/reset`, { method: 'POST' });
    setActiveDroneId(null);
  };

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
        recognition.onstart = () => setIsRecording(true);
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
        recognition.onend = () => setIsRecording(false);
        recognition.start();
      } catch (_err) {
        setSpeechError("Failed to initialize speech recognition.");
        setIsRecording(false);
      }
    } else {
      setSpeechError("Web Speech API not supported.");
      setIsRecording(true);
      setTimeout(() => {
        setTranscription("Simulated: My friend is at grid 10");
        setOperatorMsg("My friend is at grid 10");
        setIsRecording(false);
      }, 3000);
    }
  };

  const respondToVictim = (droneId: string) => {
    fetch(`${API_BASE}/victim-response?drone_id=${droneId}&operator_message=${encodeURIComponent(operatorMsg)}`, { method: 'POST' });
    setOperatorMsg("");
    setTranscription("");
  };

  if (isLoading) return <div className="loading-container"><Zap className="animate-pulse" /> INITIALIZING SENTINEL...</div>;

  const { stats, drones, zone, log, base_station } = state || {};
  const baseX = base_station?.x ?? 0;
  const baseY = base_station?.y ?? 0;
  const waitingDrone = drones?.find((d: any) => d.is_waiting_response);

  return (
    <div className="app-container">
      <DashboardHeader
        connectionStatus={connectionStatus}
        stats={stats}
        victimCount={victimCount}
        setVictimCount={setVictimCount}
        isDeploying={isDeploying}
        is3DView={is3DView}
        setIs3DView={setIs3DView}
        runMission={runMission}
        stopMission={stopMission}
        resetMission={resetMission}
      />

      <main className="main-content">
        <FleetStatus
          drones={drones}
          activeDroneId={activeDroneId}
          setActiveDroneId={setActiveDroneId}
          showRtbOnly={showRtbOnly}
          setShowRtbOnly={setShowRtbOnly}
          lowBatteryPct={LOW_BATTERY_PCT}
        />

        <GridMap
          is3DView={is3DView}
          zone={zone}
          drones={drones || []}
          stats={stats}
          baseX={baseX}
          baseY={baseY}
          showRtbOnly={showRtbOnly}
          gridW={GRID_W}
          gridH={GRID_H}
          Map3D={Map3D}
        />

        <ReasoningLog
          log={log}
          logFilter={logFilter}
          setLogFilter={setLogFilter}
          logEndRef={logEndRef}
        />
      </main>

      <VictimPopup
        waitingDrone={waitingDrone}
        isRecording={isRecording}
        transcription={transcription}
        speechError={speechError}
        toggleVoiceCapture={toggleVoiceCapture}
        respondToVictim={respondToVictim}
        setTranscription={setTranscription}
        setOperatorMsg={setOperatorMsg}
      />
    </div>
  );
}