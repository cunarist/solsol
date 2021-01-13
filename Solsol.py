import os
import sys
import platform
import pathlib
from urllib import request
import tempfile
import subprocess
import shutil
import tkinter as tk
import threading
import time

userpath = str(pathlib.Path.home())
condapath = f"{userpath}/miniconda3/condabin/conda.bat"

# ■■■■■ 스플래시 창 표시 ■■■■■

display_event = threading.Event()


def job():
    global balloon
    splash_window = tk.Tk()
    splash_window.overrideredirect(1)
    splash_window.attributes("-transparentcolor", "gray", "-topmost", True)
    balloon_image = tk.PhotoImage(file="./resource/balloon_1.png")
    balloon = tk.Label(splash_window, bg="gray", image=balloon_image)
    balloon.pack()
    splash_window.eval("tk::PlaceWindow . Center")
    display_event.set()
    splash_window.mainloop()


threading.Thread(target=job, daemon=True).start()
display_event.wait()

# ■■■■■ 콘다가 설치되어 있는지 ■■■■■

if not os.path.isdir(f"{userpath}/miniconda3"):

    balloon_image = tk.PhotoImage(file="./resource/balloon_2.png")
    balloon.configure(image=balloon_image)

    if platform.system() == "Windows":

        url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
        installer_file = request.urlopen(url).read()

        with tempfile.TemporaryDirectory() as directory:
            with open(directory + "/installer.exe", mode="wb") as file:
                filepath = file.name
                file.write(installer_file)

            commands = [
                f"{filepath} /S",
            ]
            subprocess.run(
                "&&".join(commands),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

    elif platform.system() == "Linux":

        sys.exit()

    elif platform.system() == "Darwin":  # macOS

        sys.exit()

# ■■■■■ 가상 환경이 존재하는지 ■■■■■

commands = [
    f"{condapath} activate base",
    "conda env list",
]
run_output = subprocess.run(
    "&&".join(commands),
    shell=True,
    stdout=subprocess.PIPE,
    text=True,
    creationflags=subprocess.CREATE_NO_WINDOW,
)

environment_lines = run_output.stdout.split("\n")
environment_lines = [line for line in environment_lines if "#" not in line]
environment_lines = [line for line in environment_lines if len(line) > 0]
environments = [line.split()[0] for line in environment_lines]

if "solsol" not in environments:

    balloon_image = tk.PhotoImage(file="./resource/balloon_3.png")
    balloon.configure(image=balloon_image)

    commands = [
        f"{condapath} create -y -n solsol python=3.9 --force",
        f"{condapath} config --add channels conda-forge",
        f"{condapath} config --set channel_priority strict",
    ]
    subprocess.run(
        "&&".join(commands),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

# ■■■■■ 패키지는 다 설치되어 있는지 ■■■■■

# pip list는 시스템 파이썬과 혼동하는 경우도 있어 사용하지 않음

commands = [
    f"{condapath} activate solsol",
    "conda list",
]
run_output = subprocess.run(
    "&&".join(commands),
    shell=True,
    stdout=subprocess.PIPE,
    text=True,
    creationflags=subprocess.CREATE_NO_WINDOW,
)

package_lines = run_output.stdout.split("\n")
package_lines = [line for line in package_lines if "#" not in line]
package_lines = [line for line in package_lines if len(line) > 0]
installed_packages = [line.split()[0] for line in package_lines]
lowered_packages = [name.lower() for name in installed_packages]

with open("./resource/conda_requirements.txt", mode="r", encoding="utf8") as file:
    conda_requirements = file.read().split("\n")

with open("./resource/pip_requirements.txt", mode="r", encoding="utf8") as file:
    pip_requirements = file.read().split("\n")

for conda_requirement in conda_requirements:

    if conda_requirement.lower() not in lowered_packages:

        balloon_image = tk.PhotoImage(file="./resource/balloon_4.png")
        balloon.configure(image=balloon_image)

        commands = [
            f"{condapath} activate solsol",
            f"conda install -y {conda_requirement}",
        ]
        subprocess.run(
            "&&".join(commands),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

for pip_requirement in pip_requirements:

    if pip_requirement.lower() not in lowered_packages:

        balloon_image = tk.PhotoImage(file="./resource/balloon_4.png")
        balloon.configure(image=balloon_image)

        commands = [
            f"{condapath} activate solsol",
            f"pip install {pip_requirement}",
        ]
        subprocess.run(
            "&&".join(commands),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

# ■■■■■ 코드 편집기 설정 파일 마련 ■■■■■

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    # running in a PyInstaller bundle
    pass
else:
    # coding in project folder
    if not os.path.isfile("./.vscode/settings.json"):
        os.makedirs("./.vscode", exist_ok=True)
        shutil.copy("./resource/vscode_settings.json", "./.vscode")
        os.rename("./.vscode/vscode_settings.json", "./.vscode/settings.json")

# ■■■■■ 실행 ■■■■■

# 새 프로세스에서 관리자 권한으로

balloon_image = tk.PhotoImage(file="./resource/balloon_5.png")
balloon.configure(image=balloon_image)

if platform.system() == "Windows":

    current_directory = os.getcwd()
    commands = [
        'powershell -windowstyle hidden -command "Start-Process -WindowStyle hidden'
        f" cmd -ArgumentList '/c cd /d {current_directory} && call {condapath} activate"
        " solsol && start pythonw ./module/entry.py'  -Verb runas \"",
    ]
    subprocess.run(
        "&&".join(commands),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


elif platform.system() == "Linux":

    sys.exit()

elif platform.system() == "Darwin":  # macOS

    sys.exit()

# ■■■■■ 스플래시 창 조금만 더 보이기 ■■■■■

time.sleep(3)
