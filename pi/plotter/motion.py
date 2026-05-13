import math

import numpy as np


LIMIT_POSITION = np.array([100.0, 100.0])
DEFAULT_MARGIN_MM = 0.0
DEFAULT_EPSILON_MM = 0.10
DEFAULT_MIN_SEGMENT_MM = 0.04
APPROACH_FEED_MM_MIN = 1200


def extract_points(payload):
    if isinstance(payload, dict):
        if "points" in payload:
            payload = payload["points"]
        elif "path" in payload:
            return extract_points(payload["path"])
        elif "coordinates" in payload:
            payload = payload["coordinates"]
    points = np.asarray(payload, dtype=float)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise ValueError("path must contain at least two [x, y] points")
    if not np.isfinite(points).all():
        raise ValueError("path contains non-finite coordinates")
    return points


def normalize_points(points, margin_mm=DEFAULT_MARGIN_MM, flip_y=True):
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    span = maxs - mins
    if np.any(span <= 1e-9):
        raise ValueError("path has zero width or height")
    safe = LIMIT_POSITION - 2 * margin_mm
    if np.any(safe <= 0):
        raise ValueError("margin leaves no drawable area")

    scale = float(min(safe[0] / span[0], safe[1] / span[1]))
    normalized = (points - mins) * scale
    used = span * scale
    offset = margin_mm + (safe - used) / 2
    normalized += offset
    if flip_y:
        normalized[:, 1] = LIMIT_POSITION[1] - normalized[:, 1]
    return normalized, {
        "type": "uniform_scale_fit",
        "margin_mm": margin_mm,
        "source_bbox": bbox(points),
        "scale_mm_per_source_unit": scale,
        "offset_before_y_flip_mm": offset.tolist(),
        "flip_y": flip_y,
        "normalized_bbox_mm": bbox(normalized),
    }


def bbox(points):
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    return {
        "min": [float(mins[0]), float(mins[1])],
        "max": [float(maxs[0]), float(maxs[1])],
        "span": [float(maxs[0] - mins[0]), float(maxs[1] - mins[1])],
    }


def assert_in_bounds(points):
    if np.any(points < -1e-6) or np.any(points > LIMIT_POSITION + 1e-6):
        raise ValueError(f"path is out of bounds: {bbox(points)}")


def remove_short_segments(points, min_segment_mm=DEFAULT_MIN_SEGMENT_MM):
    if len(points) <= 2:
        return points
    kept = [points[0]]
    for point in points[1:-1]:
        if np.linalg.norm(point - kept[-1]) >= min_segment_mm:
            kept.append(point)
    kept.append(points[-1])
    return np.asarray(kept, dtype=float)


def rdp(points, epsilon_mm=DEFAULT_EPSILON_MM):
    if len(points) <= 2:
        return points
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = True
    keep[-1] = True
    stack = [(0, len(points) - 1)]
    epsilon2 = epsilon_mm * epsilon_mm
    while stack:
        start_index, end_index = stack.pop()
        if end_index <= start_index + 1:
            continue
        start = points[start_index]
        end = points[end_index]
        vector = end - start
        denom = float(np.dot(vector, vector))
        candidates = points[start_index + 1 : end_index]
        if denom <= 1e-12:
            distances2 = np.sum((candidates - start) ** 2, axis=1)
        else:
            t = np.clip(((candidates - start) @ vector) / denom, 0, 1)
            projected = start + t[:, None] * vector
            distances2 = np.sum((candidates - projected) ** 2, axis=1)
        local_index = int(np.argmax(distances2))
        max_distance2 = float(distances2[local_index]) if len(distances2) else 0.0
        if max_distance2 > epsilon2:
            index = start_index + 1 + local_index
            keep[index] = True
            stack.append((start_index, index))
            stack.append((index, end_index))
    return points[keep]


def turn_angles(points):
    angles = np.zeros(len(points), dtype=float)
    vectors = np.diff(points, axis=0)
    for i in range(1, len(points) - 1):
        a = vectors[i - 1]
        b = vectors[i]
        la = float(np.linalg.norm(a))
        lb = float(np.linalg.norm(b))
        if la <= 1e-9 or lb <= 1e-9:
            continue
        cosine = float(np.clip(np.dot(a, b) / (la * lb), -1, 1))
        angles[i] = math.degrees(math.acos(cosine))
    return angles


def plan_feeds(points):
    angles = turn_angles(points)
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    feeds = []
    for i, length in enumerate(lengths):
        angle = max(angles[i], angles[i + 1])
        if angle > 120:
            feed = 600
        elif angle > 90:
            feed = 800
        elif angle > 60:
            feed = 1100
        elif angle > 35:
            feed = 1600
        elif angle > 15:
            feed = 2200
        else:
            feed = 3000

        if length < 0.5:
            feed = min(feed, 1200)
        elif length < 1.0:
            feed = min(feed, 1800)
        feeds.append(feed)
    return np.asarray(feeds, dtype=float)


def path_stats(points, feeds=None):
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    angles = turn_angles(points)
    stats = {
        "point_count": int(len(points)),
        "bbox_mm": bbox(points),
        "path_length_mm": float(lengths.sum()),
        "segment_min_mm": float(lengths.min()) if len(lengths) else 0.0,
        "segment_median_mm": float(np.median(lengths)) if len(lengths) else 0.0,
        "segment_p95_mm": float(np.percentile(lengths, 95)) if len(lengths) else 0.0,
        "segment_max_mm": float(lengths.max()) if len(lengths) else 0.0,
        "turn_median_deg": float(np.median(angles[1:-1])) if len(angles) > 2 else 0.0,
        "turn_p95_deg": float(np.percentile(angles[1:-1], 95)) if len(angles) > 2 else 0.0,
        "turns_gt_90": int(np.sum(angles > 90)),
    }
    if feeds is not None and len(feeds):
        stats.update(
            {
                "estimated_feed_time_s": float(np.sum(lengths / feeds) * 60.0),
                "weighted_feed_mm_min": float(lengths.sum() / np.sum(lengths / feeds)),
                "feed_min_mm_min": float(feeds.min()),
                "feed_max_mm_min": float(feeds.max()),
            }
        )
    return stats


def gcode_for_path(points, feeds):
    commands = [f"g1x{points[0,0]:.4f}y{points[0,1]:.4f}f{APPROACH_FEED_MM_MIN}"]
    for point, feed in zip(points[1:], feeds):
        commands.append(f"g1x{point[0]:.4f}y{point[1]:.4f}f{feed:.0f}")
    return commands


def plan_path(
    path_payload,
    raw=False,
    flip_y=True,
    margin_mm=DEFAULT_MARGIN_MM,
    epsilon_mm=DEFAULT_EPSILON_MM,
    min_segment_mm=DEFAULT_MIN_SEGMENT_MM,
):
    original = extract_points(path_payload)
    if raw:
        normalized = original.astype(float, copy=True)
        normalization = {"type": "raw_plotter_mm", "normalized_bbox_mm": bbox(normalized)}
    else:
        normalized, normalization = normalize_points(original, margin_mm=margin_mm, flip_y=flip_y)

    assert_in_bounds(normalized)
    cleaned = remove_short_segments(normalized, min_segment_mm=min_segment_mm)
    simplified = rdp(cleaned, epsilon_mm=epsilon_mm)
    assert_in_bounds(simplified)
    feeds = plan_feeds(simplified)
    commands = gcode_for_path(simplified, feeds)
    return {
        "commands": commands,
        "points": simplified,
        "feeds": feeds,
        "stats": {
            "original": path_stats(original),
            "normalized": path_stats(normalized),
            "planned": path_stats(simplified, feeds=feeds),
            "normalization": normalization,
            "planner": {
                "epsilon_mm": epsilon_mm,
                "margin_mm": margin_mm,
                "min_segment_mm": min_segment_mm,
            },
        },
    }
