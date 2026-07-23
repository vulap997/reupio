# HƯỚNG DẪN TRIỂN KHAI VÀ QUẢN LÝ LICENSE CHO KHÁCH HÀNG

Tài liệu này hướng dẫn bạn cách triển khai hệ thống quản lý bản quyền (License Server) cho tool **ViralCrawl (reupo douyin+)** để bán cho khách hàng, hỗ trợ khóa máy theo thiết bị (HWID), quản lý thời hạn dùng và kiểm soát số lượng máy sử dụng.

---

## 1. Cơ Chế Quản Lý License

Hệ thống license của ViralCrawl được thiết kế trên mô hình:
* **Tài khoản người dùng (Account)**: Khách hàng đăng ký hoặc bạn tạo cho họ một tài khoản (username/password).
* **Gói cước (License Plan)**: Mỗi tài khoản sẽ liên kết với một gói cước (`free`, `pro` hoặc `unlimited`) có ngày bắt đầu, ngày hết hạn và số lượng máy tối đa được phép chạy cùng lúc (`max_devices`).
* **Khóa thiết bị (HWID Binding)**: Khi khách đăng nhập trên máy tính của họ, app sẽ lấy thông tin chữ ký phần cứng duy nhất (Hardware ID - HWID) của máy đó gửi lên server để kích hoạt (bind). Nếu vượt quá số máy tối đa (`max_devices`), server sẽ chặn không cho kích hoạt máy mới.
* **Token Offline (Grace period)**: Server cấp một mã khóa ký số HMAC (`license_token`). Mỗi lần mở app, nếu máy khách mất mạng, app vẫn có thể xác minh chữ ký của token này để cho phép chạy offline tối đa **7 ngày** mà không cần liên hệ server liên tục.

---

## 2. Các Thành Phần Mã Nguồn Trong Codebase

1. **`license_server/lic_db.py`**: Tầng xử lý database SQLite (`license.db`). Chứa các hàm tạo tài khoản, cấp gói, kích hoạt/gỡ thiết bị, xác minh chữ ký token offline.
2. **`license_server/server.py`**: **[MỚI]** File chạy server FastAPI làm nhiệm vụ cung cấp API quản trị và API cho khách hàng đăng nhập/kích hoạt.
3. **`license_server/lic_client.py`**: Thư viện chạy dưới client (trong app của khách), giao tiếp HTTP với server.
4. **`license_server/lic_cli.py`**: CLI chạy cầu nối giữa giao diện app (Electron) và backend Python local.

---

## 3. Hướng Dẫn Chạy Server License (FastAPI)

### Bước 1: Cài đặt thư viện cần thiết
Trên máy chủ hoặc môi trường deploy, bạn cần cài đặt:
```bash
pip install fastapi uvicorn pydantic cryptography
```

### Bước 2: Chạy thử local
Để chạy thử Server License trên máy của bạn (mặc định chạy ở cổng `8900`):
```bash
python license_server/server.py
```
Bạn có thể mở trình duyệt truy cập `http://127.0.0.1:8900/docs` để xem tài liệu API chi tiết (Swagger UI) và thử nghiệm các tính năng.

### Bước 3: Deploy lên Cloud (VPS / Render / Railway)
Để chạy online 24/7 cho khách hàng kết nối:
* **Phương án VPS**:
  1. Cài Python, clone thư mục `license_server/` lên VPS.
  2. Chạy server bằng lệnh:
     ```bash
     uvicorn server:app --host 0.0.0.0 --port 8900
     ```
  3. Cấu hình reverse proxy Nginx + SSL (HTTPS) trỏ về cổng `8900`.
* **Phương án Cloud (Render / Railway / Vercel)**:
  * Deploy thư mục này lên các dịch vụ PaaS như Render hoặc Railway. 
  * Cần mount một persistent volume cho file database `license.db` (hoặc cấu hình env chuyển sang PostgreSQL/Supabase nếu cơ sở dữ liệu lớn).

### Bước 4: Biến môi trường quan trọng (Environment Variables)
* `LIC_SECRET`: Khóa bí mật dùng để ký token offline HMAC-SHA256 (Ví dụ: `6a5b23e8...`). Hãy giữ khóa này tuyệt mật, nếu đổi khóa này toàn bộ token offline của khách cũ sẽ bị vô hiệu hóa và họ phải online để nhận token mới.
* `LIC_DB_DIR`: Thư mục lưu file `license.db`. Mặc định lưu ngay trong thư mục `license_server`.
* `LIC_SERVER`: Đường dẫn URL của License Server (ví dụ: `https://your-license-server.com`).

---

## 4. Cách Quản Lý Tạo Key và Cấp Gói Cho Khách Hàng

### Cách 1: Sử dụng giao diện tài liệu Swagger API (Khuyên dùng khi chưa có Admin Web)
1. Truy cập `https://your-license-server.com/docs`.
2. Tạo tài khoản Admin trước hoặc chỉnh sửa trường `is_admin = 1` trong SQLite DB.
3. Sử dụng API `/license/register` (hoặc bạn tạo tài khoản cho khách) để tạo User.
4. Sử dụng API `/admin/license/grant` (yêu cầu Header `X-Token` của Admin) để cấp/gia hạn gói:
   * **`username`**: Tên tài khoản của khách hàng.
   * **`plan`**: Gói cước (`pro` hoặc `unlimited`).
   * **`max_devices`**: Số lượng máy tối đa khách được dùng (thường là `1` hoặc `2`).
   * **`days`**: Hạn sử dụng (ví dụ: `30` cho gói tháng, `365` cho gói năm, hoặc `0` cho trọn đời).

### Cách 2: Quản lý trực tiếp bằng script Python
Bạn có thể mở Python shell trên server và gọi trực tiếp các hàm quản trị trong `lic_db.py`:
```python
import lic_db

# 1. Tạo tài khoản cho khách
uid, err = lic_db.dang_ky("khachhang_a", "matkhau123", "email_khach@gmail.com")

# 2. Cấp gói Pro 30 ngày, tối đa 1 máy
lic_db.cap_license(user_id=uid, plan="pro", max_devices=1, days=30)

# 3. Xem danh sách tất cả khách hàng & gói cước
users = lic_db.liet_ke_users()
print(users)
```

---

## 5. Hướng Dẫn Cấu Hình Thiết Lập Trên App Của Khách Hàng

Khi đóng gói app bán cho khách hàng:
1. Đảm bảo cấu hình biến môi trường `LIC_SERVER` trong app Electron trỏ về URL server thực tế của bạn (trong `desktop/main.js` hoặc file env cấu hình build).
   * Mặc định trong code `lic_client.py` đang trỏ về:
     ```python
     DEFAULT_BASE = "https://license-server-cyan-kappa.vercel.app" # Thay thế thành domain của bạn
     ```
2. Khách hàng khi mở app lần đầu sẽ thực hiện Đăng nhập / Đăng ký qua giao diện.
3. Thiết bị của khách sẽ tự động đăng ký với máy chủ và chạy bình thường nếu gói còn hạn.

### Cách tắt kiểm tra License khi lập trình (Dev Mode Bypass)
Khi bạn đang lập trình, chỉnh sửa tính năng trên máy cá nhân và không muốn bị chặn bởi License Server, bạn chỉ cần set biến môi trường:
```cmd
set VC_BYPASS_LICENSE=1
```
(hoặc thêm vào file cấu hình môi trường chạy app). Khi bật biến này, app sẽ tự động giả lập gói `unlimited` và mở khóa toàn bộ tính năng mà không cần kết nối server.
