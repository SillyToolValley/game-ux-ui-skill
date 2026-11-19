# game-ux-ui-skill

![Version](https://img.shields.io/badge/version-0.5.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Core deps](https://img.shields.io/badge/core%20dependencies-0-brightgreen)

[English](README.md) · **中文** · [한국어](README.ko.md) · [日本語](README.ja.md)

面向 AI 编码代理的**锚点优先**游戏 UI 工作流，以及一个让这个循环保持诚实的小型 CLI。

选**一张**已发售游戏的界面作为锚点，仔细拆解，直接以完整保真度构建你的界面，然后把构建截图放在锚点旁边缩小差距。最多重复三轮。

## 为什么锚点优先

早期版本会收集大量参考图，把它们编译成带审批关卡的 JSON 界面契约，并渲染灰色线框图。产出看起来很完整，但实际上，直接把一张优秀已发售游戏的截图交给前沿模型，得到的界面更好。

- 一张已发售的界面是数百个相互调校过的决策。混合多张参考，或在动笔之前先抽象成契约，都会丢掉这种调校，回归到品类平均水平。
- 模型会匹配它能看到的东西。一张具体的图能设定质量标杆，十二张图的文字描述做不到。
- 首次渲染之前的规格说明，把精力花在了回报最低的地方。行之有效的通用 UI 技能都把重心放在首次渲染之后：看结果、对比、修正。

因此 v0.5 把单一锚点作为默认路径，契约流水线降级为可选的交接阶段。

## 锚点循环

```bash
# 1. 登记该界面所锚定的那一张已发售界面
ui-ref anchor add captures/reward-screen.png --screen level-up \
  --game "<游戏名>" --source-url "<来源>"

# 2. 对照图片填写 ui_anchor/level-up/ANATOMY.md：
#    实测比例、字号、色彩角色、为何有效、保留/改变/舍弃

# 3. 构建真实界面（HTML 或引擎内），并把截图存入一轮对比
ui-ref shot build/level-up.html --screen level-up
#    引擎构建？改用你自己的截图：
ui-ref compare captures/unity-level-up.png --screen level-up

# 4. 打开 ui_anchor/level-up/rounds/01/compare.html，填写 critique.md，修复最重要的三个差距

# 5. 守住底线：字号、对比度、安全区、裁切、初始焦点
ui-ref audit build/level-up.html --platform tv
```

| 命令 | 作用 | 依赖 |
| --- | --- | --- |
| `ui-ref anchor add` | 每个界面保存一张主锚点，记录来源、哈希、尺寸和提取的调色板，并生成 `ANATOMY.md` 模板。拒绝第二张主锚点；辅助参考最多两张，且必须用 `--borrow` 说明借用内容。 | 标准库（调色板需浏览器 extra） |
| `ui-ref anchor show` | 列出锚点、拆解文档完成度和已进行的轮数。 | 标准库 |
| `ui-ref shot` | 以锚点尺寸截取 HTML 文件或 URL，并开始一轮对比。 | 浏览器 extra |
| `ui-ref compare` | 生成并排对比页：眯眼（模糊）、明度（灰度）、安全区与三分线参考、叠加、闪烁切换，以及九个视角的评审模板。可用于任何截图，包括引擎截图。 | 标准库 |
| `ui-ref audit` | 按平台预设（`tv`、`desktop`、`handheld`、`mobile`）对 HTML 构建做确定性底线检查，说明未评估项，失败时以非零码退出。 | 浏览器 extra |

`audit` 只守底线，无法告诉你界面好不好；那要靠 `compare` 和你的眼睛。

## 技能

[`.claude/skills/game-ux-ui-design/`](.claude/skills/game-ux-ui-design/) 是面向代理的一半，复制到项目的技能目录即可。`SKILL.md` 是简短的路由，细节按需加载（技能正文为英文）。

| 文件 | 内容 |
| --- | --- |
| `references/anchor-workflow.md` | 选主锚点、拆解、转译（保留结构，改变身份）、完整示例 |
| `references/finding-anchors.md` | 锚点从哪里来、如何截取、图库网站的使用条款 |
| `references/game-ui-tells.md` | 模型生成的游戏 UI 会趋同的特征，以及已发售游戏的做法 |
| `references/platform-numbers.md` | 字号、对比度、安全区、触控、本地化的底线，附来源和核实状态 |
| `references/feel-and-states.md` | 时序起始值、焦点与导航规则、会破坏布局的状态 |
| `references/spec-pipeline.md` | 可选：契约、线框、原型与引擎交接流程 |

### 关于参考网站

图库网站用于**发现**哪款游戏把某个界面做得最好，然后自己截取该界面。Game UI Database 的 robots.txt（2026 年 11 月核实）全面禁止 AI 代理和 AI 训练爬虫，并将其内容标记为 `ai-train=no, use=reference`。因此 `ui-ref collect` 会拒绝该网站的 URL，原有的站点预设也已移除。从任何网站采集前都应先查看其当前条款和 robots 规则。

## 从其他技能学到的

本次重新设计之前，我们调研了广泛使用的通用 UI 技能和游戏专用技能。

- **以一个具体参考作为事实来源** — DESIGN.md 约定（Google `design.md`、`VoltAgent/awesome-design-md`）
- **点名趋同默认值、构建前的简短计划、只在一处大胆、查看渲染结果** — Anthropic `frontend-design`
- **窄动词、与设计判断分离的确定性检查、轮数上限、由非作者评审** — `pbakaus/impeccable`、`Leonxlnx/taste-skill`
- **轻量路由加按需参考、如实标注“未评估”** — `Donchitos/Claude-Code-Game-Studios`、`gamedev-skills/awesome-gamedev-agent-skills`
- **每行数据附来源和核实状态** — `fcsouza/agent-skills`

所调研的技能中，没有一个在首次渲染之前设置契约与线框的编译阶段。

## 可选：规格与交接流水线

当团队需要书面规格、审批记录、可点击的流程原型或引擎脚手架时，v0.4 流水线仍然可用且未改动。请在界面做出来**之后**再运行它。以下内容是对该流水线的说明。

## GRENADE! — 真实项目展示

以下概念图套件是在为开发中的 Unity 游戏 **GRENADE!** 制作 UX/UI 规格时，使用 `ui-ref` 规范契约管线与配套工作流最终确定的版本。同一轮工作结构化并验证了 10 个核心界面、8 个可复用组件和 24 条用户流程，同时生成确定性线框图、可点击状态原型以及 Unity uGUI 交接数据。

| 美术方向关键帧 | 俱乐部房间枢纽 |
| :---: | :---: |
| [![描绘明亮屋顶接球赛场与温暖社团房间的 GRENADE 美术方向关键帧](docs/showcase/grenade/01-art-direction-keyframe.png)](docs/showcase/grenade/01-art-direction-keyframe.png) | [![仅展开最近任务标记的 GRENADE 俱乐部房间枢纽概念图](docs/showcase/grenade/02-club-room-hub.png)](docs/showcase/grenade/02-club-room-hub.png) |
| **四人比赛 HUD** | **结果与再战界面** |
| [![展示四名玩家状态和比赛阶段的 GRENADE 比赛 HUD](docs/showcase/grenade/03-match-hud.png)](docs/showcase/grenade/03-match-hud.png) | [![包含回放、再战与返回房间操作的 GRENADE 结果界面](docs/showcase/grenade/04-result-rewards.png)](docs/showcase/grenade/04-result-rewards.png) |

> 这些图片用于传达美术方向、信息层级与构图。图片中的文字、数值和货币值均为示例；实现时仍以经过评审的 `ui_design` 契约为唯一事实来源。

一个以证据为基础的游戏 UX/UI 研究与规格编译器。`ui-ref` 收集和索引参考证据，把经过评审的决策转为可版本管理的界面/组件契约，验证其可追溯性和生命周期，并从同一份源数据生成确定性的线框图、可读规格、可点击原型以及引擎交接脚手架。

核心工作流没有外部依赖。JavaScript 渲染的参考站点可选用 Playwright；只有从视频提取帧时才需要 FFmpeg。

> 本工具不会把 AI 的猜测变成已批准设计。逆向分析结果始终以 `draft` 导入，最终批准必须由具名的人类评审者明确确认。

## v0.4.0 概览

- **参考证据：**索引本地截图，或礼貌地采集明确列出的公开页面；每项都保留来源路径/URL 和可哈希的溯源信息。
- **规范契约：**用带版本的 JSON 管理项目、令牌、流程、参考、决策、批准、界面和可复用组件。
- **质量门禁：**验证 ID、引用、绑定、交互、状态、无障碍、输入一致性、验收标准、流程和批准时效性。
- **AI 友好的线框图：**编写小型 `.uiwire` DSL，无需图形依赖即可渲染确定性的带注释 SVG。
- **单一源构建：**把契约编译为引擎中立 Design IR、Markdown、HTML 和渲染后的线框图。
- **可点击评审：**生成带界面导航、场景状态、键盘焦点和手柄轮询的静态原型。
- **引擎交接：**为 Unity UI Toolkit、Unity uGUI、Godot 和 Cocos 导出明确的脚手架及能力/哈希 manifest。
- **证据约束逆向分析：**为任意多模态模型准备截图/视频证据包，再验证其结论并只作为草稿导入。

## 5 分钟工作流

在游戏项目根目录运行下列命令。`--project-root`、`--design-root` 等全局选项应放在命令之前。

```bash
# 1. 创建轻量研究工作区。
ui-ref init --project-name "My Game"

# 2. 把截图放到 references/ui/<collection>/<category>/ 下并建立索引。
ui-ref scan-local

# 3. 创建 ui_design/；当前本地 manifest 会自动导入。
ui-ref spec init --project-name "My Game" --platform pc --locale zh

# 4. 添加界面草稿和起始线框图。
ui-ref spec add-screen "Main Menu" --id main-menu --wireframe

# 编辑 ui_design/screens/main-menu.json 和 ui_design/wireframes/main-menu.uiwire。
ui-ref spec validate --strict

# 5. 编译 IR + Markdown/HTML + SVG 线框图。
ui-ref spec build

# 6. 构建可点击静态原型。
ui-ref prototype build

# 7. 生成引擎交接脚手架。
ui-ref export unity-uitoolkit
```

在浏览器中打开 `ui_design/build/design-spec.html` 和 `ui_design/build/prototype/index.html`。生成命令不会在没有 `--force` 时替换非空的自定义输出目录；只有明确要刷新时才使用 `--force`。

后续参考资料变更时运行：

```bash
ui-ref scan-local
ui-ref spec import-references
ui-ref spec check
```

已有参考 ID 和人工备注会保留；消失的源文件会被标记为缺失，而不是静默删除。

## 规范源与生成结果

把 `ui_design/` 当作设计的源代码。

| 路径 | 作用 | 提交到版本库？ |
| --- | --- | --- |
| `ui_design/project.json` | 项目元数据、路径和质量门禁 | 是 |
| `ui_design/tokens.json`, `flows.json` | 共享设计令牌和导航流程 | 是 |
| `ui_design/references.json` | 证据目录及来源权利/备注 | 是 |
| `ui_design/decisions.json`, `approvals.json` | 决策和与哈希绑定的评审台账 | 是 |
| `ui_design/screens/*.json` | 规范界面契约 | 是 |
| `ui_design/components/*.json` | 规范可复用组件契约 | 是 |
| `ui_design/wireframes/*.uiwire` | 规范文本线框图 | 是 |
| `ui_design/schemas/` | 工作区契约 schema | 是 |
| `ui_design/build/` | 生成的 IR、报告、文档、SVG、原型和 export | 否；重新构建 |
| `ui_design/analysis/` | 临时帧、证据包、提示词和 contact sheet | 否；只把评审后的结果导入规范契约 |

仓库的 `.gitignore` 只忽略 `ui_design/build/` 和 `ui_design/analysis/`，**不会**忽略规范设计文件。

`ui-ref spec check` 会同时执行契约验证、批准检查、线框图 lint 和生成结果漂移检测。请编辑规范 JSON/`.uiwire`，不要编辑生成的 HTML、SVG、引擎文件或 Design IR。

## 生命周期与批准安全

界面和组件采用明确的生命周期：

```text
draft → reviewed → approved → deprecated
  ↑        │          │          │
  └────────┴──────────┴──────────┘  （需要修订时返回 draft）
```

状态提升不是简单修改字符串，而要通过质量门禁：

```bash
ui-ref spec promote screen main-menu \
  --to reviewed --by "UX reviewer" --note "已检查状态、输入和验收标准"

ui-ref spec promote screen main-menu \
  --to approved --by "Design lead" --note "批准进入实现" \
  --human-confirmed
```

- `reviewed` 和 `approved` 必须通过评审级完整性检查。
- 最终 `approved` 必须带 `--human-confirmed`；AI 或 import 不能授予最终批准。
- 批准台账同时保存产物和依赖的哈希。修改令牌、流程、参考或组件会使批准过期，重新评审前验证会失败。
- 验证会重新检查本地证据的存在性与 SHA-256、组件引用以及 `project.json` 中启用的全部质量门禁。创建/import 的 `--force` 只能替换从未评审过的草稿。
- `ui-ref spec trace screen main-menu` 展示证据、绑定、交互、批准和依赖的可追溯性。
- `ui-ref prototype build --release` 和 `ui-ref export <engine> --release` 会拒绝未批准或无效的发布输入。

批准标志不能替代真实评审。只有具名人员检查了该精确修订后，才应使用 `--human-confirmed`。

## 截图和视频逆向分析

分析工作流与提供商无关，它本身**不会**上传媒体或调用模型。

```bash
# 截图、目录或混合输入
ui-ref analyze media ./captures/menu.png ./captures/hud/

# 视频帧提取需要 PATH 中存在 ffmpeg
ui-ref analyze media ./captures/gameplay.mp4 --interval 2 --frame-limit 120
```

`ui_design/analysis/<timestamp>/` 运行目录包含：

- `analysis-packet.json` — 证据 ID、路径、SHA-256 哈希、尺寸和时间戳
- `analysis-prompt.md` — 证据规则和必需的结果形状
- `analysis-result.schema.json` — 结果契约
- `contact-sheet.html` — 本地评审页
- 输入视频时产生的提取帧

完全相同的文件/帧会按 SHA-256 去重。把证据包、提示词和被引用的图片交给你选择的多模态提供商，保存其 JSON 响应，然后导入：

```bash
ui-ref analyze import result.json \
  --packet ui_design/analysis/<timestamp>/analysis-packet.json
```

import 会验证证据 ID、`observed` / `inferred` / `unknown` 分类和置信度，并记录提供商/模型/提示词溯源，只创建或更新**草稿**界面契约。精确的数据包与证据哈希会绑定到抗冲突的参考 ID，参考、契约和线框图要么全部提交，要么完全不提交。即使使用 `--force`，已评审、已批准、已弃用或带有评审历史的草稿也会被保留。暂停规则、初始焦点、正式事件、失败处理等不可见运行时行为，在没有其他证据前必须保持 `unknown`。

## 线框图与构建输出

创建、检查并渲染逐行书写的 `.uiwire` 源：

```bash
ui-ref wireframe new main-menu
ui-ref wireframe lint ui_design/wireframes/main-menu.uiwire
ui-ref wireframe render ui_design/wireframes/main-menu.uiwire
```

源文件以版本和 canvas 开始，后跟稳定元素 ID 与 key/value 几何信息。label 和 callout 在输出 SVG 前会进行转义。

```text
uiwire 1
canvas 1920 1080
button A1 x=720 y=420 w=480 h=96 label="Start"
callout A1 side=right text="Primary action"
```

`ui-ref spec compile` 只写入引擎中立的 `design.ir.json`。`ui-ref spec build` 还会生成 `design-spec.md`、可读的 `design-spec.html`、带注释 SVG 线框图，以及包含源/输出哈希的 `build-manifest.json`。

## 原型与引擎交接

```bash
ui-ref prototype build
ui-ref export unity-uitoolkit
ui-ref export unity-ugui
ui-ref export godot
ui-ref export cocos
```

使用 `--screen <id>` 只导出一个界面，使用 `--release` 要求每个界面都有当前的人类批准。已编写的 `flows.json` 会驱动原型的入口与导航；同一动作存在冲突目标时验证会失败。每个引擎目录都包含 `engine-ir.json`、`capability-report.json` 和 `export-manifest.json`，每次导出会原子替换上一组生成文件，已移除界面不会残留。

这些是**实现交接脚手架，不是可直接投产的引擎项目**：

| 目标 | 生成内容 | 仍需人工/项目专用工作 |
| --- | --- | --- |
| Unity UI Toolkit | 每界面 UXML、`tokens.uss`、绑定/事件 JSON | 运行时绑定、项目资源、响应式调整、音频/触觉反馈 |
| Unity uGUI | RectTransform/组件交接 JSON | Unity 端 importer 和真正的 prefab 序列化 |
| Godot | 每界面 `Control` `.tscn`、绑定/事件 JSON | Theme 资源、资产、signal 和 GDScript |
| Cocos | 节点/组件/UITransform 交接 JSON | 版本专用 prefab 序列化和编辑器 adapter |

务必阅读 `capability-report.json`；它明确标出契约数据保留范围与人工/有损工作的边界。

## 安装与测试

```bash
git clone https://github.com/SillyToolValley/game-ux-ui-skill
cd game-ux-ui-skill
python -m pip install -e .
ui-ref --version
```

核心命令只使用 Python 3.10+ 标准库。若要处理 JavaScript 渲染的参考站点：

```bash
python -m pip install -e ".[browser]"
playwright install chromium
```

视频分析需要另外安装 FFmpeg，并确保 `ffmpeg` 位于 `PATH`。截图分析不需要它。

使用标准库运行回归测试：

```bash
python -m unittest discover -s tests -v
```

## 参考采集（旧工作流，继续支持）

原有 `init`、`scan-local`、`collect` 工作流保持兼容。采集刻意采用保守策略：

- 优先索引本地参考；
- 只获取用户**明确列出的**外部 URL，不做爬取；
- 未明确要求时不下载资产；
- 内置请求间隔、单次页面上限、`robots.txt` 检查、公共网络 URL 检查和响应大小限制。

需要登录的图库不在范围内。本工具是个人研究助手，不是通用爬虫，也不是重新分发他人资产的方式。请遵守站点条款、版权和 `robots.txt`。

### 索引本地参考

把文件放在 `references/ui/<collection>/<category>/` 下，然后运行：

```bash
ui-ref scan-local
```

它从 PNG/GIF/JPEG/WebP 字节中读取图片尺寸，根据文件夹路径推断粗粒度标签，并写入：

```text
ui_research/manifests/local_ui_refs_manifest.json
ui_research/manifests/local_ui_refs_manifest.md
```

### 采集明确列出的页面

在 `ui_research/urls.txt` 中每行放一个 URL，或重复使用 `--url`：

```bash
# JS 渲染站点：使用可选浏览器路径。
ui-ref collect --browser

# 下载少量图片并滚动以触发懒加载内容。
ui-ref collect --browser --scroll 6 \
  --download-gallery-assets --download-asset-limit 2

# 为未知站点强制指定提取行为。
ui-ref collect --browser --mode images
ui-ref collect --browser --gallery-class "thumb-card"
```

每次运行都会在 `ui_research/manifests/` 下写入 `collected_pages_<run_id>.json` 和可在浏览器查看的 `contact_sheet_<run_id>.html`。常用选项包括 `--site`、`--mode`、`--gallery-class`、`--scroll`、`--max-pages`、`--delay`、`--timeout`、`--keep-*`、`--download-full-images`、`--no-headless`。

### 支持的站点和模式

- `gallery`：读取结构化 gallery anchor 和元数据。
- `images`：采集渲染后的 `<img>`/`srcset` 候选，同时过滤明显的页面装饰。

| 站点键 | 域名 | 模式 | 说明 |
| --- | --- | --- | --- |
| `interfaceingame` | interfaceingame.com | images | 游戏 UI 截图。 |
| `screenlane` | screenlane.com | images | 移动 UI/UX 流程。 |
| `collectui` | collectui.com | images | 每日 UI 灵感。 |
| `landbook` | land-book.com | images | 落地页图库。 |
| `lapaninja` | lapa.ninja | images | 落地页示例。 |
| `refero` | refero.design | images | Web/iOS UI 灵感。 |
| `dribbble` | dribbble.com | images | 公开设计作品。 |
| `behance` | behance.net | images | 公开创意展示。 |

未知公开站点默认使用 `images`。要添加站点，在 `ui_ref_cli.py` 的 `SITE_PRESETS` 中加入 `match`、`mode`、可选的 `gallery_class` 和 `notes`；只有结构化元数据使用不同属性时才需扩展 `LinkExtractor`。

### 配置发现与采集礼仪

未提供 `--config` 时，CLI 按以下顺序搜索：

```text
ui_ref_config.json
ui_research/ui_ref_config.json
docs/ui_research/ui_ref_config.json
```

使用全局 `--project-root` 指定其他项目，使用 `--design-root` 覆盖 `ui_design`。采集应保持小规模、低频率；默认请求间隔为 8 秒，每次最多 20 页。把采集内容当作带引用的研究上下文，不要当作资产包或训练语料库。

## 用于 DOCX/PDF 和深度设计文档的配套技能

v0.4.0 核心构建会有意生成 JSON Design IR、Markdown、HTML、SVG 和静态原型文件，**不会**直接生成 DOCX 或 PDF。

仓库 checkout 中包含的 [`game-ux-ui-design` 配套技能](.claude/skills/game-ux-ui-design/) 增加长篇设计文档工作流：GDD 绑定、逐界面设计依据、密集图例/状态表、设计令牌、决策跟踪、美术概念 brief 和文档渲染。其模板包含 [`build_docx.py`](.claude/skills/game-ux-ui-design/templates/build_docx.py) 与 [`build_pdf.py`](.claude/skills/game-ux-ui-design/templates/build_pdf.py)。需要面向利益相关者的 DOCX/PDF 时使用该配套技能，同时保持规范 `ui_design` 契约作为机器可读的唯一事实来源。

Python wheel 只安装 `ui-ref` CLI，不会安装或注册此配套技能。需要配套工作流时，请 clone/download 本仓库，或将 `.claude/skills/game-ux-ui-design/` 复制到当前助手支持的技能目录。

## 仓库内可复现的完整示例

完整的公开配套技能示例位于 [`examples/lucid-dawn/`](examples/lucid-dawn/)：包含 12 个已记录界面、13 个带注释线框图、令牌、决策、引用，以及英语/中文/韩语/日语设计文档。

阅读完整示例：[英语](examples/lucid-dawn/lucid_dawn_ui_ux_design.en.md) · [中文](examples/lucid-dawn/lucid_dawn_ui_ux_design.zh.md) · [韩语](examples/lucid-dawn/lucid_dawn_ui_ux_design.ko.md) · [日语](examples/lucid-dawn/lucid_dawn_ui_ux_design.ja.md) · [PDF](examples/lucid-dawn/lucid_dawn_ui_ux_design.en.pdf)。

## 命令参考

| 命令 | 用途 |
| --- | --- |
| `ui-ref init` | 初始化参考研究和配置 |
| `ui-ref scan-local` | 索引本地参考媒体 |
| `ui-ref collect` | 获取明确列出的公开参考页面 |
| `ui-ref spec init` | 初始化规范契约工作区；`design` 是 `spec` 的别名 |
| `ui-ref spec add-screen` / `add-component` | 创建契约草稿 |
| `ui-ref spec import-references` | 把最新本地 manifest 同步到证据目录 |
| `ui-ref spec validate [--strict]` | 验证结构、语义、生命周期门禁和批准 |
| `ui-ref spec check [--strict]` | 验证 + 线框图 lint + 生成结果漂移检测 |
| `ui-ref spec compile` | 构建引擎中立 Design IR |
| `ui-ref spec build` | 构建 IR、Markdown、HTML、注释 SVG 和哈希 manifest |
| `ui-ref spec promote` | 执行带门禁的生命周期转换并记录台账 |
| `ui-ref spec trace` | 报告证据和依赖可追溯性 |
| `ui-ref wireframe new/lint/render` | 创建、验证并渲染 `.uiwire` |
| `ui-ref prototype build [--release]` | 构建可点击静态原型 |
| `ui-ref analyze media/import` | 准备证据包，并将验证后的 AI 结果作为草稿导入 |
| `ui-ref export <engine> [--screen ID] [--release]` | 生成引擎交接脚手架 |

使用 `ui-ref <command> --help` 查看全部选项。

## 许可证

MIT — 见 [LICENSE](LICENSE)。

项目文档：[变更记录](CHANGELOG.md) · [贡献指南](CONTRIBUTING.md) · [安全策略](SECURITY.md)
