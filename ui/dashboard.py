"""DashboardWidget — KPI labels + monthly bar chart + per-category pie chart."""

from datetime import date
from typing import Optional

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.database import Database
from ui import constants as c


class DashboardWidget(QWidget):
    """Simple analytics dashboard for the active profile (current year)."""

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._db = db
        self._profile_id: Optional[int] = None

        self.kpi_total = self._kpi_label()
        self.kpi_count = self._kpi_label()
        self.kpi_top = self._kpi_label()

        kpi_row = QGridLayout()
        kpi_row.addWidget(self._kpi_box("Minuté spolu (rok)", self.kpi_total), 0, 0)
        kpi_row.addWidget(self._kpi_box("Počet bločkov", self.kpi_count), 0, 1)
        kpi_row.addWidget(self._kpi_box("Top kategória", self.kpi_top), 0, 2)

        self.bar_view = QChartView()
        self.bar_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.pie_view = QChartView()
        self.pie_view.setRenderHint(QPainter.RenderHint.Antialiasing)

        charts = QHBoxLayout()
        charts.addWidget(self.bar_view, 2)
        charts.addWidget(self.pie_view, 1)

        layout = QVBoxLayout(self)
        layout.addLayout(kpi_row)
        layout.addLayout(charts, 1)

    @staticmethod
    def _kpi_label() -> QLabel:
        label = QLabel("—")
        label.setStyleSheet(
            f"font-size:{c.FONT_SIZE_LARGE}pt; font-weight:bold; color:{c.CLR_ACCENT};"
        )
        return label

    def _kpi_box(self, title: str, value_label: QLabel) -> QWidget:
        box = QWidget()
        box.setStyleSheet(
            f"background-color:{c.CLR_PANEL}; border:1px solid {c.CLR_BORDER};"
            "border-radius:6px;"
        )
        v = QVBoxLayout(box)
        caption = QLabel(title)
        caption.setStyleSheet(f"color:{c.CLR_TEXT_SECONDARY};")
        v.addWidget(caption)
        v.addWidget(value_label)
        return box

    def set_profile(self, profile_id: Optional[int]) -> None:
        """Set the active profile and refresh charts."""
        self._profile_id = profile_id
        self.refresh()

    def refresh(self) -> None:
        """Recompute KPIs and rebuild both charts."""
        if not self._profile_id:
            return
        year = date.today().year
        monthly = self._db.get_monthly_totals(self._profile_id, year)
        cat_totals = self._db.get_category_totals(self._profile_id, year)

        total = round(sum(v for _, v in monthly), 2)
        self.kpi_total.setText(f"{total:.2f} €")
        receipts = self._db.get_receipts(self._profile_id, year=year)
        self.kpi_count.setText(str(len(receipts)))
        self.kpi_top.setText(cat_totals[0][0] if cat_totals else "—")

        self._build_bar_chart(monthly)
        self._build_pie_chart(cat_totals)

    def _build_bar_chart(self, monthly) -> None:
        values = {m: v for m, v in monthly}
        bar_set = QBarSet("Výdavky")
        for month in range(1, 13):
            bar_set.append(values.get(month, 0.0))
        bar_set.setColor(QColor(c.CLR_ACCENT))

        series = QBarSeries()
        series.append(bar_set)

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Výdavky po mesiacoch")
        chart.setBackgroundBrush(QColor(c.CLR_BG_MAIN))
        chart.setTitleBrush(QColor(c.CLR_TEXT_PRIMARY))
        chart.legend().setVisible(False)

        axis_x = QBarCategoryAxis()
        axis_x.append([m[:3] for m in c.MONTHS_SK])
        axis_x.setLabelsColor(QColor(c.CLR_TEXT_PRIMARY))
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setLabelsColor(QColor(c.CLR_TEXT_PRIMARY))
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        self.bar_view.setChart(chart)

    def _build_pie_chart(self, cat_totals) -> None:
        series = QPieSeries()
        for name, color, total in cat_totals:
            if total <= 0:
                continue
            slice_ = series.append(f"{name} ({total:.0f})", total)
            slice_.setColor(QColor(color))
            slice_.setLabelColor(QColor(c.CLR_TEXT_PRIMARY))

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Výdavky podľa kategórií")
        chart.setBackgroundBrush(QColor(c.CLR_BG_MAIN))
        chart.setTitleBrush(QColor(c.CLR_TEXT_PRIMARY))
        chart.legend().setLabelColor(QColor(c.CLR_TEXT_PRIMARY))
        self.pie_view.setChart(chart)
