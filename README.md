# 🎓 教务成绩监控

> 自动监控正方教务系统成绩发布，检测到新成绩时通过 Bark 推送通知到手机。

## 功能

| 功能 | 说明 |
|------|------|
| **自动登录** | 支持图形验证码 OCR（ddddocr），自动识别并提交 |
| **成绩查询** | 自动导航到成绩页面，查询指定学年学期 |
| **智能对比** | 与上次缓存对比，仅在有变化时通知 |
| **平时分/卷面分** | 从 __VIEWSTATE 自动提取平时分(PSCJ)和卷面分(QMCJ) |
| **Bark 推送** | 新成绩/成绩更新时通过 Bark 推送到 iOS |
| **持续监控** | 默认每 5 分钟检查一轮 |
| **多账号** | 支持命令行参数临时切换账号 |
| **无需下载浏览器** | 自动使用系统已安装的 Chrome/Edge |

## 快速开始

### 获取Bark的key

去App Store下载软件Bark,在首页的第一个网址里，app/之后的内容就是你的设备的key（末尾没有/）
<img width="1170" height="2532" alt="image" src="https://github.com/user-attachments/assets/2d94c7dd-d33c-4f80-8194-8f189e7c9f8d" />

### 下载

去 [Releases](https://github.com/Dvesiz/score-monitor/releases) 下载 `成绩监控.exe`，放任意目录。

### 首次运行

**双击 `成绩监控.exe`**，按提示输入：

```
学号: 2021******
密码: ********
学年（如 2025-2026）[2025-2026]:
学期（1 或 2）[2]:
Bark Key（手机推送，不填则不通知）:*******************
```

信息会自动保存到同目录下的 `config.json` 中。

### Bark 推送设置（可选）

1. App Store 搜索 **Bark** 并安装
2. 打开 Bark，复制设备专属的推送 Key
3. 首次启动时填入，或运行 `成绩监控.exe --setup`

推送效果：
<img width="1170" height="2532" alt="c06c266feaa7c7ae95843c67290fcd98" src="https://github.com/user-attachments/assets/b3ee0cbf-d3b6-458c-bc95-057b03adda5e" />


> **🎯 成绩更新 (6 门)**
> 新成绩:
>   专业英语: 94 (平98 卷88)
>   物理化学: 92 (平85 卷95)
>   马克思主义基本原理: 86 (平85 卷92)
>   物理化学实验: 80 (平84 卷77)
>   数据分析项目实训: 99 (平 卷99)
>   移动应用开发: 97 (平 卷94)

### 后续运行

以后直接双击 `default.exe` 即可，会自动读取已保存的配置。

## 使用方法

### 命令一览

```bash
成绩监控.exe                    # 读取配置，持续监控（5分钟间隔）
成绩监控.exe --once             # 只检查一次
成绩监控.exe --setup            # 重新配置学号、密码、Bark Key
成绩监控.exe --interval 10      # 临时改为 10 分钟间隔（不保存）
成绩监控.exe --visible          # 显示浏览器窗口（调试用）
成绩监控.exe --student-id 123456 --password xxx    # 临时切换账号
```

### 从源码运行

```bash
# 安装依赖
pip install playwright ddddocr pillow beautifulsoup4 httpx

# 安装浏览器
playwright install chromium

# 运行
python score_monitor.py
```

## 项目结构

```
├── score_monitor.py       # 主程序
├── build_exe.bat          # PyInstaller 打包脚本
├── .gitignore
├── README.md
├── data/
│   └── scores_cache.json  # 成绩缓存（自动生成）
└── dist/
    └── 成绩监控.exe        # 编译后的可执行文件
```

## 首次运行说明

第一次运行会建立成绩缓存快照，不会推送通知：

```
============================================================
          📋 首次成绩快照
============================================================
  时间: 2026-07-08 00:52:27

  📚 当前成绩 (8 门):
    ✅ 专业英语: 94 [平98 卷88]
    ✅ 物理化学: 92 [平85 卷95]
    ✅ 物理化学实验: 80 [平84 卷77]
    ✅ 马克思主义基本原理: 86 [平85 卷92]
    ...
============================================================
```

后续运行才有对比效果。

## 打包为 exe

```bash
# 安装 PyInstaller
pip install pyinstaller

# 打包（含 ddddocr 的 ONNX 模型文件）
pyinstaller --onefile --console --name "成绩监控" ^
  --hidden-import=httpx ^
  --hidden-import=playwright.async_api ^
  --hidden-import=bs4 ^
  --hidden-import=lxml ^
  --collect-all ddddocr ^
  --add-data "config.json;." ^
  score_monitor.py
```

打包后的 exe 在 `dist/` 目录。需要将 `config.json` 放同一目录才能运行。

## 技术细节

### 浏览器策略

1. 启动时自动检测系统已安装的 Chrome/Edge
2. 有系统浏览器 → 直接使用，零下载
3. 无系统浏览器 → 自动下载 Playwright 内置 Chromium 到 `browsers/` 目录（仅一次）

### 验证码

使用 ddddocr 本地 OCR 引擎识别图形验证码，无需调用外部 API。登录失败时自动刷新验证码重试（最多 5 次）。

### 缓存

成绩以 `课程名称 → {分数, 学分, 绩点, 平时分, 卷面分}` 格式缓存到 `data/scores_cache.json`，重启进程不丢失。

### VIEWSTATE 解析

成绩页面使用 ASP.NET __VIEWSTATE 存储数据，程序从成绩查询页面的 iframe 中获取完整 VIEWSTATE（约 30KB），解码并提取每门课程的平时分(PSCJ)和卷面分(QMCJ)，与 HTML 表格中的总成绩合并显示。

## 常见问题

### ❓ 登录失败

- 确保已连接校园网 VPN
- 运行 `--visible` 观察浏览器界面
- 验证码 OCR 有时会认错（如 `0` ↔ `O`），程序会自动重试

### ❓ Bark 推送没收到

- 确认 Bark App 已安装且设备令牌有效
- 用浏览器打开 `https://api.day.app/你的Key/测试` 测试
- 返回 `{"code":200,"message":"success"}` 表示正常

### ❓ VPN 断开

默认 5 分钟检查一次，VPN 短期断开会自动重连。如果 VPN 经常断开，建议拉长间隔（`--interval 10`）。

### ❓ 如何查其他学期

启动时按提示输入，或修改 config.json 中的 `academic_year` 和 `semester`。

## 免责声明

本程序仅用于个人学习用途，请勿用于任何违规用途。使用本程序产生的任何后果由使用者自行承担。
