# 🍃 StatGI — 原神挂机收益统计器

**StatGI** 是一个 Windows 桌面工具，通过 **屏幕捕捉 + OCR 文字识别**，自动统计原神挂机打怪期间的收益（摩拉 / 材料 / 圣遗物·狗粮）。

> 不读取游戏内存、不注入、不修改游戏，仅识别屏幕上的拾取提示 —— 安全、稳定，适合长期挂机与直播场景。

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 摩拉统计 | 识别 `摩拉 ×200`，自动累计今日摩拉 |
| 材料统计 | 识别 `破损的面具 ×2`，按名称统计（内置 574 种材料库） |
| 圣遗物（狗粮） | 出现圣遗物自动计数（内置 299 种圣遗物名单） |
| 防重复统计 | 5 行 FIFO 拾取 Track 生命周期，同一提示只统计一次 |
| 提示栏锚点定位 | 识别「获得」标题自动定位，无需手动框选 |
| 只采集游戏窗口 | 用 PrintWindow 截取原神窗口本身内容，叠加工具（如 BetterGI）的提示不会混入 |
| 每日统计 | 自动换日归档、本地保存、一键清空 |
| 收益统计条 | 直播间小窗口（摩拉/材料/狗粮三格，图标可自定义，可置顶） |
| 托盘 + 任务栏 | 最小化后台继续监测 |
| 图标外置库 | 图标放置于文件夹，可自由替换，无需改代码 |
| 直播数据接口 | `http://127.0.0.1:8765/api` 返回 JSON，可接入 OBS 浏览器源 |
| 低资源占用 | 画面无变化自动跳过识别，后台线程运行不卡界面 |

## 🧠 技术方案

- **语言 / 框架**：Python + Tkinter / CustomTkinter
- **屏幕捕捉**：`PrintWindow`（只截取游戏窗口内容，覆盖层不会混入）
- **文字识别**：`RapidOCR`（中文离线识别，无需 GPU）
- **打包**：PyInstaller（文件夹版，免安装 Python 环境）

### 核心流程

```
只采集原神游戏窗口内容（PrintWindow，BetterGI 等覆盖层不进入）
  → 画面变化检测（无变化跳过，节省 CPU）
  → OCR 文字识别（"摩拉 ×200" / "破损的面具 ×2"）
  → 5 行 FIFO 拾取 Track 去重（同一提示只统计一次）
  → 写入今日收益（本地 JSON 存档）
```

## 🚀 发布版

正式发行版本请在 **[Releases](https://github.com/Cash-553/StatGI/releases)** 页面下载。

## 📁 目录结构（源码）

```
├─ app.py              主程序（界面 + 控制流）
├─ detector.py         检测流水线（文字识别 + 拾取提示 Track 去重）
├─ ocr_engine.py       OCR 引擎（RapidOCR 封装）
├─ printwindow_capture.py  只采集游戏窗口内容（PrintWindow）
├─ ui_detector.py      游戏界面状态检测（返回/关闭键模板匹配）
├─ generated_names.py  材料（574）/ 圣遗物（299）名单
├─ stats.py            每日统计
├─ overlay_bar.py      横向收益统计条
├─ icon_manager.py     图标管理窗口
├─ region_selector.py  区域框选
├─ materials_db.py     材料数据库
├─ tray.py             系统托盘
├─ api_server.py       直播数据接口（Flask）
├─ demo.py             演示模式
└─ theme.py            界面配色主题
```

## 🤝 参与贡献

欢迎提交 Issue 与 Pull Request，共同完善这个项目。可贡献的方向包括：

- 修复问题 / 提交建议：[Issues](https://github.com/Cash-553/StatGI/issues)
- 提高识别准确率：OCR 参数调优、文字解析规则优化
- 改进界面：CustomTkinter 主题与布局
- 补充测试：自动化测试用例
- 完善文档：README、FAQ

### 开发指引

1. Fork 本仓库并 `git clone`
2. 创建特性分支：`git checkout -b feature/xxx`
3. 提交改动并 Push 到你的 Fork
4. 提交 Pull Request

### 约定

- 代码兼容 Python 3.10+
- 不依赖游戏内存 / 注入类技术
- 新增依赖请同步更新 `requirements.txt`

## ⚠️ 注意事项

- 本工具仅用于**个人挂机收益统计**，请遵守游戏运营规则

## 📝 License

[MIT](LICENSE)

