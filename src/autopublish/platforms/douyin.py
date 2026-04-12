import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from autopublish.platforms import VideoInfo

try:
    from patchright.async_api import TimeoutError as BrowserTimeoutError
    from patchright.async_api import async_playwright
except ImportError:
    from playwright.async_api import TimeoutError as BrowserTimeoutError
    from playwright.async_api import async_playwright

DOUYIN_HOME_URL = "https://creator.douyin.com/"
DOUYIN_UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
DOUYIN_MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"

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

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
}


class DouyinPlatform:
    """抖音创作者中心浏览器自动发布。"""

    name = "douyin"

    def __init__(self, config: dict):
        platform_config = config.get("douyin", {})
        credentials_dir = config.get("credentials_dir", "~/.autopublish/credentials")
        self.credentials_dir = Path(credentials_dir).expanduser()
        self.default_tags: list[str] = platform_config.get("tags", [])
        self.headless = bool(platform_config.get("headless", False))
        self.channel = platform_config.get("channel", "chrome")
        self.timeout_ms = int(platform_config.get("timeout", 120)) * 1000

    def _credential_path(self, account: str = "default") -> Path:
        return self.credentials_dir / f"douyin_{account}.json"

    def login(self, account: str = "default") -> None:
        asyncio.run(self._login_async(account))

    def check(self, account: str = "default") -> bool:
        try:
            valid = asyncio.run(self._check_async(account))
            print("凭证有效" if valid else "凭证无效或已过期，请重新登录")
            return valid
        except Exception as exc:
            print(f"凭证检查失败: {exc}")
            return False

    def upload(self, video: VideoInfo, account: str = "default") -> dict:
        result = asyncio.run(self._upload_async(video, account))
        print("上传成功！")
        return {"success": True, "result": result}

    async def _login_async(self, account: str = "default") -> None:
        credential_path = self._credential_path(account)
        credential_path.parent.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as playwright:
            browser = await self._launch_browser(playwright, headless=False)
            context = await browser.new_context()
            await self._set_init_script(context)
            page = await context.new_page()
            try:
                print("将打开抖音创作者中心，请在浏览器中完成登录...")
                await page.goto(DOUYIN_HOME_URL, wait_until="domcontentloaded")
                await self._wait_for_login(page)
                await context.storage_state(path=str(credential_path))
                print(f"登录成功！凭证已保存至: {credential_path}")
            finally:
                await context.close()
                await browser.close()

    async def _check_async(self, account: str = "default") -> bool:
        credential_path = self._credential_path(account)
        if not credential_path.exists():
            return False

        async with async_playwright() as playwright:
            browser = await self._launch_browser(playwright, headless=True)
            context = await browser.new_context(storage_state=str(credential_path))
            await self._set_init_script(context)
            page = await context.new_page()
            try:
                await page.goto(DOUYIN_UPLOAD_URL, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                return not await self._has_login_marker(page)
            finally:
                await context.close()
                await browser.close()

    async def _upload_async(self, video: VideoInfo, account: str) -> dict:
        credential_path = self._credential_path(account)
        if not credential_path.exists():
            raise RuntimeError(
                f"凭证文件不存在: {credential_path}\n"
                f"请先登录: autopublish login douyin --account {account}"
            )

        video_path = self._validate_video_file(video.file_path)
        if not video.title:
            raise ValueError("视频标题不能为空")
        if video.cover_path:
            self._validate_image_file(video.cover_path)
        if video.cover43_path:
            self._validate_image_file(video.cover43_path)

        tags = video.tags or self.default_tags
        publish_time = self._parse_schedule_time(video.scheduled_time)

        async with async_playwright() as playwright:
            browser = await self._launch_browser(playwright, headless=self.headless)
            context = await browser.new_context(
                storage_state=str(credential_path),
                permissions=["geolocation"],
            )
            await self._set_init_script(context)
            page = await context.new_page()
            try:
                print(f"开始上传到抖音: {video.title}")
                print(f"  文件: {video_path}")
                if tags:
                    print(f"  标签: {', '.join(tags)}")
                if publish_time:
                    print(f"  定时发布: {publish_time:%Y-%m-%d %H:%M}")

                await page.goto(DOUYIN_UPLOAD_URL, wait_until="domcontentloaded")
                if await self._has_login_marker(page):
                    raise RuntimeError("抖音登录已失效，请重新登录")

                await self._select_video_file(page, video_path)
                await self._wait_for_publish_page(page)
                await self._fill_title_description_tags(page, video.title, video.description, tags)
                await self._wait_for_video_uploaded(page)

                if video.cover_path or video.cover43_path:
                    await self._set_covers(
                        page,
                        landscape_cover_path=self._resolve_optional_path(video.cover_path),
                        portrait_cover_path=self._resolve_optional_path(video.cover43_path),
                    )

                if publish_time:
                    await self._set_schedule_time(page, publish_time)

                await self._click_publish(page)
                await context.storage_state(path=str(credential_path))
                return {"platform": "douyin", "account": account, "title": video.title}
            finally:
                await context.close()
                await browser.close()

    async def _launch_browser(self, playwright, headless: bool):
        launch_options = {"headless": headless}
        if self.channel:
            launch_options["channel"] = self.channel
        try:
            return await playwright.chromium.launch(**launch_options)
        except Exception as exc:
            if not self.channel:
                raise RuntimeError(
                    "无法启动浏览器，请先安装 Chrome 或执行: "
                    "python -m playwright install chromium"
                ) from exc
            print(
                f"使用浏览器 channel={self.channel} 启动失败，"
                f"改用 Playwright Chromium: {exc}"
            )
            launch_options.pop("channel", None)
            try:
                return await playwright.chromium.launch(**launch_options)
            except Exception as fallback_exc:
                raise RuntimeError(
                    "无法启动浏览器，请先安装 Chrome 或执行: "
                    "python -m playwright install chromium"
                ) from fallback_exc

    async def _set_init_script(self, context) -> None:
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            """
        )

    async def _wait_for_login(self, page) -> None:
        deadline = asyncio.get_running_loop().time() + max(self.timeout_ms / 1000, 300)
        while asyncio.get_running_loop().time() < deadline:
            if await self._is_logged_in(page):
                return
            await page.wait_for_timeout(3000)
        raise RuntimeError("等待抖音登录超时")

    async def _is_logged_in(self, page) -> bool:
        if await self._has_login_marker(page):
            return False
        if page.url.startswith("https://creator.douyin.com/creator-micro"):
            return True
        try:
            await page.goto(DOUYIN_UPLOAD_URL, wait_until="domcontentloaded", timeout=10000)
            await page.wait_for_timeout(1000)
            return not await self._has_login_marker(page)
        except Exception:
            return False

    async def _has_login_marker(self, page) -> bool:
        markers = [
            page.get_by_text("扫码登录", exact=True).first,
            page.get_by_text("手机号登录", exact=True).first,
            page.get_by_role("img", name="二维码").first,
        ]
        for marker in markers:
            try:
                if await marker.count() and await marker.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _select_video_file(self, page, video_path: Path) -> None:
        file_input = page.locator('input[type="file"]').first
        await file_input.wait_for(state="attached", timeout=self.timeout_ms)
        await file_input.set_input_files(str(video_path))

    async def _wait_for_publish_page(self, page) -> None:
        patterns = [
            "**/creator-micro/content/publish?enter_from=publish_page",
            "**/creator-micro/content/post/video?enter_from=publish_page",
        ]
        deadline = asyncio.get_running_loop().time() + max(self.timeout_ms / 1000, 300)
        while asyncio.get_running_loop().time() < deadline:
            for pattern in patterns:
                try:
                    await page.wait_for_url(pattern, timeout=3000)
                    return
                except BrowserTimeoutError:
                    continue
        raise RuntimeError("等待抖音发布页面加载超时")

    async def _fill_title_description_tags(
        self,
        page,
        title: str,
        description: str,
        tags: list[str],
    ) -> None:
        description_section = (
            page.get_by_text("作品描述", exact=True)
            .locator("xpath=ancestor::div[2]")
            .locator("xpath=following-sibling::div[1]")
        )

        title_input = description_section.locator('input[type="text"]').first
        await title_input.wait_for(state="visible", timeout=self.timeout_ms)
        await title_input.fill(title[:30])

        editor = description_section.locator('.zone-container[contenteditable="true"]').first
        await editor.wait_for(state="visible", timeout=self.timeout_ms)
        await editor.click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.press("Delete")
        await page.keyboard.type(description or title)

        for tag in tags:
            tag = str(tag).strip().lstrip("#")
            if not tag:
                continue
            await page.keyboard.type(" #" + tag)
            await page.keyboard.press("Space")

    async def _wait_for_video_uploaded(self, page) -> None:
        deadline = asyncio.get_running_loop().time() + max(self.timeout_ms / 1000, 600)
        while asyncio.get_running_loop().time() < deadline:
            if await page.locator('[class^="long-card"] div:has-text("重新上传")').count():
                print("视频上传完成")
                return
            if await page.locator('div.progress-div > div:has-text("上传失败")').count():
                raise RuntimeError("抖音视频上传失败")
            print("等待视频上传完成...")
            await page.wait_for_timeout(3000)
        raise RuntimeError("等待抖音视频上传完成超时")

    async def _set_covers(
        self,
        page,
        landscape_cover_path: Path | None = None,
        portrait_cover_path: Path | None = None,
    ) -> None:
        try:
            await page.get_by_text("选择封面", exact=True).first.click(timeout=10000)
            modal = page.locator('div[id*="creator-content-modal"]').first
            await modal.wait_for(state="visible", timeout=10000)
            upload_input = modal.locator(
                'div[class^="semi-upload upload"] input.semi-upload-hidden-input'
            ).first
            if not await upload_input.count():
                upload_input = modal.locator('input[type="file"]').first
            await upload_input.wait_for(state="attached", timeout=10000)

            if landscape_cover_path:
                await self._select_cover_step(modal, 0)
                await upload_input.set_input_files(str(landscape_cover_path))
                await page.wait_for_timeout(2000)
                print("横版封面设置完成")

            if portrait_cover_path:
                await self._select_cover_step(modal, 1)
                await upload_input.set_input_files(str(portrait_cover_path))
                await page.wait_for_timeout(2000)
                print("竖版封面设置完成")

            await modal.locator('button:visible:has-text("完成")').click()
            print("封面设置完成")
        except Exception as exc:
            raise RuntimeError(f"设置抖音封面失败: {exc}") from exc

    async def _select_cover_step(self, modal, index: int) -> None:
        steps = modal.locator('div[class*="steps"] div')
        step_count = await steps.count()
        if step_count > index:
            await steps.nth(index).click()
            return
        if index == 1:
            labels = ["竖版封面", "主页封面", "封面二"]
            for label in labels:
                target = modal.get_by_text(label, exact=True).first
                if await target.count():
                    await target.click()
                    return

    def _resolve_optional_path(self, file_path: str | None) -> Path | None:
        if not file_path:
            return None
        return Path(file_path).expanduser().resolve()

    async def _set_schedule_time(self, page, publish_time: datetime) -> None:
        await page.locator("[class^='radio']:has-text('定时发布')").click()
        await page.wait_for_timeout(1000)
        await page.locator('.semi-input[placeholder="日期和时间"]').click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.type(publish_time.strftime("%Y-%m-%d %H:%M"))
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1000)

    async def _click_publish(self, page) -> None:
        deadline = asyncio.get_running_loop().time() + max(self.timeout_ms / 1000, 300)
        while asyncio.get_running_loop().time() < deadline:
            try:
                publish_button = page.get_by_role("button", name="发布", exact=True)
                if await publish_button.count():
                    await publish_button.click()
                await page.wait_for_url(DOUYIN_MANAGE_URL + "**", timeout=5000)
                print("抖音视频发布已提交")
                return
            except Exception:
                await self._choose_recommended_cover_if_required(page)
                await page.wait_for_timeout(1000)
        raise RuntimeError("提交抖音发布超时")

    async def _choose_recommended_cover_if_required(self, page) -> None:
        try:
            if not await page.get_by_text("请设置封面后再发布").first.is_visible():
                return
            recommend_cover = page.locator('[class^="recommendCover-"]').first
            if not await recommend_cover.count():
                return
            await recommend_cover.click()
            await page.wait_for_timeout(1000)
            confirm = page.get_by_text("是否确认应用此封面？").first
            if await confirm.count() and await confirm.is_visible():
                await page.get_by_role("button", name="确定").click()
        except Exception:
            return

    def _parse_schedule_time(self, timestamp: int | None) -> datetime | None:
        if not timestamp:
            return None
        publish_time = datetime.fromtimestamp(int(timestamp))
        min_publish_time = datetime.now() + timedelta(hours=2)
        if publish_time <= min_publish_time:
            raise ValueError("抖音定时发布时间必须大于当前时间 2 小时")
        return publish_time

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

    def _validate_image_file(self, file_path: str) -> Path:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"图片文件不存在: {path}")
        if not path.is_file():
            raise ValueError(f"图片路径不是文件: {path}")
        if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            options = ", ".join(sorted(SUPPORTED_IMAGE_EXTENSIONS))
            raise ValueError(f"不支持的图片格式: {path.suffix}，当前支持: {options}")
        return path
