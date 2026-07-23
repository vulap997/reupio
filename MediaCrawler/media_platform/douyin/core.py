# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/douyin/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。

import asyncio
import glob
import json
import os
import random
import re
import urllib.parse
import urllib.request
from asyncio import Task
from typing import Any, Dict, List, Optional, Tuple

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)

import config
from base.base_crawler import AbstractCrawler
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import douyin as douyin_store
from tools import utils
from tools import dich_ten
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import DouYinClient
from .exception import DataFetchError
from .field import PublishTimeType, SearchSortType
from .help import parse_video_info_from_url, parse_creator_info_from_url
from .login import DouYinLogin


# Tên thiết bị dành riêng của Windows — không được dùng làm tên file/thư mục
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def _safe_name(s: str, maxlen: int = 60) -> str:
    """Làm sạch tên thư mục/tệp: bỏ ký tự cấm trên Windows, rút gọn."""
    s = (s or "").strip()
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")
    s = s[:maxlen].strip() or "video"
    if s.upper() in _WIN_RESERVED:
        s += "_"
    return s


_VI_CACHE = None


def _vi_cache_path() -> str:
    base = config.SAVE_DATA_PATH if config.SAVE_DATA_PATH else "data"
    return os.path.join(base, "douyin", "_kenh_vi.json")


def ten_kenh_vi(safe_nick: str) -> str:
    """Dịch tên kênh (đã làm sạch) sang tiếng Việt cho người Việt dễ đọc; cache lại. '' nếu không cần/không được."""
    global _VI_CACHE
    if not safe_nick:
        return ""
    if _VI_CACHE is None:
        _VI_CACHE = {}
        p = _vi_cache_path()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    _VI_CACHE = json.load(f)
            except Exception:
                _VI_CACHE = {}
    if safe_nick in _VI_CACHE:
        return _VI_CACHE[safe_nick]
    # Nếu tên đã chủ yếu là chữ Latin thì khỏi dịch
    ascii_letters = sum(1 for c in safe_nick if ord(c) < 128 and c.isalpha())
    vi = ""
    if ascii_letters < max(3, len(safe_nick.replace(" ", "")) * 0.5):
        try:
            _tl = (os.environ.get("TARGET_LANG") or "vi").strip().lower()
            if _tl not in ("vi", "en"):
                _tl = "vi"
            url = ("https://translate.googleapis.com/translate_a/single"
                   "?client=gtx&sl=auto&tl=" + _tl + "&dt=t&q=" + urllib.parse.quote(safe_nick))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            vi = "".join(s[0] for s in d[0] if s and s[0]).strip()
            vi = re.sub(r'[\\/:*?"<>|]+', " ", vi).strip()[:40].strip()
        except Exception:
            vi = ""
    _VI_CACHE[safe_nick] = vi
    try:
        p = _vi_cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_VI_CACHE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return vi


def _media_path_parts(aweme_item: Dict) -> Tuple[str, str]:
    """Tạo (thư mục con, tên tệp gốc) theo kiểu cào: tu-khoa / kenh / link."""
    ctype = crawler_type_var.get()
    aweme_id = aweme_item.get("aweme_id", "") or ""
    # Tên file = tiêu đề ĐÃ DỊCH sang ngôn ngữ đích (không chỉ dịch trên màn hình)
    title = _safe_name(dich_ten.dich_tieu_de(aweme_item.get("desc", ""), "douyin"), 60)
    id6 = aweme_id[-6:]
    file_base = f"{title}_{id6}" if id6 else title
    if ctype == "search":
        grp = _safe_name(source_keyword_var.get() or "khac", 40)
        sub_dir = f"tu-khoa/{grp}"
    elif ctype == "creator":
        nickname = (aweme_item.get("author", {}) or {}).get("nickname", "") or "khong-ro"
        safe_nick = _safe_name(nickname, 40)
        vi = ten_kenh_vi(safe_nick)
        folder = _safe_name(vi, 40) if vi else safe_nick  # tên Việt cho người Việt; lỗi dịch -> giữ tên gốc
        sub_dir = f"kenh/{folder}"
    else:
        sub_dir = "link"
    return sub_dir, file_base


class DouYinCrawler(AbstractCrawler):
    context_page: Page
    dy_client: DouYinClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self) -> None:
        self.index_url = "https://www.douyin.com"
        self.cookie_urls = [
            "https://douyin.com",
            self.index_url,
            "https://creator.douyin.com",
            "https://douhot.douyin.com",
            "https://live.douyin.com",
        ]
        self.cdp_manager = None
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh
        self._seen_ids = None  # sổ ID đã tải (để không tải lại dù file gốc đã bị xóa sau rerender)
        self._dl_tasks = []    # tải media chạy NỀN (song song có giới hạn) — crawl/API VẪN tuần tự
        self._dl_sem = None    # asyncio.Semaphore(MC_DL_CONCURRENCY) — tạo lazy trong event loop

    def _tai_nen(self, coro_fn, *a):
        """Lên lịch TẢI MEDIA chạy NỀN, giới hạn MC_DL_CONCURRENCY (mặc định 2). Fetch-detail/API VẪN tuần
        tự (semaphore cũ không đổi) → chỉ phần tải video chồng lấp = nhanh hơn mà nhẹ nhàng với anti-bot."""
        if self._dl_sem is None:
            self._dl_sem = asyncio.Semaphore(max(1, int(os.environ.get("MC_DL_CONCURRENCY", "2"))))
        async def _w():
            async with self._dl_sem:
                try:
                    await coro_fn(*a)
                except Exception as _e:
                    utils.logger.error(f"[tai-nen] {_e}")
        self._dl_tasks.append(asyncio.create_task(_w()))

    async def _drain_tai(self):
        """Đợi MỌI tải nền hoàn tất (gọi cuối mỗi hàm cào, trước khi return)."""
        if self._dl_tasks:
            await asyncio.gather(*self._dl_tasks, return_exceptions=True)
            self._dl_tasks = []

    def _ledger_path(self) -> str:
        base = config.SAVE_DATA_PATH if config.SAVE_DATA_PATH else "data"
        return os.path.join(base, "douyin", "_da_tai_ids.txt")

    def _load_seen(self):
        if self._seen_ids is None:
            self._seen_ids = set()
            p = self._ledger_path()
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        self._seen_ids = {line.strip() for line in f if line.strip()}
                except Exception:
                    pass
        return self._seen_ids

    def _mark_seen(self, aweme_id: str):
        if not aweme_id:
            return
        self._load_seen().add(aweme_id)
        p = self._ledger_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(aweme_id + "\n")
        except Exception:
            pass

    def _video_moi_path(self) -> str:
        base = config.SAVE_DATA_PATH if config.SAVE_DATA_PATH else "data"
        return os.path.join(base, "douyin", "_video_moi.jsonl")

    def _ghi_video_moi(self, aweme_item: Dict, sub_dir: str, file_base: str):
        """Ghi 1 dòng 'video MỚI theo kênh' vào sổ phụ _video_moi.jsonl (sidecar — KHÔNG đụng ledger).
        Chỉ cho cào theo KÊNH (sub_dir 'kenh/...'); giữ sec_uid + create_time để truy ngược kênh + ngày đăng.
        Bọc try/except: lỗi ghi sổ KHÔNG được làm hỏng việc tải (giống _mark_seen)."""
        try:
            if not sub_dir.startswith("kenh/"):
                return
            author = aweme_item.get("author", {}) or {}
            ban_ghi = {
                "aweme_id": aweme_item.get("aweme_id", "") or "",
                "sec_uid": author.get("sec_uid", "") or "",
                "nickname": author.get("nickname", "") or "",
                "kenh": sub_dir[len("kenh/"):],
                "create_time": aweme_item.get("create_time", 0) or 0,
                "platform": "douyin",
                "file": f"{sub_dir}/{file_base}.mp4",
                "da_xem": False,
            }
            p = self._video_moi_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(ban_ghi, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def start(self) -> None:
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        # NO-BROWSER (mặc định ON): cookie giải mã từ profile Chromium (DPAPI) + httpx + a_bogus qua execjs
        # — KHÔNG mở Playwright headless. Tránh douyin anti-bot flag "nhiều phiên browser lạ liên tiếp" →
        # hết throttle khi cào nhiều lần (giống bili no-browser). Kill-switch: DY_NO_BROWSER=0 → quay browser.
        if os.environ.get("DY_NO_BROWSER", "1") != "0":
            self.dy_client = self._create_douyin_client_no_browser(httpx_proxy_format)
            if not await self.dy_client.pong():
                utils.logger.error("[DouYinCrawler] Chưa đăng nhập Douyin (no-browser: thiếu cookie sessionid). Hãy đăng nhập qua nút Đăng nhập trong app.")
                return
            await self._run_crawl()
            return

        async with async_playwright() as playwright:
            # Select startup mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[DouYinCrawler] 使用CDP模式启动浏览器")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    None,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[DouYinCrawler] 使用标准模式启动浏览器")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(
                    chromium,
                    playwright_proxy_format,
                    user_agent=None,
                    headless=config.HEADLESS,
                )
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            # Dùng domcontentloaded + timeout: trang chủ Douyin nặng, chờ "load" có thể TREO vô hạn.
            try:
                await self.context_page.goto(self.index_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                utils.logger.warning(f"[DouYinCrawler] goto index bỏ qua (timeout/err): {e}")

            self.dy_client = await self.create_douyin_client(httpx_proxy_format)
            if not await self.dy_client.pong(browser_context=self.browser_context):
                if os.environ.get("MC_NO_QR_LOGIN", "1") != "0":   # app crawl: KHÔNG tự bật QR popup (tmp*.PNG) khi chưa login -> fail gọn; login qua nút Đăng nhập
                    utils.logger.error("[DouYinCrawler] Chưa đăng nhập Douyin — KHÔNG cào được. Hãy đăng nhập qua nút Đăng nhập trong app.")
                    return
                login_obj = DouYinLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # you phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.dy_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )
            await self._run_crawl()

    async def _run_crawl(self) -> None:
        """Dispatch theo CRAWLER_TYPE — dùng CHUNG cho cả no-browser lẫn browser mode."""
        crawler_type_var.set(config.CRAWLER_TYPE)
        if config.CRAWLER_TYPE == "search":
            await self.search()
        elif config.CRAWLER_TYPE == "detail":
            await self.get_specified_awemes()
        elif config.CRAWLER_TYPE == "creator":
            await self.get_creators_and_videos()
        elif config.CRAWLER_TYPE == "userlist":
            await self.search_creators_to_file()
        utils.logger.info("[DouYinCrawler.start] Douyin Crawler finished ...")

    async def search_creators_to_file(self) -> None:
        """Tìm KÊNH theo từ khóa: tìm video → lấy tác giả → tra số follow → xếp hạng → ghi JSON."""
        keyword = (config.KEYWORDS.split(",")[0] if config.KEYWORDS else "").strip()
        out_path = os.environ.get("GOI_Y_OUT") or os.path.join("data", "douyin", "_goi_y_kenh.json")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        utils.logger.info(f"[search_creators_to_file] Tìm kênh theo từ khóa: {keyword}")

        # 1) Tìm video, gom tác giả duy nhất (qua vài trang để có nhiều kênh)
        authors: Dict[str, Dict] = {}
        dy_search_id = ""
        # ANTI-BOT RETRY (như search() cào-video): Douyin RẤT hay trả RỖNG lần gọi ĐẦU (风控/giới hạn tần suất)
        # rồi OK khi thử lại (mỗi lần client tự sinh msToken+a_bogus MỚI = chữ ký mới). Trước đây gợi-ý-kênh
        # BỎ CUỘC ngay khi trang đầu rỗng → "không tìm được kênh dù đã login". Chỉ retry TRANG ĐẦU (rỗng).
        dy_max_retry = int(os.environ.get("DY_SEARCH_RETRY", 4))
        for page in range(2):
            data = []
            for _attempt in range(dy_max_retry + 1):
                try:
                    res = await self.dy_client.search_info_by_keyword(
                        keyword=keyword, offset=page * 10, search_id=dy_search_id)
                except Exception as e:
                    utils.logger.error(f"[search_creators_to_file] search page {page} error: {e}")
                    res = {}
                data = res.get("data") or []
                dy_search_id = res.get("extra", {}).get("logid", "") or dy_search_id
                if data or page > 0 or _attempt >= dy_max_retry:
                    break    # có kết quả / trang sau (rỗng=hết thật) / hết lượt thử → dừng retry
                wait = config.CRAWLER_MAX_SLEEP_SEC + 3 * (_attempt + 1)   # backoff tăng dần
                utils.logger.info(f"[search_creators_to_file] Douyin tra RONG (co the 风控/gioi han tan suat) - nghi {wait}s thu lai voi chu ky moi ({_attempt+1}/{dy_max_retry})...")
                await asyncio.sleep(wait)
            if not data:
                if page == 0:
                    utils.logger.error(f"[search_creators_to_file] DOUYIN_EMPTY: keyword '{keyword}' tra 0 sau {dy_max_retry} lan thu (anti-bot/gioi han tan suat - KHONG phai loi tool, thu lai sau)")
                break
            for item in data:
                cands = []
                if item.get("aweme_info"):
                    cands.append(item["aweme_info"])
                cands += item.get("aweme_list") or []
                for a in cands:
                    au = (a or {}).get("author") or {}
                    sec = au.get("sec_uid")
                    if not sec or sec in authors:
                        continue
                    avatar = ""
                    v = au.get("avatar_thumb") or {}
                    if v.get("url_list"):
                        avatar = v["url_list"][0]
                    authors[sec] = {"nickname": au.get("nickname", ""), "avatar": avatar}
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)

        # 2) Tra follow/like/video từng kênh — chạy SONG SONG (semaphore) cho nhanh.
        #    GOI_Y_FANS=0 để tắt (chỉ lấy tên/avatar, cực nhanh). GOI_Y_LIMIT giới hạn số kênh.
        lay_fans = os.environ.get("GOI_Y_FANS", "1") == "1"
        gioi_han_kenh = int(os.environ.get("GOI_Y_LIMIT", "12"))
        items = list(authors.items())[:gioi_han_kenh]
        sem = asyncio.Semaphore(5)

        async def _lay_1_kenh(sec, base):
            avatar = base["avatar"]
            fans = total = videos = 0
            sig = ""
            if lay_fans:
                async with sem:
                    try:
                        info = await self.dy_client.get_user_info(sec)
                        u = info.get("user", {}) if isinstance(info, dict) else {}
                        fans = u.get("max_follower_count") or u.get("follower_count") or 0
                        total = u.get("total_favorited") or 0
                        videos = u.get("aweme_count") or 0
                        sig = u.get("signature", "")
                        if not avatar:
                            uri = (u.get("avatar_300x300", {}) or {}).get("uri")
                            if uri:
                                avatar = f"https://p3-pc.douyinpic.com/img/{uri}~c5_300x300.jpeg?from=2956013662"
                    except Exception as e:
                        utils.logger.error(f"[search_creators_to_file] get_user_info error: {e}")
            return {
                "nickname": base["nickname"], "sec_uid": sec,
                "link": f"https://www.douyin.com/user/{sec}", "avatar": avatar,
                "fans": fans, "total_favorited": total, "videos_count": videos, "signature": sig,
            }

        creators = list(await asyncio.gather(*[_lay_1_kenh(s, b) for s, b in items]))
        if lay_fans:
            creators.sort(key=lambda c: c.get("fans") or 0, reverse=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(creators, f, ensure_ascii=False, indent=2)
        utils.logger.info(f"[search_creators_to_file] Đã lưu {len(creators)} kênh -> {out_path}")

    async def search(self) -> None:
        utils.logger.info("[DouYinCrawler.search] Begin search douyin keywords")
        dy_limit_count = 10  # douyin limit page fixed value
        if config.CRAWLER_MAX_NOTES_COUNT < dy_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = dy_limit_count
        start_page = config.START_PAGE  # start page number
        # "Cào KHÔNG TRÙNG" (đào sâu): MC_DEEP_NEW=1 → cào tới khi đủ N video CHƯA TẢI (bỏ qua video đã tải,
        # đào trang SÂU hơn) thay vì chỉ N/10 trang → "tải hết rồi vẫn ra video mới". Trần MC_DEEP_PAGE_CAP
        # chống đào vô hạn kênh không còn gì mới (đào sâu = nhiều request hơn = tăng rủi ro anti-bot).
        DEEP = os.environ.get("MC_DEEP_NEW", "0") == "1"
        try:
            DEEP_PAGE_CAP = int(os.environ.get("MC_DEEP_PAGE_CAP", "40") or 40)
        except ValueError:
            DEEP_PAGE_CAP = 40
        seen_ref = self._load_seen()   # set ID đã tải (cached) — đếm "mới" = aid vừa được get_aweme_media mark_seen
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[DouYinCrawler.search] Current keyword: {keyword}")
            aweme_list: List[str] = []
            new_count = 0   # số video MỚI (chưa tải) đã tải được trong lần này — dùng cho chế độ đào sâu DEEP
            page = 0
            dy_search_id = ""
            while ((not DEEP and (page - start_page + 1) * dy_limit_count <= config.CRAWLER_MAX_NOTES_COUNT)
                   or (DEEP and new_count < config.CRAWLER_MAX_NOTES_COUNT and (page - start_page) < DEEP_PAGE_CAP)):
                if page < start_page:
                    utils.logger.info(f"[DouYinCrawler.search] Skip {page}")
                    page += 1
                    continue
                # Cho phép GUI ghi đè kiểu sắp xếp / lọc thời gian qua biến môi trường
                sort_val = int(os.environ.get("DY_SORT_TYPE", getattr(config, "DY_SEARCH_SORT_TYPE", 0)))
                time_val = int(os.environ.get("DY_PUBLISH_TIME", config.PUBLISH_TIME_TYPE))
                # ANTI-BOT RETRY: Douyin RẤT hay trả data RỖNG (风控 / giới hạn tần suất) ở lần gọi ĐẦU rồi
                # thành công khi thử lại — khác Bilibili (đã ổn) ở chỗ trước đây Douyin BỎ CUỘC ngay, không retry.
                # Mỗi lần gọi client tự sinh msToken + a_bogus MỚI nên retry là một chữ ký mới (cơ hội qua 风控).
                # Chỉ retry khi CHƯA lấy được bài nào (trang ĐẦU); trang sau rỗng = đã hết kết quả thật → dừng.
                dy_max_retry = int(os.environ.get("DY_SEARCH_RETRY", 4))
                posts_res = None
                for _attempt in range(dy_max_retry + 1):
                    try:
                        utils.logger.info(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page}, sort={sort_val}, time={time_val}" + (f" (thu lai {_attempt}/{dy_max_retry})" if _attempt else ""))
                        posts_res = await self.dy_client.search_info_by_keyword(
                            keyword=keyword,
                            offset=page * dy_limit_count - dy_limit_count,
                            sort_type=SearchSortType(sort_val),
                            publish_time=PublishTimeType(time_val),
                            search_id=dy_search_id,
                        )
                    except DataFetchError:
                        posts_res = None   # bị chặn (text rỗng / "blocked") → coi như rỗng, sẽ retry
                    if posts_res and posts_res.get("data"):
                        break              # có kết quả → thoát retry
                    # Rỗng GIỮA CHỪNG thường là 风控 TẠM (trang 1 cũng từng rỗng rồi hồi phục sau retry) → RETRY
                    # CẢ trang sau (mỗi lần msToken/a_bogus mới = cơ hội qua 风控). Hết lượt vẫn rỗng = hết thật → dừng.
                    # (Trước đây: trang-sau rỗng → break NGAY, không retry → kẹt ~20 video dù keyword còn nhiều.)
                    if _attempt >= dy_max_retry:
                        break
                    wait = config.CRAWLER_MAX_SLEEP_SEC + 3 * (_attempt + 1)   # backoff tăng dần
                    utils.logger.info(f"[DouYinCrawler.search] Douyin tra RONG (co the 风控/gioi han tan suat) - nghi {wait}s roi thu lai voi chu ky moi...")
                    await asyncio.sleep(wait)

                if not posts_res or posts_res.get("data") is None or posts_res.get("data") == []:
                    if not aweme_list:
                        # Rỗng NGAY sau khi đã retry (chưa lấy được bài nào) = NỀN TẢNG từ chối:
                        # Douyin trả data rỗng (KHÔNG báo lỗi) khi phiên hết hạn / anti-bot / 风控 / giới hạn tần suất.
                        utils.logger.error(f"[DouYinCrawler.search] DOUYIN_EMPTY_RESULT keyword:{keyword} (Douyin tra 0 ket qua sau {dy_max_retry} lan thu - thuong do phien het han / anti-bot / gioi han tan suat, KHONG phai loi tool)")
                    else:
                        utils.logger.info(f"[DouYinCrawler.search] search douyin keyword: {keyword}, page: {page} is empty")
                    break

                page += 1
                if "data" not in posts_res:
                    utils.logger.error(f"[DouYinCrawler.search] search douyin keyword: {keyword} failed，账号也许被风控了。")
                    break
                dy_search_id = posts_res.get("extra", {}).get("logid", "")
                page_aweme_list = []
                for post_item in posts_res.get("data"):
                    try:
                        aweme_info: Dict = (post_item.get("aweme_info") or post_item.get("aweme_mix_info", {}).get("mix_items")[0])
                    except TypeError:
                        continue
                    aid = aweme_info.get("aweme_id", "")
                    was_new = bool(aid) and aid not in seen_ref   # chưa tải TRƯỚC khi gọi
                    aweme_list.append(aid)
                    page_aweme_list.append(aid)
                    await douyin_store.update_douyin_aweme(aweme_item=aweme_info)
                    if DEEP:                                   # đào sâu: cần tải XONG để đếm video mới → TUẦN TỰ
                        await self.get_aweme_media(aweme_item=aweme_info)
                        if was_new and aid in seen_ref:        # get_aweme_media đã mark_seen ⇒ tải MỚI thành công
                            new_count += 1
                            if new_count >= config.CRAWLER_MAX_NOTES_COUNT:
                                utils.logger.info(f"[DouYinCrawler.search] Đủ {new_count} video MỚI (đào sâu) — dừng keyword {keyword}")
                                break
                    else:
                        self._tai_nen(self.get_aweme_media, aweme_info)   # tải NỀN song song (≤MC_DL_CONCURRENCY)

                # Batch get note comments for the current page
                await self.batch_get_note_comments(page_aweme_list)

                # Sleep after each page navigation
                await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                utils.logger.info(f"[DouYinCrawler.search] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")
            utils.logger.info(f"[DouYinCrawler.search] keyword:{keyword}, aweme_list:{aweme_list}")
        await self._drain_tai()    # đợi tải nền (non-deep) xong trước khi kết thúc search

    async def get_specified_awemes(self):
        """Get the information and comments of the specified post from URLs or IDs"""
        utils.logger.info("[DouYinCrawler.get_specified_awemes] Parsing video URLs...")
        aweme_id_list = []
        for video_url in config.DY_SPECIFIED_ID_LIST:
            try:
                video_info = parse_video_info_from_url(video_url)

                # Handling short links
                if video_info.url_type == "short":
                    utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Resolving short link: {video_url}")
                    resolved_url = await self.dy_client.resolve_short_url(video_url)
                    if resolved_url:
                        # Extract video ID from parsed URL
                        video_info = parse_video_info_from_url(resolved_url)
                        utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Short link resolved to aweme ID: {video_info.aweme_id}")
                    else:
                        utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to resolve short link: {video_url}")
                        continue

                aweme_id_list.append(video_info.aweme_id)
                utils.logger.info(f"[DouYinCrawler.get_specified_awemes] Parsed aweme ID: {video_info.aweme_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_specified_awemes] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(aweme_id=aweme_id, semaphore=semaphore) for aweme_id in aweme_id_list]
        aweme_details = await asyncio.gather(*task_list)
        for aweme_detail in aweme_details:
            if aweme_detail is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_detail)
                self._tai_nen(self.get_aweme_media, aweme_detail)   # tải NỀN song song
        await self._drain_tai()
        await self.batch_get_note_comments(aweme_id_list)

    async def get_aweme_detail(self, aweme_id: str, semaphore: asyncio.Semaphore) -> Any:
        """Get note detail"""
        async with semaphore:
            # ANTI-BOT RETRY: detail API Douyin cũng hay rỗng/风控 (nhất là khi cào dồn / IP bị giới hạn tần
            # suất) → thử lại với CHỮ KÝ MỚI (mỗi get_video_by_id sinh msToken/a_bogus mới = cơ hội qua 风控),
            # như search/creator. Trước: lỗi 1 lần → None → "tải lại từ lịch sử ra 0 video" dù chỉ là 风控 TẠM.
            dy_max_retry = int(os.environ.get("DY_SEARCH_RETRY", 4))
            for _attempt in range(dy_max_retry + 1):
                try:
                    result = await self.dy_client.get_video_by_id(aweme_id)
                    if result:
                        await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                        return result
                except DataFetchError:
                    result = None
                except KeyError as ex:
                    utils.logger.error(f"[DouYinCrawler.get_aweme_detail] have not fund note detail aweme_id:{aweme_id}, err: {ex}")
                    return None
                if _attempt >= dy_max_retry:
                    utils.logger.error(f"[DouYinCrawler.get_aweme_detail] aweme {aweme_id} rong/风控 sau {dy_max_retry} lan thu")
                    return None
                wait = config.CRAWLER_MAX_SLEEP_SEC + 3 * (_attempt + 1)
                utils.logger.info(f"[DouYinCrawler.get_aweme_detail] aweme {aweme_id} 风控/rong - nghi {wait}s thu lai voi chu ky moi...")
                await asyncio.sleep(wait)
            return None

    async def batch_get_note_comments(self, aweme_list: List[str]) -> None:
        """
        Batch get note comments
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[DouYinCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        task_list: List[Task] = []
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        for aweme_id in aweme_list:
            task = asyncio.create_task(self.get_comments(aweme_id, semaphore), name=aweme_id)
            task_list.append(task)
        if len(task_list) > 0:
            await asyncio.wait(task_list)

    async def get_comments(self, aweme_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                # Pass the list of keywords to the get_aweme_all_comments method
                # Use fixed crawling interval
                crawl_interval = config.CRAWLER_MAX_SLEEP_SEC
                await self.dy_client.get_aweme_all_comments(
                    aweme_id=aweme_id,
                    crawl_interval=crawl_interval,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=douyin_store.batch_update_dy_aweme_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )
                # Sleep after fetching comments
                await asyncio.sleep(crawl_interval)
                utils.logger.info(f"[DouYinCrawler.get_comments] Sleeping for {crawl_interval} seconds after fetching comments for aweme {aweme_id}")
                utils.logger.info(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} comments have all been obtained and filtered ...")
            except DataFetchError as e:
                utils.logger.error(f"[DouYinCrawler.get_comments] aweme_id: {aweme_id} get comments failed, error: {e}")

    async def get_creators_and_videos(self) -> None:
        """
        Get the information and videos of the specified creator from URLs or IDs
        """
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Begin get douyin creators")
        utils.logger.info("[DouYinCrawler.get_creators_and_videos] Parsing creator URLs...")

        for creator_url in config.DY_CREATOR_ID_LIST:
            try:
                creator_info_parsed = parse_creator_info_from_url(creator_url)
                user_id = creator_info_parsed.sec_user_id
                utils.logger.info(f"[DouYinCrawler.get_creators_and_videos] Parsed sec_user_id: {user_id} from {creator_url}")
            except ValueError as e:
                utils.logger.error(f"[DouYinCrawler.get_creators_and_videos] Failed to parse creator URL: {e}")
                continue

            creator_info: Dict = await self.dy_client.get_user_info(user_id)
            if creator_info:
                await douyin_store.save_creator(user_id, creator=creator_info)

            # Chọn video theo: mới nhất (newest) hoặc nhiều like nhất (most_liked) + số lượng
            sort_mode = os.environ.get("DY_CREATOR_SORT", "newest")
            limit = config.CRAWLER_MAX_NOTES_COUNT
            selected = await self._collect_user_posts(user_id, sort_mode, limit)
            utils.logger.info(f"[DouYinCrawler.get_creators_and_videos] sort={sort_mode}, lấy {len(selected)} video")
            # XEM TRƯỚC (MC_GET_MEDIAS=0): list item ĐÃ có đủ cover/title/like/url → GHI THẲNG, KHỎI fetch detail
            # từng video (get_aweme_detail + sleep chống-bot = CHẬM, khách báo tới 10 phút). Preview chỉ cần
            # cover/title → nhanh hẳn (chỉ tốn thời gian phân trang list). Cào THẬT (tải) vẫn fetch detail đầy đủ.
            if os.environ.get("MC_GET_MEDIAS", "1") == "0":
                for _aw in selected:
                    try:
                        await douyin_store.update_douyin_aweme(aweme_item=_aw)
                    except Exception as _e:
                        utils.logger.warning(f"[get_creators_and_videos] preview ghi list item lỗi: {_e}")
            else:
                await self.fetch_creator_video_detail(selected)

            video_ids = [video_item.get("aweme_id") for video_item in selected]
            await self.batch_get_note_comments(video_ids)

    async def _collect_user_posts(self, sec_user_id: str, sort_mode: str, limit: int) -> List[Dict]:
        """Thu thập danh sách bài của kênh rồi chọn theo mới nhất / nhiều like nhất.
        LỌC THEO NGÀY ĐĂNG: DY_PUBLISH_TIME (1=1 ngày, 7=1 tuần, 180=6 tháng; 0=không lọc) — áp cho
        cào KÊNH bằng create_time (search đã có sẵn filter của Douyin; kênh thì tự lọc ở đây)."""
        import time as _t
        try:
            days = int(os.environ.get("DY_PUBLISH_TIME", "0"))
        except ValueError:
            days = 0
        cutoff = (_t.time() - days * 86400) if days > 0 else 0
        # Lọc ngày → lấy NHIỀU hơn (tới khi quá mốc) rồi mới cắt; most_liked vẫn cần pool để xếp like.
        pool_cap = limit if sort_mode == "newest" else max(limit, 120)
        if cutoff:
            pool_cap = max(pool_cap, 600)
        # "Cào KHÔNG TRÙNG" (đào sâu) cho KÊNH: bỏ video đã tải, gom trang tới khi đủ N video CHƯA tải.
        DEEP = os.environ.get("MC_DEEP_NEW", "0") == "1"
        seen = self._load_seen() if DEEP else set()
        try:
            DEEP_PAGE_CAP = int(os.environ.get("MC_DEEP_PAGE_CAP", "40") or 40)
        except ValueError:
            DEEP_PAGE_CAP = 40
        collected: List[Dict] = []
        max_cursor = ""
        has_more = 1
        pages = 0
        _empty = 0                                        # số trang RỖNG liên tiếp (khoảng-trống/风控 giữa danh sách)
        while has_more == 1:
            if DEEP:
                n_new = sum(1 for a in collected if a.get("aweme_id") not in seen)
                if n_new >= limit or pages >= DEEP_PAGE_CAP:
                    break
            elif len(collected) >= pool_cap:
                break
            _cursor_truoc = max_cursor
            res = await self.dy_client.get_user_aweme_posts(sec_user_id, max_cursor)
            pages += 1
            has_more = res.get("has_more", 0)
            max_cursor = res.get("max_cursor")
            lst = res.get("aweme_list") or []
            if not lst:
                # Douyin trả trang RỖNG nhưng has_more=1 + cursor VẪN TIẾN → "khoảng trống" giữa danh sách (KHÔNG
                # phải hết). ĐI TIẾP cursor MỚI để VƯỢT gap (đo thật: kênh 222 video có 2 trang rỗng ở giữa rồi
                # video trở lại). KHÔNG break ngay (bug cũ kẹt ở 14). Bỏ khi: has_more=0 / cursor kẹt / quá nhiều rỗng.
                _empty += 1
                if has_more == 1 and _empty <= 8 and max_cursor and max_cursor != _cursor_truoc:
                    utils.logger.info(f"[DouYinCrawler._collect_user_posts] trang {pages} RỖNG (gap {_empty}) "
                                      f"→ đi tiếp cursor {str(max_cursor)[:16]}")
                    await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
                    continue
                break
            _empty = 0
            collected.extend(lst)
            utils.logger.info(f"[DouYinCrawler._collect_user_posts] trang {pages}: +{len(lst)} video, "
                              f"has_more={has_more}, max_cursor={str(max_cursor)[:20]}, tổng={len(collected)}")
            # Posts trả theo MỚI NHẤT trước → gặp bài cũ hơn mốc thì các bài sau cũng cũ → DỪNG sớm.
            if cutoff and min((a.get("create_time", 0) or 0) for a in lst) < cutoff:
                break
            await asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)
        if cutoff:
            truoc = len(collected)
            collected = [a for a in collected if (a.get("create_time", 0) or 0) >= cutoff]
            utils.logger.info(f"[DouYinCrawler._collect_user_posts] lọc ngày {days}d: {truoc} → {len(collected)} video")
        if DEEP:   # bỏ video ĐÃ TẢI → chỉ giữ MỚI (đào sâu cho đủ N mới)
            truoc = len(collected)
            collected = [a for a in collected if a.get("aweme_id") not in seen]
            utils.logger.info(f"[DouYinCrawler._collect_user_posts] đào sâu (DEEP): {truoc} → {len(collected)} video CHƯA tải")
        if sort_mode == "most_liked":
            collected.sort(key=lambda a: (a.get("statistics", {}) or {}).get("digg_count", 0), reverse=True)
        return collected[:limit] if limit and limit > 0 else collected

    async def fetch_creator_video_detail(self, video_list: List[Dict]):
        """
        Concurrently obtain the specified post list and save the data
        """
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list = [self.get_aweme_detail(post_item.get("aweme_id"), semaphore) for post_item in video_list]

        note_details = await asyncio.gather(*task_list)
        for aweme_item in note_details:
            if aweme_item is not None:
                await douyin_store.update_douyin_aweme(aweme_item=aweme_item)
                self._tai_nen(self.get_aweme_media, aweme_item)   # tải NỀN song song (deep đã đếm ở _collect_user_posts)
        await self._drain_tai()

    async def create_douyin_client(self, httpx_proxy: Optional[str]) -> DouYinClient:
        """Create douyin client"""
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )  # type: ignore
        douyin_client = DouYinClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": await self.context_page.evaluate("() => navigator.userAgent"),
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return douyin_client

    def _create_douyin_client_no_browser(self, httpx_proxy: Optional[str]) -> DouYinClient:
        """Tạo DouYinClient KHÔNG mở browser: cookie giải mã trực tiếp từ profile Chromium (DPAPI v10 +
        AES-GCM) qua cookie_decrypt; ký a_bogus qua execjs (libs/douyin.js). Tránh fingerprint Playwright
        headless → douyin anti-bot không flag 'nhiều phiên lạ liên tiếp' khi cào nhiều (giống bili no-browser)."""
        import sys as _sys
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        import cookie_decrypt
        ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
        udd = os.path.join(
            os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(os.getcwd(), "browser_data"),
            config.USER_DATA_DIR % config.PLATFORM,
        )
        cookie_str = cookie_decrypt.cookie_header(udd, "douyin.com")
        cookie_dict = {}
        for _part in cookie_str.split("; "):
            if "=" in _part:
                _k, _v = _part.split("=", 1)
                cookie_dict[_k] = _v
        if cookie_str:
            utils.logger.info("[DouYinCrawler] no-browser: đọc %d cookie từ profile (httpx thuần, a_bogus execjs)" % len(cookie_dict))
        else:
            utils.logger.warning("[DouYinCrawler] no-browser: KHÔNG đọc được cookie douyin (chưa đăng nhập?)")
        return DouYinClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": ua,
                "Cookie": cookie_str,
                "Host": "www.douyin.com",
                "Origin": "https://www.douyin.com/",
                "Referer": "https://www.douyin.com/",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=None,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,
        )

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """Launch browser and create browser context"""
        if config.SAVE_LOGIN_STATE:
            user_data_dir = os.path.join(os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(os.getcwd(), "browser_data"), config.USER_DATA_DIR % config.PLATFORM)  # type: ignore
            browser_context = await chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                accept_downloads=True,
                headless=headless,
                proxy=playwright_proxy,  # type: ignore
                viewport={
                    "width": 1920,
                    "height": 1080
                },
                user_agent=user_agent,
            )  # type: ignore
            return browser_context
        else:
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy)  # type: ignore
            browser_context = await browser.new_context(viewport={"width": 1920, "height": 1080}, user_agent=user_agent)
            return browser_context

    async def launch_browser_with_cdp(
        self,
        playwright: Playwright,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        使用CDP模式启动浏览器
        """
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Add anti-detection script
            await self.cdp_manager.add_stealth_script()

            # Show browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[DouYinCrawler] CDP浏览器信息: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[DouYinCrawler] CDP模式启动失败，回退到标准模式: {e}")
            # Fall back to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def close(self) -> None:
        """Close browser context"""
        # If you use CDP mode, special processing is required
        if self.cdp_manager:
            await self.cdp_manager.cleanup()
            self.cdp_manager = None
        else:
            await self.browser_context.close()
        utils.logger.info("[DouYinCrawler.close] Browser context closed ...")

    async def get_aweme_media(self, aweme_item: Dict):
        """
        获取抖音媒体，自动判断媒体类型是短视频还是帖子图片并下载

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[DouYinCrawler.get_aweme_media] Crawling image mode is not enabled")
            return
        # List of note urls. If it is a short video type, an empty list will be returned.
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)
        # The video URL will always exist, but when it is a short video type, the file is actually an audio file.
        video_download_url: str = douyin_store._extract_video_download_url(aweme_item)
        # TODO: Douyin does not adopt the audio and video separation strategy, so the audio can be separated from the original video and will not be extracted for the time being.
        # ƯU TIÊN VIDEO: _extract_video_download_url trả "" cho post ẢNH thuần (không có video.play_addr),
        # nên có video_download_url = CHẮC CHẮN có video thật. Nếu check note-ảnh TRƯỚC, post vừa-video-vừa-kèm-ảnh
        # sẽ tải nhầm ẢNH -> render LỖI (preview _item_dy gắn "video" theo video_download_url -> hiện là video ->
        # user chọn -> tải ra ảnh). Check video_download_url trước cho KHỚP _item_dy.
        if video_download_url:
            await self.get_aweme_video(aweme_item)
        elif note_download_url:
            await self.get_aweme_images(aweme_item)

    async def get_aweme_images(self, aweme_item: Dict):
        """
        get aweme images. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")
        # List of note urls. If it is a short video type, an empty list will be returned.
        note_download_url: List[str] = douyin_store._extract_note_image_list(aweme_item)

        if not note_download_url:
            return
        sub_dir, file_base = _media_path_parts(aweme_item)
        img_sub_dir = f"{sub_dir}/{file_base}"  # mỗi bài ảnh 1 thư mục riêng
        picNum = 0
        for url in note_download_url:
            if not url:
                continue
            content = await self.dy_client.get_aweme_media(url)
            await asyncio.sleep(random.random())
            if content is None:
                continue
            extension_file_name = f"{picNum:>03d}.jpeg"
            picNum += 1
            await douyin_store.update_dy_aweme_image(aweme_id, content, extension_file_name, sub_dir=img_sub_dir)

    async def get_aweme_video(self, aweme_item: Dict):
        """
        get aweme videos. please use get_aweme_media

        Args:
            aweme_item (Dict): 抖音作品详情
        """
        if not config.ENABLE_GET_MEIDAS:
            return
        aweme_id = aweme_item.get("aweme_id")

        # Danh sách link tải dự phòng (nhiều CDN) — thử lần lượt nếu 1 link bị 403/lỗi
        url_candidates: List[str] = douyin_store._extract_video_download_url_list(aweme_item)
        if not url_candidates:
            one = douyin_store._extract_video_download_url(aweme_item)
            url_candidates = [one] if one else []
        if not url_candidates:
            return
        sub_dir, file_base = _media_path_parts(aweme_item)
        # Bỏ qua nếu đã tải rồi: theo SỔ LEDGER (id) hoặc file còn tồn tại.
        # Ledger giúp không tải lại kể cả khi video gốc đã bị xóa sau khi rerender.
        base_videos = f"{config.SAVE_DATA_PATH}/douyin/videos" if config.SAVE_DATA_PATH else "data/douyin/videos"
        target_dir = os.path.join(base_videos, *sub_dir.split("/"))
        da_co_file = aweme_id and glob.glob(os.path.join(target_dir, f"*_{aweme_id[-6:]}.mp4"))
        # "Cào đã chọn" (CRAWLER_TYPE=detail) = user CHỦ ĐỘNG chọn video -> CHỈ bỏ qua nếu file gốc CÒN tồn
        # tại; file đã bị xóa/rerender thì TẢI LẠI (đừng để sổ ledger chặn lựa chọn của user → "tải không
        # được" oan). Cào TỰ ĐỘNG (search/creator/userlist) vẫn dùng ledger để không ôm lại video cũ.
        la_chon_tay = getattr(config, "CRAWLER_TYPE", "") == "detail"
        da_bo_qua = bool(da_co_file) if la_chon_tay else (aweme_id in self._load_seen() or bool(da_co_file))
        if aweme_id and da_bo_qua:
            utils.logger.info(f"[DouYinCrawler.get_aweme_video] Đã tải trước đó, bỏ qua {aweme_id}")
            self._mark_seen(aweme_id)
            return
        content = None
        for i, url in enumerate(url_candidates):
            content = await self.dy_client.get_aweme_media(url)
            if content is not None:
                break
            utils.logger.info(f"[DouYinCrawler.get_aweme_video] link {i+1}/{len(url_candidates)} lỗi, thử link khác...")
            await asyncio.sleep(0.5)
        await asyncio.sleep(random.random())
        if content is None:
            utils.logger.error(f"[DouYinCrawler.get_aweme_video] Tải thất bại tất cả link cho {aweme_id} (sẽ thử lại lần sau)")
            return
        extension_file_name = f"{file_base}.mp4"
        await douyin_store.update_dy_aweme_video(aweme_id, content, extension_file_name, sub_dir=sub_dir)
        self._mark_seen(aweme_id)
        self._ghi_video_moi(aweme_item, sub_dir, file_base)
