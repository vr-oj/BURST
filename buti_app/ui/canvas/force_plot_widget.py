# force_plot_widget.py
import os
import time
import bisect
import logging
import math

from PyQt5.QtWidgets import (
    QWidget,
    QSizePolicy,
    QVBoxLayout,
    QMessageBox,
    QFileDialog,
    QScrollBar,
)
from PyQt5.QtCore import Qt, pyqtSlot
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import matplotlib as mpl

from utils.config import PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX

log = logging.getLogger(__name__)


class ForcePlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        mpl.rcParams.update(
            {
                "font.size": 11,
                "axes.edgecolor": "#333333",
                "axes.labelweight": "bold",
                "axes.labelsize": 12,
                "axes.linewidth": 1.5,
                "xtick.color": "#333333",
                "ytick.color": "#333333",
                "figure.facecolor": "#ffffff",
                "savefig.facecolor": "#ffffff",
            }
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Matplotlib canvas
        self.fig = Figure(facecolor="white", tight_layout=True)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)

        # Plot state
        self.axes = {}
        self.lines = {}
        self.placeholder = None
        self.hover_annotation = None

        # Data storage (force only)
        self.times = []
        self.forces = []
        self.manual_xlim = None
        self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
        self.window_duration = 100  # Duration of the visible window in seconds

        self._configure_axes()

        # Scrollbar for manual X panning
        self.scrollbar = QScrollBar(Qt.Horizontal, self)
        self.scrollbar.hide()
        layout.addWidget(self.scrollbar)
        self.scrollbar.valueChanged.connect(self._on_scroll)

        # MODIFIED: Apply a simple stylesheet to the scrollbar for better visibility
        self.scrollbar.setStyleSheet(
            """
            QScrollBar:horizontal {
                border: 1px solid #C0C0C0; /* Light border for the scrollbar itself */
                background: #F0F0F0;    /* Background of the scrollbar groove */
                height: 15px;           /* Height of the scrollbar */
                margin: 0px 20px 0 20px;/* Margins to make space for add/sub-line buttons if they were visible */
            }
            QScrollBar::handle:horizontal {
                background: #A0A0A0;    /* A medium gray for the handle */
                min-width: 20px;        /* Minimum width of the handle */
                border-radius: 5px;     /* Rounded corners for the handle */
                border: 1px solid #808080; /* Border for the handle */
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                /* Style for arrow buttons if you want them, currently not explicitly shown */
                /* border: 1px solid grey; background: #E0E0E0; width: 18px; */
                width: 0px; /* Hide standard arrow buttons by making them zero width */
                height: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none; /* Background of the area where you click to page scroll */
            }
        """
        )

        # Internal state mirrors PlotControlPanel defaults
        self._last_auto_x = True
        self._last_auto_y = False

        # Create initial placeholder
        self._update_placeholder("Waiting for BURST device data...")

        # Connect hover event for hover annotations
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

    def _configure_axes(self):
        """(Re)create axes and line artists for the force plot."""
        self.fig.clear()
        self.axes = {}
        self.lines = {}
        self.placeholder = None

        ax = self.fig.add_subplot(111)
        self._style_axis(ax)
        ax.set_xlabel("Time (s)", fontsize=16, fontweight="bold")
        ax.set_ylabel("Force (mN)", fontsize=16, fontweight="bold")

        self.axes = {"force": ax}
        self.lines = {
            "force": ax.plot([], [], "-", lw=2, color="#2E3440", label="Force (mN)")[
                0
            ],
        }
        ax.legend(loc="upper right", frameon=False, fontsize=10)

        self.hover_annotation = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(15, 15),
            textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.4", fc="wheat", alpha=0.85),
            arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=.2", color="black"),
        )
        self.hover_annotation.set_visible(False)

        self.fig.tight_layout()
        primary_ax = self._primary_axis()
        if primary_ax and self.manual_ylim:
            primary_ax.set_ylim(self.manual_ylim)
        self.canvas.draw_idle()

    def _style_axis(self, ax):
        ax.set_facecolor("white")
        ax.tick_params(labelsize=10, colors="#333333")
        for spine in ax.spines.values():
            spine.set_color("#D8DEE9")
        ax.grid(True, linestyle="--", alpha=0.7, color="lightgray")

    def _primary_axis(self):
        return self.axes.get("force")

    def _refresh_line_data(self):
        line = self.lines.get("force")
        if line:
            line.set_data(self.times, self.forces)

    def _apply_xlim(self, limits):
        for ax in self.axes.values():
            ax.set_xlim(limits)

    def _update_axes_limits(self, auto_x: bool, auto_y: bool):
        primary_ax = self._primary_axis()
        if not primary_ax:
            return

        # â”€â”€â”€ X-axis handling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if auto_x:
            self.manual_xlim = None
            self.scrollbar.hide()
            if len(self.times) > 1:
                start, end = self.times[0], self.times[-1]
                pad = max(1, (end - start) * 0.05)
                limits = (start - pad * 0.1, end + pad * 0.9)
            elif self.times:
                t0 = self.times[-1]
                limits = (t0 - 0.5, t0 + 0.5)
            else:
                limits = (0, 10)
            self._apply_xlim(limits)
        else:
            t_latest = self.times[-1] if self.times else 0.0
            xmin = max(0.0, t_latest - self.window_duration)
            xmax = t_latest
            self.manual_xlim = (xmin, xmax)
            self._apply_xlim(self.manual_xlim)
            self.scrollbar.hide()

        # â”€â”€â”€ Y-axis handling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if auto_y and self.times:
            mn, mx = min(self.forces), max(self.forces)
            if math.isfinite(mn) and math.isfinite(mx):
                pad = max(abs(mx - mn) * 0.1, 2.0)
                if pad == 0:
                    pad = 2.0
                primary_ax.set_ylim(mn - pad, mx + pad)
        elif not auto_y and self.manual_ylim:
            primary_ax.set_ylim(self.manual_ylim)
        elif not self.times:
            primary_ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)

    def _update_placeholder(self, text=None):
        primary_ax = self._primary_axis()
        if not primary_ax:
            return

        if text:
            # Clear all lines when showing the placeholder
            for line in self.lines.values():
                line.set_data([], [])

            if self.hover_annotation and self.hover_annotation.get_visible():
                self.hover_annotation.set_visible(False)

            if self.placeholder:
                self.placeholder.set_text(text)
                self.placeholder.set_visible(True)
            else:
                self.placeholder = primary_ax.text(
                    0.5,
                    0.5,
                    text,
                    transform=primary_ax.transAxes,
                    ha="center",
                    va="center",
                    fontsize=12,
                    color="gray",
                    bbox=dict(boxstyle="round,pad=0.5", fc="#ECEFF4", alpha=0.8),
                )
        elif self.placeholder:
            self.placeholder.set_visible(False)

        self.canvas.draw_idle()

    def _find_nearest_datapoint(self, x_coord):
        """Finds the nearest data point (time, force, index) to the given x_coord."""
        if not self.times:
            return None, None, -1

        # bisect_left finds the insertion point for x_coord to maintain sorted order
        idx = bisect.bisect_left(self.times, x_coord)

        if idx == 0:  # x_coord is at or before the first element
            best_idx = 0
        elif idx == len(self.times):  # x_coord is after the last element
            best_idx = len(self.times) - 1
        else:  # x_coord is between self.times[idx-1] and self.times[idx]
            # Determine which of the two neighbours is closer
            dist1 = abs(x_coord - self.times[idx - 1])
            dist2 = abs(x_coord - self.times[idx])
            if dist1 <= dist2:
                best_idx = idx - 1
            else:
                best_idx = idx

        # Optional: Add a threshold if you only want to show hover for very close points
        # For example, if the closest point's x value is too far from mouse x_coord:
        # x_axis_range = self.ax.get_xlim()[1] - self.ax.get_xlim()[0]
        # if x_axis_range > 0 and abs(self.times[best_idx] - x_coord) > x_axis_range * 0.05: # 5% of current x-axis view
        #     return None, None, -1

        return self.times[best_idx], self.forces[best_idx], best_idx

    def _on_hover(self, event):
        """Handles mouse motion event to show data point information."""
        line = self.lines.get("force")
        ax = self._primary_axis()
        if not line or not ax or not self.hover_annotation:
            return

        # If no data, or placeholder is visible, or line is not visible, do nothing with hover
        if (
            not self.times
            or (self.placeholder and self.placeholder.get_visible())
            or not line.get_visible()
        ):
            if self.hover_annotation and self.hover_annotation.get_visible():
                self.hover_annotation.set_visible(False)
                self.canvas.draw_idle()
            return

        annotation_visible = self.hover_annotation.get_visible()
        needs_redraw = False

        if event.inaxes == ax:  # Check if mouse is over the plot axes
            x_mouse, y_mouse = (
                event.xdata,
                event.ydata,
            )  # Mouse coordinates in data space

            # Find the data point on the line closest to the mouse's x-coordinate
            target_x, target_y, _ = self._find_nearest_datapoint(x_mouse)

            if target_x is not None:
                self.hover_annotation.xy = (target_x, target_y)
                new_text = f"Time: {target_x:.2f} s\nForce: {target_y:.2f}"

                if self.hover_annotation.get_text() != new_text:
                    self.hover_annotation.set_text(new_text)
                    needs_redraw = True

                if not annotation_visible:
                    self.hover_annotation.set_visible(True)
                    needs_redraw = True
            else:  # No suitable data point found
                if annotation_visible:
                    self.hover_annotation.set_visible(False)
                    needs_redraw = True
        else:  # Mouse is not over the axes
            if annotation_visible:
                self.hover_annotation.set_visible(False)
                needs_redraw = True

        if needs_redraw:
            self.canvas.draw_idle()

    @pyqtSlot(float, float, float, int, bool, bool)
    def update_plot(self, t, force, _length, _cycle, auto_x, auto_y):
        self._last_auto_x = auto_x
        self._last_auto_y = auto_y

        # Remove placeholder on first data point
        if not self.times and self.placeholder and self.placeholder.get_visible():
            self._update_placeholder(None)

        # Append new data
        self.times.append(t)
        self.forces.append(force)

        self._refresh_line_data()

        if auto_y:
            self.manual_ylim = None

        prev_limits = {
            key: self.axes[key].get_ylim() if key in self.axes else None
            for key in self.axes
        }
        prev_xlim = self._primary_axis().get_xlim() if self._primary_axis() else None

        self._update_axes_limits(auto_x, auto_y)

        # Redraw only if something actually changed
        need_redraw = any(line.stale for line in self.lines.values())

        new_primary = self._primary_axis()
        if prev_xlim and new_primary and new_primary.get_xlim() != prev_xlim:
            need_redraw = True

        for key, ax in self.axes.items():
            if key in prev_limits and ax.get_ylim() != prev_limits[key]:
                need_redraw = True

        if need_redraw:
            self.canvas.draw_idle()

    def _update_scrollbar(self):
        if not self.times or not self.manual_xlim:  # Ensure data and manual_xlim exist
            self.scrollbar.hide()
            return

        # Determine index-based window for manual_xlim
        xmin, xmax = self.manual_xlim
        idx0 = bisect.bisect_left(self.times, xmin)
        idx1 = bisect.bisect_right(self.times, xmax)
        window_size = max(idx1 - idx0, 1)  # Ensure window_size is at least 1
        full_len = len(self.times)

        if full_len <= window_size:  # If the window covers all data
            self.scrollbar.hide()
            return

        # Configure scrollbar
        self.scrollbar.setMinimum(0)
        self.scrollbar.setMaximum(
            max(full_len - window_size, 0)
        )  # Ensure maximum is not negative
        self.scrollbar.setPageStep(window_size)
        self.scrollbar.setSingleStep(
            max(window_size // 10, 1)
        )  # Ensure singleStep is at least 1

        # Position scrollbar thumb
        self.scrollbar.setValue(idx0)  # Set value after setting min/max/pageStep
        self.scrollbar.show()

    @pyqtSlot(int)
    def _on_scroll(self, pos):
        # Pan X-axis window based on scroll position
        if not self.manual_xlim or not self.times or len(self.times) <= 1:
            return

        # Determine window size from current manual_xlim to maintain zoom level
        current_xmin, current_xmax = self.manual_xlim
        # Find indices for the current xlim to estimate window width in data units
        current_idx_min = bisect.bisect_left(self.times, current_xmin)
        current_idx_max = bisect.bisect_right(self.times, current_xmax)

        # Calculate window width in terms of number of data points
        # This uses pageStep as an approximation of window size in indices
        window_indices = self.scrollbar.pageStep()

        # New start index from scrollbar position
        start_idx = pos
        end_idx = min(
            start_idx + window_indices - 1, len(self.times) - 1
        )  # Ensure end_idx is valid

        if start_idx >= end_idx and len(self.times) > 1:  # Ensure valid range
            # This can happen if window_indices is too small or pos is at the very end.
            # Default to a small window at the end.
            start_idx = max(0, len(self.times) - 2)
            end_idx = len(self.times) - 1

        if start_idx < 0:
            start_idx = 0  # Should not happen with QScrollBar limits

        xmin_new = self.times[start_idx]
        xmax_new = self.times[end_idx]

        # Ensure xmax_new is greater than xmin_new, especially for small datasets
        if xmin_new == xmax_new and len(self.times) > 1:
            if end_idx + 1 < len(self.times):
                xmax_new = self.times[end_idx + 1]
            elif start_idx - 1 >= 0:
                xmin_new = self.times[start_idx - 1]
            else:  # Single point, or all points identical; give a small default range
                xmax_new = xmin_new + 1.0

        self.manual_xlim = (xmin_new, xmax_new)
        self._apply_xlim(self.manual_xlim)
        self.canvas.draw_idle()

    def set_manual_x_limits(self, xmin, xmax):
        if xmin < xmax:
            self.manual_xlim = (xmin, xmax)
            self._apply_xlim(self.manual_xlim)
            self._update_scrollbar()  # Update scrollbar based on new manual limits
            self.canvas.draw_idle()  # Redraw
        else:
            log.warning("X min must be less than X max")

    def set_manual_y_limits(self, ymin, ymax):
        if (
            ymin < ymax and math.isfinite(ymin) and math.isfinite(ymax)
        ):  # Ensure finite values
            self.manual_ylim = (ymin, ymax)
            primary_ax = self._primary_axis()
            if primary_ax:
                primary_ax.set_ylim(self.manual_ylim)
            self.canvas.draw_idle()
        else:
            log.warning(
                f"Y limits must be finite and min < max. Received: {ymin}, {ymax}"
            )

    def reset_zoom(self, auto_x, auto_y):
        self.manual_xlim = None  # Reset manual x-limits
        if auto_x:
            self.scrollbar.hide()

        if not auto_y:  # If auto_y is false, reset to default Y manual limits
            self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            primary_ax = self._primary_axis()
            if primary_ax:
                primary_ax.set_ylim(self.manual_ylim)
        else:  # If auto_y is true, clear manual y-limits for full auto-scaling
            self.manual_ylim = None

        # Re-evaluate plot based on current data and new auto settings
        if self.times:
            self._update_axes_limits(auto_x, auto_y)
            self.canvas.draw_idle()
        else:  # No data, set to default view
            default_xlim = (0, 10)
            self._apply_xlim(default_xlim)
            primary_ax = self._primary_axis()
            if primary_ax:
                if self.manual_ylim and not auto_y:
                    primary_ax.set_ylim(self.manual_ylim)
                elif not auto_y:
                    primary_ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            self._update_placeholder("Plot cleared or waiting for data.")
            self.canvas.draw_idle()

    def clear_plot(self):
        self.times.clear()
        self.forces.clear()

        for line in self.lines.values():
            line.set_data([], [])

        self._apply_xlim((0, 100))  # Reset to a default X view

        primary_ax = self._primary_axis()
        if primary_ax:
            if self.manual_ylim is None:
                primary_ax.set_ylim(PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
            elif (
                isinstance(self.manual_ylim, tuple)
                and len(self.manual_ylim) == 2
                and all(v is not None and math.isfinite(v) for v in self.manual_ylim)
            ):
                primary_ax.set_ylim(self.manual_ylim)
            else:
                self.manual_ylim = (PLOT_DEFAULT_Y_MIN, PLOT_DEFAULT_Y_MAX)
                primary_ax.set_ylim(self.manual_ylim)

        if self.hover_annotation and self.hover_annotation.get_visible():
            self.hover_annotation.set_visible(False)

        self._update_placeholder("Plot data cleared.")  # This will also call draw_idle
        # self.canvas.draw_idle() # Called by _update_placeholder

    def export_as_image(self):
        if not self.times and not (
            self.placeholder and self.placeholder.get_visible()
        ):  #
            QMessageBox.warning(self, "Empty Plot", "Plot has no data to export.")
            return
        default_name = f"plot_export_{time.strftime('%Y%m%d-%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Plot Image",
            default_name,
            "PNG (*.png);;JPEG (*.jpg);;SVG (*.svg);;PDF (*.pdf)",
        )
        if not path:
            return
        try:
            # Temporarily hide hover annotation and placeholder for export
            hover_visible = self.hover_annotation.get_visible() if self.hover_annotation else False
            placeholder_text_visible = (
                self.placeholder and self.placeholder.get_visible()
            )

            if hover_visible and self.hover_annotation:
                self.hover_annotation.set_visible(False)
            if placeholder_text_visible:
                self.placeholder.set_visible(False)

            # Redraw canvas without annotations before saving
            self.canvas.draw()

            self.fig.savefig(path, dpi=300, facecolor=self.fig.get_facecolor())

            # Restore visibility
            if hover_visible and self.hover_annotation:
                self.hover_annotation.set_visible(True)
            if placeholder_text_visible:
                self.placeholder.set_visible(True)

            # Redraw canvas with annotations again
            self.canvas.draw_idle()

            sb = self.window().statusBar() if self.window() else None
            if sb:
                sb.showMessage(f"Plot exported to {os.path.basename(path)}", 3000)
        except Exception as e:  # Use 'e' for the exception instance
            log.exception(f"Error exporting plot image: {e}")
            QMessageBox.critical(
                self, "Export Error", f"Could not save plot image: {e}"
            )

    def get_plot_data(self):
        """Return shallow copies of the current time-series samples."""
        return {
            "time": list(self.times),
            "force": list(self.forces),
        }

