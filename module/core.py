import os
import sys
import threading
import time
import logging
import pathlib
import urllib
import math
import webbrowser
import traceback

from PySide6 import QtGui, QtWidgets, QtCore
import pandas as pd
import pyqtgraph
from apscheduler.schedulers.background import BlockingScheduler

from module import introduction
from module import process_toss
from module import thread_toss
from module.user_interface import Ui_MainWindow
from module.worker import manager
from module.worker import collector
from module.worker import transactor
from module.worker import simulator
from module.worker import strategist
from module.instrument.thread_pool_executor import ThreadPoolExecutor
from module.instrument.percent_axis_item import PercentAxisItem
from module.instrument.time_axis_item import TimeAxisItem
from module.instrument.telephone import Telephone
from module.instrument.api_streamer import ApiStreamer
from module.instrument.api_requester import ApiRequester
from module.instrument.log_handler import LogHandler
from module.recipe import outsource
from module.recipe import check_internet
from module.recipe import user_settings
from module.recipe import find_goodies
from module.recipe import examine_data_files
from module.widget.ask_popup import AskPopup
from module.widget.token_selection_frame import TokenSelectionFrame
from module.widget.coin_selection_frame import CoinSelectionFrame
from module.widget.guide_frame import GuideFrame
from module.widget.license_frame import LicenseFrame
from module.widget.symbol_box import SymbolBox


class Window(QtWidgets.QMainWindow, Ui_MainWindow):
    def closeEvent(self, event):  # noqa:N802
        event.ignore()

        def job():
            if not self.should_finalize:
                self.closeEvent = lambda e: e.accept()
                self.undertake(self.close, True)

            if self.should_confirm_closing:
                question = [
                    "Really quit?",
                    "If Solsol is not turned on, data collection gets stopped as well."
                    " Solsol will proceed to finalizations such as closing network"
                    " connections and saving data.",
                    ["Cancel", "Shut down"],
                    False,
                ]
                answer = self.ask(question)

                if answer in (0, 1):
                    return

            total_steps = len(self.finalize_functions)
            done_steps = 0

            self.undertake(lambda: self.gauge.hide(), True)
            self.undertake(lambda: self.board.hide(), True)
            self.closeEvent = lambda e: e.ignore()

            guide_frame = None

            def job():
                nonlocal guide_frame
                guide_frame = GuideFrame(1)
                guide_frame.announce("Finalizing...")
                self.centralWidget().layout().addWidget(guide_frame)

            self.undertake(job, True)

            def job():
                while True:
                    if done_steps == total_steps:
                        text = "Finalization done"
                        self.undertake(lambda t=text: guide_frame.announce(t), True)
                        time.sleep(1)
                        process_toss.terminate_pool()
                        self.closeEvent = lambda e: e.accept()
                        find_goodies.apply()
                        self.undertake(self.close, True)
                        break
                    else:
                        time.sleep(0.1)

            thread_toss.apply_async(job)

            self.scheduler.remove_all_jobs()
            self.scheduler.shutdown()
            ApiStreamer.close_all_forever()

            def job(function):
                nonlocal done_steps
                function()
                done_steps += 1

            thread_toss.map(job, self.finalize_functions)

        thread_toss.apply_async(job)

    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # ■■■■■ global settings of packages ■■■■■

        os.get_terminal_size = lambda *args: os.terminal_size((72, 80))
        pd.set_option("display.precision", 3)
        pd.set_option("display.min_rows", 20)
        pd.set_option("display.max_rows", 20)
        pyqtgraph.setConfigOptions(antialias=True)

        # ■■■■■ basic sizing ■■■■■

        self.resize(0, 0)  # to smallest size possible
        self.splitter.setSizes([3, 1, 1, 2])
        self.splitter_2.setSizes([3, 1, 1, 2])

        # ■■■■■ app closing settings ■■■■■

        self.should_finalize = False
        self.should_confirm_closing = True

        # ■■■■■ hide the main widgets and go on to boot phase ■■■■■

        self.gauge.hide()
        self.board.hide()
        thread_toss.apply_async(self.boot)

    def boot(self):
        try:
            # ■■■■■ start basic things ■■■■■

            examine_data_files.do_first()
            user_settings.load()
            examine_data_files.do()
            user_settings.load()
            check_internet.start_monitoring()

            # ■■■■■ request internet connection ■■■■■

            while not check_internet.connected():
                question = [
                    "No internet connection",
                    "Internet connection is necessary for Solsol to start up.",
                    ["Okay"],
                    False,
                ]
                self.ask(question)
                time.sleep(1)

            # ■■■■■ check app settings ■■■■■

            if user_settings.get_app_settings()["license_key"] is None:
                license_frame = None

                # add temporary widget
                def job():
                    nonlocal license_frame
                    license_frame = LicenseFrame()
                    self.centralWidget().layout().addWidget(license_frame)

                self.undertake(job, True)

                license_frame.done_event.wait()

                # remove temporary widget
                def job():
                    license_frame.setParent(None)

                self.undertake(job, True)

            if user_settings.get_app_settings()["datapath"] is None:
                datapath = ""

                def job():
                    nonlocal datapath
                    file_dialog = QtWidgets.QFileDialog
                    default_path = str(pathlib.Path.home())
                    title_bar_text = "Data folder"
                    datapath = str(
                        file_dialog.getExistingDirectory(
                            self,
                            title_bar_text,
                            default_path,
                        )
                    )

                while datapath == "":
                    question = [
                        "Choose your data folder",
                        "All the data that Solsol produces will go in this folder.",
                        ["Okay"],
                        False,
                    ]
                    self.ask(question)
                    self.undertake(job, True)

                user_settings.apply_app_settings({"datapath": datapath})

            user_settings.load()

            # ■■■■■ check data settings ■■■■■

            if user_settings.get_data_settings()["asset_token"] is None:
                token_selection_frame = None

                # add temporary widget
                def job():
                    nonlocal token_selection_frame
                    token_selection_frame = TokenSelectionFrame()
                    self.centralWidget().layout().addWidget(token_selection_frame)

                self.undertake(job, True)

                token_selection_frame.done_event.wait()

                # remove temporary widget
                def job():
                    token_selection_frame.setParent(None)

                self.undertake(job, True)

            if user_settings.get_data_settings()["target_symbols"] is None:
                coin_selection_frame = None

                # add temporary widget
                def job():
                    nonlocal coin_selection_frame
                    coin_selection_frame = CoinSelectionFrame()
                    self.centralWidget().layout().addWidget(coin_selection_frame)

                self.undertake(job, True)

                coin_selection_frame.done_event.wait()

                # remove temporary widget
                def job():
                    coin_selection_frame.setParent(None)

                self.undertake(job, True)

            user_settings.load()

            # ■■■■■ guide frame ■■■■■

            guide_frame = None

            def job():
                nonlocal guide_frame
                guide_frame = GuideFrame(2)
                guide_frame.announce("Loading...")
                self.centralWidget().layout().addWidget(guide_frame)

            self.undertake(job, True)

            # ■■■■■ multiprocessing ■■■■■

            process_toss.start_pool()

            # ■■■■■ get information about target symbols ■■■■■

            asset_token = user_settings.get_data_settings()["asset_token"]
            target_symbols = user_settings.get_data_settings()["target_symbols"]
            response = ApiRequester().coinstats("GET", "/public/v1/coins")
            about_coins = response["coins"]

            coin_names = {}
            coin_icon_urls = {}
            coin_ranks = {}

            for about_coin in about_coins:
                coin_symbol = about_coin["symbol"]
                coin_names[coin_symbol] = about_coin["name"]
                coin_icon_urls[coin_symbol] = about_coin["icon"]
                coin_ranks[coin_symbol] = about_coin["rank"]

            self.alias_to_symbol = {}
            self.symbol_to_alias = {}

            for symbol in target_symbols:
                coin_symbol = symbol.removesuffix(asset_token)
                coin_name = coin_names.get(coin_symbol, "")
                if coin_name == "":
                    alias = coin_symbol
                else:
                    alias = coin_name
                self.alias_to_symbol[alias] = symbol
                self.symbol_to_alias[symbol] = alias

            # ■■■■■ make widgets according to the data_settings ■■■■■

            token_text_size = 14
            name_text_size = 11
            price_text_size = 9
            detail_text_size = 7

            is_long = len(target_symbols) > 5

            symbol_pixmaps = {}
            for symbol in target_symbols:
                coin_symbol = symbol.removesuffix(asset_token)
                coin_icon_url = coin_icon_urls.get(coin_symbol, "")
                pixmap = QtGui.QPixmap()
                if coin_icon_url != "":
                    image_data = urllib.request.urlopen(coin_icon_url).read()
                    pixmap.loadFromData(image_data)
                else:
                    pixmap.load("./static/icon/blank_coin.png")
                symbol_pixmaps[symbol] = pixmap

            token_icon_url = coin_icon_urls.get(asset_token, "")
            token_pixmap = QtGui.QPixmap()
            image_data = urllib.request.urlopen(token_icon_url).read()
            token_pixmap.loadFromData(image_data)

            def job():
                self.lineEdit.setText(user_settings.get_app_settings()["datapath"])

                icon_label = QtWidgets.QLabel(
                    "",
                    self,
                    alignment=QtCore.Qt.AlignmentFlag.AlignCenter,
                )
                icon_label.setPixmap(token_pixmap)
                icon_label.setScaledContents(True)
                icon_label.setFixedSize(30, 30)
                this_layout = QtWidgets.QHBoxLayout()
                self.verticalLayout_14.addLayout(this_layout)
                this_layout.addWidget(icon_label)
                text = asset_token
                token_font = QtGui.QFont()
                token_font.setPointSize(token_text_size)
                token_font.setWeight(QtGui.QFont.Weight.Bold)
                text_label = QtWidgets.QLabel(
                    text,
                    self,
                    alignment=QtCore.Qt.AlignmentFlag.AlignCenter,
                )
                text_label.setFont(token_font)
                self.verticalLayout_14.addWidget(text_label)
                spacing_text = QtWidgets.QLabel("")
                spacing_text_font = QtGui.QFont()
                spacing_text_font.setPointSize(1)
                spacing_text.setFont(spacing_text_font)
                self.verticalLayout_14.addWidget(spacing_text)
                this_layout = QtWidgets.QHBoxLayout()
                self.verticalLayout_14.addLayout(this_layout)
                divider = QtWidgets.QFrame(self)
                divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                divider.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
                divider.setFixedWidth(320)
                this_layout.addWidget(divider)
                spacing_text = QtWidgets.QLabel("")
                spacing_text_font = QtGui.QFont()
                spacing_text_font.setPointSize(2)
                spacing_text.setFont(spacing_text_font)
                self.verticalLayout_14.addWidget(spacing_text)

                for symbol in target_symbols:
                    icon = QtGui.QIcon()
                    icon.addPixmap(symbol_pixmaps[symbol])
                    alias = self.symbol_to_alias[symbol]
                    self.comboBox_4.addItem(icon, alias)
                    self.comboBox_6.addItem(icon, alias)

                spacer = QtWidgets.QSpacerItem(
                    0,
                    0,
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Minimum,
                )
                self.horizontalLayout_20.addItem(spacer)
                spacer = QtWidgets.QSpacerItem(
                    0,
                    0,
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Minimum,
                )
                self.horizontalLayout_17.addItem(spacer)
                self.price_labels = {}
                for turn, symbol in enumerate(target_symbols):
                    coin_symbol = symbol.removesuffix(asset_token)
                    coin_rank = coin_ranks.get(coin_symbol, 0)
                    symbol_box = SymbolBox()
                    if is_long and turn + 1 > math.floor(len(target_symbols) / 2):
                        self.horizontalLayout_17.addWidget(symbol_box)
                    else:
                        self.horizontalLayout_20.addWidget(symbol_box)
                    inside_layout = QtWidgets.QVBoxLayout(symbol_box)
                    spacer = QtWidgets.QSpacerItem(
                        0,
                        0,
                        QtWidgets.QSizePolicy.Policy.Minimum,
                        QtWidgets.QSizePolicy.Policy.Expanding,
                    )
                    inside_layout.addItem(spacer)
                    icon_label = QtWidgets.QLabel(
                        alignment=QtCore.Qt.AlignmentFlag.AlignCenter,
                    )
                    this_layout = QtWidgets.QHBoxLayout()
                    inside_layout.addLayout(this_layout)
                    icon_label.setPixmap(symbol_pixmaps[symbol])
                    icon_label.setScaledContents(True)
                    icon_label.setFixedSize(50, 50)
                    icon_label.setMargin(5)
                    this_layout.addWidget(icon_label)
                    name_label = QtWidgets.QLabel(
                        self.symbol_to_alias[symbol],
                        alignment=QtCore.Qt.AlignmentFlag.AlignCenter,
                    )
                    name_font = QtGui.QFont()
                    name_font.setPointSize(name_text_size)
                    name_font.setWeight(QtGui.QFont.Weight.Bold)
                    name_label.setFont(name_font)
                    inside_layout.addWidget(name_label)
                    price_label = QtWidgets.QLabel(
                        "",
                        alignment=QtCore.Qt.AlignmentFlag.AlignCenter,
                    )
                    price_font = QtGui.QFont()
                    price_font.setPointSize(price_text_size)
                    price_font.setWeight(QtGui.QFont.Weight.Bold)
                    price_label.setFont(price_font)
                    inside_layout.addWidget(price_label)
                    if coin_rank == 0:
                        text = coin_symbol
                    else:
                        text = f"{coin_rank} - {coin_symbol}"
                    detail_label = QtWidgets.QLabel(
                        text,
                        alignment=QtCore.Qt.AlignmentFlag.AlignCenter,
                    )
                    detail_font = QtGui.QFont()
                    detail_font.setPointSize(detail_text_size)
                    detail_font.setWeight(QtGui.QFont.Weight.Bold)
                    detail_label.setFont(detail_font)
                    inside_layout.addWidget(detail_label)
                    self.price_labels[symbol] = price_label
                    spacer = QtWidgets.QSpacerItem(
                        0,
                        0,
                        QtWidgets.QSizePolicy.Policy.Minimum,
                        QtWidgets.QSizePolicy.Policy.Expanding,
                    )
                    inside_layout.addItem(spacer)
                spacer = QtWidgets.QSpacerItem(
                    0,
                    0,
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Minimum,
                )
                self.horizontalLayout_20.addItem(spacer)
                spacer = QtWidgets.QSpacerItem(
                    0,
                    0,
                    QtWidgets.QSizePolicy.Policy.Expanding,
                    QtWidgets.QSizePolicy.Policy.Minimum,
                )
                self.horizontalLayout_17.addItem(spacer)

            self.undertake(job, True)

            # ■■■■■ show package licenses ■■■■■

            def job():
                for category in ("CODE_SOURCES", "DEPENDENCIES"):
                    if category == "CODE_SOURCES":
                        category_text = "Code sources"
                    elif category == "DEPENDENCIES":
                        category_text = "Dependencies"
                    category_label = QtWidgets.QLabel(category_text)
                    self.verticalLayout_15.addWidget(category_label)
                    divider = QtWidgets.QFrame(self)
                    divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
                    divider.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
                    self.verticalLayout_15.addWidget(divider)
                    for dependency in getattr(introduction, category):
                        dependency_name = dependency[0]
                        dependency_version = dependency[1]
                        dependency_license = dependency[2]
                        dependency_url = dependency[3]

                        text = dependency_name
                        text += f" ({dependency_version})"
                        text += f" - {dependency_license}"

                        # card structure
                        card = QtWidgets.QGroupBox()
                        card.setFixedHeight(72)
                        card_layout = QtWidgets.QHBoxLayout(card)
                        license_label = QtWidgets.QLabel(
                            text,
                            alignment=QtCore.Qt.AlignmentFlag.AlignCenter,
                        )
                        card_layout.addWidget(license_label)
                        spacer = QtWidgets.QSpacerItem(
                            0,
                            0,
                            QtWidgets.QSizePolicy.Policy.Expanding,
                            QtWidgets.QSizePolicy.Policy.Minimum,
                        )
                        card_layout.addItem(spacer)

                        def job(dependency_url=dependency_url):
                            webbrowser.open(dependency_url)

                        if dependency_url.startswith("http"):
                            text = dependency_url
                            link_button = QtWidgets.QPushButton(text, card)
                            outsource.do(link_button.clicked, job)
                            card_layout.addWidget(link_button)

                        self.verticalLayout_15.addWidget(card)

                    spacer = QtWidgets.QSpacerItem(
                        0,
                        0,
                        QtWidgets.QSizePolicy.Policy.Minimum,
                        QtWidgets.QSizePolicy.Policy.Expanding,
                    )
                    self.verticalLayout_15.addItem(spacer)

            self.undertake(job, True)

            # ■■■■■ graph widgets ■■■■■

            def job():
                self.plot_widget = pyqtgraph.PlotWidget()
                self.plot_widget_1 = pyqtgraph.PlotWidget()
                self.plot_widget_4 = pyqtgraph.PlotWidget()
                self.plot_widget_6 = pyqtgraph.PlotWidget()
                self.plot_widget.setBackground("#FCFCFC")
                self.plot_widget_1.setBackground("#FCFCFC")
                self.plot_widget_4.setBackground("#FCFCFC")
                self.plot_widget_6.setBackground("#FCFCFC")
                self.plot_widget.setMouseEnabled(y=False)
                self.plot_widget_1.setMouseEnabled(y=False)
                self.plot_widget_4.setMouseEnabled(y=False)
                self.plot_widget_6.setMouseEnabled(y=False)
                self.plot_widget.enableAutoRange(y=True)
                self.plot_widget_1.enableAutoRange(y=True)
                self.plot_widget_4.enableAutoRange(y=True)
                self.plot_widget_6.enableAutoRange(y=True)
                self.horizontalLayout_7.addWidget(self.plot_widget)
                self.horizontalLayout_29.addWidget(self.plot_widget_1)
                self.horizontalLayout_16.addWidget(self.plot_widget_4)
                self.horizontalLayout_28.addWidget(self.plot_widget_6)

                plot_item = self.plot_widget.plotItem
                plot_item_1 = self.plot_widget_1.plotItem
                plot_item_4 = self.plot_widget_4.plotItem
                plot_item_6 = self.plot_widget_6.plotItem
                plot_item.vb.setLimits(xMin=0, yMin=0)
                plot_item_1.vb.setLimits(xMin=0, yMin=0)
                plot_item_4.vb.setLimits(xMin=0, yMin=0)
                plot_item_6.vb.setLimits(xMin=0)
                plot_item.setDownsampling(auto=True, mode="subsample")
                plot_item.setClipToView(True)
                plot_item.setAutoVisible(y=True)
                plot_item_1.setDownsampling(auto=True, mode="subsample")
                plot_item_1.setClipToView(True)
                plot_item_1.setAutoVisible(y=True)
                plot_item_4.setDownsampling(auto=True, mode="subsample")
                plot_item_4.setClipToView(True)
                plot_item_4.setAutoVisible(y=True)
                plot_item_6.setDownsampling(auto=True, mode="subsample")
                plot_item_6.setClipToView(True)
                plot_item_6.setAutoVisible(y=True)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": PercentAxisItem(orientation="left"),
                    "right": PercentAxisItem(orientation="right"),
                }
                plot_item.setAxisItems(axis_items)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": PercentAxisItem(orientation="left"),
                    "right": PercentAxisItem(orientation="right"),
                }
                plot_item_1.setAxisItems(axis_items)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": pyqtgraph.AxisItem(orientation="left"),
                    "right": pyqtgraph.AxisItem(orientation="right"),
                }
                plot_item_4.setAxisItems(axis_items)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": pyqtgraph.AxisItem(orientation="left"),
                    "right": pyqtgraph.AxisItem(orientation="right"),
                }
                plot_item_6.setAxisItems(axis_items)
                tick_font = QtGui.QFont("Consolas", 7)
                plot_item.getAxis("top").setTickFont(tick_font)
                plot_item.getAxis("bottom").setTickFont(tick_font)
                plot_item.getAxis("left").setTickFont(tick_font)
                plot_item.getAxis("right").setTickFont(tick_font)
                plot_item_1.getAxis("top").setTickFont(tick_font)
                plot_item_1.getAxis("bottom").setTickFont(tick_font)
                plot_item_1.getAxis("left").setTickFont(tick_font)
                plot_item_1.getAxis("right").setTickFont(tick_font)
                plot_item_4.getAxis("top").setTickFont(tick_font)
                plot_item_4.getAxis("bottom").setTickFont(tick_font)
                plot_item_4.getAxis("left").setTickFont(tick_font)
                plot_item_4.getAxis("right").setTickFont(tick_font)
                plot_item_6.getAxis("top").setTickFont(tick_font)
                plot_item_6.getAxis("bottom").setTickFont(tick_font)
                plot_item_6.getAxis("left").setTickFont(tick_font)
                plot_item_6.getAxis("right").setTickFont(tick_font)
                plot_item.getAxis("left").setWidth(40)
                plot_item.getAxis("right").setWidth(40)
                plot_item_1.getAxis("left").setWidth(40)
                plot_item_1.getAxis("right").setWidth(40)
                plot_item_4.getAxis("left").setWidth(40)
                plot_item_4.getAxis("right").setWidth(40)
                plot_item_6.getAxis("left").setWidth(40)
                plot_item_6.getAxis("right").setWidth(40)
                plot_item.getAxis("bottom").setHeight(0)
                plot_item_1.getAxis("top").setHeight(0)
                plot_item_4.getAxis("top").setHeight(0)
                plot_item_4.getAxis("bottom").setHeight(0)
                plot_item_6.getAxis("top").setHeight(0)
                plot_item_6.getAxis("bottom").setHeight(0)
                plot_item.showGrid(x=True, y=True, alpha=0.15)
                plot_item_1.showGrid(x=True, y=True, alpha=0.15)
                plot_item_4.showGrid(x=True, y=True, alpha=0.15)
                plot_item_6.showGrid(x=True, y=True, alpha=0.15)

                self.transaction_lines = {
                    "book_tickers": [
                        plot_item.plot(
                            pen=pyqtgraph.mkPen("#CFCFCF"),
                            connect="finite",
                            stepMode="right",
                        )
                        for _ in range(2)
                    ],
                    "last_price": plot_item.plot(
                        pen=pyqtgraph.mkPen("#D8E461"),
                        connect="finite",
                        stepMode="right",
                    ),
                    "mark_price": plot_item.plot(
                        pen=pyqtgraph.mkPen("#E2F200"),
                        connect="finite",
                    ),
                    "price_indicators": [
                        plot_item.plot(connect="finite") for _ in range(20)
                    ],
                    "entry_price": plot_item.plot(
                        pen=pyqtgraph.mkPen("#FFBB00"),
                        connect="finite",
                    ),
                    "boundaries": [
                        plot_item.plot(
                            pen=pyqtgraph.mkPen("#D0E200"),
                            connect="finite",
                        )
                        for _ in range(20)
                    ],
                    "wobbles": [
                        plot_item.plot(
                            pen=pyqtgraph.mkPen("#BBBBBB"),
                            connect="finite",
                            stepMode="right",
                        )
                        for _ in range(2)
                    ],
                    "price_down": plot_item.plot(
                        pen=pyqtgraph.mkPen("#DD0000"),
                        connect="finite",
                    ),
                    "price_up": plot_item.plot(
                        pen=pyqtgraph.mkPen("#1CA200"),
                        connect="finite",
                    ),
                    "sell": plot_item.plot(
                        pen=pyqtgraph.mkPen(None),  # invisible line
                        symbol="o",
                        symbolBrush="#0055FF",
                        symbolPen=pyqtgraph.mkPen("#BBBBBB"),
                        symbolSize=8,
                    ),
                    "buy": plot_item.plot(
                        pen=pyqtgraph.mkPen(None),  # invisible line
                        symbol="o",
                        symbolBrush="#FF3300",
                        symbolPen=pyqtgraph.mkPen("#BBBBBB"),
                        symbolSize=8,
                    ),
                    "volume": plot_item_4.plot(
                        pen=pyqtgraph.mkPen("#111111"),
                        connect="all",
                        stepMode="right",
                        fillLevel=0,
                        brush=pyqtgraph.mkBrush(0, 0, 0, 15),
                    ),
                    "last_volume": plot_item_4.plot(
                        pen=pyqtgraph.mkPen("#111111"),
                        connect="finite",
                    ),
                    "volume_indicators": [
                        plot_item_4.plot(connect="finite") for _ in range(20)
                    ],
                    "abstract_indicators": [
                        plot_item_6.plot(connect="finite") for _ in range(20)
                    ],
                    "asset_with_unrealized_profit": plot_item_1.plot(
                        pen=pyqtgraph.mkPen("#AAAAAA"),
                        connect="finite",
                    ),
                    "asset": plot_item_1.plot(
                        pen=pyqtgraph.mkPen("#FF8700"),
                        connect="finite",
                        stepMode="right",
                    ),
                }

                self.plot_widget_1.setXLink(self.plot_widget)
                self.plot_widget_4.setXLink(self.plot_widget_1)
                self.plot_widget_6.setXLink(self.plot_widget_4)

            self.undertake(job, True)

            def job():
                self.plot_widget_2 = pyqtgraph.PlotWidget()
                self.plot_widget_3 = pyqtgraph.PlotWidget()
                self.plot_widget_5 = pyqtgraph.PlotWidget()
                self.plot_widget_7 = pyqtgraph.PlotWidget()
                self.plot_widget_2.setBackground("#FCFCFC")
                self.plot_widget_3.setBackground("#FCFCFC")
                self.plot_widget_5.setBackground("#FCFCFC")
                self.plot_widget_7.setBackground("#FCFCFC")
                self.plot_widget_2.setMouseEnabled(y=False)
                self.plot_widget_3.setMouseEnabled(y=False)
                self.plot_widget_5.setMouseEnabled(y=False)
                self.plot_widget_7.setMouseEnabled(y=False)
                self.plot_widget_2.enableAutoRange(y=True)
                self.plot_widget_3.enableAutoRange(y=True)
                self.plot_widget_5.enableAutoRange(y=True)
                self.plot_widget_7.enableAutoRange(y=True)
                self.horizontalLayout.addWidget(self.plot_widget_2)
                self.horizontalLayout_30.addWidget(self.plot_widget_3)
                self.horizontalLayout_19.addWidget(self.plot_widget_5)
                self.horizontalLayout_31.addWidget(self.plot_widget_7)

                plot_item_2 = self.plot_widget_2.plotItem
                plot_item_3 = self.plot_widget_3.plotItem
                plot_item_5 = self.plot_widget_5.plotItem
                plot_item_7 = self.plot_widget_7.plotItem
                plot_item_2.vb.setLimits(xMin=0, yMin=0)
                plot_item_3.vb.setLimits(xMin=0, yMin=0)
                plot_item_5.vb.setLimits(xMin=0, yMin=0)
                plot_item_7.vb.setLimits(xMin=0)
                plot_item_2.setDownsampling(auto=True, mode="subsample")
                plot_item_2.setClipToView(True)
                plot_item_2.setAutoVisible(y=True)
                plot_item_3.setDownsampling(auto=True, mode="subsample")
                plot_item_3.setClipToView(True)
                plot_item_3.setAutoVisible(y=True)
                plot_item_5.setDownsampling(auto=True, mode="subsample")
                plot_item_5.setClipToView(True)
                plot_item_5.setAutoVisible(y=True)
                plot_item_7.setDownsampling(auto=True, mode="subsample")
                plot_item_7.setClipToView(True)
                plot_item_7.setAutoVisible(y=True)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": PercentAxisItem(orientation="left"),
                    "right": PercentAxisItem(orientation="right"),
                }
                plot_item_2.setAxisItems(axis_items)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": PercentAxisItem(orientation="left"),
                    "right": PercentAxisItem(orientation="right"),
                }
                plot_item_3.setAxisItems(axis_items)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": pyqtgraph.AxisItem(orientation="left"),
                    "right": pyqtgraph.AxisItem(orientation="right"),
                }
                plot_item_5.setAxisItems(axis_items)
                axis_items = {
                    "top": TimeAxisItem(orientation="top"),
                    "bottom": TimeAxisItem(orientation="bottom"),
                    "left": pyqtgraph.AxisItem(orientation="left"),
                    "right": pyqtgraph.AxisItem(orientation="right"),
                }
                plot_item_7.setAxisItems(axis_items)
                tick_font = QtGui.QFont("Consolas", 7)
                plot_item_2.getAxis("top").setTickFont(tick_font)
                plot_item_2.getAxis("bottom").setTickFont(tick_font)
                plot_item_2.getAxis("left").setTickFont(tick_font)
                plot_item_2.getAxis("right").setTickFont(tick_font)
                plot_item_3.getAxis("top").setTickFont(tick_font)
                plot_item_3.getAxis("bottom").setTickFont(tick_font)
                plot_item_3.getAxis("left").setTickFont(tick_font)
                plot_item_3.getAxis("right").setTickFont(tick_font)
                plot_item_5.getAxis("top").setTickFont(tick_font)
                plot_item_5.getAxis("bottom").setTickFont(tick_font)
                plot_item_5.getAxis("left").setTickFont(tick_font)
                plot_item_5.getAxis("right").setTickFont(tick_font)
                plot_item_7.getAxis("top").setTickFont(tick_font)
                plot_item_7.getAxis("bottom").setTickFont(tick_font)
                plot_item_7.getAxis("left").setTickFont(tick_font)
                plot_item_7.getAxis("right").setTickFont(tick_font)
                plot_item_2.getAxis("left").setWidth(40)
                plot_item_2.getAxis("right").setWidth(40)
                plot_item_3.getAxis("left").setWidth(40)
                plot_item_3.getAxis("right").setWidth(40)
                plot_item_5.getAxis("left").setWidth(40)
                plot_item_5.getAxis("right").setWidth(40)
                plot_item_7.getAxis("left").setWidth(40)
                plot_item_7.getAxis("right").setWidth(40)
                plot_item_2.getAxis("bottom").setHeight(0)
                plot_item_3.getAxis("top").setHeight(0)
                plot_item_5.getAxis("top").setHeight(0)
                plot_item_5.getAxis("bottom").setHeight(0)
                plot_item_7.getAxis("top").setHeight(0)
                plot_item_7.getAxis("bottom").setHeight(0)
                plot_item_2.showGrid(x=True, y=True, alpha=0.15)
                plot_item_3.showGrid(x=True, y=True, alpha=0.15)
                plot_item_5.showGrid(x=True, y=True, alpha=0.15)
                plot_item_7.showGrid(x=True, y=True, alpha=0.15)

                self.simulation_lines = {
                    "book_tickers": [
                        plot_item_2.plot(
                            pen=pyqtgraph.mkPen("#CFCFCF"),
                            connect="finite",
                            stepMode="right",
                        )
                        for _ in range(2)
                    ],
                    "last_price": plot_item_2.plot(
                        pen=pyqtgraph.mkPen("#D8E461"),
                        connect="finite",
                        stepMode="right",
                    ),
                    "mark_price": plot_item_2.plot(
                        pen=pyqtgraph.mkPen("#E2F200"),
                        connect="finite",
                    ),
                    "price_indicators": [
                        plot_item_2.plot(connect="finite") for _ in range(20)
                    ],
                    "entry_price": plot_item_2.plot(
                        pen=pyqtgraph.mkPen("#FFBB00"),
                        connect="finite",
                    ),
                    "boundaries": [
                        plot_item_2.plot(
                            pen=pyqtgraph.mkPen("#D0E200"),
                            connect="finite",
                        )
                        for _ in range(20)
                    ],
                    "wobbles": [
                        plot_item_2.plot(
                            pen=pyqtgraph.mkPen("#BBBBBB"),
                            connect="finite",
                            stepMode="right",
                        )
                        for _ in range(2)
                    ],
                    "price_down": plot_item_2.plot(
                        pen=pyqtgraph.mkPen("#DD0000"),
                        connect="finite",
                    ),
                    "price_up": plot_item_2.plot(
                        pen=pyqtgraph.mkPen("#1CA200"),
                        connect="finite",
                    ),
                    "sell": plot_item_2.plot(
                        pen=pyqtgraph.mkPen(None),  # invisible line
                        symbol="o",
                        symbolBrush="#0055FF",
                        symbolPen=pyqtgraph.mkPen("#BBBBBB"),
                        symbolSize=8,
                    ),
                    "buy": plot_item_2.plot(
                        pen=pyqtgraph.mkPen(None),  # invisible line
                        symbol="o",
                        symbolBrush="#FF3300",
                        symbolPen=pyqtgraph.mkPen("#BBBBBB"),
                        symbolSize=8,
                    ),
                    "volume": plot_item_5.plot(
                        pen=pyqtgraph.mkPen("#111111"),
                        connect="all",
                        stepMode="right",
                        fillLevel=0,
                        brush=pyqtgraph.mkBrush(0, 0, 0, 15),
                    ),
                    "last_volume": plot_item_5.plot(
                        pen=pyqtgraph.mkPen("#111111"),
                        connect="finite",
                    ),
                    "volume_indicators": [
                        plot_item_5.plot(connect="finite") for _ in range(20)
                    ],
                    "abstract_indicators": [
                        plot_item_7.plot(connect="finite") for _ in range(20)
                    ],
                    "asset_with_unrealized_profit": plot_item_3.plot(
                        pen=pyqtgraph.mkPen("#AAAAAA"),
                        connect="finite",
                    ),
                    "asset": plot_item_3.plot(
                        pen=pyqtgraph.mkPen("#FF8700"),
                        connect="finite",
                        stepMode="right",
                    ),
                }

                self.plot_widget_3.setXLink(self.plot_widget_2)
                self.plot_widget_5.setXLink(self.plot_widget_3)
                self.plot_widget_7.setXLink(self.plot_widget_5)

            self.undertake(job, True)

            # ■■■■■ intergrated strategies ■■■■■

            # usability / is parallel calculation / divided chunk length
            self.strategy_tuples = [
                (0, "Custom strategy"),
                (1, "Make random orders", [True, True, 7]),
                (2, "Solsol default strategy", [True, True, 30]),
            ]

            red_pixmap = QtGui.QPixmap()
            red_pixmap.load("./static/icon/traffic_light_red.png")
            yellow_pixmap = QtGui.QPixmap()
            yellow_pixmap.load("./static/icon/traffic_light_yellow.png")
            green_pixmap = QtGui.QPixmap()
            green_pixmap.load("./static/icon/traffic_light_green.png")

            for strategy_tuple in self.strategy_tuples:
                strategy_number = strategy_tuple[0]
                strategy_name = strategy_tuple[1]

                traffic_light_icon = QtGui.QIcon()
                if strategy_number == 0:
                    traffic_light_icon.addPixmap(yellow_pixmap)
                elif strategy_number == 1:
                    traffic_light_icon.addPixmap(red_pixmap)
                elif strategy_number == 2:
                    traffic_light_icon.addPixmap(green_pixmap)

                def job(text=strategy_name):
                    self.comboBox.addItem(traffic_light_icon, text)
                    self.comboBox_2.addItem(traffic_light_icon, text)

                self.undertake(job, True)

            # ■■■■■ submenus ■■■■■

            def job():
                action_menu = QtWidgets.QMenu(self)
                collector.me_actions = []
                text = "Save candle data"
                collector.me_actions.append(action_menu.addAction(text))
                text = "Save every year's candle data"
                collector.me_actions.append(action_menu.addAction(text))
                text = "Open binance historical data webpage"
                collector.me_actions.append(action_menu.addAction(text))
                text = "Stop filling candle data"
                collector.me_actions.append(action_menu.addAction(text))
                self.pushButton_13.setMenu(action_menu)

                action_menu = QtWidgets.QMenu(self)
                transactor.me_actions = []
                text = "Open binance exchange"
                transactor.me_actions.append(action_menu.addAction(text))
                text = "Open binance testnet exchange"
                transactor.me_actions.append(action_menu.addAction(text))
                text = "Open binance wallet"
                transactor.me_actions.append(action_menu.addAction(text))
                text = "Open binance API management webpage"
                transactor.me_actions.append(action_menu.addAction(text))
                text = "Cancel all open orders on this symbol"
                transactor.me_actions.append(action_menu.addAction(text))
                text = "Display same range as simulation graph"
                transactor.me_actions.append(action_menu.addAction(text))
                self.pushButton_12.setMenu(action_menu)

                action_menu = QtWidgets.QMenu(self)
                simulator.me_actions = []
                text = "Calculate temporarily only on visible range"
                simulator.me_actions.append(action_menu.addAction(text))
                text = "Stop calculation"
                simulator.me_actions.append(action_menu.addAction(text))
                text = "Find spots with lowest unrealized profit"
                simulator.me_actions.append(action_menu.addAction(text))
                text = "Display same range as transaction graph"
                simulator.me_actions.append(action_menu.addAction(text))
                self.pushButton_11.setMenu(action_menu)

                action_menu = QtWidgets.QMenu(self)
                strategist.me_actions = []
                text = "Apply sample strategy"
                strategist.me_actions.append(action_menu.addAction(text))
                self.pushButton_9.setMenu(action_menu)

                action_menu = QtWidgets.QMenu(self)
                manager.me_actions = []
                text = "Make a small error on purpose"
                manager.me_actions.append(action_menu.addAction(text))
                text = "Show test popup"
                manager.me_actions.append(action_menu.addAction(text))
                text = "Match system time with binance server"
                manager.me_actions.append(action_menu.addAction(text))
                text = "Show current Solsol version"
                manager.me_actions.append(action_menu.addAction(text))
                text = "Show Solsol license key"
                manager.me_actions.append(action_menu.addAction(text))
                self.pushButton_10.setMenu(action_menu)

            self.undertake(job, True)

            # ■■■■■ prepare auto executions ■■■■■

            self.initialize_functions = []
            self.finalize_functions = []
            self.scheduler = BlockingScheduler(timezone="UTC")
            self.scheduler.add_executor(ThreadPoolExecutor(), "thread_pool_executor")

            # ■■■■■ workers ■■■■■

            collector.bring_to_life()
            transactor.bring_to_life()
            simulator.bring_to_life()
            strategist.bring_to_life()
            manager.bring_to_life()

            # ■■■■■ prepare logging ■■■■■

            log_handler = LogHandler(manager.me.add_log_output)
            log_format = "■ %(asctime)s.%(msecs)03d %(levelname)s\n\n%(message)s"
            date_format = "%Y-%m-%d %H:%M:%S"
            log_formatter = logging.Formatter(log_format, datefmt=date_format)
            log_formatter.converter = time.gmtime
            log_handler.setFormatter(log_formatter)
            logging.getLogger().addHandler(log_handler)
            logger = logging.getLogger("solsol")
            logger.setLevel("DEBUG")
            logger.info("Started up")

            # ■■■■■ connect events to functions ■■■■■

            def job():
                # gauge
                job = manager.me.toggle_board_availability
                outsource.do(self.gauge.clicked, job)

                # actions
                job = collector.me.save_candle_data
                outsource.do(collector.me_actions[0].triggered, job)
                job = collector.me.save_all_years_history
                outsource.do(collector.me_actions[1].triggered, job)
                job = collector.me.open_binance_data_page
                outsource.do(collector.me_actions[2].triggered, job)
                job = collector.me.stop_filling_candle_data
                outsource.do(collector.me_actions[3].triggered, job)
                job = transactor.me.open_exchange
                outsource.do(transactor.me_actions[0].triggered, job)
                job = transactor.me.open_testnet_exchange
                outsource.do(transactor.me_actions[1].triggered, job)
                job = transactor.me.open_futures_wallet_page
                outsource.do(transactor.me_actions[2].triggered, job)
                job = transactor.me.open_api_management_page
                outsource.do(transactor.me_actions[3].triggered, job)
                job = transactor.me.cancel_symbol_orders
                outsource.do(transactor.me_actions[4].triggered, job)
                job = transactor.me.match_graph_range
                outsource.do(transactor.me_actions[5].triggered, job)
                job = simulator.me.simulate_only_visible
                outsource.do(simulator.me_actions[0].triggered, job)
                job = simulator.me.stop_calculation
                outsource.do(simulator.me_actions[1].triggered, job)
                job = simulator.me.analyze_unrealized_peaks
                outsource.do(simulator.me_actions[2].triggered, job)
                job = simulator.me.match_graph_range
                outsource.do(simulator.me_actions[3].triggered, job)
                job = strategist.me.fill_with_sample
                outsource.do(strategist.me_actions[0].triggered, job)
                job = manager.me.make_small_exception
                outsource.do(manager.me_actions[0].triggered, job)
                job = manager.me.open_sample_ask_popup
                outsource.do(manager.me_actions[1].triggered, job)
                job = manager.me.match_system_time
                outsource.do(manager.me_actions[2].triggered, job)
                job = manager.me.show_version
                outsource.do(manager.me_actions[3].triggered, job)
                job = manager.me.show_license_key
                outsource.do(manager.me_actions[4].triggered, job)

                # special widgets
                job = transactor.me.display_range_information
                outsource.do(self.plot_widget.sigRangeChanged, job)
                job = transactor.me.set_minimum_view_range
                outsource.do(self.plot_widget.sigRangeChanged, job)
                job = simulator.me.display_range_information
                outsource.do(self.plot_widget_2.sigRangeChanged, job)
                job = simulator.me.set_minimum_view_range
                outsource.do(self.plot_widget_2.sigRangeChanged, job)

                # normal widgets
                job = simulator.me.update_calculation_settings
                outsource.do(self.comboBox.activated, job)
                job = transactor.me.update_automation_settings
                outsource.do(self.comboBox_2.activated, job)
                job = transactor.me.update_automation_settings
                outsource.do(self.checkBox.toggled, job)
                job = simulator.me.calculate
                outsource.do(self.pushButton_3.clicked, job)
                job = manager.me.open_datapath
                outsource.do(self.pushButton_8.clicked, job)
                job = simulator.me.update_presentation_settings
                outsource.do(self.spinBox_2.editingFinished, job)
                job = simulator.me.update_presentation_settings
                outsource.do(self.doubleSpinBox.editingFinished, job)
                job = simulator.me.update_presentation_settings
                outsource.do(self.doubleSpinBox_2.editingFinished, job)
                job = simulator.me.erase
                outsource.do(self.pushButton_4.clicked, job)
                job = simulator.me.update_calculation_settings
                outsource.do(self.comboBox_5.activated, job)
                job = transactor.me.update_keys
                outsource.do(self.lineEdit_4.editingFinished, job)
                job = transactor.me.update_keys
                outsource.do(self.lineEdit_6.editingFinished, job)
                job = manager.me.run_script
                outsource.do(self.pushButton.clicked, job)
                job = transactor.me.toggle_frequent_draw
                outsource.do(self.checkBox_2.toggled, job)
                job = simulator.me.toggle_combined_draw
                outsource.do(self.checkBox_3.toggled, job)
                job = transactor.me.display_day_range
                outsource.do(self.pushButton_14.clicked, job)
                job = simulator.me.display_year_range
                outsource.do(self.pushButton_15.clicked, job)
                job = simulator.me.delete_calculation_data
                outsource.do(self.pushButton_16.clicked, job)
                job = simulator.me.draw
                outsource.do(self.pushButton_17.clicked, job)
                job = strategist.me.revert_scripts
                outsource.do(self.pushButton_19.clicked, job)
                job = strategist.me.save_scripts
                outsource.do(self.pushButton_20.clicked, job)
                job = transactor.me.update_keys
                outsource.do(self.comboBox_3.activated, job)
                job = collector.me.download_fill_candle_data
                outsource.do(self.pushButton_2.clicked, job)
                job = transactor.me.update_mode_settings
                outsource.do(self.spinBox.editingFinished, job)
                job = manager.me.deselect_log_output
                outsource.do(self.pushButton_6.clicked, job)
                job = manager.me.reset_datapath
                outsource.do(self.pushButton_22.clicked, job)
                job = transactor.me.update_viewing_symbol
                outsource.do(self.comboBox_4.activated, job)
                job = simulator.me.update_viewing_symbol
                outsource.do(self.comboBox_6.activated, job)
                job = manager.me.open_documentation
                outsource.do(self.pushButton_7.clicked, job)

            self.undertake(job, True)

            # ■■■■■ initialize functions ■■■■■

            def job():
                guide_frame.announce("Initializing...")

            self.undertake(job, True)

            def job(function):
                function()

            map_result = thread_toss.map_async(job, self.initialize_functions)

            for _ in range(200):
                if map_result.ready() and map_result.successful():
                    break
                time.sleep(0.1)

            # ■■■■■ start repetitive timer ■■■■■

            thread_toss.apply_async(lambda: self.scheduler.start())

            # ■■■■■ activate finalization ■■■■■

            self.should_finalize = True

            # ■■■■■ wait until the contents are filled ■■■■■

            time.sleep(1)

            # ■■■■■ show main widgets ■■■■■

            self.undertake(lambda: guide_frame.setParent(None), True)
            self.undertake(lambda: self.board.show(), True)
            self.undertake(lambda: self.gauge.show(), True)

        except Exception:
            text = traceback.format_exc()
            question = [
                "An error occured during the boot phase",
                text,
                ["Shut down"],
                False,
            ]
            self.ask(question)
            self.undertake(self.close, False)

    # takes function and run it on the main thread
    def undertake(self, job, wait_return, called_remotely=False, holder=None):
        if not called_remotely:
            holder = [threading.Event(), None]
            telephone = Telephone()
            telephone.signal.connect(self.undertake)
            telephone.signal.emit(job, False, True, holder)
            if wait_return:
                holder[0].wait()
                return holder[1]

        else:
            returned = job()
            holder[1] = returned
            holder[0].set()

    # show an ask popup and blocks the stack
    def ask(self, question):
        ask_popup = None

        def job():
            nonlocal ask_popup
            ask_popup = AskPopup(self, question)
            ask_popup.show()

        self.undertake(job, True)

        ask_popup.done_event.wait()

        def job():
            ask_popup.setParent(None)

        self.undertake(job, False)

        return ask_popup.answer


window = None


def bring_to_life():
    global window

    # ■■■■■ app ■■■■■

    app = QtWidgets.QApplication(sys.argv)

    # ■■■■■ theme ■■■■■

    # this part should be done after creating the app and before creating the window
    QtGui.QFontDatabase.addApplicationFont("./static/consolas.ttf")
    QtGui.QFontDatabase.addApplicationFont("./static/notosans_regular.ttf")
    default_font = QtGui.QFont("Noto Sans", 9)

    app.setStyle("Fusion")
    app.setFont(default_font)

    # ■■■■■ window ■■■■■

    window = Window()

    # ■■■■■ show ■■■■■

    window.show()
    sys.exit(getattr(app, "exec")())
