#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
成绩监控 - 通用桌面版
======================
带图形界面的教务系统成绩监控工具。

双击运行本程序，输入账号信息即可开始监控。
"""

import os
import sys
import json
import asyncio
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime

# 添加当前目录到 Python 路径
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from score_monitor import (
    ScoreMonitor, Config, logger, _setup_console_encoding, _ensure_dirs,
    CONFIG_FILE, DATA_DIR, CACHE_FILE, LOG_FILE, SCREENSHOT_DIR,
)

_setup_console_encoding()

USER_CFG_FILE = BASE_DIR / "user_config.json"


# ============================================================
# 用户配置持久化（保存输入框内容，不含密码）
# ============================================================
def load_user_config() -> dict:
    """加载上次保存的用户配置"""
    if USER_CFG_FILE.exists():
        try:
            return json.loads(USER_CFG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_user_config(data: dict):
    """保存用户配置（不含密码）"""
    try:
        USER_CFG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"保存配置失败: {e}")


# ============================================================
# 主窗口
# ============================================================
class App:
    """成绩监控 GUI"""

    APP_NAME = "📚 教务成绩监控"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(self.APP_NAME)
        self.root.geometry("720x680")
        self.root.minsize(640, 580)
        self.root.resizable(True, True)

        # 图标（如果有的话）
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        # 状态变量
        self.monitor = None
        self._loop_thread = None
        self._loop = None
        self._running = False

        # 加载上次配置
        self._saved = load_user_config()

        # 构建界面
        self._build_ui()

        # 关闭窗口时的处理
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------------------------------------
    # 界面构建
    # --------------------------------------------------------
    def _build_ui(self):
        """构建完整的 GUI 界面"""
        main_frame = ttk.Frame(self.root, padding="12 12 12 12")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===================== 输入区域 =====================
        input_frame = ttk.LabelFrame(main_frame, text=" 教务系统设置 ", padding="8 8 8 8")
        input_frame.pack(fill=tk.X, pady=(0, 8))

        labels = [
            ("学号 *", "学号或用户名"),
            ("密码 *", "教务系统密码"),
            ("教务系统地址", "例如 http://jwgl.jsut.edu.cn"),
            ("学年", "例如 2025-2026"),
            ("学期", "1 或 2"),
            ("Bark Key", "iOS 推送 Key（可在 Bark App 获取）"),
            ("检查间隔(分钟)", "默认 30 分钟"),
        ]

        self.entries = {}
        defaults = {
            "学号": self._saved.get("student_id", ""),
            "密码": self._saved.get("password", ""),
            "教务系统地址": self._saved.get("base_url", "http://jwgl.jsut.edu.cn"),
            "学年": self._saved.get("academic_year", "2025-2026"),
            "学期": self._saved.get("semester", "2"),
            "Bark Key": self._saved.get("bark_key", ""),
            "检查间隔(分钟)": self._saved.get("interval", "30"),
        }

        for i, (label, hint) in enumerate(labels):
            ttk.Label(input_frame, text=label, width=14, anchor=tk.E).grid(
                row=i // 2, column=(i % 2) * 2, sticky=tk.W, padx=(0, 4), pady=3
            )
            key = label.split("(")[0].strip()
            show = "*" if label.startswith("密码") else None
            text_var = tk.StringVar(value=defaults.get(key, ""))
            entry = ttk.Entry(input_frame, textvariable=text_var, width=28, show=show)
            entry.grid(
                row=i // 2, column=(i % 2) * 2 + 1, sticky=tk.W + tk.E, padx=(0, 16), pady=3
            )
            self.entries[key] = (text_var, entry)

        # 让第二列也扩展
        input_frame.columnconfigure(1, weight=1)
        input_frame.columnconfigure(3, weight=1)

        # ===================== 密码显示切换 =====================
        self._show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            input_frame, text="显示密码", variable=self._show_pw,
            command=self._toggle_password
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=0, pady=2)

        # ===================== 操作按钮 =====================
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        self.btn_start = ttk.Button(
            btn_frame, text="🚀 开始监控", command=self._start_monitor, width=18
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = ttk.Button(
            btn_frame, text="⏹  停止监控", command=self._stop_monitor, width=18, state=tk.DISABLED
        )
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_check_once = ttk.Button(
            btn_frame, text="🔍 检查一次", command=self._check_once, width=14
        )
        self.btn_check_once.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_clear_log = ttk.Button(
            btn_frame, text="清空日志", command=self._clear_log, width=10
        )
        self.btn_clear_log.pack(side=tk.RIGHT)

        # ===================== 状态栏 =====================
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(
            main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W
        )
        status_bar.pack(fill=tk.X, pady=(0, 6))

        # ===================== 日志区域 =====================
        log_label = ttk.Label(main_frame, text="运行日志:", anchor=tk.W)
        log_label.pack(fill=tk.X)

        self.log_text = scrolledtext.ScrolledText(
            main_frame, wrap=tk.WORD, font=("Consolas", 10),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4",
            state=tk.DISABLED, height=20, relief=tk.SUNKEN, borderwidth=2
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 标签样式
        self.log_text.tag_config("INFO", foreground="#d4d4d4")
        self.log_text.tag_config("DEBUG", foreground="#569cd6")
        self.log_text.tag_config("WARNING", foreground="#ce9178")
        self.log_text.tag_config("ERROR", foreground="#f44747")
        self.log_text.tag_config("CRITICAL", foreground="#f44747", font=("Consolas", 10, "bold"))

        # 初始提示
        self._log("就绪 — 输入账号信息后点击「开始监控」", "INFO")

        # 如果有上次保存的配置，提示用户
        if self._saved.get("student_id"):
            self._log(f"已加载上次配置（学号: {self._saved['student_id']}）", "INFO")

    # --------------------------------------------------------
    # 密码显示切换
    # --------------------------------------------------------
    def _toggle_password(self):
        show = "" if self._show_pw.get() else "*"
        for key, (var, entry) in self.entries.items():
            if "密码" in key:
                entry.configure(show=show)

    # --------------------------------------------------------
    # 日志输出到 GUI
    # --------------------------------------------------------
    def _log(self, msg: str, level: str = "INFO"):
        """向 GUI 日志框追加一行"""
        self.log_text.configure(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = level if level in ("INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL") else "INFO"
        self.log_text.insert(tk.END, f"{timestamp} [{level}] {msg}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _gui_log_callback(self, msg: str):
        """从后台线程安全地追加日志，自动解析日志级别"""
        # 消息格式: "HH:MM:SS [LEVEL] content"
        level = "INFO"
        if "[WARNING]" in msg or "[WARN]" in msg:
            level = "WARNING"
        elif "[ERROR]" in msg or "[CRITICAL]" in msg:
            level = "ERROR"
        elif "[DEBUG]" in msg:
            level = "DEBUG"
        self.root.after(0, self._log, msg, level)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # --------------------------------------------------------
    # 获取输入值
    # --------------------------------------------------------
    def _get_values(self) -> dict:
        """从输入框读取值，返回 dict"""
        result = {}
        for key, (var, _) in self.entries.items():
            result[key] = var.get().strip()
        return result

    def _validate(self, values: dict) -> bool:
        """校验必填字段"""
        if not values.get("学号"):
            messagebox.showerror("错误", "请输入学号")
            return False
        if not values.get("密码"):
            messagebox.showerror("错误", "请输入密码")
            return False
        return True

    # --------------------------------------------------------
    # 启动 / 停止监控
    # --------------------------------------------------------
    def _save_current_config(self, values: dict):
        """保存用户配置（下次启动自动加载）"""
        save_user_config({
            "student_id": values.get("学号", ""),
            "password": values.get("密码", ""),
            "base_url": values.get("教务系统地址", ""),
            "academic_year": values.get("学年", ""),
            "semester": values.get("学期", ""),
            "bark_key": values.get("Bark Key", ""),
            "interval": values.get("检查间隔(分钟)", "30"),
        })

    def _build_config(self, values: dict) -> Config:
        """从输入值构建 Config 对象"""
        try:
            interval = int(values.get("检查间隔(分钟)", "30"))
        except ValueError:
            interval = 30
        return Config(
            student_id=values.get("学号", ""),
            password=values.get("密码", ""),
            base_url=values.get("教务系统地址", "http://jwgl.jsut.edu.cn"),
            academic_year=values.get("学年", "2025-2026"),
            semester=values.get("学期", "2"),
            check_interval_minutes=interval,
            bark_key=values.get("Bark Key", ""),
        )

    def _run_async_monitor(self, config: Config):
        """在后台线程中运行 asyncio 监控循环"""
        async def runner():
            self.monitor = ScoreMonitor(config, headless=True, gui_log_callback=self._gui_log_callback)
            try:
                await self.monitor.run_loop()
            except Exception as e:
                self._gui_log_callback(f"监控异常退出: {e}")
            finally:
                self.root.after(0, self._on_monitor_stopped)

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(runner())
        except Exception as e:
            self._gui_log_callback(f"事件循环异常: {e}")
        finally:
            self._loop.close()
            self._loop = None

    def _start_monitor(self):
        """启动持续监控"""
        values = self._get_values()
        if not self._validate(values):
            return

        # 保存配置
        self._save_current_config(values)

        # 构建 Config
        config = self._build_config(values)

        # 切换按钮状态
        self._running = True
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_stop.configure(state=tk.NORMAL)
        self.btn_check_once.configure(state=tk.DISABLED)

        self._log("🚀 启动持续监控…", "INFO")
        if config.bark_key:
            self._log(f"   Bark 推送已启用", "INFO")
        else:
            self._log("   未配置 Bark Key，仅控制台通知", "INFO")

        self.status_var.set(
            f"监控中 — 学号: {config.student_id}  每 {config.check_interval_seconds // 60} 分钟检查"
        )

        # 启动后台线程
        self._loop_thread = threading.Thread(
            target=self._run_async_monitor,
            args=(config,),
            daemon=True,
        )
        self._loop_thread.start()

        # 禁用输入框
        self._set_entries_state(tk.DISABLED)

    def _stop_monitor(self):
        """请求停止监控"""
        if self.monitor:
            self._log("⏹  正在停止监控…", "WARNING")
            self.status_var.set("正在停止…")
            self.monitor.stop()
        else:
            self._on_monitor_stopped()

    def _check_once(self):
        """执行单次检查"""
        values = self._get_values()
        if not self._validate(values):
            return

        self._save_current_config(values)
        config = self._build_config(values)

        self._log("🔍 执行单次检查…", "INFO")
        self.btn_check_once.configure(state=tk.DISABLED)
        self.btn_start.configure(state=tk.DISABLED)
        self.status_var.set("检查中…")

        # 禁用输入
        self._set_entries_state(tk.DISABLED)

        # 后台线程执行
        def run_once():
            async def once():
                monitor = ScoreMonitor(config, headless=True, gui_log_callback=self._gui_log_callback)
                result = await monitor.check_once()
                self.root.after(0, lambda: self._log(
                    "检查完成" if result else "检查失败", "INFO"
                ))
                self.root.after(0, self._on_check_done)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(once())
            loop.close()

        threading.Thread(target=run_once, daemon=True).start()

    def _on_check_done(self):
        """单次检查完成后的 UI 恢复"""
        self.btn_check_once.configure(state=tk.NORMAL)
        self.btn_start.configure(state=tk.NORMAL)
        self.status_var.set("就绪")
        self._set_entries_state(tk.NORMAL)
        self._log("单次检查完成 ✅\n", "INFO")

    def _on_monitor_stopped(self):
        """监控停止后的 UI 恢复"""
        self._running = False
        self.monitor = None
        self.btn_start.configure(state=tk.NORMAL)
        self.btn_stop.configure(state=tk.DISABLED)
        self.btn_check_once.configure(state=tk.NORMAL)
        self.status_var.set("已停止")
        self._set_entries_state(tk.NORMAL)
        self._log("监控已停止 ✅\n", "INFO")

    def _set_entries_state(self, state: str):
        """启用/禁用所有输入框"""
        for _, (_, entry) in self.entries.items():
            entry.configure(state=state)

    # --------------------------------------------------------
    # 关闭窗口
    # --------------------------------------------------------
    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("确认退出", "监控正在运行中，确定要退出吗？"):
                return
            if self.monitor:
                self.monitor.stop()
        self.root.destroy()

    # --------------------------------------------------------
    # 启动
    # --------------------------------------------------------
    def run(self):
        """启动 GUI 事件循环"""
        self.root.mainloop()


# ============================================================
# 检查 Chromium 是否已安装，未安装则自动下载
# ============================================================
def ensure_chromium():
    """检查 playwright Chromium 是否就绪，未安装则引导安装"""
    import subprocess
    from pathlib import Path

    # Playwright 浏览器默认安装路径
    playwright_dir = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not playwright_dir.exists():
        playwright_dir = Path.home() / "AppData" / "Local" / "ms-playwright"

    chromium_marker = playwright_dir / "chromium-1060" / "chrome-win" / "chrome.exe"
    if chromium_marker.exists():
        return True

    # 也可能是其他版本号，模糊查找
    any_chromium = list(playwright_dir.glob("chromium-*/chrome-win/chrome.exe"))
    if any_chromium:
        return True

    return False


def install_chromium():
    """引导安装 Chromium（静默安装）"""
    import subprocess, webbrowser
    msg = (
        "首次使用需要安装 Chromium 浏览器引擎（约 150MB）。\n\n"
        "是否自动下载安装？"
    )
    if messagebox.askyesno("安装 Chromium", msg):
        # 显示等待提示
        progress = tk.Toplevel()
        progress.title("正在安装…")
        progress.geometry("400x120")
        progress.resizable(False, False)
        progress.transient()
        progress.grab_set()
        ttk.Label(progress, text="正在下载 Chromium 浏览器引擎…", font=("", 11)).pack(pady=16)
        ttk.Label(progress, text="首次下载约需 1-5 分钟，请耐心等待", foreground="gray").pack()
        progress.update()

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=600
            )
            progress.destroy()
            if proc.returncode == 0:
                messagebox.showinfo("安装完成", "Chromium 安装成功！请重新启动程序。")
                return True
            else:
                error_msg = proc.stderr[-300:] if proc.stderr else "未知错误"
                messagebox.showerror(
                    "安装失败",
                    f"自动安装失败。请手动运行以下命令安装：\n\n"
                    f"  pip install playwright\n"
                    f"  python -m playwright install chromium\n\n"
                    f"错误: {error_msg}"
                )
                return False
        except subprocess.TimeoutExpired:
            progress.destroy()
            messagebox.showerror("安装超时", "下载超时，请手动安装。")
            return False
        except Exception as e:
            progress.destroy()
            messagebox.showerror("安装异常", f"{e}")
            return False
    else:
        messagebox.showinfo(
            "手动安装",
            "请运行以下命令手动安装：\n\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )
        return False


# ============================================================
# 入口
# ============================================================
def main():
    # 检查 Chromium
    if not ensure_chromium():
        if not install_chromium():
            sys.exit(1)

    # 启动 GUI
    app = App()
    app.run()


if __name__ == "__main__":
    main()
