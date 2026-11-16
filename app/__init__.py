"""剧集海报墙生成器。

把「一个视频 + 一张同名封面」组成的视频专辑，按季整理成 Jellyfin / Emby /
Kodi / 绿联影音中心等媒体中心可读取的剧集结构与 NFO 元数据；
视频和图片原文件只移动到季目录，不改名、不改内容。
"""

from .constants import APP_VERSION

__version__ = APP_VERSION
