"""
MCP Tool Definitions — registered with the FastMCP server.

All tools are registered via register_tools(mcp), called from server.py.
This separation keeps server.py focused on infrastructure (tick loop, REST API)
while this file owns the agent-facing tool surface.

Tools (12 total):
  Core query:
    list_drones()              — active drone IDs
    get_status(drone_id)       — per-drone telemetry
    get_grid_state()           — all 12 zones with scan %, priority, assignment
    get_swarm_status()         — fleet-level overview (fast situational check)
    get_thermal_scan(drone_id) — raw thermal matrix + CNN confidence

  Planning:
    get_idle_drones()                  — full options menu, main planning input
    get_mission_intel()                — comprehensive situational brief
    get_survivor_intel()               — known survivors + triage + rescue status

  Action:
    assign_scan_zone(drone_id, zone_id) — dispatch drone to zone
    return_to_base(drone_id)            — force RTB
    reassign_drone(drone_id, zone_id)   — emergency zone swap (active drone)
    prioritize_zone(zone_id, priority)  — dynamic priority override
"""
import sys
import shared
from simulation import ZoneStatus, chebyshev, BATTERY_RETURN_RESERVE

# Stale sighting advisory: only surface to agent after this many ticks without re-scan
STALE_SIGHTING_MIN_AGE_TICKS = 10


def register_tools(mcp):
    """Register all MCP tools on the provided FastMCP instance."""

    # ── Core Query Tools ──────────────────────────────────────────────────────

    @mcp.tool()
    def list_drones() -> str:
        """Returns all active drone IDs in the swarm."""
        sim = shared.sim
        ids = list(sim.drones.keys())
        return f"Active drones: {', '.join(ids)}"

    @mcp.tool()
    def get_status(drone_id: str) -> str:
        """
        Returns detailed telemetry for a specific drone.
        Args:
            drone_id: The ID of the drone (e.g. 'ALPHA-1').
        """
        sim = shared.sim
        drone = sim.drones.get(drone_id)
        if not drone:
            return f"Error: Drone {drone_id} not found."
        return (
            f"[{drone_id}] Battery: {drone.battery:.1f}% | "
            f"Pos: ({drone.x},{drone.y}) | Status: {drone.status_label} | "
            f"Charging: {drone.is_charging} | RTB: {drone.returning_to_base} | "
            f"Zone: {drone.assigned_zone_id or 'None'} | "
            f"PathQueue: {len(drone.path_queue)} steps remaining"
        )

    @mcp.tool()
    def get_grid_state() -> str:
        """
        Returns the state of all 12 search zones: status, score, assignment, and scan progress.
        Use this to identify UNSCANNED zones available for assignment.
        """
        sim = shared.sim
        lines = ["=== ZONE MAP (12 zones, 5×5 each) ==="]
        for zid, z in sim.zone.zones.items():
            total = (z.ex - z.sx + 1) * (z.ey - z.sy + 1)
            scanned = sum(
                1 for cy in range(z.sy, z.ey + 1)
                for cx in range(z.sx, z.ex + 1)
                if sim.zone.scanned_cells[cy][cx]
            )
            pct = int(100 * scanned / total) if total > 0 else 0
            zone_score = sum(
                sim.probability_map[cy][cx]
                for cy in range(z.sy, z.ey + 1)
                for cx in range(z.sx, z.ex + 1)
                if not sim.is_inaccessible(cx, cy)
            )
            assigned = f" → {z.assigned_to}" if z.assigned_to else ""
            has_residual = " [has residual path]" if z.residual_path else ""
            lines.append(
                f"  {zid} ({z.sx},{z.sy})-({z.ex},{z.ey}): {z.status.value} | "
                f"Score={zone_score:.2f} | Scanned={pct}%{assigned}{has_residual}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def get_swarm_status() -> str:
        """
        Returns a fleet-level overview: active/idle/charging drone counts,
        average battery, and grid coverage. Use for quick situational awareness.
        """
        sim = shared.sim
        drones = list(sim.drones.values())

        active  = [d for d in drones if d.status == "ON_MISSION"]
        idle    = [d for d in drones if d.status == "IDLE" and not d.is_charging and not d.returning_to_base]
        charging = [d for d in drones if d.is_charging]
        rtb     = [d for d in drones if d.returning_to_base]
        standby = [d for d in drones if d.is_waiting_response]

        avg_battery = sum(d.battery for d in drones) / len(drones) if drones else 0
        total_cells = sim.zone.width * sim.zone.height
        scanned = sum(
            sim.zone.scanned_cells[y][x]
            for y in range(sim.zone.height) for x in range(sim.zone.width)
        )
        coverage_pct = int(100 * scanned / total_cells) if total_cells > 0 else 0

        lines = [
            "=== SWARM STATUS OVERVIEW ===",
            f"Fleet: {len(active)} active | {len(idle)} idle | {len(charging)} charging | "
            f"{len(rtb)} RTB | {len(standby)} on standby",
            f"Avg Battery: {avg_battery:.1f}% | Grid Coverage: {coverage_pct}%",
            f"Mission: {'ACTIVE' if sim.mission_active else 'INACTIVE'} | "
            f"Survivors: {sim.total_victims_found} found / {sim.total_rescued} rescued",
        ]
        if active:
            lines.append("Active Missions: " + ", ".join(
                f"{d.id}→{d.assigned_zone_id}({d.battery:.0f}%)" for d in active
            ))
        if idle:
            lines.append("Idle Drones: " + ", ".join(f"{d.id}({d.battery:.0f}%)" for d in idle))
        if charging:
            lines.append("Charging: " + ", ".join(f"{d.id}({d.battery:.0f}%)" for d in charging))
        return "\n".join(lines)

    @mcp.tool()
    def get_thermal_scan(drone_id: str) -> str:
        """
        Returns the latest thermal sensor data from a specific drone.
        Use after a zone scan returns a thermal anomaly to assess detection confidence.
        Args:
            drone_id: The drone whose thermal data to retrieve (e.g. 'ALPHA-2').
        """
        sim = shared.sim
        drone = sim.drones.get(drone_id)
        if not drone:
            return f"Error: Drone {drone_id} not found."
        if not drone.last_thermal_scan and not drone.last_thermal_matrix:
            return f"{drone_id} has no thermal scan data yet."

        lines = [f"=== THERMAL DATA — {drone_id} @ ({drone.x},{drone.y}) ==="]
        if drone.last_thermal_scan:
            ts = drone.last_thermal_scan
            lines.append(
                f"Last Detection: ({ts['x']},{ts['y']}) | "
                f"Confidence: {ts['confidence']}% | Triage: {ts.get('triage','N/A')}"
            )
            lines.append(f"Report: {ts.get('report','N/A')}")
        if drone.last_thermal_matrix:
            matrix = drone.last_thermal_matrix
            flat = [v for row in matrix for v in row]
            max_heat = max(flat)
            mean_heat = sum(flat) / len(flat)
            contrast = max_heat - mean_heat
            lines.append(
                f"Thermal Matrix: max={max_heat}° avg={mean_heat:.1f}° contrast={contrast:.1f}°"
            )
            detect = "POSITIVE DETECTION" if max_heat >= 78 and contrast >= 28 else "no match"
            lines.append(f"CNN Result: {detect}")
        return "\n".join(lines)

    # ── Planning Tools ────────────────────────────────────────────────────────

    @mcp.tool()
    def get_idle_drones() -> str:
        """
        Returns a 'Mission Options Menu' for all idle drones.
        The agent evaluates these options based on battery, priority, and risk,
        then executes the chosen assignments using assign_scan_zone() or return_to_base().
        Also surfaces RE-SCAN advisories for stale sightings when mobile survivors
        have moved 10+ ticks after last detection.
        """
        sim = shared.sim

        idle_drones = [
            (d_id, d) for d_id, d in sim.drones.items()
            if (d.is_active                    # only connected drones
                and d.target_x is None
                and not d.path_queue
                and not d.returning_to_base
                and not d.is_charging
                and not d.is_waiting_response)
        ]

        if not idle_drones:
            return "NO_IDLE_DRONES: No drones currently need orders."

        available = [z for z in sim.get_available_zones()
                     if z["zone_id"] not in sim.reserved_zones]
        survivors_found = sim.total_victims_found

        if not available:
            # Before declaring MISSION COMPLETE, verify actual cell coverage.
            # Zones can be falsely COMPLETE (race) or stuck IN_PROGRESS (no drone assigned).
            # Reset any such zones so the agent can reassign them.
            recovered = False
            for zid, z in sim.zone.zones.items():
                if z.status == ZoneStatus.COMPLETE:
                    has_unscanned = any(
                        not sim.zone.scanned_cells[cy][cx]
                        for cy in range(z.sy, z.ey + 1)
                        for cx in range(z.sx, z.ex + 1)
                        if not sim.is_inaccessible(cx, cy)
                    )
                    if has_unscanned:
                        z.status = ZoneStatus.UNSCANNED
                        z.assigned_to = None
                        recovered = True
                elif z.status == ZoneStatus.IN_PROGRESS:
                    # Release zones claimed but with no active drone scanning them
                    if not any(d.assigned_zone_id == zid for d in sim.drones.values()):
                        z.status = ZoneStatus.UNSCANNED
                        z.assigned_to = None
                        recovered = True
            if recovered:
                available = [z for z in sim.get_available_zones()
                             if z["zone_id"] not in sim.reserved_zones]

        if not available:
            # Check if any zones are still actively being scanned
            still_scanning = [
                f"{z.id}→{z.assigned_to}"
                for z in sim.zone.zones.values()
                if z.status == ZoneStatus.IN_PROGRESS
            ]
            drone_names = ", ".join(d_id for d_id, _ in idle_drones)
            if still_scanning:
                # Not done yet — other drones are still scanning. Idle drones should wait.
                return (f"NO_ZONES_AVAILABLE: Zones still being scanned: {', '.join(still_scanning)}. "
                        f"Idle drones [{drone_names}] — send them return_to_base() to conserve battery "
                        f"and re-assign when zones free up.")
            return (f"MISSION COMPLETE: Grid fully searched. "
                    f"Found {survivors_found} survivors. "
                    f"Drones available for recall: {drone_names}")

        base_x, base_y = sim.base_station
        report = [f"--- MISSION OPTIONS MENU (Found: {survivors_found}) ---"]

        # Mission-start strategic briefing header
        all_fresh = all(z.status == ZoneStatus.UNSCANNED for z in sim.zone.zones.values())
        if all_fresh:
            report.insert(0, (
                "=== MISSION START — STRATEGIC BRIEFING REQUIRED ===\n"
                "Before assigning any drones, write a Mission Plan in the log:\n"
                "  1. Which zones have the highest Score (expected survivors) and why\n"
                "  2. Your intended drone-to-zone mapping for the first wave\n"
                "  3. Any zones you will defer (low score or battery risk)\n"
                "Then proceed with assign_scan_zone() calls for all idle drones."
            ))

        in_progress = [
            f"{z.id}→{z.assigned_to}"
            for z in sim.zone.zones.values()
            if z.status.value == "in_progress" and z.assigned_to
        ]
        if in_progress:
            report.append(f"IN_PROGRESS: {', '.join(in_progress)} (do NOT duplicate these)")

        # Mission status header
        total_zones = len(sim.zone.zones)
        complete_zones = sum(1 for z in sim.zone.zones.values() if z.status == ZoneStatus.COMPLETE)
        total_grid = sim.zone.width * sim.zone.height
        scanned_grid = sum(
            sim.zone.scanned_cells[y][x]
            for y in range(sim.zone.height) for x in range(sim.zone.width)
        )
        coverage_pct = int(100 * scanned_grid / total_grid) if total_grid > 0 else 0
        s_found = sum(1 for s in sim.zone.survivors if s.get("found") or s.get("rescued"))
        report.append(
            f"Mission Status: {complete_zones}/{total_zones} zones done, "
            f"{coverage_pct}% grid covered, {s_found}/{len(sim.zone.survivors)} survivors found"
        )

        # ── Stale sightings: high-priority re-scan options ────────────────
        stale = getattr(sim, 'stale_sightings', [])
        fresh_stale = [
            st for st in stale
            if (sim.tick_count - st.get("stale_since_tick", 0)) >= STALE_SIGHTING_MIN_AGE_TICKS
        ]
        if fresh_stale:
            report.append(f"\n⚠️  STALE SIGHTINGS — mobile survivors moved from last known position:")
            for st in fresh_stale:
                age = sim.tick_count - st.get("stale_since_tick", sim.tick_count)
                report.append(
                    f"  RE-SCAN ({st['x']},{st['y']}) — victim {st['victim_id']} last seen "
                    f"{age} ticks ago. "
                    f"Identify the zone containing this cell and call assign_scan_zone() for it. "
                    f"PRIORITY: HIGH — known survivor may be nearby."
                )

        # Determine which zone rows already have an active drone (to guide spread)
        # Grid has 3 rows of zones (row 0: y=0-4, row 1: y=5-9, row 2: y=10-14)
        zone_height = sim.zone.height
        row_size = zone_height // 3  # typically 5
        active_rows: set = set()
        for _, z_obj in sim.zone.zones.items():
            if z_obj.status == ZoneStatus.IN_PROGRESS:
                active_rows.add(z_obj.sy // row_size)

        for d_id, drone in idle_drones:
            report.append(f"\n[DRONE: {d_id}] Battery: {drone.battery:.1f}% @ ({drone.x},{drone.y})")
            options = []
            for z in available:
                transit = min(
                    chebyshev(drone.x, drone.y, z["sx"], z["sy"]),
                    chebyshev(drone.x, drone.y, z["ex"], z["sy"]),
                    chebyshev(drone.x, drone.y, z["sx"], z["ey"]),
                    chebyshev(drone.x, drone.y, z["ex"], z["ey"]),
                )
                return_cost = max(
                    chebyshev(z["ex"], z["ey"], base_x, base_y),
                    chebyshev(z["sx"], z["ey"], base_x, base_y),
                )

                z_obj = sim.zone.zones[z["zone_id"]]
                terrain_counts: dict = {}
                # Terrain-weighted scan cost over UNSCANNED cells only.
                # Cells already scanned opportunistically don't need revisiting, so
                # partial/residual zones cost proportionally less — a drone with moderate
                # battery can still be assigned to an 80%-scanned zone.
                scan_cost_actual = 0.0
                for cy in range(z_obj.sy, z_obj.ey + 1):
                    for cx in range(z_obj.sx, z_obj.ex + 1):
                        t = sim.zone.terrain_types[cy][cx]
                        terrain_counts[t] = terrain_counts.get(t, 0) + 1
                        if not sim.zone.scanned_cells[cy][cx] and not sim.is_inaccessible(cx, cy):
                            scan_cost_actual += 1.5 if t == 'forest' else 1.0

                terrain_str = " ".join(
                    f"{k.capitalize()}:{v}" for k, v in sorted(terrain_counts.items()) if v > 0
                )
                total_needed = transit + scan_cost_actual + return_cost

                total_cells = (z_obj.ey - z_obj.sy + 1) * (z_obj.ex - z_obj.sx + 1)
                scanned_count = sum(
                    1 for cy in range(z_obj.sy, z_obj.ey + 1)
                    for cx in range(z_obj.sx, z_obj.ex + 1)
                    if sim.zone.scanned_cells[cy][cx]
                )
                scan_pct = int(100 * scanned_count / total_cells) if total_cells > 0 else 0
                zone_row = z_obj.sy // row_size
                row_gap = zone_row not in active_rows  # True = this row has no active drone

                options.append({
                    "zone_id": z["zone_id"],
                    "transit": transit,
                    "scan": scan_cost_actual,
                    "return": return_cost,
                    "total": total_needed,
                    "zone_score": z["zone_score"],
                    "terrain": terrain_str,
                    "scan_pct": scan_pct,
                    "zone_row": zone_row,
                    "row_gap": row_gap,
                })

            options.sort(key=lambda x: (
                # 1st: highest probability score first
                -x["zone_score"],
                # 2nd: gap rows as tiebreaker within similar scores
                0 if x["row_gap"] else 1,
                # 3rd: nearest first
                x["transit"]
            ))
            valid_options = [o for o in options if o["total"] + BATTERY_RETURN_RESERVE <= drone.battery][:3]

            if not valid_options:
                report.append("  * REC: return_to_base() | Battery too low for any zone.")
            else:
                for i, opt in enumerate(valid_options):
                    remaining = drone.battery - opt["total"]
                    risk = "LOW" if remaining > 20 else ("MEDIUM" if remaining > 10 else "HIGH")
                    has_residual = bool(sim.zone.zones[opt['zone_id']].residual_path)
                    partial = " [PARTIAL-resume]" if has_residual else ""
                    gap_tag = " [GAP-ROW: no drone in this sector]" if opt["row_gap"] else ""
                    report.append(
                        f"  Opt {i+1}: assign_scan_zone(\"{d_id}\", \"{opt['zone_id']}\") "
                        f"- Score={opt['zone_score']:.2f}, Transit={opt['transit']}, Cost={opt['total']}, "
                        f"Risk={risk}, Terrain=[{opt['terrain']}], Scanned={opt['scan_pct']}%{partial}{gap_tag}"
                    )

        return "\n".join(report)

    @mcp.tool()
    def get_mission_intel() -> str:
        """
        Returns comprehensive mission intelligence: zone-by-zone scan progress,
        survivor triage summary, and current drone assignments.
        Use for high-level situational awareness before making assignment decisions.
        """
        sim = shared.sim
        lines = ["=== MISSION INTELLIGENCE BRIEF ==="]

        scanned_total = sum(
            sim.zone.scanned_cells[y][x]
            for y in range(sim.zone.height) for x in range(sim.zone.width)
        )
        accessible = sum(
            1 for y in range(sim.zone.height) for x in range(sim.zone.width)
            if not sim.zone.hazard_cells[y][x]
        )
        coverage_pct = int(100 * scanned_total / accessible) if accessible > 0 else 0
        lines.append(f"Grid Coverage: {coverage_pct}% ({scanned_total}/{accessible} accessible cells scanned)")

        lines.append("\nZone Intel (incomplete zones only):")
        for zid, z in sim.zone.zones.items():
            if z.status == ZoneStatus.COMPLETE:
                continue
            total_cells = (z.ey - z.sy + 1) * (z.ex - z.sx + 1)
            scanned_cells = sum(
                1 for cy in range(z.sy, z.ey + 1)
                for cx in range(z.sx, z.ex + 1)
                if sim.zone.scanned_cells[cy][cx]
            )
            remaining = total_cells - scanned_cells
            zone_score = sum(
                sim.probability_map[cy][cx]
                for cy in range(z.sy, z.ey + 1)
                for cx in range(z.sx, z.ex + 1)
                if not sim.is_inaccessible(cx, cy)
            )
            assigned_str = f" [{z.assigned_to}]" if z.assigned_to else ""
            lines.append(
                f"  {zid} (Score:{zone_score:.2f}): {remaining}/{total_cells} cells unscanned | "
                f"{z.status.value}{assigned_str}"
            )

        lines.append(
            f"\nSurvivor Status: {sim.total_victims_found} found / "
            f"{sim.total_rescued} rescued / {len(sim.zone.survivors)} total"
        )
        for s in sim.zone.survivors:
            if s["found"] and not s["rescued"]:
                lines.append(f"  ⚠️ AWAITING RESCUE: {s['id']} at ({s['x']},{s['y']}) — {s['triage_priority']}")

        lines.append("\nCurrent Drone Assignments:")
        for d_id, d in sim.drones.items():
            if d.assigned_zone_id:
                lines.append(
                    f"  {d_id}: scanning {d.assigned_zone_id} | "
                    f"{len(d.path_queue)} steps left | {d.battery:.0f}% battery"
                )
            elif d.returning_to_base:
                lines.append(f"  {d_id}: RTB | {d.battery:.0f}% battery")
            elif d.is_charging:
                lines.append(f"  {d_id}: CHARGING | {d.battery:.0f}%")
            else:
                lines.append(f"  {d_id}: IDLE @ ({d.x},{d.y}) | {d.battery:.0f}%")

        return "\n".join(lines)

    @mcp.tool()
    def get_survivor_intel() -> str:
        """
        Returns all known survivor positions, triage priorities, and rescue status.
        Use this after a zone scan to prioritise rescue operations.
        """
        sim = shared.sim
        survivors = sim.zone.survivors
        if not survivors:
            return "No survivor data available."

        lines = ["=== SURVIVOR INTELLIGENCE REPORT ==="]
        for s in survivors:
            if s["rescued"]:
                status = "RESCUED ✓"
            elif s["found"]:
                status = "FOUND — AWAITING RESCUE ⚠️"
            else:
                status = "NOT YET FOUND"
            can_move = " [CAN MOVE — guide eligible]" if s.get("can_move") and not s["rescued"] else ""
            lines.append(
                f"  {s['id']} @ ({s['x']},{s['y']}) | {s['triage_priority']} | {status}{can_move}"
            )

        p1 = [s for s in survivors if s["triage_priority"] == "P1-CRITICAL" and s["found"] and not s["rescued"]]
        if p1:
            lines.append(f"\n⚠️ CRITICAL: {len(p1)} P1 survivor(s) awaiting rescue — immediate action required!")

        return "\n".join(lines)

    @mcp.tool()
    def get_probability_map() -> str:
        """
        Returns per-zone survivor probability scores based on terrain analysis
        and Bayesian updates from scan results. Higher score = more likely to contain
        undiscovered survivors. Use this to prioritize which zones to assign first.
        """
        sim = shared.sim
        lines = ["=== SURVIVOR PROBABILITY MAP (per zone) ==="]
        zone_probs = []
        for zid, z in sim.zone.zones.items():
            zone_prob = sum(
                sim.probability_map[y][x]
                for y in range(z.sy, z.ey + 1)
                for x in range(z.sx, z.ex + 1)
            )
            unscanned = sum(
                1 for y in range(z.sy, z.ey + 1)
                for x in range(z.sx, z.ex + 1)
                if not sim.zone.scanned_cells[y][x] and not sim.is_inaccessible(x, y)
            )
            zone_probs.append((zid, zone_prob, unscanned, z.status.value))
        zone_probs.sort(key=lambda x: -x[1])
        for zid, prob, unscanned, status in zone_probs:
            lines.append(
                f"  {zid}: score={prob:.3f} | unscanned={unscanned} cells | status={status}"
            )
        return "\n".join(lines)

    # ── Action Tools ──────────────────────────────────────────────────────────

    @mcp.tool()
    def assign_scan_zone(drone_id: str, zone_id: str) -> str:
        """
        Commands a drone to sweep a pre-defined zone by its zone_id.
        Use get_idle_drones() to see available options first.
        Args:
            drone_id: The ID of the drone (e.g. 'ALPHA-1').
            zone_id: The zone ID to assign (e.g. 'Z0', 'Z1', ..., 'Z11').
        """
        sim = shared.sim
        drone = sim.drones.get(drone_id)
        if not drone:
            return f"Error: Drone {drone_id} not found."
        if not drone.is_active:
            return f"Error: {drone_id} is OFFLINE — no heartbeat signal. Cannot assign mission."
        if drone.is_waiting_response:
            return f"Error: {drone_id} is on VICTIM STANDBY. Cannot reassign."
        if drone.is_charging and drone.battery < 90:
            return f"Error: {drone_id} is charging ({drone.battery:.0f}%). Wait until charged."

        zone = sim.zone.zones.get(zone_id)
        if not zone:
            return f"Error: Zone {zone_id} does not exist. Use get_grid_state() to see valid IDs."
        if zone.status != ZoneStatus.UNSCANNED:
            return f"Error: Zone {zone_id} is already {zone.status.value}. Pick a different zone."
        if zone_id in sim.reserved_zones:
            reserved_for = sim.reserved_zones[zone_id]
            return (f"Error: Zone {zone_id} is reserved for {reserved_for} "
                    f"(residual coverage after current job). Choose a different zone.")

        # Pre-check: if all cells already scanned (opportunistic transit), auto-complete and skip
        unscanned_count = sum(
            1 for y in range(zone.sy, zone.ey + 1)
            for x in range(zone.sx, zone.ex + 1)
            if not sim.zone.scanned_cells[y][x] and not sim.is_inaccessible(x, y)
        )
        if unscanned_count == 0:
            zone.status = ZoneStatus.COMPLETE
            return (
                f"Zone {zone_id} already fully covered by opportunistic scan — auto-completed. "
                f"Choose a different zone."
            )

        base_x, base_y = sim.base_station
        # Use nearest corner for transit (same as get_idle_drones) — drones pick closest entry point
        transit_cost = min(
            chebyshev(drone.x, drone.y, zone.sx, zone.sy),
            chebyshev(drone.x, drone.y, zone.ex, zone.sy),
            chebyshev(drone.x, drone.y, zone.sx, zone.ey),
            chebyshev(drone.x, drone.y, zone.ex, zone.ey),
        )
        # Terrain-weighted scan cost over UNSCANNED cells only (mirrors get_idle_drones logic).
        # Partial/residual zones cost proportionally less so drones with moderate battery
        # can still be assigned rather than being sent to RTB unnecessarily.
        scan_cost = sum(
            1.5 if sim.zone.terrain_types[y][x] == 'forest' else 1.0
            for y in range(zone.sy, zone.ey + 1)
            for x in range(zone.sx, zone.ex + 1)
            if not sim.zone.scanned_cells[y][x] and not sim.is_inaccessible(x, y)
        )
        # Use Chebyshev (diagonal movement) for return — consistent with get_idle_drones
        return_cost = max(
            chebyshev(zone.ex, zone.ey, base_x, base_y),
            chebyshev(zone.sx, zone.ey, base_x, base_y),
        )
        total_estimated = transit_cost + scan_cost + return_cost

        if drone.battery < total_estimated + BATTERY_RETURN_RESERVE:
            return (
                f"Error: {drone_id} has {drone.battery:.1f}% battery but zone {zone_id} "
                f"requires ~{total_estimated + BATTERY_RETURN_RESERVE:.0f}% (incl. reserve). REJECTED. "
                f"Pick a closer zone or call return_to_base(\"{drone_id}\")."
            )

        if not sim.claim_zone(zone_id, drone_id):
            return f"Error: Zone {zone_id} was just claimed by another drone. Pick a different zone."

        result = sim.assign_zone(drone_id, zone_id)
        if "error" in result:
            sim.release_zone(zone_id)
            return f"Error: {result['error']}"

        sim.log(f"📡 AGENT DISPATCH: {drone_id} assigned to zone {zone_id}.", "AI", drone_id)
        return f"SUCCESS: {result['message']} (Zone {zone_id} claimed)"

    @mcp.tool()
    def return_to_base(drone_id: str) -> str:
        """Forces a drone to abort its current mission and return to base for recharging."""
        sim = shared.sim
        drone = sim.drones.get(drone_id)
        if not drone:
            return f"Error: Drone {drone_id} not found."
        if not drone.is_active:
            return f"Error: {drone_id} is OFFLINE — cannot issue RTB command."

        base_x, base_y = sim.base_station

        # If drone is already at base and charged, skip redundant RTB
        if (drone.x, drone.y) == (base_x, base_y) and drone.battery >= 90 and not drone.assigned_zone_id:
            return (f"Info: {drone_id} is already at base ({base_x},{base_y}) "
                    f"with {drone.battery:.0f}% battery — no RTB needed. "
                    f"Use assign_scan_zone() to dispatch it.")

        if drone.assigned_zone_id:
            zid = drone.assigned_zone_id
            if drone.path_queue and zid in sim.zone.zones:
                sim.zone.zones[zid].residual_path = list(drone.path_queue)
            sim.release_zone(zid)
            drone.assigned_zone_id = None

        drone.path_queue = sim.compute_path(drone.x, drone.y, base_x, base_y)
        drone.target_x, drone.target_y = base_x, base_y
        drone.returning_to_base = True
        drone.status = "RETURNING"
        drone.status_label = "RTB"
        sim.log(f"🔁 AGENT: {drone_id} recalled to base.", "INFO", drone_id)
        return f"Drone {drone_id} is returning to base ({base_x},{base_y})."

    @mcp.tool()
    def split_scan_zone(drone_a_id: str, drone_b_id: str, zone_id: str) -> str:
        """
        Splits a high-score zone between two drones for parallel scanning.
        Drone A takes the top half, Drone B takes the bottom half.
        Use when a zone has Score > 1.5 and 2+ idle drones are available.
        Args:
            drone_a_id: First drone (e.g. 'ALPHA-1') — scans top half.
            drone_b_id: Second drone (e.g. 'ALPHA-2') — scans bottom half.
            zone_id: The zone to split (e.g. 'Z5').
        """
        sim = shared.sim
        for did in (drone_a_id, drone_b_id):
            drone = sim.drones.get(did)
            if not drone:
                return f"Error: Drone {did} not found."
            if not drone.is_active:
                return f"Error: {did} is OFFLINE."
            if drone.is_waiting_response:
                return f"Error: {did} is on VICTIM STANDBY."
            if drone.is_charging and drone.battery < 90:
                return f"Error: {did} is charging ({drone.battery:.0f}%)."

        zone = sim.zone.zones.get(zone_id)
        if not zone:
            return f"Error: Zone {zone_id} does not exist."
        if zone.status != ZoneStatus.UNSCANNED:
            return f"Error: Zone {zone_id} is already {zone.status.value}."

        if not sim.claim_zone(zone_id, f"{drone_a_id}+{drone_b_id}"):
            return f"Error: Zone {zone_id} was just claimed."

        result = sim.assign_zone_split(drone_a_id, drone_b_id, zone_id)
        if "error" in result:
            sim.release_zone(zone_id)
            return f"Error: {result['error']}"

        sim.log(
            f"📡 AGENT DISPATCH: {drone_a_id} + {drone_b_id} split-scanning zone {zone_id}.",
            "AI",
        )
        return f"SUCCESS: {result['message']}"

    @mcp.tool()
    def reassign_drone(drone_id: str, zone_id: str) -> str:
        """
        Force-reassigns a drone to a different zone even if it has an active assignment.
        Use when a high-score zone just opened up and this drone is better positioned than any idle drone.
        Args:
            drone_id: The drone to reassign (e.g. 'ALPHA-3').
            zone_id: The new zone to assign (e.g. 'Z7').
        """
        sim = shared.sim
        drone = sim.drones.get(drone_id)
        if not drone:
            return f"Error: Drone {drone_id} not found."
        if drone.is_waiting_response:
            return f"Error: {drone_id} is on VICTIM STANDBY — cannot reassign."
        if drone.is_charging:
            return f"Error: {drone_id} is charging — wait until charged."

        zone = sim.zone.zones.get(zone_id)
        if not zone:
            return f"Error: Zone {zone_id} not found."
        if zone.status != ZoneStatus.UNSCANNED:
            return f"Error: Zone {zone_id} is {zone.status.value} — cannot assign."

        if drone.assigned_zone_id:
            old_zid = drone.assigned_zone_id
            if drone.path_queue:
                sim.zone.zones[old_zid].residual_path = list(drone.path_queue)
            sim.release_zone(old_zid)
            sim.log(f"🔀 AGENT: Releasing {drone_id} from {old_zid} → reassigning to {zone_id}.", "AI", drone_id)
            drone.assigned_zone_id = None
        else:
            sim.log(f"🔀 AGENT: Reassigning idle {drone_id} to priority zone {zone_id}.", "AI", drone_id)

        drone.path_queue = []
        drone.returning_to_base = False
        drone.target_x = None

        if not sim.claim_zone(zone_id, drone_id):
            return f"Error: Zone {zone_id} was just claimed by another drone."

        result = sim.assign_zone(drone_id, zone_id)
        if "error" in result:
            sim.release_zone(zone_id)
            return f"Error: {result['error']}"

        return f"SUCCESS: {drone_id} force-reassigned to {zone_id}. {result['message']}"

