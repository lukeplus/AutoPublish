import random
import time
from datetime import datetime, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from autopublish.platforms import VideoInfo

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"
DEFAULT_PRIVACY_STATUS = "public"
DEFAULT_CATEGORY_ID = "27"
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
MAX_THUMBNAIL_SIZE = 2 * 1024 * 1024
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
VALID_PRIVACY_STATUSES = {"public", "unlisted", "private"}
SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".m4v",
    ".webm",
    ".flv",
    ".wmv",
}
SUPPORTED_THUMBNAIL_EXTENSIONS = {".jpg", ".jpeg", ".png"}


class YouTubePlatform:
    """YouTube Data API 自动发布。"""

    name = "youtube"

    def __init__(self, config: dict):
        platform_config = config.get("youtube", {})
        credentials_dir = config.get("credentials_dir", "~/.autopublish/credentials")
        self.credentials_dir = Path(credentials_dir).expanduser()
        self.client_secrets_file = Path(
            platform_config.get(
                "client_secrets_file",
                "~/.autopublish/youtube_client_secret.json",
            )
        ).expanduser()
        self.default_tags: list[str] = platform_config.get("tags", [])
        self.default_privacy_status = self._normalize_privacy_status(
            platform_config.get("privacy_status", DEFAULT_PRIVACY_STATUS)
        )
        self.default_category_id = str(
            platform_config.get("category_id", DEFAULT_CATEGORY_ID)
        )
        self.default_made_for_kids = bool(platform_config.get("made_for_kids", False))
        self.chunk_size = int(platform_config.get("chunk_size", DEFAULT_CHUNK_SIZE))
        if self.chunk_size <= 0:
            raise ValueError("youtube.chunk_size 必须大于 0")

    def _credential_path(self, account: str = "default") -> Path:
        return self.credentials_dir / f"youtube_{account}.json"

    def login(self, account: str = "default") -> None:
        if not self.client_secrets_file.exists():
            raise FileNotFoundError(
                f"YouTube OAuth client 文件不存在: {self.client_secrets_file}\n"
                "请在 autopublish.yaml 配置 youtube.client_secrets_file"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secrets_file),
            YOUTUBE_SCOPES,
        )
        credentials = flow.run_local_server(port=0)
        self._save_credentials(credentials, account)
        print(f"登录成功！凭证已保存至: {self._credential_path(account)}")

    def check(self, account: str = "default") -> bool:
        try:
            self._load_credentials(account)
            print("凭证有效")
            return True
        except Exception as exc:
            print(f"凭证检查失败: {exc}")
            return False

    def upload(self, video: VideoInfo, account: str = "default") -> dict:
        credentials = self._load_credentials(account)
        service = build(
            YOUTUBE_API_SERVICE_NAME,
            YOUTUBE_API_VERSION,
            credentials=credentials,
            cache_discovery=False,
        )

        video_path = self._validate_video_file(video.file_path)
        if not video.title:
            raise ValueError("视频标题不能为空")

        thumbnail_path = None
        if video.cover_path:
            thumbnail_path = self._validate_thumbnail_file(video.cover_path)

        body = self._build_video_resource(video)
        print(f"开始上传到 YouTube: {video.title}")
        print(f"  文件: {video_path}")
        print(f"  可见性: {body['status']['privacyStatus']}")
        print(f"  分类: {body['snippet']['categoryId']}")
        print(
            "  受众: "
            + ("面向儿童" if body["status"]["selfDeclaredMadeForKids"] else "非面向儿童")
        )
        if body["snippet"].get("tags"):
            print(f"  标签: {', '.join(body['snippet']['tags'])}")
        if body["status"].get("publishAt"):
            print(f"  定时发布: {body['status']['publishAt']}")

        media = MediaFileUpload(
            str(video_path),
            chunksize=self.chunk_size,
            resumable=True,
        )
        insert_request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        result = self._execute_resumable_upload(insert_request)
        video_id = result.get("id")
        if not video_id:
            raise RuntimeError(f"YouTube 上传成功但未返回 video id: {result}")

        thumbnail_error = None
        if thumbnail_path:
            try:
                self._set_thumbnail(service, video_id, thumbnail_path)
            except Exception as exc:
                thumbnail_error = str(exc)
                print(f"封面设置失败，视频已上传成功: {thumbnail_error}")

        print("上传成功！")
        return {
            "success": True,
            "result": result,
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "thumbnail_error": thumbnail_error,
        }

    def _save_credentials(self, credentials: Credentials, account: str) -> None:
        path = self._credential_path(account)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(credentials.to_json(), encoding="utf-8")
        path.chmod(0o600)

    def _load_credentials(self, account: str = "default") -> Credentials:
        path = self._credential_path(account)
        if not path.exists():
            raise RuntimeError(
                f"凭证文件不存在: {path}\n"
                f"请先登录: autopublish login youtube --account {account}"
            )

        credentials = Credentials.from_authorized_user_file(str(path), YOUTUBE_SCOPES)
        if (credentials.expired or not credentials.valid) and credentials.refresh_token:
            credentials.refresh(Request())
            self._save_credentials(credentials, account)
        if not credentials.valid:
            raise RuntimeError("YouTube 凭证无效或已过期，请重新登录")
        return credentials

    def _build_video_resource(self, video: VideoInfo) -> dict:
        privacy_status = self._normalize_privacy_status(
            video.privacy_status or self.default_privacy_status
        )
        status = {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": (
                self.default_made_for_kids
                if video.made_for_kids is None
                else bool(video.made_for_kids)
            ),
        }
        if video.scheduled_time:
            status["privacyStatus"] = "private"
            status["publishAt"] = self._to_rfc3339_utc(video.scheduled_time)

        tags = video.tags or self.default_tags
        snippet = {
            "title": video.title,
            "description": video.description or "",
            "categoryId": str(video.category_id or self.default_category_id),
        }
        if tags:
            snippet["tags"] = tags

        return {
            "snippet": snippet,
            "status": status,
        }

    def _execute_resumable_upload(self, request) -> dict:
        response = None
        error = None
        retry = 0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f"上传进度: {int(status.progress() * 100)}%")
            except HttpError as exc:
                if exc.resp.status not in RETRIABLE_STATUS_CODES:
                    raise RuntimeError(f"YouTube 上传失败: {exc}") from exc
                error = exc
            except OSError as exc:
                error = exc

            if error:
                retry += 1
                if retry > 5:
                    raise RuntimeError(f"YouTube 上传重试失败: {error}") from error
                sleep_seconds = random.uniform(0, 2**retry)
                print(f"上传遇到可重试错误，{sleep_seconds:.1f} 秒后重试...")
                time.sleep(sleep_seconds)
                error = None

        if not isinstance(response, dict):
            raise RuntimeError(f"YouTube 上传响应异常: {response}")
        return response

    def _set_thumbnail(self, service, video_id: str, thumbnail_path: Path) -> None:
        request = service.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path)),
        )
        request.execute()
        print("封面设置完成")

    def _normalize_privacy_status(self, value: str) -> str:
        privacy_status = str(value).strip().lower()
        if privacy_status not in VALID_PRIVACY_STATUSES:
            options = ", ".join(sorted(VALID_PRIVACY_STATUSES))
            raise ValueError(f"未知 YouTube 可见性: {value}，可选值: {options}")
        return privacy_status

    def _to_rfc3339_utc(self, timestamp: int) -> str:
        return (
            datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _validate_video_file(self, file_path: str) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"视频文件不存在: {path}")
        if not path.is_file():
            raise ValueError(f"视频路径不是文件: {path}")
        if path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            options = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
            raise ValueError(f"不支持的视频格式: {path.suffix}，当前支持: {options}")
        return path

    def _validate_thumbnail_file(self, file_path: str) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"封面图片不存在: {path}")
        if not path.is_file():
            raise ValueError(f"封面路径不是文件: {path}")
        if path.suffix.lower() not in SUPPORTED_THUMBNAIL_EXTENSIONS:
            options = ", ".join(sorted(SUPPORTED_THUMBNAIL_EXTENSIONS))
            raise ValueError(f"不支持的 YouTube 封面格式: {path.suffix}，当前支持: {options}")
        if path.stat().st_size > MAX_THUMBNAIL_SIZE:
            raise ValueError("YouTube 自定义封面不能超过 2MB")
        return path
