"""
MissionMemory — tiered event storage for SENTINEL agent.

Tier 0 (cap 6): never dropped — survivor detections, P1 alerts, drone failures
Tier 1 (cap 5): compressed last — zone splits, reassigns, completions, RTBs
Tier 2 (cap 3): compressed first — routine assignments, thermal anomalies

Survivor locations (tier 0) are always preserved for the full mission duration.
"""
import re


class MissionMemory:
    TIER0_CAP = 6
    TIER1_CAP = 5
    TIER2_CAP = 3
    PROMPT_CHAR_BUDGET = 1600  # ~400 tokens

    def __init__(self) -> None:
        self.tier0: list[str] = []
        self.tier1: list[str] = []
        self.tier2: list[str] = []

    def reset(self) -> None:
        """Clear all tiers — call on MISSION START."""
        self.tier0 = []; self.tier1 = []; self.tier2 = []

    def extract(self, messages: list, tick: int) -> None:
        """Scan tool result messages and classify events into tiers."""
        for msg in messages:
            if getattr(msg, "type", None) != "tool":
                continue
            result = self._classify(str(msg.content), tick)
            if result:
                self._append(*result)

    def _classify(self, content: str, tick: int) -> tuple[int, str] | None:
        low = content.lower()
        # Tier 0
        if "survivor" in low and ("found" in low or "detected" in low):
            return (0, f"Tick {tick}: Survivor detected — {content[:100].strip()}")
        if "critical" in low:
            return (0, f"Tick {tick}: CRITICAL — {content[:80].strip()}")
        if "offline" in low or "failure" in low:
            return (0, f"Tick {tick}: Drone event — {content[:80].strip()}")
        # Tier 1
        if "split" in low and ("zone" in low or "assign" in low):
            return (1, f"Tick {tick}: Zone split — {content[:80].strip()}")
        if "reassign" in low or "redirect" in low:
            return (1, f"Tick {tick}: Reassign — {content[:80].strip()}")
        if "complete" in low and "zone" in low:
            z = re.search(r'Z\d+', content)
            return (1, f"Tick {tick}: {z.group(0) if z else 'Zone'} complete")
        if "rtb" in low or ("low battery" in low and "return" in low):
            d = re.search(r'ALPHA-\d+', content)
            b = re.search(r'(\d+)%', content)
            return (1, f"Tick {tick}: {d.group(0) if d else 'drone'} RTB {b.group(1) if b else '?'}%")
        # Tier 2
        if "assigned" in low and "zone" in low:
            d = re.search(r'ALPHA-\d+', content)
            z = re.search(r'Z\d+', content)
            return (2, f"Tick {tick}: {d.group(0) if d else 'drone'}→{z.group(0) if z else 'zone'}")
        if "anomaly" in low or "thermal" in low:
            return (2, f"Tick {tick}: Thermal — {content[:60].strip()}")
        return None

    def _append(self, tier: int, text: str) -> None:
        if tier == 0:
            self.tier0.append(text)
            if len(self.tier0) > self.TIER0_CAP:
                self.tier0.pop(0)
        elif tier == 1:
            self.tier1.append(text)
            if len(self.tier1) > self.TIER1_CAP:
                self.tier1.pop(0)
        else:
            self.tier2.append(text)
            if len(self.tier2) > self.TIER2_CAP:
                self.tier2.pop(0)

    def to_prompt_block(self) -> str:
        """Build memory string for LLM prompt. Tier 0 always included."""
        if not self.tier0 and not self.tier1 and not self.tier2:
            return ""
        lines = ["=== MISSION MEMORY (key events) ==="]
        used = 0
        for entry in self.tier0:
            lines.append(f"  • {entry}"); used += len(entry)
        for entry in self.tier1:
            if used + len(entry) > self.PROMPT_CHAR_BUDGET:
                break
            lines.append(f"  • {entry}"); used += len(entry)
        for entry in self.tier2:
            if used + len(entry) > self.PROMPT_CHAR_BUDGET:
                break
            lines.append(f"  • {entry}"); used += len(entry)
        lines.append("=== END MEMORY ===")
        return "\n".join(lines)
