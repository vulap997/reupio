# -*- coding: utf-8 -*-
"""
Cấu hình NGÔN NGỮ toàn ứng dụng (vi/en) — phục vụ học tập.

Hai khái niệm:
  • app_lang     : ngôn ngữ GIAO DIỆN (dùng cho i18n — phần 2).
  • target_lang  : ngôn ngữ ĐÍCH của nội dung (dịch tiêu đề/folder/phụ đề/lồng tiếng).
                   Mặc định = app_lang; có thể đổi riêng.

Nguồn của video xác định THEO NỀN TẢNG:
  • douyin/bili/xhs/weibo/kuaishou = tiếng Trung  -> cần dịch + lồng tiếng sang đích.
  • youtube/tiktok                 = coi như đã đúng ngôn ngữ đích -> không dịch/lồng tiếng.

Subprocess (crawl/localize) đọc đích qua biến môi trường TARGET_LANG do web_app truyền.
"""
import json
import os

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
# app_config.json PHẢI ở thư mục GHI ĐƯỢC: app-src = Program Files READ-ONLY (bản đóng gói) → luu_cau_hinh ghi
# FAIL ÂM THẦM → app_lang/target_lang KẸT mặc định "vi" (đổi ngôn ngữ KHÔNG lưu, dropdown về VI). Ưu tiên
# LIC_CACHE_DIR (userData, Electron truyền); dev không có env → THU_MUC_GOC. Di cư bản cũ app-src → userData 1 lần.
_CFG_DIR = (os.environ.get("LIC_CACHE_DIR") or "").strip() or THU_MUC_GOC
FILE_LANG = os.path.join(_CFG_DIR, "app_config.json")
_FILE_LANG_CU = os.path.join(THU_MUC_GOC, "app_config.json")
if FILE_LANG != _FILE_LANG_CU and not os.path.exists(FILE_LANG) and os.path.exists(_FILE_LANG_CU):
    try:
        os.makedirs(_CFG_DIR, exist_ok=True)
        import shutil as _sh
        _sh.copyfile(_FILE_LANG_CU, FILE_LANG)
    except OSError:
        pass

NEN_TANG_TRUNG = ("douyin", "bili", "bilibili", "xhs", "weibo", "wb", "kuaishou")

# ==== BẢNG NGÔN NGỮ ĐÍCH (data-driven, thêm ngôn ngữ = thêm 1 dòng) ====
# code -> {ten (hiển thị VN), ten_en (cho prompt dịch Gemini), google (mã Google Translate),
#          edge (giọng edge-tts mặc định = fallback), nam/nu (giọng theo GIỚI TÍNH — UI đơn giản Male/Female),
#          nam_uk/nu_uk (chỉ en: giọng UK), voices (list (value,nhãn) — GIỮ tương thích/advanced),
#          supertonic (engine offline Supertonic có hỗ trợ ngôn ngữ này không)}.
# UI ĐƠN GIẢN (ElevenLabs-style): người dùng chỉ chọn Ngôn ngữ → Male/Female (ẩn locale + tên voice kỹ thuật);
#   mapping nội bộ nam/nu → giọng Edge tốt nhất (hoặc M1/F1 nếu Supertonic). MS đổi giọng sau → chỉ sửa bảng.
# Engine: Edge (online) mặc định MỌI ngôn ngữ; nhóm LÕI Supertonic (ko/ja/es/pt/fr/de/it) giữ Supertonic offline
#   (2-lane cân bằng CPU∥mạng + hedge throttle) → nam/nu = "M1"/"F1" (giọng Supertonic theo giới tính).
# Vietnamese GIỮ NGUYÊN model cũ (Piper/omnivoice/edge) — KHÔNG áp gender-abstraction.
LANGS = {
    "af": {"ten": "Afrikaans", "ten_en": "Afrikaans", "google": "af", "edge": "af-ZA-AdriNeural",
           "nam": "af-ZA-WillemNeural", "nu": "af-ZA-AdriNeural",
           "voices": [("af-ZA-AdriNeural","Nữ — Adri"),("af-ZA-WillemNeural","Nam — Willem")], "supertonic": False},
    "sq": {"ten": "Albania", "ten_en": "Albanian", "google": "sq", "edge": "sq-AL-AnilaNeural",
           "nam": "sq-AL-IlirNeural", "nu": "sq-AL-AnilaNeural",
           "voices": [("sq-AL-AnilaNeural","Nữ — Anila"),("sq-AL-IlirNeural","Nam — Ilir")], "supertonic": False},
    "am": {"ten": "Amharic", "ten_en": "Amharic", "google": "am", "edge": "am-ET-MekdesNeural",
           "nam": "am-ET-AmehaNeural", "nu": "am-ET-MekdesNeural",
           "voices": [("am-ET-MekdesNeural","Nữ — Mekdes"),("am-ET-AmehaNeural","Nam — Ameha")], "supertonic": False},
    "az": {"ten": "Azerbaijan", "ten_en": "Azerbaijani", "google": "az", "edge": "az-AZ-BanuNeural",
           "nam": "az-AZ-BabekNeural", "nu": "az-AZ-BanuNeural",
           "voices": [("az-AZ-BanuNeural","Nữ — Banu"),("az-AZ-BabekNeural","Nam — Babek")], "supertonic": False},
    "pl": {"ten": "Ba Lan", "ten_en": "Polish", "google": "pl", "edge": "pl-PL-ZofiaNeural",
           "nam": "pl-PL-MarekNeural", "nu": "pl-PL-ZofiaNeural",
           "voices": [("pl-PL-ZofiaNeural","Nữ — Zofia"),("pl-PL-MarekNeural","Nam — Marek")], "supertonic": False},
    "fa": {"ten": "Ba Tư", "ten_en": "Persian", "google": "fa", "edge": "fa-IR-DilaraNeural",
           "nam": "fa-IR-FaridNeural", "nu": "fa-IR-DilaraNeural",
           "voices": [("fa-IR-DilaraNeural","Nữ — Dilara"),("fa-IR-FaridNeural","Nam — Farid")], "supertonic": False},
    "bn": {"ten": "Bengal", "ten_en": "Bengali", "google": "bn", "edge": "bn-IN-TanishaaNeural",
           "nam": "bn-IN-BashkarNeural", "nu": "bn-IN-TanishaaNeural",
           "voices": [("bn-IN-TanishaaNeural","Nữ — Tanishaa"),("bn-IN-BashkarNeural","Nam — Bashkar")], "supertonic": False},
    "bs": {"ten": "Bosnia", "ten_en": "Bosnian", "google": "bs", "edge": "bs-BA-VesnaNeural",
           "nam": "bs-BA-GoranNeural", "nu": "bs-BA-VesnaNeural",
           "voices": [("bs-BA-VesnaNeural","Nữ — Vesna"),("bs-BA-GoranNeural","Nam — Goran")], "supertonic": False},
    "bg": {"ten": "Bulgaria", "ten_en": "Bulgarian", "google": "bg", "edge": "bg-BG-KalinaNeural",
           "nam": "bg-BG-BorislavNeural", "nu": "bg-BG-KalinaNeural",
           "voices": [("bg-BG-KalinaNeural","Nữ — Kalina"),("bg-BG-BorislavNeural","Nam — Borislav")], "supertonic": False},
    "pt": {"ten": "Bồ Đào Nha", "ten_en": "Portuguese", "google": "pt", "edge": "pt-BR-ThalitaMultilingualNeural",
           "nam": "M1", "nu": "F1",
           "voices": [("pt-BR-ThalitaMultilingualNeural","Nữ — ThalitaMultilingual"),("pt-BR-AntonioNeural","Nam — Antonio")], "supertonic": True},
    "ca": {"ten": "Catalan", "ten_en": "Catalan", "google": "ca", "edge": "ca-ES-JoanaNeural",
           "nam": "ca-ES-EnricNeural", "nu": "ca-ES-JoanaNeural",
           "voices": [("ca-ES-JoanaNeural","Nữ — Joana"),("ca-ES-EnricNeural","Nam — Enric")], "supertonic": False},
    "hr": {"ten": "Croatia", "ten_en": "Croatian", "google": "hr", "edge": "hr-HR-GabrijelaNeural",
           "nam": "hr-HR-SreckoNeural", "nu": "hr-HR-GabrijelaNeural",
           "voices": [("hr-HR-GabrijelaNeural","Nữ — Gabrijela"),("hr-HR-SreckoNeural","Nam — Srecko")], "supertonic": False},
    "he": {"ten": "Do Thái", "ten_en": "Hebrew", "google": "iw", "edge": "he-IL-HilaNeural",
           "nam": "he-IL-AvriNeural", "nu": "he-IL-HilaNeural",
           "voices": [("he-IL-HilaNeural","Nữ — Hila"),("he-IL-AvriNeural","Nam — Avri")], "supertonic": False},
    "en": {"ten": "English", "ten_en": "English", "google": "en", "edge": "en-US-AndrewNeural",
           "nam": "en-US-AndrewNeural", "nu": "en-US-EmmaNeural", "nam_uk":"en-GB-RyanNeural","nu_uk":"en-GB-SoniaNeural",
           "voices": [("en-US-EmmaNeural","Nữ — Ava"),("en-US-AndrewNeural","Nam — Andrew")], "supertonic": False},
    "et": {"ten": "Estonia", "ten_en": "Estonian", "google": "et", "edge": "et-EE-AnuNeural",
           "nam": "et-EE-KertNeural", "nu": "et-EE-AnuNeural",
           "voices": [("et-EE-AnuNeural","Nữ — Anu"),("et-EE-KertNeural","Nam — Kert")], "supertonic": False},
    "gl": {"ten": "Galicia", "ten_en": "Galician", "google": "gl", "edge": "gl-ES-SabelaNeural",
           "nam": "gl-ES-RoiNeural", "nu": "gl-ES-SabelaNeural",
           "voices": [("gl-ES-SabelaNeural","Nữ — Sabela"),("gl-ES-RoiNeural","Nam — Roi")], "supertonic": False},
    "ka": {"ten": "Georgia", "ten_en": "Georgian", "google": "ka", "edge": "ka-GE-EkaNeural",
           "nam": "ka-GE-GiorgiNeural", "nu": "ka-GE-EkaNeural",
           "voices": [("ka-GE-EkaNeural","Nữ — Eka"),("ka-GE-GiorgiNeural","Nam — Giorgi")], "supertonic": False},
    "gu": {"ten": "Gujarat", "ten_en": "Gujarati", "google": "gu", "edge": "gu-IN-DhwaniNeural",
           "nam": "gu-IN-NiranjanNeural", "nu": "gu-IN-DhwaniNeural",
           "voices": [("gu-IN-DhwaniNeural","Nữ — Dhwani"),("gu-IN-NiranjanNeural","Nam — Niranjan")], "supertonic": False},
    "hi": {"ten": "Hindi", "ten_en": "Hindi", "google": "hi", "edge": "hi-IN-SwaraNeural",
           "nam": "hi-IN-MadhurNeural", "nu": "hi-IN-SwaraNeural",
           "voices": [("hi-IN-SwaraNeural","Nữ — Swara"),("hi-IN-MadhurNeural","Nam — Madhur")], "supertonic": False},
    "hu": {"ten": "Hungary", "ten_en": "Hungarian", "google": "hu", "edge": "hu-HU-NoemiNeural",
           "nam": "hu-HU-TamasNeural", "nu": "hu-HU-NoemiNeural",
           "voices": [("hu-HU-NoemiNeural","Nữ — Noemi"),("hu-HU-TamasNeural","Nam — Tamas")], "supertonic": False},
    "el": {"ten": "Hy Lạp", "ten_en": "Greek", "google": "el", "edge": "el-GR-AthinaNeural",
           "nam": "el-GR-NestorasNeural", "nu": "el-GR-AthinaNeural",
           "voices": [("el-GR-AthinaNeural","Nữ — Athina"),("el-GR-NestorasNeural","Nam — Nestoras")], "supertonic": False},
    "nl": {"ten": "Hà Lan", "ten_en": "Dutch", "google": "nl", "edge": "nl-NL-ColetteNeural",
           "nam": "nl-NL-MaartenNeural", "nu": "nl-NL-ColetteNeural",
           "voices": [("nl-NL-ColetteNeural","Nữ — Colette"),("nl-NL-MaartenNeural","Nam — Maarten")], "supertonic": False},
    "ko": {"ten": "Hàn", "ten_en": "Korean", "google": "ko", "edge": "ko-KR-SunHiNeural",
           "nam": "M1", "nu": "F1",
           "voices": [("ko-KR-SunHiNeural","Nữ — SunHi"),("ko-KR-HyunsuMultilingualNeural","Nam — HyunsuMultilingual")], "supertonic": True},
    "is": {"ten": "Iceland", "ten_en": "Icelandic", "google": "is", "edge": "is-IS-GudrunNeural",
           "nam": "is-IS-GunnarNeural", "nu": "is-IS-GudrunNeural",
           "voices": [("is-IS-GudrunNeural","Nữ — Gudrun"),("is-IS-GunnarNeural","Nam — Gunnar")], "supertonic": False},
    "id": {"ten": "Indonesia", "ten_en": "Indonesian", "google": "id", "edge": "id-ID-GadisNeural",
           "nam": "id-ID-ArdiNeural", "nu": "id-ID-GadisNeural",
           "voices": [("id-ID-GadisNeural","Nữ — Gadis"),("id-ID-ArdiNeural","Nam — Ardi")], "supertonic": False},
    "ga": {"ten": "Ireland", "ten_en": "Irish", "google": "ga", "edge": "ga-IE-OrlaNeural",
           "nam": "ga-IE-ColmNeural", "nu": "ga-IE-OrlaNeural",
           "voices": [("ga-IE-OrlaNeural","Nữ — Orla"),("ga-IE-ColmNeural","Nam — Colm")], "supertonic": False},
    "jv": {"ten": "Java", "ten_en": "Javanese", "google": "jw", "edge": "jv-ID-SitiNeural",
           "nam": "jv-ID-DimasNeural", "nu": "jv-ID-SitiNeural",
           "voices": [("jv-ID-SitiNeural","Nữ — Siti"),("jv-ID-DimasNeural","Nam — Dimas")], "supertonic": False},
    "kn": {"ten": "Kannada", "ten_en": "Kannada", "google": "kn", "edge": "kn-IN-SapnaNeural",
           "nam": "kn-IN-GaganNeural", "nu": "kn-IN-SapnaNeural",
           "voices": [("kn-IN-SapnaNeural","Nữ — Sapna"),("kn-IN-GaganNeural","Nam — Gagan")], "supertonic": False},
    "kk": {"ten": "Kazakh", "ten_en": "Kazakh", "google": "kk", "edge": "kk-KZ-AigulNeural",
           "nam": "kk-KZ-DauletNeural", "nu": "kk-KZ-AigulNeural",
           "voices": [("kk-KZ-AigulNeural","Nữ — Aigul"),("kk-KZ-DauletNeural","Nam — Daulet")], "supertonic": False},
    "km": {"ten": "Khmer", "ten_en": "Khmer", "google": "km", "edge": "km-KH-SreymomNeural",
           "nam": "km-KH-PisethNeural", "nu": "km-KH-SreymomNeural",
           "voices": [("km-KH-SreymomNeural","Nữ — Sreymom"),("km-KH-PisethNeural","Nam — Piseth")], "supertonic": False},
    "lv": {"ten": "Latvia", "ten_en": "Latvian", "google": "lv", "edge": "lv-LV-EveritaNeural",
           "nam": "lv-LV-NilsNeural", "nu": "lv-LV-EveritaNeural",
           "voices": [("lv-LV-EveritaNeural","Nữ — Everita"),("lv-LV-NilsNeural","Nam — Nils")], "supertonic": False},
    "lt": {"ten": "Litva", "ten_en": "Lithuanian", "google": "lt", "edge": "lt-LT-OnaNeural",
           "nam": "lt-LT-LeonasNeural", "nu": "lt-LT-OnaNeural",
           "voices": [("lt-LT-OnaNeural","Nữ — Ona"),("lt-LT-LeonasNeural","Nam — Leonas")], "supertonic": False},
    "lo": {"ten": "Lào", "ten_en": "Lao", "google": "lo", "edge": "lo-LA-KeomanyNeural",
           "nam": "lo-LA-ChanthavongNeural", "nu": "lo-LA-KeomanyNeural",
           "voices": [("lo-LA-KeomanyNeural","Nữ — Keomany"),("lo-LA-ChanthavongNeural","Nam — Chanthavong")], "supertonic": False},
    "mk": {"ten": "Macedonia", "ten_en": "Macedonian", "google": "mk", "edge": "mk-MK-MarijaNeural",
           "nam": "mk-MK-AleksandarNeural", "nu": "mk-MK-MarijaNeural",
           "voices": [("mk-MK-MarijaNeural","Nữ — Marija"),("mk-MK-AleksandarNeural","Nam — Aleksandar")], "supertonic": False},
    "ml": {"ten": "Malayalam", "ten_en": "Malayalam", "google": "ml", "edge": "ml-IN-SobhanaNeural",
           "nam": "ml-IN-MidhunNeural", "nu": "ml-IN-SobhanaNeural",
           "voices": [("ml-IN-SobhanaNeural","Nữ — Sobhana"),("ml-IN-MidhunNeural","Nam — Midhun")], "supertonic": False},
    "ms": {"ten": "Malaysia", "ten_en": "Malay", "google": "ms", "edge": "ms-MY-YasminNeural",
           "nam": "ms-MY-OsmanNeural", "nu": "ms-MY-YasminNeural",
           "voices": [("ms-MY-YasminNeural","Nữ — Yasmin"),("ms-MY-OsmanNeural","Nam — Osman")], "supertonic": False},
    "mt": {"ten": "Malta", "ten_en": "Maltese", "google": "mt", "edge": "mt-MT-GraceNeural",
           "nam": "mt-MT-JosephNeural", "nu": "mt-MT-GraceNeural",
           "voices": [("mt-MT-GraceNeural","Nữ — Grace"),("mt-MT-JosephNeural","Nam — Joseph")], "supertonic": False},
    "mr": {"ten": "Marathi", "ten_en": "Marathi", "google": "mr", "edge": "mr-IN-AarohiNeural",
           "nam": "mr-IN-ManoharNeural", "nu": "mr-IN-AarohiNeural",
           "voices": [("mr-IN-AarohiNeural","Nữ — Aarohi"),("mr-IN-ManoharNeural","Nam — Manohar")], "supertonic": False},
    "my": {"ten": "Miến Điện", "ten_en": "Burmese", "google": "my", "edge": "my-MM-NilarNeural",
           "nam": "my-MM-ThihaNeural", "nu": "my-MM-NilarNeural",
           "voices": [("my-MM-NilarNeural","Nữ — Nilar"),("my-MM-ThihaNeural","Nam — Thiha")], "supertonic": False},
    "mn": {"ten": "Mông Cổ", "ten_en": "Mongolian", "google": "mn", "edge": "mn-MN-YesuiNeural",
           "nam": "mn-MN-BataaNeural", "nu": "mn-MN-YesuiNeural",
           "voices": [("mn-MN-YesuiNeural","Nữ — Yesui"),("mn-MN-BataaNeural","Nam — Bataa")], "supertonic": False},
    "nb": {"ten": "Na Uy", "ten_en": "Norwegian", "google": "no", "edge": "nb-NO-PernilleNeural",
           "nam": "nb-NO-FinnNeural", "nu": "nb-NO-PernilleNeural",
           "voices": [("nb-NO-PernilleNeural","Nữ — Pernille"),("nb-NO-FinnNeural","Nam — Finn")], "supertonic": False},
    "ne": {"ten": "Nepal", "ten_en": "Nepali", "google": "ne", "edge": "ne-NP-HemkalaNeural",
           "nam": "ne-NP-SagarNeural", "nu": "ne-NP-HemkalaNeural",
           "voices": [("ne-NP-HemkalaNeural","Nữ — Hemkala"),("ne-NP-SagarNeural","Nam — Sagar")], "supertonic": False},
    "ru": {"ten": "Nga", "ten_en": "Russian", "google": "ru", "edge": "ru-RU-SvetlanaNeural",
           "nam": "ru-RU-DmitryNeural", "nu": "ru-RU-SvetlanaNeural",
           "voices": [("ru-RU-SvetlanaNeural","Nữ — Svetlana"),("ru-RU-DmitryNeural","Nam — Dmitry")], "supertonic": False},
    "ja": {"ten": "Nhật", "ten_en": "Japanese", "google": "ja", "edge": "ja-JP-NanamiNeural",
           "nam": "M1", "nu": "F1",
           "voices": [("ja-JP-NanamiNeural","Nữ — Nanami"),("ja-JP-KeitaNeural","Nam — Keita")], "supertonic": True},
    "ps": {"ten": "Pashto", "ten_en": "Pashto", "google": "ps", "edge": "ps-AF-LatifaNeural",
           "nam": "ps-AF-GulNawazNeural", "nu": "ps-AF-LatifaNeural",
           "voices": [("ps-AF-LatifaNeural","Nữ — Latifa"),("ps-AF-GulNawazNeural","Nam — GulNawaz")], "supertonic": False},
    "fil": {"ten": "Philippines", "ten_en": "Filipino", "google": "tl", "edge": "fil-PH-BlessicaNeural",
           "nam": "fil-PH-AngeloNeural", "nu": "fil-PH-BlessicaNeural",
           "voices": [("fil-PH-BlessicaNeural","Nữ — Blessica"),("fil-PH-AngeloNeural","Nam — Angelo")], "supertonic": False},
    "fr": {"ten": "Pháp", "ten_en": "French", "google": "fr", "edge": "fr-FR-VivienneMultilingualNeural",
           "nam": "M1", "nu": "F1",
           "voices": [("fr-FR-VivienneMultilingualNeural","Nữ — VivienneMultilingual"),("fr-FR-RemyMultilingualNeural","Nam — RemyMultilingual")], "supertonic": True},
    "fi": {"ten": "Phần Lan", "ten_en": "Finnish", "google": "fi", "edge": "fi-FI-NooraNeural",
           "nam": "fi-FI-HarriNeural", "nu": "fi-FI-NooraNeural",
           "voices": [("fi-FI-NooraNeural","Nữ — Noora"),("fi-FI-HarriNeural","Nam — Harri")], "supertonic": False},
    "ro": {"ten": "Romania", "ten_en": "Romanian", "google": "ro", "edge": "ro-RO-AlinaNeural",
           "nam": "ro-RO-EmilNeural", "nu": "ro-RO-AlinaNeural",
           "voices": [("ro-RO-AlinaNeural","Nữ — Alina"),("ro-RO-EmilNeural","Nam — Emil")], "supertonic": False},
    "sr": {"ten": "Serbia", "ten_en": "Serbian", "google": "sr", "edge": "sr-RS-SophieNeural",
           "nam": "sr-RS-NicholasNeural", "nu": "sr-RS-SophieNeural",
           "voices": [("sr-RS-SophieNeural","Nữ — Sophie"),("sr-RS-NicholasNeural","Nam — Nicholas")], "supertonic": False},
    "si": {"ten": "Sinhala", "ten_en": "Sinhala", "google": "si", "edge": "si-LK-ThiliniNeural",
           "nam": "si-LK-SameeraNeural", "nu": "si-LK-ThiliniNeural",
           "voices": [("si-LK-ThiliniNeural","Nữ — Thilini"),("si-LK-SameeraNeural","Nam — Sameera")], "supertonic": False},
    "sk": {"ten": "Slovakia", "ten_en": "Slovak", "google": "sk", "edge": "sk-SK-ViktoriaNeural",
           "nam": "sk-SK-LukasNeural", "nu": "sk-SK-ViktoriaNeural",
           "voices": [("sk-SK-ViktoriaNeural","Nữ — Viktoria"),("sk-SK-LukasNeural","Nam — Lukas")], "supertonic": False},
    "sl": {"ten": "Slovenia", "ten_en": "Slovenian", "google": "sl", "edge": "sl-SI-PetraNeural",
           "nam": "sl-SI-RokNeural", "nu": "sl-SI-PetraNeural",
           "voices": [("sl-SI-PetraNeural","Nữ — Petra"),("sl-SI-RokNeural","Nam — Rok")], "supertonic": False},
    "so": {"ten": "Somali", "ten_en": "Somali", "google": "so", "edge": "so-SO-UbaxNeural",
           "nam": "so-SO-MuuseNeural", "nu": "so-SO-UbaxNeural",
           "voices": [("so-SO-UbaxNeural","Nữ — Ubax"),("so-SO-MuuseNeural","Nam — Muuse")], "supertonic": False},
    "su": {"ten": "Sunda", "ten_en": "Sundanese", "google": "su", "edge": "su-ID-TutiNeural",
           "nam": "su-ID-JajangNeural", "nu": "su-ID-TutiNeural",
           "voices": [("su-ID-TutiNeural","Nữ — Tuti"),("su-ID-JajangNeural","Nam — Jajang")], "supertonic": False},
    "sw": {"ten": "Swahili", "ten_en": "Swahili", "google": "sw", "edge": "sw-KE-ZuriNeural",
           "nam": "sw-KE-RafikiNeural", "nu": "sw-KE-ZuriNeural",
           "voices": [("sw-KE-ZuriNeural","Nữ — Zuri"),("sw-KE-RafikiNeural","Nam — Rafiki")], "supertonic": False},
    "cs": {"ten": "Séc", "ten_en": "Czech", "google": "cs", "edge": "cs-CZ-VlastaNeural",
           "nam": "cs-CZ-AntoninNeural", "nu": "cs-CZ-VlastaNeural",
           "voices": [("cs-CZ-VlastaNeural","Nữ — Vlasta"),("cs-CZ-AntoninNeural","Nam — Antonin")], "supertonic": False},
    "ta": {"ten": "Tamil", "ten_en": "Tamil", "google": "ta", "edge": "ta-IN-PallaviNeural",
           "nam": "ta-IN-ValluvarNeural", "nu": "ta-IN-PallaviNeural",
           "voices": [("ta-IN-PallaviNeural","Nữ — Pallavi"),("ta-IN-ValluvarNeural","Nam — Valluvar")], "supertonic": False},
    "te": {"ten": "Telugu", "ten_en": "Telugu", "google": "te", "edge": "te-IN-ShrutiNeural",
           "nam": "te-IN-MohanNeural", "nu": "te-IN-ShrutiNeural",
           "voices": [("te-IN-ShrutiNeural","Nữ — Shruti"),("te-IN-MohanNeural","Nam — Mohan")], "supertonic": False},
    "th": {"ten": "Thái", "ten_en": "Thai", "google": "th", "edge": "th-TH-PremwadeeNeural",
           "nam": "th-TH-NiwatNeural", "nu": "th-TH-PremwadeeNeural",
           "voices": [("th-TH-PremwadeeNeural","Nữ — Premwadee"),("th-TH-NiwatNeural","Nam — Niwat")], "supertonic": False},
    "tr": {"ten": "Thổ Nhĩ Kỳ", "ten_en": "Turkish", "google": "tr", "edge": "tr-TR-EmelNeural",
           "nam": "tr-TR-AhmetNeural", "nu": "tr-TR-EmelNeural",
           "voices": [("tr-TR-EmelNeural","Nữ — Emel"),("tr-TR-AhmetNeural","Nam — Ahmet")], "supertonic": False},
    "sv": {"ten": "Thụy Điển", "ten_en": "Swedish", "google": "sv", "edge": "sv-SE-SofieNeural",
           "nam": "sv-SE-MattiasNeural", "nu": "sv-SE-SofieNeural",
           "voices": [("sv-SE-SofieNeural","Nữ — Sofie"),("sv-SE-MattiasNeural","Nam — Mattias")], "supertonic": False},
    "zh": {"ten": "Trung", "ten_en": "Chinese", "google": "zh-CN", "edge": "zh-CN-XiaoxiaoNeural",
           "nam": "zh-CN-YunjianNeural", "nu": "zh-CN-XiaoxiaoNeural",
           "voices": [("zh-CN-XiaoxiaoNeural","Nữ — Xiaoxiao"),("zh-CN-YunjianNeural","Nam — Yunjian")], "supertonic": False},
    "es": {"ten": "Tây Ban Nha", "ten_en": "Spanish", "google": "es", "edge": "es-ES-XimenaNeural",
           "nam": "M1", "nu": "F1",
           "voices": [("es-ES-XimenaNeural","Nữ — Ximena"),("es-ES-AlvaroNeural","Nam — Alvaro")], "supertonic": True},
    "uk": {"ten": "Ukraina", "ten_en": "Ukrainian", "google": "uk", "edge": "uk-UA-PolinaNeural",
           "nam": "uk-UA-OstapNeural", "nu": "uk-UA-PolinaNeural",
           "voices": [("uk-UA-PolinaNeural","Nữ — Polina"),("uk-UA-OstapNeural","Nam — Ostap")], "supertonic": False},
    "ur": {"ten": "Urdu", "ten_en": "Urdu", "google": "ur", "edge": "ur-PK-UzmaNeural",
           "nam": "ur-PK-AsadNeural", "nu": "ur-PK-UzmaNeural",
           "voices": [("ur-PK-UzmaNeural","Nữ — Uzma"),("ur-PK-AsadNeural","Nam — Asad")], "supertonic": False},
    "uz": {"ten": "Uzbek", "ten_en": "Uzbek", "google": "uz", "edge": "uz-UZ-MadinaNeural",
           "nam": "uz-UZ-SardorNeural", "nu": "uz-UZ-MadinaNeural",
           "voices": [("uz-UZ-MadinaNeural","Nữ — Madina"),("uz-UZ-SardorNeural","Nam — Sardor")], "supertonic": False},
    "vi": {"ten": "Việt", "ten_en": "Vietnamese", "google": "vi", "edge": "vi-VN-HoaiMyNeural",
           "nam": "vi-VN-NamMinhNeural", "nu": "vi-VN-HoaiMyNeural",
           "voices": [("vi-VN-HoaiMyNeural","Nữ — HoaiMy"),("vi-VN-NamMinhNeural","Nam — NamMinh")], "supertonic": False},
    "cy": {"ten": "Wales", "ten_en": "Welsh", "google": "cy", "edge": "cy-GB-NiaNeural",
           "nam": "cy-GB-AledNeural", "nu": "cy-GB-NiaNeural",
           "voices": [("cy-GB-NiaNeural","Nữ — Nia"),("cy-GB-AledNeural","Nam — Aled")], "supertonic": False},
    "zu": {"ten": "Zulu", "ten_en": "Zulu", "google": "zu", "edge": "zu-ZA-ThandoNeural",
           "nam": "zu-ZA-ThembaNeural", "nu": "zu-ZA-ThandoNeural",
           "voices": [("zu-ZA-ThandoNeural","Nữ — Thando"),("zu-ZA-ThembaNeural","Nam — Themba")], "supertonic": False},
    "it": {"ten": "Ý", "ten_en": "Italian", "google": "it", "edge": "it-IT-ElsaNeural",
           "nam": "M1", "nu": "F1",
           "voices": [("it-IT-ElsaNeural","Nữ — Elsa"),("it-IT-GiuseppeMultilingualNeural","Nam — GiuseppeMultilingual")], "supertonic": True},
    "da": {"ten": "Đan Mạch", "ten_en": "Danish", "google": "da", "edge": "da-DK-ChristelNeural",
           "nam": "da-DK-JeppeNeural", "nu": "da-DK-ChristelNeural",
           "voices": [("da-DK-ChristelNeural","Nữ — Christel"),("da-DK-JeppeNeural","Nam — Jeppe")], "supertonic": False},
    "de": {"ten": "Đức", "ten_en": "German", "google": "de", "edge": "de-DE-SeraphinaMultilingualNeural",
           "nam": "M1", "nu": "F1",
           "voices": [("de-DE-SeraphinaMultilingualNeural","Nữ — SeraphinaMultilingual"),("de-DE-FlorianMultilingualNeural","Nam — FlorianMultilingual")], "supertonic": True},
    "ar": {"ten": "Ả Rập", "ten_en": "Arabic", "google": "ar", "edge": "ar-EG-SalmaNeural",
           "nam": "ar-EG-ShakirNeural", "nu": "ar-EG-SalmaNeural",
           "voices": [("ar-EG-SalmaNeural","Nữ — Salma"),("ar-EG-ShakirNeural","Nam — Shakir")], "supertonic": False},
}
HO_TRO = tuple(LANGS.keys())
_GOOGLE = {k: v["google"] for k, v in LANGS.items()}          # mã ngôn ngữ Google Translate (tl)
_VOICE = {k: v["edge"] for k, v in LANGS.items()}             # giọng edge-tts mặc định (fallback)


def _chuan(lang):
    lang = (lang or "").strip().lower()
    return lang if lang in HO_TRO else ""


def doc_cau_hinh():
    """Đọc app_config.json -> {'app_lang','target_lang'}. Thiếu/sai -> mặc định vi."""
    d = {"app_lang": "vi", "target_lang": "vi"}
    if os.path.exists(FILE_LANG):
        try:
            with open(FILE_LANG, encoding="utf-8") as f:
                raw = json.load(f)
            for k in d:
                if _chuan(raw.get(k)):
                    d[k] = _chuan(raw.get(k))
        except Exception:
            pass
    return d


def luu_cau_hinh(app_lang=None, target_lang=None):
    """Lưu cấu hình. Đổi app_lang sẽ đặt mặc định target_lang = app_lang (đồng bộ),
    trừ khi truyền target_lang riêng."""
    d = doc_cau_hinh()
    app_lang = _chuan(app_lang)
    target_lang = _chuan(target_lang)
    if app_lang:
        d["app_lang"] = app_lang
        if not target_lang:
            d["target_lang"] = app_lang
    if target_lang:
        d["target_lang"] = target_lang
    try:
        os.makedirs(os.path.dirname(FILE_LANG) or ".", exist_ok=True)
        with open(FILE_LANG, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return d


def target_lang():
    """Ngôn ngữ đích hiện tại. Ưu tiên env TARGET_LANG (cho subprocess), rồi tới config."""
    v = _chuan(os.environ.get("TARGET_LANG"))
    return v or doc_cau_hinh()["target_lang"]


def google_code(lang=None):
    return _GOOGLE.get(lang or target_lang(), "vi")


def voice_mac_dinh(lang=None):
    return _VOICE.get(lang or target_lang(), "vi-VN-HoaiMyNeural")


def la_nen_tang_trung(platform):
    return (platform or "").strip().lower() in NEN_TANG_TRUNG


def nguon_theo_nen_tang(platform):
    """Ngôn ngữ nguồn của video theo nền tảng: nền tảng Trung -> 'zh'; còn lại = ngôn ngữ đích."""
    return "zh" if la_nen_tang_trung(platform) else target_lang()


def platform_tu_duong_dan(path):
    """Đoán nền tảng từ đường dẫn .../data/<nền tảng>/... hoặc processed_videos/<nền tảng>/..."""
    parts = (path or "").replace("\\", "/").lower().split("/")
    for anchor in ("data", "processed_videos"):
        if anchor in parts:
            i = parts.index(anchor)
            if i + 1 < len(parts):
                return parts[i + 1]
    return ""


def can_dich(platform=None, src_lang=None, tgt=None):
    """Có cần dịch/lồng tiếng không? = nguồn KHÁC đích.
    Truyền src_lang trực tiếp, hoặc suy từ platform."""
    tgt = tgt or target_lang()
    if src_lang is None:
        src_lang = nguon_theo_nen_tang(platform)
    # 'zh' luôn khác đích (vi/en); nếu nguồn == đích thì khỏi dịch
    return src_lang != tgt
