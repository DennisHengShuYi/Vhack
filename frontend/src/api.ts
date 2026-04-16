const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

export interface MissionSummary {
  id: string;
  started_at: string;
  ended_at: string;
  status: "COMPLETE" | "PARTIAL";
  total_victims: number;
  victims_found: number;
  victims_rescued: number;
  avg_time_to_find_s: number;
}

export interface MissionDetail extends MissionSummary {
  coverage_pct: number;
  detection_rate_pct: number;
  false_positives: number;
  llm_ticks: number;
  auto_ticks: number;
  fallback_ticks: number;
  contract_violations: number;
  zone_times: Record<string, { drone: string; duration_s: number }>;
  per_drone: Record<string, {
    drone_id: string; battery_used: number; cells_moved: number;
    scans_performed: number; charges_count: number; idle_ticks: number;
    utilisation_pct: number;
  }>;
  survivors: Array<{
    tick: number; priority: string; condition: string;
    drone: string; rescue_s: number;
  }>;
}

export interface ReplayTick {
  tick: number;
  coverage_pct: number;
  drones: Record<string, { x: number; y: number; battery: number; status: string }>;
  zones: Record<string, string>;
  events: string[];
  decision_type: string;
}

export async function fetchMissions(): Promise<MissionSummary[]> {
  const r = await fetch(`${API_BASE}/missions`);
  if (!r.ok) throw new Error("Failed to fetch missions");
  return r.json();
}

export async function fetchMissionDetail(id: string): Promise<MissionDetail> {
  const r = await fetch(`${API_BASE}/missions/${id}`);
  if (!r.ok) throw new Error("Failed to fetch mission detail");
  return r.json();
}

export async function fetchReplay(id: string): Promise<ReplayTick[]> {
  const r = await fetch(`${API_BASE}/missions/${id}/replay`);
  if (!r.ok) throw new Error("Failed to fetch replay");
  return r.json();
}

export function formatDuration(startedAt: string, endedAt: string): string {
  const s = Math.round((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}
