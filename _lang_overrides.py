# -*- coding: utf-8 -*-
"""Đè bản dịch tiếng Anh đúng thuật ngữ (domain) lên web/lang_en.json (máy dịch sai/cứng nhắc).
Chạy SAU _gen_lang_en.py."""
import json
import os
import sys

# Windows: ép stdout UTF-8 để print() tiếng Việt không crash (cp1252) khi không set PYTHONUTF8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "lang_en.json")

OVERRIDE = {
    # ----- Nav -----
    "Cào ngay": "Crawl now", "⚡ Cào ngay": "⚡ Crawl now",
    "Gợi ý kênh": "Channel suggestions", "🔎 Gợi ý kênh": "🔎 Channel suggestions",
    "Theo dõi": "Tracking", "Hẹn giờ": "Scheduler",
    "Trợ lý AI": "AI assistant", "🤖 Trợ lý AI": "🤖 AI assistant",
    "File đã tải": "Downloaded files", "📁 File đã tải": "📁 Downloaded files",
    "Lồng tiếng": "Dubbing", "🎙️ Lồng tiếng": "🎙️ Dubbing",
    "Đăng bài": "Publish", "Khách hàng": "Customers", "🔐 Khách hàng": "🔐 Customers",
    "Lịch sử": "History", "📜 Lịch sử": "📜 History",
    "Cài đặt": "Settings", "⚙️ Cài đặt": "⚙️ Settings",
    # ----- Domain "cào" -----
    "0 đã cào": "0 crawled", "Cách cào": "How to crawl",
    "▶ BẮT ĐẦU CÀO": "▶ START CRAWL", "Tổng video đã cào": "Total videos crawled",
    "➜ Cào + Theo dõi": "➜ Crawl + Track", "➜ Cào các kênh đã tick": "➜ Crawl ticked channels",
    "➜ Đưa vào Theo dõi": "➜ Add to Tracking",
    # ----- Render / biến đổi -----
    "Dịch": "Translate", "Bộ dịch": "Translator",
    "Giọng": "Voice", "Giọng đọc": "Voice", "🎤 Giọng clone": "🎤 Clone voice",
    "Nền tảng": "Platform", "Chọn nền tảng": "Choose platform", "tất cả nền tảng": "all platforms",
    "Che chữ Trung": "Hide Chinese text", "Che chữ": "Hide text",
    "Cắt đầu": "Trim start", "s · cuối": "s · end",
    "Tăng tốc": "Speed up", "Lật ngang": "Flip horizontally", "Lật": "Flip",
    "Chỉnh màu": "Color grade", "Màu": "Color",
    "Trộn nhạc nền": "Mix background music", "Tách nhạc nền": "Separate background music",
    "Tách nhạc": "Separate music", "Nhạc/tiếng nền": "Background music/audio",
    "Phụ đề Việt": "Vietnamese subtitles", "Phụ đề:": "Subtitles:",
    "Biến đổi hình/tiếng": "Transform video/audio", "video gốc": "original video",
    "GỐC chưa render": "ORIGINAL not rendered", "chưa render.": "not rendered yet.",
    "Đã rerender": "Rerendered", "Chọn video": "Select video",
    "🎬 Đưa vào xử lý": "🎬 Send to processing", "➕ Thêm vào hàng đợi": "➕ Add to queue",
    "📋 Hàng đợi": "📋 Queue", "🎬 Đã chọn": "🎬 Selected",
    "✓ Chọn hết": "✓ Select all", "✕ Bỏ chọn": "✕ Deselect", "☑ Chọn tất cả": "☑ Select all",
    "🎚 Tách giọng trước": "🎚 Separate voice first",
    "�wait": "",  # placeholder, removed below
    # ----- Tự động render -----
    "🤖 Tự động": "🤖 Auto", "🤖 Tự động render": "🤖 Auto render",
    "Tự động đưa video": "Automatically add videos", "GỐC chưa render": "ORIGINAL not rendered",
    # ----- Lồng tiếng (dub tab) -----
    "🎙️ Bắt đầu lồng tiếng": "🎙️ Start dubbing", "Video cần lồng tiếng": "Video to dub",
    "khi tick Lồng tiếng.": "when 'Dubbing' is ticked.",
    "Clone giọng (XTTS)": "Clone voice (XTTS)", "edge-tts (mặc định)": "edge-tts (default)",
    "Nữ (mặc định)": "Female (default)", "Giọng TTS": "TTS voice",
    "Độ chính xác (Whisper)": "Accuracy (Whisper)", "Giữ nền (hạ nhỏ)": "Keep background (lowered)",
    "📁 Tải giọng mẫu": "📁 Upload voice sample", "➕ Feed giọng (tải lên)": "➕ Feed voice (upload)",
    "🎤 Giọng lồng tiếng (F5-TTS clone)": "🎤 Dubbing voice (F5-TTS clone)",
    # ----- Tìm/cào -----
    "Sắp xếp": "Sort", "Từ khóa": "Keywords", "🔍 Theo từ khóa": "🔍 By keyword",
    "Theo từ khóa": "By keyword", "Theo kênh": "By channel", "👤 Theo kênh": "👤 By channel",
    "Số lượng": "Quantity", "Số video": "Number of videos", "Tần suất": "Frequency",
    "Lấy video": "Get videos", "🔎 Tìm kênh": "🔎 Find channels", "➕ Thêm kênh": "➕ Add channels",
    "Chạy ẩn (headless)": "Run hidden (headless)", "Mỗi kênh lấy tối đa": "Max per channel",
    # ----- Đăng nhập / khách -----
    "Đăng ký": "Register", "Đăng nhập": "Login", "Đăng xuất": "Logout",
    "Mật khẩu": "Password", "Nhập lại mật khẩu": "Re-enter password",
    "Tên đăng nhập": "Username", "Tên khách": "Customer name",
    "Thêm khách": "Add customer", "➕ Thêm khách": "➕ Add customer",
    "🔑 Đăng nhập nền tảng": "🔑 Platform login", "Đăng nhập để tiếp tục": "Log in to continue",
    # ----- Chung -----
    "Ngôn ngữ": "Language", "Ngôn ngữ đích": "Target language", "Tiếng Việt": "Vietnamese",
    "Trạng thái": "Status", "Thông báo": "Notification", "Sẵn sàng": "Ready",
    "Thời gian chạy": "Uptime", "Nhật ký hoạt động": "Activity log",
    "Đổi sáng/tối": "Toggle light/dark", "Nâng cấp ngay": "Upgrade now",
    "👑 Nâng cấp Pro": "👑 Upgrade to Pro", "🌐 Việt hóa": "🌐 Localize",
    "⚡ Tự cài 1 chạm": "⚡ 1-click auto setup",
    "⚠️ Dự án học tập.": "⚠️ Educational project.",
    "ViralCrawl — học tập": "LLN APP — Pro",
    "🎬 ViralCrawl — học tập": "🎬 LLN APP — Pro",
    "📤 Đăng bài theo trang": "📤 Publish by page", "📥 Gom vào folder đăng": "📥 Collect into publish folder",
    "💾 Lưu cấu hình": "💾 Save configuration", "💾 Lưu danh sách": "💾 Save list",
    "🔄 Làm mới": "🔄 Refresh", "🔄 Tải lại": "🔄 Reload", "🗑 Xóa log": "🗑 Clear logs",
    "📂 Mở thư mục": "📂 Open folder", "📁 Xem file đã tải": "📁 View downloaded files",
    "ổn": "ok", "chuẩn": "standard", "rất chuẩn": "very accurate",
    "AI (chuẩn)": "AI (accurate)", "Google (cơ bản)": "Google (basic)",
    "medium (chuẩn, chậm)": "medium (accurate, slow)", "Cân bằng (medium)": "Balanced (medium)",
    "Mỗi giờ 1 lần": "Once per hour", "Giờ cố định mỗi ngày": "Fixed hour each day",
    "Giờ chạy mỗi ngày": "Run hour each day", "Kiểm tra mỗi (phút)": "Check every (minutes)",
    "Weibo (ảnh)": "Weibo (images)",
    # ----- Status / thống kê động -----
    "Đang chạy...": "Running...", "Sẵn sàng": "Ready", "so với hôm qua": "vs yesterday",
    "đã cào": "crawled", "Tổng video đã cào": "Total videos crawled",
    "Đang xử lý...": "Processing...", "Hoàn tất.": "Done.", "Đã dừng.": "Stopped.",
}


def main():
    d = {}
    if os.path.exists(OUT):
        d = json.load(open(OUT, encoding="utf-8"))
    OVERRIDE.pop("🇼wait", None)
    OVERRIDE.pop("�wait", None)
    n = 0
    for k, v in OVERRIDE.items():
        if v and d.get(k) != v:
            d[k] = v
            n += 1
    # Sửa "cào" bị máy dịch thành scratch/rake/scrape -> crawl (giữ hoa/thường)
    FIX = [("START SCRATCHING", "START CRAWL"), ("START RAKE", "START CRAWL"),
           ("Scratch Now", "Crawl now"), ("Scratch now", "Crawl now"),
           ("scratching", "crawling"), ("scratched", "crawled"),
           ("Scratch", "Crawl"), ("scratch", "crawl"),
           ("Scraping", "Crawling"), ("scraping", "crawling"),
           ("Scrape", "Crawl"), ("scrape", "crawl"), ("Rake", "Crawl"), ("rake", "crawl")]
    for k in list(d):
        v = d[k]
        for a, b in FIX:
            if a in v:
                v = v.replace(a, b)
        if v != d[k]:
            d[k] = v
            n += 1
    # Bỏ key chứa HTML (<...>) — walker dịch theo text node nên key có thẻ không bao giờ khớp
    for k in [k for k in d if "<" in k or ">" in k]:
        del d[k]
    json.dump(d, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # Xuất kèm .js (server cũ phục vụ được .js, không cần restart cho i18n giao diện)
    js = os.path.join(os.path.dirname(OUT), "lang_en.js")
    # ensure_ascii=True: file .js thuần ASCII (\uXXXX) -> không lệ thuộc charset khi <script src> tải
    with open(js, "w", encoding="utf-8") as f:
        f.write("window.LANGDICT_EN = " + json.dumps(d, ensure_ascii=True) + ";\n")
    print(f"Đè {n} thuật ngữ. Tổng {len(d)} cặp -> {OUT} + {js}.")


if __name__ == "__main__":
    main()
