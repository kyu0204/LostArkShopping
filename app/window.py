"""메인 창 (HANDOFF §7, §8).

오버레이가 아니다. 일반 QMainWindow, 트레이 상주 없음, 창 닫으면 종료.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from loa import options as loa_options
from loa import quality as q
from loa.export import write_csv
from loa.models import Listing

from .assets import IconFetcher, missing_names, pending_downloads
from .card import CardDelegate
from .search_panel import SearchPanel
from .table import ListingProxy, ListingTableModel
from .worker import CollectWorker

STYLE = """
QLabel#badge {
    font-weight: 600;
    padding: 4px 10px;
    border: 1px solid palette(mid);
    border-radius: 3px;
    background: palette(alternate-base);
}
QLabel#hint  { color: palette(dark); font-size: 11px; }
QLabel#cohort { font-size: 15px; font-weight: 600; }
QLabel#fixed  { color: palette(dark); }
QLabel#hidden_note { color: palette(dark); font-size: 11px; }
QTableView { gridline-color: palette(midlight); }
"""


class MainWindow(QMainWindow):
    def __init__(self, client, options_payload: dict) -> None:
        super().__init__()
        self._client = client
        self._worker: CollectWorker | None = None
        self._listings: list[Listing] = []
        # 연마 등급(하/중/상) 누적 관측. 검색할 때마다 새로 본 값을 합쳐 저장한다.
        self._grades = q.load_upgrade_grades()

        self.setWindowTitle("로스트아크 경매장 매물 비교기")
        self.resize(1240, 780)
        self.setStyleSheet(STYLE)

        splitter = QSplitter(Qt.Horizontal)

        self.panel = SearchPanel(options_payload, self._grades)
        self.panel.search_requested.connect(self._start_search)

        # 스크롤을 달아 폼이 길어져도 창을 밀지 않게 한다
        self.left = QScrollArea()
        self.left.setWidget(self.panel)
        self.left.setWidgetResizable(True)
        self.left.setFrameShape(QScrollArea.NoFrame)
        self.left.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 옵션 이름이 길다 ('세레나데, 신앙, 조화 게이지 획득량 증가').
        # 좁게 잡으면 콤보가 글자를 잘라먹는다.
        self.left.setMinimumWidth(420)
        self.left.setMaximumWidth(620)
        splitter.addWidget(self.left)

        splitter.addWidget(self._build_results())
        splitter.setStretchFactor(1, 1)
        self.splitter = splitter
        self.setCentralWidget(splitter)

        self._build_status()
        self._build_shortcuts()

    # ---- 오른쪽: 결과 ----

    def _build_results(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setSpacing(8)

        head = QHBoxLayout()

        # 검색 폼 접기 — 표시 공간을 넓히는 용도 (F2 로도 토글)
        self.collapse_button = QPushButton("◀ 검색 숨기기")
        self.collapse_button.setCheckable(True)
        self.collapse_button.setToolTip("F2")
        self.collapse_button.toggled.connect(self._on_collapse_toggled)
        head.addWidget(self.collapse_button)

        self.cohort_label = QLabel("검색 조건을 지정하고 Enter")
        self.cohort_label.setObjectName("cohort")
        head.addWidget(self.cohort_label)
        head.addStretch(1)

        # 정렬 축은 하나로 고정하지 않는다 (§7.5)
        head.addWidget(QLabel("정렬"))
        self.sort_field = QComboBox()
        for name in ListingTableModel.SORT_FIELDS:
            self.sort_field.addItem(name)
        self.sort_field.currentTextChanged.connect(self._on_sort_changed)
        head.addWidget(self.sort_field)

        self.sort_desc = QCheckBox("내림차순")
        self.sort_desc.toggled.connect(self._on_sort_changed)
        head.addWidget(self.sort_desc)

        self.hide_bidonly = QCheckBox("입찰 전용 숨김")
        self.hide_bidonly.setChecked(True)  # 기본값 = 켬 (§7.4)
        self.hide_bidonly.toggled.connect(self._on_hide_toggled)
        head.addWidget(self.hide_bidonly)

        self.export_button = QPushButton("CSV 내보내기")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_csv)
        head.addWidget(self.export_button)
        lay.addLayout(head)

        # 검색 조건으로 고정된 값은 열에서 빼고 여기 배지로 (§7.1)
        self.fixed_label = QLabel("")
        self.fixed_label.setObjectName("fixed")
        lay.addWidget(self.fixed_label)

        self.model = ListingTableModel()
        self.proxy = ListingProxy()
        self.proxy.setSourceModel(self.model)

        # 한 행 = 한 카드. QListView 라서 대량 매물에도 가상화가 유지된다.
        self.table = QListView()
        self.table.setModel(self.proxy)
        self.table.setItemDelegate(CardDelegate(self.model, self.table))
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setResizeMode(QListView.Adjust)
        self.table.setUniformItemSizes(True)
        self.table.setSpacing(0)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.clicked.connect(self._on_row_clicked)
        lay.addWidget(self.table, 1)

        self.hidden_note = QLabel("")
        self.hidden_note.setObjectName("hidden_note")
        lay.addWidget(self.hidden_note)
        return panel

    def _build_status(self) -> None:
        bar = self.statusBar()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._cancel)
        bar.addPermanentWidget(self.progress)
        bar.addPermanentWidget(self.cancel_button)
        bar.showMessage("준비됨")

    def _build_shortcuts(self) -> None:
        # Enter — 검색 / Esc — 수집 취소 (§8.5)
        for seq in (QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            QShortcut(seq, self, activated=self.panel.search_button.click)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._cancel)
        QShortcut(QKeySequence(Qt.Key_F2), self, activated=self.collapse_button.toggle)

        quit_action = QAction("종료", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

    # ---- 수집 ----

    def _start_search(self, req: dict) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._special_keys = req.get("special_keys") or set()
        self.panel.set_busy(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, req["max_pages"])
        self.progress.setValue(0)
        self.cancel_button.setVisible(True)
        self.cohort_label.setText(req["label"])
        self.statusBar().showMessage("수집 중…")

        self._worker = CollectWorker(
            self._client, req["category_code"], req["max_pages"], req["payload_kw"]
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, page: int, total: int, valid: int) -> None:
        self.progress.setValue(page)
        self.statusBar().showMessage(
            f"{page}/{self.progress.maximum()} 페이지 · 조건 일치 {total:,}건 중 "
            f"유효 매물 {valid}건"
        )

    def _cancel(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self.statusBar().showMessage("취소 중…")

    def _finish_busy(self) -> None:
        self.panel.set_busy(False)
        self.progress.setVisible(False)
        self.cancel_button.setVisible(False)

    def _on_failed(self, msg: str) -> None:
        self._finish_busy()
        self.statusBar().showMessage("실패")
        QMessageBox.warning(self, "요청 실패", msg)

    def _on_done(self, listings: list) -> None:
        self._finish_busy()
        self._listings = listings

        # 이번 코호트에서 새로 본 등급값을 누적본에 합쳐 다음 실행에도 남긴다
        merged = q.merge_upgrade_grades(self._grades, q.derive_upgrade_grades(listings))
        if merged != self._grades:
            self._grades = merged
            q.save_upgrade_grades(merged, q.DEFAULT_GRADES_PATH)

        self.model.set_listings(listings, self._grades, getattr(self, "_special_keys", set()))
        self.export_button.setEnabled(bool(listings))

        # 로컬 에셋이 없는 매물은 응답의 Icon(cdn-lostark) 주소로 받아 캐시한다.
        # 그리기 중에 네트워크를 타면 창이 얼기 때문에 별도 스레드로 돌린다.
        jobs = pending_downloads(listings)
        if jobs:
            self._fetcher = IconFetcher(jobs, self)
            self._fetcher.fetched.connect(self._on_icons_fetched)
            self._fetcher.start()
        missing = missing_names(listings)
        if missing:
            print(f"[아이콘 없음] {', '.join(missing)}")  # 누락은 조용히 넘기지 않는다

    def _on_icons_fetched(self, count: int) -> None:
        if count:
            self.table.viewport().update()

        badges = self.model.fixed_badges
        self.fixed_label.setText(
            "고정: " + " · ".join(f"{k} {v}" for k, v in badges.items())
            if badges
            else ""
        )

        self._on_sort_changed()
        self._sync_baseline_selection()
        self._update_hidden_note()

        valid = sum(1 for x in listings if not x.is_biddable_only)
        self.statusBar().showMessage(
            f"{len(listings)}건 수집 · 유효 매물 {valid}건 · "
            f"행을 클릭하면 그 매물이 기준이 된다"
        )

    # ---- 기준 행 (§6.2) ----

    def _on_row_clicked(self, proxy_index) -> None:
        source = self.proxy.mapToSource(proxy_index)
        ls = self.model.listing_at(source.row())
        if ls is None:
            return
        if ls.is_biddable_only:
            self.statusBar().showMessage("즉시구매가 없어 기준으로 쓸 수 없다")
            return
        self.model.set_baseline(source.row())
        self.statusBar().showMessage(
            f"기준 변경 · 즉구가 {ls.buy_price:,} · 힘민지 {ls.stat_main:,}"
        )

    def _sync_baseline_selection(self) -> None:
        row = self.model.baseline_row()
        if row is None:
            return
        proxy_index = self.proxy.mapFromSource(self.model.index(row, 0))
        if proxy_index.isValid():
            self.table.setCurrentIndex(proxy_index)
            self.table.scrollTo(proxy_index)

    # ---- 필터 / 내보내기 ----

    def _on_collapse_toggled(self, collapsed: bool) -> None:
        self.left.setVisible(not collapsed)
        self.collapse_button.setText("▶ 검색" if collapsed else "◀ 검색 숨기기")

    def _on_sort_changed(self, *_) -> None:
        field = ListingTableModel.SORT_FIELDS.get(self.sort_field.currentText(), "buy_price")
        self.model.set_sort_field(field)
        self.proxy.sort(0, Qt.DescendingOrder if self.sort_desc.isChecked() else Qt.AscendingOrder)

    def _on_hide_toggled(self, hide: bool) -> None:
        self.proxy.set_hide_bid_only(hide)
        self._update_hidden_note()

    def _update_hidden_note(self) -> None:
        n = sum(1 for x in self._listings if x.is_biddable_only)
        if n and self.hide_bidonly.isChecked():
            # 완전히 사라지면 시장 전체를 봤다고 착각한다 (§7.4)
            self.hidden_note.setText(f"입찰 전용 {n}건 숨김")
        elif n:
            self.hidden_note.setText(f"입찰 전용 {n}건 표시 중 — 계산에서는 제외된다")
        else:
            self.hidden_note.setText("")

    def _export_csv(self) -> None:
        if not self._listings:
            return
        default = self.cohort_label.text().replace(" · ", "_") + ".csv"
        path, _ = QFileDialog.getSaveFileName(self, "CSV 내보내기", default, "CSV (*.csv)")
        if not path:
            return
        n = write_csv(self._listings, Path(path), grades=self._grades)
        self.statusBar().showMessage(f"{n}건 내보냄 → {path}")

    # ---- 종료 ----

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        fetcher = getattr(self, "_fetcher", None)
        if fetcher is not None and fetcher.isRunning():
            fetcher.wait(5000)  # 돌고 있는 스레드를 파괴하면 Qt 가 죽는다
        super().closeEvent(event)


def load_options(client):
    """캐시 우선 (TTL 24h). 앱 시작 시 1회."""
    return loa_options.fetch_options(client)
