# 剧集海报墙生成器（VideoPosterWall）

把一个「很多视频 + 很多封面图」的视频专辑，按用户划分的**季**和**季内顺序**，整理成可供 Jellyfin / Emby / Kodi / 绿联影音中心等平台读取的剧集结构：建立 `Season NN` 目录、把视频与封面移动到所属季目录、生成 `tvshow.nfo`、每季的 `season.nfo` 与季封面、每集含 `<season>` / `<episode>` 的 NFO。

支持 Windows 11（64 位），桌面界面、进度显示、多线程与可选 GPU 加速。

> **硬约束**：视频与配对封面**只移动、不改名、不修改内容、不覆盖已有文件**。程序不会改写媒体文件的任何一个字节，也不会给它们换名字；除季目录外不创建其它目录。

---

## 1. 快速开始

1. 解压后保留**整个** `VideoPosterWall` 目录，双击 `VideoPosterWall.exe`。
   > 目录版 exe 依赖同目录下的 Qt 运行库，单独拷贝 `.exe` 无法运行。
2. 点击 **选择文件夹…**，用 Windows 文件夹选择器选中视频专辑目录；**选择后会自动递归扫描所有子目录**。
3. 在设置区设定 **季数**（默认 1 季）。
4. 表格中每一季有一条**季标题行**，其下的子视频行有缩进。在「季」列给每个视频分组；用 **上移 / 下移** 调整同一季内的顺序——同季排第一的就是该季第 1 集。
5. 选中**季标题行**：右侧详情会显示该季的元数据与季封面预览，并可用「季封面设置」选择本季某个条目的封面、自定义选图或清除。选中**子视频行**：右侧以可视化字段表展示该条目 NFO 信息与封面预览，不显示 NFO 源文件。
6. 需要整辑封面时，在设置区选中某行点 **用选中条目的封面**，或点 **自定义选图…**。
7. 点 **开始生成**，会依次弹出「确认生成」与「二次确认：即将移动媒体文件」两个对话框，确认后执行。完成后程序自动刷新列表。
8. 之后若添加了新文件，点 **重新载入** 刷新列表与数据（会保留内存中的季划分与排序）。

---

## 2. 文件夹命名与剧集名

剧集名取自**文件夹名中第一对 `【】` 之间的文字**：

| 文件夹名 | 剧集名 |
| --- | --- |
| `【我的剧集】1080P合集` | 我的剧集 |
| `【【aa】】` | aa |
| `【bb】【cc】` | bb |
| `没有括号的名字` | 没有括号的名字（退化为整个文件夹名） |

连续多个 `【` / `】` 视为装饰。找不到 `【】` 时使用整个文件夹名并给出提示。

---

## 3. 视频与封面图的识别规则

- 按**同名不同后缀**配对：`第01话.mp4` ↔ `第01话.jpg`，同目录、主文件名相同（不区分大小写）。
- **默认递归扫描所选文件夹下的所有子目录**，无需任何开关；隐藏目录会被跳过。
- 支持的常见视频格式：mp4 / mkv / m4v / mov / avi / wmv / flv / webm / ts / m2ts / mpg / mpeg / rmvb / rm / vob / 3gp / divx 等。
- 支持的常见图片格式：jpg / jpeg / png / webp / bmp / gif / tif / tiff / tbn / avif / heic 等。
- 同一主文件名有多个候选时按内置优先级挑选（jpg 优先于 png 等），其余在「状态」列标注。
- 缺少封面的视频仍会生成 NFO（不含封面引用）；没有对应视频的图片列为「孤立图片」并跳过。
- 程序自己管理的图片不会参与单集封面配对：专辑根 `poster.jpg`、季目录里的 `poster.jpg`、季目录里的 `seasonNN-poster.jpg`（以及旧版本留在根目录的同名文件）。
- 会识别已存在的 `Season NN` 目录并据此初始化季号，方便重复运行或继续整理。

---

## 4. 季、集与文件组织

### 4.1 界面上怎么划分

| 操作 | 效果 |
| --- | --- |
| 设置区 **季数** | 1 表示全部归第 1 季；设为 N 则创建 `Season 01` … `Season NN` 共 N 个目录 |
| 表格 **季标题行** | 每季独立成行，子视频行缩进显示；季行只读，只用于选中后在右侧设置季封面 |
| 子视频行的 **季** 下拉 | 把该视频划分到指定季；改变后自动插到目标季分组末尾。只有子视频行能改季 |
| **上移 / 下移** | 只在**同一季内**调整顺序；同季第 k 个即该季第 k 集 |
| **重新载入** | 重新递归扫描并按文件名保留当前的季划分与季内顺序 |

季数和排序只保存在内存中；因为**文件名始终不变**，重复载入仍能对应上。

### 4.2 生成后目录结构

设定 2 季、把 4 个视频分成「2 + 2」时：

```
【aa】我的视频专辑/
├── tvshow.nfo                    # 剧集名 + 可选总封面引用
├── poster.jpg                    # 整辑封面（仅当指定来源时）
├── Season 01/
│   ├── season.nfo                # 第 1 季元数据（seasonnumber / seasonname）
│   ├── season01-poster.jpg       # 第 1 季封面（本工具命名，放在季目录）
│   ├── poster.jpg                # 第 1 季封面（Jellyfin / Emby 实际读取的季主图）
│   ├── 第01话.mkv                # 原文件，仅移动，文件名与内容不变
│   ├── 第01话.jpg                # 同名封面，Jellyfin 自动识别为单集主图
│   ├── 第01话.nfo                # season=1 / episode=1
│   ├── 第03话.mkv
│   ├── 第03话.jpg
│   └── 第03话.nfo                # season=1 / episode=2
└── Season 02/
    ├── season.nfo
    ├── season02-poster.jpg
    ├── poster.jpg
    ├── 第02话.mkv
    ├── 第02话.jpg
    ├── 第02话.nfo                # season=2 / episode=1
    ├── 第04话.mkv
    ├── 第04话.jpg
    └── 第04话.nfo                # season=2 / episode=2
```

季封面全部放在季目录内，专辑根目录不再写 `seasonNN-poster.jpg`。每个季目录写两份是同名的内容：

- `seasonNN-poster.jpg` 是用户要求的季封面命名，便于人工识别和其他刮削工具使用；
- `poster.jpg` 是 Jellyfin / Emby 在季目录内实际读取的季主图文件名（Jellyfin `LocalImageProvider` 对 Season 只查 `poster/folder/cover/default`，不查 `seasonNN-poster`）。

这样既满足「季封面放在季目录、命名为 season03-poster」的要求，又不会让 Jellyfin 丢季封面。旧版本曾写在专辑根目录的 `seasonNN-poster.jpg` 会在生成时清理（迁移到季目录），撤销可恢复。

生成顺序为：**创建季目录 → 写专辑封面与季封面 → 写 NFO → 清理原位置的旧 NFO → 最后移动媒体**，保证封面来源在移动前仍可读、季目录在写 NFO 前已存在。若视频已经在目标季目录，则不会重复移动，只更新 NFO。

### 4.3 season.nfo 与单集 NFO

`Season 01/season.nfo`（由已知信息生成，不含 `lockdata`）：

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<season>
  <seasonnumber>1</seasonnumber>
  <title>第 1 季</title>
  <seasonname>第 1 季</seasonname>
  <showtitle>aa</showtitle>
  <sorttitle>aa 01</sorttitle>
  <art>
    <poster>poster.jpg</poster>
  </art>
</season>
```

`tvshow.nfo` 还会按当前季数维护 `<namedseason number="N">第 N 季</namedseason>`；已有的特别篇（第 0 季）节点保留。

`Season 01/第01话.nfo`（假设已解析到 24 分钟时长）：

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<episodedetails>
  <title>第01话</title>
  <showtitle>aa</showtitle>
  <season>1</season>
  <episode>1</episode>
  <runtime>24</runtime>
  <original_filename>第01话.mkv</original_filename>
  <fileinfo>
    <streamdetails>
      <video>
        <durationinseconds>1440</durationinseconds>
      </video>
    </streamdetails>
  </fileinfo>
</episodedetails>
```

`<title>` 始终是原始视频文件名；`<season>` / `<episode>` 来自界面上的季划分与季内排序。按 `test/` 中的三类样例，单集 NFO 还会写入 `original_filename`，并把本地可确定的编码、宽高、宽高比、分辨率和秒数写入 `fileinfo/streamdetails/video`；无法确定的字段不虚构，也不批量生成空节点。

**已有 NFO 采用合并更新**：演员、简介、评分、外部 ID、远程图片及其它刮削字段均保留，只更新本地可确定的字段。目标季目录已有 NFO 时优先合并它，否则合并视频原位置的 NFO。无法解析的 XML 会按本地信息重建，原始文件内容仍保存在当次运行的撤销记录中。

**为什么新单集 NFO 不写相对 `<thumb>`**：Jellyfin 的 NFO 图片解析（`BaseNfoParser.FetchThumbNode`）只接受绝对 URI，相对文件名会被判为无效并写错误日志；而 Jellyfin 的 `EpisodeLocalImageProvider` 会把与视频同名的 `第01话.jpg` 直接识别为单集主图。已有的远程 `thumb` 会保留，本地封面仍由同名图和 `art/poster` 提供。

### 4.4 季封面怎么设置

选中表格里的**季标题行**后，右侧「季封面设置」可用：

| 操作 | 效果 |
| --- | --- |
| 下拉框选择本季某个条目 → **用所选条目的封面** | 用该条目的同名封面图作为这一季的封面 |
| **自定义选图…** | 弹出 Windows 文件选择器，任选一张本地图片 |
| **清除季封面** | 生成时删除该季目录内的 `seasonNN-poster.jpg` 与 `poster.jpg`，`season.nfo` 也不再引用 |

若未手动设置，默认取**本季第一个有封面的条目**作为季封面，保证每季都有封面；已存在的季封面会被沿用。季封面预览只在**右侧详情面板**显示，列表里不再放缩略图（避免行高/列宽错乱）。来源固定转成 JPEG；如果来源本身就是 `.jpg`，直接复制字节不做二次编码。移动媒体后封面来源会按文件名自动跟随到新路径。

---

## 5. 删除指定条目的 NFO

1. 勾选子视频行**第一列**的复选框（可用「全选」/「清空选择」）。
2. 点击 **删除所选 NFO**；会同时检查条目原位置和目标季目录里的同名 NFO。
3. 确认后仅删除这些 `.nfo`；视频、封面、季封面、`tvshow.nfo` 都不受影响。
4. 删除前的内容保存在内存，可用 **撤销本次操作** 恢复。

---

## 6. 平台兼容性

NFO 含 `<season>` / `<episode>`，并有 `Season NN` 目录、`season.nfo` 和季封面，比纯原地方案更容易被平台把多个季识别成同一个剧集。

**Jellyfin 的 NFO/图片读取规则（本次按源码对齐）**：

- `EpisodeNfoParser` 会读单集 NFO 的 `<season>`、`<episode>`、`<showtitle>`、`<title>`、`<runtime>`；这些字段已写入。
- `SeasonNfoParser` 会读 `<seasonnumber>` 与 `<seasonname>`；`<title>` 作为兜底，`<sorttitle>` 用零填充季号（`aa 01`）避免第 10 季排到第 2 季前。
- 季封面：`LocalImageProvider` 对 Season 只在**季目录**内查 `poster/folder/cover/default`，不查 `seasonNN-poster`；所以季目录内必须保留 `poster.jpg`。`seasonNN-poster.jpg` 仍按你的要求写在季目录内，但 Jellyfin 不会读它。
- 单集封面：`EpisodeLocalImageProvider` 会把**与视频同名**的 `第01话.jpg` 直接识别为主图；因此单集 NFO 不再写相对 `<thumb>`（Jellyfin 的 NFO 图片解析只接受绝对 URI，相对文件名会写错误日志）。
- 专辑封面：`poster.jpg` 放在专辑根目录。

**仍需如实说明一个限制**：Kodi 官方 NFO 文档明确写着「单集必须遵守标准命名约定；Kodi 从**文件名**中的 `S01E01` 判断季号和集号，而不是从 NFO 读取」，Jellyfin / Emby 也以文件名与 `Season NN` 目录为主要依据。由于本程序按你的要求**不重命名**媒体文件，部分平台可能仍无法把它们稳定编排成剧集列表，或排序不符合预期。请以实际扫描结果为准。另外，Kodi 的季封面习惯是专辑根目录的 `seasonNN-poster.jpg`；本工具按你的要求改到季目录内，Kodi 可能不显示季封面，Jellyfin / Emby 不受影响。

| 平台 | 建议设置 |
| --- | --- |
| Jellyfin | 媒体库类型选「节目 / 剧集」；本地 NFO 优先于在线元数据；刷新媒体库 |
| Emby | 媒体库 → 编辑 → 元数据读取器启用 **Nfo** 并排到前面 |
| Kodi | 视频源使用「本地信息 / NFO」刮削器 |
| 绿联影音中心 / 海报墙 | 「偏好设置 → NFO 解析默认选项」选**本地优先**，再重新扫描 |

官方参考：

- Jellyfin 本地 NFO 文档：<https://jellyfin.org/docs/general/server/metadata/nfo/>
- Jellyfin 剧集目录规范：<https://jellyfin.org/docs/general/server/media/shows/>
- Kodi 单集 NFO 文档：<https://kodi.wiki/view/NFO_files/Episodes>
- Kodi 剧集封面命名：<https://kodi.wiki/view/TV-Show_artwork>

---

## 7. 界面能看什么

| 区域 | 内容 |
| --- | --- |
| 条目表格 | 季标题行（只读，无季下拉、无缩略图）+ 缩进的子视频行；勾选框、季下拉、集号、视频/封面/NFO 信息、状态 |
| 详情（合并页） | 上方是封面预览，下方是「字段 / 值」表格，把 NFO 信息以可视化方式展示（标题、所属剧集、季、集、时长、封面、NFO 路径、已有 NFO 字段等），**不显示 NFO 原始 XML** |
| 季封面设置 | 选中季标题行时在右侧详情上方显示，可选择本季条目的封面、自定义选图或清除，并预览；列表里不再显示季封面缩略图 |
| 运行日志 | 全部运行信息，仅显示在界面中 |
| 进度条 | 扫描 / 写盘 / 删除 / 撤销的实时进度 |

界面采用自适应布局：顶部设置按网格排列；宽窗口中列表与详情左右分栏，窄窗口自动改为上下分栏，分隔条仍可拖动。表格列宽随可用空间分配，空间不足时提供横向滚动，省略文本的完整内容可通过工具提示查看；详情区可滚动，封面预览随控件尺寸缩放。

界面不再提供「生成计划」页与「预览计划」按钮；写盘前由「确认生成」+「二次确认」两个对话框给出动作数量与警告。

---

## 8. 设置项

| 设置 | 说明 |
| --- | --- |
| 工作线程 | 扫描、信息解析、NFO 读写、移动使用线程池并发，范围 1 ~ CPU 逻辑核数 × 2 |
| 加速后端 | 自动（优先 GPU）/ CPU 多线程 / 已检测到的 CUDA 后端，自动探测、无需指定路径 |
| 检测 GPU | 探测本机 CUDA 运行时（选择文件夹自动扫描时也会探测一次） |
| 季数 | 1 ~ 99；决定创建多少个 `Season NN` 目录 |
| 季列 / 上移 / 下移 | 划分每个视频所属季、调整季内顺序，决定 `<season>` / `<episode>` |
| 专辑封面 | 用选中条目的封面 / 自定义选图… / 清除封面 |
| 季封面 | 选中季标题行后按季设置，见 4.4 |

界面**不提供**：扫描子目录开关（默认递归）、输出模式、锁定本地元数据、覆盖 NFO、`ffprobe` 路径、CUDA 模块目录、基准测试、生成计划预览。

---

## 9. 写盘边界（重要）

所有写操作都经过统一的 `WriteGuard`，带分类白名单：

| 允许的操作 | 约束 |
| --- | --- |
| 创建 `Season NN` 目录 | 只创建本次设定季数对应的目录，且只在专辑根目录内 |
| 移动视频与配对封面 | 源与目标文件名**必须完全相同**（禁止重命名）；目标不存在（禁止覆盖）；用 `Path.replace` 原子搬移，**不读取也不改写字节** |
| 生成 / 修改 / 删除 NFO | 与各视频同名的 `.nfo`、各季 `season.nfo`、专辑根 `tvshow.nfo` |
| 生成 / 修改 / 删除封面 | 专辑根 `poster.jpg`、各季目录 `poster.jpg` 与 `seasonNN-poster.jpg`；不再写专辑根 `seasonNN-poster.jpg` |

此外还有目录边界校验（含符号链接绕出检测）：任何目标解析后都必须位于所选专辑文件夹内。`write_text` / `write_bytes` / `unlink` 只能作用于上述 NFO 与封面白名单，**媒体文件在这些接口中根本不在允许清单里**，因此不可能被写入或覆盖。

若视频目标位置已有同名文件，程序会跳过该视频移动，同时不更新该集目标 NFO、不清理原位置 NFO，并在状态列说明原因；目标 NFO 写入冲突时同样保留未合并的原 NFO，避免生成指向错误位置的元数据或删除唯一来源。

其它约束：

- **不写任何其他目录**：没有配置、日志、临时文件、缩略图缓存、图片缓存，也没有 `.pyc` 字节码（启动时已关闭）；扫描结果、JPEG 字节、NFO 文本、撤销所需的原始字节全部只在内存。
- NFO 或封面目标内容与本次生成结果完全相同时跳过写入，避免无意义的覆盖与撤销记录。
- 采用 **onedir（目录版）** 打包，运行时不会像 onefile 那样把依赖解压到系统临时目录。
- 撤销记录只在内存：关闭程序后无法再撤销，操作前请自行备份。撤销失败或因中止而未处理的记录会保留，可在排除问题后重试。

---

## 10. 多线程与 GPU 加速说明

- **多线程**：扫描、视频/封面信息读取、NFO 写入与删除、媒体移动都在可配置大小的线程池中并发执行；写盘动作按阶段顺序推进，阶段内并发。停止写盘时会完整收集当前阶段的结果，再跳过后续阶段，确保已发生的改动都有撤销记录。
- **GPU 加速**：用于批量计算封面图指纹（64 位 dHash，可发现重复封面），把整批 9×8 灰度矩阵一次性上传显存做位比较；支持 `torch.cuda` 与 `cupy` 两种 CUDA 后端。
- GPU 是**可选能力且无需配置**：程序自动探测本机 CUDA 运行时（只读检查常见 Python 环境目录）；打包产物不内置 CUDA 运行时，未检测到或加载失败时回退 CPU 多线程，不影响任何功能。
- 如实说明：本工具主要瓶颈是**磁盘 I/O 与文件移动**，GPU 只加速封面指纹这一小段计算，提速有限。界面不提供基准测试按钮。

---

## 11. 从源码运行与重新打包

需要 Python 3.13（64 位）与 Windows 11。

```bat
python -m pip install -r requirements-build.txt -i https://mirrors.aliyun.com/pypi/simple/
python launcher.py
build_exe.bat
```

打包产物为 `dist/VideoPosterWall/`，入口 `VideoPosterWall.exe`。`build_exe.py` 支持参数：

```bat
python build_exe.py --clean
python build_exe.py --distpath D:/out/dist --workpath D:/out/build
```

若工作区盘符对构建进程只读（例如共享文件夹映射），用 `--distpath` / `--workpath` 指向可写路径即可。

---

## 12. 已知限制

- 因不重命名媒体文件，部分平台仍可能无法把专辑识别为剧集列表或正确排序，详见第 6 节。
- 若目标季目录已存在同名文件，该移动动作会跳过并在计划中标注，不会覆盖。
- 季划分、季内排序、季封面选择只保存在内存，关闭程序后丢失；重新载入会按文件名尽量保留季与顺序。
- 已有 NFO 会被更新；需要保留旧文件请自行备份，或用「撤销本次操作」恢复。
- 不访问网络、不刮削在线元数据、不下载图片；所有信息都来自本地文件。
- 视频时长/分辨率来自内置文件头解析（MP4 / Matroska / AVI），其他封装格式只显示基础信息。
- 程序不写日志到磁盘，关闭窗口后运行日志与撤销记录即消失。

---

## 13. 项目文件

```
launcher.py               源码 / 打包入口
app/                      核心逻辑与界面
  main.py                 应用入口
  constants.py            扩展名、季目录解析、线程默认值
  models.py               内存数据模型、季/集字段、白名单集合
  show_name.py            剧集名解析
  guard.py                唯一写盘出口：目录边界 + 分类白名单 + 移动同名约束
  scanner.py              递归扫描与配对（排除程序管理的封面）
  media_info.py           视频/封面只读探测 + 内存 JPEG 转换
  accel.py                CPU / GPU 加速后端与封面指纹
  nfo.py                  单集 / 季 / 剧集 NFO 合并生成与解析
  planner.py              季集计算、白名单构造、五阶段写盘计划
  engine.py               多线程任务编排、删除、可重试撤销
  ui/main_window.py       主窗口、季标题行、季封面设置、可视化详情
  ui/widgets.py           省略文本、自适应封面预览与表格列宽控件
video_posterwall.spec     PyInstaller onedir 配置
build_exe.py / .bat       构建脚本
requirements*.txt         依赖
assets/app.ico            应用图标
README.md                 本文档
```
