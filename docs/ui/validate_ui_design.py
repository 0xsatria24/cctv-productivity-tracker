"""Static UI handoff checks. Does not verify a running Qt application."""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from render_design_preview import DRAFT_POINTS

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
TOKENS = json.loads((HERE / "design-tokens.json").read_text(encoding="utf-8"))
COLORS = TOKENS["colors"]
checks = []
contrast = []


def require(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)


def luminance(hex_value):
    rgb = [int(hex_value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))


def ratio(foreground, background):
    values = sorted([luminance(COLORS[foreground]), luminance(COLORS[background])])
    return (values[1] + .05) / (values[0] + .05)


def check_contrast():
    for surface in ["surface.canvas", "surface.sidebar", "surface.panel", "surface.raised", "surface.hover", "surface.selected", "surface.video"]:
        for text in ["text.primary", "text.secondary", "text.muted"]:
            actual = ratio(text, surface)
            require(actual >= 4.5, f"Readable contrast: {text} on {surface} ({actual:.2f}:1)")
            contrast.append((text, surface, actual, 4.5))
    for text in ["accent.default", "status.occupied", "status.empty", "status.unknown", "status.warning", "status.error"]:
        for surface in ["surface.panel", "surface.selected", "surface.video"]:
            actual = ratio(text, surface)
            require(actual >= 4.5, f"Semantic contrast: {text} on {surface} ({actual:.2f}:1)")
            contrast.append((text, surface, actual, 4.5))
    for fg, bg in [("border.control", "surface.raised"), ("focus.ring", "surface.selected"), ("accent.foreground", "accent.default")]:
        target = 4.5 if fg == "accent.foreground" else 3
        actual = ratio(fg, bg)
        require(actual >= target, f"Essential control contrast: {fg} on {bg} ({actual:.2f}:1)")
        contrast.append((fg, bg, actual, target))


def check_assets():
    for width, height in [TOKENS["sizes"]["window_default"], TOKENS["sizes"]["window_minimum"]]:
        for name in ["live-monitoring", "workspace-editor"]:
            file = HERE / "previews" / f"{name}-{width}.svg"
            root = ET.fromstring(file.read_text(encoding="utf-8"))
            require(root.attrib["viewBox"] == f"0 0 {width} {height}", f"SVG correct logical dimensions: {file.name}")
            tags = {node.tag.split("}")[-1] for node in root.iter()}
            require(not tags & {"linearGradient", "radialGradient", "filter", "image", "animate", "script"}, f"No forbidden effects/images/runtime claims: {file.name}")
            texts = [node.text or "" for node in root.iter() if node.tag.endswith("}text")]
            require("PREVIEW DESAIN" in texts and "Tanpa data CCTV" in texts, f"Proposal status disclosed: {file.name}")
            require(not any(re.search(r"\d+(?:[.,]\d+)?%|\b\d{2}:\d{2}:\d{2}\b", text) for text in texts), f"No fabricated numeric analytics: {file.name}")
            require(all(text not in {"LIVE", "ONLINE", "Productivity score"} for text in texts), f"No false live/healthy badge: {file.name}")
            with Image.open(file.with_suffix(".png")) as png:
                require(png.size == (width * 2, height * 2), f"PNG 2x output: {file.name}")


def check_handoff():
    expected_nav = ["Ringkasan", "Pemantauan Live", "Workstation", "Analitik", "Laporan", "Kamera", "Pengaturan"]
    require(TOKENS["navigation"] == expected_nav, "Navigation matches PRD V1 without employee/alert sections")
    require(TOKENS["preview"]["has_numeric_analytics"] is False and TOKENS["preview"]["has_real_camera_data"] is False, "Preview data limitations declared")
    require(3 <= len(DRAFT_POINTS) <= 64 and all(0 <= x <= 1 and 0 <= y <= 1 for x, y in DRAFT_POINTS), "Draft polygon coordinate range/vertex bounds")
    area = abs(sum(x * DRAFT_POINTS[(i + 1) % len(DRAFT_POINTS)][1] - y * DRAFT_POINTS[(i + 1) % len(DRAFT_POINTS)][0] for i, (x, y) in enumerate(DRAFT_POINTS))) / 2
    require(area > 0, "Draft polygon has nonzero area")
    docs = [PROJECT / name for name in ["UI_UX_SPEC.md", "DESIGN_SYSTEM.md", "COMPONENT_INVENTORY.md", "SCREEN_IMPLEMENTATION_PLAN.md", "README.md"]]
    require(all(p.exists() for p in docs), "Four requested documents and README exist")
    linked = 0
    for doc in docs:
        body = doc.read_text(encoding="utf-8")
        for href in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", body):
            href = href.strip("<>").split("#", 1)[0]
            if not href or "://" in href:
                continue
            require((doc.parent / href).exists(), f"Local link exists: {doc.name} -> {href}")
            linked += 1
    require(linked >= 20, "Handoff traceability links present")


def main():
    check_contrast()
    check_assets()
    check_handoff()
    lines = ["# Static UI Design Validation", "", f"PASS: {len(checks)} static handoff checks.", "",
             "## Contrast measurements", "", "| Foreground | Surface | Ratio | Target |", "|---|---|---|---|"]
    lines.extend(f"| {fg} | {bg} | {actual:.2f}:1 | {target}:1 |" for fg, bg, actual, target in contrast)
    lines.extend(["", "## Executed checks", ""] + [f"- PASS: {label}" for label in checks] + [
        "", "## Scope", "", "Static documents/tokens/proposal SVG and PNG only. Render script also rejects over-wide text. Visual PNG inspection is recorded separately. No Qt app, live CCTV, HTTP/WebSocket runtime, keyboard/screen-reader behavior, high-DPI native rendering, or performance has been verified.", ""])
    (HERE / "VALIDATION_RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"PASS: {len(checks)} static UI handoff checks. Report: docs/ui/VALIDATION_RESULTS.md")


if __name__ == "__main__":
    main()
