from datetime import datetime, timedelta, timezone
import os
from collections import deque
import time
import statistics
import logging
import webbrowser
import platform
import subprocess
import json

import timesetter

from module import core
from module import process_toss
from module import thread_toss
from module import introduction
from module.worker import collector
from module.instrument.api_requester import ApiRequester
from module.recipe import simply_format
from module.recipe import check_internet
from module.recipe import user_settings
from module.recipe import find_goodies
from module.recipe import remember_task_durations
from module.recipe import datalocks
from module.recipe import value_to

WINDOW_LOCK_OPTIONS = (
    "NEVER",
    "10_SECOND",
    "1_MINUTE",
    "10_MINUTE",
    "1_HOUR",
)


class Manager:
    def __init__(self):
        # ■■■■■ for data management ■■■■■

        self.workerpath = user_settings.get_app_settings()["datapath"] + "/manager"
        os.makedirs(self.workerpath, exist_ok=True)

        # ■■■■■ worker secret memory ■■■■■

        self.secret_memory = {}

        # ■■■■■ remember and display ■■■■■

        self.api_requester = ApiRequester()

        self.executed_time = datetime.now(timezone.utc).replace(microsecond=0)

        self.online_status = {
            "ping": 0,
            "server_time_differences": deque(maxlen=120),
        }
        self.binance_limits = {}

        filepath = self.workerpath + "/settings.json"
        if os.path.isfile(filepath):
            with open(filepath, "r", encoding="utf8") as file:
                self.settings = json.load(file)
        else:
            self.settings = {
                "match_system_time": True,
                "disable_system_update": False,
                "lock_window": "NEVER",
            }
        payload = (
            core.window.checkBox_12.setChecked,
            self.settings["match_system_time"],
        )
        core.window.undertake(lambda p=payload: p[0](p[1]), False)
        payload = (
            core.window.checkBox_13.setChecked,
            self.settings["disable_system_update"],
        )
        core.window.undertake(lambda p=payload: p[0](p[1]), False)
        payload = (
            core.window.comboBox_3.setCurrentIndex,
            value_to.indexes(WINDOW_LOCK_OPTIONS, self.settings["lock_window"])[0],
        )
        core.window.undertake(lambda p=payload: p[0](p[1]), False)

        filepath = self.workerpath + "/python_script.txt"
        if os.path.isfile(filepath):
            with open(filepath, "r", encoding="utf8") as file:
                script = file.read()
        else:
            script = ""
        core.window.undertake(
            lambda s=script: core.window.plainTextEdit.setPlainText(s), False
        )

        # ■■■■■ repetitive schedules ■■■■■

        core.window.scheduler.add_job(
            self.lock_board,
            trigger="cron",
            second="*",
            executor="thread_pool_executor",
        )
        core.window.scheduler.add_job(
            self.check_online_status,
            trigger="cron",
            second="*",
            executor="thread_pool_executor",
        )
        core.window.scheduler.add_job(
            self.display_system_status,
            trigger="cron",
            second="*",
            executor="thread_pool_executor",
        )
        core.window.scheduler.add_job(
            self.display_internal_status,
            trigger="cron",
            second="*",
            executor="thread_pool_executor",
        )
        core.window.scheduler.add_job(
            self.disable_system_auto_update,
            trigger="cron",
            minute="*",
            executor="thread_pool_executor",
        )
        core.window.scheduler.add_job(
            self.match_system_time,
            trigger="cron",
            minute="*/10",
            executor="thread_pool_executor",
        )
        core.window.scheduler.add_job(
            self.check_for_update,
            trigger="cron",
            minute="*/10",
            executor="thread_pool_executor",
        )
        core.window.scheduler.add_job(
            self.check_binance_limits,
            trigger="cron",
            hour="*",
            executor="thread_pool_executor",
        )

        # ■■■■■ websocket streamings ■■■■■

        self.api_streamers = []

        # ■■■■■ invoked by the internet connection  ■■■■■

        connected_functions = []
        check_internet.add_connected_functions(connected_functions)

        disconnected_functions = []
        check_internet.add_disconnected_functions(disconnected_functions)

    def change_settings(self, *args, **kwargs):
        payload = (core.window.checkBox_12.isChecked,)
        is_checked = core.window.undertake(lambda p=payload: p[0](), True)
        self.settings["match_system_time"] = True if is_checked else False

        payload = (core.window.checkBox_13.isChecked,)
        is_checked = core.window.undertake(lambda p=payload: p[0](), True)
        self.settings["disable_system_update"] = True if is_checked else False

        payload = (core.window.comboBox_3.currentIndex,)
        current_index = core.window.undertake(lambda p=payload: p[0](), True)
        self.settings["lock_window"] = WINDOW_LOCK_OPTIONS[current_index]

        filepath = self.workerpath + "/settings.json"
        with open(filepath, "w", encoding="utf8") as file:
            json.dump(self.settings, file, indent=4)

    def open_datapath(self, *args, **kwargs):
        os.startfile(user_settings.get_app_settings()["datapath"])

    def deselect_log_output(self, *args, **kwargs):
        def job():
            core.window.listWidget.clearSelection()

        core.window.undertake(job, False)

    def add_log_output(self, *args, **kwargs):
        # get the data
        summarization = args[0]
        log_content = args[1]

        # add to log list
        job = core.window.listWidget.addItem
        payload = (job, summarization, log_content)
        core.window.undertake(lambda p=payload: p[0](p[1], p[2]), False)

        # save to file
        task_start_time = datetime.now(timezone.utc)
        filepath = str(self.executed_time)
        filepath = filepath.replace(":", "_")
        filepath = filepath.replace(" ", "_")
        filepath = filepath.replace("-", "_")
        filepath = filepath.replace("+", "_")
        filepath = self.workerpath + "/log_outputs_" + filepath + ".txt"
        with open(filepath, "a", encoding="utf8") as file:
            file.write(f"{summarization}\n")
            file.write(f"{log_content}\n\n")
        duration = datetime.now(timezone.utc) - task_start_time
        duration = duration.total_seconds()
        remember_task_durations.add("write_log", duration)

    def display_internal_status(self, *args, **kwargs):
        def job():
            active_count = 0
            texts = []
            task_presences = thread_toss.get_task_presences()
            for thread_name, is_task_present in task_presences.items():
                if is_task_present:
                    active_count += 1
                text = thread_name
                text += f": {'Active' if is_task_present else 'Inactive'}"
                texts.append(text)
            text = f"{active_count} active"
            text += "\n\n" + "\n".join(texts)
            core.window.undertake(lambda t=text: core.window.label_12.setText(t), False)

            active_count = 0
            texts = []
            task_presences = process_toss.get_task_presences()
            for process_id, is_task_present in task_presences.items():
                if is_task_present:
                    active_count += 1
                text = f"PID {process_id}"
                text += f": {'Active' if is_task_present else 'Inactive'}"
                texts.append(text)
            text = f"{active_count} active"
            text += "\n\n" + "\n".join(texts)
            core.window.undertake(lambda t=text: core.window.label_32.setText(t), False)

            texts = []
            texts.append("Limits")
            for limit_type, limit_value in self.binance_limits.items():
                text = f"{limit_type}: {limit_value}"
                texts.append(text)

            used_rates = self.api_requester.used_rates
            if len(used_rates) > 0:
                texts.append("")
                texts.append("Usage")
                for used_type, used_tuple in used_rates.items():
                    time_string = used_tuple[1].strftime("%m-%d %H:%M:%S")
                    text = f"{used_type}: {used_tuple[0]}({time_string})"
                    texts.append(text)

            text = "\n".join(texts)
            core.window.undertake(lambda t=text: core.window.label_35.setText(t), False)

            texts = []

            task_durations = remember_task_durations.get()
            for data_name, deque_data in task_durations.items():
                if len(deque_data) > 0:
                    text = data_name
                    text += "\n"
                    data_value = sum(deque_data) / len(deque_data)
                    text += f"Average {simply_format.fixed_float(data_value,6)}s "
                    data_value = statistics.median(deque_data)
                    text += f"Middle {simply_format.fixed_float(data_value,6)}s "
                    text += "\n"
                    data_value = min(deque_data)
                    text += f"Minimum {simply_format.fixed_float(data_value,6)}s "
                    data_value = max(deque_data)
                    text += f"Maximum {simply_format.fixed_float(data_value,6)}s "
                    texts.append(text)

            text = "\n\n".join(texts)
            core.window.undertake(lambda t=text: core.window.label_33.setText(t), False)

            block_sizes = collector.me.aggtrade_candle_sizes
            lines = (f"{symbol} {count}" for (symbol, count) in block_sizes.items())
            text = "\n".join(lines)
            core.window.undertake(lambda t=text: core.window.label_36.setText(t), False)

            texts = []
            for key, lock in datalocks.object_locks.items():
                is_locked = lock.locked()
                locked_text = "Locked" if is_locked else "Unlocked"
                texts.append(f"{key}: {locked_text}")
            text = "\n".join(texts)
            core.window.undertake(lambda t=text: core.window.label_34.setText(t), False)

        for _ in range(10):
            job()
            time.sleep(0.1)

    def run_script(self, *args, **kwargs):
        widget = core.window.plainTextEdit
        script_text = core.window.undertake(lambda w=widget: w.toPlainText(), True)
        filepath = self.workerpath + "/python_script.txt"
        with open(filepath, "w", encoding="utf8") as file:
            file.write(script_text)
        namespace = {"window": core.window, "logger": logging.getLogger("solie")}
        exec(script_text, namespace)

    def check_online_status(self, *args, **kwargs):
        if not check_internet.connected():
            return

        request_time = datetime.now(timezone.utc)
        payload = {}
        response = self.api_requester.binance(
            http_method="GET",
            path="/fapi/v1/time",
            payload=payload,
        )
        response_time = datetime.now(timezone.utc)
        ping = (response_time - request_time).total_seconds()
        self.online_status["ping"] = ping

        server_timestamp = response["serverTime"] / 1000
        server_time = datetime.fromtimestamp(server_timestamp, tz=timezone.utc)
        local_time = datetime.now(timezone.utc)
        time_difference = (local_time - server_time).total_seconds() - ping / 2
        self.online_status["server_time_differences"].append(time_difference)

    def display_system_status(self, *args, **kwargs):
        time = datetime.now(timezone.utc)
        time_text = time.strftime("%Y-%m-%d %H:%M:%S")
        internet_connected = check_internet.connected()
        ping = self.online_status["ping"]
        payload = (core.window.board.isEnabled,)
        board_enabled = core.window.undertake(lambda p=payload: p[0](), True)

        deque_data = self.online_status["server_time_differences"]
        if len(deque_data) > 0:
            mean_difference = sum(deque_data) / len(deque_data)
        else:
            mean_difference = 0

        text = ""
        text += f"Current time UTC {time_text}"
        text += "  ⦁  "
        if internet_connected:
            text += "Connected to the internet"
        else:
            text += "Not connected to the internet"
        text += "  ⦁  "
        text += f"Ping {ping:.3f}s"
        text += "  ⦁  "
        text += f"Time difference with server {mean_difference:+.3f}s"
        text += "  ⦁  "
        text += f"Board {('unlocked' if board_enabled else 'locked')}"
        core.window.undertake(lambda t=text: core.window.gauge.setText(t), False)

    def match_system_time(self, *args, **kwargs):
        if not self.settings["match_system_time"]:
            return

        server_time_differences = self.online_status["server_time_differences"]
        if len(server_time_differences) < 60:
            return
        mean_difference = sum(server_time_differences) / len(server_time_differences)
        new_time = datetime.now(timezone.utc) - timedelta(seconds=mean_difference)
        timesetter.set(new_time)
        server_time_differences.clear()
        server_time_differences.append(0)

    def check_binance_limits(self, *args, **kwargs):
        if not check_internet.connected():
            return

        payload = {}
        response = self.api_requester.binance(
            http_method="GET",
            path="/fapi/v1/exchangeInfo",
            payload=payload,
        )
        for about_rate_limit in response["rateLimits"]:
            limit_type = about_rate_limit["rateLimitType"]
            limit_value = about_rate_limit["limit"]
            interval_unit = about_rate_limit["interval"]
            interval_value = about_rate_limit["intervalNum"]
            limit_name = f"{limit_type}({interval_value}{interval_unit})"
            self.binance_limits[limit_name] = limit_value

    def reset_datapath(self, *args, **kwargs):
        question = [
            "Are you sure you want to change the data folder?",
            "Solie will shut down shortly. You will get to choose the new data folder"
            " when you start Solie again. Previous data folder does not get deleted.",
            ["No", "Yes"],
        ]
        answer = core.window.ask(question)

        if answer in (0, 1):
            return

        user_settings.apply_app_settings({"datapath": None})

        core.window.should_confirm_closing = False
        core.window.undertake(core.window.close, False)

    def check_for_update(self, *args, **kwargs):
        should_update = find_goodies.is_newer_version_available()

        if should_update:
            latest_version = find_goodies.get_latest_version()
            question = [
                "Update is ready",
                "Shut down Solie and fetch the latest commits via Git."
                + f" The latest version is {latest_version},"
                + f" while the current version is {introduction.CURRENT_VERSION}.",
                ["Okay"],
            ]
            core.window.ask(question)

    def open_documentation(self, *args, **kwargs):
        webbrowser.open("https://solie-docs.cunarist.com")

    def disable_system_auto_update(self, *args, **kwargs):
        if not self.settings["disable_system_update"]:
            return

        if platform.system() == "Windows":
            commands = ["sc", "stop", "wuauserv"]
            subprocess.run(commands)
            commands = ["sc", "config", "wuauserv", "start=disabled"]
            subprocess.run(commands)

        elif platform.system() == "Linux":
            pass
        elif platform.system() == "Darwin":  # macOS
            pass

    def lock_board(self, *args, **kwargs):
        lock_window_setting = self.settings["lock_window"]

        if lock_window_setting == "NEVER":
            return
        elif lock_window_setting == "10_SECOND":
            wait_time = timedelta(seconds=10)
        elif lock_window_setting == "1_MINUTE":
            wait_time = timedelta(minutes=1)
        elif lock_window_setting == "10_MINUTE":
            wait_time = timedelta(minutes=10)
        elif lock_window_setting == "1_HOUR":
            wait_time = timedelta(hours=1)

        last_interaction_time = core.window.last_interaction
        if datetime.now(timezone.utc) < last_interaction_time + wait_time:
            return

        is_enabled = core.window.undertake(lambda: core.window.board.isEnabled(), True)
        if is_enabled:
            core.window.undertake(lambda: core.window.board.setEnabled(False), False)


me = None


def bring_to_life():
    global me
    me = Manager()
