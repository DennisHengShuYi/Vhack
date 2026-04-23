from io import BytesIO
from typing import Dict, List
import colorsys
import math

from PIL import Image

from simulation import GRID_H, GRID_W


def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int(round((len(sorted_values) - 1) * q))
    idx = max(0, min(len(sorted_values) - 1, idx))
    return sorted_values[idx]


def _majority_label(labels: List[str]) -> str:
    counts: Dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _majority_label_weighted(labels: List[str], preserve: str) -> str:
    counts: Dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    if counts.get(preserve, 0) >= 4:
        return preserve
    return max(counts.items(), key=lambda item: item[1])[0]


def _smooth_terrain_grid(terrain_grid: List[List[str]], passes: int = 2) -> List[List[str]]:
    smoothed = [row[:] for row in terrain_grid]
    for _ in range(passes):
        next_grid = [row[:] for row in smoothed]
        for y in range(GRID_H):
            for x in range(GRID_W):
                neighbors: List[str] = []
                for ny in range(max(0, y - 1), min(GRID_H, y + 2)):
                    for nx in range(max(0, x - 1), min(GRID_W, x + 2)):
                        neighbors.append(smoothed[ny][nx])
                next_grid[y][x] = _majority_label_weighted(neighbors, preserve=smoothed[y][x])
        smoothed = next_grid
    return smoothed


def _cleanup_small_islands(terrain_grid: List[List[str]], label: str, min_neighbors: int) -> None:
    for y in range(GRID_H):
        for x in range(GRID_W):
            if terrain_grid[y][x] != label:
                continue
            same_neighbors = 0
            neighborhood: List[str] = []
            for ny in range(max(0, y - 1), min(GRID_H, y + 2)):
                for nx in range(max(0, x - 1), min(GRID_W, x + 2)):
                    if nx == x and ny == y:
                        continue
                    neighborhood.append(terrain_grid[ny][nx])
                    if terrain_grid[ny][nx] == label:
                        same_neighbors += 1
            if same_neighbors >= min_neighbors:
                continue
            if neighborhood:
                terrain_grid[y][x] = _majority_label(neighborhood)


def _recover_false_lakes(
    terrain_grid: List[List[str]],
    feature_grid: List[List[Dict[str, float]]],
    thresholds: Dict[str, float],
) -> None:
    """Convert likely forest-but-lake cells back to forest using neighborhood and texture cues."""
    to_forest: List[tuple[int, int]] = []
    for y in range(GRID_H):
        for x in range(GRID_W):
            if terrain_grid[y][x] != "lake":
                continue

            forest_neighbors = 0
            lake_neighbors = 0
            for ny in range(max(0, y - 1), min(GRID_H, y + 2)):
                for nx in range(max(0, x - 1), min(GRID_W, x + 2)):
                    if nx == x and ny == y:
                        continue
                    if terrain_grid[ny][nx] == "forest":
                        forest_neighbors += 1
                    elif terrain_grid[ny][nx] == "lake":
                        lake_neighbors += 1

            feat = feature_grid[y][x]
            green_strength = feat["avg_g"] - max(feat["avg_r"], feat["avg_b"])
            blue_strength = feat["avg_b"] - max(feat["avg_r"], feat["avg_g"])
            is_textured = feat["texture_std"] >= thresholds["texture_mid"] * 1.05
            is_edgy = feat["edge_strength"] >= thresholds["edge_mid"] * 1.10
            greenish = (
                (0.18 <= feat["avg_h"] <= 0.48 and green_strength >= thresholds["green_hi"] * 0.85)
                or (green_strength >= blue_strength - 2.0)
            )

            # Water should be smoother and usually forms contiguous patches.
            if forest_neighbors >= 4 and lake_neighbors <= 2 and greenish and (is_textured or is_edgy):
                to_forest.append((x, y))

    for x, y in to_forest:
        terrain_grid[y][x] = "forest"


def _mark_urban_hotspots(terrain_grid: List[List[str]], texture_grid: List[List[float]]) -> None:
    """Promote textured city cores to hazard-like landmarks for clearer differentiation."""
    city_textures: List[float] = []
    for y in range(GRID_H):
        for x in range(GRID_W):
            if terrain_grid[y][x] == "city":
                city_textures.append(texture_grid[y][x])

    if len(city_textures) < 6:
        return

    city_textures.sort()
    cutoff_index = int(len(city_textures) * 0.7)
    cutoff = city_textures[min(cutoff_index, len(city_textures) - 1)]

    for y in range(GRID_H):
        for x in range(GRID_W):
            if terrain_grid[y][x] != "city":
                continue
            if texture_grid[y][x] < cutoff:
                continue
            city_neighbors = 0
            for ny in range(max(0, y - 1), min(GRID_H, y + 2)):
                for nx in range(max(0, x - 1), min(GRID_W, x + 2)):
                    if terrain_grid[ny][nx] == "city":
                        city_neighbors += 1
            if city_neighbors >= 4:
                terrain_grid[y][x] = "hazard"


def _classify_patch_stats(
    avg_h: float,
    avg_s: float,
    avg_v: float,
    avg_r: float,
    avg_g: float,
    avg_b: float,
    texture_std: float,
    edge_strength: float,
    thresholds: Dict[str, float],
) -> str:
    blue_strength = avg_b - max(avg_r, avg_g)
    green_strength = avg_g - max(avg_r, avg_b)
    red_strength = avg_r - max(avg_g, avg_b)

    lake_score = 0.0
    if 0.48 <= avg_h <= 0.73:
        lake_score += 1.0
    if avg_s >= thresholds["sat_mid"]:
        lake_score += 0.8
    if blue_strength >= thresholds["blue_hi"]:
        lake_score += 1.2
    if avg_v <= thresholds["value_water_max"]:
        lake_score += 0.6
    # Lakes are typically smoother and less edge-dense than vegetation textures.
    if texture_std <= thresholds["texture_mid"] * 1.15:
        lake_score += 0.5
    else:
        lake_score -= 0.6
    if edge_strength <= thresholds["edge_mid"] * 1.20:
        lake_score += 0.4
    else:
        lake_score -= 0.5
    if green_strength > blue_strength - 1.0:
        lake_score -= 0.5

    forest_score = 0.0
    if 0.20 <= avg_h <= 0.44:
        forest_score += 1.0
    if green_strength >= thresholds["green_hi"]:
        forest_score += 1.3
    if avg_s >= thresholds["sat_mid"]:
        forest_score += 0.8
    if texture_std >= thresholds["texture_mid"]:
        forest_score += 0.4
    if edge_strength >= thresholds["edge_mid"] * 0.9:
        forest_score += 0.25
    if green_strength > blue_strength - 1.0:
        forest_score += 0.35

    city_score = 0.0
    if avg_s <= thresholds["sat_low"]:
        city_score += 1.0
    if avg_v >= thresholds["value_city_min"]:
        city_score += 0.7
    if texture_std >= thresholds["texture_mid"]:
        city_score += 0.8
    if edge_strength >= thresholds["edge_mid"]:
        city_score += 0.8

    hazard_score = 0.0
    if texture_std >= thresholds["texture_hi"]:
        hazard_score += 1.2
    if edge_strength >= thresholds["edge_hi"]:
        hazard_score += 1.0
    if red_strength >= thresholds["red_mid"] and avg_s >= thresholds["sat_mid"]:
        hazard_score += 1.1
    if avg_v <= thresholds["value_dark"] and edge_strength >= thresholds["edge_mid"]:
        hazard_score += 0.7
    if avg_v >= thresholds["value_bright"] and avg_s <= thresholds["sat_low"] and texture_std >= thresholds["texture_mid"]:
        hazard_score += 0.8

    scores = {
        "lake": lake_score,
        "forest": forest_score,
        "city": city_score,
        "hazard": hazard_score,
        "flat": 0.9,
    }

    best_label = max(scores.items(), key=lambda item: item[1])[0]
    if scores[best_label] < 1.3:
        return "flat"

    if best_label == "city" and hazard_score >= city_score + 0.5:
        return "hazard"
    if best_label == "hazard" and city_score > hazard_score + 0.4:
        return "city"
    if best_label == "lake" and forest_score >= lake_score - 0.3 and green_strength > blue_strength - 2.0:
        return "forest"

    return best_label


def image_bytes_to_terrain_grid(image_bytes: bytes) -> List[List[str]]:
    """Convert an uploaded image into the simulation's fixed 20x15 terrain grid.

    Uses patch-based color and texture features so landmarks are differentiated
    more reliably than single-pixel classification.
    """
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    sample_w = GRID_W * 4
    sample_h = GRID_H * 4
    sampled = image.resize((sample_w, sample_h), Image.Resampling.BILINEAR)
    pixels = sampled.load()

    cell_w = sample_w / GRID_W
    cell_h = sample_h / GRID_H

    terrain: List[List[str]] = [["flat" for _ in range(GRID_W)] for _ in range(GRID_H)]
    texture_grid: List[List[float]] = [[0.0 for _ in range(GRID_W)] for _ in range(GRID_H)]
    edge_grid: List[List[float]] = [[0.0 for _ in range(GRID_W)] for _ in range(GRID_H)]
    feature_grid: List[List[Dict[str, float]]] = [
        [{} for _ in range(GRID_W)] for _ in range(GRID_H)
    ]

    for gy in range(GRID_H):
        for gx in range(GRID_W):
            x0 = int(gx * cell_w)
            x1 = int((gx + 1) * cell_w)
            y0 = int(gy * cell_h)
            y1 = int((gy + 1) * cell_h)

            sum_r = 0.0
            sum_g = 0.0
            sum_b = 0.0
            sum_h = 0.0
            sum_s = 0.0
            sum_v = 0.0
            gray_values: List[float] = []
            edge_accum = 0.0
            count = 0

            for py in range(y0, max(y0 + 1, y1)):
                for px in range(x0, max(x0 + 1, x1)):
                    r, g, b = pixels[px, py]
                    rf = float(r)
                    gf = float(g)
                    bf = float(b)
                    h, s, v = colorsys.rgb_to_hsv(rf / 255.0, gf / 255.0, bf / 255.0)
                    sum_r += rf
                    sum_g += gf
                    sum_b += bf
                    sum_h += h
                    sum_s += s
                    sum_v += v
                    gray = (0.299 * rf + 0.587 * gf + 0.114 * bf) / 255.0
                    gray_values.append(gray)
                    if px + 1 < max(x0 + 1, x1):
                        r2, g2, b2 = pixels[px + 1, py]
                        gray2 = (0.299 * float(r2) + 0.587 * float(g2) + 0.114 * float(b2)) / 255.0
                        edge_accum += abs(gray2 - gray)
                    if py + 1 < max(y0 + 1, y1):
                        r3, g3, b3 = pixels[px, py + 1]
                        gray3 = (0.299 * float(r3) + 0.587 * float(g3) + 0.114 * float(b3)) / 255.0
                        edge_accum += abs(gray3 - gray)
                    count += 1

            if count == 0:
                continue

            avg_r = sum_r / count
            avg_g = sum_g / count
            avg_b = sum_b / count
            avg_h = sum_h / count
            avg_s = sum_s / count
            avg_v = sum_v / count

            mean_gray = sum(gray_values) / len(gray_values)
            variance = sum((v - mean_gray) ** 2 for v in gray_values) / len(gray_values)
            texture_std = math.sqrt(variance)
            edge_strength = edge_accum / max(1, count)
            texture_grid[gy][gx] = texture_std
            edge_grid[gy][gx] = edge_strength

            feature_grid[gy][gx] = {
                "avg_h": avg_h,
                "avg_s": avg_s,
                "avg_v": avg_v,
                "avg_r": avg_r,
                "avg_g": avg_g,
                "avg_b": avg_b,
                "texture_std": texture_std,
                "edge_strength": edge_strength,
                "blue_strength": avg_b - max(avg_r, avg_g),
                "green_strength": avg_g - max(avg_r, avg_b),
                "red_strength": avg_r - max(avg_g, avg_b),
            }

    sat_values = [feature_grid[y][x]["avg_s"] for y in range(GRID_H) for x in range(GRID_W)]
    val_values = [feature_grid[y][x]["avg_v"] for y in range(GRID_H) for x in range(GRID_W)]
    texture_values = [texture_grid[y][x] for y in range(GRID_H) for x in range(GRID_W)]
    edge_values = [edge_grid[y][x] for y in range(GRID_H) for x in range(GRID_W)]
    blue_values = [feature_grid[y][x]["blue_strength"] for y in range(GRID_H) for x in range(GRID_W)]
    green_values = [feature_grid[y][x]["green_strength"] for y in range(GRID_H) for x in range(GRID_W)]
    red_values = [feature_grid[y][x]["red_strength"] for y in range(GRID_H) for x in range(GRID_W)]

    thresholds = {
        "sat_low": _percentile(sat_values, 0.30),
        "sat_mid": _percentile(sat_values, 0.55),
        "value_dark": _percentile(val_values, 0.22),
        "value_water_max": _percentile(val_values, 0.58),
        "value_city_min": _percentile(val_values, 0.45),
        "value_bright": _percentile(val_values, 0.78),
        "texture_mid": _percentile(texture_values, 0.55),
        "texture_hi": _percentile(texture_values, 0.77),
        "edge_mid": _percentile(edge_values, 0.56),
        "edge_hi": _percentile(edge_values, 0.80),
        "blue_hi": _percentile(blue_values, 0.65),
        "green_hi": _percentile(green_values, 0.62),
        "red_mid": _percentile(red_values, 0.62),
    }

    # Clamp dynamic thresholds to robust floor values for washed-out maps.
    thresholds["sat_low"] = min(thresholds["sat_low"], 0.30)
    thresholds["sat_mid"] = max(thresholds["sat_mid"], 0.18)
    thresholds["value_water_max"] = min(thresholds["value_water_max"], 0.90)
    thresholds["value_city_min"] = max(thresholds["value_city_min"], 0.26)
    thresholds["texture_mid"] = max(thresholds["texture_mid"], 0.07)
    thresholds["texture_hi"] = max(thresholds["texture_hi"], 0.10)
    thresholds["edge_mid"] = max(thresholds["edge_mid"], 0.035)
    thresholds["edge_hi"] = max(thresholds["edge_hi"], 0.055)
    thresholds["blue_hi"] = max(thresholds["blue_hi"], 6.0)
    thresholds["green_hi"] = max(thresholds["green_hi"], 7.0)
    thresholds["red_mid"] = max(thresholds["red_mid"], 8.0)

    for gy in range(GRID_H):
        for gx in range(GRID_W):
            feature = feature_grid[gy][gx]
            terrain[gy][gx] = _classify_patch_stats(
                avg_h=feature["avg_h"],
                avg_s=feature["avg_s"],
                avg_v=feature["avg_v"],
                avg_r=feature["avg_r"],
                avg_g=feature["avg_g"],
                avg_b=feature["avg_b"],
                texture_std=feature["texture_std"],
                edge_strength=feature["edge_strength"],
                thresholds=thresholds,
            )

    terrain = _smooth_terrain_grid(terrain, passes=1)
    _recover_false_lakes(terrain, feature_grid, thresholds)
    _cleanup_small_islands(terrain, label="lake", min_neighbors=2)
    _cleanup_small_islands(terrain, label="forest", min_neighbors=1)
    terrain = _smooth_terrain_grid(terrain, passes=1)
    _mark_urban_hotspots(terrain, texture_grid)

    # Keep the base cell safe and traversable.
    terrain[0][0] = "flat"
    return terrain


def summarize_terrain(terrain_grid: List[List[str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {"flat": 0, "forest": 0, "city": 0, "hazard": 0, "lake": 0}
    for row in terrain_grid:
        for terrain in row:
            counts[terrain] = counts.get(terrain, 0) + 1
    return counts
