"""GUI-M1 主窗口：界面只提交命令，设备与写盘在 QThread 中执行。"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from data.spatial_session import SpatialSession
from gui.configuration import load_config, save_config_atomic
from mock.mock_camera import MockCamera
from mock.mock_xyz_stage import MockXYZStage
from scan.scan_state import ScanState
from scan.spatial_controller import SpatialCallbacks, SpatialScanController
from scan.spatial_scan import PLANE_AXES, SpatialPoint, SpatialScanPlan


pg.setConfigOption("imageAxisOrder", "row-major")


STATE_TEXT = {
    ScanState.IDLE: "空闲", ScanState.MOVING: "模拟移动", ScanState.WAITING_FOR_POSITION: "等待模拟到位",
    ScanState.SETTLING: "稳定等待", ScanState.ACQUIRING: "Mock 采集", ScanState.SAVING: "保存原图与日志",
    ScanState.PAUSED: "已暂停", ScanState.STOPPING: "停止中", ScanState.STOPPED: "已停止",
    ScanState.COMPLETED: "已完成", ScanState.ERROR: "错误",
}

OBJECTIVE_AXIS_TEXT = {
    "X": "X（物理+Y / 轴3+）",
    "Y": "Y（物理+Z / 轴5-）",
    "Z": "Z（物理+X / 轴4+ / 逆光）",
}
CAMERA_AXIS_TEXT = {
    "X": "X（物理+Y / 轴1+）",
    "Y": "Y（物理+Z / 轴2-）",
}


class Bridge(QtCore.QObject):
    state = QtCore.Signal(object)
    position = QtCore.Signal(object)
    point_saved = QtCore.Signal(object, object)
    progress = QtCore.Signal(int, int)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)


class ScanWorker(QtCore.QObject):
    def __init__(self, controller: SpatialScanController, plan: SpatialScanPlan, bridge: Bridge) -> None:
        super().__init__()
        self.controller, self.plan, self.bridge = controller, plan, bridge

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self.bridge.finished.emit(self.controller.run(self.plan))
        except Exception as exc:
            self.bridge.failed.emit(str(exc))
        finally:
            QtCore.QThread.currentThread().quit()


class MoveWorker(QtCore.QObject):
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, controller: SpatialScanController, targets: dict[str, float], group: str) -> None:
        super().__init__()
        self.controller, self.targets, self.group = controller, targets, group

    @QtCore.Slot()
    def run(self) -> None:
        try:
            if self.group == "camera":
                self.done.emit(self.controller.manual_move_camera(self.targets))
            else:
                self.done.emit(self.controller.manual_move(self.targets))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            QtCore.QThread.currentThread().quit()


def spin(value: float = 0.0, *, minimum: float = -10000, maximum: float = 10000, decimals: int = 4) -> QtWidgets.QDoubleSpinBox:
    widget = QtWidgets.QDoubleSpinBox()
    widget.setRange(minimum, maximum)
    widget.setDecimals(decimals)
    widget.setValue(value)
    widget.setKeyboardTracking(False)
    return widget


class MainWindow(QtWidgets.QMainWindow):
    scan_finished = QtCore.Signal(object)

    def __init__(self, *, config_path: Path | None = None) -> None:
        super().__init__()
        self.config_path = config_path or Path("configuration.json")
        self.config, config_error = load_config(self.config_path)
        self.setWindowTitle("Dimension Camera — GUI-M1 MOCK 空间扫描")
        self.resize(1500, 920)
        self.setMinimumSize(1180, 720)

        self.stage = MockXYZStage(speed_mm_s=20.0)
        self.stage.connect()
        self.camera = MockCamera(
            serial_number="MOCK-GUI-001", shape=(256, 320), seed=20260920,
            position_provider=self.stage.get_signal_positions, capture_delay_s=0.025,
        )
        self.camera.connect()
        self.bridge = Bridge()
        callbacks = SpatialCallbacks(
            on_state=self.bridge.state.emit,
            on_position=self.bridge.position.emit,
            on_point_saved=self.bridge.point_saved.emit,
            on_progress=self.bridge.progress.emit,
        )
        self.controller = SpatialScanController(self.stage, self.camera, callbacks)
        self._thread: QtCore.QThread | None = None
        self._move_thread: QtCore.QThread | None = None
        self._plan: SpatialScanPlan | None = None
        self._session: SpatialSession | None = None
        self._records: dict[int, dict[str, object]] = {}
        self._images: dict[int, np.ndarray] = {}
        self._metric_data: np.ndarray | None = None
        self._selected_point_id: int | None = None
        self._last_session_dir: Path | None = None
        self._build_ui()
        self._connect_signals()
        self._update_scan_labels()
        self._set_state(ScanState.IDLE)
        self._update_all_positions()
        if config_error:
            self.error_label.setText(config_error)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        banner = QtWidgets.QLabel("MOCK / 模拟数据 — 真实位移控制已禁用；停止按钮不是物理急停")
        banner.setStyleSheet("background:#7a2f00;color:white;padding:8px;font-weight:700;")
        root.addWidget(banner)
        splitter = QtWidgets.QSplitter()
        root.addWidget(splitter, 1)
        left_scroll = QtWidgets.QScrollArea(widgetResizable=True)
        left_scroll.setMinimumWidth(500)
        left = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left)
        left_scroll.setWidget(left)
        splitter.addWidget(left_scroll)
        splitter.addWidget(self._build_right())
        splitter.setSizes([520, 950])
        self._build_device_group()
        self._build_manual_group()
        self._build_scan_group()
        self._build_actions()
        self.left_layout.addStretch(1)
        self._build_status(root)

    def _build_device_group(self) -> None:
        box = QtWidgets.QGroupBox("设备（安全 Mock）")
        form = QtWidgets.QFormLayout(box)
        form.addRow("当前模式", QtWidgets.QLabel("MOCK（真实硬件入口未接入）"))
        form.addRow("位移台", QtWidgets.QLabel("MockFiveAxisStage · 相机2轴 + 物镜3轴"))
        form.addRow("扫描相机", QtWidgets.QLabel("MOCK-GUI-001 · Mono16"))
        self.exposure = spin(float(self.config["exposure_ms"]), minimum=0.01, maximum=10000, decimals=3)
        self.exposure.setSuffix(" ms")
        form.addRow("曝光时间", self.exposure)
        self.left_layout.addWidget(box)

    def _build_manual_group(self) -> None:
        box = QtWidgets.QGroupBox("探测物镜 XYZ（扫描坐标）")
        grid = QtWidgets.QGridLayout(box)
        self.position_labels: dict[str, QtWidgets.QLabel] = {}
        self.target_spins: dict[str, QtWidgets.QDoubleSpinBox] = {}
        for column, axis in enumerate(("X", "Y", "Z")):
            header = QtWidgets.QLabel(OBJECTIVE_AXIS_TEXT[axis])
            header.setWordWrap(True)
            grid.addWidget(header, 0, column + 1, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
            label = QtWidgets.QLabel("0.0000 mm")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.position_labels[axis] = label
            grid.addWidget(label, 1, column + 1)
        grid.addWidget(QtWidgets.QLabel("当前位置*"), 1, 0)
        self.manual_step = spin(float(self.config["manual_step_mm"]), minimum=0.0001, maximum=100, decimals=4)
        self.manual_step.setSuffix(" mm")
        grid.addWidget(QtWidgets.QLabel("步长"), 2, 0)
        grid.addWidget(self.manual_step, 2, 1, 1, 3)
        self.jog_buttons: list[QtWidgets.QPushButton] = []
        for column, axis in enumerate(("X", "Y", "Z")):
            minus = QtWidgets.QPushButton(f"{axis}−")
            plus = QtWidgets.QPushButton(f"{axis}+")
            minus.setAutoRepeat(False); plus.setAutoRepeat(False)
            minus.setText(f"{axis}-")
            minus.clicked.connect(lambda _=False, a=axis: self._jog(a, -1))
            plus.clicked.connect(lambda _=False, a=axis: self._jog(a, 1))
            grid.addWidget(minus, 3, column + 1); grid.addWidget(plus, 4, column + 1)
            self.jog_buttons.extend([minus, plus])
            target = spin(0.0)
            self.target_spins[axis] = target
            grid.addWidget(target, 5, column + 1)
        grid.addWidget(QtWidgets.QLabel("绝对目标"), 5, 0)
        self.move_button = QtWidgets.QPushButton("移动到目标（Mock）")
        self.move_button.clicked.connect(self._move_to_targets)
        grid.addWidget(self.move_button, 6, 1, 1, 3)
        note = QtWidgets.QLabel("* 轴号与方向已按现场观察录入；当前仍仅为 Mock，真实运动未开放")
        note.setWordWrap(True)
        note.setStyleSheet("color:#a85d00")
        grid.addWidget(note, 7, 0, 1, 4)
        self.left_layout.addWidget(box)

        camera_box = QtWidgets.QGroupBox("探测相机 XY（固定定位，不参与扫描计划）")
        camera_grid = QtWidgets.QGridLayout(camera_box)
        self.camera_position_labels: dict[str, QtWidgets.QLabel] = {}
        self.camera_target_spins: dict[str, QtWidgets.QDoubleSpinBox] = {}
        for column, axis in enumerate(("X", "Y")):
            header = QtWidgets.QLabel(CAMERA_AXIS_TEXT[axis])
            header.setWordWrap(True)
            camera_grid.addWidget(header, 0, column + 1, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
            label = QtWidgets.QLabel("0.0000 mm")
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.camera_position_labels[axis] = label
            camera_grid.addWidget(label, 1, column + 1)
        camera_grid.addWidget(QtWidgets.QLabel("当前位置*"), 1, 0)
        self.camera_manual_step = spin(
            float(self.config["camera_manual_step_mm"]), minimum=0.0001, maximum=100, decimals=4
        )
        self.camera_manual_step.setSuffix(" mm")
        camera_grid.addWidget(QtWidgets.QLabel("步长"), 2, 0)
        camera_grid.addWidget(self.camera_manual_step, 2, 1, 1, 2)
        self.camera_jog_buttons: list[QtWidgets.QPushButton] = []
        for column, axis in enumerate(("X", "Y")):
            minus = QtWidgets.QPushButton(f"{axis}−")
            plus = QtWidgets.QPushButton(f"{axis}+")
            minus.setAutoRepeat(False); plus.setAutoRepeat(False)
            minus.setText(f"{axis}-")
            minus.clicked.connect(lambda _=False, a=axis: self._camera_jog(a, -1))
            plus.clicked.connect(lambda _=False, a=axis: self._camera_jog(a, 1))
            camera_grid.addWidget(minus, 3, column + 1); camera_grid.addWidget(plus, 4, column + 1)
            self.camera_jog_buttons.extend([minus, plus])
            target = spin(0.0)
            self.camera_target_spins[axis] = target
            camera_grid.addWidget(target, 5, column + 1)
        camera_grid.addWidget(QtWidgets.QLabel("绝对目标"), 5, 0)
        self.camera_move_button = QtWidgets.QPushButton("相机移动到目标（Mock）")
        self.camera_move_button.clicked.connect(self._move_camera_to_targets)
        camera_grid.addWidget(self.camera_move_button, 6, 1, 1, 2)
        camera_note = QtWidgets.QLabel("* 扫描期间锁定；Mock 光斑使用物镜横向位置 − 相机位置")
        camera_note.setWordWrap(True)
        camera_note.setStyleSheet("color:#a85d00")
        camera_grid.addWidget(camera_note, 7, 0, 1, 3)
        self.left_layout.addWidget(camera_box)

    def _build_scan_group(self) -> None:
        box = QtWidgets.QGroupBox("扫描计划")
        form = QtWidgets.QFormLayout(box)
        self.scan_type = QtWidgets.QComboBox()
        self.scan_type.addItems(["XY", "XZ", "YZ", "X range", "Y range", "Z range", "X list", "Y list", "Z list"])
        self.scan_type.setCurrentText(str(self.config["scan_type"]))
        form.addRow("扫描类型", self.scan_type)
        self.axis1_label = QtWidgets.QLabel("X 起/止/步长")
        self.axis1 = [spin(float(self.config[key])) for key in ("horizontal_start", "horizontal_stop", "horizontal_step")]
        row1 = QtWidgets.QHBoxLayout(); [row1.addWidget(item) for item in self.axis1]
        form.addRow(self.axis1_label, row1)
        self.axis2_label = QtWidgets.QLabel("Y 起/止/步长")
        self.axis2 = [spin(float(self.config[key])) for key in ("vertical_start", "vertical_stop", "vertical_step")]
        row2 = QtWidgets.QHBoxLayout(); [row2.addWidget(item) for item in self.axis2]
        form.addRow(self.axis2_label, row2)
        self.list_values = QtWidgets.QLineEdit("-0.4,-0.1,0.2,0.45")
        self.list_values.setVisible(False)
        self.list_label = QtWidgets.QLabel("位置列表 (mm)"); self.list_label.setVisible(False)
        form.addRow(self.list_label, self.list_values)
        self.fixed = spin(float(self.config["fixed_value_mm"]))
        form.addRow("固定轴位置 (mm)", self.fixed)
        self.settling = spin(float(self.config["settling_ms"]), minimum=0, maximum=60000, decimals=1)
        self.settling.setSuffix(" ms")
        form.addRow("稳定等待", self.settling)
        # QMainWindow 已有 metric() 虚方法，控件不能命名为 self.metric。
        self.metric_combo = QtWidgets.QComboBox(); self.metric_combo.addItems(["mean", "sum"]); self.metric_combo.setCurrentText(str(self.config["metric"]))
        form.addRow("ROI 指标", self.metric_combo)
        roi_row = QtWidgets.QHBoxLayout()
        self.roi_spins: list[QtWidgets.QSpinBox] = []
        for value in self.config["roi_xywh"]:
            item = QtWidgets.QSpinBox(); item.setRange(0, 100000); item.setValue(int(value)); roi_row.addWidget(item); self.roi_spins.append(item)
        form.addRow("ROI x/y/w/h", roi_row)
        out_row = QtWidgets.QHBoxLayout()
        self.output_edit = QtWidgets.QLineEdit(str(self.config["output_dir"]))
        browse = QtWidgets.QPushButton("选择…"); browse.clicked.connect(self._choose_output)
        out_row.addWidget(self.output_edit, 1); out_row.addWidget(browse)
        form.addRow("保存目录", out_row)
        self.plan_summary = QtWidgets.QLabel()
        self.plan_summary.setWordWrap(True)
        form.addRow("扫描前估算", self.plan_summary)
        self.scan_inputs = [self.scan_type, *self.axis1, *self.axis2, self.list_values, self.fixed, self.settling, self.metric_combo, *self.roi_spins, self.output_edit, self.exposure]
        self.left_layout.addWidget(box)

    def _build_actions(self) -> None:
        box = QtWidgets.QGroupBox("运行与回读")
        grid = QtWidgets.QGridLayout(box)
        self.start_button = QtWidgets.QPushButton("开始 Mock 扫描")
        self.pause_button = QtWidgets.QPushButton("暂停")
        self.resume_button = QtWidgets.QPushButton("继续")
        self.stop_button = QtWidgets.QPushButton("停止")
        self.open_button = QtWidgets.QPushButton("打开已有扫描目录…")
        grid.addWidget(self.start_button, 0, 0, 1, 2)
        grid.addWidget(self.pause_button, 1, 0); grid.addWidget(self.resume_button, 1, 1)
        grid.addWidget(self.stop_button, 2, 0, 1, 2); grid.addWidget(self.open_button, 3, 0, 1, 2)
        self.left_layout.addWidget(box)

    def _build_right(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget(); layout = QtWidgets.QVBoxLayout(widget)
        upper_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        heat_container = QtWidgets.QWidget(); heat_layout = QtWidgets.QHBoxLayout(heat_container); heat_layout.setContentsMargins(0,0,0,0)
        self.main_plot = pg.PlotWidget(title="主图（尚未扫描）")
        self.main_plot.showGrid(x=True, y=True, alpha=0.25)
        self.main_plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.main_plot.getAxis("left").enableAutoSIPrefix(False)
        self.heat_item = pg.ImageItem(axisOrder="row-major")
        self.main_plot.addItem(self.heat_item)
        self.curve = self.main_plot.plot([], [], pen=pg.mkPen("#31b7ff", width=2), symbol="o", symbolSize=7)
        self.cross_x = pg.InfiniteLine(angle=90, pen=pg.mkPen("w", style=QtCore.Qt.PenStyle.DashLine))
        self.cross_y = pg.InfiniteLine(angle=0, pen=pg.mkPen("w", style=QtCore.Qt.PenStyle.DashLine))
        self.main_plot.addItem(self.cross_x); self.main_plot.addItem(self.cross_y)
        heat_layout.addWidget(self.main_plot, 1)
        self.histogram = pg.HistogramLUTWidget(); self.histogram.setImageItem(self.heat_item)
        self.histogram.gradient.loadPreset("viridis")
        heat_layout.addWidget(self.histogram)
        upper_split.addWidget(heat_container)
        self.profile_plot = pg.PlotWidget(title="选中点所在行/列剖面")
        self.profile_plot.addLegend(); self.profile_row = self.profile_plot.plot([], [], pen="#ffcc4d", name="行")
        self.profile_col = self.profile_plot.plot([], [], pen="#ff5c93", name="列")
        upper_split.addWidget(self.profile_plot); upper_split.setSizes([560, 220])
        layout.addWidget(upper_split, 3)
        raw_box = QtWidgets.QGroupBox("原始相机图像（显示伪彩不修改 TIFF / 指标）")
        raw_layout = QtWidgets.QVBoxLayout(raw_box)
        self.raw_plot = pg.PlotWidget(); self.raw_plot.invertY(True); self.raw_plot.setAspectLocked(True)
        self.raw_item = pg.ImageItem(axisOrder="row-major"); self.raw_plot.addItem(self.raw_item)
        self.roi_item = pg.RectROI((80, 64), (160, 128), pen=pg.mkPen("#ffcc00", width=2), movable=False, resizable=False)
        self.raw_plot.addItem(self.roi_item); raw_layout.addWidget(self.raw_plot, 1)
        browse = QtWidgets.QHBoxLayout()
        self.view_mode = QtWidgets.QComboBox(); self.view_mode.addItems(["跟随最新", "固定选择"])
        self.raw_colormap = QtWidgets.QComboBox(); self.raw_colormap.addItems(["gray", "viridis", "plasma", "inferno"])
        self.raw_colormap.setCurrentText(str(self.config.get("colormap", "viridis")))
        self.point_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.point_slider.setRange(1, 1)
        self.point_spin = QtWidgets.QSpinBox(); self.point_spin.setRange(1, 1)
        browse.addWidget(self.view_mode); browse.addWidget(QtWidgets.QLabel("伪彩")); browse.addWidget(self.raw_colormap)
        browse.addWidget(QtWidgets.QLabel("point_id")); browse.addWidget(self.point_slider, 1); browse.addWidget(self.point_spin)
        raw_layout.addLayout(browse)
        self.image_info = QtWidgets.QLabel("无图像"); self.image_info.setWordWrap(True); raw_layout.addWidget(self.image_info)
        layout.addWidget(raw_box, 2)
        return widget

    def _build_status(self, root: QtWidgets.QVBoxLayout) -> None:
        line = QtWidgets.QHBoxLayout()
        self.state_label = QtWidgets.QLabel("空闲"); self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 100)
        self.count_label = QtWidgets.QLabel("0 / 0"); self.directory_label = QtWidgets.QLabel("输出：—")
        self.error_label = QtWidgets.QLabel(); self.error_label.setStyleSheet("color:#d9534f")
        line.addWidget(QtWidgets.QLabel("状态：")); line.addWidget(self.state_label); line.addWidget(self.progress, 1); line.addWidget(self.count_label); line.addWidget(self.directory_label, 2)
        root.addLayout(line); root.addWidget(self.error_label)

    def _connect_signals(self) -> None:
        self.scan_type.currentTextChanged.connect(self._update_scan_labels)
        for item in self.scan_inputs:
            if isinstance(item, QtWidgets.QComboBox): item.currentTextChanged.connect(self._refresh_estimate)
            elif isinstance(item, QtWidgets.QLineEdit): item.textChanged.connect(self._refresh_estimate)
            else: item.valueChanged.connect(self._refresh_estimate)
        self.start_button.clicked.connect(self.start_scan)
        self.pause_button.clicked.connect(self._pause)
        self.resume_button.clicked.connect(self.controller.resume)
        self.stop_button.clicked.connect(self.controller.request_stop)
        self.open_button.clicked.connect(self._open_dialog)
        self.bridge.state.connect(self._set_state)
        self.bridge.position.connect(self._update_position)
        self.bridge.point_saved.connect(self._on_point_saved)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.finished.connect(self._on_finished)
        self.bridge.failed.connect(self._on_failed)
        self.point_slider.valueChanged.connect(self._user_select_point)
        self.point_spin.valueChanged.connect(self._user_select_point)
        self.raw_colormap.currentTextChanged.connect(self._set_raw_colormap)
        self.main_plot.scene().sigMouseClicked.connect(self._main_clicked)
        self._set_raw_colormap(self.raw_colormap.currentText())

    def _update_scan_labels(self) -> None:
        kind = self.scan_type.currentText()
        plane = kind in PLANE_AXES
        is_list = kind.endswith("list")
        if plane:
            h, v = PLANE_AXES[kind]; self.axis1_label.setText(f"{OBJECTIVE_AXIS_TEXT[h]} 起/止/步长"); self.axis2_label.setText(f"{OBJECTIVE_AXIS_TEXT[v]} 起/止/步长")
        else:
            axis = kind[0]; self.axis1_label.setText(f"{OBJECTIVE_AXIS_TEXT[axis]} 起/止/步长"); self.axis2_label.setText("第二扫描轴（单轴不使用）")
        for widget in self.axis2: widget.setEnabled(plane)
        for widget in self.axis1: widget.setVisible(not is_list)
        self.axis1_label.setVisible(not is_list)
        self.list_values.setVisible(is_list); self.list_label.setVisible(is_list)
        self._refresh_estimate()

    def _plan_from_controls(self) -> SpatialScanPlan:
        common = dict(
            save_root=Path(self.output_edit.text()).expanduser(), exposure_us=self.exposure.value() * 1000.0,
            settling_time_s=self.settling.value() / 1000.0, roi_xywh=tuple(item.value() for item in self.roi_spins),
            metric=self.metric_combo.currentText(), experiment_name="gui_mock", camera_serial=self.camera.get_serial_number(),
        )
        kind = self.scan_type.currentText()
        if kind in PLANE_AXES:
            return SpatialScanPlan.from_plane(
                plane=kind, horizontal_start=self.axis1[0].value(), horizontal_stop=self.axis1[1].value(), horizontal_step=self.axis1[2].value(),
                vertical_start=self.axis2[0].value(), vertical_stop=self.axis2[1].value(), vertical_step=self.axis2[2].value(), fixed_value_mm=self.fixed.value(), **common,
            )
        axis = kind[0]
        fixed = self.stage.get_positions()
        fixed[axis] = self.fixed.value()
        if kind.endswith("list"):
            values = [float(value.strip()) for value in self.list_values.text().split(",") if value.strip()]
            return SpatialScanPlan.from_axis_list(axis=axis, values=values, fixed_positions_mm=fixed, **common)
        return SpatialScanPlan.from_axis_range(
            axis=axis, start=self.axis1[0].value(), stop=self.axis1[1].value(), step=self.axis1[2].value(), fixed_positions_mm=fixed, **common,
        )

    def _refresh_estimate(self, *_: object) -> None:
        try:
            plan = self._plan_from_controls()
            raw_bytes = plan.total_points * self.camera.image_shape[0] * self.camera.image_shape[1] * 2
            self.plan_summary.setText(f"{plan.total_points} 点 / {plan.total_points} 幅原图；未压缩像素约 {raw_bytes / 1024**2:.2f} MiB（另有 TIFF/JSON/CSV/MAT 开销）")
            self.start_button.setEnabled(self._thread is None)
        except Exception as exc:
            self.plan_summary.setText(f"参数错误：{exc}")
            self.start_button.setEnabled(False)

    def start_scan(self) -> None:
        try:
            plan = self._plan_from_controls()
            problems = self.controller.preflight(plan, image_shape=self.camera.image_shape)
            if problems: raise ValueError("；".join(problems))
        except Exception as exc:
            self._on_failed(str(exc)); return
        self._plan = plan; self._session = None; self._records.clear(); self._images.clear(); self._last_session_dir = None
        self._metric_data = np.full(plan.grid_shape if plan.grid_shape else (plan.total_points,), np.nan, dtype=float)
        self.error_label.clear(); self.progress.setValue(0); self.count_label.setText(f"0 / {plan.total_points}")
        self.point_slider.setRange(1, plan.total_points); self.point_spin.setRange(1, plan.total_points)
        self._render_main(); self._lock_controls(True)
        thread = QtCore.QThread(self); worker = ScanWorker(self.controller, plan, self.bridge); worker.moveToThread(thread)
        thread.started.connect(worker.run); self.bridge.finished.connect(thread.quit); self.bridge.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater); thread.finished.connect(self._thread_done); self._thread = thread; self._worker = worker; thread.start()

    def _thread_done(self) -> None:
        if self._thread: self._thread.deleteLater()
        self._thread = None; self._lock_controls(False); self._refresh_estimate()

    def _lock_controls(self, locked: bool) -> None:
        for item in self.scan_inputs: item.setEnabled(not locked)
        for button in self.jog_buttons: button.setEnabled(not locked)
        self.move_button.setEnabled(not locked)
        for button in self.camera_jog_buttons: button.setEnabled(not locked)
        self.camera_move_button.setEnabled(not locked)
        self.open_button.setEnabled(not locked)
        self.start_button.setEnabled(not locked)
        self.pause_button.setEnabled(locked); self.resume_button.setEnabled(locked); self.stop_button.setEnabled(locked)

    def _pause(self) -> None:
        self.controller.request_pause(); self.state_label.setText("暂停请求（当前点保存后生效）")

    @QtCore.Slot(object)
    def _set_state(self, state: ScanState) -> None:
        self.state_label.setText(STATE_TEXT[state])
        active = state not in {ScanState.IDLE, ScanState.STOPPED, ScanState.COMPLETED, ScanState.ERROR}
        self.pause_button.setEnabled(active and state is not ScanState.PAUSED)
        self.resume_button.setEnabled(state is ScanState.PAUSED or active)
        self.stop_button.setEnabled(active or state is ScanState.PAUSED)

    @QtCore.Slot(object)
    def _update_position(self, positions: dict[str, float]) -> None:
        for axis, value in positions.items():
            if axis in self.position_labels:
                self.position_labels[axis].setText(f"{value:.4f} mm")

    def _update_camera_position(self, positions: dict[str, float]) -> None:
        for axis, value in positions.items():
            if axis in self.camera_position_labels:
                self.camera_position_labels[axis].setText(f"{value:.4f} mm")

    def _update_all_positions(self) -> None:
        self._update_position(self.stage.get_positions())
        self._update_camera_position(self.stage.get_camera_positions())

    @QtCore.Slot(object, object)
    def _on_point_saved(self, record: dict[str, object], image: np.ndarray) -> None:
        point_id = int(record["point_id"]); self._records[point_id] = record; self._images = {point_id: image}
        if self._metric_data is not None:
            if self._plan and self._plan.is_plane:
                self._metric_data[int(record["row"]), int(record["col"])] = float(record["metric_value"])
            else: self._metric_data[point_id - 1] = float(record["metric_value"])
        self._render_main()
        if self.view_mode.currentText() == "跟随最新": self._select_point(point_id)

    @QtCore.Slot(int, int)
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setValue(round(done * 100 / total)); self.count_label.setText(f"{done} / {total} ({done * 100 / total:.1f}%)")

    @QtCore.Slot(object)
    def _on_finished(self, directory: Path | None) -> None:
        if directory:
            self._last_session_dir = Path(directory); self.directory_label.setText(f"输出：{directory}")
            try: self._session = SpatialSession.open(Path(directory))
            except Exception as exc: self.error_label.setText(f"扫描已结束，但回读检查失败：{exc}")
        self.scan_finished.emit(directory)

    @QtCore.Slot(str)
    def _on_failed(self, message: str) -> None:
        self.error_label.setText(message); self._set_state(ScanState.ERROR)

    def _render_main(self) -> None:
        if self._plan is None or self._metric_data is None: return
        if self._plan.is_plane:
            self.curve.setData([], []); self.heat_item.show(); self.histogram.show()
            finite = self._metric_data[np.isfinite(self._metric_data)]
            if finite.size:
                low, high = float(np.min(finite)), float(np.max(finite))
                if math.isclose(low, high): high = low + 1.0
                self.heat_item.setImage(self._metric_data, autoLevels=False, levels=(low, high))
            else:
                self.heat_item.clear()
            h, v = self._plan.horizontal_values, self._plan.vertical_values
            dx = h[1] - h[0] if len(h) > 1 else 1.0; dy = v[1] - v[0] if len(v) > 1 else 1.0
            transform = QtGui.QTransform(); transform.translate(h[0] - dx / 2, v[0] - dy / 2); transform.scale(dx, dy); self.heat_item.setTransform(transform)
            self.main_plot.setLabel("bottom", f"{self._plan.horizontal_axis} (mm)"); self.main_plot.setLabel("left", f"{self._plan.vertical_axis} (mm)")
            self.main_plot.setTitle(f"{self._plan.scan_type} 热图 · NaN=未采集 · 固定 {self._plan.fixed_axis}={self._plan.fixed_value_mm:g} mm")
        else:
            self.heat_item.hide(); self.histogram.hide(); self.curve.setData(self._plan.horizontal_values, self._metric_data)
            self.main_plot.setLabel("bottom", f"{self._plan.horizontal_axis} (mm)"); self.main_plot.setLabel("left", self._plan.metric)
            self.main_plot.setTitle(f"{self._plan.scan_type} 单轴曲线 · NaN=未采集")

    def _select_point(self, point_id: int) -> None:
        if point_id < 1: return
        for widget in (self.point_slider, self.point_spin):
            blocker = QtCore.QSignalBlocker(widget); widget.setValue(point_id); del blocker
        record = self._records.get(point_id)
        image = self._images.get(point_id)
        if record is not None and image is None and record.get("_session_dir") and record.get("filename"):
            try:
                import tifffile
                image = tifffile.imread(Path(str(record["_session_dir"])) / str(record["filename"]))
            except Exception as exc:
                self.error_label.setText(f"读取运行中已保存原图失败：{exc}")
        if self._session is not None and (record is None or image is None):
            record = next((r for r in self._session.successful_records if int(r["point_id"]) == point_id), record)
            if record is not None and image is None:
                try: image = self._session.load_image(point_id)
                except Exception as exc: self.error_label.setText(str(exc)); return
        if record is None or image is None:
            self.image_info.setText(f"point_id={point_id} 未采集或采集失败"); return
        self._selected_point_id = point_id; self.raw_item.setImage(image, autoLevels=True)
        roi = tuple(int(record[name]) for name in ("roi_x", "roi_y", "roi_width", "roi_height"))
        self.roi_item.setPos((roi[0], roi[1])); self.roi_item.setSize((roi[2], roi[3]))
        targets = ", ".join(f"{a}={float(record[f'target_{a.lower()}_mm']):.4f}" for a in ("X","Y","Z"))
        self.image_info.setText(f"已保存扫描点 · point_id={point_id} · {targets} mm · {Path(str(record['filename'])).name} · 指标={float(record['metric_value']):.3f}")
        self._update_selection_graphics(record)

    def _user_select_point(self, point_id: int) -> None:
        self.view_mode.setCurrentText("固定选择")
        self._select_point(point_id)

    def _set_raw_colormap(self, name: str) -> None:
        self.raw_item.setColorMap(pg.colormap.get(name))

    def _update_selection_graphics(self, record: dict[str, object]) -> None:
        x = float(record[f"target_{self._plan.horizontal_axis.lower()}_mm"]) if self._plan and self._plan.horizontal_axis else 0
        if self._plan and self._plan.is_plane:
            y = float(record[f"target_{self._plan.vertical_axis.lower()}_mm"]); self.cross_x.setValue(x); self.cross_y.setValue(y)
            row, col = int(record["row"]), int(record["col"])
            self.profile_row.setData(self._plan.horizontal_values, self._metric_data[row, :]); self.profile_col.setData(self._plan.vertical_values, self._metric_data[:, col])
        else:
            self.cross_x.setValue(x); self.profile_row.setData([], []); self.profile_col.setData([], [])

    def _main_clicked(self, event: object) -> None:
        if self._plan is None or not self._records: return
        position = self.main_plot.plotItem.vb.mapSceneToView(event.scenePos())
        if self._plan.is_plane:
            col = int(np.argmin(np.abs(np.asarray(self._plan.horizontal_values) - position.x())))
            row = int(np.argmin(np.abs(np.asarray(self._plan.vertical_values) - position.y())))
            point_id = row * len(self._plan.horizontal_values) + col + 1
        else:
            point_id = int(np.argmin(np.abs(np.asarray(self._plan.horizontal_values) - position.x()))) + 1
        self.view_mode.setCurrentText("固定选择"); self._select_point(point_id)

    def open_session(self, directory: Path) -> None:
        session = SpatialSession.open(directory); self._session = session; self._records = {int(r["point_id"]): r for r in session.successful_records}; self._images.clear()
        cfg = session.config; points = cfg["points"]
        # 回读时只重建显示所需的不可变计划；不连接或移动任何设备。
        self._plan = SpatialScanPlan(
            scan_type=str(cfg["scan_type"]), points=[SpatialPoint(**p) for p in points],
            save_root=Path(cfg["save_root"]), exposure_us=float(cfg["exposure_us"]), settling_time_s=float(cfg["settling_time_s"]),
            motion_timeout_s=float(cfg["motion_timeout_s"]), roi_xywh=tuple(cfg["roi_xywh"]), metric=str(cfg["metric"]),
            experiment_name=str(cfg["experiment_name"]), camera_serial=str(cfg["camera_serial"]), horizontal_axis=cfg.get("horizontal_axis"),
            vertical_axis=cfg.get("vertical_axis"), horizontal_values=list(cfg.get("horizontal_values", [])), vertical_values=list(cfg.get("vertical_values", [])),
            fixed_axis=cfg.get("fixed_axis"), fixed_value_mm=cfg.get("fixed_value_mm"),
        )
        self._metric_data = np.full(self._plan.grid_shape if self._plan.grid_shape else (self._plan.total_points,), np.nan)
        for record in session.successful_records:
            if self._plan.is_plane: self._metric_data[int(record["row"]), int(record["col"])] = float(record["metric_value"])
            else: self._metric_data[int(record["point_id"]) - 1] = float(record["metric_value"])
        self.point_slider.setRange(1, self._plan.total_points); self.point_spin.setRange(1, self._plan.total_points)
        completed = len(session.successful_records)
        self.progress.setValue(round(completed * 100 / self._plan.total_points))
        self.count_label.setText(f"{completed} / {self._plan.total_points}")
        self._last_session_dir = directory; self.directory_label.setText(f"已打开：{directory}"); self._render_main()
        if session.successful_records: self._select_point(int(session.successful_records[0]["point_id"]))

    def _open_dialog(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 GUI-M1 扫描目录")
        if selected:
            try: self.open_session(Path(selected))
            except Exception as exc: self._on_failed(str(exc))

    def _choose_output(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "选择保存根目录")
        if selected: self.output_edit.setText(selected)

    def _jog(self, axis: str, sign: int) -> None:
        targets = self.stage.get_positions(); targets[axis] += sign * self.manual_step.value(); self._start_move(targets, group="objective")

    def _camera_jog(self, axis: str, sign: int) -> None:
        targets = self.stage.get_camera_positions(); targets[axis] += sign * self.camera_manual_step.value(); self._start_move(targets, group="camera")

    def _move_to_targets(self) -> None:
        self._start_move({axis: item.value() for axis, item in self.target_spins.items()}, group="objective")

    def _move_camera_to_targets(self) -> None:
        self._start_move({axis: item.value() for axis, item in self.camera_target_spins.items()}, group="camera")

    def _start_move(self, targets: dict[str, float], *, group: str) -> None:
        if self._move_thread is not None or self._thread is not None: self._on_failed("设备忙，拒绝移动命令"); return
        for button in self.jog_buttons: button.setEnabled(False)
        self.move_button.setEnabled(False)
        for button in self.camera_jog_buttons: button.setEnabled(False)
        self.camera_move_button.setEnabled(False)
        thread = QtCore.QThread(self); worker = MoveWorker(self.controller, targets, group); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.done.connect(self._move_done); worker.failed.connect(self._on_failed)
        worker.done.connect(thread.quit); worker.failed.connect(thread.quit); thread.finished.connect(worker.deleteLater); thread.finished.connect(self._move_thread_done)
        self._move_thread, self._move_worker = thread, worker; thread.start()

    def _move_done(self, _positions: dict[str, float]) -> None: self._update_all_positions()

    def _move_thread_done(self) -> None:
        if self._move_thread: self._move_thread.deleteLater()
        self._move_thread = None
        for button in self.jog_buttons: button.setEnabled(True)
        self.move_button.setEnabled(True)
        for button in self.camera_jog_buttons: button.setEnabled(True)
        self.camera_move_button.setEnabled(True)

    def _config_from_controls(self) -> dict[str, object]:
        return {
            "schema_version": 1, "device_mode": "MOCK", "exposure_ms": self.exposure.value(), "manual_step_mm": self.manual_step.value(),
            "camera_manual_step_mm": self.camera_manual_step.value(),
            "scan_type": self.scan_type.currentText(), "horizontal_start": self.axis1[0].value(), "horizontal_stop": self.axis1[1].value(), "horizontal_step": self.axis1[2].value(),
            "vertical_start": self.axis2[0].value(), "vertical_stop": self.axis2[1].value(), "vertical_step": self.axis2[2].value(), "fixed_value_mm": self.fixed.value(),
            "settling_ms": self.settling.value(), "roi_xywh": [item.value() for item in self.roi_spins], "metric": self.metric_combo.currentText(),
            "output_dir": self.output_edit.text(), "colormap": self.raw_colormap.currentText(),
        }

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._thread is not None:
            self.controller.request_stop()
            if not self._thread.wait(6000):
                self.error_label.setText("扫描线程未能在 6 秒内安全退出，窗口保持打开")
                event.ignore(); return
        if self._move_thread is not None:
            self.controller.request_stop()
            if not self._move_thread.wait(6000): event.ignore(); return
        try: save_config_atomic(self.config_path, self._config_from_controls())
        except Exception as exc: self.error_label.setText(f"保存配置失败：{exc}")
        self.camera.disconnect(); self.stage.disconnect(); event.accept()
