#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
江苏理工学院 成绩监控程序 v1.0
=================================
监控 http://jwgl.jsut.edu.cn 教务系统的成绩发布
当检测到新成绩或成绩更新时，通过多种方式通知。

使用方法:
  1. 确保已连接 VPN（校园网）
  2. 修改 config.json 中的账号信息（如需要）
  3. python score_monitor.py              # 持续监控（每30分钟）
  4. python score_monitor.py --once       # 只检查一次
  5. python score_monitor.py --visible    # 显示浏览器窗口（调试用）
  6. python score_monitor.py --interval 10  # 每10分钟检查一次

依赖安装:
  pip install playwright ddddocr pillow beautifulsoup4
  playwright install chromium
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ============================================================
# 第三方库导入
# ============================================================
try:
    import ddddocr
except ImportError:
    print("缺少 ddddocr 库，请运行: pip install ddddocr")
    sys.exit(1)

try:
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout
except ImportError:
    print("缺少 playwright 库，请运行: pip install playwright && playwright install chromium")
    sys.exit(1)

# ============================================================
# 路径配置
# ============================================================
# 判断是否在 PyInstaller 打包环境中运行
if getattr(sys, 'frozen', False):
    # 打包为 exe 时，数据存到 exe 所在目录
    BASE_DIR = Path(sys.executable).parent
elif getattr(sys, '_MEIPASS', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

CONFIG_FILE = BASE_DIR / "config.json"
DATA_DIR = BASE_DIR / "data"
CACHE_FILE = DATA_DIR / "scores_cache.json"
LOG_FILE = DATA_DIR / "monitor.log"
SCREENSHOT_DIR = DATA_DIR / "screenshots"


# ============================================================
# 浏览器检测（优先用系统已安装的浏览器，无需下载）
# ============================================================
def _get_browsers_path() -> Path:
    """获取持久化的浏览器安装路径（exe 同级目录下的 browsers/）"""
    browsers = BASE_DIR / "browsers"
    browsers.mkdir(parents=True, exist_ok=True)
    return browsers


def find_system_chrome() -> Optional[str]:
    """
    查找系统中已安装的 Chrome/Edge/Chromium。
    优先使用系统浏览器，避免下载 150MB 的 Playwright 内置 Chromium。
    """
    candidates = [
        # Google Chrome（64位）
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        # Google Chrome（32位）
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        # Google Chrome（用户级别）
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        # Microsoft Edge（64位）
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        # Microsoft Edge（32位）
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        # Microsoft Edge（用户级别）
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    # 最后试试 PATH
    return shutil.which("chrome") or shutil.which("msedge") or shutil.which("chromium")


def ensure_chromium_installed() -> bool:
    """
    当系统无 Chrome/Edge 时，静默下载 Playwright 内置 Chromium。
    安装到 exe 同级的 browsers/ 目录（持久化，重启不丢失）。
    """
    browsers_path = _get_browsers_path()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)

    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        node_exe, cli_script = compute_driver_executable()
        env = get_driver_env()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)

        # 检查是否已有安装
        installed = False
        try:
            installed = any(browsers_path.iterdir())
        except (PermissionError, FileNotFoundError):
            pass

        if installed:
            logger.info("Chromium 已就绪")
            return True

        logger.info("未找到系统浏览器，正在下载 Chromium（约 150MB，只需一次）...")
        r = subprocess.run(
            [node_exe, cli_script, "install", "chromium"],
            env=env, capture_output=True, text=True, timeout=600,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                lower = line.lower()
                if "already" in lower and "chromium" in lower:
                    logger.info(f"  ✓ {line}")
                elif "downloading" in lower:
                    logger.info(f"  ⬇ {line}")
                elif "installing" in lower:
                    logger.info(f"  📦 {line}")
            logger.info("Chromium 下载完成")
            return True
        logger.warning(f"Chromium 安装异常: {r.stderr}")
    except ImportError:
        logger.debug("playwright._impl._driver 不可用，跳过自动检测")
    except subprocess.TimeoutExpired:
        logger.warning("Chromium 下载超时，可手动运行 playwright install chromium")
    except Exception as e:
        logger.debug(f"浏览器检测跳过: {e}")
    return False


# ============================================================
# 配置管理
# ============================================================
class Config:
    """从 config.json 加载配置，或由外部构造时直接传入"""

    def __init__(self, **kwargs):
        self.student_id = kwargs.get("student_id", "")
        self.password = kwargs.get("password", "")
        self.base_url = kwargs.get("base_url", "http://jwgl.jsut.edu.cn")
        self.academic_year = kwargs.get("academic_year", "2025-2026")
        self.semester = kwargs.get("semester", "2")
        interval = kwargs.get("check_interval_minutes", 5)
        self.check_interval_seconds = interval * 60
        self.captcha_max_retries = kwargs.get("captcha_max_retries", 5)
        self.bark_enabled = bool(kwargs.get("bark_key"))
        self.bark_key = kwargs.get("bark_key", "")
        self.pushplus_enabled = False
        self.pushplus_token = kwargs.get("pushplus_token", "")

    @classmethod
    def load(cls) -> "Config":
        """从 JSON 文件加载配置"""
        cfg = cls()

        if not CONFIG_FILE.exists():
            logger.warning(f"配置文件 {CONFIG_FILE} 不存在，使用默认配置")
            return cfg

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            cfg.student_id = data.get("student_id", cfg.student_id)
            cfg.password = data.get("password", cfg.password)
            cfg.base_url = data.get("base_url", cfg.base_url)
            cfg.academic_year = data.get("academic_year", cfg.academic_year)
            cfg.semester = data.get("semester", cfg.semester)
            cfg.captcha_max_retries = data.get("captcha_max_retries", cfg.captcha_max_retries)

            interval = data.get("check_interval_minutes", 5)
            cfg.check_interval_seconds = interval * 60

            notify = data.get("notify", {})
            bark = notify.get("bark", {})
            cfg.bark_enabled = bark.get("enabled", False)
            cfg.bark_key = bark.get("key", "")

            pushplus = notify.get("pushplus", {})
            cfg.pushplus_enabled = pushplus.get("enabled", False)
            cfg.pushplus_token = pushplus.get("token", "")

            logger.info(f"配置已加载: 学号={cfg.student_id}, 检查间隔={interval}分钟")

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"读取配置文件失败: {e}")

        return cfg

    def save(self):
        """保存配置到 config.json"""
        data = {
            "student_id": self.student_id,
            "password": self.password,
            "base_url": self.base_url,
            "academic_year": self.academic_year,
            "semester": self.semester,
            "check_interval_minutes": max(1, self.check_interval_seconds // 60),
            "captcha_max_retries": self.captcha_max_retries,
            "notify": {
                "bark": {"enabled": self.bark_enabled, "key": self.bark_key},
                "pushplus": {"enabled": self.pushplus_enabled, "token": self.pushplus_token},
            },
        }
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ 配置已保存到 {CONFIG_FILE}")

    @property
    def login_url(self) -> str:
        return f"{self.base_url}/xs_main.aspx?xh={self.student_id}"


# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("score_monitor")
logger.setLevel(logging.DEBUG)

_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(_formatter)
logger.addHandler(_console_handler)


def _ensure_dirs():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _setup_console_encoding():
    """解决 Windows GBK 终端无法打印 emoji/中文的问题"""
    if sys.platform != "win32":
        return
    if sys.stdout is None:
        return
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


_setup_console_encoding()


def _setup_file_logging():
    """设置文件日志"""
    _file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(_file_handler)


# ============================================================
# CAPTCHA 识别器
# ============================================================
class CaptchaSolver:
    """验证码识别器（封装 ddddocr）"""

    def __init__(self):
        self.ocr = ddddocr.DdddOcr(show_ad=False)
        logger.info("验证码 OCR 引擎已初始化")

    def solve(self, image_bytes: bytes) -> str:
        """识别验证码图片, 返回识别结果"""
        try:
            result = self.ocr.classification(image_bytes)
            return result.strip()
        except Exception as e:
            logger.error(f"验证码 OCR 失败: {e}")
            return ""


# ============================================================
# 成绩数据持久化
# ============================================================
class ScoreStore:
    """成绩缓存管理"""

    def __init__(self):
        self._file = CACHE_FILE
        self._data = self._load()

    def _load(self) -> dict:
        if self._file.exists():
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"读取缓存失败: {e}")
        return {}

    def save(self):
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @property
    def previous(self) -> dict:
        return self._data

    def update(self, new_scores: dict):
        self._data = new_scores
        self.save()


# ============================================================
# 通知器
# ============================================================
class Notifier:

    def __init__(self, config: Config):
        self.config = config

    @staticmethod
    def console(title: str, new_courses: dict, updated_courses: dict):
        """打印带 Emoji 的控制台通知"""
        sep = "=" * 60
        lines = [
            f"\n{sep}",
            f"          {title}",
            f"{sep}",
            f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if new_courses:
            lines.append(f"\n  📚 新出成绩 ({len(new_courses)} 门):")
            for name, info in new_courses.items():
                lines.append(f"    ✅ {name}: {info.get('score', '?')} 分")
        if updated_courses:
            lines.append(f"\n  🔄 成绩更新 ({len(updated_courses)} 门):")
            for name, (old, new) in updated_courses.items():
                lines.append(f"    🔄 {name}: {old} → {new}")
        if not new_courses and not updated_courses:
            lines.append("  暂无变化\n")
        lines.extend([f"{sep}\n"])
        print("\n".join(lines))

    async def bark(self, title: str, content: str):
        if not self.config.bark_enabled or not self.config.bark_key:
            return
        try:
            import httpx
            from urllib.parse import quote
            # Bark API: URL中不能有换行符，需要严格URL编码
            safe_title = quote(title, safe="")
            safe_content = quote(content.strip(), safe="")
            url = f"https://api.day.app/{self.config.bark_key}/{safe_title}/{safe_content}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                logger.debug(f"Bark 响应: {resp.status_code} {resp.text[:100]}")
            logger.info("Bark 推送成功")
        except ImportError:
            logger.debug("httpx 未安装，跳过 Bark")
        except Exception as e:
            logger.warning(f"Bark 推送失败: {e}")

    async def pushplus(self, title: str, content: str):
        if not self.config.pushplus_enabled or not self.config.pushplus_token:
            return
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    "https://www.pushplus.plus/send",
                    json={"token": self.config.pushplus_token, "title": title, "content": content},
                    timeout=10,
                )
            logger.info("PushPlus 推送成功")
        except ImportError:
            logger.debug("httpx 未安装，跳过 PushPlus")
        except Exception as e:
            logger.warning(f"PushPlus 推送失败: {e}")


# ============================================================
# 核心监控器
# ============================================================
class ScoreMonitor:
    """成绩监控器"""

    def __init__(self, config: Config, headless: bool = True, gui_log_callback=None):
        """
        gui_log_callback: 可选，接收 (msg: str) 用于 GUI 显示日志
        """
        self.cfg = config
        self.headless = headless
        self._stopped = False
        self.captcha = CaptchaSolver()
        self.store = ScoreStore()
        self.notifier = Notifier(config)
        _ensure_dirs()
        _setup_file_logging()
        self._gui_handler = None
        if gui_log_callback:
            self._gui_handler = logging.Handler()
            self._gui_handler.setLevel(logging.INFO)
            self._gui_handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
            )
            # 使用 closure 捕获 handler 实例，emit 会被 logging 正确调用
            _hdlr = self._gui_handler
            _hdlr.emit = lambda record: gui_log_callback(_hdlr.format(record))
            logger.addHandler(self._gui_handler)

    def stop(self):
        """请求停止监控循环"""
        self._stopped = True
        logger.info("⏹️  收到停止信号，将在本轮检查结束后退出")

    # --------------------------------------------------------
    # 登录
    # --------------------------------------------------------
    async def _solve_captcha(self, page) -> str:
        """识别验证码"""
        selectors = [
            "#icode",
            "img[src*='CheckCode']",
            "img[src*='checkcode']",
            "img[src*='CheckCode.aspx']",
            "td:has(input[name*='txtSecretCode']) img",
            "table[id*='Table'] img",
        ]
        img = None
        for sel in selectors:
            img = await page.query_selector(sel)
            if img:
                logger.debug(f"验证码图片匹配: {sel}")
                break
        if not img:
            logger.warning("未找到验证码图片")
            return ""

        try:
            raw = await img.screenshot()
            code = self.captcha.solve(raw)
            logger.info(f"验证码识别: '{code}'")
            return code
        except Exception as e:
            logger.error(f"验证码截图失败: {e}")
            return ""

    async def login(self, page) -> bool:
        """登录，含验证码重试"""
        url = self.cfg.login_url
        logger.info(f"打开登录页: {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # 绑定对话框自动关闭（登录失败时可能会弹 alert）
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        for attempt in range(1, self.cfg.captcha_max_retries + 1):
            logger.info(f"--- 登录尝试 {attempt}/{self.cfg.captcha_max_retries} ---")

            # 1) 验证码
            code = await self._solve_captcha(page)
            if not code:
                logger.warning("验证码为空，刷新验证码后重试...")
                # 点击验证码图片刷新
                try:
                    code_img = await page.query_selector("#icode, img[src*='CheckCode']")
                    if code_img:
                        await code_img.click()
                except:
                    pass
                await page.wait_for_timeout(2000)
                continue

            # 2) 填表
            await page.fill("#txtUserName", self.cfg.student_id)
            pw = await page.query_selector("#TextBox2")
            if pw:
                await pw.fill(self.cfg.password)
            await page.fill("#txtSecretCode", code)

            # 3) 提交
            btn = await page.query_selector("#Button1")
            if btn:
                await btn.click()
            else:
                await page.keyboard.press("Enter")

            # 等待页面跳转（可能跳转回 xs_main 或其他页面）
            await page.wait_for_timeout(3000)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except:
                pass
            await page.wait_for_timeout(2000)

            # 4) 检查登录状态 — 看登录表单是否消失了
            login_form_still_exists = await page.query_selector("#txtUserName")
            if not login_form_still_exists:
                logger.info("✅ 登录成功（登录表单已消失）")
                await page.wait_for_load_state("networkidle", timeout=15000)
                await page.wait_for_timeout(2000)
                return True

            # 打印当前 URL 和标题调试
            cur = page.url.lower()
            title = await page.title()
            logger.debug(f"当前 URL: {cur}")
            logger.debug(f"当前标题: {title}")
            logger.warning(f"第{attempt}次登录失败，重试...")

            # 重试：回到登录页
            await page.goto(url, wait_until="networkidle", timeout=15000)
            await page.wait_for_timeout(2000)

        logger.error("❌ 登录失败次数过多")
        return False

    # --------------------------------------------------------
    # 导航
    # --------------------------------------------------------
    async def navigate_to_score_page(self, page) -> None:
        """点击导航菜单进入成绩查询页面"""
        logger.info("导航到成绩查询…")

        # 等待页面加载
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(2000)

        frames = page.frames
        logger.debug(f"frames 数量: {len(frames)}")

        # 尝试在 frames 中找到导航菜单
        nav_frame = None
        for f in frames:
            try:
                txt = await f.inner_text("body") if await f.query_selector("body") else ""
                if "信息查询" in txt:
                    nav_frame = f
                    logger.info("在 frame 中找到导航菜单")
                    break
            except Exception:
                continue

        target = nav_frame or page

        # 点击"信息查询"展开
        for sel in [
            "a:has-text('信息查询')",
            "span:has-text('信息查询')",
            "td:has-text('信息查询')",
            "font:has-text('信息查询')",
            "[class*='node']:has-text('信息查询')",
        ]:
            els = await target.query_selector_all(sel)
            for e in els:
                try:
                    await e.click()
                    logger.debug("点击 信息查询")
                    await page.wait_for_timeout(1500)
                    break
                except Exception:
                    continue
            if els:
                break

        # 点击"成绩查询"
        for sel in [
            "a:has-text('成绩查询')",
            "span:has-text('成绩查询')",
            "td:has-text('成绩查询')",
            "font:has-text('成绩查询')",
        ]:
            els = await target.query_selector_all(sel)
            for e in els:
                try:
                    await e.click()
                    logger.info("点击 成绩查询")
                    await page.wait_for_timeout(2000)
                    break
                except Exception:
                    continue
            if els:
                break

        await page.wait_for_load_state("networkidle", timeout=20000)
        await page.wait_for_timeout(3000)
        logger.info("导航完成")

    # --------------------------------------------------------
    # 查询 & 解析
    # --------------------------------------------------------
    async def query_scores(self, page) -> list:
        """选择学年学期 → 点击查询 → 解析表格"""
        logger.info("执行成绩查询…")

        # 找到成绩查询的 iframe (name="zhuti" 或包含 xscjcx / 学年)
        query_frame = page
        for wait_attempt in range(15):
            for f in page.frames:
                try:
                    if not await f.query_selector("body"):
                        continue
                    url = f.url.lower()
                    txt = await f.inner_text("body")
                    if "xscjcx" in url or ("学年" in txt and ("课程" in txt or "成绩" in txt)):
                        query_frame = f
                        logger.debug(f"找到成绩查询 frame (URL: {url[:60]})")
                        break
                except Exception:
                    continue
            if query_frame != page:
                break
            await page.wait_for_timeout(1000)
        else:
            logger.warning("等待 15s 后仍未找到成绩查询 frame")

        # ---- 选学年 ----
        for sel in [
            "select[id*='ddlXN']", "select[name*='ddlXN']",
            f"select:has(option[value*='{self.cfg.academic_year}'])",
        ]:
            el = await query_frame.query_selector(sel)
            if el:
                try:
                    await el.select_option(label=self.cfg.academic_year)
                    logger.info(f"学年: {self.cfg.academic_year}")
                    break
                except Exception:
                    try:
                        await el.select_option(value=self.cfg.academic_year)
                        logger.info(f"学年(value): {self.cfg.academic_year}")
                        break
                    except Exception:
                        continue
        else:
            logger.warning("未找到学年选择器")
            await page.screenshot(path=str(SCREENSHOT_DIR / "no_year_select.png"))

        await page.wait_for_timeout(500)

        # ---- 选学期 ----
        for sel in [
            "select[id*='ddlXQ']", "select[name*='ddlXQ']",
        ]:
            el = await query_frame.query_selector(sel)
            if el:
                try:
                    await el.select_option(label=self.cfg.semester)
                    logger.info(f"学期: {self.cfg.semester}")
                    break
                except Exception:
                    continue
        else:
            logger.warning("未找到学期选择器")

        await page.wait_for_timeout(500)

        # ---- 点击"学期成绩"（唯一一次！） ----
        btn = await query_frame.query_selector("input[value='学期成绩']")
        if not btn:
            btn = await query_frame.query_selector("input[value*='学期']")
        if btn:
            logger.info("点击查询按钮")
            try:
                await btn.click()
            except Exception:
                await query_frame.evaluate("document.querySelector('input[value*=\"学期\"]').click()")
            # 等待 iframe 加载完成（ASP.NET postback 触发 iframe 刷新）
            for _ in range(20):
                await page.wait_for_timeout(1000)
                # 检查 iframe 里是否出现了成绩表格
                try:
                    tbl = await query_frame.query_selector_all("table")
                    if len(tbl) >= 2:
                        rows = await tbl[1].query_selector_all("tr")
                        if len(rows) >= 6:
                            logger.info("成绩表格加载完成")
                            break
                except Exception:
                    pass
        else:
            logger.warning("未找到学期成绩按钮，仍尝试解析表格")

        await page.wait_for_timeout(2000)

        # ---- 解析：从正确的 iframe 里找 ----
        result = await self._parse_table(query_frame)
        if result:
            logger.info(f"从 frame 解析到 {len(result)} 条成绩")
            return result

        # 保底：搜所有 frame
        for f in page.frames:
            if f == query_frame:
                continue
            result = await self._parse_table(f)
            if result:
                logger.info(f"从 frame[{f.url[:30]}] 解析到 {len(result)} 条成绩")
                return result

        return []

    async def _parse_table(self, frame) -> list:
        """从 frame/page 解析成绩表格"""
        logger.debug("解析成绩表格…")

        # 查找表格元素
        table = None
        for sel in [
            "table[id*='dgrd']",
            "table[id*='DataGrid']",
            "table[id*='datagrid']",
            "table[class*='datagrid']",
            "table.datagrid",
            "table[id*='GridView']",
            "table[id*='gv']",
        ]:
            table = await frame.query_selector(sel)
            if table:
                logger.debug(f"表格选择器: {sel}")
                break

        # 如果没匹配到，智能查找
        if not table:
            tables = await frame.query_selector_all("table")
            for t in tables:
                rows = await t.query_selector_all("tr")
                if len(rows) < 3:
                    continue
                cells = await rows[0].query_selector_all("td, th")
                texts = [((await c.inner_text()).strip()) for c in cells]
                # 必须第一行同时包含"课程名称"和"成绩"作为列标题
                has_course_name = any("课程名称" in t for t in texts)
                has_score = any(c == "成绩" or "成绩" in c for c in texts)
                if has_course_name and has_score:
                    table = t
                    logger.info("关键词匹配找到成绩表格")
                    break

        if not table:
            logger.warning("未找到成绩表格")
            return []

        # 提取表头
        all_rows = await table.query_selector_all("tr")
        headers = []
        start_idx = 0

        for i, row in enumerate(all_rows):
            cells = await row.query_selector_all("td, th")
            texts = [(await c.inner_text()).strip() for c in cells]
            # 表头必须同时包含"课程名称"和"成绩"作为列名
            h_joined = " ".join(texts)
            if "课程名称" in h_joined and "成绩" in h_joined:
                headers = texts
                start_idx = i + 1
                logger.info(f"检测到表头，第{i}行")
                break

        if not headers:
            # 第一行当表头
            cells = await all_rows[0].query_selector_all("td, th")
            headers = [(await c.inner_text()).strip() for c in cells]
            start_idx = 1

        # 提取数据
        scores = []
        for row in all_rows[start_idx:]:
            cells = await row.query_selector_all("td, th")
            texts = [(await c.inner_text()).strip() for c in cells]
            if not any(t.strip() for t in texts):
                continue
            row_data = {}
            for i, h in enumerate(headers):
                val = texts[i] if i < len(texts) else ""
                # 特殊处理: 去除全角/半角空格及不可见字符
                h_clean = h.replace("\u3000", "").replace(" ", "").strip()
                row_data[h_clean] = val
            scores.append(row_data)

        if scores:
            sample_keys = list(scores[0].keys())
            logger.info(f"表头字段: {sample_keys}")
            logger.info(f"样例数据: {list(scores[0].values())[:3]}")

        return scores

    # --------------------------------------------------------
    # 对比 & 通知
    # --------------------------------------------------------
    def _normalize(self, raw: list) -> dict:
        """标准化成绩字典"""
        norm = {}
        for item in raw:
            name = (
                item.get("课程名称")
                or item.get("课程")
                or item.get("科目名称")
                or item.get("课程名")
                or f"课程{len(norm)}"
            )
            score = (
                item.get("成绩")
                or item.get("最终成绩")
                or item.get("总评成绩")
                or item.get("百分成绩")
                or item.get("考试成绩")
                or ""
            )
            credits = item.get("学分", item.get("学　　分", ""))
            gpa = item.get("绩点", item.get("学分绩点", ""))
            norm[name] = {"score": score, "credits": credits, "gpa": gpa}
        return norm

    def _compare_and_notify(self, raw_scores: list):
        """对比缓存，若有变化则通知"""
        current = self._normalize(raw_scores)
        if not current:
            logger.info("成绩为空，跳过")
            return

        prev = self.store.previous

        if not prev:
            Notifier.console("📋 首次成绩快照", current, {})
            logger.info(f"首次检查: {len(current)} 门")
            # 首次也推送通知
            title = "🎯 成绩发布"
            if len(current) == 1:
                title += " (1 门)"
            else:
                title += f" ({len(current)} 门)"
            parts = ["新成绩:"]
            parts.extend([f"  {n}: {d['score']}" for n, d in current.items()])
            body = "\n".join(parts)
            bark_task = asyncio.ensure_future(self.notifier.bark(title, body))
            pushplus_task = asyncio.ensure_future(self.notifier.pushplus(title, body))
            self.store.update(current)
            return [bark_task, pushplus_task]
        else:
            new, updated = {}, {}
            for name, info in current.items():
                if name not in prev:
                    new[name] = info
                elif prev[name].get("score") != info["score"]:
                    updated[name] = (prev[name].get("score", "?"), info["score"])

            if new or updated:
                title = "🎯 成绩更新"
                if new:
                    title += f" (+{len(new)})"
                if updated:
                    title += f" (~{len(updated)})"
                Notifier.console(title, new, updated)

                for name, info in new.items():
                    logger.info(f"[新增] {name}: {info['score']}")
                for name, (o, n) in updated.items():
                    logger.info(f"[更新] {name}: {o}→{n}")

                # 异步推送
                parts = []
                if new:
                    parts.append("新成绩:")
                    parts.extend([f"  {n}: {d['score']}" for n, d in new.items()])
                if updated:
                    parts.append("成绩更新:")
                    parts.extend([f"  {n}: {o}→{n_}" for n, (o, n_) in updated.items()])
                body = "\n".join(parts)
                bark_task = asyncio.ensure_future(self.notifier.bark(title, body))
                pushplus_task = asyncio.ensure_future(self.notifier.pushplus(title, body))
                self.store.update(current)
                return [bark_task, pushplus_task]
            else:
                logger.info("✅ 成绩无变化")

        self.store.update(current)
        return []

    # --------------------------------------------------------
    # 主流程
    # --------------------------------------------------------
    async def check_once(self) -> bool:
        """执行一次完整的检查"""
        logger.info("=" * 60)
        logger.info(f"开始检查 ({datetime.now():%Y-%m-%d %H:%M:%S})")
        logger.info("=" * 60)

        playwright = await async_playwright().start()
        browser = None
        try:
            # 优先使用系统已安装的浏览器（无需下载 150MB 内置 Chromium）
            sys_chrome = find_system_chrome()
            launch_opts = {
                "headless": self.headless,
                "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            }
            if sys_chrome:
                launch_opts["executable_path"] = sys_chrome
                logger.info(f"使用系统浏览器: {sys_chrome}")
            else:
                # 无系统浏览器 → 确保 Playwright 内置浏览器已安装
                if not getattr(self, '_browser_checked', False):
                    ensure_chromium_installed()
                    self._browser_checked = True
                logger.info("使用 Playwright 内置 Chromium")

            browser = await playwright.chromium.launch(**launch_opts)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            page.set_default_timeout(30000)

            # ---- 1. 登录 ----
            if not await self.login(page):
                await page.screenshot(path=str(SCREENSHOT_DIR / "login_fail.png"))
                return False
            await page.screenshot(path=str(SCREENSHOT_DIR / "login_ok.png"))

            # ---- 2. 导航 ----
            await self.navigate_to_score_page(page)
            await page.screenshot(path=str(SCREENSHOT_DIR / "navigated.png"))

            # ---- 3. 查成绩 ----
            scores = await self.query_scores(page)
            if scores:
                logger.info(f"共 {len(scores)} 门课程")
                for s in scores[:10]:
                    name = s.get("课程名称", s.get("课程", "?"))
                    sc = s.get("成绩", s.get("最终成绩", "?"))
                    logger.info(f"  {name}: {sc}")
                if len(scores) > 10:
                    logger.info(f"  ... 还有 {len(scores)-10} 门")
            else:
                logger.warning("未查到成绩（可能未发布）")

            # ---- 4. 对比通知 ----
            pending = self._compare_and_notify(scores)
            # 等异步通知推完再退出（确保日志完整）
            if pending:
                done, _ = await asyncio.wait(pending, timeout=10)
                for t in done:
                    try:
                        t.result()
                    except Exception as e:
                        logger.error(f"推送失败: {e}")
            return True

        except PwTimeout as e:
            logger.error(f"超时: {e}")
            return False
        except Exception as e:
            logger.error(f"异常: {e}", exc_info=True)
            return False
        finally:
            if browser:
                await browser.close()
            await playwright.stop()

    async def run_loop(self):
        """持续监控"""
        interval = self.cfg.check_interval_seconds
        logger.info(f"📡 每 {interval//60} 分钟检查一次，点击「停止监控」或关闭窗口退出")
        self._stopped = False
        await self.check_once()
        while not self._stopped:
            next_check = datetime.now() + timedelta(seconds=interval)
            logger.info(f"⏳ {interval//60} 分钟后再次检查（{next_check:%H:%M}）")
            try:
                await asyncio.sleep(interval)
                if self._stopped:
                    break
                await self.check_once()
            except (asyncio.CancelledError, KeyboardInterrupt):
                logger.info("监控已停止")
                break
            except Exception as e:
                logger.error(f"检查异常: {e}，{interval//60}分钟后重试")
                await asyncio.sleep(interval)
        logger.info("监控循环已退出")


# ============================================================
# 入口
# ============================================================
async def main():
    parser = argparse.ArgumentParser(
        description="📚 教务成绩监控 - CLI 版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  成绩监控.exe                          # 首次启动会自动引导输入配置
  成绩监控.exe --once                   # 只检查一次
  成绩监控.exe --interval 10            # 每10分钟检查一次
  成绩监控.exe --visible                # 显示浏览器窗口（调试用）
  成绩监控.exe --setup                  # 重新配置学号、密码
  成绩监控.exe --student-id 123456      # 命令行指定学号（覆盖 config.json）

首次使用:
  直接双击本程序，按提示输入学号、密码即可。
""",
    )
    parser.add_argument("--once", action="store_true", help="只检查一次")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--interval", type=int, default=0, help="检查间隔(分钟)")
    parser.add_argument("--student-id", help="学号（覆盖 config.json）")
    parser.add_argument("--password", help="密码（覆盖 config.json）")
    parser.add_argument("--base-url", help="教务系统地址（覆盖 config.json）")
    parser.add_argument("--year", help="学年，如 2025-2026（覆盖 config.json）")
    parser.add_argument("--semester", type=str, help="学期 1 或 2（覆盖 config.json）")
    parser.add_argument("--bark-key", help="Bark 推送 Key")
    parser.add_argument("--setup", action="store_true", help="重新配置账号信息")
    args = parser.parse_args()

    config = Config.load()

    if args.interval > 0:
        config.check_interval_seconds = args.interval * 60
    if args.student_id:
        config.student_id = args.student_id
    if args.password:
        config.password = args.password
    if args.base_url:
        config.base_url = args.base_url
    if args.year:
        config.academic_year = args.year
    if args.semester:
        config.semester = args.semester
    if args.bark_key:
        config.bark_key = args.bark_key
        config.bark_enabled = True

    # 交互式配置：首次使用或 --setup
    if args.setup or not config.student_id or not config.password:
        print("=" * 50)
        print("  📚 成绩监控 - 首次配置")
        print("  输入信息后将自动保存到 config.json")
        print("=" * 50)

        sid = input(f"\n学号 [{config.student_id}]: ").strip()
        if sid:
            config.student_id = sid

        pw = input("密码: ").strip()
        if pw:
            config.password = pw

        yr = input(f"学年（如 2025-2026）[{config.academic_year}]: ").strip()
        if yr:
            config.academic_year = yr

        sm = input(f"学期（1 或 2）[{config.semester}]: ").strip()
        if sm:
            config.semester = sm

        bk = input(f"Bark Key（手机推送，不填则不通知）[{config.bark_key or ''}]: ").strip()
        if bk:
            config.bark_key = bk
            config.bark_enabled = True
        elif config.bark_key:
            # 保持已有 key
            pass
        else:
            config.bark_enabled = False

        print()
        config.save()

    if not config.student_id or not config.password:
        logger.error("❌ 未配置学号和密码！")
        sys.exit(1)

    logger.info(f"📋 配置: 学号={config.student_id}, 学年={config.academic_year}, "
                f"学期={config.semester}, Bark={'✅' if config.bark_enabled else '❌'}")

    monitor = ScoreMonitor(config, headless=not args.visible)

    if args.once:
        await monitor.check_once()
    else:
        await monitor.run_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.critical(f"崩溃: {e}", exc_info=True)
        sys.exit(1)
