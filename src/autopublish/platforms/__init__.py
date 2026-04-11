from dataclasses import dataclass, field


@dataclass
class VideoInfo:
    """视频上传信息"""

    file_path: str
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    cover_path: str | None = None
    cover43_path: str | None = None
    human_type2: int | str | None = None
    copyright: int = 1
    source: str = ""
    scheduled_time: int | None = None
    dynamic: str = ""
    season_id: int | None = None


from autopublish.platforms.bilibili import BilibiliPlatform
from autopublish.platforms.douyin import DouyinPlatform

PLATFORMS: dict[str, type] = {
    "bilibili": BilibiliPlatform,
    "douyin": DouyinPlatform,
}


def get_platform(name: str, config: dict):
    """根据名称获取平台实例"""
    cls = PLATFORMS.get(name)
    if cls is None:
        raise ValueError(f"不支持的平台: {name}，可用平台: {', '.join(PLATFORMS)}")
    return cls(config)
