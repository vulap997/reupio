# -*- coding: utf-8 -*-
"""
DỊCH BẰNG AI (Groq / Gemini, free-tier) — Option 1: Google dịch thô → AI sửa cả phụ đề 1 lần.

- Quản lý NHIỀU API key (mã hoá DPAPI qua bao_mat_key), tự XOAY key khi 1 key hết quota/lỗi.
- Kiểm tra key bằng request rẻ (liệt kê model — 0 token).
- Phân biệt key SAI (bỏ) vs HẾT QUOTA (nghỉ, xoay lại sau).

Kho key: bao_mat_key "ai_keys" = JSON list [{id, provider, key, trang_thai, msg}].
Cấu hình mặc định: ai_cau_hinh.json {provider, model}.
"""
import datetime
import json
import os
import re
import time
import threading
import urllib.error
import urllib.request

import bao_mat_key

_KHO_LOCK = threading.RLock()   # bảo vệ kho key khi NHIỀU luồng dịch song song đọc/ghi usage

THU_MUC_GOC = os.path.dirname(os.path.abspath(__file__))
FILE_CAU_HINH = os.path.join(THU_MUC_GOC, "ai_cau_hinh.json")
KHO = "ai_keys"  # tên trong bao_mat_key

PROVIDERS = {
    "groq": {
        "ten": "Groq",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b"],
        "chat": "https://api.groq.com/openai/v1/chat/completions",
        "list": "https://api.groq.com/openai/v1/models",
        "key_url": "https://console.groq.com/keys",
    },
    "gemini": {
        "ten": "Gemini (Google AI Studio)",
        "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash"],
        "list": "https://generativelanguage.googleapis.com/v1beta/models",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "ollama": {  # Ollama Cloud (ollama.com) — OpenAI-compatible, free-tier, key tại ollama.com/settings/keys
        "ten": "Ollama Cloud",
        # CHỈ gemma3:27b: non-reasoning, NHANH, bám format. KHÔNG dùng qwen3/glm/deepseek (reasoning
        # hoặc chậm → nghĩ hết token → trả rỗng/timeout → dịch phình/lệch dòng trên video dài).
        "models": ["gemma3:27b"],
        "chat": "https://ollama.com/v1/chat/completions",
        "list": "https://ollama.com/v1/models",
        "key_url": "https://ollama.com/settings/keys",
    },
    "ollama_local": {  # Ollama CHẠY MÁY (localhost) — KHÔNG cần key, model chạy trên GPU rảnh, FREE
        "ten": "Ollama Local (máy bạn)",
        # qwen2.5 = NON-THINKING (đúng nhu cầu); 1.5b/3b nhẹ vừa GPU 4GB. `ollama pull qwen2.5:1.5b` trước.
        "models": ["qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:7b"],
        "chat": "http://localhost:11434/v1/chat/completions",
        "list": "http://localhost:11434/v1/models",
        "key_url": "",
    },
}
# Provider dùng API kiểu OpenAI (Bearer + /v1/chat/completions)
OPENAI_STYLE = ("groq", "ollama", "ollama_local")
MAC_DINH = {"provider": "ollama", "model": "gemma3:27b"}


# ---------------- Kho key ----------------
def _doc_kho():
    raw = bao_mat_key.doc_key(KHO)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except Exception:
        return []


def _ghi_kho(ds):
    with _KHO_LOCK:
        bao_mat_key.luu_key(json.dumps(ds, ensure_ascii=False), KHO)


def _che(key):
    key = key or ""
    return (key[:6] + "…" + key[-4:]) if len(key) > 12 else "…"


# ---------------- Theo dõi sử dụng (request + token / NGÀY, theo từng key) ----------------
# Hạn mức REQUEST/ngày free-tier (ước lượng — chỉnh cho khớp gói của bạn). Dùng làm mẫu số thanh quota.
QUOTA_REQ_NGAY = {"gemini": 200, "groq": 1000, "ollama": 1000}


def _hom_nay():
    return datetime.date.today().isoformat()


def _now_str():
    return datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y")


def _dung_homnay(k):
    """Dict usage HÔM NAY của key; tự reset khi sang ngày mới (giữ lại 'lan_cuoi')."""
    d = k.get("dung") or {}
    if d.get("ngay") != _hom_nay():
        return {"ngay": _hom_nay(), "req": 0, "tok_in": 0, "tok_out": 0, "lan_cuoi": d.get("lan_cuoi", "")}
    return {"ngay": d["ngay"], "req": d.get("req", 0), "tok_in": d.get("tok_in", 0),
            "tok_out": d.get("tok_out", 0), "lan_cuoi": d.get("lan_cuoi", "")}


def ghi_su_dung(kid=None, key=None, tok_in=0, tok_out=0):
    """+1 request + cộng token (theo NGÀY, tự reset) + cập nhật lần cuối dùng cho 1 key (theo id HOẶC value)."""
    with _KHO_LOCK:   # read-modify-write nguyên tử: nhiều luồng dịch không ghi đè usage của nhau
        ds = _doc_kho()
        for k in ds:
            if (kid and k["id"] == kid) or (key and k["key"] == key):
                d = _dung_homnay(k)
                d["req"] += 1
                d["tok_in"] += int(tok_in or 0)
                d["tok_out"] += int(tok_out or 0)
                d["lan_cuoi"] = _now_str()
                k["dung"] = d
                _ghi_kho(ds)
                return


def bat_tat_key(kid, bat):
    """Bật/Tắt 1 key (key tắt sẽ bị goi_ai bỏ qua khi xoay)."""
    ds = _doc_kho()
    for k in ds:
        if k["id"] == kid:
            k["bat"] = bool(bat)
            _ghi_kho(ds)
            return {"ok": True, "bat": k["bat"]}
    return {"ok": False, "msg": "Không thấy key."}


def sua_nhan(kid, nhan):
    """Đặt nhãn (label) cho key — dễ nhận ra key nào của ai."""
    ds = _doc_kho()
    for k in ds:
        if k["id"] == kid:
            k["nhan"] = (nhan or "").strip()[:40]
            _ghi_kho(ds)
            return {"ok": True, "nhan": k["nhan"]}
    return {"ok": False, "msg": "Không thấy key."}


def danh_sach():
    """Danh sách key + usage HÔM NAY cho UI. Tiện thể DỌN key của provider đã gỡ (vd 9router cũ)."""
    ds = _doc_kho()
    sach = [k for k in ds if k.get("provider") in PROVIDERS]
    if len(sach) != len(ds):
        _ghi_kho(sach)   # bỏ hẳn key của provider không còn hỗ trợ
    out = []
    for k in sach:
        d = _dung_homnay(k)
        out.append({"id": k["id"], "provider": k["provider"], "key_che": _che(k["key"]),
                    "trang_thai": k.get("trang_thai", "chua"), "msg": k.get("msg", ""),
                    "nhan": k.get("nhan", ""), "bat": k.get("bat", True) is not False,
                    "req": d["req"], "tok_in": d["tok_in"], "tok_out": d["tok_out"],
                    "lan_cuoi": d["lan_cuoi"], "quota_req": QUOTA_REQ_NGAY.get(k["provider"], 0)})
    return out


def them_key(provider, key):
    key = (key or "").strip()
    if provider not in PROVIDERS or not key:
        return {"ok": False, "msg": "Thiếu provider hoặc key."}
    ds = _doc_kho()
    if any(k["key"] == key for k in ds):
        return {"ok": False, "msg": "Key này đã có."}
    kid = "%s_%d_%d" % (provider, len(ds) + 1, int(time.time()) % 100000)
    ds.append({"id": kid, "provider": provider, "key": key, "trang_thai": "chua", "msg": ""})
    _ghi_kho(ds)
    return {"ok": True, "id": kid}


def xoa_key(kid):
    _ghi_kho([k for k in _doc_kho() if k["id"] != kid])
    return {"ok": True}


def cau_hinh():
    if os.path.exists(FILE_CAU_HINH):
        try:
            with open(FILE_CAU_HINH, encoding="utf-8") as f:
                c = json.load(f)
            prov = c.get("provider", MAC_DINH["provider"])
            if prov not in PROVIDERS:   # vd cấu hình cũ trỏ "9router" (đã gỡ) -> về mặc định
                return dict(MAC_DINH)
            model = c.get("model", MAC_DINH["model"])
            if model not in PROVIDERS[prov].get("models", []):   # model đã gỡ (vd qwen3-next:80b) -> ép model tốt
                model = MODEL_DICH_TOT.get(prov) or (PROVIDERS[prov].get("models") or [MAC_DINH["model"]])[0]
            return {"provider": prov, "model": model}
        except Exception:
            pass
    return dict(MAC_DINH)


def luu_cau_hinh(provider, model):
    with open(FILE_CAU_HINH, "w", encoding="utf-8") as f:
        json.dump({"provider": provider, "model": model}, f, ensure_ascii=False)
    return {"ok": True}


# Model dịch ZH→VI tốt nhất cho từng provider (người dùng KHỎI phải chọn)
MODEL_DICH_TOT = {
    "gemini": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    # gemma3:27b = non-reasoning, NHANH, bám format. KHÔNG dùng qwen3-next:80b (reasoning →
    # nghĩ hết token → trả rỗng/timeout → dịch phình/lệch dòng trên video dài).
    "ollama": "gemma3:27b",
    "ollama_local": "qwen2.5:1.5b",   # local GPU, non-thinking, free
}


def them_va_dung(provider, key):
    """Thêm key + kiểm tra + TỰ chọn model dịch tốt nhất + đặt làm mặc định. 1 bước cho người dùng."""
    res = them_key(provider, key)
    if not res.get("ok"):
        return res
    chk = kiem_tra_id(res["id"])
    model = MODEL_DICH_TOT.get(provider) or (PROVIDERS.get(provider, {}).get("models") or [""])[0]
    if chk.get("trang_thai") == "ok":
        luu_cau_hinh(provider, model)
        return {"ok": True, "msg": "✅ Đã thêm + dùng làm AI dịch: %s." % PROVIDERS[provider]["ten"], "id": res["id"]}
    return {"ok": False, "id": res["id"],
            "msg": "Đã lưu key nhưng kiểm tra báo lỗi: %s. Bấm 'Kiểm tra lại' sau, hoặc thử dịch vụ khác." % chk.get("msg", "")}


def them_nhieu_key(provider, text):
    """Thêm NHIỀU key 1 lần (mỗi dòng / phẩy 1 key) → tránh hết quota nhờ tự xoay key.
    Bỏ key trùng; đặt provider làm AI dịch mặc định + kiểm tra 1 key cho biết trạng thái."""
    import re
    if provider not in PROVIDERS:
        return {"ok": False, "msg": "Thiếu provider."}
    keys = [k.strip() for k in re.split(r"[\n,]+", text or "") if k.strip()]
    if not keys:
        return {"ok": False, "msg": "Chưa dán key nào."}
    them, trung, id_dau = 0, 0, None
    for k in keys:
        r = them_key(provider, k)
        if r.get("ok"):
            them += 1
            id_dau = id_dau or r["id"]
        else:
            trung += 1
    if them == 0:
        return {"ok": False, "msg": "Tất cả %d key đã có sẵn (không thêm mới)." % trung}
    model = MODEL_DICH_TOT.get(provider) or (PROVIDERS.get(provider, {}).get("models") or [""])[0]
    luu_cau_hinh(provider, model)
    if id_dau:
        kiem_tra_id(id_dau)   # kiểm 1 key để báo trạng thái ngay
    return {"ok": True, "them": them, "trung": trung,
            "msg": "✅ Đã thêm %d key%s cho %s, đặt làm AI dịch (tự xoay khi hết quota)." %
                   (them, (" (%d trùng, bỏ qua)" % trung if trung else ""), PROVIDERS[provider]["ten"])}


def phat_hien_provider(key):
    """Đoán provider từ ĐỊNH DẠNG key: AIza…→gemini, gsk_…→groq. Không rõ → None (sẽ xác thực thử)."""
    k = (key or "").strip()
    if k.startswith("AIza"):
        return "gemini"
    if k.startswith("gsk_"):
        return "groq"
    return None


def them_tu_dong(text):
    """1 Ô CHUNG: nhận 1 hoặc nhiều key (mỗi dòng / phẩy), TỰ phát hiện provider rồi thêm + kiểm tra.
    - Prefix rõ (AIza/gsk_) → dùng luôn; không rõ (vd Ollama) → THỬ xác thực gemini/groq/ollama,
      chọn provider nào key chạy được.
    - Đặt provider được thêm nhiều nhất làm AI dịch mặc định."""
    keys = [k.strip() for k in re.split(r"[\n,]+", text or "") if k.strip()]
    if not keys:
        return {"ok": False, "msg": "Chưa dán key nào."}
    them, trung, khong_ro = 0, 0, 0
    theo_provider = {}   # đếm key DÙNG ĐƯỢC NGAY (ok) — để chọn AI mặc định
    da_them = {}         # đếm mọi key thêm được (kể cả hết quota) — cho thông báo
    for k in keys:
        prov = phat_hien_provider(k)
        thu = [prov] if prov else ["gemini", "groq", "ollama"]
        chon, tt_chon = None, None
        for c in thu:
            tt, _msg = kiem_tra_key(c, k)
            if tt in ("ok", "quota"):   # xác thực được (quota = key ĐÚNG, chỉ hết hạn mức)
                chon, tt_chon = c, tt
                break
        if not chon:
            chon = prov   # verify lỗi mạng/sai nhưng prefix đã chỉ rõ → vẫn theo prefix
        if not chon:
            khong_ro += 1
            continue
        r = them_key(chon, k)
        if not r.get("ok"):
            trung += 1
            continue
        kiem_tra_id(r["id"])   # cập nhật trạng thái/hạn mức ngay
        them += 1
        da_them[chon] = da_them.get(chon, 0) + 1
        if tt_chon == "ok":    # CHỈ key dùng được NGAY mới được tính làm mặc định (tránh key hết quota chiếm chỗ)
            theo_provider[chon] = theo_provider.get(chon, 0) + 1
    if them == 0:
        return {"ok": False,
                "msg": "Không thêm được key mới (%d trùng, %d không nhận ra provider)." % (trung, khong_ro)}
    chi_tiet = ", ".join("%s %d" % (PROVIDERS[p]["ten"], n) for p, n in da_them.items())
    duoi = (" · %d trùng" % trung if trung else "") + (" · %d không nhận ra" % khong_ro if khong_ro else "")
    if theo_provider:   # có key dùng được → đặt provider được thêm nhiều nhất làm mặc định
        prov_chinh = max(theo_provider, key=theo_provider.get)
        luu_cau_hinh(prov_chinh, MODEL_DICH_TOT.get(prov_chinh) or PROVIDERS[prov_chinh]["models"][0])
        return {"ok": True, "them": them,
                "msg": "✅ Đã thêm %d key (%s)%s. AI dịch mặc định: %s." %
                       (them, chi_tiet, duoi, PROVIDERS[prov_chinh]["ten"])}
    return {"ok": True, "them": them,   # thêm được nhưng chưa key nào dùng được ngay → KHÔNG đổi mặc định
            "msg": "⚠ Đã thêm %d key (%s)%s nhưng CHƯA key nào dùng được ngay (hết hạn mức/sai) → giữ nguyên AI mặc định cũ." %
                   (them, chi_tiet, duoi)}


def key_groq_dung_duoc():
    """Lấy 1 key Groq DÙNG ĐƯỢC trong kho (cho Trợ lý AI chat — cần tool-calling).
    Bỏ qua key đã đánh dấu 'sai'. '' nếu không có key Groq dùng được (để nhắc người dùng thêm)."""
    for k in _doc_kho():
        if k["provider"] == "groq" and k.get("trang_thai") != "sai":
            return k["key"]
    return ""


def trang_thai_ai():
    """Trạng thái AI dịch hiện tại (cho banner đơn giản)."""
    cfg = cau_hinh()
    ks = [k for k in _doc_kho() if k["provider"] == cfg["provider"]]
    san_sang = any(k.get("trang_thai") == "ok" for k in ks)
    return {"provider": cfg["provider"],
            "ten": PROVIDERS.get(cfg["provider"], {}).get("ten", cfg["provider"]),
            "model": cfg["model"], "co_key": bool(ks), "san_sang": san_sang}


# ---------------- Gọi HTTP ----------------
def _http(url, data=None, headers=None, timeout=60):
    # Groq nằm sau Cloudflare: UA mặc định 'Python-urllib' bị chặn 403 (error 1010) → phải giả UA trình duyệt.
    h = {"User-Agent": "Mozilla/5.0"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8")


def kiem_tra_key(provider, key):
    """Test key bằng request RẺ (chat/generate 1 token). Trả (trang_thai, msg)."""
    try:
        if provider == "groq":
            # Test bằng CHAT 1 token (giống lúc dịch thật) thay vì /v1/models → bắt đúng key hết quota (429)
            # & xác nhận key thật sự gọi được model. Dùng model 8b rẻ nhất cho đỡ tốn khi 'kiểm tra tất cả key'.
            body = json.dumps({"model": "llama-3.1-8b-instant",
                               "messages": [{"role": "user", "content": "hi"}],
                               "max_tokens": 1, "stream": False}).encode("utf-8")
            _http(PROVIDERS["groq"]["chat"], data=body,
                  headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, timeout=20)
        elif provider == "ollama":
            # /v1/models công khai → test bằng chat 1 token (rẻ) để thực sự xác thực key
            body = json.dumps({"model": PROVIDERS["ollama"]["models"][0],
                               "messages": [{"role": "user", "content": "hi"}],
                               "max_tokens": 1, "stream": False}).encode("utf-8")
            _http(PROVIDERS["ollama"]["chat"], data=body,
                  headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, timeout=25)
        elif provider == "gemini":
            # generateContent 1 token: list-models KHÔNG bắt được key "quota 0" (dạng AQ.) → phải gọi SINH thật
            url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
                   % (MODEL_DICH_TOT.get("gemini", "gemini-2.0-flash"), key))
            body = json.dumps({"contents": [{"parts": [{"text": "hi"}]}],
                               "generationConfig": {"maxOutputTokens": 1}}).encode("utf-8")
            _http(url, data=body, headers={"Content-Type": "application/json"}, timeout=20)
        else:
            return "sai", "Provider lạ"
        return "ok", "Dùng được"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "sai", "Key sai / không có quyền"
        if e.code == 429:
            return "quota", "Hết quota (thử lại sau)"
        return "sai", "HTTP %d" % e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        # Lỗi MẠNG/timeout (không phải key sai) → KHÔNG loại key, để 'chua' cho kiểm lại sau
        return "chua", "Mạng chậm/timeout — thử lại (key có thể vẫn dùng được)"
    except Exception as e:
        return "sai", str(e)[:80]


def kiem_tra_id(kid):
    ds = _doc_kho()
    for k in ds:
        if k["id"] == kid:
            tt, msg = kiem_tra_key(k["provider"], k["key"])
            k["trang_thai"], k["msg"] = tt, msg
            _ghi_kho(ds)
            return {"ok": True, "trang_thai": tt, "msg": msg}
    return {"ok": False, "msg": "Không thấy key."}


def kiem_tra_tat_ca():
    ds = _doc_kho()
    for k in ds:
        k["trang_thai"], k["msg"] = kiem_tra_key(k["provider"], k["key"])
    _ghi_kho(ds)
    return {"ok": True, "keys": danh_sach()}


def lay_models(provider):
    """Danh sách model gợi ý cho provider."""
    return PROVIDERS.get(provider, {}).get("models", [])


# ---------------- Gọi AI (1 prompt) + xoay key ----------------
def _noi_dung_chat(txt):
    """Lấy (content, tok_in, tok_out) từ phản hồi chat OpenAI-style. CHỊU cả JSON thường
    LẪN SSE streaming — một số gateway luôn stream 'data: {...}' nên json.loads vỡ."""
    txt = (txt or "").strip()
    try:                                    # 1) JSON thường (non-stream)
        d = json.loads(txt)
        u = d.get("usage") or {}
        return (d["choices"][0]["message"]["content"],
                u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
    except (ValueError, KeyError, IndexError, TypeError):
        pass
    parts = []                              # 2) SSE: gom các dòng 'data: {...}'
    for line in txt.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            ch = json.loads(data)["choices"][0]
            piece = (ch.get("delta") or ch.get("message") or {}).get("content")
            if piece:
                parts.append(piece)
        except (ValueError, KeyError, IndexError, TypeError):
            continue
    if parts:
        return "".join(parts), 0, 0
    raise RuntimeError("Không parse được phản hồi chat: " + txt[:150])


def _goi_provider(provider, model, key, prompt):
    """Trả (text, tok_in, tok_out) — token đọc từ 'usage' của response (để theo dõi quota)."""
    if provider in OPENAI_STYLE:
        body = json.dumps({"model": model, "temperature": 0.2, "stream": False,
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        hdr = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        _s, txt = _http(PROVIDERS[provider]["chat"], data=body, headers=hdr, timeout=120)
        return _noi_dung_chat(txt)
    elif provider == "gemini":
        url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
               % (model, key))
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"temperature": 0.2}}).encode("utf-8")
        _s, txt = _http(url, data=body, headers={"Content-Type": "application/json"}, timeout=120)
        d = json.loads(txt)
        u = d.get("usageMetadata") or {}
        return (d["candidates"][0]["content"]["parts"][0]["text"],
                u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0))
    raise RuntimeError("Provider lạ: " + provider)


def goi_ai(prompt, log_fn=print):
    """Gọi AI với key của provider mặc định, tự XOAY key khi 429/lỗi. Trả text hoặc raise."""
    cfg = cau_hinh()
    provider, model = cfg["provider"], cfg["model"]
    ds = _doc_kho()
    keys = [k for k in ds if k["provider"] == provider and k.get("trang_thai") != "sai"
            and k.get("bat", True) is not False]   # bỏ key đã TẮT
    if not keys and provider == "ollama_local":
        keys = [{"id": "ollama_local", "key": "ollama", "provider": "ollama_local"}]   # local KHÔNG cần key thật
    if not keys:
        raise RuntimeError("Chưa có API key dùng được cho %s. Vào tab API Keys AI để thêm." % provider)
    loi_cuoi = ""
    for k in keys:
        try:
            txt, tok_in, tok_out = _goi_provider(provider, model, k["key"], prompt)
            ghi_su_dung(kid=k["id"], tok_in=tok_in, tok_out=tok_out)   # đếm request + token hôm nay
            return _bo_think(txt)   # bỏ khối <think> nếu model reasoning lỡ xuất
        except urllib.error.HTTPError as e:
            if e.code == 429:
                k["trang_thai"], k["msg"] = "quota", "Hết quota — xoay key khác"
                _ghi_kho(ds)
                log_fn("LOG:🔁 Key %s hết quota → đổi key" % _che(k["key"]))
                loi_cuoi = "429 quota"
                continue
            if e.code in (401, 403):
                k["trang_thai"], k["msg"] = "sai", "Key sai"
                _ghi_kho(ds)
                loi_cuoi = "key sai"
                continue
            loi_cuoi = "HTTP %d" % e.code
            continue
        except Exception as e:
            loi_cuoi = str(e)[:80]
            continue
    raise RuntimeError("Tất cả key %s đều lỗi (%s)." % (provider, loi_cuoi))


# translation_memory/: bộ quy tắc dịch theo CHỦ ĐỀ, USER tự sửa/thêm. File ALWAYS luôn nạp; còn lại theo chu_de.
_TM_ALWAYS = ["01_general_rule", "02_name_dictionary", "10_subtitle_format"]
CHU_DE_FILES = {
    "phim": ["03_movie_review", "04_chinese_drama"], "review": ["03_movie_review"],
    "co_trang": ["03_movie_review", "05_wuxia_xianxia"], "tien_hiep": ["03_movie_review", "05_wuxia_xianxia"],
    "wuxia": ["05_wuxia_xianxia"], "xianxia": ["05_wuxia_xianxia"],
    "hien_dai": ["04_chinese_drama", "06_modern_drama"], "drama": ["04_chinese_drama"],
    "mukbang": ["07_mukbang_food"], "an_uong": ["07_mukbang_food"], "cooking": ["07_mukbang_food"],
    "thread": ["08_thread_tiktok", "09_slang_internet"], "tiktok": ["08_thread_tiktok", "09_slang_internet"],
    "reddit": ["08_thread_tiktok", "09_slang_internet"],
}


def _doc_huong_dan(chu_de=None):
    """Quy tắc dịch theo CHỦ ĐỀ từ translation_memory/: ALWAYS (01 general + 02 names + 10 format) LUÔN nạp,
    + file topic theo chu_de (env DICH_CHU_DE). User tự sửa/thêm .md. Tương thích ngược: không có thư mục → huong_dan_dich.md."""
    if chu_de is None:
        chu_de = os.environ.get("DICH_CHU_DE", "")
    base = os.path.join(THU_MUC_GOC, "translation_memory")
    parts = []
    if os.path.isdir(base):
        for name in _TM_ALWAYS + CHU_DE_FILES.get((chu_de or "").strip().lower(), []):
            try:
                t = open(os.path.join(base, name + ".md"), encoding="utf-8").read().strip()
                if t:
                    parts.append(t)
            except OSError:
                pass
    if parts:
        return "\n\n".join(parts)
    try:   # tương thích ngược: file gộp cũ
        return open(os.path.join(THU_MUC_GOC, "huong_dan_dich.md"), encoding="utf-8").read().strip()
    except OSError:
        return ""


_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def _bo_chu_han(s):
    """Lưới an toàn: bỏ '(...chữ Hán...)' + mọi chữ Hán còn sót (AI lỡ để lại) → không lọt vào TTS."""
    s = re.sub(r"[\(（][^)）]*[㐀-鿿][^)）]*[\)）]", "", s)   # xoá '(嫖哥)' kèm pinyin
    s = _CJK.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.IGNORECASE | re.DOTALL)


def _bo_think(s):
    """Bỏ khối suy luận của model reasoning (<think>...</think>, <reasoning>...) để chỉ còn các dòng
    dịch — tránh phần 'nghĩ' lọt vào parser làm lệch dòng. Áp cho MỌI provider trong goi_ai()."""
    s = (s or "")
    s = _THINK_RE.sub("", s)
    # <think> mở mà KHÔNG đóng (model cắt giữa chừng) -> bỏ tất cả tới hết khối nghĩ
    s = re.sub(r"<(think|thinking|reasoning)>.*$", "", s, flags=re.IGNORECASE | re.DOTALL)
    return s.strip()


# Ràng buộc CHỐNG AI kể/bịa/phình câu + CHỐNG reasoning — chèn vào MỌI prompt dịch/sửa
_RANG_BUOC = (
    "RÀNG BUỘC QUAN TRỌNG NHẤT: mỗi dòng nguồn = ĐÚNG 1 dòng dịch, đúng thứ tự, "
    "KHÔNG gộp/tách/đổi số. CHỈ dịch nội dung CÂU GỐC — TUYỆT ĐỐI KHÔNG thêm câu dẫn, "
    "KHÔNG kể thêm, KHÔNG diễn giải, KHÔNG bịa thông tin ngoài câu gốc. "
    "Độ dài bản dịch TƯƠNG ĐƯƠNG câu gốc — câu gốc NGẮN thì dịch NGẮN (vài chữ Trung → vài từ Việt). "
    "TẮT SUY LUẬN: KHÔNG xuất phần suy nghĩ/lý giải, KHÔNG dùng <think>, KHÔNG ghi chú — "
    "CHỈ xuất các dòng kết quả đúng định dạng. ")


# Dòng kết quả: 'số|dịch' (gemma) HOẶC 'số. / số) / số: / số- dịch' (llama/gemini hay dùng dấu chấm).
# Bắt buộc bắt đầu bằng SỐ + 1 dấu phân cách → tự bỏ câu mở đầu kiểu "Dưới đây là bản dịch:".
_RE_DONG = re.compile(r"^(\d+)\s*[).:|\-]\s*(.+)$")


def _parse_lo(tra, sources, start_no):
    """Tách phản hồi 'số<dấu>dịch' của 1 lô → list vi cùng độ dài sources.
    - Đủ số dòng → gán theo VỊ TRÍ (bỏ qua số AI tự ghi) → chống AI đánh số lệch gây LỆCH DÒNG.
    - Lệch số dòng → khớp theo SỐ AI ghi (như cũ); dòng thiếu để '' cho caller dịch bù.
    - Lưới chặn: dòng dịch phình bất thường so với nguồn (AI kể/bịa) → trả '' để dịch bù sát nghĩa."""
    raw = []
    for line in (tra or "").splitlines():
        m = _RE_DONG.match(line.strip())
        if m:
            raw.append((int(m.group(1)), _bo_chu_han(m.group(2).strip())))
    n = len(sources)
    vi = [""] * n
    if len(raw) == n:                                  # đủ dòng → tin THỨ TỰ, không tin số AI ghi
        for j in range(n):
            vi[j] = raw[j][1]
    else:                                              # thiếu/thừa dòng → khớp theo số AI ghi
        theo_so = {so: txt for so, txt in raw if so is not None}
        for j in range(n):
            vi[j] = theo_so.get(start_no + j, "")
    for j, src in enumerate(sources):                  # lưới chặn dịch phình (kể/bịa) → bỏ, dịch bù
        # Phạt NẶNG câu ngắn phình to (AI ảo giác): câu 2-3 chữ Trung dịch thành 50-80 ký tự vẫn chặn.
        # Chặn nếu (dài > 40 VÀ > 5× gốc) HOẶC (dài > 100 VÀ > 8× gốc) → bỏ, caller Google dịch bù sát nghĩa.
        if vi[j] and (len(vi[j]) > max(40, len(src) * 5) or len(vi[j]) > max(100, len(src) * 8)):
            vi[j] = ""
    return vi


# ---------------- Option 1: AI sửa cả phụ đề ----------------
def sua_phu_de(segs_vi, log_fn=print):
    """segs_vi = [(st,en,(zh, vi_tho))]. AI sửa vi cho đúng/tự nhiên (batch theo lô). Trả segs_vi mới."""
    if not segs_vi:
        return segs_vi
    cfg = cau_hinh()
    log_fn("LOG:🤖 AI (%s/%s) đang sửa %d câu phụ đề..." % (cfg["provider"], cfg["model"], len(segs_vi)))
    LO = 50  # số dòng mỗi lần gọi
    ket = list(segs_vi)
    for batch_dau in range(0, len(segs_vi), LO):
        nhom = segs_vi[batch_dau:batch_dau + LO]
        dong = []
        for j, (_st, _en, (zh, vi)) in enumerate(nhom):
            dong.append("%d. ZH: %s | THÔ: %s" % (batch_dau + j + 1, zh, vi))
        hd = _doc_huong_dan()
        prompt = (
            (hd + "\n\n===========\n" if hd else
             "Bạn là biên tập phụ đề Trung→Việt: sửa đúng nghĩa & tự nhiên, tên riêng chuyển sang tên Việt, không để sót chữ Hán.\n") +
            "DỮ LIỆU: mỗi dòng có số thứ tự, câu tiếng Trung (ZH) và bản dịch thô (THÔ). "
            "Hãy SỬA bản dịch theo các quy tắc trên. Áp dụng MỤC 0 (tên cố định) TRƯỚC TIÊN — ghi đè mọi ví dụ khác. "
            "BẮT BUỘC: bản dịch trả về KHÔNG được chứa BẤT KỲ chữ Hán (vd 嫖哥, 小美) hay phiên âm pinyin "
            "(vd Piǎo Gē, Xiao Mei) — MỌI tên người phải đổi sang TÊN VIỆT, dùng NHẤT QUÁN; xưng hô đúng vai vế theo ngữ cảnh. "
            + _RANG_BUOC +
            "Giữ NGUYÊN số dòng và số thứ tự.\n"
            "Trả về DUY NHẤT mỗi dòng dạng:  số|bản dịch đã sửa\n"
            "KHÔNG thêm giải thích, KHÔNG markdown.\n\n" + "\n".join(dong))
        try:
            tra = goi_ai(prompt, log_fn=log_fn)
        except Exception as e:
            log_fn("LOG:⚠ AI lỗi lô %d (%s) → giữ bản Google" % (batch_dau // LO + 1, str(e)[:60]))
            continue
        vi_moi = _parse_lo(tra, [zh for (_st, _en, (zh, _vi)) in nhom], batch_dau + 1)
        for j in range(len(nhom)):
            if vi_moi[j]:
                st, en, (zh, _vi) = nhom[j]
                ket[batch_dau + j] = (st, en, (zh, vi_moi[j]))
        log_fn("LOG:   AI sửa %d/%d" % (min(batch_dau + LO, len(segs_vi)), len(segs_vi)))
    return ket


# ---------------- AI dịch THẲNG từ ngôn ngữ gốc (chất lượng cao hơn Google) ----------------
def dich_phu_de(segs, log_fn=print):
    """segs = [(st,en,nguon)]. AI dịch THẲNG sang đích (batch theo lô). Trả [(st,en,(nguon,dich))].
    Câu nào AI bỏ trống -> để dich='' cho caller (localize) tự dịch bù bằng Google."""
    if not segs:
        return []
    cfg = cau_hinh()
    log_fn("LOG:🤖 AI (%s/%s) đang dịch %d câu..." % (cfg["provider"], cfg["model"], len(segs)))
    LO = 50  # số dòng mỗi lần gọi
    ket = [(st, en, (src, "")) for st, en, src in segs]
    hd = _doc_huong_dan()

    def _lo(dong, srcs, base1):
        """Dịch 1 lô '<số>. <gốc>' → list bản dịch khớp srcs. None nếu lỗi gọi AI."""
        prompt = (
            (hd + "\n\n===========\n" if hd else
             "Bạn là dịch giả phụ đề sang tiếng Việt: dịch đúng nghĩa & tự nhiên, "
             "tên riêng chuyển sang tên Việt, không để sót chữ Hán.\n") +
            "DỮ LIỆU: mỗi dòng có số thứ tự + câu gốc — đây là LỜI THUYẾT MINH LIÊN TỤC của 1 video (đúng thứ "
            "tự). ĐỌC HẾT các dòng để nắm NGỮ CẢNH rồi dịch cho MẠCH LẠC, nhất quán đại từ/tên/xưng hô; câu "
            "trước–sau phải nối ý trôi chảy. Hãy DỊCH sang tiếng Việt theo các quy tắc trên. "
            "BẮT BUỘC: KHÔNG chữ Hán/pinyin; tên người đổi TÊN VIỆT, dùng NHẤT QUÁN; xưng hô đúng vai. "
            "MỖI DÒNG LÀ 1 CÂU RIÊNG — dịch SÁT từng dòng, KHÔNG gộp/bỏ dòng; 2 dòng gốc KHÁC nhau thì bản dịch "
            "PHẢI khác nhau (TUYỆT ĐỐI không lặp y hệt dòng kề). "
            + _RANG_BUOC +
            ("⚠ PHẢI xuất ĐÚNG %d dòng — mỗi câu gốc tương ứng 1 dòng dịch, GIỮ ĐÚNG SỐ gốc của câu đó "
             "(vd '7. ...' → '7|...'). Câu NỐI/NGẮN/khó/trùng cũng PHẢI có dòng riêng giữ số của nó. TUYỆT ĐỐI "
             "KHÔNG gộp dòng, KHÔNG bỏ dòng, KHÔNG đánh số lại — bỏ/gộp 1 dòng sẽ làm LỆCH SAI toàn bộ phụ đề "
             "phía sau.\n" % len(dong)) +
            "Trả về DUY NHẤT mỗi dòng dạng:  số|bản dịch\nKHÔNG giải thích, KHÔNG markdown.\n\n"
            + "\n".join(dong))
        try:
            return _parse_lo(goi_ai(prompt, log_fn=log_fn), srcs, base1)
        except Exception as e:
            log_fn("LOG:⚠ AI lỗi (%s)" % str(e)[:60])
            return None

    for b in range(0, len(segs), LO):
        nhom = segs[b:b + LO]
        vi = _lo(["%d. %s" % (b + j + 1, s) for j, (_st, _en, s) in enumerate(nhom)],
                 [s for (_st, _en, s) in nhom], b + 1)
        if vi:
            for j in range(len(nhom)):
                if vi[j]:
                    st, en, (s, _) = ket[b + j]
                    ket[b + j] = (st, en, (s, vi[j]))
        log_fn("LOG:   AI dịch %d/%d" % (min(b + LO, len(segs)), len(segs)))

    # RETRY CÂU TRỐNG (cờ DICH_RETRY_TRONG, mặc định BẬT; set =0 để tắt): CHỈ câu AI bỏ trống → dịch lại
    # 1 lần (vài câu) trước khi caller bù Google. KHÔNG đụng câu đã tốt → rẻ. AI sót TẤT thì để Google lo.
    if os.environ.get("DICH_RETRY_TRONG", "1") != "0":
        trong = [j for j in range(len(segs)) if not ket[j][2][1].strip()]
        if trong and len(trong) < len(segs):
            log_fn("LOG:🔁 Dịch lại %d câu AI bỏ sót..." % len(trong))
            vi = _lo(["%d. %s" % (k + 1, segs[j][2]) for k, j in enumerate(trong)],
                     [segs[j][2] for j in trong], 1)
            if vi:
                for k, j in enumerate(trong):
                    if vi[k]:
                        st, en, (s, _) = ket[j]
                        ket[j] = (st, en, (s, vi[k]))
    return ket


# ---------------- Dịch kiểu VideoLingo (summary-first + 3 bước) ----------------
# Nghe XONG mới dịch: (0) tóm tắt + glossary toàn cục → (1) dịch trung thành (sát) →
# (2) viết lại cho mượt (reflect) — bám sát nghĩa gốc + glossary nhất quán cho cả video.
# Tắt bước 2 cho nhanh/đỡ tốn quota: env VL_REFLECT=0.
_VL_SUMMARY_CHARS = 8000   # cắt input bước tóm tắt (chỉ cần nắm bối cảnh + tên hay lặp), tránh tràn context


def _tom_tat_glossary(sources, log_fn=print):
    """Bước 0: đọc transcript → (theme, glossary=[(src,tgt)]). Lỗi → ('', []) (bỏ qua, vẫn dịch được)."""
    noi = "\n".join(s for s in sources if (s or "").strip())[:_VL_SUMMARY_CHARS]
    if not noi.strip():
        return "", []
    prompt = (
        "Đọc lời thoại (đa phần tiếng Trung) của 1 video dưới đây rồi trả về ĐÚNG định dạng:\n"
        "THEME: <tóm tắt chủ đề video trong 1-2 câu tiếng Việt>\n"
        "TERMS:\n"
        "<từ/tên gốc> => <bản dịch tiếng Việt>\n"
        "(mỗi thuật ngữ/tên riêng quan trọng 1 dòng, TỐI ĐA 15 dòng; tên người dịch sang TÊN VIỆT; "
        "KHÔNG để chữ Hán/pinyin ở vế phải). KHÔNG thêm giải thích, KHÔNG markdown.\n\n" + noi)
    try:
        tra = goi_ai(prompt, log_fn=log_fn)
    except Exception as e:
        log_fn("LOG:⚠ Tóm tắt/glossary lỗi (%s) → bỏ qua." % str(e)[:60])
        return "", []
    theme, terms, trong_terms = "", [], False
    for line in (tra or "").splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith("theme:"):
            theme = s.split(":", 1)[1].strip()
            trong_terms = False
        elif low.startswith("terms:"):
            trong_terms = True
        elif "=>" in s or "=" in s:
            sep = "=>" if "=>" in s else "="
            a, b = s.split(sep, 1)
            a = a.strip(" -·•").strip()    # vế trái = tên/từ GỐC (có thể là chữ Hán) → giữ nguyên để khớp
            b = _bo_chu_han(b).strip()     # vế phải = tiếng Việt → làm sạch chữ Hán/pinyin sót
            if a and b:
                terms.append((a, b))
    return theme, terms[:15]


def _vl_goi_buoc(srcs, batch_dau, hd, boi_canh, gloss_txt, truoc, buoc, draft=None, log_fn=print, tries=2):
    """Gọi 1 bước dịch (faithful/free) cho 1 lô → list vi cùng độ dài srcs. Lệch nhiều dòng → thử lại."""
    ctx = ""
    if truoc:
        ctx = ("CÁC CÂU LIỀN TRƯỚC (đã dịch, CHỈ để nối mạch — ĐỪNG dịch lại):\n"
               + "\n".join("· %s → %s" % (s, v) for s, v in truoc) + "\n")
    if buoc == "faithful":
        data = "\n".join("%d. %s" % (batch_dau + j + 1, s) for j, s in enumerate(srcs))
        nhiem_vu = ("DỊCH SÁT NGHĨA sang tiếng Việt: trung thành câu gốc, đủ ý, ưu tiên ĐÚNG nghĩa. ")
    else:   # free: kèm bản nháp trung thành để viết lại cho mượt
        data = "\n".join("%d. GỐC: %s | NHÁP: %s" % (batch_dau + j + 1, s, (draft[j] if draft else ""))
                         for j, s in enumerate(srcs))
        nhiem_vu = ("VIẾT LẠI bản NHÁP cho TỰ NHIÊN như tiếng Việt nói, VẪN bám sát nghĩa GỐC. ")
    prompt = (
        (hd + "\n\n===========\n" if hd else "Bạn là dịch giả phụ đề phim sang tiếng Việt.\n")
        + boi_canh + gloss_txt + ctx + nhiem_vu
        + "Áp dụng MỤC 0 (tên cố định) TRƯỚC TIÊN. BẮT BUỘC: KHÔNG còn chữ Hán/pinyin; tên người sang "
        "TÊN VIỆT, dùng NHẤT QUÁN (đúng glossary trên); xưng hô đúng vai vế. " + _RANG_BUOC
        + "Giữ NGUYÊN số dòng và số thứ tự.\n"
        "Trả về DUY NHẤT mỗi dòng dạng:  số|bản dịch\nKHÔNG giải thích, KHÔNG markdown.\n\n" + data)
    vi = [""] * len(srcs)
    for _lan in range(max(1, tries)):
        try:
            tra = goi_ai(prompt, log_fn=log_fn)
        except Exception as e:
            log_fn("LOG:⚠ AI lỗi bước %s (%s)" % (buoc, str(e)[:50]))
            return vi
        vi = _parse_lo(tra, srcs, batch_dau + 1)
        if sum(1 for v in vi if (v or "").strip()) >= max(1, int(len(srcs) * 0.8)):
            return vi   # đủ ~80% dòng → nhận; thiếu nhiều (lệch dòng) → thử lại
    return vi


def dich_video_vl(segs, log_fn=print, on_segvi=None):
    """Dịch CẢ video kiểu VideoLingo (gọi SAU khi ASR xong, cần toàn transcript).
    segs = [(st,en,src)] → trả [(st,en,(src,vi))]. on_segvi(i_1based, vi) để fill cột Dịch theo lô.
    Câu AI bỏ trống để '' cho caller (localize) bù Google."""
    if not segs:
        return []
    cfg = cau_hinh()
    sources = [src for (_st, _en, src) in segs]
    reflect = os.environ.get("VL_REFLECT", "1") != "0"
    log_fn("LOG:🤖 AI (%s/%s) dịch kiểu VideoLingo — %d câu (%s)..."
           % (cfg["provider"], cfg["model"], len(segs), "3 bước" if reflect else "1 bước (đã tắt reflect)"))
    theme, glossary = _tom_tat_glossary(sources, log_fn=log_fn)
    if theme:
        log_fn("LOG:📑 Bối cảnh: " + theme[:140])
    if glossary:
        mau = ", ".join("%s→%s" % (a, b) for a, b in glossary[:6])
        log_fn("LOG:📑 Glossary %d mục: %s%s" % (len(glossary), mau, "..." if len(glossary) > 6 else ""))
    hd = _doc_huong_dan()
    boi_canh = ("BỐI CẢNH video (để dịch đúng giọng/ngữ cảnh): " + theme + "\n") if theme else ""
    gloss_txt = (("TỪ ĐIỂN THUẬT NGỮ (BẮT BUỘC dùng nhất quán): "
                  + "; ".join("%s = %s" % (a, b) for a, b in glossary) + "\n") if glossary else "")
    ket = [(st, en, (src, "")) for (st, en, src) in segs]
    LO = 50
    truoc = []
    for batch_dau in range(0, len(segs), LO):
        nhom = segs[batch_dau:batch_dau + LO]
        srcs = [src for (_st, _en, src) in nhom]
        direct = _vl_goi_buoc(srcs, batch_dau, hd, boi_canh, gloss_txt, truoc, "faithful", log_fn=log_fn)
        vi_final = direct
        if reflect and any((v or "").strip() for v in direct):
            free = _vl_goi_buoc(srcs, batch_dau, hd, boi_canh, gloss_txt, truoc, "free",
                                draft=direct, log_fn=log_fn)
            vi_final = [free[j] if (free[j] or "").strip() else direct[j] for j in range(len(srcs))]
        for j in range(len(nhom)):
            if vi_final[j]:
                st, en, (src, _) = ket[batch_dau + j]
                ket[batch_dau + j] = (st, en, (src, vi_final[j]))
                if on_segvi:
                    on_segvi(batch_dau + j + 1, vi_final[j])
        truoc = [(s, v) for s, v in zip(srcs, vi_final) if (v or "").strip()][-3:]
        log_fn("LOG:   dịch %d/%d" % (min(batch_dau + LO, len(segs)), len(segs)))
    return ket
