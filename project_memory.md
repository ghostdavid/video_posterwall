# 项目记忆

## 项目概况与现状

- 目标：把「一个视频 + 一张同名封面」组成的视频专辑，按用户划分的季与季内顺序整理成媒体中心可读的剧集结构，生成 `Season NN` 目录、单集 NFO / 各季 `season.nfo` / `tvshow.nfo`、专辑封面与每季封面；桌面界面可查看进度、季/条目信息与封面预览。
- 交付形态：Python 3.13 + PySide6 桌面程序，PyInstaller **onedir（目录版）** 打包为 `VideoPosterWall.exe`，面向 Windows 11 64 位；附 `.gitignore`、`README.md` 与构建脚本。
- 剧集名规则（用户要求）：取文件夹名第一对 `【】` 之间的文字，连续多个 `【` / `】` 视为装饰（`【【aa】】` → `aa`，`【bb】【cc】` → `bb`）；无括号时退化为整个文件夹名。
- **当前最终设计**：NFO 含 `<season>` / `<episode>`（用户实测去掉后部分平台识别不出）；用户设定季数、给每个视频划分所属季、在同季内上移/下移排序（同季第 k 个即第 k 集）；生成时创建 `Season 01…NN` 目录并把视频与配对封面移动到所属季目录。
- **季级元数据（用户要求，2026-11-15 调整）**：每个季目录写 `season.nfo`（根 `<season>`，含 `seasonnumber`、`title=第 N 季`、`seasonname=第 N 季`、`showtitle`、`sorttitle={剧集名} NN`、可选 `art/poster`）；季封面**全部放在季目录内**：`Season NN/seasonNN-poster.jpg`（用户要求的命名）+ `Season NN/poster.jpg`（Jellyfin / Emby `LocalImageProvider` 实际读取的季主图）。不再写专辑根 `seasonNN-poster.jpg`，旧版本残留会在生成时迁移/清理。
- 季封面来源：用户按季选择（选中季标题行后，在右侧「季封面设置」里从本季条目封面下拉选 / Windows 文件选择器自定义 / 清除）；未设置时默认取本季首个有封面的条目，已有季封面（季目录内两种命名或旧版根目录文件）则沿用。列表里不再显示季封面缩略图，预览与编辑都在右侧详情区域。
- **硬约束（用户明确强调）**：视频与配对封面**只移动、不改名、不修改内容、不覆盖已有文件**。`WriteGuard.move` 强制源与目标文件名相同、目标不存在、`Path.replace` 原子搬移（不读写字节）；`write_text`/`write_bytes`/`unlink` 白名单不含媒体路径。
- **默认递归扫描所选文件夹下所有子目录**，不再有扫描开关；扫描时排除程序管理的图片（专辑根 `poster.jpg`、季目录 `poster.jpg`、季目录/旧版根目录的 `seasonNN-poster.jpg`），避免误配成单集封面。
- 写盘分类白名单：`writable_files`（各 NFO、`tvshow.nfo`、专辑/季封面，以及扫描发现且真实存在的递归子目录单集原 NFO）、`allowed_dirs`（本次季数对应的 `Season NN`）、`media_paths`（媒体在根目录与各季目录的可能路径，用于双向移动与撤销）。递归原 NFO 必须按 `episode.existing_nfo_path` 加入白名单，保证清理、手动删除与撤销覆盖实际来源。
- 执行阶段顺序：创建季目录 → 写专辑/季封面 → 写 NFO → 清理原位置旧 NFO → 最后移动媒体。封面来源在移动前可读，季目录在写 NFO 前已存在。视频目标冲突时禁用对应单集 NFO 写入；目标 NFO 冲突或视频未移动时保留原 NFO，并在状态列说明，防止未成功生成目标元数据却清理唯一来源。
- 界面：表格有**季标题行**（独立成行、加粗底色、只读、无季下拉、无缩略图）+ 缩进的子视频行；「条目详情」与「NFO 预览」合并为单个**可视化字段表**（不展示 NFO 原始 XML）；已移除「生成计划」页与「预览计划」按钮，改为生成时「确认生成」+「二次确认：即将移动媒体文件」两个对话框。顶部设置使用紧凑网格；主区域用 `QSplitter`，宽窗口左右分栏、窄窗口自动上下分栏；表格列宽按空间分配、长文本省略并保留工具提示，详情区可滚动，封面随控件尺寸缩放。
- 交互：选择文件夹后自动扫描；「重新载入」只用于刷新；生成 / 撤销后自动刷新（`QTimer` 规避引擎忙碌竞态）；季下拉信号延后处理避免在信号中销毁控件。后台任务期间禁用季封面、季划分、勾选、线程与后端等会改变工作状态的控件，完成或取消后恢复，避免与刷新及执行结果竞争。
- 多线程用于扫描、信息解析、NFO 读写、移动，线程数可配置；GPU 只加速封面指纹，自动探测 CUDA 版 `torch` / `cupy`，未检测到回退 CPU；界面不提供基准测试按钮。
- **NFO 合并规则（用户确认，2026-11-15）**：以 `test/` 的 `tvshow.nfo`、`season.nfo`、`video.nfo` 为结构参考；已有且可解析的 XML 保留演员、简介、评分、外部 ID、远程图片和其它刮削字段，只更新本地可确定的信息。目标季目录 NFO 优先作为合并来源，否则使用视频原位置 NFO；`tvshow.nfo` 维护当前季的 `namedseason`，单集补充 `original_filename` 与 `fileinfo/streamdetails/video`。未知信息不虚构、不批量生成空节点；无效 XML 无法合并，按本地信息重建并保留当次撤销所需原始字节。
- **Jellyfin NFO/图片对齐（2026-11-15）**：按 Jellyfin 源码，`EpisodeNfoParser` 读 `<season>/<episode>/<showtitle>/<title>/<runtime>`；`SeasonNfoParser` 读 `<seasonnumber>/<seasonname>`；`Season` 的本地季主图只在季目录内查 `poster/folder/cover/default`，不读 `seasonNN-poster`；`EpisodeLocalImageProvider` 接受与视频同名的 jpg。NFO 的 `<thumb>` 只接受绝对 URI，因此不新增相对路径 `thumb`，已有远程 `thumb` 保留；本地专辑/季封面引用继续使用 `art/poster`。
- **必须如实说明的兼容性风险**：Kodi 官方文档规定季集号由**文件名**的 `S01E01` 解析。现在虽有季目录、season.nfo、季封面和 NFO 季集字段，但因用户要求不重命名，部分平台仍可能无法稳定识别或正确排序。已在 README 第 6 节写明并附依据，不得擅自改成重命名。Kodi 的季封面习惯是专辑根 `seasonNN-poster.jpg`，改到季目录后 Kodi 可能不显示季封面，这是用户明确要求的取舍。

## 资料与文件地图

- `launcher.py`：源码运行与打包入口；`app/main.py` 创建 Qt 应用，并从源码项目根目录或 onedir 的 `_MEIPASS` 资源目录加载 `assets/app.ico` 作为窗口图标；spec 同时把图标嵌入 exe 并复制到运行资源的 `assets/`。
- `app/models.py`：`Episode` 季/集/目标季目录/NFO 目标字段、`Action` 阶段与来源、`Album` 三类白名单集合与季 NFO/季封面状态、`UndoEntry` 自带守卫参数。
- `app/guard.py`：唯一写盘出口，目录边界 + 分类白名单 + 移动同名约束；无任意写媒体的能力。
- `app/constants.py`：`season_from_dir()`；`app/scanner.py`：递归扫描与配对、排除管理图片；`app/show_name.py`：剧集名解析。
- `app/media_info.py`：封面 `QImageReader`、视频纯内置文件头解析、`image_to_jpeg_bytes()` 内存转 JPEG。
- `app/nfo.py`：单集 / 季 / 剧集 NFO 合并生成与解析（保留已有刮削字段，不新增相对图片路径）；`app/planner.py`：季集计算、白名单构造、五阶段计划、相同内容跳过写入、`poster_bytes()` 与 `season_poster_source()`；季封面写 `Season NN/seasonNN-poster.jpg` + `Season NN/poster.jpg`。
- `app/engine.py`：后台线程池 + Qt 信号；生成、删除 NFO 统一走 `_run_actions` 与 `_apply`，停止时完整收集当前阶段再跳过后续阶段；撤销每条自带 root 与三类白名单，失败或中止的记录保留以便重试；扫描取消通过 `cancelled` 信号恢复 UI。
- `app/accel.py`：后端探测与 CPU/GPU 指纹计算；`app/ui/main_window.py`：主窗口、季标题行、季封面设置、可视化详情、二次确认；`app/ui/widgets.py`：省略文本、自适应封面预览与表格列宽控件。
- `video_posterwall.spec`、`build_exe.py`、`build_exe.bat`：onedir 打包；`requirements*.txt`：依赖；`README.md` 面向用户；`assets/app.ico`：图标。`test/` 保存本地 NFO 样例，`dist/` 保存构建输出，两者均加入 Git 忽略并在 spec 的模块排除列表中声明，不作为应用运行资源收集。

## 规则与限制

- 运行时禁止在专辑目录之外写盘，包括配置、日志、临时文件、`.pyc`；不得使用 `QSettings` 等会落盘的持久化机制。原因：用户明确要求，且 onedir 运行时不解压到系统临时目录。
- 媒体文件只能通过 `guard.move` 在预置路径间移动，且文件名不变、不覆盖；任何写入或删除媒体文件的企图都会被白名单拒绝。
- 撤销仅当次运行有效（内存记录），关闭程序即失效；README 与确认对话框应提示自行备份。撤销失败或中止时保留未完成记录，允许排除问题后重试，不得把未恢复的内容当作已撤销。
- 计划目标比较一律使用 `resolve()` 后的路径；未设置新封面来源时沿用已有封面并保留 NFO 的 `<art><poster>` 引用。
- 表格勾选与季下拉均使用单元格内嵌控件，并对底层控件已销毁的情况做容错；行映射 `_row_map` 区分季标题行与子视频行。每次刷新先 `setRowCount(0)` 清空旧行与旧 cell widget，杜绝季行残留季下拉/缩略图导致的行高列宽错乱；季行单元格 flags 只保留 Enabled｜Selectable；刷新后的勾选状态按条目对象身份恢复，避免调季或排序后勾选错位。
- 界面不暴露扫描子目录开关、输出模式、锁定元数据、覆盖 NFO、ffprobe 路径、CUDA 模块目录、基准测试、生成计划预览。
- 视频信息解析范围仅为内置 MP4 / Matroska / AVI 文件头；其他格式只给基础信息，不得虚报完整元数据，也不得重新引入外部程序依赖。
- 工作区盘符对构建进程只读时（共享文件夹映射常见），`build_exe.py` 提供 `--distpath` / `--workpath`；共享文件夹 UNC 路径无法进回收站，安全删除策略会拦截批量删除，因此构建改在本地临时目录完成后再覆盖写回，不关闭任何安全策略。
- 不主动运行用户未要求的测试或 exe 启动验证。用户明确要求完整交付审核时，必须分别完成全部源码静态检查、合成媒体核心回归、Qt 窗口实例化与布局检查、窗口图标非空检查、spec 资源及打包后图标加载检查、原生 exe 启动与窗口图标检查，并如实记录 Python 版本及验证范围；不能以 AST、依赖文件存在或构建成功替代运行验收。
- 第三方 Qt 枚举和控件构造须以实际运行 API 为准；图标必须完整核对 `assets/app.ico` → spec 的 exe 图标与 `datas` → `_MEIPASS` 资源定位 → `QApplication.setWindowIcon` → 原生窗口图标，不能只检查资源管理器中的 exe 图标。此规则源于此前滚动枚举和窗口图标两处遗漏，用户要求将审核经验长期保留。
- **当前交付版本的验证边界**：实际构建与回归使用 Python 3.12.16，而非项目目标 Python 3.13；已验收合成媒体核心与控件回归、原生源码入口完整生成/撤销、打包 exe 启动/窗口图标/正常退出，以及宽窄窗口截图。未验证真实 GPU、真实 MKV/AVI 样本和真实媒体库识别；打包 exe 未单独重复完整生成/撤销流程，不得把原生源码流程的通过结果扩大解释为这些场景均已验收。
