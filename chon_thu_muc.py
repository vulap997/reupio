# -*- coding: utf-8 -*-
"""Mở hộp thoại CHỌN THƯ MỤC (native Windows) bằng tkinter; in 'PICKED:<path>' hoặc 'CANCELLED'.
Dùng bởi web_app (/api/data_dir action=pick) để user chọn nơi lưu video đã cào (vd ổ D:).
Chạy như tiến trình con riêng để hộp thoại không chặn backend."""
import sys

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as e:
    print("ERROR:" + str(e)[:120])
    sys.exit(1)


def main():
    # Chế độ CHỌN FILE video (multi-select) khi arg[1]=="--files" → in mỗi đường dẫn 1 dòng "PICKED:<path>".
    # Mặc định (không arg / arg là initialdir) = CHỌN THƯ MỤC (giữ hành vi cũ cho /api/data_dir).
    files_mode = len(sys.argv) > 1 and sys.argv[1] == "--files"
    init = (sys.argv[2] if files_mode and len(sys.argv) > 2 else
            (sys.argv[1] if (not files_mode and len(sys.argv) > 1) else ""))
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    try:
        if files_mode:
            paths = filedialog.askopenfilenames(
                title="Chọn video của bạn để render (có thể chọn nhiều)",
                initialdir=init or None,
                filetypes=[("Video", "*.mp4 *.mov *.mkv *.webm *.avi *.flv *.m4v"), ("Tất cả", "*.*")])
            paths = list(paths or [])
        else:
            p = filedialog.askdirectory(
                title="Chọn thư mục lưu video đã cào (nên chọn ổ còn nhiều dung lượng, vd D:\\ViralCrawl)",
                initialdir=init or None, mustexist=False)
            paths = [p] if p else []
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    if paths:
        for p in paths:
            print("PICKED:" + p, flush=True)
    else:
        print("CANCELLED", flush=True)


if __name__ == "__main__":
    main()
