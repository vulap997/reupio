# -*- coding: utf-8 -*-
"""
Browser-first XHS / RedNote (xiaohongshu) — phục vụ học tập.

LÝ DO: API user_posted/feed của XHS gọi qua httpx bị CAPTCHA 461 (automation-detection + thiếu xsec_token
động), DÙ cookie + chữ ký GET hợp lệ (selfinfo/creator-info pass). Nhưng TRÌNH DUYỆT thật (Playwright,
cùng account/IP/profile) RENDER được trang kênh bình thường → account/IP KHÔNG bị chặn. Vì vậy chuyển nhánh
liệt-kê (và sau này tải) sang BROWSER-first: mở profile bằng Playwright (persistent context = profile đã
login), cuộn cho nạp hết card, parse DOM lấy note_id/title/cover — KHÔNG đụng endpoint bị 461.

Kiến trúc (sẵn cho phần B = tải video):
    XHSBrowser.open_profile(url)      -> mở trang kênh
    XHSBrowser.list_notes(max)        -> [A] cuộn-đến-ổn-định + parse DOM card  (DÙNG NGAY cho Xem-trước)
    XHSBrowser.open_note(note_id)     -> [B] mở trang note
    XHSBrowser.get_video_info()       -> [B] bắt URL video qua network (page.on response)

CLI (tim_anh.py gọi):
    python xhs_browser.py --action list --url <profile_url> --count 50 --intl 1 --profile <user_data_dir>
    -> in 1 dòng JSON: {"ok":true,"items":[{id,title,thumb,loai,video,so_anh,url,...}],"tong":N}
"""
import argparse
import asyncio
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# UA PHẢI khớp UA login (mo_dang_nhap = Windows Chrome 126) — XHS gắn phiên theo fingerprint UA.
WIN_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Regex note-id: XHS/RedNote đặt link note ở 3 dạng — /explore/<id>, /discovery/item/<id>, VÀ (mới, trên
# trang KÊNH) /user/profile/<uid>/<noteid>?xsec_token=... . Trước chỉ bắt 2 dạng đầu → trang kênh dạng mới
# ra 0 card (link video nằm dưới path /user/profile/<uid>/<noteid>). Segment 2 (noteid) ≥16 hex để KHÔNG
# nhầm link KÊNH /user/profile/<uid> (1 id). group1=explore/discovery, group2=note-in-profile.
_NOTE_RE = r"/(?:explore|discovery/item)/([0-9a-fA-F]+)|/user/profile/[0-9a-fA-F]+/([0-9a-fA-F]{16,})"

# Đếm số card hiện có (để biết cuộn đã nạp thêm chưa). Regex TRUYỀN QUA THAM SỐ (new RegExp) — KHÔNG
# nhúng vào /.../ literal (dấu '/' trong 'discovery/item' + '{16,}' phá literal → SyntaxError, ra 0 card).
_CNT_JS = r"""(re) => { const R=new RegExp(re); return new Set([...document.querySelectorAll('a')]
    .map(a => { const m=(a.href||'').match(R); return m ? (m[1]||m[2]) : null; })
    .filter(Boolean)).size; }"""

# Parse card -> item theo SHAPE preview của tim_anh (_item_xhs): id,title,thumb,loai,video,so_anh,url,...
_PARSE_JS = r"""(re) => {
  const NOTE_RE = new RegExp(re);
  const out = [], seen = new Set();
  const links = [...document.querySelectorAll('a')].filter(a => NOTE_RE.test(a.href||''));
  for (const a of links) {
    const m = (a.href||'').match(NOTE_RE);
    if (!m) continue;
    const id = m[1] || m[2]; if (!id || seen.has(id)) continue; seen.add(id);
    const card = a.closest('section, div') || a;
    const img = card.querySelector('img');
    let title = '';
    const tEl = card.querySelector('.title, [class*="title"], footer span, footer');
    if (tEl) title = (tEl.textContent || '').trim();
    if (!title) { const im = card.querySelector('img[alt]'); if (im) title = im.alt || ''; }
    const isVid = !!card.querySelector('[class*="play"], .play-icon, video');
    out.push({
      id: id,
      title: (title || '').slice(0, 160),
      thumb: (img && (img.src || img.getAttribute('data-src'))) || '',
      loai: isVid ? 'video' : 'anh',
      video: isVid,
      so_anh: 0,
      url: (a.href || ''),
      link: (a.href || ''),     // GIỮ ?xsec_token — BẮT BUỘC để mở note + tải video (né 461)
      like: '', time: 0, nick: '', user_id: '', avatar: ''
    });
  }
  return out;
}"""

# Trang đòi đăng nhập / chặn (để báo RÕ thay vì "0 bài").
_LOGIN_HINT = ("请登录", "登录后查看", "扫码登录", "登录小红书")


class XHSBrowser:
    """Phiên trình duyệt tái dùng cho XHS/RedNote (persistent context = profile đã login)."""

    def __init__(self, profile_dir, intl=True, headless=True, ua=WIN_UA):
        self.profile_dir = profile_dir
        self.intl = intl
        self.headless = headless
        self.ua = ua
        self.domain = "https://www.rednote.com" if intl else "https://www.xiaohongshu.com"
        self._pw = None
        self.ctx = None
        self.page = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()
        self.ctx = await self._pw.chromium.launch_persistent_context(
            self.profile_dir,
            headless=self.headless,
            user_agent=self.ua,
            viewport={"width": 1280, "height": 900},
            args=["--hide-crash-restore-bubble", "--no-first-run",
                  "--no-default-browser-check", "--disable-blink-features=AutomationControlled"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        return self

    async def __aexit__(self, *a):
        for fn in (lambda: self.ctx.close(), lambda: self._pw.stop()):
            try:
                await fn()
            except Exception:
                pass

    async def open_profile(self, url):
        # XHS nội địa & RedNote DÙNG CHUNG dữ liệu. Tool gộp về RedNote (profile đã login) → link
        # xiaohongshu.com phải ĐỔI DOMAIN sang rednote.com để mở đúng profile đã đăng nhập (nếu goto
        # xiaohongshu.com bằng profile rednote → trang đòi login lại → 0 note). Chỉ đổi khi intl (rednote).
        if self.intl and "xiaohongshu.com" in (url or ""):
            url = url.replace("xiaohongshu.com", "rednote.com")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)

    async def can_login(self):
        """Trang có đang đòi đăng nhập không (cookie hết hạn)."""
        try:
            body = (await self.page.inner_text("body"))[:4000]
        except Exception:
            return False
        return any(h in body for h in _LOGIN_HINT)

    async def list_notes(self, max_count=50, max_rounds=40):
        """[A] Cuộn-đến-cạn rồi trả note. XHS VIRTUALIZE feed (card ngoài viewport bị UNMOUNT khỏi DOM —
        đã đo: in_dom tụt 21→10 trong khi union tăng) → PHẢI GOM item qua TỪNG vòng cuộn (union theo id),
        KHÔNG parse-1-lần (chỉ được ~10 card đang mount). Dừng khi union KHÔNG tăng `idle` vòng liên tiếp."""
        acc = {}          # id -> item (tích lũy xuyên suốt, chống virtualization)
        idle = 0
        for _ in range(max_rounds):
            try:
                items = await self.page.evaluate(_PARSE_JS, _NOTE_RE)
            except Exception:
                items = []
            before = len(acc)
            for it in items:
                _id = it.get("id")
                if _id and _id not in acc:
                    acc[_id] = it
            if len(acc) >= max_count:
                break
            if len(acc) == before:
                idle += 1
                if idle >= 4:          # union không tăng 4 vòng = đã cạn (hết phân trang)
                    break
            else:
                idle = 0
            # Trigger nạp trang kế: kéo CARD CUỐI vào viewport (IntersectionObserver) + window bottom + End.
            # Card cuối = link note khớp _NOTE_RE (KHÔNG hardcode '/explore/' — trang KÊNH dùng /user/profile/<uid>/<nid>
            # → selector cũ tìm 0 phần tử → không cuộn được → chỉ parse trang đầu).
            try:
                await self.page.evaluate(
                    "(re) => { const R=new RegExp(re);"
                    " const ls=[...document.querySelectorAll('a')].filter(a=>R.test(a.href||''));"
                    " if(ls.length) ls[ls.length-1].scrollIntoView({block:'end'});"
                    " window.scrollTo(0, document.documentElement.scrollHeight); }", _NOTE_RE)
                await self.page.keyboard.press("End")
            except Exception:
                pass
            await self.page.wait_for_timeout(2000)
        return list(acc.values())[:max_count]

    # ---------- B-ready (chưa wire vào UI) ----------
    async def open_note(self, note_id):
        """[B] Mở trang chi tiết note (để trích URL video). Chưa dùng ở Commit A."""
        await self.page.goto(f"{self.domain}/explore/{note_id}", wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(2500)

    async def get_single_note_info(self, url):
        """Lấy thông tin của một video/bài viết đơn lẻ từ DOM/InitialState."""
        if self.intl and "xiaohongshu.com" in (url or ""):
            url = url.replace("xiaohongshu.com", "rednote.com")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)
        
        if await self.can_login():
            raise Exception("Need login")
            
        item = await self.page.evaluate("""() => {
            if (typeof window.__INITIAL_STATE__ === 'undefined') return null;
            const state = window.__INITIAL_STATE__;
            if (state.note && state.note.noteDetailMap) {
                const map = state.note.noteDetailMap;
                const noteId = Object.keys(map)[0];
                if (noteId) {
                    const note = map[noteId].note;
                    const title = note.title || note.desc || "";
                    const thumb = (note.imageList && note.imageList[0]) ? 
                        (note.imageList[0].urlDefault || note.imageList[0].url || note.imageList[0].urlPre || "") : "";
                    const isVid = note.type === "video" || !!note.video;
                    const nick = note.user ? note.user.nickname : "";
                    const avatar = note.user ? note.user.avatar : "";
                    const link = location.href;
                    return {
                        id: noteId,
                        title: title.slice(0, 160),
                        thumb: thumb,
                        loai: isVid ? 'video' : 'anh',
                        video: isVid,
                        so_anh: note.imageList ? note.imageList.length : 0,
                        url: link,
                        link: link,
                        like: note.interactInfo ? String(note.interactInfo.likedCount || '') : '',
                        time: note.time ? Math.floor(note.time / 1000) : 0,
                        nick: nick,
                        user_id: note.user ? note.user.userId : '',
                        avatar: avatar
                    };
                }
            }
            return null;
        }""")
        
        if not item:
            # Fallback
            doc_title = await self.page.title()
            title = doc_title.replace(" - rednote", "").replace(" - 小红书", "").strip()
            is_video = await self.page.evaluate("() => !!document.querySelector('video')")
            thumb = await self.page.evaluate("""() => {
                const v = document.querySelector('video');
                if (v && v.getAttribute('poster')) return v.getAttribute('poster');
                const img = document.querySelector('.media-container img, [class*="note"] img, img');
                return img ? img.src : '';
            }""")
            import re
            m = re.search(r"/(?:explore|discovery/item)/([0-9a-fA-F]+)|/user/profile/[0-9a-fA-F]+/([0-9a-fA-F]{16,})", url)
            note_id = (m.group(1) or m.group(2)) if m else "note"
            item = {
                "id": note_id,
                "title": title[:160],
                "thumb": thumb,
                "loai": "video" if is_video else "anh",
                "video": is_video,
                "so_anh": 0 if is_video else 1,
                "url": url,
                "link": url,
                "like": "",
                "time": 0,
                "nick": "",
                "user_id": "",
                "avatar": ""
            }
        return item


    async def get_video_info(self, timeout_ms=8000):
        """[B] Bắt URL video/m3u8 qua network sau open_note (browser đã giải challenge → request đủ token).
        Chưa dùng ở Commit A — để sẵn cho phần tải."""
        hits = []
        self.page.on("response", lambda r: hits.append(r.url)
                     if any(k in r.url for k in (".mp4", ".m3u8", "sns-video", "/stream/")) else None)
        await self.page.wait_for_timeout(timeout_ms)
        return hits

    async def download_note(self, note_id, out_path, url=None, wait_ms=8000):
        """[B] TẢI video 1 note QUA BROWSER: mở /explore/<id> → bắt URL .mp4 từ network (listener đăng
        TRƯỚC goto) → tải bằng `ctx.request` (mang cookie/headers của browser thật → né 461 như preview).
        Trả True nếu lưu được file > 10KB. KHÔNG đụng API ký (x-s/x-t) → không vi phạm 'no reverse-signature'."""
        vids = []

        def _on(r):
            u = r.url
            if (".mp4" in u or "sns-video" in u) and ".m3u8" not in u:
                vids.append(u)

        self.page.on("response", _on)
        try:
            await self.page.goto(url or f"{self.domain}/explore/{note_id}", wait_until="domcontentloaded", timeout=60000)
            await self.page.wait_for_timeout(wait_ms)
            try:   # ép phát (muted) → 1 số note chỉ tải video khi play
                await self.page.evaluate(
                    "() => { const v=document.querySelector('video'); if(v){v.muted=true; v.play().catch(()=>{});} }")
                await self.page.wait_for_timeout(3500)
            except Exception:
                pass
        finally:
            try:
                self.page.remove_listener("response", _on)
            except Exception:
                pass
        urls = [u for u in vids if ".mp4" in u] or vids
        for u in dict.fromkeys(urls):   # khử trùng giữ thứ tự; thử tới khi tải được
            try:
                resp = await self.ctx.request.get(u, timeout=120000)
                if not resp.ok:
                    continue
                body = await resp.body()
                if len(body) > 10000:
                    with open(out_path, "wb") as f:
                        f.write(body)
                    return True
            except Exception:
                continue
        return False


def _resolve_profile(args):
    if args.profile:
        return args.profile
    bd = os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "MediaCrawler", "browser_data")
    leaf = os.environ.get("MC_XHS_PROFILE") or ("rednote_user_data_dir" if args.intl == "1" else "xhs_user_data_dir")
    return os.path.join(bd, leaf)


async def _run(args):
    profile = _resolve_profile(args)
    if not os.path.isdir(profile):
        return {"ok": False, "msg": "Chưa có hồ sơ đăng nhập (profile) cho nền tảng này — hãy ĐĂNG NHẬP trước."}
    try:
        async with XHSBrowser(profile, intl=(args.intl == "1"), headless=(args.headless != "no")) as b:
            if args.action == "download":   # TẢI video qua browser (mỗi id 1 file) — KHÔNG cần open_profile
                ids = [x.strip() for x in (args.ids or "").split(",") if x.strip()]
                os.makedirs(args.out_dir, exist_ok=True)
                tai, loi = [], []
                for nid in ids:
                    out = os.path.join(args.out_dir, nid + ".mp4")
                    try:
                        ok = await b.download_note(nid, out)
                    except Exception:
                        ok = False
                    (tai if ok else loi).append(nid)
                return {"ok": len(tai) > 0, "tai": tai, "loi": loi,
                        "msg": "Tải %d/%d video qua browser" % (len(tai), len(ids))}
            import re
            is_note = False
            if args.url:
                if re.search(r"/(?:explore|discovery/item)/[0-9a-fA-F]+|/user/profile/[0-9a-fA-F]+/([0-9a-fA-F]{16,})", args.url):
                    is_note = True

            if is_note:
                try:
                    item = await b.get_single_note_info(args.url)
                    if await b.can_login():
                        return {"ok": False, "msg": "Phiên đăng nhập đã hết hạn — hãy ĐĂNG NHẬP LẠI nền tảng rồi thử lại."}
                    items = [item] if item else []
                    return {"ok": True, "items": items, "tong": len(items)}
                except Exception as e:
                    return {"ok": False, "msg": "Lỗi tải thông tin bài: " + str(e)[:200]}
            else:
                await b.open_profile(args.url)
                if await b.can_login():
                    return {"ok": False, "msg": "Phiên đăng nhập đã hết hạn — hãy ĐĂNG NHẬP LẠI nền tảng rồi thử lại."}
                if args.action == "list":
                    items = await b.list_notes(max_count=int(args.count or 50))
                    return {"ok": True, "items": items, "tong": len(items)}
            return {"ok": False, "msg": "Hành động chưa hỗ trợ: " + str(args.action)}
    except Exception as e:
        return {"ok": False, "msg": "Lỗi mở trình duyệt: " + str(e)[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", default="list")     # list (A) | download (B: tải video qua browser)
    ap.add_argument("--url", default="")             # link trang kênh (creator) — cho action=list
    ap.add_argument("--count", default="50")
    ap.add_argument("--intl", default="1")           # 1=rednote.com, 0=xiaohongshu.com
    ap.add_argument("--headless", default="yes")
    ap.add_argument("--profile", default="")         # user_data_dir; rỗng -> suy từ env
    ap.add_argument("--ids", default="")             # action=download: note_id phân tách dấu phẩy
    ap.add_argument("--out-dir", dest="out_dir", default="")  # action=download: thư mục lưu .mp4
    args = ap.parse_args()
    if args.action == "download":
        if not args.ids.strip() or not args.out_dir.strip():
            print(json.dumps({"ok": False, "msg": "download cần --ids và --out-dir."}, ensure_ascii=False)); return
    elif not args.url.strip():
        print(json.dumps({"ok": False, "msg": "Chưa nhập link kênh."}, ensure_ascii=False))
        return
    try:
        res = asyncio.run(_run(args))
    except Exception as e:
        res = {"ok": False, "msg": "Lỗi: " + str(e)[:200]}
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
