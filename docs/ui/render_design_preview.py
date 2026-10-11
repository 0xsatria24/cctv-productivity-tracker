"""Render design proposals, never a screenshot of a running Qt/CCTV app.

Uses reusable product tokens and native Windows fonts. SVG is editable vector
output; PNG is a 2x antialiased preview. No source reference image is edited.
Requires Pillow; production GUI remains PySide6 after direction approval.
"""
from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
TOKENS = json.loads((ROOT / "design-tokens.json").read_text(encoding="utf-8"))
C = TOKENS["colors"]
S = TOKENS["sizes"]
G = TOKENS["spacing"]
OUT = ROOT / "previews"
SCALE = 2


class Canvas:
    def __init__(self, width: int, height: int, name: str):
        self.width, self.height, self.name = width, height, name
        self.image = Image.new("RGB", (width * SCALE, height * SCALE), C["surface.canvas"])
        self.draw = ImageDraw.Draw(self.image)
        self.svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                    '<title>Proposal desain UI CCTV, tanpa stream atau angka analitik nyata</title>',
                    '<desc>Desain statis untuk review; bukan screenshot aplikasi Qt berjalan.</desc>']
        self.bounds_issues: list[str] = []

    def rect(self, x, y, w, h, fill="surface.panel", border=None, radius=0, stroke=1):
        box = tuple(round(v * SCALE) for v in (x, y, x + w, y + h))
        self.draw.rounded_rectangle(box, radius=radius * SCALE, fill=C[fill],
                                    outline=C[border] if border else None, width=stroke * SCALE)
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{C[fill]}"'
                        + (f' stroke="{C[border]}" stroke-width="{stroke}"' if border else "") + '/>')

    def line(self, x1, y1, x2, y2, color="border.subtle", stroke=1):
        self.draw.line(tuple(round(v * SCALE) for v in (x1, y1, x2, y2)), fill=C[color], width=stroke * SCALE)
        self.svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{C[color]}" stroke-width="{stroke}"/>')

    def font(self, role="body"):
        spec = TOKENS["fonts"]["roles"][role]
        file = "consola.ttf" if role == "code" else "segoeuib.ttf" if spec["weight"] == "semibold" else "segoeui.ttf"
        size = round(spec["point_size"] * 96 / 72 * SCALE)
        return ImageFont.truetype(str(Path("C:/Windows/Fonts") / file), size)

    def width_of(self, value, role="body"):
        return self.draw.textlength(value, font=self.font(role)) / SCALE

    def text(self, x, y, value, role="body", color="text.primary", max_width=None, align="left"):
        width = self.width_of(value, role)
        if max_width is not None and width > max_width + .5:
            self.bounds_issues.append(f"{self.name}: text too wide: {value!r} ({width:.1f}>{max_width})")
        if align == "center":
            x -= width / 2
        if align == "right":
            x -= width
        if x < 0 or x + width > self.width + .5:
            self.bounds_issues.append(f"{self.name}: text beyond canvas: {value!r}")
        font = self.font(role)
        self.draw.text((round(x * SCALE), round(y * SCALE)), value, font=font, fill=C[color], anchor="lt")
        pt = TOKENS["fonts"]["roles"][role]["point_size"]
        family = "Consolas" if role == "code" else "Segoe UI"
        weight = "600" if TOKENS["fonts"]["roles"][role]["weight"] == "semibold" else "400"
        self.svg.append(f'<text x="{x:.2f}" y="{y + pt * 96 / 72 * .82:.2f}" fill="{C[color]}" font-family="{family},sans-serif" font-size="{pt * 96 / 72:.2f}" font-weight="{weight}">{escape(value)}</text>')

    def paragraph(self, x, y, value, width, role="body", color="text.secondary"):
        lines, current = [], ""
        for word in value.split():
            trial = f"{current} {word}".strip()
            if self.width_of(trial, role) > width and current:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        line_height = round(TOKENS["fonts"]["roles"][role]["point_size"] * 96 / 72) + G["xs"]
        for index, line in enumerate(lines):
            self.text(x, y + index * line_height, line, role, color, max_width=width)
        return y + len(lines) * line_height

    def button(self, x, y, w, label, primary=False, disabled=False):
        fill = "accent.default" if primary else "surface.raised"
        color = "text.disabled" if disabled else "accent.foreground" if primary else "text.primary"
        self.rect(x, y, w, S["control"], fill, "border.subtle" if disabled else "border.control", TOKENS["radius"]["control"])
        self.text(x + w / 2, y + G["sm"], label, color=color, max_width=w - G["lg"], align="center")

    def save(self):
        OUT.mkdir(parents=True, exist_ok=True)
        self.image.save(OUT / f"{self.name}.png")
        (OUT / f"{self.name}.svg").write_text("\n".join(self.svg) + "\n</svg>\n", encoding="utf-8")
        if self.bounds_issues:
            raise ValueError("\n".join(self.bounds_issues))


def shell(canvas, selected, title, subtitle):
    width, height = canvas.width, canvas.height
    compact = width < S["inspector_breakpoint"]
    rail = S["sidebar_compact"] if compact else S["sidebar"]
    canvas.rect(0, 0, rail, height, "surface.sidebar")
    canvas.line(rail, 0, rail, height)
    canvas.text(G["lg"], G["xl"], "CCTV Workspace", "body" if compact else "section", max_width=rail - G["xxl"])
    canvas.text(G["lg"], 52, "DESKTOP LOKAL", "caption", "text.muted")
    canvas.line(G["lg"], 88, rail - G["lg"], 88)
    for i, label in enumerate(TOKENS["navigation"]):
        y = 104 + i * (S["nav_row"] + G["xs"])
        if label == selected:
            canvas.rect(G["sm"], y, rail - G["lg"], S["nav_row"], "surface.selected", radius=TOKENS["radius"]["control"])
            canvas.rect(G["sm"], y + G["sm"], TOKENS["stroke"]["focus"], S["nav_row"] - G["lg"], "accent.default")
        canvas.text(G["lg"], y + G["md"], label, color="accent.default" if label == selected else "text.secondary", max_width=rail - G["xxl"])
    canvas.text(G["lg"], height - 112, "Akses lokal", "caption", "text.secondary")
    canvas.text(G["lg"], height - 88, "Mengikuti akun OS", "caption", "text.muted")
    canvas.rect(rail, 0, width - rail, S["header"], "surface.canvas")
    canvas.text(rail + G["lg"], 20, title, "title")
    canvas.text(rail + G["lg"], 54, subtitle, "body", "text.secondary", max_width=width - rail - 248)
    canvas.text(width - G["lg"], 24, "PREVIEW DESAIN", "caption", "accent.default", align="right")
    canvas.text(width - G["lg"], 48, "Tanpa data CCTV", "caption", "text.muted", align="right")
    canvas.line(rail, S["header"], width, S["header"])
    canvas.rect(rail, height - S["status_bar"], width - rail, S["status_bar"], "surface.sidebar")
    canvas.line(rail, height - S["status_bar"], width, height - S["status_bar"])
    canvas.text(rail + G["lg"], height - 20, "Engine tidak tersambung", "caption", "status.warning")
    canvas.text(rail + 220, height - 20, "Tersimpan sampai: N/A", "caption", "text.secondary")
    if not compact:
        canvas.text(rail + 440, height - 20, "Timezone lokasi: belum diatur", "caption", "text.secondary")
    canvas.text(width - G["lg"], height - 20, "Monitoring tidak aktif", "caption", "text.secondary", align="right")
    return rail, compact


def heading(canvas, x, y, w, title, action=None):
    canvas.rect(x, y, w, S["panel_heading"], "surface.panel")
    canvas.text(x + G["md"], y + G["md"], title, "section")
    if action:
        canvas.text(x + w - G["md"], y + G["md"], action, "caption", "accent.default", align="right")
    canvas.line(x, y + S["panel_heading"], x + w, y + S["panel_heading"])


CAMERAS = [
    ("Area produksi", "CAM-01", "Tanpa stream", "text.secondary"),
    ("Area perakitan", "CAM-02", "Tidak terhubung", "status.error"),
    ("Area pengemasan", "CAM-03", "Kredensial belum diisi", "status.warning"),
    ("Gudang", "CAM-04", "Nonaktif", "text.muted")
]


def camera_list(canvas, x, y, w, h):
    canvas.rect(x, y, w, h, "surface.panel", "border.subtle", TOKENS["radius"]["panel"])
    heading(canvas, x, y, w, "Daftar kamera")
    for i, (name, camera_id, status, color) in enumerate(CAMERAS):
        row_y = y + S["panel_heading"] + G["sm"] + i * 80
        if i == 0:
            canvas.rect(x + G["xs"], row_y, w - G["sm"], 72, "surface.selected", radius=TOKENS["radius"]["control"])
            canvas.rect(x + G["xs"], row_y + G["sm"], 2, 56, "accent.default")
        canvas.text(x + G["md"], row_y + G["sm"], name, max_width=w - G["xl"])
        canvas.text(x + G["md"], row_y + 28, camera_id, "code", "text.muted")
        canvas.text(x + G["md"], row_y + 48, status, "caption", color, max_width=w - G["xl"])
    canvas.line(x + G["md"], y + h - 108, x + w - G["md"], y + h - 108)
    canvas.paragraph(x + G["md"], y + h - 96, "Nama dan state kamera adalah contoh untuk review desain.", w - G["xl"], "caption", "text.muted")
    canvas.button(x + G["md"], y + h - 44, w - G["xl"], "Tambah kamera")


def tile(canvas, x, y, w, h, index):
    name, cid, status, color = CAMERAS[index]
    canvas.rect(x, y, w, h, "surface.video", "accent.default" if index == 0 else "border.subtle", TOKENS["radius"]["video"])
    canvas.rect(x + 1, y + 1, w - 2, S["video_heading"], "surface.panel")
    canvas.text(x + G["md"], y + G["sm"], name, max_width=w - 100)
    canvas.text(x + w - G["md"], y + G["sm"], cid, "code", "text.muted", align="right")
    titles = ["Belum ada frame", "Kamera tidak terhubung", "Kredensial belum tersedia", "Kamera dinonaktifkan"]
    actions = ["Uji koneksi", "Buka diagnostik", "Isi kredensial", "Buka konfigurasi"]
    body_h = h - S["video_heading"] - S["video_footer"]
    center = y + S["video_heading"] + body_h / 2
    canvas.text(x + w / 2, center - 32, titles[index], "section", color, max_width=w - G["xxl"], align="center")
    canvas.text(x + w / 2, center - 8, "Observasi zona belum tersedia", "caption", "text.muted", max_width=w - G["xxl"], align="center")
    canvas.button(x + w / 2 - 76, center + 16, 152, actions[index])
    canvas.rect(x + 1, y + h - S["video_footer"] - 1, w - 2, S["video_footer"], "surface.panel")
    canvas.text(x + G["md"], y + h - 18, "Waktu frame: N/A", "caption", "text.muted")
    canvas.text(x + w - G["md"], y + h - 18, status if index != 2 else "Kredensial belum diisi", "caption", color, align="right")


def live(width, height):
    cv = Canvas(width, height, f"live-monitoring-{width}")
    side, compact = shell(cv, "Pemantauan Live", "Pemantauan Live", "Status stream dan observasi zona ditampilkan terpisah.")
    x = side + G["lg"]
    rail_w = S["camera_rail_compact"] if compact else S["camera_rail"]
    y = 104
    content_h = height - S["status_bar"] - G["lg"] - y
    camera_list(cv, x, y, rail_w, content_h)
    main_x = x + rail_w + G["md"]
    inspector_w = 0 if compact else S["inspector"]
    main_w = width - G["lg"] - main_x - (inspector_w + G["md"] if inspector_w else 0)
    cv.text(main_x, y + G["xs"], "TAMPILAN KAMERA", "caption", "text.muted")
    cv.button(main_x + 160, y, 68, "Fokus")
    cv.button(main_x + 236, y, 68, "2 × 2", primary=True)
    cv.button(main_x + 312, y, 68, "3 × 3")
    if compact:
        cv.button(main_x + main_w - 104, y, 104, "Detail kamera")
    else:
        cv.text(main_x + main_w, y + G["sm"], "Overlay: zona", "caption", "text.secondary", align="right")
    grid_y = y + S["toolbar"]
    summary_h = 100 if compact else 132
    grid_h = height - S["status_bar"] - G["lg"] - summary_h - G["md"] - grid_y
    tile_w, tile_h = (main_w - G["md"]) / 2, (grid_h - G["md"]) / 2
    for i in range(4):
        tile(cv, main_x + (i % 2) * (tile_w + G["md"]), grid_y + (i // 2) * (tile_h + G["md"]), tile_w, tile_h, i)
    summary_y = grid_y + grid_h + G["md"]
    cv.rect(main_x, summary_y, main_w, summary_h, "surface.panel", "border.subtle", TOKENS["radius"]["panel"])
    heading(cv, main_x, summary_y, main_w, "Observasi workstation", "Buka timeline")
    cv.text(main_x + G["md"], summary_y + 52, "Belum ada observasi yang dapat ditampilkan.", color="text.secondary")
    cv.text(main_x + G["md"], summary_y + 76, "Kamera offline tidak dihitung sebagai workstation kosong.", "caption", "text.muted", max_width=main_w - G["xl"])
    if not compact:
        cv.text(main_x + G["md"], summary_y + 104, "Terisi", "caption", "status.occupied")
        cv.text(main_x + 104, summary_y + 104, "Kosong", "caption", "status.empty")
        cv.text(main_x + 200, summary_y + 104, "Tidak diketahui", "caption", "status.unknown")
        ix = main_x + main_w + G["md"]
        cv.rect(ix, y, inspector_w, content_h, "surface.panel", "border.subtle", TOKENS["radius"]["panel"])
        heading(cv, ix, y, inspector_w, "Detail kamera")
        cv.text(ix + G["lg"], y + 56, "Area produksi", "section")
        cv.text(ix + G["lg"], y + 84, "CAM-01 · konfigurasi contoh", "caption", "text.muted")
        fields = [("Stream", "Tanpa stream"), ("Waktu frame", "N/A"), ("Tracking", "Belum tersedia"),
                  ("Status zona", "Tidak diketahui"), ("Jumlah occupant", "N/A"), ("Coverage", "N/A"), ("Durasi sesi", "N/A")]
        fy = y + 124
        for label, value in fields:
            cv.text(ix + G["lg"], fy, label, "caption", "text.muted")
            cv.text(ix + G["lg"], fy + 24, value, color="text.primary")
            fy += 64
        cv.line(ix + G["lg"], fy, ix + inspector_w - G["lg"], fy)
        fy = cv.paragraph(ix + G["lg"], fy + G["lg"], "Track ID bersifat anonim. Presence tidak membuktikan hasil kerja.", inspector_w - G["xxl"], "body", "text.secondary")
        cv.paragraph(ix + G["lg"], fy + G["lg"], "Video: status penyimpanan belum tersedia dari engine.", inspector_w - G["xxl"], "caption", "text.muted")
    cv.save()


DRAFT_POINTS = [(0.18, 0.36), (0.39, 0.36), (0.42, 0.48), (0.36, 0.53), (0.17, 0.50)]


def polygon(canvas, points):
    raster = [(round(x * SCALE), round(y * SCALE)) for x, y in points]
    canvas.draw.polygon(raster, fill=C["surface.selected"])
    canvas.draw.line(raster + [raster[0]], fill=C["accent.default"], width=TOKENS["stroke"]["polygon"] * SCALE)
    coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    canvas.svg.append(f'<polygon points="{coords}" fill="{C["surface.selected"]}" stroke="{C["accent.default"]}" stroke-width="{TOKENS["stroke"]["polygon"]}"/>')


def diagram(canvas, x, y, w, h):
    canvas.rect(x, y, w, h, "surface.video", "border.subtle")
    canvas.rect(x + G["lg"], y + G["lg"], w - G["xxl"], h - G["xxl"], "surface.panel", "border.subtle")
    # Draft geometry is a real illustrative polygon, never detector evidence.
    points = [(x + u * w, y + v * h) for u, v in DRAFT_POINTS]
    polygon(canvas, points)
    for nx, ny in [(0.22, 0.25), (0.57, 0.25), (0.77, 0.25), (0.22, 0.56), (0.57, 0.56), (0.77, 0.56)]:
        dx, dy, dw, dh = x + nx * w, y + ny * h, .13 * w, .13 * h
        canvas.rect(dx, dy, dw, dh, "surface.raised", "border.control", TOKENS["radius"]["video"])
        canvas.rect(dx + dw * .3, dy + dh + G["sm"], dw * .4, dh * .32, "surface.raised", "border.subtle", TOKENS["radius"]["control"])
    canvas.text(x + G["lg"], y + G["xl"], "ILUSTRASI FRAME ACUAN · BUKAN CCTV", "caption", "text.secondary", max_width=w - G["xxl"])
    canvas.rect(x + .18 * w, y + .36 * h - 28, 116, 24, "surface.selected")
    canvas.text(x + .18 * w + G["sm"], y + .36 * h - 23, "Desk A01 · draft", "caption", "accent.default")
    for index, (px, py) in enumerate(points, 1):
        size = S["vertex_handle"]
        canvas.rect(px - size / 2, py - size / 2, size, size, "accent.default", "text.primary")
        canvas.text(px + G["sm"], py + G["sm"], str(index), "code", "text.primary")
    canvas.text(x + G["lg"], y + h - 28, "Polygon mencakup area occupant duduk.", "caption", "text.muted")


def form_field(canvas, x, y, w, label, value, disabled=False):
    canvas.text(x, y, label, "caption", "text.secondary")
    canvas.rect(x, y + 24, w, S["control"], "surface.raised", "border.subtle" if disabled else "border.control", TOKENS["radius"]["control"])
    canvas.text(x + G["sm"], y + 32, value, color="text.disabled" if disabled else "text.primary", max_width=w - G["lg"])


def editor(width, height):
    cv = Canvas(width, height, f"workspace-editor-{width}")
    side, compact = shell(cv, "Workstation", "Editor Workstation", "Geometri draft dipisahkan dari konfigurasi yang sudah diterapkan.")
    x = side + G["lg"]
    bottom = height - S["status_bar"] - G["lg"]
    y = 104
    prop_w = 272 if compact else 296
    left_w = 0 if compact else S["camera_rail"]
    if left_w:
        cv.rect(x, y, left_w, bottom - y, "surface.panel", "border.subtle", TOKENS["radius"]["panel"])
        heading(cv, x, y, left_w, "Workstation")
        cv.rect(x + G["xs"], y + 52, left_w - G["sm"], 72, "surface.selected", radius=TOKENS["radius"]["control"])
        cv.text(x + G["md"], y + 64, "Desk A01", "section")
        cv.text(x + G["md"], y + 92, "Draft belum disimpan", "caption", "status.warning")
        cv.paragraph(x + G["md"], y + 156, "Pilih satu kamera utama untuk perhitungan setiap zona.", left_w - G["xl"], "body", "text.secondary")
        cv.line(x + G["md"], bottom - 176, x + left_w - G["md"], bottom - 176)
        cv.paragraph(x + G["md"], bottom - 156, "Perubahan polygon membuat revisi baru. Histori memakai revisi asalnya.", left_w - G["xl"], "caption", "text.muted")
    mx = x + (left_w + G["md"] if left_w else 0)
    mw = width - G["lg"] - mx - prop_w - G["md"]
    px = mx + mw + G["md"]
    cv.rect(mx, y, mw, bottom - y, "surface.panel", "border.subtle", TOKENS["radius"]["panel"])
    heading(cv, mx, y, mw, "Frame acuan editor", "CAM-01 · contoh")
    cv.text(mx + G["md"], y + 52, "Polygon", "body", "accent.default")
    cv.text(mx + 88, y + 52, "Undo", "body", "text.secondary")
    cv.text(mx + 144, y + 52, "Redo", "body", "text.secondary")
    cv.text(mx + mw - G["md"], y + 52, "Frame belum tersedia", "caption", "status.warning", align="right")
    frame_x, frame_y = mx + G["md"], y + 84
    frame_w = mw - G["xl"]
    frame_h = min(frame_w * 9 / 16, (bottom - frame_y - 200))
    diagram_width = min(frame_w, frame_h * 16 / 9)
    cv.rect(frame_x, frame_y, frame_w, frame_h, "surface.video")
    diagram(cv, frame_x + (frame_w - diagram_width) / 2, frame_y, diagram_width, frame_h)
    table_y = frame_y + frame_h + G["lg"]
    cv.text(frame_x, table_y, "Vertex draft", "section")
    cv.text(frame_x + frame_w, table_y, "Koordinat normalized 0..1", "caption", "text.muted", align="right")
    cv.line(frame_x, table_y + 28, frame_x + frame_w, table_y + 28)
    cv.text(frame_x + G["sm"], table_y + 40, "Titik", "caption", "text.muted")
    cv.text(frame_x + 104, table_y + 40, "X", "caption", "text.muted")
    cv.text(frame_x + 184, table_y + 40, "Y", "caption", "text.muted")
    cv.text(frame_x + 280, table_y + 40, "Validasi", "caption", "text.muted")
    for i, (vx, vy) in enumerate(DRAFT_POINTS[:3] if compact else DRAFT_POINTS):
        ry = table_y + 64 + i * 24
        cv.text(frame_x + G["sm"], ry, str(i + 1), "code")
        cv.text(frame_x + 104, ry, f"{vx:.2f}", "code")
        cv.text(frame_x + 184, ry, f"{vy:.2f}", "code")
        cv.text(frame_x + 280, ry, "Dalam frame", "caption", "text.secondary")
    if compact:
        cv.text(frame_x + frame_w, table_y + 136, "5 titik total", "caption", "text.muted", align="right")
    cv.rect(px, y, prop_w, bottom - y, "surface.panel", "border.subtle", TOKENS["radius"]["panel"])
    heading(cv, px, y, prop_w, "Properti zona")
    fx, fw = px + G["lg"], prop_w - G["xxl"]
    fy = y + 52
    fields = [("Nama workstation", "Desk A01"), ("Jenis", "Desk"), ("Kapasitas", "1 occupant"),
              ("Kamera utama", "CAM-01 (contoh)"), ("Rule preset", "Belum dipilih")]
    for label, value in fields:
        form_field(cv, fx, fy, fw, label, value)
        fy += 72 if not compact else 64
    fy = cv.paragraph(fx, fy, "Geometri draft: valid, 5 titik. Frame acuan dan rule diperlukan sebelum simpan.", fw, "caption", "text.secondary")
    if not compact:
        cv.paragraph(fx, fy + G["lg"], "Revisi belum disimpan. Monitoring belum dimulai dari draft ini.", fw, "caption", "text.muted")
    cv.button(fx, bottom - 76, fw, "Simpan revisi", disabled=True)
    cv.text(fx, bottom - 32, "Ctrl+S · setelah draft lengkap", "caption", "text.muted", max_width=fw)
    cv.save()


def main():
    for width, height in (TOKENS["sizes"]["window_default"], TOKENS["sizes"]["window_minimum"]):
        live(width, height)
        editor(width, height)
    print("Rendered 4 static proposals (PNG + SVG). No Qt/CCTV runtime executed.")


if __name__ == "__main__":
    main()
