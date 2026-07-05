# 🎓 教务成绩监控

> 自动监控正方教务系统成绩发布，检测到新成绩时通过 Bark 推送通知到手机。

## 功能

| 功能 | 说明 |
|------|------|
| **自动登录** | 支持图形验证码 OCR（ddddocr），自动识别并提交 |
| **成绩查询** | 自动导航到成绩页面，查询指定学年学期 |
| **智能对比** | 与上次缓存对比，仅在有变化时通知 |
| **Bark 推送** | 新成绩/成绩更新时通过 Bark 推送到 iOS |
| **持续监控** | 默认每 5 分钟检查一轮 |
| **多账号** | 支持命令行参数临时切换账号 |
| **无需浏览器** | 自动使用系统已安装的 Chrome/Edge，无需额外下载 |

## 快速开始

### 下载

去 [Releases](https://github.com/your-repo/releases) 下载 `成绩监控.exe`，放任意目录。

### 首次运行

**双击 `成绩监控.exe`**，按提示输入：

```
学号: 2023144106
密码: ********
学年（如 2025-2026）[2025-2026]:
学期（1 或 2）[2]:
Bark Key（手机推送，不填则不通知）:
```

信息会自动保存到同目录下的 `config.json` 中。

### Bark 推送设置（可选）

1. App Store 搜索 **Bark** 并安装
2. 打开 Bark，复制设备专属的推送 Key
3. 首次启动时填入，或运行 `成绩监控.exe --setup`

推送效果：

> **🎯 成绩发布 (5 门)**
> 新成绩:
>   专业英语: 94
>   软件测试与质量: 86

### 后续运行

以后直接双击 `成绩监控.exe` 即可，会自动读取已保存的配置。

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
├── config.example.json    # 配置模板（供参考）
├── .gitignore
├── README.md
└── dist/
    └── 成绩监控.exe        # 编译后的可执行文件
```

## 首次运行说明

第一次运行会建立成绩缓存快照，不会推送通知：

```
============================================================
          📋 首次成绩快照
============================================================
  时间: 2026-07-06 01:18:30

  📚 新出成绩 (5 门):
    ✅ 专业英语: 94 分
    ✅ 软件测试与质量: 86 分
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
  --hidden-import=playwright._impl._driver ^
  --hidden-import=playwright.async_api ^
  --hidden-import=bs4 ^
  --hidden-import=lxml ^
  --collect-data ddddocr ^
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

成绩以 `课程名称 → {分数, 学分, 绩点}` 格式缓存到 `data/scores_cache.json`，重启进程不丢失。

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
