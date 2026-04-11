import asyncio
import base64
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from autopublish.platforms import VideoInfo

DEFAULT_SUBMIT_TID = 21

HUMAN_TYPE2_CATEGORIES: dict[str, int] = {
    "知识区": 1010,
    "知识": 1010,
    "健康": 1026,
    "健康区": 1026,
}

HUMAN_TYPE2_NAMES: dict[int, str] = {
    1010: "知识区",
    1026: "健康",
}

LEGACY_TID_TO_HUMAN_TYPE2: dict[int, int] = {
    21: 1010,
    36: 1010,
    122: 1010,
    188: 1010,
    228: 1010,
}

LEGACY_CATEGORY_NAMES: dict[str, int] = {
    "日常": 1010,
    "知识分享": 1010,
    "野生技术协会": 1010,
    "科普人文": 1010,
    "人文历史": 1010,
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)

UPLOAD_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bilibili.com",
}

MEMBER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Origin": "https://member.bilibili.com",
    "Referer": "https://member.bilibili.com/platform/upload/video/frame",
}

PASSPORT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": "https://www.bilibili.com/",
}

BILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILI_QRCODE_GENERATE_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
)
BILI_QRCODE_POLL_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
)
PREUPLOAD_URL = "https://member.bilibili.com/preupload"
COVER_UPLOAD_URL = "https://member.bilibili.com/x/vu/web/cover/up"
SUBMIT_URL = "https://member.bilibili.com/x/vu/web/add/v3"
SEASONS_URL = "https://member.bilibili.com/x2/creative/web/seasons"
SEASON_ADD_URL = "https://member.bilibili.com/x2/creative/web/season/section/episodes/add"
SEASONS_PAGE_SIZE = 20
SEASON_DUPLICATE_CODES = {20080}

UPLOAD_LINES = {
    "bda2": {"os": "upos", "upcdn": "bda2", "probe_version": 20221109},
    "qn": {"os": "upos", "upcdn": "qn", "probe_version": 20221109},
    "ws": {"os": "upos", "upcdn": "ws", "probe_version": 20221109},
}


class BilibiliCredential:
    def __init__(self, cookies: dict[str, str]):
        self.cookies = {key: value for key, value in cookies.items() if value}
        self.bili_jct = self.cookies.get("bili_jct", "")

    async def get_buvid_cookies(self) -> dict[str, str]:
        if self.cookies.get("buvid3") and self.cookies.get("buvid4"):
            return dict(self.cookies)

        async with httpx.AsyncClient(
            headers=UPLOAD_HEADERS,
            cookies=self.cookies,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            await client.get("https://www.bilibili.com")
            self.cookies.update(dict(client.cookies))
            self.bili_jct = self.cookies.get("bili_jct", self.bili_jct)
            return dict(self.cookies)


def resolve_human_type2(value: str | int | None) -> int | None:
    """解析 human_type2 主区。"""
    if value is None:
        return None

    if isinstance(value, int):
        if value in HUMAN_TYPE2_NAMES:
            return value
        if value in LEGACY_TID_TO_HUMAN_TYPE2:
            return LEGACY_TID_TO_HUMAN_TYPE2[value]
        raise ValueError(
            f"未知 human_type2: {value}，可用值: 1010(知识区), 1026(健康)"
        )

    text = str(value).strip()
    try:
        numeric = int(text)
        return resolve_human_type2(numeric)
    except ValueError:
        pass

    if text in HUMAN_TYPE2_CATEGORIES:
        return HUMAN_TYPE2_CATEGORIES[text]

    if text in LEGACY_CATEGORY_NAMES:
        return LEGACY_CATEGORY_NAMES[text]

    matches = [name for name in HUMAN_TYPE2_CATEGORIES if text in name]
    if len(matches) == 1:
        return HUMAN_TYPE2_CATEGORIES[matches[0]]
    if len(matches) > 1:
        options = ", ".join(
            f"{name}({HUMAN_TYPE2_CATEGORIES[name]})"
            for name in matches
        )
        raise ValueError(
            f"human_type2 名称 \"{text}\" 匹配到多个结果: {options}，请更精确"
        )

    raise ValueError(
        f"未知 human_type2: \"{text}\"\n"
        f"可用值: 1010(知识区), 1026(健康)"
    )


def get_human_type2_name(value: int) -> str:
    return HUMAN_TYPE2_NAMES.get(value, str(value))


def list_categories() -> str:
    """返回格式化的主区列表"""
    lines = [f"  {code:>4}  {name}" for code, name in HUMAN_TYPE2_NAMES.items()]
    return "\n".join(lines)


class BilibiliPlatform:
    """B站上传，登录和上传链路均为自实现"""

    name = "bilibili"

    def __init__(self, config: dict):
        platform_config = config.get("bilibili", {})
        self.submit_tid: int = DEFAULT_SUBMIT_TID
        self.default_human_type2: int = resolve_human_type2(
            platform_config.get("human_type2", 1010)
        ) or 1010
        self.default_tags: list[str] = platform_config.get("tags", [])
        self.default_copyright: int = platform_config.get("copyright", 1)
        self.line = platform_config.get("line")
        self.chunk_concurrency: int = platform_config.get("limit", 3)
        credentials_dir = config.get("credentials_dir", "~/.autopublish/credentials")
        self.credentials_dir = Path(credentials_dir).expanduser()

    def _credential_path(self, account: str = "default") -> Path:
        return self.credentials_dir / f"bilibili_{account}.json"

    def _save_credential(
        self,
        cookies: dict[str, str],
        account: str = "default",
    ) -> None:
        path = self._credential_path(account)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: value for key, value in cookies.items() if value}
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _load_credential(self, account: str = "default") -> BilibiliCredential:
        path = self._credential_path(account)
        if not path.exists():
            raise RuntimeError(
                f"凭证文件不存在: {path}\n"
                f"请先登录: autopublish login bilibili --account {account}"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return BilibiliCredential(self._normalize_saved_cookies(data))

    async def _login_async(self, account: str = "default") -> None:
        """扫码登录B站"""
        async with httpx.AsyncClient(
            headers=PASSPORT_HEADERS,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            qrcode_data = await self._generate_login_qrcode(client)
            self._show_login_qrcode(qrcode_data["url"])
            cookies = await self._poll_login_qrcode(
                client,
                qrcode_data["qrcode_key"],
            )

        if not cookies.get("SESSDATA") or not cookies.get("bili_jct"):
            raise RuntimeError("登录成功但未获取到完整 B站 cookie，请重试")

        self._save_credential(cookies, account)
        print(f"\n登录成功！凭证已保存至: {self._credential_path(account)}")

    def login(self, account: str = "default") -> None:
        asyncio.run(self._login_async(account))

    def check(self, account: str = "default") -> bool:
        """检查登录凭证是否有效"""
        try:
            credential = self._load_credential(account)
            valid = asyncio.run(self._check_credential(credential))
            if valid:
                print("凭证有效")
                return True
            print("凭证无效或已过期，请重新登录")
            return False
        except Exception as e:
            print(f"凭证检查失败: {e}")
            return False

    async def _check_credential(self, credential: BilibiliCredential) -> bool:
        async with httpx.AsyncClient(
            headers=PASSPORT_HEADERS,
            cookies=credential.cookies,
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            response = await client.get(BILI_NAV_URL)
        response.raise_for_status()
        data = response.json()
        return data.get("code") == 0 and bool((data.get("data") or {}).get("isLogin"))

    async def _generate_login_qrcode(self, client: httpx.AsyncClient) -> dict:
        response = await client.get(BILI_QRCODE_GENERATE_URL)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            message = payload.get("message") or payload.get("msg") or "请求失败"
            raise RuntimeError(f"获取 B站登录二维码失败: {message}")

        data = payload.get("data") or {}
        if not data.get("url") or not data.get("qrcode_key"):
            raise RuntimeError("获取 B站登录二维码失败: 接口返回数据不完整")
        return data

    async def _poll_login_qrcode(
        self,
        client: httpx.AsyncClient,
        qrcode_key: str,
    ) -> dict[str, str]:
        last_code = None
        for _ in range(180):
            response = await client.get(
                BILI_QRCODE_POLL_URL,
                params={"qrcode_key": qrcode_key},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            code = data.get("code")
            if code != last_code:
                if code == 86101:
                    print("等待扫码...")
                elif code == 86090:
                    print("已扫码，请在手机上确认...")
                elif code == 86038:
                    raise RuntimeError("二维码已过期，请重新登录")
                elif code == 0:
                    print("已确认，正在保存凭证...")
                else:
                    message = data.get("message") or payload.get("message") or code
                    print(f"扫码状态: {message}")
                last_code = code

            if code == 0:
                cookies = dict(client.cookies)
                cookies.update(dict(response.cookies))
                cookies.update(self._cookies_from_login_url(data.get("url") or ""))
                return self._normalize_saved_cookies(cookies)

            await asyncio.sleep(2)

        raise RuntimeError("等待 B站扫码登录超时")

    def _show_login_qrcode(self, qrcode_url: str) -> None:
        print("请使用B站APP扫描二维码登录:\n")
        try:
            import qrcode
        except ImportError:
            print(qrcode_url)
            print("\n未安装 qrcode，无法生成终端二维码。")
            print("请安装依赖后重试: pip install -e .")
            return

        qr = qrcode.QRCode(border=1)
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        self._print_terminal_qrcode(qr.get_matrix())

        qr_path = Path("qrcode.png")
        image = qr.make_image(fill_color="black", back_color="white")
        image.save(qr_path)
        print(f"\n如果终端二维码无法识别，请打开 {qr_path.resolve()} 扫码\n")

    def _print_terminal_qrcode(self, matrix: list[list[bool]]) -> None:
        for row in matrix:
            print("".join("██" if cell else "  " for cell in row))

    def _normalize_saved_cookies(self, data: dict) -> dict[str, str]:
        cookie_aliases = {
            "sessdata": "SESSDATA",
            "dedeuserid": "DedeUserID",
            "bili_jct": "bili_jct",
            "buvid3": "buvid3",
            "buvid4": "buvid4",
            "ac_time_value": "ac_time_value",
        }
        cookies: dict[str, str] = {}
        for key, value in data.items():
            normalized_key = cookie_aliases.get(key, key)
            if value:
                cookies[normalized_key] = str(value)
        return cookies

    def _cookies_from_login_url(self, login_url: str) -> dict[str, str]:
        if not login_url:
            return {}

        query = parse_qs(urlparse(login_url).query)
        cookie_names = {
            "DedeUserID",
            "DedeUserID__ckMd5",
            "SESSDATA",
            "bili_jct",
            "sid",
        }
        return {
            name: values[0]
            for name, values in query.items()
            if name in cookie_names and values and values[0]
        }

    def upload(self, video: VideoInfo, account: str = "default") -> dict:
        """上传视频到B站"""
        credential = self._load_credential(account)

        video_path = Path(video.file_path)
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video.file_path}")
        if not video.title:
            raise ValueError("视频标题不能为空")

        human_type2 = resolve_human_type2(video.human_type2) or self.default_human_type2
        tags = video.tags or self.default_tags
        if not tags:
            tags = ["自动发布"]

        print(f"开始上传: {video.title}")
        print(f"  文件: {video_path}")
        print(f"  主区: {get_human_type2_name(human_type2)} ({human_type2})")
        print(f"  标签: {', '.join(tags)}")
        if self.line:
            print(f"  线路: {self.line}")
        print(f"  分片并发: {self.chunk_concurrency}")
        if video.season_id:
            print(f"  合集: {video.season_id}")

        uploader = BilibiliUploader(
            credential=credential,
            line=self.line,
            chunk_concurrency=self.chunk_concurrency,
        )
        result = asyncio.run(
            uploader.upload(
                video=video,
                tid=self.submit_tid,
                human_type2=human_type2,
                tags=tags,
                default_copyright=self.default_copyright,
            )
        )

        if video.season_id and result:
            try:
                aid = result.get("aid")
                cid = result.get("cid")
                if aid and cid:
                    print(f"正在添加到合集 {video.season_id}...")
                    asyncio.run(
                        add_episodes_to_season(
                            season_id=video.season_id,
                            episodes=[
                                {
                                    "title": video.title,
                                    "cid": cid,
                                    "aid": aid,
                                }
                            ],
                            credential=credential,
                        )
                    )
                    print("已添加到合集")
                elif aid:
                    print("添加到合集已跳过: 投稿结果中缺少 cid")
            except Exception as e:
                print(f"添加到合集失败 (视频已上传成功): {e}")

        print("上传成功！")
        return {"success": True, "result": result}


class BilibiliUploader:
    def __init__(
        self,
        credential: BilibiliCredential,
        line: str | None = None,
        chunk_concurrency: int = 3,
    ):
        self.credential = credential
        self.line = self._resolve_line(line)
        self.chunk_concurrency = max(1, int(chunk_concurrency))

    def _csrf_fields(self) -> dict[str, str]:
        return {
            "csrf": self.credential.bili_jct,
            "csrf_token": self.credential.bili_jct,
        }

    def _member_post_headers(self) -> dict[str, str]:
        return {
            **MEMBER_HEADERS,
            "x-csrf-token": self.credential.bili_jct,
            "x-csrfToken": self.credential.bili_jct,
        }

    async def upload(
        self,
        video: VideoInfo,
        tid: int,
        human_type2: int,
        tags: list[str],
        default_copyright: int,
    ) -> dict:
        cookies = await self.credential.get_buvid_cookies()
        video_path = Path(video.file_path).resolve()

        async with httpx.AsyncClient(
            headers=UPLOAD_HEADERS,
            cookies=cookies,
            timeout=None,
            follow_redirects=True,
        ) as client:
            page = await self._upload_page(
                client,
                video_path,
                video.title,
                video.description or "",
            )
            cover_url = ""
            if video.cover_path:
                print("上传封面...")
                cover_url = await self._upload_cover(client, Path(video.cover_path))

            cover43_url = ""
            if video.cover43_path:
                print("上传4:3封面...")
                cover43_url = await self._upload_cover(client, Path(video.cover43_path))

            print("提交稿件...")
            result = await self._submit(
                client=client,
                video=video,
                tid=tid,
                human_type2=human_type2,
                tags=tags,
                cover_url=cover_url,
                cover43_url=cover43_url,
                page=page,
                default_copyright=default_copyright,
            )
            if isinstance(result, dict) and "cid" not in result:
                result["cid"] = page["cid"]
            return result

    def _resolve_line(self, line: str | None) -> dict:
        if line is None:
            return UPLOAD_LINES["bda2"]

        key = str(line).strip().lower()
        if key not in UPLOAD_LINES:
            options = ", ".join(sorted(UPLOAD_LINES))
            raise ValueError(f"未知上传线路: {line}，可选值: {options}")
        return UPLOAD_LINES[key]

    async def _upload_page(
        self,
        client: httpx.AsyncClient,
        video_path: Path,
        title: str,
        description: str,
    ) -> dict:
        preupload = await self._preupload(client, video_path)
        print("准备上传分P...")

        total_chunks = await self._upload_chunks(client, video_path, preupload)
        completed = await self._complete_page(client, video_path, preupload, total_chunks)

        return {
            "title": title,
            "desc": description,
            "filename": completed["filename"],
            "cid": completed["cid"],
        }

    async def _preupload(self, client: httpx.AsyncClient, video_path: Path) -> dict:
        print("获取上传信息...")
        response = await client.get(
            PREUPLOAD_URL,
            params={
                "profile": "ugcfx/bup",
                "name": video_path.name,
                "size": video_path.stat().st_size,
                "r": self.line["os"],
                "ssl": "0",
                "version": "2.14.0",
                "build": "2100400",
                "upcdn": self.line["upcdn"],
                "probe_version": self.line["probe_version"],
            },
        )
        preupload = self._unwrap_response(response, expect_ok=True, stage="获取上传信息")
        preupload = self._switch_upload_endpoint(preupload)

        upload_url = self._get_upload_url(preupload)
        upload_id_response = await client.post(
            upload_url,
            headers={"x-upos-auth": preupload["auth"]},
            params={
                "uploads": "",
                "output": "json",
                "profile": "ugcfx/bup",
                "filesize": video_path.stat().st_size,
                "partsize": preupload["chunk_size"],
                "biz_id": preupload["biz_id"],
            },
        )
        upload_id_data = self._unwrap_response(
            upload_id_response,
            expect_ok=True,
            stage="申请 upload_id",
        )
        preupload["upload_id"] = upload_id_data["upload_id"]
        return preupload

    async def _upload_chunks(
        self,
        client: httpx.AsyncClient,
        video_path: Path,
        preupload: dict,
    ) -> int:
        file_size = video_path.stat().st_size
        chunk_size = int(preupload["chunk_size"])
        offsets = list(range(0, file_size, chunk_size))
        total_chunks = len(offsets)
        progress_interval = 1 if total_chunks <= 20 else max(1, total_chunks // 10)

        for batch_start in range(0, total_chunks, self.chunk_concurrency):
            batch = []
            batch_offsets = offsets[batch_start : batch_start + self.chunk_concurrency]
            for chunk_number, offset in enumerate(batch_offsets, start=batch_start):
                batch.append(
                    self._upload_chunk(
                        client=client,
                        video_path=video_path,
                        offset=offset,
                        chunk_number=chunk_number,
                        total_chunks=total_chunks,
                        preupload=preupload,
                    )
                )

            await asyncio.gather(*batch)
            completed = min(batch_start + len(batch), total_chunks)
            if completed == total_chunks or completed % progress_interval == 0:
                print(f"已上传分片: {completed}/{total_chunks}")

        return total_chunks

    async def _upload_chunk(
        self,
        client: httpx.AsyncClient,
        video_path: Path,
        offset: int,
        chunk_number: int,
        total_chunks: int,
        preupload: dict,
    ) -> None:
        chunk_size = int(preupload["chunk_size"])
        with video_path.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read(chunk_size)

        url = self._get_upload_url(preupload)
        params = {
            "partNumber": str(chunk_number + 1),
            "uploadId": str(preupload["upload_id"]),
            "chunk": str(chunk_number),
            "chunks": str(total_chunks),
            "size": str(len(chunk)),
            "start": str(offset),
            "end": str(offset + len(chunk)),
            "total": str(video_path.stat().st_size),
        }

        last_error: str | None = None
        for attempt in range(1, 4):
            try:
                response = await client.put(
                    url,
                    params=params,
                    content=chunk,
                    headers={"x-upos-auth": preupload["auth"]},
                )
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}"
                else:
                    body = response.text.strip()
                    if body in {"", "MULTIPART_PUT_SUCCESS"}:
                        return
                    last_error = body or "未知错误"
            except Exception as exc:
                last_error = str(exc)

            if attempt < 3:
                await asyncio.sleep(attempt)

        raise RuntimeError(
            f"上传分片失败: {chunk_number + 1}/{total_chunks}，原因: {last_error}"
        )

    async def _complete_page(
        self,
        client: httpx.AsyncClient,
        video_path: Path,
        preupload: dict,
        total_chunks: int,
    ) -> dict:
        response = await client.post(
            self._get_upload_url(preupload),
            params={
                "output": "json",
                "name": video_path.name,
                "profile": "ugcfx/bup",
                "uploadId": preupload["upload_id"],
                "biz_id": preupload["biz_id"],
            },
            headers={
                "x-upos-auth": preupload["auth"],
                "content-type": "application/json; charset=UTF-8",
            },
            content=json.dumps(
                {
                    "parts": [
                        {"partNumber": index, "eTag": "etag"}
                        for index in range(1, total_chunks + 1)
                    ]
                }
            ),
        )
        data = self._unwrap_response(response, expect_ok=True, stage="合并分片")
        key = str(data["key"]).lstrip("/")
        return {
            "filename": os.path.splitext(key)[0],
            "cid": preupload["biz_id"],
        }

    async def _upload_cover(
        self,
        client: httpx.AsyncClient,
        cover_path: Path,
    ) -> str:
        mime_type, _ = mimetypes.guess_type(cover_path.name)
        if mime_type is None:
            mime_type = "image/png"
        encoded = base64.b64encode(cover_path.read_bytes()).decode("utf-8")

        response = await client.post(
            COVER_UPLOAD_URL,
            headers=self._member_post_headers(),
            data={
                "cover": f"data:{mime_type};base64,{encoded}",
                **self._csrf_fields(),
            },
        )
        data = self._unwrap_response(response, stage="上传封面")
        return data["url"]

    def _build_submit_payload(
        self,
        video: VideoInfo,
        tid: int,
        human_type2: int,
        tags: list[str],
        cover_url: str,
        cover43_url: str,
        page: dict,
        default_copyright: int,
    ) -> dict:
        is_original = (video.copyright or default_copyright) == 1
        payload = {
            "title": video.title,
            "copyright": 1 if is_original else 2,
            "tid": tid,
            "human_type2": human_type2,
            "tag": ",".join(tags),
            "desc_format_id": 9999,
            "desc": video.description or "",
            "recreate": -1,
            "dynamic": video.dynamic or "",
            "interactive": 0,
            "act_reserve_create": 0,
            "no_disturbance": 0,
            "open_elec": 0,
            "origin_state": 0,
            "no_reprint": 1,
            "subtitle": {"open": 0, "lan": ""},
            "neutral_mark": "",
            "dolby": 0,
            "lossless_music": 0,
            "up_selection_reply": False,
            "up_close_reply": False,
            "up_close_danmu": False,
            "web_os": 2,
            "watermark": {"state": 1},
            "cover": cover_url,
            "videos": [page],
            "is_only_self": 1,
            "space_hidden": 2,
            **self._csrf_fields(),
        }

        if cover43_url:
            payload["cover43"] = cover43_url

        if not is_original and video.source:
            payload["source"] = video.source
        if video.scheduled_time:
            payload["dtime"] = video.scheduled_time

        return payload

    async def _submit(
        self,
        client: httpx.AsyncClient,
        video: VideoInfo,
        tid: int,
        human_type2: int,
        tags: list[str],
        cover_url: str,
        cover43_url: str,
        page: dict,
        default_copyright: int,
    ) -> dict:
        payload = self._build_submit_payload(
            video=video,
            tid=tid,
            human_type2=human_type2,
            tags=tags,
            cover_url=cover_url,
            cover43_url=cover43_url,
            page=page,
            default_copyright=default_copyright,
        )
        print("准备提交稿件...")

        response = await client.post(
            SUBMIT_URL,
            headers={
                **self._member_post_headers(),
                "content-type": "application/json;charset=UTF-8",
            },
            params={
                "csrf": self.credential.bili_jct,
                "t": int(time.time() * 1000),
            },
            json=payload,
        )
        return self._unwrap_response(response, stage="提交稿件")

    def _unwrap_response(
        self,
        response: httpx.Response,
        expect_ok: bool = False,
        stage: str = "请求",
    ) -> dict:
        response.raise_for_status()
        data = response.json()

        if expect_ok:
            if data.get("OK") != 1:
                raise RuntimeError(f"{stage}失败: {json.dumps(data, ensure_ascii=False)}")
            return data

        code = data.get("code")
        if code is not None and code != 0:
            message = data.get("message") or data.get("msg") or "请求失败"
            raise RuntimeError(f"{stage}失败: B站接口返回错误 {code}: {message}")

        real_data = data.get("data")
        if real_data is None:
            real_data = data.get("result")
        if real_data is None:
            return data
        return real_data

    def _switch_upload_endpoint(self, preupload: dict) -> dict:
        endpoint = str(preupload.get("endpoint", ""))
        if re.match(r"//upos-(sz|cs)-upcdn(bda2|ws|qn)\.bilivideo\.com", endpoint):
            preupload["endpoint"] = re.sub(
                r"upcdn(bda2|qn|ws)",
                f'upcdn{self.line["upcdn"]}',
                endpoint,
            )
        return preupload

    def _get_upload_url(self, preupload: dict) -> str:
        upos_uri = str(preupload["upos_uri"]).removeprefix("upos://")
        return f'https:{preupload["endpoint"]}/{upos_uri}'


async def add_episodes_to_season(
    season_id: int,
    episodes: list[dict],
    credential: BilibiliCredential,
) -> dict:
    """按创作中心请求体添加视频到合集。"""
    if not episodes:
        return {"success": True, "message": "无需添加视频"}

    cookies = await credential.get_buvid_cookies()
    csrf = credential.bili_jct or ""
    section_id = await _resolve_season_section_id(season_id, cookies)

    payload = {
        "sectionId": int(section_id),
        "episodes": [_normalize_episode(episode) for episode in episodes],
        "csrf": csrf,
    }

    async with httpx.AsyncClient(
        headers={
            **MEMBER_HEADERS,
            "Content-Type": "application/json;charset=UTF-8",
        },
        cookies=cookies,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        response = await client.post(
            SEASON_ADD_URL,
            params={"csrf": csrf},
            json=payload,
        )

    response.raise_for_status()
    data = response.json()
    code = data.get("code", -1)
    if code in SEASON_DUPLICATE_CODES:
        return data.get("data") or {
            "code": code,
            "message": data.get("message") or data.get("msg"),
        }
    if code != 0:
        message = data.get("message") or data.get("msg") or "请求失败"
        raise RuntimeError(f"添加到合集失败: B站接口返回错误 {code}: {message}")
    return data.get("data") or data


def _normalize_episode(episode: dict) -> dict:
    aid = episode.get("aid")
    cid = episode.get("cid")
    title = episode.get("title")

    if aid is None:
        raise RuntimeError("添加到合集失败: episodes[].aid 缺失")
    if cid is None:
        raise RuntimeError("添加到合集失败: episodes[].cid 缺失")
    if not title:
        raise RuntimeError("添加到合集失败: episodes[].title 缺失")

    return {
        "title": str(title),
        "cid": int(cid),
        "aid": int(aid),
    }


async def _resolve_season_section_id(season_id: int, cookies: dict[str, str]) -> int:
    async with httpx.AsyncClient(
        headers=MEMBER_HEADERS,
        cookies=cookies,
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        page = 1
        total = None

        while True:
            response = await client.get(
                SEASONS_URL,
                params={"pn": page, "ps": SEASONS_PAGE_SIZE},
            )
            response.raise_for_status()

            data = response.json()
            code = data.get("code", -1)
            if code != 0:
                message = data.get("message") or data.get("msg") or "请求失败"
                raise RuntimeError(f"查询合集失败: B站接口返回错误 {code}: {message}")

            payload = data.get("data") or {}
            seasons = payload.get("seasons") or []
            for item in seasons:
                season = item.get("season") or {}
                if int(season.get("id") or 0) == int(season_id):
                    return _pick_section_id(item)

            total = int(payload.get("total") or 0) if total is None else total
            if not seasons or page * SEASONS_PAGE_SIZE >= total:
                break
            page += 1

    raise RuntimeError(f"未找到合集: {season_id}")


def _pick_section_id(season_item: dict) -> int:
    sections = ((season_item.get("sections") or {}).get("sections")) or []
    if not sections:
        raise RuntimeError("合集缺少可用分节，无法自动添加视频")

    for section in sections:
        if section.get("title") == "正片":
            return int(section["id"])

    sections = sorted(
        sections,
        key=lambda section: (int(section.get("order") or 0), int(section.get("id") or 0)),
    )
    return int(sections[0]["id"])
