import argparse
import sys
from pathlib import Path

import yaml

from autopublish.platforms import VideoInfo, get_platform

DEFAULT_CONFIG_PATHS = [
    Path("autopublish.yaml"),
    Path("autopublish.yml"),
    Path("config.yaml"),
    Path("config.yml"),
]

DEFAULT_CONFIG = {
    "credentials_dir": "~/.autopublish/credentials",
    "bilibili": {
        "human_type2": 1010,
        "tags": [],
        "copyright": 1,
        "limit": 3,
    },
    "douyin": {
        "tags": [],
        "headless": False,
        "channel": "chrome",
        "timeout": 120,
    },
    "youtube": {
        "client_secrets_file": "~/.autopublish/youtube_client_secret.json",
        "privacy_status": "public",
        "category_id": "27",
        "made_for_kids": False,
        "tags": [],
        "chunk_size": 8388608,
    },
}


def load_config(config_path: str | None = None) -> dict:
    """加载配置文件，如未指定则搜索默认路径"""
    if config_path:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(path, encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        return merge_config(DEFAULT_CONFIG, user_config)

    for path in DEFAULT_CONFIG_PATHS:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            return merge_config(DEFAULT_CONFIG, user_config)

    return dict(DEFAULT_CONFIG)


def merge_config(base: dict, override: dict) -> dict:
    """递归合并配置"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(
        prog="autopublish",
        description="自动发布视频到B站、抖音和 YouTube",
    )
    parser.add_argument(
        "-c", "--config",
        help="配置文件路径 (默认自动查找 autopublish.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # ── login ──
    login_parser = subparsers.add_parser("login", help="登录平台")
    login_parser.add_argument("platform", help="平台名称 (bilibili/douyin/youtube)")
    login_parser.add_argument(
        "--account",
        default="default",
        help="账号名称 (默认: default)",
    )

    # ── check ──
    check_parser = subparsers.add_parser("check", help="检查登录状态")
    check_parser.add_argument("platform", help="平台名称 (bilibili/douyin/youtube)")
    check_parser.add_argument(
        "--account",
        default="default",
        help="账号名称 (默认: default)",
    )

    # ── upload ──
    upload_parser = subparsers.add_parser("upload", help="上传视频")
    upload_parser.add_argument("platform", help="平台名称 (bilibili/douyin/youtube)")
    upload_parser.add_argument("video", nargs="?", help="视频文件路径")
    upload_parser.add_argument("--title", help="视频标题")
    upload_parser.add_argument("--desc", default="", help="视频简介")
    upload_parser.add_argument("--tags", help="标签，逗号分隔")
    upload_parser.add_argument("--human-type2", help="主区 (如 1010=知识区, 1026=健康)")
    upload_parser.add_argument("--cover", help="封面图片路径，抖音作为横版封面")
    upload_parser.add_argument("--cover43", help="B站4:3封面；抖音作为竖版封面")
    upload_parser.add_argument("--copyright", type=int, choices=[1, 2], help="1=自制 2=转载")
    upload_parser.add_argument("--source", default="", help="转载来源 (copyright=2 时填写)")
    upload_parser.add_argument("--season-id", type=int, help="合集ID")
    upload_parser.add_argument(
        "--privacy-status",
        choices=["public", "unlisted", "private"],
        help="YouTube 可见性",
    )
    upload_parser.add_argument("--category-id", help="YouTube 分类ID")
    made_for_kids_group = upload_parser.add_mutually_exclusive_group()
    made_for_kids_group.add_argument(
        "--made-for-kids",
        dest="made_for_kids",
        action="store_true",
        default=None,
        help="YouTube 声明为面向儿童",
    )
    made_for_kids_group.add_argument(
        "--not-made-for-kids",
        dest="made_for_kids",
        action="store_false",
        help="YouTube 声明为非面向儿童",
    )
    upload_parser.add_argument(
        "--scheduled-time",
        type=int,
        help="定时发布时间，10位时间戳",
    )
    upload_parser.add_argument(
        "--account",
        default="default",
        help="账号名称 (默认: default)",
    )

    # ── batch ──
    batch_parser = subparsers.add_parser("batch", help="批量上传 (从 YAML 任务文件)")
    batch_parser.add_argument("task_file", help="任务文件路径 (YAML)")
    batch_parser.add_argument(
        "--account",
        default="default",
        help="账号名称 (默认: default)",
    )

    # ── categories ──
    subparsers.add_parser("categories", help="列出B站可用主区")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = load_config(args.config)

    try:
        if args.command == "login":
            cmd_login(args, config)
        elif args.command == "check":
            cmd_check(args, config)
        elif args.command == "upload":
            cmd_upload(args, config)
        elif args.command == "batch":
            cmd_batch(args, config)
        elif args.command == "categories":
            cmd_categories()
    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_login(args, config: dict):
    platform = get_platform(args.platform, config)
    platform.login(account=args.account)


def cmd_check(args, config: dict):
    platform = get_platform(args.platform, config)
    valid = platform.check(account=args.account)
    sys.exit(0 if valid else 1)


def cmd_categories():
    from autopublish.platforms.bilibili import list_categories

    print("可用主区:")
    print(list_categories())


def cmd_upload(args, config: dict):
    if not args.video:
        print("错误: 请指定视频文件路径", file=sys.stderr)
        sys.exit(1)
    if not args.title:
        print("错误: 请指定视频标题 (--title)", file=sys.stderr)
        sys.exit(1)

    tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()] if args.tags else []
    video = VideoInfo(
        file_path=args.video,
        title=args.title,
        description=args.desc,
        tags=tags,
        cover_path=args.cover,
        cover43_path=args.cover43,
        human_type2=args.human_type2,
        copyright=args.copyright or 1,
        source=args.source,
        scheduled_time=args.scheduled_time,
        season_id=args.season_id,
        privacy_status=args.privacy_status,
        category_id=args.category_id,
        made_for_kids=args.made_for_kids,
    )

    platform = get_platform(args.platform, config)
    platform.upload(video, account=args.account)


def cmd_batch(args, config: dict):
    task_path = Path(args.task_file)
    if not task_path.exists():
        raise FileNotFoundError(f"任务文件不存在: {args.task_file}")

    with open(task_path, encoding="utf-8") as f:
        task_data = yaml.safe_load(f)

    tasks = task_data.get("tasks", [])
    if not tasks:
        print("任务文件中没有找到任务")
        return

    total = len(tasks)
    success = 0
    failed = 0

    for i, task in enumerate(tasks, 1):
        platform_name = task.get("platform", "bilibili")
        print(f"\n{'='*50}")
        print(f"任务 [{i}/{total}]: {task.get('title', '未命名')}")
        print(f"{'='*50}")

        video = VideoInfo(
            file_path=task["video"],
            title=task["title"],
            description=task.get("description", ""),
            tags=task.get("tags", []),
            cover_path=task.get("cover"),
            cover43_path=task.get("cover43"),
            human_type2=task.get("human_type2"),
            copyright=task.get("copyright", 1),
            source=task.get("source", ""),
            scheduled_time=task.get("scheduled_time"),
            dynamic=task.get("dynamic", ""),
            season_id=task.get("season_id"),
            privacy_status=task.get("privacy_status"),
            category_id=task.get("category_id"),
            made_for_kids=task.get("made_for_kids"),
        )

        account = task.get("account", args.account)

        try:
            platform = get_platform(platform_name, config)
            platform.upload(video, account=account)
            success += 1
        except Exception as e:
            print(f"任务失败: {e}", file=sys.stderr)
            failed += 1

    print(f"\n{'='*50}")
    print(f"批量上传完成: 成功 {success}, 失败 {failed}, 共 {total}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
