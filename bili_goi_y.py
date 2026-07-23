# -*- coding: utf-8 -*-
"""
Gợi ý kênh Bilibili THẬT (không mô phỏng).
Mở tab tìm UP của Bilibili (search.bilibili.com/upuser), trích danh sách kênh kèm
follow (粉丝) + số video (视频) hiển thị sẵn trên card, xếp theo follow giảm dần.

Dùng:  python bili_goi_y.py "<từ khóa>"
Env:   GOI_Y_OUT (đường dẫn json ra), GOI_Y_LIMIT (số kênh, mặc định 20),
       GOI_Y_HEADLESS ("1" ẩn / "0" hiện, mặc định "1")
Kết quả: ghi JSON list các kênh ra GOI_Y_OUT (mặc định MediaCrawler/data/bili/_goi_y_kenh.json)
"""
import os
import sys
import json
import time

from playwright.sync_api import sync_playwright

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
THU_MUC_CRAWLER = os.path.join(THU_MUC_GOC, "MediaCrawler")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

JS_TRICH = r"""
() => {
  const parseNum = (s) => {
    s = (s || '').replace(/[, ]/g, '');
    let m = s.match(/([\d.]+)\s*亿/); if (m) return Math.round(parseFloat(m[1]) * 1e8);
    m = s.match(/([\d.]+)\s*万/);     if (m) return Math.round(parseFloat(m[1]) * 1e4);
    m = s.match(/([\d.]+)/);          return m ? parseInt(m[1]) : 0;
  };
  const out = [];
  const cards = document.querySelectorAll('.b-user-info-card, .user-list .b-user-video-card');
  cards.forEach(c => {
    const a = c.querySelector('a[href*="space.bilibili.com"]');
    if (!a) return;
    let link = a.href; if (link.startsWith('//')) link = 'https:' + link;
    const img = c.querySelector('img.bili-avatar-img, img[data-src], img');
    let avatar = img ? (img.getAttribute('data-src') || img.src || '') : '';
    if (avatar.startsWith('//')) avatar = 'https:' + avatar;
    if (avatar.includes('@')) avatar = avatar.split('@')[0];  // bỏ tham số resize
    const nameEl = c.querySelector('.user-name, .i_card_title a, .i_card_title, h2 a, h2');
    const name = nameEl ? nameEl.textContent.trim() : '';
    const txt = c.innerText || '';
    const fansM = txt.match(/([\d.]+[万亿]?)\s*粉丝/);
    const vidM  = txt.match(/([\d.]+[万亿]?)\s*个?视频/);
    let sig = '';
    const sigEl = c.querySelector('.user-sign, .b_text.sign, [class*="sign"]');
    if (sigEl) sig = sigEl.textContent.trim();
    out.push({
      nickname: name,
      link: link,
      avatar: avatar,
      fans: fansM ? parseNum(fansM[1]) : 0,
      videos_count: vidM ? parseNum(vidM[1]) : 0,
      signature: sig,
    });
  });
  // bỏ trùng theo link
  const seen = new Set(); const uniq = [];
  for (const o of out) { if (o.link && !seen.has(o.link)) { seen.add(o.link); uniq.push(o); } }
  return uniq;
}
"""


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "影评"
    limit = int(os.environ.get("GOI_Y_LIMIT", "20"))
    headless = os.environ.get("GOI_Y_HEADLESS", "1") == "1"
    out_path = os.environ.get("GOI_Y_OUT") or os.path.join(
        THU_MUC_CRAWLER, "data", "bili", "_goi_y_kenh.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    import urllib.parse
    url = "https://search.bilibili.com/upuser?keyword=" + urllib.parse.quote(keyword)
    # ĐỌC profile từ MC_BROWSER_DATA_DIR (userData — nơi LOGIN lưu cookie bili), KHÔNG hardcode app-src/MediaCrawler:
    # login lưu userData/browser_data/bili_user_data_dir nhưng trước đây gợi-ý đọc app-src/MediaCrawler/browser_data
    # RỖNG → "chưa login" → 0 kênh. Cùng cơ chế MC_BROWSER_DATA_DIR như douyin core / mo_dang_nhap.
    _bd = os.environ.get("MC_BROWSER_DATA_DIR") or os.path.join(THU_MUC_CRAWLER, "browser_data")
    user_data_dir = os.path.join(_bd, "bili_user_data_dir")
    os.makedirs(user_data_dir, exist_ok=True)
    stealth_path = os.path.join(THU_MUC_CRAWLER, "libs", "stealth.min.js")

    creators = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir, headless=headless,
            viewport={"width": 1366, "height": 900}, user_agent=UA,
            ignore_default_args=["--enable-automation"],
            args=["--hide-crash-restore-bubble", "--no-first-run",
                  "--no-default-browser-check", "--disable-session-crashed-bubble"],
        )
        if os.path.exists(stealth_path):
            try:
                ctx.add_init_script(path=stealth_path)
            except Exception:
                pass
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        # chờ card UP xuất hiện
        try:
            page.wait_for_selector(".b-user-info-card, .b-user-video-card", timeout=15000)
        except Exception:
            pass
        time.sleep(2)
        for _ in range(2):
            try:
                page.mouse.wheel(0, 1500)
            except Exception:
                pass
            time.sleep(1.2)
        try:
            creators = page.evaluate(JS_TRICH) or []
        except Exception:
            creators = []
        try:
            ctx.close()
        except Exception:
            pass

    creators.sort(key=lambda c: c.get("fans") or 0, reverse=True)
    creators = creators[:limit]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(creators, f, ensure_ascii=False)
    print("BILI_GOI_Y_DONE", len(creators))


if __name__ == "__main__":
    main()
