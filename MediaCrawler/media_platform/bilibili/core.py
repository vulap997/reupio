# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/bilibili/core.py
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

# -*- coding: utf-8 -*-
# @Author  : relakkes@gmail.com
# @Time    : 2023/12/2 18:44
# @Desc    : Bilibili Crawler

import asyncio
import os
import random  # jitter NGẮN ngẫu nhiên giữa request bili (random tránh nhịp ĐỀU = dấu hiệu bot)
from asyncio import Task
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta
import pandas as pd

from playwright.async_api import (
    BrowserContext,
    BrowserType,
    Page,
    Playwright,
    async_playwright,
)
from playwright._impl._errors import TargetClosedError

import config
from base.base_crawler import AbstractCrawler
from proxy.proxy_ip_pool import IpInfoModel, create_ip_pool
from store import bilibili as bilibili_store
from tools import utils
from tools import dich_ten
from tools.cdp_browser import CDPBrowserManager
from var import crawler_type_var, source_keyword_var

from .client import BilibiliClient
from .exception import DataFetchError
from .field import SearchOrderType
from .help import parse_video_info_from_url, parse_creator_info_from_url
from .login import BilibiliLogin


def _ngu_sec() -> float:
    """Jitter NGẮN giữa request bili — KHÔNG còn 'cào từ từ' (gỡ theo yêu cầu; repo gốc NanmiCoder cũng không có).
    Bili no-browser API chịu được nhịp nhanh (burst 100 nav đã PASS); chỉ random NHẸ tránh nhịp ĐỀU tăm tắp
    (nhịp đều = dấu hiệu bot). Nếu sau này bị anti-bot/kill phiên thì NÂNG khoảng này lên."""
    return random.uniform(0.1, 0.4)


def _bili_safe_name(s, n=40):
    """Làm sạch tên cho đường dẫn file/thư mục (bỏ ký tự cấm Windows)."""
    import re as _re
    s = _re.sub(r'[<>:"/\\|?*\n\r\t]+', " ", str(s or "")).strip()
    s = _re.sub(r"\s+", " ", s)
    return (s[:n] or "khac").rstrip(". ")


def _bili_media_parts(video_item_view):
    """Trả (sub_dir, file_base) — CHIA thư mục lưu video bili theo từ-khoá/kênh GIỐNG Douyin:
    search -> tu-khoa/<kw>; creator -> kenh/<tên UP>; detail -> link.
    file_base = '<title>_<6 số cuối aid>' (độc nhất trong thư mục, nhiều video cùng từ khoá KHÔNG đè nhau)."""
    view = video_item_view if isinstance(video_item_view, dict) else {}
    aid = view.get("aid", "")
    # Tên file = tiêu đề ĐÃ DỊCH sang ngôn ngữ đích (không chỉ dịch trên màn hình)
    title = _bili_safe_name(dich_ten.dich_tieu_de(view.get("title", ""), "bili"), 50)
    file_base = f"{title}_{str(aid)[-6:]}" if aid else (title or "video")
    ctype = config.CRAWLER_TYPE
    if ctype == "search":
        sub_dir = f"tu-khoa/{_bili_safe_name(source_keyword_var.get() or 'khac', 40)}"
    elif ctype == "creator":
        owner = (view.get("owner", {}) or {}).get("name", "") or "khong-ro"
        sub_dir = f"kenh/{_bili_safe_name(owner, 40)}"
    else:
        sub_dir = "link"
    return sub_dir, file_base


def _search_to_video_item(sr):
    """SEARCH RESULT bili (1 item) -> cấu trúc video_item như get_video_info (để update_bilibili_video ghi jsonl).
    Dùng cho XEM-TRƯỚC: search result ĐÃ đủ title/cover/like/view/duration -> KHỎI detail-fetch (nhanh + NHIỀU,
    1 trang ~30 video tức thì). cid/playurl KHÔNG có ở đây -> chỉ để XEM; lúc TẢI mới fetch detail lấy cid."""
    import re as _re
    title = _re.sub(r"<[^>]+>", "", sr.get("title") or "")   # bỏ <em class="keyword">...</em>
    pic = sr.get("pic") or ""
    if pic.startswith("//"):
        pic = "https:" + pic
    return {
        "View": {
            "aid": sr.get("aid"),
            "title": title,
            "desc": sr.get("description") or "",
            "pubdate": sr.get("pubdate"),
            "pic": pic,
            "owner": {"mid": sr.get("mid", 0), "name": sr.get("author") or sr.get("uname") or "", "face": sr.get("upic", "")},
            "stat": {"like": sr.get("like", 0), "dislike": 0, "view": sr.get("play", 0),
                     "favorite": sr.get("favorites", 0), "share": 0, "coin": 0,
                     "danmaku": sr.get("danmaku", sr.get("video_review", 0)), "reply": sr.get("review", 0)},
        },
    }


class BilibiliCrawler(AbstractCrawler):
    context_page: Page
    bili_client: BilibiliClient
    browser_context: BrowserContext
    cdp_manager: Optional[CDPBrowserManager]

    def __init__(self):
        self.index_url = "https://www.bilibili.com"
        self.cookie_urls = [self.index_url]
        # UA CỐ ĐỊNH = UA lúc ĐĂNG NHẬP (mo_dang_nhap, Windows Chrome). bili ràng buộc phiên (SESSDATA)
        # theo User-Agent; get_user_agent() trả UA NGẪU NHIÊN khác UA login -> bili coi là phiên LẠ ->
        # VÔ HIỆU HÓA phiên = "cào 1 lần là bị đăng xuất". (xhs/core.py đã patch bỏ get_user_agent vì lý do này.)
        self.user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
        self.cdp_manager = None
        self.browser_context = None  # set ở browser-mode; GIỮ None ở no-browser để close() không AttributeError
        self.ip_proxy_pool = None  # Proxy IP pool for automatic proxy refresh
        self._dl_tasks = []    # tải video chạy NỀN (song song có giới hạn) — fetch/API VẪN tuần tự
        self._dl_sem = None    # asyncio.Semaphore(MC_DL_CONCURRENCY) — tạo lazy trong event loop
        self._seen_ids = None  # ledger ID đã tải (cào KHÔNG TRÙNG / đào sâu) — lazy load

    def _ledger_path(self) -> str:
        base = config.SAVE_DATA_PATH if config.SAVE_DATA_PATH else "data"
        return os.path.join(base, "bilibili", "_da_tai_ids.txt")

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

    def _mark_seen(self, vid: str):
        """Ghi ID video đã tải vào ledger (cào không trùng). Lỗi ghi KHÔNG làm hỏng việc tải."""
        if not vid:
            return
        self._load_seen().add(vid)
        p = self._ledger_path()
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(vid + "\n")
        except Exception:
            pass

    def _tai_nen(self, coro_fn, *a):
        """Lên lịch TẢI VIDEO chạy NỀN, giới hạn MC_DL_CONCURRENCY (mặc định 2). get_video_play_url vẫn qua
        semaphore(1) cũ → API tuần tự; chỉ get_video_media (tải bytes) chồng lấp = nhanh hơn, nhẹ anti-bot."""
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

    async def start(self):
        playwright_proxy_format, httpx_proxy_format = None, None
        if config.ENABLE_IP_PROXY:
            self.ip_proxy_pool = await create_ip_pool(config.IP_PROXY_POOL_COUNT, enable_validate_ip=True)
            ip_proxy_info: IpInfoModel = await self.ip_proxy_pool.get_proxy()
            playwright_proxy_format, httpx_proxy_format = utils.format_proxy_info(ip_proxy_info)

        # CHẾ ĐỘ API-ONLY (no-browser) — MẶC ĐỊNH BẬT cho bili: KHÔNG mở Playwright -> không có fingerprint
        # trình duyệt tự động -> bili KHÔNG vô hiệu hóa phiên login (hết "cào 1 lần bị đăng xuất").
        # Cookie giải mã trực tiếp từ profile Chromium (DPAPI v10 + AES-GCM), client httpx thuần, wbi qua
        # API nav. Áp cho CẢ xem-trước (metadata, nhanh) lẫn tải. Kill-switch: env BILI_NO_BROWSER=0 -> browser.
        if os.environ.get("BILI_NO_BROWSER", "1") != "0":
            utils.logger.info("[BilibiliCrawler] Chế độ API-ONLY (no-browser) — không mở trình duyệt")
            self.bili_client = self._create_client_no_browser(httpx_proxy_format)
            if not await self.bili_client.pong():
                utils.logger.error("[BilibiliCrawler] Đăng nhập bili không hợp lệ (cookie hết hạn / chưa đăng nhập) — KHÔNG cào được ở chế độ no-browser. Hãy đăng nhập lại bili.")
                return
            await self._run_crawler_type()
            return

        async with async_playwright() as playwright:
            # Choose launch mode based on configuration
            if config.ENABLE_CDP_MODE:
                utils.logger.info("[BilibiliCrawler] Launching browser using CDP mode")
                self.browser_context = await self.launch_browser_with_cdp(
                    playwright,
                    playwright_proxy_format,
                    self.user_agent,
                    headless=config.CDP_HEADLESS,
                )
            else:
                utils.logger.info("[BilibiliCrawler] Launching browser using standard mode")
                # Launch a browser context.
                chromium = playwright.chromium
                self.browser_context = await self.launch_browser(chromium, None, self.user_agent, headless=config.HEADLESS)
                # stealth.min.js is a js script to prevent the website from detecting the crawler.
                await self.browser_context.add_init_script(path="libs/stealth.min.js")

            self.context_page = await self.browser_context.new_page()
            # Trang chủ bilibili.com NẶNG + mạng tới bilibili có lúc CHẬM -> kể cả "domcontentloaded" vẫn
            # timeout 30s; mà goto KHÔNG bọc try/except -> "Page.goto Timeout 30000ms" GIẾT cả crawl
            # ("bilibili không cào được"). Fix: "commit" (fire NGAY khi nhận response headers — đã đủ set
            # cookie buvid3; wbi key lấy qua API nav chứ không cần DOM) + BỌC try/except để goto chậm/lỗi
            # KHÔNG giết crawl (cookie sẵn trên profile + API vẫn cào được). Đồng bộ douyin/core.py.
            try:
                await self.context_page.goto(self.index_url, wait_until="commit", timeout=45000)
            except Exception as e:
                utils.logger.warning(f"[BilibiliCrawler] goto trang chủ bỏ qua (timeout/lỗi): {e}")

            # Create a client to interact with the xiaohongshu website.
            self.bili_client = await self.create_bilibili_client(httpx_proxy_format)
            if not await self.bili_client.pong():
                login_obj = BilibiliLogin(
                    login_type=config.LOGIN_TYPE,
                    login_phone="",  # your phone number
                    browser_context=self.browser_context,
                    context_page=self.context_page,
                    cookie_str=config.COOKIES,
                )
                await login_obj.begin()
                await self.bili_client.update_cookies(
                    browser_context=self.browser_context,
                    urls=self.cookie_urls,
                )

            await self._run_crawler_type()

    async def _run_crawler_type(self):
        """Dispatch theo CRAWLER_TYPE — dùng CHUNG cho cả chế độ browser lẫn no-browser."""
        crawler_type_var.set(config.CRAWLER_TYPE)
        if config.CRAWLER_TYPE == "search":
            await self.search()
        elif config.CRAWLER_TYPE == "detail":
            await self.get_specified_videos(config.BILI_SPECIFIED_ID_LIST)
        elif config.CRAWLER_TYPE == "creator":
            if config.CREATOR_MODE:
                for creator_url in config.BILI_CREATOR_ID_LIST:
                    try:
                        creator_info = parse_creator_info_from_url(creator_url)
                        utils.logger.info(f"[BilibiliCrawler._run_crawler_type] Parsed creator ID: {creator_info.creator_id} from {creator_url}")
                        await self.get_creator_videos(int(creator_info.creator_id))
                    except ValueError as e:
                        utils.logger.error(f"[BilibiliCrawler._run_crawler_type] Failed to parse creator URL: {e}")
                        continue
            else:
                await self.get_all_creator_details(config.BILI_CREATOR_ID_LIST)
        else:
            pass
        utils.logger.info("[BilibiliCrawler.start] Bilibili Crawler finished ...")

    def _create_client_no_browser(self, httpx_proxy: Optional[str]) -> BilibiliClient:
        """Tạo BilibiliClient KHÔNG mở browser: cookie giải mã trực tiếp từ profile Chromium
        (DPAPI v10 + AES-GCM) qua cookie_decrypt. Tránh fingerprint Playwright headless."""
        import sys as _sys
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        import cookie_decrypt
        udd = os.path.join(
            os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(os.getcwd(), "browser_data"),
            config.USER_DATA_DIR % config.PLATFORM,
        )
        cookie_str = cookie_decrypt.cookie_header(udd, "bilibili.com")
        cookie_dict = {}
        for _part in cookie_str.split("; "):
            if "=" in _part:
                _k, _v = _part.split("=", 1)
                cookie_dict[_k] = _v
        if cookie_str:
            utils.logger.info("[BilibiliCrawler] no-browser: đọc %d cookie từ profile (httpx thuần)" % len(cookie_dict))
        else:
            utils.logger.warning("[BilibiliCrawler] no-browser: KHÔNG đọc được cookie bili (chưa đăng nhập?)")
        return BilibiliClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": self.user_agent,
                "Cookie": cookie_str,
                "Origin": "https://www.bilibili.com",
                "Referer": "https://www.bilibili.com",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=None,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,
        )

    async def search(self):
        """
        search bilibili video
        """
        # Search for video and retrieve their comment information.
        if config.BILI_SEARCH_MODE == "normal":
            await self.search_by_keywords()
        elif config.BILI_SEARCH_MODE == "all_in_time_range":
            await self.search_by_keywords_in_time_range(daily_limit=False)
        elif config.BILI_SEARCH_MODE == "daily_limit_in_time_range":
            await self.search_by_keywords_in_time_range(daily_limit=True)
        else:
            utils.logger.warning(f"Unknown BILI_SEARCH_MODE: {config.BILI_SEARCH_MODE}")

    @staticmethod
    async def get_pubtime_datetime(
        start: str = config.START_DAY,
        end: str = config.END_DAY,
    ) -> Tuple[str, str]:
        """
        Get bilibili publish start timestamp pubtime_begin_s and publish end timestamp pubtime_end_s
        ---
        :param start: Publish date start time, YYYY-MM-DD
        :param end: Publish date end time, YYYY-MM-DD

        Note
        ---
        - Search time range is from start to end, including both start and end
        - To search content from the same day, to include search content from that day, pubtime_end_s should be pubtime_begin_s plus one day minus one second, i.e., the last second of start day
            - For example, searching only 2024-01-05 content, pubtime_begin_s = 1704384000, pubtime_end_s = 1704470399
              Converted to readable datetime objects: pubtime_begin_s = datetime.datetime(2024, 1, 5, 0, 0), pubtime_end_s = datetime.datetime(2024, 1, 5, 23, 59, 59)
        - To search content from start to end, to include search content from end day, pubtime_end_s should be pubtime_end_s plus one day minus one second, i.e., the last second of end day
            - For example, searching 2024-01-05 - 2024-01-06 content, pubtime_begin_s = 1704384000, pubtime_end_s = 1704556799
              Converted to readable datetime objects: pubtime_begin_s = datetime.datetime(2024, 1, 5, 0, 0), pubtime_end_s = datetime.datetime(2024, 1, 6, 23, 59, 59)
        """
        # Convert start and end to datetime objects
        start_day: datetime = datetime.strptime(start, "%Y-%m-%d")
        end_day: datetime = datetime.strptime(end, "%Y-%m-%d")
        if start_day > end_day:
            raise ValueError("Wrong time range, please check your start and end argument, to ensure that the start cannot exceed end")
        elif start_day == end_day:  # Searching content from the same day
            end_day = (start_day + timedelta(days=1) - timedelta(seconds=1))  # Set end_day to start_day + 1 day - 1 second
        else:  # Searching from start to end
            end_day = (end_day + timedelta(days=1) - timedelta(seconds=1))  # Set end_day to end_day + 1 day - 1 second
        # Convert back to timestamps
        return str(int(start_day.timestamp())), str(int(end_day.timestamp()))

    async def search_by_keywords(self):
        """
        search bilibili video with keywords in normal mode
        :return:
        """
        utils.logger.info("[BilibiliCrawler.search_by_keywords] Begin search bilibli keywords")
        bili_limit_count = 20  # bilibili limit page fixed value
        user_max = config.CRAWLER_MAX_NOTES_COUNT  # GIỮ count GỐC user (override dưới chỉ để vòng while chạy ≥1 trang)
        if not config.ENABLE_GET_MEIDAS:
            # XEM-TRƯỚC: cho xem NHIỀU để chọn (search result RẺ, không detail-fetch) -> nâng cap ≥60 (3 trang).
            # Tải TỪ TỪ từng trang (per-page sleep dưới) -> user thấy thêm dần. Pick rồi mới tải video thật.
            user_max = max(user_max, 60)
            config.CRAWLER_MAX_NOTES_COUNT = max(config.CRAWLER_MAX_NOTES_COUNT, 60)
        elif config.CRAWLER_MAX_NOTES_COUNT < bili_limit_count:
            config.CRAWLER_MAX_NOTES_COUNT = bili_limit_count
        start_page = config.START_PAGE  # start page number
        # "Cào KHÔNG TRÙNG" (đào sâu): MC_DEEP_NEW=1 → bỏ video ĐÃ tải, đào trang SÂU tới khi đủ N video MỚI
        # (trần MC_DEEP_PAGE_CAP=40) thay vì dừng theo count. Gate: DEEP off (mặc định) = hành vi CŨ y nguyên.
        DEEP = os.environ.get("MC_DEEP_NEW", "0") == "1"
        try:
            DEEP_PAGE_CAP = int(os.environ.get("MC_DEEP_PAGE_CAP", "40") or 40)
        except (TypeError, ValueError):
            DEEP_PAGE_CAP = 40
        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[BilibiliCrawler.search_by_keywords] Current search keyword: {keyword}")
            page = 1
            crawled = 0  # số video ĐÃ tải cho keyword này — giới hạn theo user_max (khỏi tải cả trang 20)
            while ((page - start_page + 1) * bili_limit_count <= config.CRAWLER_MAX_NOTES_COUNT) \
                    or (DEEP and (page - start_page) < DEEP_PAGE_CAP):
                if page < start_page:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] Skip page: {page}")
                    page += 1
                    continue

                utils.logger.info(f"[BilibiliCrawler.search_by_keywords] search bilibili keyword: {keyword}, page: {page}")
                video_id_list: List[str] = []
                videos_res = await self.bili_client.search_video_by_keyword(
                    keyword=keyword,
                    page=page,
                    page_size=bili_limit_count,
                    order=SearchOrderType.DEFAULT,
                    pubtime_begin_s=0,  # Publish date start timestamp
                    pubtime_end_s=0,  # Publish date end timestamp
                )
                video_list: List[Dict] = videos_res.get("result")

                if not video_list:
                    utils.logger.info(f"[BilibiliCrawler.search_by_keywords] No more videos for '{keyword}', moving to next keyword.")
                    break

                # XEM-TRƯỚC (MC_GET_MEDIAS=0): search result ĐÃ đủ title/cover/like/view/duration -> ghi THẲNG
                # CẢ TRANG (~30 video) TỨC THÌ + từng cái (jsonl tăng dần -> preview hiện dần), KHÔNG detail-fetch
                # (chậm + ít). cid chỉ cần lúc TẢI -> chỉ download mode (dưới) mới fetch detail.
                if not config.ENABLE_GET_MEIDAS:
                    for sr in video_list:
                        if not sr.get("aid"):
                            continue
                        await bilibili_store.update_bilibili_video(_search_to_video_item(sr))
                        crawled += 1
                    if crawled >= user_max:
                        break
                    page += 1
                    await asyncio.sleep(_ngu_sec())
                    continue

                # GIỚI HẠN theo count USER: bilibili trả NGUYÊN trang 20 -> trước đây fetch-detail (sleep 2s/cái)
                # + TẢI HẾT trang dù user xin ít -> cào RẤT CHẬM (như treo). Chỉ xử lý số CÒN THIẾU.
                # Cào KHÔNG TRÙNG: bỏ video ĐÃ tải (theo aid) TRƯỚC fetch-detail/tải → chỉ tốn cho video MỚI.
                if DEEP:
                    _seen = self._load_seen()
                    _truoc = len(video_list)
                    video_list = [sr for sr in video_list if str(sr.get("aid")) not in _seen]
                    if _truoc != len(video_list):
                        utils.logger.info(f"[BilibiliCrawler.search_by_keywords] đào sâu: bỏ {_truoc - len(video_list)} video đã tải, còn {len(video_list)} mới (trang {page})")
                video_list = video_list[: max(user_max - crawled, 0)]
                utils.logger.info(f"[BilibiliCrawler.search_by_keywords] count: user_max={user_max} crawled={crawled} -> lấy chi tiết {len(video_list)} video (trang bili {bili_limit_count}). NHIỀU detail/lần = burst -> bili dễ vô hiệu phiên.")
                if not video_list:
                    if DEEP and (page - start_page) < DEEP_PAGE_CAP:   # trang toàn video đã tải → sang trang sau (đào sâu)
                        page += 1
                        await asyncio.sleep(_ngu_sec())
                        continue
                    break

                semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                task_list = []
                try:
                    task_list = [self.get_video_info_task(aid=video_item.get("aid"), bvid="", semaphore=semaphore) for video_item in video_list]
                except Exception as e:
                    utils.logger.warning(f"[BilibiliCrawler.search_by_keywords] error in the task list. The video for this page will not be included. {e}")
                video_items = await asyncio.gather(*task_list)
                for video_item in video_items:
                    if video_item:
                        video_id_list.append(video_item.get("View").get("aid"))
                        await bilibili_store.update_bilibili_video(video_item)
                        await bilibili_store.update_up_info(video_item)
                        self._tai_nen(self.get_bilibili_video, video_item, semaphore)   # tải NỀN song song
                        crawled += 1
                if crawled >= user_max:  # đủ số user xin -> dừng, khỏi sang trang sau
                    break
                page += 1

                # Sleep after page navigation
                await asyncio.sleep(_ngu_sec())
                utils.logger.info(f"[BilibiliCrawler.search_by_keywords] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                await self._drain_tai()   # đợi tải nền của trang xong
                await self.batch_get_video_comments(video_id_list)

    async def search_by_keywords_in_time_range(self, daily_limit: bool):
        """
        Search bilibili video with keywords in a given time range.
        :param daily_limit: if True, strictly limit the number of notes per day and total.
        """
        utils.logger.info(f"[BilibiliCrawler.search_by_keywords_in_time_range] Begin search with daily_limit={daily_limit}")
        bili_limit_count = 20
        start_page = config.START_PAGE

        for keyword in config.KEYWORDS.split(","):
            source_keyword_var.set(keyword)
            utils.logger.info(f"[BilibiliCrawler.search_by_keywords_in_time_range] Current search keyword: {keyword}")
            total_notes_crawled_for_keyword = 0

            for day in pd.date_range(start=config.START_DAY, end=config.END_DAY, freq="D"):
                if (daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                    utils.logger.info(f"[BilibiliCrawler.search] Reached CRAWLER_MAX_NOTES_COUNT limit for keyword '{keyword}', skipping remaining days.")
                    break

                if (not daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                    utils.logger.info(f"[BilibiliCrawler.search] Reached CRAWLER_MAX_NOTES_COUNT limit for keyword '{keyword}', skipping remaining days.")
                    break

                pubtime_begin_s, pubtime_end_s = await self.get_pubtime_datetime(start=day.strftime("%Y-%m-%d"), end=day.strftime("%Y-%m-%d"))
                page = 1
                notes_count_this_day = 0

                while True:
                    if notes_count_this_day >= config.MAX_NOTES_PER_DAY:
                        utils.logger.info(f"[BilibiliCrawler.search] Reached MAX_NOTES_PER_DAY limit for {day.ctime()}.")
                        break
                    if (daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                        utils.logger.info(f"[BilibiliCrawler.search] Reached CRAWLER_MAX_NOTES_COUNT limit for keyword '{keyword}'.")
                        break
                    if (not daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                        break

                    try:
                        utils.logger.info(f"[BilibiliCrawler.search] search bilibili keyword: {keyword}, date: {day.ctime()}, page: {page}")
                        video_id_list: List[str] = []
                        videos_res = await self.bili_client.search_video_by_keyword(
                            keyword=keyword,
                            page=page,
                            page_size=bili_limit_count,
                            order=SearchOrderType.DEFAULT,
                            pubtime_begin_s=pubtime_begin_s,
                            pubtime_end_s=pubtime_end_s,
                        )
                        video_list: List[Dict] = videos_res.get("result")

                        if not video_list:
                            utils.logger.info(f"[BilibiliCrawler.search] No more videos for '{keyword}' on {day.ctime()}, moving to next day.")
                            break

                        # GIỚI HẠN số video LẤY CHI TIẾT theo count còn thiếu (khớp search_by_keywords normal):
                        # bản gốc gather CẢ trang 20 detail trước khi mới break ở vòng dưới -> BURST request
                        # -> bili anti-crawler vô hiệu hóa phiên = "cào 1 lần bị đăng xuất". Chỉ lấy số CÒN THIẾU.
                        con_lai = config.CRAWLER_MAX_NOTES_COUNT - total_notes_crawled_for_keyword
                        if con_lai <= 0:
                            break
                        video_list = video_list[:con_lai]
                        utils.logger.info(f"[BilibiliCrawler.search_by_keywords_in_time_range] count còn thiếu={con_lai} -> lấy chi tiết {len(video_list)} video (trang bili {bili_limit_count}).")

                        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
                        task_list = [self.get_video_info_task(aid=video_item.get("aid"), bvid="", semaphore=semaphore) for video_item in video_list]
                        video_items = await asyncio.gather(*task_list)

                        for video_item in video_items:
                            if video_item:
                                if (daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                                    break
                                if (not daily_limit and total_notes_crawled_for_keyword >= config.CRAWLER_MAX_NOTES_COUNT):
                                    break
                                if notes_count_this_day >= config.MAX_NOTES_PER_DAY:
                                    break
                                notes_count_this_day += 1
                                total_notes_crawled_for_keyword += 1
                                video_id_list.append(video_item.get("View").get("aid"))
                                await bilibili_store.update_bilibili_video(video_item)
                                await bilibili_store.update_up_info(video_item)
                                self._tai_nen(self.get_bilibili_video, video_item, semaphore)   # tải NỀN song song

                        page += 1

                        # Sleep after page navigation
                        await asyncio.sleep(_ngu_sec())
                        utils.logger.info(f"[BilibiliCrawler.search_by_keywords_in_time_range] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {page-1}")

                        await self._drain_tai()   # đợi tải nền của trang xong
                        await self.batch_get_video_comments(video_id_list)

                    except Exception as e:
                        utils.logger.error(f"[BilibiliCrawler.search] Error searching on {day.ctime()}: {e}")
                        break

    async def batch_get_video_comments(self, video_id_list: List[str]):
        """
        batch get video comments
        :param video_id_list:
        :return:
        """
        if not config.ENABLE_GET_COMMENTS:
            utils.logger.info(f"[BilibiliCrawler.batch_get_note_comments] Crawling comment mode is not enabled")
            return

        utils.logger.info(f"[BilibiliCrawler.batch_get_video_comments] video ids:{video_id_list}")
        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        for video_id in video_id_list:
            task = asyncio.create_task(self.get_comments(video_id, semaphore), name=video_id)
            task_list.append(task)
        await asyncio.gather(*task_list)

    async def get_comments(self, video_id: str, semaphore: asyncio.Semaphore):
        """
        get comment for video id
        :param video_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_comments] begin get video_id: {video_id} comments ...")
                await asyncio.sleep(_ngu_sec())
                utils.logger.info(f"[BilibiliCrawler.get_comments] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching comments for video {video_id}")
                await self.bili_client.get_video_all_comments(
                    video_id=video_id,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    is_fetch_sub_comments=config.ENABLE_GET_SUB_COMMENTS,
                    callback=bilibili_store.batch_update_bilibili_video_comments,
                    max_count=config.CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_comments] get video_id: {video_id} comment error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_comments] may be been blocked, err:{e}")
                # Propagate the exception to be caught by the main loop
                raise

    async def get_creator_videos(self, creator_id: int):
        """
        get videos for a creator
        :return:
        """
        ps = 30
        pn = 1
        while True:
            result = await self.bili_client.get_creator_videos(creator_id, pn, ps)
            video_bvids_list = [video["bvid"] for video in result["list"]["vlist"]]
            await self.get_specified_videos(video_bvids_list)
            if int(result["page"]["count"]) <= pn * ps:
                break
            await asyncio.sleep(_ngu_sec())
            utils.logger.info(f"[BilibiliCrawler.get_creator_videos] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after page {pn}")
            pn += 1

    async def get_specified_videos(self, video_url_list: List[str]):
        """
        get specified videos info from URLs or BV IDs
        :param video_url_list: List of video URLs or BV IDs
        :return:
        """
        utils.logger.info("[BilibiliCrawler.get_specified_videos] Parsing video URLs...")
        bvids_list = []
        for video_url in video_url_list:
            try:
                video_info = parse_video_info_from_url(video_url)
                bvids_list.append(video_info.video_id)
                utils.logger.info(f"[BilibiliCrawler.get_specified_videos] Parsed video ID: {video_info.video_id} from {video_url}")
            except ValueError as e:
                utils.logger.error(f"[BilibiliCrawler.get_specified_videos] Failed to parse video URL: {e}")
                continue

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        # bvids_list có thể chứa 'av<aid>' (URL search bilibili chỉ có aid, không có bvid) -> route sang
        # tham số aid; còn 'BV...' -> bvid. (get_video_info nhận aid HOẶC bvid.) Trước đây luôn truyền bvid
        # -> av-id sai định dạng bvid -> 0 video detail -> "Cào video đã chọn" tải 0.
        task_list = []
        for vid in bvids_list:
            if str(vid).startswith("av") and str(vid)[2:].isdigit():
                task_list.append(self.get_video_info_task(aid=int(str(vid)[2:]), bvid="", semaphore=semaphore))
            else:
                task_list.append(self.get_video_info_task(aid=0, bvid=vid, semaphore=semaphore))
        video_details = await asyncio.gather(*task_list)
        video_aids_list = []
        for video_detail in video_details:
            if video_detail is not None:
                video_item_view: Dict = video_detail.get("View")
                video_aid: str = video_item_view.get("aid")
                if video_aid:
                    video_aids_list.append(video_aid)
                await bilibili_store.update_bilibili_video(video_detail)
                await bilibili_store.update_up_info(video_detail)
                self._tai_nen(self.get_bilibili_video, video_detail, semaphore)   # tải NỀN song song
        await self._drain_tai()
        await self.batch_get_video_comments(video_aids_list)

    async def get_video_info_task(self, aid: int, bvid: str, semaphore: asyncio.Semaphore) -> Optional[Dict]:
        """
        Get video detail task
        :param aid:
        :param bvid:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                result = await self.bili_client.get_video_info(aid=aid, bvid=bvid)

                # Sleep after fetching video details
                await asyncio.sleep(_ngu_sec())
                utils.logger.info(f"[BilibiliCrawler.get_video_info_task] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video details {bvid or aid}")

                return result
            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] Get video detail error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_info_task] have not fund note detail video_id:{bvid}, err: {ex}")
                return None

    async def get_video_play_url_task(self, aid: int, cid: int, semaphore: asyncio.Semaphore) -> Union[Dict, None]:
        """
        Get video play url
        :param aid:
        :param cid:
        :param semaphore:
        :return:
        """
        async with semaphore:
            try:
                result = await self.bili_client.get_video_play_url(aid=aid, cid=cid)
                return result
            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_play_url_task] Get video play url error: {ex}")
                return None
            except KeyError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_video_play_url_task] have not fund play url from :{aid}|{cid}, err: {ex}")
                return None

    async def create_bilibili_client(self, httpx_proxy: Optional[str]) -> BilibiliClient:
        """
        create bilibili client
        :param httpx_proxy: httpx proxy
        :return: bilibili client
        """
        utils.logger.info("[BilibiliCrawler.create_bilibili_client] Begin create bilibili API client ...")
        cookie_str, cookie_dict = await utils.convert_browser_context_cookies(
            self.browser_context,
            urls=self.cookie_urls,
        )
        bilibili_client_obj = BilibiliClient(
            proxy=httpx_proxy,
            headers={
                "User-Agent": self.user_agent,
                "Cookie": cookie_str,
                "Origin": "https://www.bilibili.com",
                "Referer": "https://www.bilibili.com",
                "Content-Type": "application/json;charset=UTF-8",
            },
            playwright_page=self.context_page,
            cookie_dict=cookie_dict,
            proxy_ip_pool=self.ip_proxy_pool,  # Pass proxy pool for automatic refresh
        )
        return bilibili_client_obj

    async def launch_browser(
        self,
        chromium: BrowserType,
        playwright_proxy: Optional[Dict],
        user_agent: Optional[str],
        headless: bool = True,
    ) -> BrowserContext:
        """
        launch browser and create browser context
        :param chromium: chromium browser
        :param playwright_proxy: playwright proxy
        :param user_agent: user agent
        :param headless: headless mode
        :return: browser context
        """
        utils.logger.info("[BilibiliCrawler.launch_browser] Begin create browser context ...")
        if config.SAVE_LOGIN_STATE:
            # feat issue #14
            # we will save login state to avoid login every time
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
                channel="chrome",  # Use system's stable Chrome version
            )
            return browser_context
        else:
            # type: ignore
            browser = await chromium.launch(headless=headless, proxy=playwright_proxy, channel="chrome")
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
        Launch browser using CDP mode
        """
        try:
            self.cdp_manager = CDPBrowserManager()
            browser_context = await self.cdp_manager.launch_and_connect(
                playwright=playwright,
                playwright_proxy=playwright_proxy,
                user_agent=user_agent,
                headless=headless,
            )

            # Display browser information
            browser_info = await self.cdp_manager.get_browser_info()
            utils.logger.info(f"[BilibiliCrawler] CDP browser info: {browser_info}")

            return browser_context

        except Exception as e:
            utils.logger.error(f"[BilibiliCrawler] CDP mode launch failed, fallback to standard mode: {e}")
            # Fallback to standard mode
            chromium = playwright.chromium
            return await self.launch_browser(chromium, playwright_proxy, user_agent, headless)

    async def close(self):
        """Close browser context"""
        try:
            # If using CDP mode, special handling is required
            if self.cdp_manager:
                await self.cdp_manager.cleanup()
                self.cdp_manager = None
            elif self.browser_context:
                await self.browser_context.close()
            utils.logger.info("[BilibiliCrawler.close] Browser context closed ...")
        except TargetClosedError:
            utils.logger.warning("[BilibiliCrawler.close] Browser context was already closed.")
        except Exception as e:
            utils.logger.error(f"[BilibiliCrawler.close] An error occurred during close: {e}")

    async def get_bilibili_video(self, video_item: Dict, semaphore: asyncio.Semaphore):
        """
        download bilibili video
        :param video_item:
        :param semaphore:
        :return:
        """
        if not config.ENABLE_GET_MEIDAS:
            utils.logger.info(f"[BilibiliCrawler.get_bilibili_video] Crawling image mode is not enabled")
            return
        video_item_view: Dict = video_item.get("View")
        aid = video_item_view.get("aid")
        cid = video_item_view.get("cid")
        result = await self.get_video_play_url_task(aid, cid, semaphore)
        if result is None:
            utils.logger.info("[BilibiliCrawler.get_bilibili_video] get video play url failed")
            return
        durl_list = result.get("durl")
        max_size = -1
        video_url = ""
        for durl in durl_list:
            size = durl.get("size")
            if size > max_size:
                max_size = size
                video_url = durl.get("url")
        if video_url == "":
            utils.logger.info("[BilibiliCrawler.get_bilibili_video] get video url failed")
            return

        content = await self.bili_client.get_video_media(video_url)
        await asyncio.sleep(_ngu_sec())
        utils.logger.info(f"[BilibiliCrawler.get_bilibili_video] Sleeping for {config.CRAWLER_MAX_SLEEP_SEC} seconds after fetching video {aid}")
        if content is None:
            return
        sub_dir, file_base = _bili_media_parts(video_item_view)
        extension_file_name = f"{file_base}.mp4"
        await bilibili_store.store_video(aid, content, extension_file_name, sub_dir=sub_dir)
        # Ledger "đã tải" (cào KHÔNG TRÙNG / đào sâu) — ghi cả aid lẫn bvid để đào-sâu + badge nhận diện.
        self._mark_seen(str(aid))
        _bv = video_item_view.get("bvid")
        if _bv:
            self._mark_seen(str(_bv))

    async def get_all_creator_details(self, creator_url_list: List[str]):
        """
        creator_url_list: get details for creator from creator URL list
        """
        utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] Crawling the details of creators")
        utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] Parsing creator URLs...")

        creator_id_list = []
        for creator_url in creator_url_list:
            try:
                creator_info = parse_creator_info_from_url(creator_url)
                creator_id_list.append(int(creator_info.creator_id))
                utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] Parsed creator ID: {creator_info.creator_id} from {creator_url}")
            except ValueError as e:
                utils.logger.error(f"[BilibiliCrawler.get_all_creator_details] Failed to parse creator URL: {e}")
                continue

        utils.logger.info(f"[BilibiliCrawler.get_all_creator_details] creator ids:{creator_id_list}")

        semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY_NUM)
        task_list: List[Task] = []
        try:
            for creator_id in creator_id_list:
                task = asyncio.create_task(self.get_creator_details(creator_id, semaphore), name=str(creator_id))
                task_list.append(task)
        except Exception as e:
            utils.logger.warning(f"[BilibiliCrawler.get_all_creator_details] error in the task list. The creator will not be included. {e}")

        await asyncio.gather(*task_list)

    async def get_creator_details(self, creator_id: int, semaphore: asyncio.Semaphore):
        """
        get details for creator id
        :param creator_id:
        :param semaphore:
        :return:
        """
        async with semaphore:
            creator_unhandled_info: Dict = await self.bili_client.get_creator_info(creator_id)
            creator_info: Dict = {
                "id": creator_id,
                "name": creator_unhandled_info.get("name"),
                "sign": creator_unhandled_info.get("sign"),
                "avatar": creator_unhandled_info.get("face"),
            }
        await self.get_fans(creator_info, semaphore)
        await self.get_followings(creator_info, semaphore)
        await self.get_dynamics(creator_info, semaphore)

    async def get_fans(self, creator_info: Dict, semaphore: asyncio.Semaphore):
        """
        get fans for creator id
        :param creator_info:
        :param semaphore:
        :return:
        """
        creator_id = creator_info["id"]
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_fans] begin get creator_id: {creator_id} fans ...")
                await self.bili_client.get_creator_all_fans(
                    creator_info=creator_info,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=bilibili_store.batch_update_bilibili_creator_fans,
                    max_count=config.CRAWLER_MAX_CONTACTS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_fans] get creator_id: {creator_id} fans error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_fans] may be been blocked, err:{e}")

    async def get_followings(self, creator_info: Dict, semaphore: asyncio.Semaphore):
        """
        get followings for creator id
        :param creator_info:
        :param semaphore:
        :return:
        """
        creator_id = creator_info["id"]
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_followings] begin get creator_id: {creator_id} followings ...")
                await self.bili_client.get_creator_all_followings(
                    creator_info=creator_info,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=bilibili_store.batch_update_bilibili_creator_followings,
                    max_count=config.CRAWLER_MAX_CONTACTS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_followings] get creator_id: {creator_id} followings error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_followings] may be been blocked, err:{e}")

    async def get_dynamics(self, creator_info: Dict, semaphore: asyncio.Semaphore):
        """
        get dynamics for creator id
        :param creator_info:
        :param semaphore:
        :return:
        """
        creator_id = creator_info["id"]
        async with semaphore:
            try:
                utils.logger.info(f"[BilibiliCrawler.get_dynamics] begin get creator_id: {creator_id} dynamics ...")
                await self.bili_client.get_creator_all_dynamics(
                    creator_info=creator_info,
                    crawl_interval=config.CRAWLER_MAX_SLEEP_SEC,
                    callback=bilibili_store.batch_update_bilibili_creator_dynamics,
                    max_count=config.CRAWLER_MAX_DYNAMICS_COUNT_SINGLENOTES,
                )

            except DataFetchError as ex:
                utils.logger.error(f"[BilibiliCrawler.get_dynamics] get creator_id: {creator_id} dynamics error: {ex}")
            except Exception as e:
                utils.logger.error(f"[BilibiliCrawler.get_dynamics] may be been blocked, err:{e}")
