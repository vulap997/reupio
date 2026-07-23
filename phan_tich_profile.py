# -*- coding: utf-8 -*-
"""Tổng hợp _render_profile.jsonl (do localize/_ResMon + dich_gemini_web ghi) → bảng quyết định tối ưu.

Trả lời bằng SỐ (không đoán): pha nào là nút thắt, GPU/CPU rảnh hay bận mỗi pha (overlap được không),
Gemini startup hay model chiếm thời gian (giữ-tab-sống đáng không), chuẩn hoá giây/phút-video & giây/1000-chars.

Dùng:  python phan_tich_profile.py [đường_dẫn_jsonl]
       (mặc định: $MC_DATA_DIR/_render_profile.jsonl hoặc ./_render_profile.jsonl)
"""
import os
import sys
import json


def _doc(path):
    renders, gem = [], []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if "gemini" in d:
                gem.append(d["gemini"])
            elif "stages" in d:
                renders.append(d)
    except FileNotFoundError:
        print("KHÔNG thấy file:", path)
        sys.exit(1)
    return renders, gem


def _stat(xs):
    """avg / median / p95 / max cho list số (bỏ None)."""
    xs = sorted(v for v in xs if v is not None)
    if not xs:
        return None
    n = len(xs)
    avg = sum(xs) / n
    med = xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2
    p95 = xs[min(n - 1, int(round(0.95 * (n - 1))))]
    return {"n": n, "avg": avg, "med": med, "p95": p95, "max": xs[-1]}


def _key(stage_name):
    """Gộp tên stage biến thiên ('ASR/OCR (đọc lời thoại 6 câu)') → khoá ổn định ('ASR/OCR')."""
    return stage_name.split(" (")[0].strip()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else (
        os.path.join(os.environ.get("MC_DATA_DIR") or ".", "_render_profile.jsonl"))
    renders, gem = _doc(path)
    print("FILE:", path)
    print("RENDERS:", len(renders), "| GEMINI calls:", len(gem))
    if not renders:
        print("Chưa có render nào — hãy render vài chục video rồi chạy lại."); return

    tot_min = sum((r.get("dur") or 0) for r in renders) / 60.0
    print("Tổng thời lượng video đã render: %.1f phút | tổng wall-time: %.1f phút"
          % (tot_min, sum((r.get("total") or 0) for r in renders) / 60.0))

    # gom theo stage-key
    by = {}   # key -> {time:[], cpu:[], gpu:[], ram:[], vram:[], spm:[](giây/phút-video), spk:[](giây/1000char)}
    order = []
    for r in renders:
        dur_min = (r.get("dur") or 0) / 60.0
        meta = r.get("meta") or {}
        chars = meta.get("chars_vi") or meta.get("chars_zh") or 0
        for st in r.get("stages") or []:
            if not isinstance(st, list) or len(st) < 2:
                continue
            k = _key(st[0]); secs = st[1]; res = st[2] if len(st) > 2 and isinstance(st[2], dict) else {}
            if k not in by:
                by[k] = {"time": [], "cpu": [], "gpu": [], "ram": [], "vram": [], "spm": [], "spk": []}
                order.append(k)
            b = by[k]
            b["time"].append(secs)
            b["cpu"].append(res.get("cpu")); b["gpu"].append(res.get("gpu"))
            b["ram"].append(res.get("ram")); b["vram"].append(res.get("vram"))
            if dur_min > 0:
                b["spm"].append(secs / dur_min)
            if chars > 0:
                b["spk"].append(secs / (chars / 1000.0))

    print("\n=== THEO STAGE (giây) — đâu là nút thắt + tài nguyên rảnh? ===")
    hdr = "%-14s %3s %7s %7s %7s %7s | %5s %5s %6s | %8s %8s"
    print(hdr % ("STAGE", "n", "avg", "med", "p95", "max", "cpu%", "gpu%", "vramMB", "s/phút-vid", "s/1000ch"))
    for k in order:
        b = by[k]
        t = _stat(b["time"]) or {}
        def g(lst, key="avg"):
            s = _stat(lst); return ("%.0f" % s[key]) if s else "-"
        spm = _stat(b["spm"]); spk = _stat(b["spk"])
        print(hdr % (k[:14], t.get("n", 0),
                     "%.1f" % t.get("avg", 0), "%.1f" % t.get("med", 0),
                     "%.1f" % t.get("p95", 0), "%.1f" % t.get("max", 0),
                     g(b["cpu"]), g(b["gpu"]), g(b["vram"]),
                     ("%.1f" % spm["avg"]) if spm else "-",
                     ("%.1f" % spk["avg"]) if spk else "-"))

    # === TỔNG s/phút-video THEO ĐỘ DÀI — câu hỏi quyết định: startup có dominate không? ===
    print("\n=== TỔNG s/phút-video THEO NHÓM ĐỘ DÀI (giảm khi dài hơn = STARTUP chiếm ưu thế) ===")
    buckets = [("<1ph", 0, 60), ("1-3ph", 60, 180), ("3-10ph", 180, 600), (">10ph", 600, 1e18)]
    co_bucket = False
    for nhan, lo, hi in buckets:
        rs = [r for r in renders if r.get("total") and r.get("dur") and lo <= r["dur"] < hi]
        if not rs:
            continue
        co_bucket = True
        spm = _stat([r["total"] / (r["dur"] / 60.0) for r in rs])
        print("  %-7s n=%-3d s/phút-video avg=%-5.0f med=%-5.0f  (tổng avg=%.0fs · dur avg=%.0fs)"
              % (nhan, len(rs), spm["avg"], spm["med"],
                 sum(r["total"] for r in rs) / len(rs), sum(r["dur"] for r in rs) / len(rs)))
    if co_bucket:
        print("  → s/phút-video GIẢM mạnh khi dài hơn = chi phí CỐ ĐỊNH (startup) lớn → Persistent Worker ĐÁNG.")
        print("    s/phút-video PHẲNG = compute scale theo độ dài → startup nhỏ → ưu tiên overlap/concurrency.")

    if gem:
        print("\n=== GEMINI WEB (startup vs model) — có nên giữ browser/tab sống? ===")
        o = _stat([x.get("open") for x in gem]); l = _stat([x.get("load") for x in gem]); w = _stat([x.get("wait") for x in gem])
        for nhan, s in [("open (khởi động Chrome)", o), ("load (hydrate SPA)", l), ("wait (model nghĩ)", w)]:
            if s:
                print("  %-26s avg=%.1fs  p95=%.1fs  max=%.1fs" % (nhan, s["avg"], s["p95"], s["max"]))
        if o and l and w:
            startup = o["avg"] + l["avg"]; total = startup + w["avg"]
            print("  → STARTUP (open+load) = %.0f%% thời gian Gemini ĐO ĐƯỢC (%.1fs/%.1fs)."
                  % (100 * startup / total if total else 0, startup, total))
        # OVERHEAD ẨN = (stage Dịch) − (GEMPROF open+load+wait) = respawn python + import playwright + chờ
        # ô-nhập + screenshot. GEMPROF chỉ đo TỪ sync_playwright; phần này nằm NGOÀI → đo gián tiếp.
        dich = by.get("Dịch")
        gem_tot = _stat([(x.get("open") or 0) + (x.get("load") or 0) + (x.get("wait") or 0) for x in gem])
        if dich and gem_tot:
            d_avg = (_stat(dich["time"]) or {}).get("avg", 0)
            overhead = d_avg - gem_tot["avg"]
            print("  → OVERHEAD ẨN (respawn python+playwright, NGOÀI GEMPROF) ≈ %.1fs/render"
                  % overhead + "  (stage Dịch %.1fs − Gemini-inner %.1fs)" % (d_avg, gem_tot["avg"]))
            print("    Đây là phần Persistent Worker (giữ python+browser sống) cắt được — thường LỚN hơn cả model.")

    print("\n=== GỢI Ý ĐỌC SỐ ===")
    print("  • gpu% thấp ở MỌI stage + vram thừa  → GPU rảnh: render concurrency=2 / overlap KHẢ THI.")
    print("  • cpu% cao 1 stage, gpu% thấp stage khác → overlap CHÉO 2 video bù tài nguyên.")
    print("  • s/phút-video ổn định giữa video ngắn↔dài → đó là compute thật (đáng tối ưu).")
    print("  • s/phút-video GIẢM mạnh khi video dài hơn → phần lớn là STARTUP cố định (preload/giữ-tab).")


if __name__ == "__main__":
    main()
