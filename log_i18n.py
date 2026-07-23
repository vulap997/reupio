# -*- coding: utf-8 -*-
"""Dịch dòng LOG hoạt động (tiếng Việt) sang tiếng Anh khi giao diện = en.
Dùng ở web_app /api/log — KHÔNG sửa logic logging (log lưu tiếng Việt, chỉ dịch lúc gửi ra).
Gồm thông điệp them_log() (web_app) + log từ subprocess localize.py/xu_ly_chon.py."""
import re

# ----- Khớp nguyên văn (chuỗi cố định) -----
_EXACT = {
    "✔ Hoàn tất.": "✔ Done.",
    "✔ Đã tải 1 video": "✔ Downloaded 1 video",
    "⚠ 1 video lỗi 403 (bỏ qua)": "⚠ 1 video failed 403 (skipped)",
    "■ Đã dừng.": "■ Stopped.",
    "Sẵn sàng.": "Ready.",
    "📥 Bắt đầu gom video vào folder đăng theo trang...": "📥 Collecting videos into per-page publish folders...",
    "⏹ TẮT tự động render.": "⏹ Auto render OFF.",
    "🤖 BẬT tự động render — không giới hạn.": "🤖 Auto render ON — unlimited.",
    "🗑 Đã xóa giọng mẫu.": "🗑 Deleted voice sample.",
    "🔍 Đang kiểm tra đăng nhập (chạy ngầm)...": "🔍 Checking login (in background)...",
    "✅ Kiểm tra đăng nhập xong.": "✅ Login check done.",
    "🧪 Đang kiểm tra theo dõi kênh...": "🧪 Testing channel tracking...",
    "🧪 Đang chạy thử tác vụ hẹn giờ...": "🧪 Test-running the scheduled task...",
    # --- subprocess: localize.py / xu_ly_chon.py ---
    "🎧 Nghe giọng mẫu để lấy lời (cho clone)...": "🎧 Listening to voice sample to get text (for clone)...",
    "⚠ Thiếu giọng mẫu để clone (ref_audio + mặc định đều không có) → bỏ lồng tiếng.":
        "⚠ Missing voice sample to clone (no ref_audio nor default) → skip dubbing.",
    "⚠ edge-tts không tạo được câu nào → bỏ lồng tiếng.": "⚠ edge-tts produced no segments → skip dubbing.",
    "🎚 Đang tách giọng/nhạc (demucs — chậm nếu không GPU)...":
        "🎚 Separating voice/music (demucs — slow without GPU)...",
    "⚠ Phụ đề rỗng.": "⚠ Empty subtitles.",
    "✔ Đã tách giọng — nhận dạng trên giọng sạch (chính xác hơn).":
        "✔ Voice separated — transcribing on clean voice (more accurate).",
    "⚠ Không nhận dạng được lời thoại.": "⚠ Could not recognize any speech.",
    "⚠ Lồng tiếng không thành công → xuất video phụ đề thay thế.":
        "⚠ Dubbing failed → exporting subtitled video instead.",
    "🎞 Đang biến đổi (lật/tốc độ/watermark/màu/cắt)...":
        "🎞 Transforming (flip/speed/watermark/color/trim)...",
    "⚠ Chưa chọn phép xử lý nào.": "⚠ No processing option selected.",
    "⚠ Không tạo được video phụ đề/lồng tiếng.": "⚠ Could not create subtitled/dubbed video.",
    "🎬 Đang ghép video (che chữ + phụ đề)...": "🎬 Muxing video (hide text + subtitles)...",
    "🎬 Đang ghép video (che chữ + phụ đề + lồng tiếng)...":
        "🎬 Muxing video (hide text + subtitles + dubbing)...",
}

# ----- Khớp mẫu (có phần nội suy) -----  (regex, bản tiếng Anh dùng \1 \2 ...)
_PATTERNS = [
    (r"^▶ Bắt đầu tải (.+) — (.+)$", r"▶ Start downloading \1 — \2"),
    (r"^▶ Bắt đầu cào (.+) — (.+)$", r"▶ Start crawling \1 — \2"),
    (r"^\[LỖI\] (.+)$", r"[ERROR] \1"),
    (r"^🤖 Tự động: đưa (\d+) video vào hàng đợi\.$", r"🤖 Auto: queued \1 video(s)."),
    (r"^✅ Tự động: đã đưa đủ (\d+) video — dừng theo dõi\.$",
     r"✅ Auto: queued all \1 video(s) — stopped."),
    (r"^⚠ Tự động render lỗi: (.+)$", r"⚠ Auto render error: \1"),
    (r"^🌐 Bắt đầu Việt hóa: (.+)$", r"🌐 Start localizing: \1"),
    (r"^➕ Đã thêm (\d+) video vào hàng đợi render\.$", r"➕ Added \1 video(s) to render queue."),
    (r"^⏹ Đã hủy video đang xử lý \(treo\): (.+)$", r"⏹ Cancelled stuck video: \1"),
    (r"^🗑 Đã xóa khỏi hàng đợi: (.+)$", r"🗑 Removed from queue: \1"),
    (r"^🤖 BẬT tự động render — (\d+) video\.$", r"🤖 Auto render ON — \1 video(s)."),
    (r"^🎤 Đã thêm giọng mẫu: (.+)$", r"🎤 Added voice sample: \1"),
    (r"^🗑️ Đã xóa: (.+)$", r"🗑️ Deleted: \1"),
    (r"^🔑 Mở trình duyệt để đăng nhập: (.+)$", r"🔑 Opening browser to log in: \1"),
    (r"^⚠️ Kiểm tra đăng nhập lỗi: (.+)$", r"⚠️ Login check error: \1"),
    (r"^Lỗi khởi tạo DB khách: (.+)$", r"Customer DB init error: \1"),
    (r"^▶ (Video \d+/\d+): (.+)$", r"▶ \1: \2"),
    # --- subprocess localize.py / xu_ly_chon.py ---
    (r"^🎧 Đang nghe & nhận dạng giọng nói \((.+)\)\.\.\.$", r"🎧 Listening & transcribing (\1)..."),
    (r"^⚠ FFmpeg lỗi: (.*)$", r"⚠ FFmpeg error: \1"),
    (r"^⚠ Không lấy được lời giọng mẫu: (.*)$", r"⚠ Could not get voice-sample text: \1"),
    (r"^⚠ edge-tts lỗi: (.*)$", r"⚠ edge-tts error: \1"),
    (r"^⚠ Thiếu demucs/soundfile → bỏ tách giọng\. (.*)$",
     r"⚠ Missing demucs/soundfile → skip voice separation. \1"),
    (r"^⚠ demucs lỗi: (.*)$", r"⚠ demucs error: \1"),
    (r"^⚠ Không thấy file video: (.+)$", r"⚠ Video file not found: \1"),
    (r"^ℹ Nguồn đã cùng ngôn ngữ đích \((.+)\) — .*$",
     r"ℹ Source already in target language (\1) — skip dubbing, subtitles/copyright-avoid only."),
    (r"^📝 Nhận dạng (\d+) câu \(nguồn cùng ngôn ngữ đích — không dịch\)\.$",
     r"📝 Recognized \1 segment(s) (source = target language — no translation)."),
    (r"^📝 Nhận dạng (\d+) câu\. Đang dịch \(Google\)\.\.\.$",
     r"📝 Recognized \1 segment(s). Translating (Google)..."),
    (r"^✔ Xong video LỒNG TIẾNG: (.+)$", r"✔ Dubbed video done: \1"),
    (r"^✔ Xong video phụ đề: (.+)$", r"✔ Subtitled video done: \1"),
    (r"^✔ Xong: (.+)$", r"✔ Done: \1"),
    (r"^🎙 Lồng tiếng bằng edge-tts \((.+)\) — (\d+) câu\.\.\.$",
     r"🎙 Dubbing with edge-tts (\1) — \2 segment(s)..."),
    (r"^⚠ ghép câu (\d+) lỗi: (.*)$", r"⚠ segment \1 merge error: \2"),
    (r"^\s*đọc (\d+)/(\d+)$", r"   reading \1/\2"),
    (r"^\s*dịch (\d+)/(\d+)$", r"   translating \1/\2"),
    (r"^📄 Dùng phụ đề đã sửa: (\d+) câu\.$", r"📄 Using edited subtitles: \1 segment(s)."),
    (r"^⚠ AI sửa lỗi \((.*)\) → giữ bản Google$", r"⚠ AI fix failed (\1) → keeping Google version"),
    (r"^✔ Đã tạo phụ đề: (.+)$", r"✔ Subtitles created: \1"),
]
_COMPILED = [(re.compile(p), r) for p, r in _PATTERNS]
_CACHE = {}


def dich_log(line, lang="en"):
    if lang != "en" or not line:
        return line
    if line in _CACHE:
        return _CACHE[line]
    out = _EXACT.get(line)
    if out is None:
        out = line
        for pat, repl in _COMPILED:
            m = pat.match(line)
            if m:
                out = m.expand(repl)
                break
    _CACHE[line] = out
    return out


def dich_nhieu(lines, lang="en"):
    if lang != "en":
        return lines
    return [dich_log(l, lang) for l in lines]
