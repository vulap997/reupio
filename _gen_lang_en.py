# -*- coding: utf-8 -*-
"""Trích chuỗi UI tiếng Việt trong web/index.html -> dịch sang tiếng Anh (Google) -> web/lang_en.json.
Chạy 1 lần (và mỗi khi UI đổi nhiều). Khớp cách DOM tách text node (theo thẻ) để JS walker match đúng."""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

# Windows: stdout mặc định cp1252 -> print() chuỗi tiếng Việt ném UnicodeEncodeError (crash TRƯỚC khi ghi
# file). Ép UTF-8 để chạy được dù không set env PYTHONUTF8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

GOC = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(GOC, "web", "index.html")
OUT = os.path.join(GOC, "web", "lang_en.json")

VN = "àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ"
VN += VN.upper()
ATTRS = ("placeholder", "title", "data-tip", "value")


def co_vn(s):
    return any(c in VN for c in (s or ""))


class P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.bo = 0          # đang trong <script>/<style>
        self.found = set()

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.bo += 1
        for k, v in attrs:
            if k in ATTRS and v and co_vn(v):
                t = v.strip()
                if t:
                    self.found.add(t)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.bo:
            self.bo -= 1

    def handle_data(self, data):
        if self.bo:
            return
        t = (data or "").strip()
        if t and co_vn(t):
            self.found.add(t)


def dich(text):
    try:
        url = ("https://translate.googleapis.com/translate_a/single"
               "?client=gtx&sl=vi&tl=en&dt=t&q=" + urllib.parse.quote(text))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
        return text, "".join(s[0] for s in d[0] if s and s[0]).strip()
    except Exception as e:
        return text, ""


def js_literals(html):
    """Trích string literal tiếng Việt trong <script> (bỏ literal có ${} vì cần t())."""
    out = set()
    for blk in re.findall(r"<script>(.*?)</script>", html, re.S):
        for m in re.findall(r'"([^"\\\n]{2,})"' + r"|'([^'\\\n]{2,})'", blk):
            s = (m[0] or m[1]).strip()
            if s and "${" not in s and co_vn(s):
                out.add(s)
    return out


def main():
    html = open(HTML, encoding="utf-8").read()
    p = P()
    p.feed(html)
    p.found |= js_literals(html)
    strings = sorted(p.found)
    print(f"Trích {len(strings)} chuỗi tiếng Việt cần dịch.")
    cu = {}
    if os.path.exists(OUT):
        try:
            cu = json.load(open(OUT, encoding="utf-8"))
        except Exception:
            cu = {}
    can = [s for s in strings if s not in cu]
    print(f"Đã có {len(cu)} trong cache, dịch mới {len(can)}.")
    out = dict(cu)
    if can:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for i, (vi, en) in enumerate(ex.map(dich, can), 1):
                if en:
                    out[vi] = en
                if i % 25 == 0 or i == len(can):
                    print(f"  dịch {i}/{len(can)}")
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Ghi {len(out)} cặp -> {OUT}")


if __name__ == "__main__":
    main()
