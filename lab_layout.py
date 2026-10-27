#!/usr/bin/env python3
"""Lab Layout Planner — Generic optical table layout tool."""

import sys
import os
import json
import math
import numpy as np
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QGraphicsScene, QGraphicsView,
    QGraphicsRectItem, QGraphicsPathItem, QGraphicsSimpleTextItem,
    QGraphicsLineItem, QToolBar, QAction, QFileDialog, QDialog,
    QFormLayout, QLineEdit, QDoubleSpinBox, QComboBox, QDialogButtonBox,
    QLabel, QStatusBar, QMenu, QMessageBox, QSpinBox, QHBoxLayout,
    QVBoxLayout, QWidget, QGroupBox, QListWidget, QListWidgetItem,
    QPushButton, QCheckBox, QProgressDialog, QRadioButton, QButtonGroup,
    QMenuBar, QSplitter, QColorDialog, QDockWidget, QUndoStack,
    QUndoCommand, QGraphicsTextItem
)
from PyQt5.QtCore import (
    Qt, QPointF, QRectF, QLineF, QThread, pyqtSignal, QSettings, QSize
)
from PyQt5.QtGui import (
    QPolygonF, QColor, QPen, QBrush, QPainter, QFont, QPainterPath,
    QImage, QPixmap, QPalette, QKeySequence
)

# ============================================================================
#  CONSTANTS
# ============================================================================

DEFAULT_COMPONENT_COLOR = "#4488CC"
MM_TO_INCH = 1.0 / 25.4

THEME_LIGHT = {
    "name": "light",
    "bg": "#FFFFFF", "grid": "#D0D0D0", "grid_major": "#B0B0B0",
    "table_fill": "#B8C8D8", "table_border": "#555555",
    "text": "#222222", "selection": "#0066FF",
    "ruler_bg": "#F0F0F0", "ruler_tick": "#333333",
    "panel_bg": "#F5F5F5", "panel_border": "#CCCCCC",
}
THEME_DARK = {
    "name": "dark",
    "bg": "#1E1E2E", "grid": "#333344", "grid_major": "#444466",
    "table_fill": "#3A4A5A", "table_border": "#8899AA",
    "text": "#DDDDDD", "selection": "#4499FF",
    "ruler_bg": "#2A2A3A", "ruler_tick": "#AAAACC",
    "panel_bg": "#252535", "panel_border": "#444466",
}

CURRENT_THEME = dict(THEME_LIGHT)

def get_theme():
    return CURRENT_THEME

def set_theme(theme_dict):
    CURRENT_THEME.clear()
    CURRENT_THEME.update(theme_dict)

# ============================================================================
#  DATA CLASSES
# ============================================================================

@dataclass
class TableData:
    name: str
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in ['name', 'x', 'y', 'width', 'height', 'rotation'] if k in d})


@dataclass
class ComponentData:
    name: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    locked: bool = False
    color: str = DEFAULT_COMPONENT_COLOR
    outline: list = None
    width: float = 0.0
    height: float = 0.0
    source_file: str = ""
    preview_png: str = ""
    z_order: float = 0.0

    def get_bounding_size(self):
        if self.outline:
            xs = [p[0] for p in self.outline]
            ys = [p[1] for p in self.outline]
            return max(xs) - min(xs), max(ys) - min(ys)
        return self.width, self.height

    def to_dict(self):
        d = {"name": self.name, "x": self.x, "y": self.y,
             "rotation": self.rotation, "locked": self.locked,
             "color": self.color}
        if self.outline:
            d["outline"] = self.outline
        if self.width:
            d["width"] = self.width
        if self.height:
            d["height"] = self.height
        if self.source_file:
            d["source_file"] = self.source_file
        if self.preview_png:
            d["preview_png"] = self.preview_png
        d["z_order"] = self.z_order
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"], x=d.get("x", 0), y=d.get("y", 0),
            rotation=d.get("rotation", 0), locked=d.get("locked", False),
            color=d.get("color", DEFAULT_COMPONENT_COLOR),
            outline=d.get("outline"), width=d.get("width", 0),
            height=d.get("height", 0), source_file=d.get("source_file", ""),
            preview_png=d.get("preview_png", ""),
            z_order=d.get("z_order", 0),
        )


# ============================================================================
#  STP PROJECTION ENGINE
#  Tessellates STEP files, projects front-facing triangles to 2D,
#  rasterizes to a binary image, and extracts the contour as a polygon.
# ============================================================================

RASTER_RES = 800  # pixels for contour extraction

def load_and_tessellate(file_path, tolerance=5.0):
    import cadquery as cq
    shape = cq.importers.importStep(file_path)
    vertices, triangles = shape.val().tessellate(tolerance)
    pts = np.array([[v.x, v.y, v.z] for v in vertices])
    tris = np.array(triangles)
    return pts, tris


def _project_plane(pts, tris, ax0, ax1, view_dir):
    """Get front-facing triangle vertices projected to a 2D plane."""
    v0 = pts[tris[:, 0]]; v1 = pts[tris[:, 1]]; v2 = pts[tris[:, 2]]
    normals = np.cross(v1 - v0, v2 - v0)
    dots = np.einsum('ij,j->i', normals, view_dir)
    front = tris[dots > 0]
    tri_verts_2d = pts[front][:, :, [ax0, ax1]]  # (N, 3, 2)
    all_2d = pts[:, [ax0, ax1]]
    xmin, ymin = all_2d.min(axis=0)
    xmax, ymax = all_2d.max(axis=0)
    return tri_verts_2d, (xmin, xmax, ymin, ymax)


def _rasterize_and_contour(tri_verts_2d, bounds, resolution=RASTER_RES):
    """Rasterize projected triangles to binary image, extract outer contour."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    import io

    xmin, xmax, ymin, ymax = bounds
    w = xmax - xmin
    h = ymax - ymin
    if w < 1e-6 or h < 1e-6:
        return [], 0, 0

    verts = tri_verts_2d
    if len(verts) > 200000:
        step = len(verts) // 200000
        verts = verts[::step]

    aspect = h / w
    res_x = resolution
    res_y = max(int(resolution * aspect), 10)

    fig, ax = plt.subplots(1, 1, figsize=(res_x / 100, res_y / 100), dpi=100)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect('equal')
    ax.axis('off')
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    pc = PolyCollection(verts, facecolors='white', edgecolors='none', alpha=1.0)
    ax.add_collection(pc)
    ax.set_facecolor('black')
    ax.set_rasterization_zorder(None)

    fig.canvas.draw()
    buf = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
    buf = buf.reshape(fig.canvas.get_width_height()[::-1] + (4,))
    gray = buf[:, :, 0]  # R channel: 255=shape, 0=background
    plt.close(fig)

    binary = (gray > 128).astype(np.uint8)

    # Extract contour: find boundary pixels
    padded = np.pad(binary, 1, mode='constant', constant_values=0)
    # Edge detection: pixel is boundary if it's 1 and any neighbor is 0
    shifts = [padded[:-2, 1:-1], padded[2:, 1:-1],
              padded[1:-1, :-2], padded[1:-1, 2:]]
    boundary = binary.copy()
    for s in shifts:
        boundary = boundary & (binary | (1 - s[:binary.shape[0], :binary.shape[1]]))
    boundary = binary & ~(
        padded[:-2, 1:-1] & padded[2:, 1:-1] &
        padded[1:-1, :-2] & padded[1:-1, 2:])

    ys_px, xs_px = np.where(boundary)
    if len(xs_px) == 0:
        return [], w, h

    # Convert pixel coords back to real coords
    img_h, img_w = binary.shape
    real_x = xmin + xs_px * w / img_w
    real_y = ymin + ys_px * h / img_h

    # Order the boundary points by angle from centroid
    cx, cy = real_x.mean(), real_y.mean()
    angles = np.arctan2(real_y - cy, real_x - cx)
    order = np.argsort(angles)
    contour = list(zip(real_x[order].tolist(), real_y[order].tolist()))

    # Subsample to manageable count
    if len(contour) > 300:
        step = len(contour) // 300
        contour = contour[::step]

    return contour, w, h


def _simplify_rdp(points, tolerance=0.5):
    """Douglas-Peucker polygon simplification."""
    if len(points) < 4:
        return points
    pts = [np.array(p) for p in points]

    def _rdp(pts, eps):
        if len(pts) < 3:
            return pts
        start, end = pts[0], pts[-1]
        line_vec = end - start
        line_len = np.linalg.norm(line_vec)
        if line_len < 1e-10:
            return [pts[0], pts[-1]]
        line_unit = line_vec / line_len
        dists = [np.linalg.norm((p - start) - np.dot(p - start, line_unit) * line_unit)
                 for p in pts[1:-1]]
        max_idx = np.argmax(dists)
        if dists[max_idx] > eps:
            left = _rdp(pts[:max_idx + 2], eps)
            right = _rdp(pts[max_idx + 1:], eps)
            return left[:-1] + right
        return [pts[0], pts[-1]]

    result = _rdp(pts, tolerance)
    return [p.tolist() for p in result] if len(result) >= 3 else [p.tolist() for p in pts]


def compute_projections(file_path, tolerance=5.0, units='mm'):
    """Compute filled-silhouette projections for XY, XZ, YZ planes."""
    pts, tris = load_and_tessellate(file_path, tolerance)
    scale = MM_TO_INCH if units == 'mm' else 1.0

    planes = {
        'XY': (0, 1, np.array([0, 0, 1])),
        'XZ': (0, 2, np.array([0, 1, 0])),
        'YZ': (1, 2, np.array([1, 0, 0])),
    }
    result = {}
    for name, (ax0, ax1, view_dir) in planes.items():
        tri_verts_2d, bounds = _project_plane(pts, tris, ax0, ax1, view_dir)
        contour, w_raw, h_raw = _rasterize_and_contour(tri_verts_2d, bounds)

        w = w_raw * scale
        h = h_raw * scale
        if contour:
            xmin = min(p[0] for p in contour)
            ymin = min(p[1] for p in contour)
            normalized = [[(p[0] - xmin) * scale, (p[1] - ymin) * scale]
                          for p in contour]
            normalized = _simplify_rdp(normalized, tolerance=0.3 * scale)
        else:
            normalized = []

        # Also store raw triangle data for preview rendering
        result[name] = {
            "outline": normalized, "width": w, "height": h,
            "_tri_verts": tri_verts_2d, "_bounds": bounds,
        }
    return result


class TessellateWorker(QThread):
    """Runs STP conversion in a subprocess, then loads the result."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, file_path, tolerance=5.0, units='mm'):
        super().__init__()
        self._file_path = file_path
        self._tolerance = tolerance
        self._units = units

    def run(self):
        try:
            self.progress.emit("Converting (this may take a minute)...")
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix='.comp.json', delete=False)
            tmp.close()
            _run_conversion_subprocess(
                self._file_path, tmp.name, self._tolerance, self._units)
            data = load_component_file(tmp.name)
            os.unlink(tmp.name)
            # Rebuild the dict format expected by ImportSTPDialog
            result = {}
            for plane, proj in data.get("projections", {}).items():
                result[plane] = {
                    "outline": proj["outline"],
                    "width": proj["width"],
                    "height": proj["height"],
                }
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ============================================================================
#  COMPONENT FILE (.comp.json) — preprocessed STP data for instant loading
# ============================================================================

def _render_preview_png(tri_verts_2d, bounds, max_px=800):
    """Render solid silhouette (outermost shape only) to a PNG byte string."""
    import io, base64
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import PolyCollection

        if len(tri_verts_2d) == 0:
            return ""
        xmin, xmax, ymin, ymax = bounds
        w, h = xmax - xmin, ymax - ymin
        if w < 1e-6 or h < 1e-6:
            return ""

        verts = tri_verts_2d
        if len(verts) > 300000:
            step = len(verts) // 300000
            verts = verts[::step]

        dpi = 150
        fig_w = max_px / dpi
        fig_h = fig_w * (h / w) if w > 0 else fig_w
        fig_h = max(0.3, min(fig_h, 12.0))

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax)
        ax.set_aspect('equal'); ax.axis('off')
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        # Solid opaque fill — edges same color as face to seal sub-pixel gaps
        pc = PolyCollection(verts, facecolors='#4488CC',
                            edgecolors='#4488CC', linewidths=0.5, alpha=1.0)
        ax.add_collection(pc)
        ax.set_facecolor('white')
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                    pad_inches=0.02, facecolor='white')
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return ""


def save_component_file(stp_path, output_path, tolerance=5.0, units='mm'):
    """Convert a STEP file into a .comp.json file with all 3 projections."""
    projections = compute_projections(stp_path, tolerance, units)
    name = os.path.splitext(os.path.basename(stp_path))[0]

    save_data = {
        "version": 1,
        "name": name,
        "source_file": os.path.basename(stp_path),
        "created": datetime.now().isoformat(),
        "projections": {}
    }
    for plane, data in projections.items():
        preview_b64 = ""
        if "_tri_verts" in data and "_bounds" in data:
            preview_b64 = _render_preview_png(data["_tri_verts"], data["_bounds"])
        save_data["projections"][plane] = {
            "outline": data["outline"],
            "width": round(data["width"], 2),
            "height": round(data["height"], 2),
            "preview_png": preview_b64,
        }

    with open(output_path, 'w') as f:
        json.dump(save_data, f, indent=2)
    return save_data


def load_component_file(path):
    """Load a .comp.json file. Returns the parsed dict."""
    with open(path) as f:
        return json.load(f)


def _run_conversion_subprocess(stp_path, output_path, tolerance=5.0, units='mm'):
    """Run STP conversion in a separate process (avoids matplotlib/Qt conflicts)."""
    import subprocess
    script = os.path.abspath(__file__)
    result = subprocess.run(
        [sys.executable, script, '--convert', stp_path, output_path,
         str(tolerance), units],
        capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Conversion failed")
    return output_path


class ConvertWorker(QThread):
    """Background worker for STP → .comp.json conversion (uses subprocess)."""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, stp_path, output_path, tolerance=5.0, units='mm'):
        super().__init__()
        self._stp = stp_path
        self._out = output_path
        self._tol = tolerance
        self._units = units

    def run(self):
        try:
            self.progress.emit("Converting in background process...")
            _run_conversion_subprocess(
                self._stp, self._out, self._tol, self._units)
            self.finished.emit(self._out)
        except Exception as e:
            self.error.emit(str(e))


# ============================================================================
#  UNDO COMMANDS
# ============================================================================

class MoveCommand(QUndoCommand):
    def __init__(self, item, old_pos, new_pos):
        super().__init__(f"Move {getattr(item, '_data', None) and item._data.name or 'item'}")
        self._item = item
        self._old = old_pos
        self._new = new_pos

    def redo(self):
        self._item.setPos(self._new)

    def undo(self):
        self._item.setPos(self._old)


class RotateCommand(QUndoCommand):
    def __init__(self, item, old_angle, new_angle):
        super().__init__(f"Rotate {item._data.name}")
        self._item = item
        self._old = old_angle
        self._new = new_angle

    def redo(self):
        self._item.setRotation(self._new)

    def undo(self):
        self._item.setRotation(self._old)


class AddItemCommand(QUndoCommand):
    def __init__(self, scene, item):
        super().__init__(f"Add {item._data.name}")
        self._scene = scene
        self._item = item

    def redo(self):
        self._scene.addItem(self._item)

    def undo(self):
        self._scene.removeItem(self._item)


class RemoveItemCommand(QUndoCommand):
    def __init__(self, scene, item):
        super().__init__(f"Remove {item._data.name}")
        self._scene = scene
        self._item = item

    def redo(self):
        self._scene.removeItem(self._item)

    def undo(self):
        self._scene.addItem(self._item)


# ============================================================================
#  GRAPHICS ITEMS
# ============================================================================

class TableItem(QGraphicsRectItem):
    def __init__(self, data: TableData):
        super().__init__(0, 0, data.width, data.height)
        self._data = data
        self._locked = True

        self.setPos(data.x, data.y)
        self.setRotation(data.rotation)
        self.setTransformOriginPoint(data.width / 2, data.height / 2)
        t = get_theme()
        self.setBrush(QBrush(QColor(t["table_fill"])))
        self.setPen(QPen(QColor(t["table_border"]), 1.5))
        self.setZValue(-50)
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self._label = QGraphicsSimpleTextItem("", self)
        self._label.setBrush(QBrush(QColor("#333333")))
        self._update_label()

    def _update_label(self):
        text = f'{self._data.name}\n{self._data.width:.0f}" x {self._data.height:.0f}"'
        self._label.setText(text)
        font = QFont("Arial", max(5, int(min(self._data.width, self._data.height) / 6)))
        self._label.setFont(font)
        br = self._label.boundingRect()
        self._label.setPos(
            (self._data.width - br.width()) / 2,
            (self._data.height - br.height()) / 2)

    def is_locked(self):
        return self._locked

    def set_locked(self, locked):
        self._locked = locked
        self.setFlag(self.ItemIsMovable, not locked)
        self.update()

    def get_data(self):
        pos = self.pos()
        self._data.x = pos.x()
        self._data.y = pos.y()
        self._data.rotation = self.rotation()
        return self._data

    def itemChange(self, change, value):
        if change == self.ItemPositionChange and self.scene():
            scene = self.scene()
            if hasattr(scene, 'grid_snap') and scene.grid_snap:
                g = scene.grid_size
                return QPointF(round(value.x() / g) * g, round(value.y() / g) * g)
        return super().itemChange(change, value)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self._locked:
            painter.setPen(QPen(QColor("#999999"), 1, Qt.DashLine))
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))
        if self.isSelected():
            painter.setPen(QPen(QColor("#0066FF"), 2))
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))

    def contextMenuEvent(self, event):
        menu = QMenu()
        lock_text = "Lock" if not self._locked else "Unlock"
        lock_act = menu.addAction(lock_text)
        menu.addSeparator()
        props = menu.addAction("Properties...")
        menu.addSeparator()
        delete = menu.addAction("Delete")
        action = menu.exec_(event.screenPos())
        if action == lock_act:
            self.set_locked(not self._locked)
        elif action == props:
            dlg = TablePropertiesDialog(self._data)
            if dlg.exec_() == QDialog.Accepted:
                self._data = dlg.get_data()
                self.setRect(0, 0, self._data.width, self._data.height)
                self.setPos(self._data.x, self._data.y)
                self.setRotation(self._data.rotation)
                self.setTransformOriginPoint(self._data.width / 2, self._data.height / 2)
                self._update_label()
        elif action == delete:
            self.scene().removeItem(self)


class DimensionItem(QGraphicsPathItem):
    """A smart-measure dimension annotation: ticks + line + centered label."""

    def __init__(self, p1, p2, offset=8):
        super().__init__()
        self._p1 = p1
        self._p2 = p2
        self.setZValue(1000)
        self.setFlag(self.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)

        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 0.01:
            dist = 0

        # Perpendicular offset direction
        if dist > 0:
            nx, ny = -dy / dist, dx / dist
        else:
            nx, ny = 0, -1
        ox, oy = nx * offset, ny * offset

        # Offset endpoints
        a = QPointF(p1.x() + ox, p1.y() + oy)
        b = QPointF(p2.x() + ox, p2.y() + oy)

        tick_len = 3
        path = QPainterPath()
        # Dimension line
        path.moveTo(a)
        path.lineTo(b)
        # Extension lines from original points to offset line
        path.moveTo(p1)
        path.lineTo(QPointF(a.x() + nx * tick_len, a.y() + ny * tick_len))
        path.moveTo(p2)
        path.lineTo(QPointF(b.x() + nx * tick_len, b.y() + ny * tick_len))
        # Tick marks at ends
        path.moveTo(QPointF(a.x() - nx * tick_len, a.y() - ny * tick_len))
        path.lineTo(QPointF(a.x() + nx * tick_len, a.y() + ny * tick_len))
        path.moveTo(QPointF(b.x() - nx * tick_len, b.y() - ny * tick_len))
        path.lineTo(QPointF(b.x() + nx * tick_len, b.y() + ny * tick_len))
        self.setPath(path)
        self.setPen(QPen(QColor("#CC3333"), 0.5))

        # Label
        if dist >= 12:
            text = f'{dist:.1f}" ({dist/12:.1f}\')'
        else:
            text = f'{dist:.2f}"'
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        self._label = QGraphicsSimpleTextItem(text, self)
        self._label.setFont(QFont("Arial", 4))
        self._label.setBrush(QBrush(QColor("#CC3333")))
        lbr = self._label.boundingRect()
        self._label.setPos(mid.x() - lbr.width() / 2 + nx * 3,
                           mid.y() - lbr.height() / 2 + ny * 3)

    def contextMenuEvent(self, event):
        menu = QMenu()
        delete = menu.addAction("Delete Measurement")
        action = menu.exec_(event.screenPos())
        if action == delete:
            self.scene().removeItem(self)

    def hoverEnterEvent(self, event):
        self.setPen(QPen(QColor("#FF0000"), 0.8))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setPen(QPen(QColor("#CC3333"), 0.5))
        super().hoverLeaveEvent(event)


class ComponentItem(QGraphicsPathItem):
    def __init__(self, data: ComponentData):
        super().__init__()
        self._data = data
        self._locked = data.locked
        self._colliding = False
        self._pixmap = None

        w, h = data.get_bounding_size()
        path = QPainterPath()
        path.addRect(0, 0, max(w, 1), max(h, 1))
        self.setPath(path)

        # Load preview image if available
        if data.preview_png:
            try:
                import base64
                img_data = base64.b64decode(data.preview_png)
                img = QImage()
                img.loadFromData(img_data)
                self._pixmap = QPixmap.fromImage(img)
                self._make_pixmap_transparent()
                if data.color and data.color != DEFAULT_COMPONENT_COLOR:
                    self._recolor_pixmap(QColor(data.color))
            except Exception:
                pass

        self.setPos(data.x, data.y)
        self.setRotation(data.rotation)
        br = path.boundingRect()
        self.setTransformOriginPoint(br.center())

        if not self._pixmap:
            color = QColor(data.color)
            color.setAlpha(180)
            self.setBrush(QBrush(color))
            self.setPen(QPen(QColor("#222222"), 1.2))
        else:
            self.setBrush(QBrush(Qt.transparent))
            self.setPen(QPen(Qt.transparent))
        if data.z_order:
            self.setZValue(data.z_order)
        else:
            ComponentItem._z_counter = getattr(ComponentItem, '_z_counter', 10) + 1
            self.setZValue(ComponentItem._z_counter)

        self.setFlag(self.ItemIsMovable, not self._locked)
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self._label = QGraphicsSimpleTextItem(data.name, self)
        self._label.setBrush(QBrush(QColor("#000000")))
        self._label.setFlag(QGraphicsSimpleTextItem.ItemIsMovable, True)
        self._label.setFlag(QGraphicsSimpleTextItem.ItemIsSelectable, False)
        self._label.setCursor(Qt.SizeAllCursor)
        self._label_visible = False
        self._label.setVisible(False)
        self._update_label()

    def shape(self):
        path = QPainterPath()
        path.addRect(self.path().boundingRect())
        return path

    def _update_label(self):
        br = self.path().boundingRect()
        w, h = br.width(), br.height()
        font_size = max(4, min(8, int(min(w, h) / 4)))
        self._label.setFont(QFont("Arial", font_size))
        lbr = self._label.boundingRect()
        self._label.setPos(
            br.x() + (w - lbr.width()) / 2,
            br.y() + (h - lbr.height()) / 2)

    def set_label_visible(self, visible):
        self._label_visible = visible
        self._label.setVisible(visible)

    def is_locked(self):
        return self._locked

    def set_locked(self, locked):
        self._locked = locked
        self._data.locked = locked
        self.setFlag(self.ItemIsMovable, not locked)
        self.update()

    def get_data(self):
        pos = self.pos()
        self._data.x = pos.x()
        self._data.y = pos.y()
        self._data.rotation = self.rotation()
        self._data.locked = self._locked
        self._data.z_order = self.zValue()
        return self._data

    def itemChange(self, change, value):
        if change == self.ItemPositionChange and self.scene():
            scene = self.scene()
            # Hold Shift to free-drag (bypass grid snap)
            mods = QApplication.keyboardModifiers()
            if (hasattr(scene, 'grid_snap') and scene.grid_snap
                    and not (mods & Qt.ShiftModifier)):
                g = scene.grid_size
                return QPointF(round(value.x() / g) * g, round(value.y() / g) * g)
        if change == self.ItemPositionHasChanged:
            self._check_collisions()
        return super().itemChange(change, value)

    def _check_collisions(self):
        colliders = [it for it in self.collidingItems(Qt.IntersectsItemBoundingRect)
                     if isinstance(it, ComponentItem)]
        new_state = len(colliders) > 0
        if new_state != self._colliding:
            self._colliding = new_state
            self.update()

    def paint(self, painter, option, widget=None):
        r = self.path().boundingRect()
        if self._pixmap:
            painter.drawPixmap(r.toRect(), self._pixmap)
        else:
            super().paint(painter, option, widget)
        # No bounding-rect borders — selection shown by corner handles only
        if self.isSelected():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#0066FF")))
            sz = max(1.5, min(r.width(), r.height()) * 0.04)
            for cx, cy in [(r.left(), r.top()), (r.right(), r.top()),
                           (r.left(), r.bottom()), (r.right(), r.bottom())]:
                painter.drawRect(QRectF(cx - sz, cy - sz, sz * 2, sz * 2))

    def contextMenuEvent(self, event):
        menu = QMenu()
        rot_cw = menu.addAction("Rotate 90° CW")
        rot_ccw = menu.addAction("Rotate 90° CCW")
        free_rot = menu.addAction("Free Rotate...")
        flip_h = menu.addAction("Flip Left/Right")
        flip_v = menu.addAction("Flip Up/Down")
        menu.addSeparator()
        color_act = menu.addAction("Change Color...")
        label_text = "Hide Label" if self._label_visible else "Show Label"
        label_act = menu.addAction(label_text)
        menu.addSeparator()
        order_menu = menu.addMenu("Order")
        bring_front = order_menu.addAction("Bring to Front")
        bring_fwd = order_menu.addAction("Bring Forward")
        send_bwd = order_menu.addAction("Send Backward")
        send_back = order_menu.addAction("Send to Back")
        menu.addSeparator()
        set_dist_act = menu.addAction("Set Distance... (click 2 edges)")
        menu.addSeparator()
        lock_text = "Lock" if not self._locked else "Unlock"
        lock_act = menu.addAction(lock_text)
        props = menu.addAction("Properties...")
        menu.addSeparator()
        delete = menu.addAction("Delete")

        action = menu.exec_(event.screenPos())
        if action == rot_cw:
            self.setRotation((self.rotation() + 90) % 360)
        elif action == rot_ccw:
            self.setRotation((self.rotation() - 90) % 360)
        elif action == free_rot:
            dlg = FreeRotateDialog(self.rotation())
            if dlg.exec_() == QDialog.Accepted:
                self.setRotation(dlg.get_angle())
        elif action == flip_h:
            self._flip('h')
        elif action == flip_v:
            self._flip('v')
        elif action == color_act:
            self._change_color()
        elif action == label_act:
            self.set_label_visible(not self._label_visible)
        elif action == bring_front:
            self._adjust_z_order('front')
        elif action == bring_fwd:
            self._adjust_z_order('forward')
        elif action == send_bwd:
            self._adjust_z_order('backward')
        elif action == send_back:
            self._adjust_z_order('back')
        elif action == set_dist_act:
            self._start_set_distance()
        elif action == lock_act:
            self.set_locked(not self._locked)
        elif action == props:
            self._show_properties()
        elif action == delete:
            self.scene().removeItem(self)

    def _start_set_distance(self):
        """Enter set-distance mode: click two edge points, then set the gap."""
        view = self.scene().views()[0] if self.scene().views() else None
        if view:
            view._set_distance_item = self
            view._set_distance_p1 = None
            view._set_distance_mode = True
            view.setCursor(Qt.CrossCursor)

    def _adjust_z_order(self, direction):
        components = [it for it in self.scene().items()
                      if isinstance(it, ComponentItem)]
        z_values = sorted(set(it.zValue() for it in components))
        cur = self.zValue()
        if direction == 'front':
            self.setZValue(max(z_values) + 1 if z_values else 11)
        elif direction == 'back':
            self.setZValue(min(z_values) - 1 if z_values else 9)
        elif direction == 'forward':
            above = [z for z in z_values if z > cur]
            self.setZValue(above[0] + 0.5 if above else cur + 1)
        elif direction == 'backward':
            below = [z for z in z_values if z < cur]
            self.setZValue(below[-1] - 0.5 if below else cur - 1)

    def _flip(self, axis):
        """Flip the component horizontally or vertically."""
        br = self.path().boundingRect()
        cx, cy = br.center().x(), br.center().y()

        if self._pixmap:
            if axis == 'h':
                self._pixmap = QPixmap.fromImage(
                    self._pixmap.toImage().mirrored(True, False))
            else:
                self._pixmap = QPixmap.fromImage(
                    self._pixmap.toImage().mirrored(False, True))
        else:
            # Mirror the path
            t = QTransform()
            if axis == 'h':
                t.translate(2 * cx, 0)
                t.scale(-1, 1)
            else:
                t.translate(0, 2 * cy)
                t.scale(1, -1)
            self.setPath(t.map(self.path()))
            self.setTransformOriginPoint(self.path().boundingRect().center())
        self.update()

    def _change_color(self):
        c = QColorDialog.getColor(QColor(self._data.color), None, "Component Color")
        if c.isValid():
            self._data.color = c.name()
            if self._pixmap:
                self._recolor_pixmap(c)
            else:
                color = QColor(c)
                color.setAlpha(180)
                self.setBrush(QBrush(color))
                self.setPen(QPen(QColor("#222222"), 1.2))
            self.update()

    def _recolor_pixmap(self, color):
        """Recolor only the visible (non-transparent) shape pixels."""
        src = self._pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        c = QColor(color)
        for y in range(src.height()):
            for x in range(src.width()):
                px = src.pixelColor(x, y)
                if px.alpha() < 10:
                    continue
                lum = (px.red() + px.green() + px.blue()) / (3 * 255.0)
                r = min(255, int(c.red() * lum * 1.2))
                g = min(255, int(c.green() * lum * 1.2))
                b = min(255, int(c.blue() * lum * 1.2))
                src.setPixelColor(x, y, QColor(r, g, b, px.alpha()))
        self._pixmap = QPixmap.fromImage(src)

    def _make_pixmap_transparent(self, color=None):
        """Make white background transparent on initial load."""
        src = self._pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        for y in range(src.height()):
            for x in range(src.width()):
                px = src.pixelColor(x, y)
                if px.red() > 240 and px.green() > 240 and px.blue() > 240:
                    src.setPixelColor(x, y, QColor(0, 0, 0, 0))
        self._pixmap = QPixmap.fromImage(src)

    def _show_properties(self):
        dlg = ComponentPropertiesDialog(self.get_data())
        if dlg.exec_() == QDialog.Accepted:
            new = dlg.get_data()
            self._data = new
            self.setPos(new.x, new.y)
            self.setRotation(new.rotation)
            self.set_locked(new.locked)
            if not self._pixmap:
                color = QColor(new.color)
                color.setAlpha(180)
                self.setBrush(QBrush(color))
            self._label.setText(new.name)
            self._update_label()

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self._drag_start_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)
        if (hasattr(self, '_drag_start_pos') and self._drag_start_pos
                and self._drag_start_pos != self.pos()):
            scene = self.scene()
            if scene and hasattr(scene, 'undo_stack'):
                scene.undo_stack.push(
                    MoveCommand(self, self._drag_start_pos, self.pos()))
            self._drag_start_pos = None
        super().mouseReleaseEvent(event)


# ============================================================================
#  DIALOGS
# ============================================================================

class TablePropertiesDialog(QDialog):
    def __init__(self, data: TableData, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Table Properties")
        layout = QFormLayout(self)
        self._name = QLineEdit(data.name)
        layout.addRow("Name:", self._name)
        self._x = QDoubleSpinBox(); self._x.setRange(-5000, 5000); self._x.setSuffix('"'); self._x.setValue(data.x)
        layout.addRow("X:", self._x)
        self._y = QDoubleSpinBox(); self._y.setRange(-5000, 5000); self._y.setSuffix('"'); self._y.setValue(data.y)
        layout.addRow("Y:", self._y)
        self._w = QDoubleSpinBox(); self._w.setRange(1, 600); self._w.setSuffix('"'); self._w.setValue(data.width)
        layout.addRow("Width:", self._w)
        self._h = QDoubleSpinBox(); self._h.setRange(1, 600); self._h.setSuffix('"'); self._h.setValue(data.height)
        layout.addRow("Height:", self._h)
        self._rot = QDoubleSpinBox(); self._rot.setRange(0, 360); self._rot.setValue(data.rotation)
        layout.addRow("Rotation:", self._rot)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        return TableData(self._name.text(), self._x.value(), self._y.value(),
                         self._w.value(), self._h.value(), self._rot.value())


class FreeRotateDialog(QDialog):
    def __init__(self, current_angle=0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Free Rotate")
        layout = QFormLayout(self)
        self._angle = QDoubleSpinBox()
        self._angle.setRange(0, 360)
        self._angle.setDecimals(1)
        self._angle.setSingleStep(1)
        self._angle.setSuffix("°")
        self._angle.setValue(current_angle % 360)
        layout.addRow("Angle:", self._angle)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_angle(self):
        return self._angle.value()


class ComponentPropertiesDialog(QDialog):
    def __init__(self, data: ComponentData, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Component Properties")
        self._data = data
        layout = QFormLayout(self)
        self._name = QLineEdit(data.name)
        layout.addRow("Name:", self._name)
        self._x = QDoubleSpinBox(); self._x.setRange(-5000, 5000); self._x.setSuffix('"'); self._x.setValue(data.x)
        layout.addRow("X:", self._x)
        self._y = QDoubleSpinBox(); self._y.setRange(-5000, 5000); self._y.setSuffix('"'); self._y.setValue(data.y)
        layout.addRow("Y:", self._y)
        self._rot = QDoubleSpinBox(); self._rot.setRange(0, 360); self._rot.setDecimals(1); self._rot.setValue(data.rotation)
        layout.addRow("Rotation:", self._rot)
        self._locked = QCheckBox(); self._locked.setChecked(data.locked)
        layout.addRow("Locked:", self._locked)
        w, h = data.get_bounding_size()
        layout.addRow("Size:", QLabel(f'{w:.1f}" x {h:.1f}"'))
        if data.source_file:
            layout.addRow("Source:", QLabel(data.source_file))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        d = ComponentData(
            name=self._name.text(), x=self._x.value(), y=self._y.value(),
            rotation=self._rot.value(), locked=self._locked.isChecked(),
            color=self._data.color, outline=self._data.outline,
            width=self._data.width, height=self._data.height,
            source_file=self._data.source_file,
            preview_png=self._data.preview_png,
            z_order=self._data.z_order)
        return d


class AddManualDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Component (Manual)")
        self.setMinimumWidth(300)
        layout = QFormLayout(self)
        self._name = QLineEdit()
        self._name.setPlaceholderText("e.g. Laser Box")
        layout.addRow("Name:", self._name)
        self._w = QDoubleSpinBox(); self._w.setRange(1, 600); self._w.setValue(24); self._w.setSuffix('"')
        layout.addRow("Width:", self._w)
        self._h = QDoubleSpinBox(); self._h.setRange(1, 600); self._h.setValue(36); self._h.setSuffix('"')
        layout.addRow("Height:", self._h)
        self._color_btn = QPushButton(DEFAULT_COMPONENT_COLOR)
        self._color_btn.setStyleSheet(f"background-color: {DEFAULT_COMPONENT_COLOR}")
        self._color_btn.clicked.connect(self._pick_color)
        self._color = DEFAULT_COMPONENT_COLOR
        layout.addRow("Color:", self._color_btn)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self)
        if c.isValid():
            self._color = c.name()
            self._color_btn.setText(self._color)
            self._color_btn.setStyleSheet(f"background-color: {self._color}")

    def get_data(self):
        return ComponentData(
            name=self._name.text().strip() or "Component",
            width=self._w.value(), height=self._h.value(),
            color=self._color)


class ProjectionPreviewWidget(QWidget):
    """Draws a filled-silhouette preview for one projection plane."""
    def __init__(self, plane_name, proj_data=None, parent=None):
        super().__init__(parent)
        self._plane = plane_name
        self._data = proj_data  # dict with outline, width, height, _tri_verts, _bounds
        self._pixmap = None
        self.setMinimumSize(200, 200)
        if proj_data and "_tri_verts" in proj_data:
            self._render_pixmap()

    def _render_pixmap(self):
        """Pre-render the filled triangles to a QPixmap for fast painting."""
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import PolyCollection
        from PyQt5.QtGui import QImage, QPixmap
        import io

        d = self._data
        tri_verts = d.get("_tri_verts")
        bounds = d.get("_bounds")
        if tri_verts is None or bounds is None or len(tri_verts) == 0:
            return

        xmin, xmax, ymin, ymax = bounds
        w, h = xmax - xmin, ymax - ymin
        if w < 1e-6 or h < 1e-6:
            return

        dpi = 100
        fig_w = 3.0
        fig_h = fig_w * (h / w) if w > 0 else fig_w
        fig_h = max(0.5, min(fig_h, 6.0))

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_aspect('equal')
        ax.axis('off')
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        pc = PolyCollection(tri_verts, facecolors='#4488CC',
                            edgecolors='none', alpha=0.9)
        ax.add_collection(pc)
        ax.set_facecolor('#F5F5F5')

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                    pad_inches=0.05, facecolor='#F5F5F5')
        plt.close(fig)
        buf.seek(0)

        img = QImage()
        img.loadFromData(buf.read())
        self._pixmap = QPixmap.fromImage(img)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F5F5F5"))

        d = self._data
        w_in = d["width"] if d else 0
        h_in = d["height"] if d else 0

        # Title
        painter.setPen(QPen(QColor("#333333")))
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(QRectF(0, 2, self.width(), 18), Qt.AlignHCenter,
                         f'{self._plane} view')

        if self._pixmap:
            margin = 22
            avail = QRectF(4, margin, self.width() - 8,
                           self.height() - margin - 20)
            pm = self._pixmap.scaled(
                int(avail.width()), int(avail.height()),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = avail.x() + (avail.width() - pm.width()) / 2
            y = avail.y() + (avail.height() - pm.height()) / 2
            painter.drawPixmap(int(x), int(y), pm)
        elif d:
            painter.drawText(self.rect(), Qt.AlignCenter, "No data")

        # Dimensions
        painter.setFont(QFont("Arial", 9))
        painter.drawText(QRectF(0, self.height() - 18, self.width(), 16),
                         Qt.AlignHCenter, f'{w_in:.1f}" x {h_in:.1f}"')
        painter.end()


class ImportSTPDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import STEP File")
        self.setMinimumWidth(650)
        self._file_path = file_path
        self._projections = None
        self._worker = None
        self._previews = {}

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(QLabel(f"File: {os.path.basename(file_path)}"))

        # Settings row
        settings = QHBoxLayout()
        settings.addWidget(QLabel("Tolerance:"))
        self._tolerance = QDoubleSpinBox()
        self._tolerance.setRange(0.1, 10.0)
        self._tolerance.setValue(1.0)
        self._tolerance.setSingleStep(0.5)
        settings.addWidget(self._tolerance)
        settings.addWidget(QLabel("Units:"))
        self._units = QComboBox()
        self._units.addItems(["mm", "inches"])
        settings.addWidget(self._units)
        retess_btn = QPushButton("Re-tessellate")
        retess_btn.clicked.connect(self._start_tessellation)
        settings.addWidget(retess_btn)
        settings.addStretch()
        main_layout.addLayout(settings)

        # Preview panels
        self._preview_container = QHBoxLayout()
        self._radio_group = QButtonGroup(self)
        for i, plane in enumerate(['XY', 'XZ', 'YZ']):
            col = QVBoxLayout()
            radio = QRadioButton(f"{plane}")
            if i == 0:
                radio.setChecked(True)
            self._radio_group.addButton(radio, i)
            col.addWidget(radio)
            pw = ProjectionPreviewWidget(plane,
                                         {"outline": [], "width": 0, "height": 0})
            self._previews[plane] = pw
            col.addWidget(pw)
            self._preview_container.addLayout(col)
        main_layout.addLayout(self._preview_container)

        # Name and color
        name_layout = QFormLayout()
        self._name = QLineEdit(os.path.splitext(os.path.basename(file_path))[0])
        name_layout.addRow("Name:", self._name)
        self._color_btn = QPushButton(DEFAULT_COMPONENT_COLOR)
        self._color_btn.setStyleSheet(f"background-color: {DEFAULT_COMPONENT_COLOR}")
        self._color_btn.clicked.connect(self._pick_color)
        self._comp_color = DEFAULT_COMPONENT_COLOR
        name_layout.addRow("Color:", self._color_btn)
        main_layout.addLayout(name_layout)

        self._status_label = QLabel("Starting tessellation...")
        main_layout.addWidget(self._status_label)

        self._btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._btns.button(QDialogButtonBox.Ok).setEnabled(False)
        self._btns.accepted.connect(self.accept)
        self._btns.rejected.connect(self._cancel)
        main_layout.addWidget(self._btns)

        self._start_tessellation()

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._comp_color), self)
        if c.isValid():
            self._comp_color = c.name()
            self._color_btn.setText(self._comp_color)
            self._color_btn.setStyleSheet(f"background-color: {self._comp_color}")

    def _start_tessellation(self):
        self._btns.button(QDialogButtonBox.Ok).setEnabled(False)
        self._status_label.setText("Tessellating... (this may take a moment)")
        units = self._units.currentText()
        self._worker = TessellateWorker(
            self._file_path, self._tolerance.value(), units)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(
            lambda msg: self._status_label.setText(msg))
        self._worker.start()

    def _on_finished(self, projections):
        self._projections = projections
        for plane, data in projections.items():
            pw = self._previews[plane]
            new_pw = ProjectionPreviewWidget(plane, data)
            new_pw.setMinimumSize(200, 200)
            for i in range(self._preview_container.count()):
                col = self._preview_container.itemAt(i).layout()
                if col:
                    for j in range(col.count()):
                        item = col.itemAt(j)
                        if item and item.widget() == pw:
                            col.removeWidget(pw)
                            pw.deleteLater()
                            col.addWidget(new_pw)
                            self._previews[plane] = new_pw
                            break

        self._status_label.setText("Ready — select a projection view")
        self._btns.button(QDialogButtonBox.Ok).setEnabled(True)

    def _on_error(self, msg):
        self._status_label.setText(f"Error: {msg}")

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait()
        self.reject()

    def get_data(self):
        if not self._projections:
            return None
        planes = ['XY', 'XZ', 'YZ']
        selected = planes[self._radio_group.checkedId()]
        proj = self._projections[selected]
        outline = proj["outline"]
        if not outline or len(outline) < 3:
            w, h = proj["width"], proj["height"]
            return ComponentData(
                name=self._name.text().strip() or "Imported",
                width=w, height=h,
                source_file=os.path.basename(self._file_path),
                color=self._comp_color)
        return ComponentData(
            name=self._name.text().strip() or "Imported",
            outline=outline,
            source_file=os.path.basename(self._file_path),
            color=self._comp_color)


class LoadComponentDialog(QDialog):
    """Load a preprocessed .comp.json file, show 3 preview images, pick a view."""
    def __init__(self, comp_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Component")
        self.setMinimumWidth(700)
        self._comp_data = comp_data
        self._projections = comp_data.get("projections", {})

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(QLabel(
            f"Component: {comp_data.get('name', '?')}   "
            f"(from {comp_data.get('source_file', '?')})"))

        # 3 preview panels with radio buttons
        preview_row = QHBoxLayout()
        self._radio_group = QButtonGroup(self)
        for i, plane in enumerate(['XY', 'XZ', 'YZ']):
            col = QVBoxLayout()
            radio = QRadioButton(plane)
            if i == 0:
                radio.setChecked(True)
            self._radio_group.addButton(radio, i)
            col.addWidget(radio)

            proj = self._projections.get(plane, {})
            # Render preview from base64 PNG
            preview = QLabel()
            preview.setMinimumSize(200, 200)
            preview.setAlignment(Qt.AlignCenter)
            preview.setStyleSheet("background-color: #F5F5F5; border: 1px solid #CCC;")
            b64 = proj.get("preview_png", "")
            if b64:
                import base64
                from PyQt5.QtGui import QPixmap, QImage
                img_data = base64.b64decode(b64)
                img = QImage()
                img.loadFromData(img_data)
                pm = QPixmap.fromImage(img).scaled(
                    200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                preview.setPixmap(pm)
            else:
                preview.setText("No preview")
            col.addWidget(preview)

            w = proj.get("width", 0)
            h = proj.get("height", 0)
            col.addWidget(QLabel(f'{w:.1f}" x {h:.1f}"'))
            preview_row.addLayout(col)
        main_layout.addLayout(preview_row)

        # Name and color
        form = QFormLayout()
        self._name = QLineEdit(comp_data.get("display_name",
                               comp_data.get("name", "Component")))
        form.addRow("Name:", self._name)
        self._color_btn = QPushButton(DEFAULT_COMPONENT_COLOR)
        self._color_btn.setStyleSheet(f"background-color: {DEFAULT_COMPONENT_COLOR}")
        self._color_btn.clicked.connect(self._pick_color)
        self._comp_color = DEFAULT_COMPONENT_COLOR
        form.addRow("Color:", self._color_btn)
        main_layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        main_layout.addWidget(btns)

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._comp_color), self)
        if c.isValid():
            self._comp_color = c.name()
            self._color_btn.setText(self._comp_color)
            self._color_btn.setStyleSheet(f"background-color: {self._comp_color}")

    def get_data(self):
        planes = ['XY', 'XZ', 'YZ']
        selected = planes[self._radio_group.checkedId()]
        proj = self._projections.get(selected, {})
        name = self._name.text().strip() or "Component"
        src = self._comp_data.get("source_file", "")
        preview = proj.get("preview_png", "")
        w = proj.get("width", 24)
        h = proj.get("height", 36)
        return ComponentData(
            name=name, width=w, height=h,
            source_file=src, color=self._comp_color,
            preview_png=preview)


class TableSetupDialog(QDialog):
    def __init__(self, existing_tables=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Table Setup")
        self.setMinimumSize(600, 450)
        self._tables = []
        if existing_tables:
            self._tables = [TableData(**asdict(t)) for t in existing_tables]

        main = QHBoxLayout(self)

        # Left: list + buttons
        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_select)
        left.addWidget(self._list)
        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_table)
        dup_btn = QPushButton("Duplicate")
        dup_btn.clicked.connect(self._dup_table)
        rm_btn = QPushButton("Remove")
        rm_btn.clicked.connect(self._remove_table)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(dup_btn)
        btn_row.addWidget(rm_btn)
        left.addLayout(btn_row)

        # Template load/save
        tmpl_row = QHBoxLayout()
        load_tmpl = QPushButton("Load Template")
        load_tmpl.clicked.connect(self._load_template)
        save_tmpl = QPushButton("Save Template")
        save_tmpl.clicked.connect(self._save_template)
        tmpl_row.addWidget(load_tmpl)
        tmpl_row.addWidget(save_tmpl)
        left.addLayout(tmpl_row)
        main.addLayout(left, 1)

        # Right: edit fields
        right = QVBoxLayout()
        edit_group = QGroupBox("Table Properties")
        form = QFormLayout()
        self._e_name = QLineEdit()
        self._e_name.textChanged.connect(self._on_edit)
        form.addRow("Name:", self._e_name)
        self._e_x = QDoubleSpinBox(); self._e_x.setRange(-5000, 5000); self._e_x.setSuffix('"')
        self._e_x.valueChanged.connect(self._on_edit)
        form.addRow("X:", self._e_x)
        self._e_y = QDoubleSpinBox(); self._e_y.setRange(-5000, 5000); self._e_y.setSuffix('"')
        self._e_y.valueChanged.connect(self._on_edit)
        form.addRow("Y:", self._e_y)
        self._e_w = QDoubleSpinBox(); self._e_w.setRange(1, 600); self._e_w.setSuffix('"')
        self._e_w.valueChanged.connect(self._on_edit)
        form.addRow("Width:", self._e_w)
        self._e_h = QDoubleSpinBox(); self._e_h.setRange(1, 600); self._e_h.setSuffix('"')
        self._e_h.valueChanged.connect(self._on_edit)
        form.addRow("Height:", self._e_h)
        self._e_rot = QDoubleSpinBox(); self._e_rot.setRange(0, 360)
        self._e_rot.valueChanged.connect(self._on_edit)
        form.addRow("Rotation:", self._e_rot)
        edit_group.setLayout(form)
        right.addWidget(edit_group)

        # Preview
        self._preview = QGraphicsView()
        self._preview_scene = QGraphicsScene()
        self._preview.setScene(self._preview_scene)
        self._preview.setRenderHint(QPainter.Antialiasing)
        right.addWidget(self._preview, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        right.addWidget(btns)
        main.addLayout(right, 2)

        self._updating = False
        self._refresh_list()
        self._update_preview()

    def _refresh_list(self):
        self._list.clear()
        for t in self._tables:
            self._list.addItem(f'{t.name} ({t.width:.0f}" x {t.height:.0f}")')

    def _on_select(self, row):
        if row < 0 or row >= len(self._tables):
            return
        self._updating = True
        t = self._tables[row]
        self._e_name.setText(t.name)
        self._e_x.setValue(t.x)
        self._e_y.setValue(t.y)
        self._e_w.setValue(t.width)
        self._e_h.setValue(t.height)
        self._e_rot.setValue(t.rotation)
        self._updating = False

    def _on_edit(self):
        if self._updating:
            return
        row = self._list.currentRow()
        if row < 0 or row >= len(self._tables):
            return
        t = self._tables[row]
        t.name = self._e_name.text()
        t.x = self._e_x.value()
        t.y = self._e_y.value()
        t.width = self._e_w.value()
        t.height = self._e_h.value()
        t.rotation = self._e_rot.value()
        self._list.item(row).setText(f'{t.name} ({t.width:.0f}" x {t.height:.0f}")')
        self._update_preview()

    def _add_table(self):
        n = len(self._tables) + 1
        t = TableData(f"Table {n}", 0, 0, 48, 96)
        self._tables.append(t)
        self._refresh_list()
        self._list.setCurrentRow(len(self._tables) - 1)
        self._update_preview()

    def _dup_table(self):
        row = self._list.currentRow()
        if row < 0:
            return
        src = self._tables[row]
        t = TableData(src.name + " copy", src.x + 20, src.y + 20,
                      src.width, src.height, src.rotation)
        self._tables.append(t)
        self._refresh_list()
        self._list.setCurrentRow(len(self._tables) - 1)
        self._update_preview()

    def _remove_table(self):
        row = self._list.currentRow()
        if row < 0:
            return
        self._tables.pop(row)
        self._refresh_list()
        self._update_preview()

    def _update_preview(self):
        self._preview_scene.clear()
        for t in self._tables:
            rect = QGraphicsRectItem(0, 0, t.width, t.height)
            rect.setPos(t.x, t.y)
            rect.setRotation(t.rotation)
            rect.setTransformOriginPoint(t.width / 2, t.height / 2)
            rect.setBrush(QBrush(QColor(TABLE_COLOR)))
            rect.setPen(QPen(QColor(TABLE_BORDER), 1))
            self._preview_scene.addItem(rect)
            label = QGraphicsSimpleTextItem(t.name)
            label.setParentItem(rect)
            font = QFont("Arial", 6)
            label.setFont(font)
            br = label.boundingRect()
            label.setPos((t.width - br.width()) / 2, (t.height - br.height()) / 2)
        if self._tables:
            self._preview.fitInView(
                self._preview_scene.sceneRect().adjusted(-20, -20, 20, 20),
                Qt.KeepAspectRatio)

    def _load_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Table Template", "", "Table Template (*.tbl.json)")
        if not path:
            return
        with open(path) as f:
            data = json.load(f)
        self._tables = [TableData.from_dict(t) for t in data.get("tables", [])]
        self._refresh_list()
        self._update_preview()

    def _save_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Table Template", "tables.tbl.json",
            "Table Template (*.tbl.json)")
        if not path:
            return
        data = {"version": 1, "tables": [asdict(t) for t in self._tables]}
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    def get_tables(self):
        return self._tables


# ============================================================================
#  SCENE & VIEW
# ============================================================================

# ============================================================================
#  COMPONENT LIBRARY PANEL
# ============================================================================

class ComponentLibraryPanel(QDockWidget):
    component_requested = pyqtSignal(str)  # emits file path

    # Default library path relative to this script
    DEFAULT_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Library")

    def __init__(self, parent=None):
        super().__init__("Component Library", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._lib_dir = ""

        from PyQt5.QtWidgets import QTreeWidget, QTreeWidgetItem, QHeaderView

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        dir_row = QHBoxLayout()
        self._dir_label = QLabel("No directory set")
        self._dir_label.setWordWrap(True)
        dir_row.addWidget(self._dir_label, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._scan)
        btn_row.addWidget(refresh_btn)
        add_cat_btn = QPushButton("+ Category")
        add_cat_btn.setToolTip("Add a new category")
        add_cat_btn.clicked.connect(self._add_category)
        btn_row.addWidget(add_cat_btn)
        layout.addLayout(btn_row)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Size"])
        self._tree.setColumnWidth(0, 150)
        self._tree.header().setStretchLastSection(True)
        self._tree.setDragDropMode(QTreeWidget.InternalMove)
        self._tree.setDefaultDropAction(Qt.MoveAction)
        self._tree.model().rowsInserted.connect(self._on_tree_drop)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tree)

        self.setWidget(container)
        self.setMinimumWidth(220)

    def set_directory(self, path):
        self._lib_dir = path
        self._dir_label.setText(os.path.basename(path) or path)
        self._scan()

    def get_directory(self):
        return self._lib_dir

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Component Library Directory")
        if d:
            self.set_directory(d)

    def _scan(self):
        from PyQt5.QtWidgets import QTreeWidgetItem
        from PyQt5.QtGui import QIcon
        import base64

        self._scanning = True
        self._tree.clear()
        if not self._lib_dir or not os.path.isdir(self._lib_dir):
            return

        # Collect all .comp.json files and their categories
        components = []
        for f in sorted(os.listdir(self._lib_dir)):
            if not f.endswith('.comp.json'):
                continue
            fpath = os.path.join(self._lib_dir, f)
            try:
                with open(fpath) as fp:
                    data = json.load(fp)
                components.append((fpath, data))
            except Exception:
                pass

        # Group by category
        categories = {}
        for fpath, data in components:
            cat = data.get("category", "Uncategorized")
            categories.setdefault(cat, []).append((fpath, data))

        # Load persistent empty categories from .categories file
        cat_file = os.path.join(self._lib_dir, ".categories.json")
        if os.path.exists(cat_file):
            try:
                with open(cat_file) as fp:
                    saved_cats = json.load(fp)
                for c in saved_cats:
                    if c not in categories:
                        categories[c] = []
            except Exception:
                pass

        # Sync .categories.json with all categories found in files
        all_cat_names = set(categories.keys())
        cat_file = os.path.join(self._lib_dir, ".categories.json")
        try:
            with open(cat_file, 'w') as f:
                json.dump(sorted(c for c in all_cat_names if c != "Uncategorized"), f, indent=2)
        except Exception:
            pass

        # Build tree
        for cat_name in sorted(categories.keys()):
            cat_item = QTreeWidgetItem([cat_name, ""])
            cat_item.setFlags(cat_item.flags() | Qt.ItemIsDropEnabled)
            font = cat_item.font(0)
            font.setBold(True)
            cat_item.setFont(0, font)
            self._tree.addTopLevelItem(cat_item)

            for fpath, data in categories[cat_name]:
                # Use filename (without .comp.json) as display name
                display_name = os.path.basename(fpath).replace('.comp.json', '')
                projs = data.get("projections", {})
                size_str = ""
                for plane in ["XY", "XZ", "YZ"]:
                    p = projs.get(plane, {})
                    if p.get("width"):
                        size_str = f'{p["width"]:.0f}" x {p["height"]:.0f}"'
                        break

                child = QTreeWidgetItem([display_name, size_str])
                child.setData(0, Qt.UserRole, fpath)
                child.setData(0, Qt.UserRole + 1, data.get("category", "Uncategorized"))
                child.setToolTip(0, display_name)
                child.setFlags(child.flags() | Qt.ItemIsDragEnabled)
                cat_item.addChild(child)
            cat_item.setExpanded(True)
        self._scanning = False

    def _on_tree_drop(self, parent, first, last):
        """When an item is dragged to a new category, save the change to disk."""
        if getattr(self, '_scanning', False):
            return
        parent_item = self._tree.itemFromIndex(parent)
        if not parent_item:
            return
        if parent_item.data(0, Qt.UserRole):
            return
        new_cat = parent_item.text(0)
        changed = False
        for row in range(first, last + 1):
            child = parent_item.child(row)
            if child:
                fpath = child.data(0, Qt.UserRole)
                if fpath:
                    try:
                        with open(fpath) as f:
                            data = json.load(f)
                        data["category"] = new_cat
                        with open(fpath, 'w') as f:
                            json.dump(data, f, indent=2)
                        self._save_category(new_cat)
                        changed = True
                    except Exception:
                        pass

    def _on_double_click(self, item, column):
        path = item.data(0, Qt.UserRole)
        if path:
            self.component_requested.emit(path)

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        menu = QMenu()

        if item and item.data(0, Qt.UserRole):
            # Component item
            fpath = item.data(0, Qt.UserRole)
            load_act = menu.addAction("Load this Component")
            info_act = menu.addAction("Show Info...")
            menu.addSeparator()

            # Move to category submenu
            move_menu = menu.addMenu("Move to Category...")
            cat_actions = {}
            for i in range(self._tree.topLevelItemCount()):
                cat_item = self._tree.topLevelItem(i)
                cat_name = cat_item.text(0)
                act = move_menu.addAction(cat_name)
                cat_actions[act] = cat_name

            menu.addSeparator()
            rename_act = menu.addAction("Rename File...")
            delete_act = menu.addAction("Remove from Library")

            action = menu.exec_(self._tree.viewport().mapToGlobal(pos))
            if action == load_act:
                self.component_requested.emit(fpath)
            elif action == info_act:
                self._show_info(fpath)
            elif action in cat_actions:
                self._set_category(fpath, cat_actions[action])
            elif action == rename_act:
                self._rename_file(fpath)
            elif action == delete_act:
                self._delete_component(fpath)

        elif item and not item.data(0, Qt.UserRole):
            # Category header
            cat_name = item.text(0)
            rename_act = menu.addAction("Rename Category...")
            delete_act = menu.addAction("Delete Category")
            action = menu.exec_(self._tree.viewport().mapToGlobal(pos))
            if action == rename_act:
                self._rename_category(cat_name)
            elif action == delete_act:
                self._delete_category(cat_name)
        else:
            add_act = menu.addAction("Add Category...")
            action = menu.exec_(self._tree.viewport().mapToGlobal(pos))
            if action == add_act:
                self._add_category()

    def _set_category(self, fpath, new_cat):
        try:
            with open(fpath) as f:
                data = json.load(f)
            data["category"] = new_cat
            with open(fpath, 'w') as f:
                json.dump(data, f, indent=2)
            self._save_category(new_cat)
            self._scan()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

    def _show_info(self, fpath):
        """Show detailed info with preview thumbnails for all 3 projections."""
        try:
            with open(fpath) as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            return

        import base64

        fname = os.path.basename(fpath).replace('.comp.json', '')
        internal_name = data.get("name", "?")
        source = data.get("source_file", "?")
        created = data.get("created", "?")
        category = data.get("category", "Uncategorized")
        fsize = os.path.getsize(fpath)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Info: {fname}")
        dlg.setMinimumWidth(550)
        layout = QVBoxLayout(dlg)

        # Text info
        info = QLabel(
            f"<b>File:</b> {fname}.comp.json<br>"
            f"<b>Internal name:</b> {internal_name}<br>"
            f"<b>Source STP:</b> {source}<br>"
            f"<b>Category:</b> {category}<br>"
            f"<b>Created:</b> {created}<br>"
            f"<b>File size:</b> {fsize / 1024:.0f} KB")
        info.setTextFormat(Qt.RichText)
        layout.addWidget(info)

        # Preview images for all 3 projections
        projs = data.get("projections", {})
        preview_row = QHBoxLayout()
        for plane in ["XY", "XZ", "YZ"]:
            p = projs.get(plane, {})
            w = p.get("width", 0)
            h = p.get("height", 0)
            col = QVBoxLayout()
            col.addWidget(QLabel(f"<b>{plane}</b> — {w:.1f}\" x {h:.1f}\""))

            img_label = QLabel()
            img_label.setFixedSize(160, 160)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setStyleSheet("background: #F5F5F5; border: 1px solid #CCC;")
            b64 = p.get("preview_png", "")
            if b64:
                try:
                    img = QImage()
                    img.loadFromData(base64.b64decode(b64))
                    pm = QPixmap.fromImage(img).scaled(
                        156, 156, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    img_label.setPixmap(pm)
                except Exception:
                    img_label.setText("No preview")
            else:
                img_label.setText("No preview")
            col.addWidget(img_label)
            preview_row.addLayout(col)
        layout.addLayout(preview_row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec_()

    def _rename_file(self, fpath):
        """Rename the .comp.json file on disk."""
        from PyQt5.QtWidgets import QInputDialog
        old_name = os.path.basename(fpath).replace('.comp.json', '')
        new_name, ok = QInputDialog.getText(self, "Rename File",
                                            "New filename:", text=old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            new_path = os.path.join(os.path.dirname(fpath),
                                    f"{new_name.strip()}.comp.json")
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Error",
                                    f'"{new_name.strip()}.comp.json" already exists.')
                return
            os.rename(fpath, new_path)
            self._scan()

    def _delete_component(self, fpath):
        reply = QMessageBox.question(self, "Remove",
                                     f"Remove {os.path.basename(fpath)} from library?")
        if reply == QMessageBox.Yes:
            os.remove(fpath)
            self._scan()

    def _add_category(self):
        from PyQt5.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if ok and name.strip():
            self._save_category(name.strip())
            self._scan()

    def _save_category(self, name):
        """Add a category to the persistent .categories.json file."""
        cat_file = os.path.join(self._lib_dir, ".categories.json")
        cats = []
        if os.path.exists(cat_file):
            try:
                with open(cat_file) as f:
                    cats = json.load(f)
            except Exception:
                pass
        if name not in cats:
            cats.append(name)
            with open(cat_file, 'w') as f:
                json.dump(sorted(cats), f, indent=2)

    def _rename_category(self, old_name):
        from PyQt5.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(self, "Rename Category",
                                            "New name:", text=old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            for f in os.listdir(self._lib_dir):
                if not f.endswith('.comp.json'):
                    continue
                fpath = os.path.join(self._lib_dir, f)
                try:
                    with open(fpath) as fp:
                        data = json.load(fp)
                    if data.get("category") == old_name:
                        data["category"] = new_name.strip()
                        with open(fpath, 'w') as fp:
                            json.dump(data, fp, indent=2)
                except Exception:
                    pass
            self._scan()

    def _delete_category(self, cat_name):
        reply = QMessageBox.question(self, "Delete Category",
                                     f'Move all items in "{cat_name}" to Uncategorized?')
        if reply == QMessageBox.Yes:
            for f in os.listdir(self._lib_dir):
                if not f.endswith('.comp.json'):
                    continue
                fpath = os.path.join(self._lib_dir, f)
                try:
                    with open(fpath) as fp:
                        data = json.load(fp)
                    if data.get("category") == cat_name:
                        data["category"] = "Uncategorized"
                        with open(fpath, 'w') as fp:
                            json.dump(data, fp, indent=2)
                except Exception:
                    pass
            # Remove from .categories.json
            cat_file = os.path.join(self._lib_dir, ".categories.json")
            if os.path.exists(cat_file):
                try:
                    with open(cat_file) as f:
                        cats = json.load(f)
                    cats = [c for c in cats if c != cat_name]
                    with open(cat_file, 'w') as f:
                        json.dump(cats, f, indent=2)
                except Exception:
                    pass
            self._scan()


# ============================================================================
#  LAYER ORDER PANEL
# ============================================================================

class LayerPanel(QDockWidget):
    """Panel to view and reorder component z-order via drag or buttons."""

    def __init__(self, scene, parent=None):
        super().__init__("Layer Order", parent)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self._scene = scene

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        self._list = QListWidget()
        self._list.setDragDropMode(QListWidget.InternalMove)
        self._list.model().rowsMoved.connect(self._on_reorder)
        self._list.currentRowChanged.connect(self._on_select)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        up_btn = QPushButton("Up")
        up_btn.setToolTip("Move selected layer up (forward)")
        up_btn.clicked.connect(lambda: self._move(-1))
        down_btn = QPushButton("Down")
        down_btn.setToolTip("Move selected layer down (backward)")
        down_btn.clicked.connect(lambda: self._move(1))
        top_btn = QPushButton("Top")
        top_btn.setToolTip("Bring to front")
        top_btn.clicked.connect(lambda: self._move_to('top'))
        bot_btn = QPushButton("Bottom")
        bot_btn.setToolTip("Send to back")
        bot_btn.clicked.connect(lambda: self._move_to('bottom'))
        btn_row.addWidget(top_btn)
        btn_row.addWidget(up_btn)
        btn_row.addWidget(down_btn)
        btn_row.addWidget(bot_btn)
        layout.addLayout(btn_row)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)

        self.setWidget(container)
        self.setMinimumWidth(180)

    def refresh(self):
        self._list.blockSignals(True)
        self._list.clear()
        components = [it for it in self._scene.items()
                      if isinstance(it, ComponentItem)]
        # Sort by z-value descending (top layer first in list)
        components.sort(key=lambda it: it.zValue(), reverse=True)
        for comp in components:
            name = comp._data.name
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, id(comp))
            self._list.addItem(item)
        self._list.blockSignals(False)

    def _find_component(self, obj_id):
        for it in self._scene.items():
            if isinstance(it, ComponentItem) and id(it) == obj_id:
                return it
        return None

    def _on_select(self, row):
        if row < 0:
            return
        item = self._list.item(row)
        if not item:
            return
        comp = self._find_component(item.data(Qt.UserRole))
        if comp:
            self._scene.clearSelection()
            comp.setSelected(True)

    def _on_reorder(self):
        # Assign z-values based on list order (top of list = highest z)
        count = self._list.count()
        for i in range(count):
            item = self._list.item(i)
            comp = self._find_component(item.data(Qt.UserRole))
            if comp:
                comp.setZValue(count - i + 10)
        self.refresh()

    def _move(self, direction):
        row = self._list.currentRow()
        if row < 0:
            return
        new_row = row + direction
        if new_row < 0 or new_row >= self._list.count():
            return
        # Swap z-values
        item_a = self._list.item(row)
        item_b = self._list.item(new_row)
        comp_a = self._find_component(item_a.data(Qt.UserRole))
        comp_b = self._find_component(item_b.data(Qt.UserRole))
        if comp_a and comp_b:
            za, zb = comp_a.zValue(), comp_b.zValue()
            comp_a.setZValue(zb)
            comp_b.setZValue(za)
        self.refresh()
        self._list.setCurrentRow(new_row)

    def _move_to(self, where):
        row = self._list.currentRow()
        if row < 0:
            return
        item = self._list.item(row)
        comp = self._find_component(item.data(Qt.UserRole))
        if not comp:
            return
        components = [it for it in self._scene.items()
                      if isinstance(it, ComponentItem)]
        z_vals = [it.zValue() for it in components]
        if where == 'top':
            comp.setZValue(max(z_vals) + 1)
        else:
            comp.setZValue(min(z_vals) - 1)
        self.refresh()
        self._list.setCurrentRow(0 if where == 'top' else self._list.count() - 1)


# ============================================================================
#  RULER WIDGET
# ============================================================================

class RulerWidget(QWidget):
    """Ruler drawn along the top or left edge, synced with the graphics view."""
    HORIZONTAL = 0
    VERTICAL = 1

    def __init__(self, orientation, parent=None):
        super().__init__(parent)
        self._orientation = orientation
        self._view = None
        self._cursor_pos = 0
        if orientation == self.HORIZONTAL:
            self.setFixedHeight(24)
        else:
            self.setFixedWidth(30)

    def set_view(self, view):
        self._view = view

    def set_cursor_scene_pos(self, pos):
        if self._orientation == self.HORIZONTAL:
            self._cursor_pos = pos.x()
        else:
            self._cursor_pos = pos.y()
        self.update()

    def paintEvent(self, event):
        if not self._view:
            return
        painter = QPainter(self)
        t = get_theme()
        painter.fillRect(self.rect(), QColor(t["ruler_bg"]))
        painter.setPen(QPen(QColor(t["ruler_tick"])))

        transform = self._view.transform()
        scale = transform.m11()
        if scale < 0.001:
            painter.end()
            return

        # Determine tick spacing (in inches)
        target_px = 50
        real_inches = target_px / scale
        nice = [0.5, 1, 2, 3, 6, 12, 24, 48, 96, 120, 240]
        tick_in = min(nice, key=lambda v: abs(v - real_inches))
        tick_px = tick_in * scale

        if self._orientation == self.HORIZONTAL:
            tl = self._view.mapToScene(0, 0)
            br = self._view.mapToScene(self._view.viewport().width(), 0)
            start = math.floor(tl.x() / tick_in) * tick_in
            end = math.ceil(br.x() / tick_in) * tick_in
            val = start
            while val <= end:
                vp = self._view.mapFromScene(QPointF(val, 0))
                x = vp.x()
                painter.drawLine(int(x), 16, int(x), 24)
                if tick_in >= 12:
                    label = f"{val / 12:.0f}'"
                elif tick_in >= 1:
                    label = f'{val:.0f}"'
                else:
                    label = f'{val:.1f}"'
                painter.setFont(QFont("Arial", 7))
                painter.drawText(int(x) + 2, 13, label)
                val += tick_in
            # Cursor marker
            vp = self._view.mapFromScene(QPointF(self._cursor_pos, 0))
            painter.setPen(QPen(QColor(t["selection"]), 1))
            painter.drawLine(int(vp.x()), 0, int(vp.x()), 24)
        else:
            tl = self._view.mapToScene(0, 0)
            br = self._view.mapToScene(0, self._view.viewport().height())
            start = math.floor(tl.y() / tick_in) * tick_in
            end = math.ceil(br.y() / tick_in) * tick_in
            val = start
            while val <= end:
                vp = self._view.mapFromScene(QPointF(0, val))
                y = vp.y()
                painter.drawLine(22, int(y), 30, int(y))
                if tick_in >= 12:
                    label = f"{val / 12:.0f}'"
                elif tick_in >= 1:
                    label = f'{val:.0f}"'
                else:
                    label = f'{val:.1f}"'
                painter.setFont(QFont("Arial", 7))
                painter.drawText(1, int(y) + 10, label)
                val += tick_in
            vp = self._view.mapFromScene(QPointF(0, self._cursor_pos))
            painter.setPen(QPen(QColor(t["selection"]), 1))
            painter.drawLine(0, int(vp.y()), 30, int(vp.y()))
        painter.end()


# ============================================================================
#  SCENE & VIEW
# ============================================================================

class LabScene(QGraphicsScene):
    def __init__(self):
        super().__init__()
        self._base_scene_rect = QRectF(-1000, -1000, 2000, 2000)
        self.setSceneRect(self._base_scene_rect)
        self.grid_snap = True
        self.grid_size = 6.0
        self.grid_visible = True
        self.undo_stack = QUndoStack()
        self.undo_stack.setUndoLimit(100)

    def update_scene_rect(self):
        """Set scene rect to 9x the bounding rect of all items."""
        items = [it for it in self.items()
                 if isinstance(it, (TableItem, ComponentItem))]
        if not items:
            self.setSceneRect(-1000, -1000, 2000, 2000)
            return
        r = items[0].sceneBoundingRect()
        for it in items[1:]:
            r = r.united(it.sceneBoundingRect())
        # 9x = 3x each dimension, centered
        w, h = r.width(), r.height()
        cx, cy = r.center().x(), r.center().y()
        self.setSceneRect(cx - w * 1.5, cy - h * 1.5, w * 3, h * 3)

    def add_table(self, data: TableData):
        item = TableItem(data)
        self.addItem(item)
        self.update_scene_rect()
        return item

    def add_component(self, data: ComponentData):
        item = ComponentItem(data)
        self.addItem(item)
        self.update_scene_rect()
        return item

    def get_all_tables(self):
        return [it.get_data() for it in self.items() if isinstance(it, TableItem)]

    def get_all_components(self):
        return [it.get_data() for it in self.items() if isinstance(it, ComponentItem)]

    def clear_tables(self):
        for it in list(self.items()):
            if isinstance(it, TableItem):
                self.removeItem(it)
        self.update_scene_rect()

    def clear_components(self):
        for it in list(self.items()):
            if isinstance(it, ComponentItem):
                self.removeItem(it)
        self.update_scene_rect()

    def clear_all(self):
        self.clear()
        self.update_scene_rect()


class LabView(QGraphicsView):
    cursor_moved = pyqtSignal(QPointF)

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setMinimumSize(800, 600)
        self._zoom_level = 1.0
        self._panning = False
        self._space_pan = False
        self._pan_mode = False  # toolbar pan mode toggle
        self._measure_mode = False
        self._measure_start = None
        self._measure_preview = None
        self._set_distance_mode = False
        self._set_distance_item = None
        self._set_distance_p1 = None
        self._clipboard = []
        self.setMouseTracking(True)
        # Mac: enable trackpad gestures
        self.viewport().setAttribute(Qt.WA_AcceptTouchEvents, True)

    def wheelEvent(self, event):
        mods = event.modifiers()
        angle = event.angleDelta()

        # Ctrl+scroll = zoom (Mac pinch-to-zoom also sends Ctrl+scroll)
        if mods & Qt.ControlModifier:
            self._do_zoom(angle.y(), event.pos())
            event.accept()
            return

        # Alt+scroll = free rotate selected component
        if mods & Qt.AltModifier:
            sel = [it for it in self.scene().selectedItems()
                   if isinstance(it, ComponentItem)]
            if sel:
                delta = 5 if angle.y() > 0 else -5
                for it in sel:
                    it.setRotation(it.rotation() + delta)
                event.accept()
                return

        # Plain scroll = zoom at mouse position (mouse wheel and trackpad)
        if angle.y() != 0:
            self._do_zoom(angle.y(), event.pos())
            event.accept()
            return

        # Horizontal scroll (trackpad two-finger horizontal swipe) = pan
        if angle.x() != 0:
            hs = self.horizontalScrollBar()
            hs.setValue(hs.value() - angle.x())
            event.accept()
            return

        event.accept()

    def _do_zoom(self, delta, viewport_pos=None):
        step = min(max(abs(delta), 1), 120) / 120.0
        factor = 1.0 + 0.05 * step * (1 if delta > 0 else -1)
        new_zoom = self._zoom_level * factor
        if not (0.05 < new_zoom < 50):
            return

        if viewport_pos:
            # Zoom centered on mouse: remember scene point under cursor,
            # scale, then scroll so that same scene point stays under cursor
            scene_pos = self.mapToScene(viewport_pos.toPoint()
                                        if hasattr(viewport_pos, 'toPoint')
                                        else viewport_pos)
            self.scale(factor, factor)
            new_vp = self.mapFromScene(scene_pos)
            delta_vp = new_vp - viewport_pos
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            hs.setValue(int(hs.value() + delta_vp.x()))
            vs.setValue(int(vs.value() + delta_vp.y()))
        else:
            self.scale(factor, factor)

        self._zoom_level = new_zoom

    def zoom_in(self):
        vp_center = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        self._do_zoom(120, vp_center)

    def zoom_out(self):
        vp_center = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        self._do_zoom(-120, vp_center)

    def set_pan_mode(self, on):
        self._pan_mode = on
        if on:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        else:
            self.setDragMode(QGraphicsView.RubberBandDrag)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            if not self._pan_mode:
                self.setDragMode(QGraphicsView.NoDrag)
                self.setDragMode(QGraphicsView.RubberBandDrag)
            return
        super().mouseReleaseEvent(event)

    def set_measure_mode(self, on):
        self._measure_mode = on
        if on:
            self.setCursor(Qt.CrossCursor)
            self._measure_start = None
        else:
            self.unsetCursor()
            self._clear_preview()

    def _clear_preview(self):
        if self._measure_preview and self._measure_preview.scene():
            self.scene().removeItem(self._measure_preview)
        self._measure_preview = None

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.pos())
        self.cursor_moved.emit(pos)
        if self._measure_mode and self._measure_start is not None:
            self._clear_preview()
            pen = QPen(QColor("#CC3333"), 0.3, Qt.DashLine)
            self._measure_preview = self.scene().addLine(
                QLineF(self._measure_start, pos), pen)
            self._measure_preview.setZValue(999)
        if self._set_distance_mode and self._set_distance_p1 is not None:
            self._clear_preview()
            pen = QPen(QColor("#22AA44"), 0.3, Qt.DashLine)
            self._measure_preview = self.scene().addLine(
                QLineF(self._set_distance_p1, pos), pen)
            self._measure_preview.setZValue(999)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        # Ctrl+click = right-click (Mac trackpad friendly)
        if (event.button() == Qt.LeftButton
                and event.modifiers() & Qt.ControlModifier
                and not self._measure_mode and not self._set_distance_mode):
            fake = event.__class__(
                event.type(), event.localPos(), Qt.RightButton,
                Qt.RightButton, Qt.NoModifier)
            super().mousePressEvent(fake)
            return
        if event.button() == Qt.MiddleButton or self._space_pan or self._pan_mode:
            self._panning = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            fake = event.__class__(
                event.type(), event.localPos(), Qt.LeftButton,
                Qt.LeftButton, event.modifiers())
            super().mousePressEvent(fake)
            return
        # Left-click on empty area = pan canvas
        if (event.button() == Qt.LeftButton
                and not self._measure_mode and not self._set_distance_mode):
            # Check if clicking on a real component or table (not labels, dimensions, etc.)
            items = self.items(event.pos())
            has_draggable = any(isinstance(it, (ComponentItem, TableItem))
                                for it in items)
            if not has_draggable:
                self._panning = True
                self._was_drag_mode = self.dragMode()
                self.setDragMode(QGraphicsView.ScrollHandDrag)
                fake = event.__class__(
                    event.type(), event.localPos(), Qt.LeftButton,
                    Qt.LeftButton, event.modifiers())
                super().mousePressEvent(fake)
                return
        if self._measure_mode and event.button() == Qt.LeftButton:
            pos = self.mapToScene(event.pos())
            if self._measure_start is None:
                self._measure_start = pos
                self._clear_preview()
            else:
                self._clear_preview()
                dim = DimensionItem(self._measure_start, pos)
                self.scene().addItem(dim)
                self._measure_start = None
            return
        if self._set_distance_mode and event.button() == Qt.LeftButton:
            pos = self.mapToScene(event.pos())
            if self._set_distance_p1 is None:
                self._set_distance_p1 = pos
            else:
                self._finish_set_distance(pos)
            return
        super().mousePressEvent(event)

    def _finish_set_distance(self, p2):
        """Show dialog to set the distance between the two clicked points."""
        p1 = self._set_distance_p1
        item = self._set_distance_item
        self._set_distance_mode = False
        self._set_distance_p1 = None
        self.unsetCursor()

        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        dist_h = abs(dx)
        dist_v = abs(dy)
        dist_total = math.sqrt(dx * dx + dy * dy)

        dlg = QDialog()
        dlg.setWindowTitle("Set Distance")
        dlg.setMinimumWidth(350)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f'Point 1: ({p1.x():.1f}", {p1.y():.1f}")\n'
            f'Point 2: ({p2.x():.1f}", {p2.y():.1f}")\n'
            f'Current: H={dist_h:.1f}"  V={dist_v:.1f}"  Total={dist_total:.1f}"'))

        form = QFormLayout()
        axis_combo = QComboBox()
        axis_combo.addItem(f'Horizontal gap ({dist_h:.1f}")', 'H')
        axis_combo.addItem(f'Vertical gap ({dist_v:.1f}")', 'V')
        axis_combo.addItem(f'Direct distance ({dist_total:.1f}")', 'D')
        form.addRow("Set:", axis_combo)

        dist_spin = QDoubleSpinBox()
        dist_spin.setRange(0, 5000)
        dist_spin.setDecimals(1)
        dist_spin.setSuffix('"')
        # Default to the larger gap
        dist_spin.setValue(dist_h if dist_h >= dist_v else dist_v)
        if dist_h >= dist_v:
            axis_combo.setCurrentIndex(0)
        else:
            axis_combo.setCurrentIndex(1)
        form.addRow("New distance:", dist_spin)
        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_() != QDialog.Accepted or not item:
            return

        new_dist = dist_spin.value()
        axis = axis_combo.currentData()
        old_pos = item.pos()
        new_pos = QPointF(old_pos)

        if axis == 'H':
            shift = new_dist - dist_h
            if dx >= 0:
                new_pos.setX(old_pos.x() - shift)
            else:
                new_pos.setX(old_pos.x() + shift)
        elif axis == 'V':
            shift = new_dist - dist_v
            if dy >= 0:
                new_pos.setY(old_pos.y() - shift)
            else:
                new_pos.setY(old_pos.y() + shift)
        elif axis == 'D' and dist_total > 0:
            scale = new_dist / dist_total
            new_pos.setX(old_pos.x() - dx * (scale - 1))
            new_pos.setY(old_pos.y() - dy * (scale - 1))

        item.setPos(new_pos)
        scene = self.scene()
        if hasattr(scene, 'undo_stack'):
            scene.undo_stack.push(MoveCommand(item, old_pos, new_pos))

    def keyPressEvent(self, event):
        scene = self.scene()
        sel = [it for it in scene.selectedItems()
               if isinstance(it, ComponentItem)]
        mods = event.modifiers()
        key = event.key()

        # Escape: cancel active mode or deselect
        if key == Qt.Key_Escape:
            if self._set_distance_mode:
                self._set_distance_mode = False
                self._set_distance_p1 = None
                self._clear_preview()
                self.unsetCursor()
            elif self._measure_mode:
                self.set_measure_mode(False)
            else:
                scene.clearSelection()
            return

        # R / Shift+R: rotate 90
        if key == Qt.Key_R and sel and not (mods & Qt.ControlModifier):
            angle = -90 if mods & Qt.ShiftModifier else 90
            for it in sel:
                old = it.rotation()
                new = (old + angle) % 360
                if hasattr(scene, 'undo_stack'):
                    scene.undo_stack.push(RotateCommand(it, old, new))
                else:
                    it.setRotation(new)
            return

        # L: lock/unlock
        if key == Qt.Key_L and sel:
            for it in sel:
                it.set_locked(not it.is_locked())
            return

        # M: toggle measurement mode
        if key == Qt.Key_M and not (mods & Qt.ControlModifier):
            self.set_measure_mode(not self._measure_mode)
            return

        # Delete/Backspace: remove selected
        if key in (Qt.Key_Delete, Qt.Key_Backspace) and sel:
            for it in sel:
                if hasattr(scene, 'undo_stack'):
                    scene.undo_stack.push(RemoveItemCommand(scene, it))
                else:
                    scene.removeItem(it)
            return

        # Arrow keys: nudge selected
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and sel:
            step = 1 if mods & Qt.ShiftModifier else scene.grid_size
            dx, dy = 0, 0
            if key == Qt.Key_Left: dx = -step
            elif key == Qt.Key_Right: dx = step
            elif key == Qt.Key_Up: dy = -step
            elif key == Qt.Key_Down: dy = step
            for it in sel:
                old = it.pos()
                new = QPointF(old.x() + dx, old.y() + dy)
                if hasattr(scene, 'undo_stack'):
                    scene.undo_stack.push(MoveCommand(it, old, new))
                else:
                    it.setPos(new)
            return

        # Ctrl+A: select all components
        if key == Qt.Key_A and mods & Qt.ControlModifier:
            for it in scene.items():
                if isinstance(it, ComponentItem):
                    it.setSelected(True)
            return

        # Ctrl+D: duplicate selected
        if key == Qt.Key_D and mods & Qt.ControlModifier and sel:
            for it in sel:
                data = it.get_data()
                import copy
                new_data = ComponentData.from_dict(data.to_dict())
                new_data.preview_png = data.preview_png
                new_data.x += 12
                new_data.y += 12
                new_item = ComponentItem(new_data)
                if hasattr(scene, 'undo_stack'):
                    scene.undo_stack.push(AddItemCommand(scene, new_item))
                else:
                    scene.addItem(new_item)
            return

        # Ctrl+C: copy
        if key == Qt.Key_C and mods & Qt.ControlModifier and sel:
            self._clipboard = [it.get_data().to_dict() for it in sel]
            # Also store preview_png separately
            self._clipboard_previews = [it._data.preview_png for it in sel]
            return

        # Ctrl+V: paste
        if key == Qt.Key_V and mods & Qt.ControlModifier and self._clipboard:
            center = self.mapToScene(self.viewport().rect().center())
            for i, d in enumerate(self._clipboard):
                new_data = ComponentData.from_dict(d)
                if hasattr(self, '_clipboard_previews') and i < len(self._clipboard_previews):
                    new_data.preview_png = self._clipboard_previews[i]
                new_data.x = center.x() + i * 12
                new_data.y = center.y() + i * 12
                new_item = ComponentItem(new_data)
                if hasattr(scene, 'undo_stack'):
                    scene.undo_stack.push(AddItemCommand(scene, new_item))
                else:
                    scene.addItem(new_item)
            return

        # Space: pan mode
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pan = True
            self.setCursor(Qt.OpenHandCursor)
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pan = False
            if not self._measure_mode:
                self.unsetCursor()
            if self._panning:
                self._panning = False
                self.setDragMode(QGraphicsView.RubberBandDrag)
        super().keyReleaseEvent(event)

    def zoom_to_fit(self):
        sr = self.scene().sceneRect()
        if sr.isEmpty():
            return
        self.fitInView(sr.adjusted(-30, -30, 30, 30), Qt.KeepAspectRatio)
        self._zoom_level = self.transform().m11()

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        scene = self.scene()
        if not (hasattr(scene, 'grid_visible') and scene.grid_visible):
            return
        grid = scene.grid_size
        t = get_theme()
        pen = QPen(QColor(t["grid"]), 0)
        painter.setPen(pen)
        left = int(math.floor(rect.left() / grid) * grid)
        top = int(math.floor(rect.top() / grid) * grid)
        right = int(math.ceil(rect.right() / grid) * grid)
        bottom = int(math.ceil(rect.bottom() / grid) * grid)
        for x in range(left, right + 1, int(grid)):
            painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
        for y in range(top, bottom + 1, int(grid)):
            painter.drawLine(QLineF(rect.left(), y, rect.right(), y))

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        vp = self.viewport().rect()
        painter.resetTransform()
        view_scale = self.transform().m11()
        target_px = 100
        real_inches = target_px / view_scale if view_scale > 0 else 12
        nice = [1, 2, 3, 6, 12, 24, 36, 48, 60, 72, 96, 120, 144, 180, 240]
        bar_in = min(nice, key=lambda v: abs(v - real_inches))
        bar_px = int(bar_in * view_scale)
        x0 = vp.right() - bar_px - 20
        y0 = vp.bottom() - 30
        painter.setPen(QPen(QColor("#333333"), 2))
        painter.drawLine(x0, y0, x0 + bar_px, y0)
        painter.drawLine(x0, y0 - 4, x0, y0 + 4)
        painter.drawLine(x0 + bar_px, y0 - 4, x0 + bar_px, y0 + 4)
        label = f"{bar_in / 12:.0f} ft" if bar_in >= 12 else f'{bar_in}"'
        painter.setFont(QFont("Arial", 9))
        painter.drawText(x0, y0 - 8, bar_px, 20, Qt.AlignHCenter, label)


# ============================================================================
#  MAIN WINDOW
# ============================================================================

class LabLayoutApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lab Layout Planner — Untitled")
        self.resize(1200, 800)
        self._current_file = None
        self._modified = False
        self._settings = QSettings("SLAC", "LabLayoutPlanner")

        self._scene = LabScene()
        self._view = LabView(self._scene)

        # Rulers + view in a grid layout
        central = QWidget()
        grid = QVBoxLayout(central)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self._h_ruler = RulerWidget(RulerWidget.HORIZONTAL)
        self._h_ruler.set_view(self._view)
        h_row = QHBoxLayout()
        h_row.setSpacing(0)
        h_row.addSpacing(30)  # offset for vertical ruler width
        h_row.addWidget(self._h_ruler)
        grid.addLayout(h_row)
        view_row = QHBoxLayout()
        view_row.setSpacing(0)
        self._v_ruler = RulerWidget(RulerWidget.VERTICAL)
        self._v_ruler.set_view(self._view)
        view_row.addWidget(self._v_ruler)
        view_row.addWidget(self._view)
        grid.addLayout(view_row)
        self.setCentralWidget(central)

        # Connect cursor movement to rulers
        self._view.cursor_moved.connect(self._on_cursor_move)

        # Component library panel
        self._library = ComponentLibraryPanel(self)
        self._library.component_requested.connect(self._on_library_component)
        self.addDockWidget(Qt.LeftDockWidgetArea, self._library)

        self._layers = LayerPanel(self._scene, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self._layers)

        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._restore_settings()
        # Refresh layers when items are added/removed
        self._scene.undo_stack.indexChanged.connect(lambda: self._layers.refresh())

    def _on_cursor_move(self, pos):
        self._h_ruler.set_cursor_scene_pos(pos)
        self._v_ruler.set_cursor_scene_pos(pos)
        self._h_ruler.update()
        self._v_ruler.update()
        ft_x, ft_y = pos.x() / 12, pos.y() / 12
        sel_count = len([it for it in self._scene.selectedItems()
                         if isinstance(it, (ComponentItem, TableItem))])
        zoom_pct = int(self._view._zoom_level * 100)
        sel_text = f"  |  {sel_count} selected" if sel_count else ""
        self._coord_label.setText(
            f'X: {pos.x():.1f}"  Y: {pos.y():.1f}"  '
            f'({ft_x:.1f}\' x {ft_y:.1f}\')  |  '
            f'Zoom: {zoom_pct}%  |  Grid: {int(self._scene.grid_size)}"{sel_text}')

    def _on_library_component(self, path):
        try:
            comp_data = load_component_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return
        comp_data["display_name"] = os.path.basename(path).replace('.comp.json', '')
        dlg = LoadComponentDialog(comp_data, self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            if data:
                center = self._view.mapToScene(
                    self._view.viewport().rect().center())
                w, h = data.get_bounding_size()
                data.x = center.x() - w / 2
                data.y = center.y() - h / 2
                item = ComponentItem(data)
                self._scene.undo_stack.push(AddItemCommand(self._scene, item))
                self._set_modified()

    def _set_modified(self, val=True):
        self._modified = val
        title = "Lab Layout Planner"
        if self._current_file:
            title += f" — {os.path.basename(self._current_file)}"
        else:
            title += " — Untitled"
        if val:
            title += " *"
        self.setWindowTitle(title)

    # ---- menus ----

    def _build_menus(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        self._add_action(file_menu, "New Layout", self._new_layout, "Ctrl+Shift+N")
        self._add_action(file_menu, "Open Layout...", self._open_layout, "Ctrl+O")
        self._add_action(file_menu, "Save Layout", self._save_layout, "Ctrl+S")
        self._add_action(file_menu, "Save Layout As...", self._save_layout_as, "Ctrl+Shift+S")
        file_menu.addSeparator()
        self._add_action(file_menu, "Export as PNG...", self._export_png, "Ctrl+Shift+E")
        file_menu.addSeparator()
        self._add_action(file_menu, "Exit", self.close)

        edit_menu = mb.addMenu("Edit")
        self._undo_act = self._add_action(edit_menu, "Undo", self._undo, "Ctrl+Z")
        self._redo_act = self._add_action(edit_menu, "Redo", self._redo, "Ctrl+Shift+Z")
        edit_menu.addSeparator()
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Add Component (Manual)...", self._add_manual, "Ctrl+N")
        self._add_action(edit_menu, "Load Component...", self._load_component, "Ctrl+L")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Convert STP to Component...", self._convert_stp, "Ctrl+I")
        edit_menu.addSeparator()
        self._add_action(edit_menu, "Delete Selected", self._delete_selected)

        view_menu = mb.addMenu("View")
        self._grid_act = self._add_action(view_menu, "Grid: ON", self._toggle_grid, "G")
        self._snap_act = self._add_action(view_menu, "Snap: ON", self._toggle_snap, "S")
        self._grid_size_act = self._add_action(view_menu, 'Grid: 6"', self._cycle_grid_size)
        view_menu.addSeparator()
        self._add_action(view_menu, "Zoom In", self._view.zoom_in, "Ctrl+=")
        self._add_action(view_menu, "Zoom Out", self._view.zoom_out, "Ctrl+-")
        self._add_action(view_menu, "Zoom to Fit", self._view.zoom_to_fit, "Ctrl+0")
        view_menu.addSeparator()
        self._add_action(view_menu, "Measure Tool (M)", lambda: self._view.set_measure_mode(True))
        self._add_action(view_menu, "Clear All Measurements", self._clear_measurements)
        view_menu.addSeparator()
        self._dark_act = self._add_action(view_menu, "Dark Mode", self._toggle_theme)
        self._dark_act.setCheckable(True)

    def _add_action(self, menu, text, slot, shortcut=None):
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(shortcut)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    # ---- toolbar ----

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        def _tb(text, slot, tip=None):
            act = QAction(text, self)
            act.triggered.connect(slot)
            if tip:
                act.setToolTip(tip)
            tb.addAction(act)

        _tb("New", self._new_layout, "New layout (Ctrl+Shift+N)")
        _tb("Save", self._save_layout, "Save layout (Ctrl+S)")
        _tb("Save As", self._save_layout_as, "Save layout as (Ctrl+Shift+S)")
        _tb("Open", self._open_layout, "Open layout (Ctrl+O)")
        tb.addSeparator()
        _tb("Undo", self._undo, "Undo (Ctrl+Z)")
        _tb("Redo", self._redo, "Redo (Ctrl+Shift+Z)")
        tb.addSeparator()
        _tb("+ Manual", self._add_manual, "Add manual component (Ctrl+N)")
        _tb("+ Component", self._load_component, "Load .comp.json (Ctrl+L)")
        _tb("Convert STP", self._convert_stp, "Convert STP to component (Ctrl+I)")
        tb.addSeparator()
        _tb("Grid", self._toggle_grid, "Toggle grid (G)")
        _tb("Snap", self._toggle_snap, "Toggle snap (S)")
        tb.addSeparator()
        _tb("Zoom +", self._view.zoom_in, "Zoom in (Ctrl+=)")
        _tb("Zoom -", self._view.zoom_out, "Zoom out (Ctrl+-)")
        _tb("Fit", self._view.zoom_to_fit, "Fit all in view (Ctrl+0)")

        self._pan_act = QAction("Pan", self)
        self._pan_act.setCheckable(True)
        self._pan_act.setToolTip("Pan mode — drag to move the view (Space)")
        self._pan_act.toggled.connect(self._view.set_pan_mode)
        tb.addAction(self._pan_act)

        _tb("Measure", lambda: self._view.set_measure_mode(True), "Measure tool (M)")
        tb.addSeparator()
        _tb("Export PNG", self._export_png, "Export as PNG (Ctrl+Shift+E)")

    def _build_statusbar(self):
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._coord_label = QLabel("")
        self._status.addPermanentWidget(self._coord_label)

    # ---- file operations ----

    def _confirm_discard(self):
        if not self._modified:
            return True
        reply = QMessageBox.question(
            self, "Unsaved Changes",
            "You have unsaved changes. Continue without saving?",
            QMessageBox.Yes | QMessageBox.No)
        return reply == QMessageBox.Yes

    def _new_layout(self):
        if not self._confirm_discard():
            return
        self._scene.clear_all()
        self._current_file = None
        self._set_modified(False)

    def _open_layout(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Layout", "", "Layout (*.layout.json);;All (*)")
        if not path:
            return
        with open(path) as f:
            data = json.load(f)
        self._scene.clear_all()
        for td in data.get("tables", []):
            self._scene.add_table(TableData.from_dict(td))
        for cd in data.get("components", []):
            comp = ComponentData.from_dict(cd)
            # Recover missing preview from library
            if not comp.preview_png and comp.source_file:
                comp.preview_png = self._find_preview_in_library(comp.source_file)
            self._scene.add_component(comp)
        self._current_file = path
        self._set_modified(False)
        self._view.zoom_to_fit()
        self._status.showMessage(f"Opened {path}", 3000)

    def _find_preview_in_library(self, source_file):
        """Search library for a .comp.json that matches this source file."""
        lib_dir = self._library.get_directory()
        if not lib_dir or not os.path.isdir(lib_dir):
            return ""
        for f in os.listdir(lib_dir):
            if not f.endswith('.comp.json'):
                continue
            fpath = os.path.join(lib_dir, f)
            try:
                with open(fpath) as fp:
                    data = json.load(fp)
                if data.get("source_file") == source_file:
                    # Return the first available preview
                    for plane in ["XY", "XZ", "YZ"]:
                        b64 = data.get("projections", {}).get(plane, {}).get("preview_png", "")
                        if b64:
                            return b64
            except Exception:
                pass
        return ""

    def _save_layout(self):
        if self._current_file:
            self._do_save(self._current_file)
        else:
            self._save_layout_as()

    def _save_layout_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Layout", "layout.layout.json",
            "Layout (*.layout.json)")
        if not path:
            return
        self._do_save(path)

    def _do_save(self, path):
        data = {
            "version": 1,
            "saved": datetime.now().isoformat(),
            "tables": [t.to_dict() for t in self._scene.get_all_tables()],
            "components": [c.to_dict() for c in self._scene.get_all_components()],
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        self._current_file = path
        self._set_modified(False)
        self._status.showMessage(f"Saved to {path}", 3000)

    def _load_table_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Table Template", "", "Table Template (*.tbl.json)")
        if not path:
            return
        with open(path) as f:
            data = json.load(f)
        self._scene.clear_tables()
        for td in data.get("tables", []):
            self._scene.add_table(TableData.from_dict(td))
        self._set_modified()
        self._view.zoom_to_fit()
        self._status.showMessage(f"Loaded table template from {path}", 3000)

    def _save_table_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Table Template", "tables.tbl.json",
            "Table Template (*.tbl.json)")
        if not path:
            return
        data = {"version": 1,
                "tables": [t.to_dict() for t in self._scene.get_all_tables()]}
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        self._status.showMessage(f"Saved table template to {path}", 3000)

    # ---- edit operations ----

    def _table_setup(self):
        existing = self._scene.get_all_tables()
        dlg = TableSetupDialog(existing, self)
        if dlg.exec_() == QDialog.Accepted:
            self._scene.clear_tables()
            for t in dlg.get_tables():
                self._scene.add_table(t)
            self._set_modified()
            self._view.zoom_to_fit()

    def _add_manual(self):
        dlg = AddManualDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            center = self._view.mapToScene(
                self._view.viewport().rect().center())
            data.x = center.x() - data.width / 2
            data.y = center.y() - data.height / 2
            self._scene.add_component(data)
            self._set_modified()

    def _convert_stp(self):
        """Convert a STEP file to .comp.json (preprocessing step)."""
        stp_path, _ = QFileDialog.getOpenFileName(
            self, "Select STEP File to Convert", "",
            "STEP Files (*.stp *.step);;All (*)")
        if not stp_path:
            return
        base = os.path.splitext(os.path.basename(stp_path))[0]
        out_dir = os.path.dirname(stp_path)
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Component File",
            os.path.join(out_dir, f"{base}.comp.json"),
            "Component File (*.comp.json)")
        if not out_path:
            return

        progress = QProgressDialog("Converting STP file...\n"
                                   "This may take a minute for large files.",
                                   "Cancel", 0, 0, self)
        progress.setWindowTitle("Converting")
        progress.setMinimumDuration(0)
        progress.show()

        self._convert_worker = ConvertWorker(stp_path, out_path)
        self._convert_worker.progress.connect(
            lambda msg: progress.setLabelText(msg))
        self._convert_worker.finished.connect(
            lambda p: self._on_convert_done(p, progress))
        self._convert_worker.error.connect(
            lambda e: self._on_convert_error(e, progress))
        self._convert_worker.start()

    def _on_convert_done(self, out_path, progress):
        progress.close()
        self._status.showMessage(f"Saved component to {out_path}", 5000)
        QMessageBox.information(self, "Conversion Complete",
                                f"Component file saved:\n{out_path}\n\n"
                                "Use 'Load Component' to add it to your layout.")

    def _on_convert_error(self, error_msg, progress):
        progress.close()
        QMessageBox.critical(self, "Conversion Error", error_msg)

    def _load_component(self):
        """Load a preprocessed .comp.json file and place it on the canvas."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Component File", "",
            "Component Files (*.comp.json);;All (*)")
        if not path:
            return
        try:
            comp_data = load_component_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load file:\n{e}")
            return
        comp_data["display_name"] = os.path.basename(path).replace('.comp.json', '')
        dlg = LoadComponentDialog(comp_data, self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            if data:
                center = self._view.mapToScene(
                    self._view.viewport().rect().center())
                w, h = data.get_bounding_size()
                data.x = center.x() - w / 2
                data.y = center.y() - h / 2
                self._scene.add_component(data)
                self._set_modified()
                self._status.showMessage(
                    f'Loaded "{data.name}" ({w:.1f}" x {h:.1f}")', 3000)

    def _delete_selected(self):
        for it in list(self._scene.selectedItems()):
            if isinstance(it, (ComponentItem, TableItem)):
                self._scene.removeItem(it)
                self._set_modified()

    # ---- view toggles ----

    def _clear_measurements(self):
        for it in list(self._scene.items()):
            if isinstance(it, DimensionItem):
                self._scene.removeItem(it)

    def _toggle_grid(self):
        self._scene.grid_visible = not self._scene.grid_visible
        self._grid_act.setText(
            "Grid: ON" if self._scene.grid_visible else "Grid: OFF")
        self._view.viewport().update()

    def _toggle_snap(self):
        self._scene.grid_snap = not self._scene.grid_snap
        self._snap_act.setText(
            "Snap: ON" if self._scene.grid_snap else "Snap: OFF")

    def _cycle_grid_size(self):
        sizes = [3, 6, 12, 24]
        cur = self._scene.grid_size
        idx = sizes.index(cur) if cur in sizes else 0
        self._scene.grid_size = sizes[(idx + 1) % len(sizes)]
        self._grid_size_act.setText(f'Grid: {int(self._scene.grid_size)}"')
        self._view.viewport().update()

    # ---- undo/redo ----

    def _undo(self):
        self._scene.undo_stack.undo()
        self._set_modified()

    def _redo(self):
        self._scene.undo_stack.redo()
        self._set_modified()

    # ---- export ----

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export as PNG", "layout.png", "PNG (*.png)")
        if not path:
            return
        sr = self._scene.sceneRect().adjusted(-10, -10, 10, 10)
        img = QImage(int(sr.width() * 4), int(sr.height() * 4),
                     QImage.Format_ARGB32)
        img.fill(QColor(get_theme()["bg"]))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        self._scene.render(painter, QRectF(img.rect()), sr)
        painter.end()
        img.save(path)
        self._status.showMessage(f"Exported to {path}", 3000)

    # ---- theme ----

    def _toggle_theme(self):
        if get_theme()["name"] == "light":
            set_theme(THEME_DARK)
            self._dark_act.setChecked(True)
        else:
            set_theme(THEME_LIGHT)
            self._dark_act.setChecked(False)
        self._apply_theme()

    def _apply_theme(self):
        t = get_theme()
        self._view.setBackgroundBrush(QBrush(QColor(t["bg"])))
        # Update table colors
        for it in self._scene.items():
            if isinstance(it, TableItem):
                it.setBrush(QBrush(QColor(t["table_fill"])))
                it.setPen(QPen(QColor(t["table_border"]), 1.5))
                it._label.setBrush(QBrush(QColor(t["text"])))
        self._h_ruler.update()
        self._v_ruler.update()
        self._view.viewport().update()
        if t["name"] == "dark":
            self.setStyleSheet(
                "QMainWindow, QToolBar, QMenuBar, QMenu, QStatusBar, "
                "QDockWidget { background: #2A2A3A; color: #DDD; } "
                "QMenu::item:selected { background: #444466; } "
                "QToolBar QToolButton { color: #DDD; } "
                "QDockWidget QWidget { background: #252535; color: #DDD; }")
        else:
            self.setStyleSheet("")

    # ---- persistent settings ----

    def _restore_settings(self):
        geo = self._settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        state = self._settings.value("windowState")
        if state:
            self.restoreState(state)
        grid_size = self._settings.value("grid_size", 6.0, type=float)
        self._scene.grid_size = grid_size
        self._grid_size_act.setText(f'Grid: {int(grid_size)}"')
        grid_snap = self._settings.value("grid_snap", True, type=bool)
        self._scene.grid_snap = grid_snap
        self._snap_act.setText("Snap: ON" if grid_snap else "Snap: OFF")
        grid_vis = self._settings.value("grid_visible", True, type=bool)
        self._scene.grid_visible = grid_vis
        self._grid_act.setText("Grid: ON" if grid_vis else "Grid: OFF")
        theme = self._settings.value("theme", "light")
        if theme == "dark":
            set_theme(THEME_DARK)
            self._dark_act.setChecked(True)
            self._apply_theme()
        lib_dir = self._settings.value("library_dir", "")
        if lib_dir and os.path.isdir(lib_dir):
            self._library.set_directory(lib_dir)
        elif os.path.isdir(ComponentLibraryPanel.DEFAULT_LIB):
            self._library.set_directory(ComponentLibraryPanel.DEFAULT_LIB)

    def _save_settings(self):
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())
        self._settings.setValue("grid_size", self._scene.grid_size)
        self._settings.setValue("grid_snap", self._scene.grid_snap)
        self._settings.setValue("grid_visible", self._scene.grid_visible)
        self._settings.setValue("theme", get_theme()["name"])
        self._settings.setValue("library_dir", self._library.get_directory())

    def closeEvent(self, event):
        if self._confirm_discard():
            self._save_settings()
            event.accept()
        else:
            event.ignore()


# ============================================================================
#  ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # CLI mode: convert STP to .comp.json without launching GUI
    if len(sys.argv) >= 5 and sys.argv[1] == '--convert':
        stp_path = sys.argv[2]
        out_path = sys.argv[3]
        tolerance = float(sys.argv[4]) if len(sys.argv) > 4 else 5.0
        units = sys.argv[5] if len(sys.argv) > 5 else 'mm'
        try:
            save_component_file(stp_path, out_path, tolerance, units)
            print(f"Saved: {out_path}")
        except Exception as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    # GUI mode
    app = QApplication(sys.argv)
    app.setApplicationName("Lab Layout Planner")
    window = LabLayoutApp()
    window.show()
    sys.exit(app.exec_())
