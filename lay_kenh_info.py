# -*- coding: utf-8 -*-
"""Lấy NHANH thông tin 1 kênh (nickname + avatar + fans) từ LINK → cho 'Theo dõi kênh' hiện tên+avatar khi dán link
(không cần qua 'Gợi ý kênh'). In 1 dòng JSON: {"nickname","avatar","fans"} (rỗng {} nếu không lấy được/nền tảng chưa hỗ trợ).
Dùng: python lay_kenh_info.py "<link kênh>"  (env MC_BROWSER_DATA_DIR = profile có cookie đăng nhập)."""
import os, sys, json, asyncio
from urllib.parse import urlparse

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))


def _la_host_douyin(link):
    """Chỉ nhận link có HOSTNAME thật thuộc douyin (chống SSRF: trước đây so substring 'douyin.com' in link
    → http://evil.com/?x=douyin.com cũng lọt → fetch host tuỳ ý). So theo hostname chuẩn."""
    try:
        h = (urlparse(link).hostname or "").lower()
    except Exception:
        return False
    return h == "douyin.com" or h.endswith(".douyin.com") or h == "iesdouyin.com" or h.endswith(".iesdouyin.com")


def _douyin_info(link):
    mc = os.path.join(THU_MUC_GOC, "MediaCrawler")
    sys.path.insert(0, mc)
    os.chdir(mc)   # ký a_bogus đọc 'libs/douyin.js' theo CWD → phải đứng ở MediaCrawler
    from media_platform.douyin.core import DouYinCrawler
    from media_platform.douyin.help import parse_creator_info_from_url

    async def _f():
        c = DouYinCrawler()
        c.ip_proxy_pool = None
        cl = c._create_douyin_client_no_browser(None)
        sec = parse_creator_info_from_url(link).sec_user_id
        resp = await cl.get_user_info(sec)
        u = (resp or {}).get("user", {}) or {}
        av_uri = ((u.get("avatar_300x300") or {}).get("uri")
                  or (u.get("avatar_168x168") or {}).get("uri"))
        avatar = (("https://p3-pc.douyinpic.com/img/%s~c5_300x300.jpeg?from=2956013662" % av_uri) if av_uri
                  else ((u.get("avatar_thumb") or {}).get("url_list", [""]) or [""])[0])
        return {"nickname": u.get("nickname", "") or "", "avatar": avatar or "",
                "fans": u.get("max_follower_count", 0) or 0}
    return asyncio.run(_f())


def main():
    link = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    info = {}
    try:
        if link and _la_host_douyin(link):
            info = _douyin_info(link)
        # bili/xhs/tt/yt: chưa hỗ trợ fetch nhanh → trả {} (Theo dõi vẫn thêm link, chỉ thiếu avatar)
    except Exception as e:
        info = {"loi": str(e)[:120]}
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
