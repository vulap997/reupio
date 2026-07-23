# -*- coding: utf-8 -*-
"""
OCR — quét chữ trong ảnh bằng Tesseract (offline). Hỗ trợ tiếng Việt + Anh.

Dùng:
  python ocr_anh.py --path anh.png                 # in text
  python ocr_anh.py --path anh_chup/reddit/xxx     # OCR cả thư mục -> ocr.json
  python ocr_anh.py --path anh.png --lang vie+eng

Mặc định lang = OCR_LANG (env) hoặc "vie+eng".
Cần: tesseract.exe (winget UB-Mannheim.TesseractOCR) + tessdata/ (eng,vie) trong dự án.
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
TESSDATA_DIR = os.path.join(THU_MUC_GOC, "tessdata")
ANH_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def log(msg):
    print("LOG:" + msg, flush=True)


def tim_tesseract():
    """Trả đường dẫn tesseract.exe: BUNDLE (vendor/tesseract) -> PATH -> các vị trí cài quen thuộc."""
    import shutil
    here = os.path.dirname(os.path.abspath(__file__))
    # bundle kèm app: app đóng gói (file ở app-src) -> ../vendor ; dev (repo) -> desktop/vendor
    for b in (os.path.join(here, "..", "vendor", "tesseract", "tesseract.exe"),
              os.path.join(here, "desktop", "vendor", "tesseract", "tesseract.exe")):
        if os.path.isfile(b):
            return os.path.abspath(b)
    p = shutil.which("tesseract")
    if p:
        return p
    for c in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    ):
        if os.path.isfile(c):
            return c
    return ""


_SAN_SANG = {"ok": False, "loi": ""}


def chuan_bi():
    """Cấu hình pytesseract 1 lần. Trả (ok, thông_báo_lỗi)."""
    if _SAN_SANG["ok"]:
        return True, ""
    try:
        import pytesseract  # noqa
    except Exception:
        return False, "Thiếu pytesseract — chạy: pip install pytesseract"
    exe = tim_tesseract()
    if not exe:
        return False, ("Chưa cài Tesseract. Cài bằng: winget install -e --id UB-Mannheim.TesseractOCR")
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = exe
    _SAN_SANG["ok"] = True
    _SAN_SANG["exe"] = exe
    return True, ""


def _set_tessdata(lang):
    """Chọn thư mục tessdata qua env TESSDATA_PREFIX (tránh path có dấu cách trong --config).
    Ưu tiên tessdata/ cục bộ (có vie) nếu đủ ngôn ngữ; nếu thiếu dùng tessdata mặc định của Tesseract."""
    if os.path.isdir(TESSDATA_DIR):
        thieu = [l for l in lang.split("+") if not os.path.isfile(os.path.join(TESSDATA_DIR, f"{l}.traineddata"))]
        if not thieu:
            os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR
            return
    exe = _SAN_SANG.get("exe", "")
    if exe:
        os.environ["TESSDATA_PREFIX"] = os.path.join(os.path.dirname(exe), "tessdata")


def ocr_anh(path, lang="vie+eng"):
    """OCR 1 ảnh -> chuỗi text (đã strip). Lỗi -> chuỗi rỗng."""
    ok, msg = chuan_bi()
    if not ok:
        raise RuntimeError(msg)
    import pytesseract
    from PIL import Image
    _set_tessdata(lang)
    img = Image.open(path)
    # Phóng to ảnh nhỏ để OCR chính xác hơn (text rõ vẫn lợi)
    if img.width < 1000:
        r = 1000 / img.width
        img = img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)
    return pytesseract.image_to_string(img, lang=lang, config="--oem 1 --psm 6").strip()


def ocr_thu_muc(folder, lang="vie+eng"):
    """OCR mọi ảnh trong thư mục -> ghi ocr.json -> trả dict {tên_file: text}."""
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(ANH_EXT))
    ket_qua = {}
    for f in files:
        try:
            ket_qua[f] = ocr_anh(os.path.join(folder, f), lang)
            log(f"📝 {f}: {len(ket_qua[f])} ký tự")
        except Exception as e:
            ket_qua[f] = ""
            log(f"⚠ Lỗi {f}: {str(e)[:120]}")
    with open(os.path.join(folder, "ocr.json"), "w", encoding="utf-8") as fp:
        json.dump(ket_qua, fp, ensure_ascii=False, indent=2)
    return ket_qua


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="ảnh hoặc thư mục")
    ap.add_argument("--lang", default=os.environ.get("OCR_LANG", "vie+eng"))
    a = ap.parse_args()

    ok, msg = chuan_bi()
    if not ok:
        log("⚠ " + msg)
        print("OCR_DONE 0", flush=True)
        return

    path = a.path
    if os.path.isfile(path):
        try:
            print(ocr_anh(path, a.lang))
            print("\nOCR_DONE 1", flush=True)
        except Exception as e:
            log(f"⚠ Lỗi OCR: {str(e)[:160]}")
            print("OCR_DONE 0", flush=True)
        return

    if not os.path.isdir(path):
        log(f"⚠ Không thấy: {path}")
        print("OCR_DONE 0", flush=True)
        return

    kq = ocr_thu_muc(path, a.lang)
    log(f"✔ OCR {len(kq)} ảnh → {os.path.relpath(os.path.join(path, 'ocr.json'), THU_MUC_GOC)}")
    print(f"OCR_DONE {len(kq)}", flush=True)


if __name__ == "__main__":
    main()
