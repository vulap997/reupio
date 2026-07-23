# HƯỚNG DẪN DÙNG GOOGLE SHEET LÀM SERVER QUẢN LÝ LICENSE

Sử dụng Google Sheets làm máy chủ quản lý bản quyền (License Server) là phương án **tiện lợi nhất, miễn phí 100%, không cần thuê VPS** và có giao diện quản lý trực quan như Excel.

Tôi đã xây dựng mã Apps Script và cập nhật Client Python để tự động tương thích. Dưới đây là các bước thiết lập chi tiết:

---

## BƯỚC 1: Tạo Google Sheet & Thiết Lập Trang Tính

1. Truy cập [Google Sheets](https://docs.google.com/spreadsheets/) và tạo một file bảng tính mới.
2. Đổi tên Sheet đầu tiên thành: **`Users`**
   * Đặt dòng tiêu đề (hàng số 1) lần lượt cho các cột sau:
     * Cột A: `username` (Tên tài khoản khách hàng)
     * Cột B: `password` (Mật khẩu đăng nhập của khách)
     * Cột C: `plan` (Gói cước: `free`, `pro`, hoặc `unlimited`)
     * Cột D: `max_devices` (Số lượng máy tối đa được dùng, ví dụ: `1`)
     * Cột E: `expires_at` (Thời gian hết hạn - Dùng Unix Timestamp, ví dụ `1798732800` cho năm 2027, hoặc `0` cho vĩnh viễn)
     * Cột F: `status` (Trạng thái: `active` hoặc `revoked` để khóa tài khoản)
     * Cột G: `created_at` (Thời gian tạo)
3. Tạo thêm một Sheet (tab) thứ 2 và đổi tên thành: **`Devices`**
   * Đặt dòng tiêu đề (hàng số 1) cho các cột:
     * Cột A: `username`
     * Cột B: `hwid` (Mã máy)
     * Cột C: `device_name`
     * Cột D: `os`
     * Cột E: `active` (Trạng thái thiết bị: `1` là đang hoạt động, `0` là đã gỡ)
     * Cột F: `last_seen`
     * Cột G: `first_seen`

---

## BƯỚC 2: Cài Đặt Google Apps Script (GAS)

1. Trên thanh công cụ của Google Sheet, chọn **Tiện ích mở rộng** (Extensions) -> **Apps Script**.
2. Xóa toàn bộ mã mặc định có sẵn trong khung soạn thảo.
3. Mở file [google_sheet_license.js](google_sheet_license.js) trong thư mục này, copy toàn bộ nội dung và dán vào Apps Script.
4. Thay đổi giá trị biến `var SECRET_KEY = "your_secret_key_here";` ở dòng đầu tiên thành một chuỗi bảo mật của riêng bạn (ví dụ: `my_super_secret_key_123`). Chuỗi này phải khớp với biến `LIC_SECRET` ở client để xác minh bản quyền offline.
5. Nhấn biểu tượng **Lưu** (hình đĩa mềm) hoặc ấn `Ctrl + S`.

---

## BƯỚC 3: Triển Khai Thành Web App công khai

1. Nhấn nút **Triển khai** (Deploy) ở góc trên bên phải -> Chọn **Triển khai mới** (New deployment).
2. Nhấp vào biểu tượng bánh răng cài đặt -> Chọn **Ứng dụng web** (Web app).
3. Cấu hình thông tin như sau:
   * **Mô tả**: `License Server`
   * **Chạy dưới dạng** (Execute as): Chọn **Tôi** (Me - địa chỉ email Google của bạn).
   * **Ai có quyền truy cập** (Who has access): Chọn **Bất kỳ ai** (Anyone) *(Lưu ý: Bắt buộc chọn "Bất kỳ ai" thì phần mềm trên máy khách mới có thể gửi dữ liệu lên được).*
4. Nhấn nút **Triển khai** (Deploy).
5. Google sẽ yêu cầu bạn cấp quyền truy cập trang tính (Ủy quyền truy cập). Hãy bấm **Cấp quyền truy cập**, chọn tài khoản Google của bạn, nhấn **Nâng cao** (Advanced) -> **Đi tới Dự án không có tiêu đề (không an toàn)** và chọn **Cho phép** (Allow).
6. Sau khi triển khai xong, Google sẽ cung cấp cho bạn một đường link **URL của ứng dụng web** (Web app URL), định dạng như sau:
   `https://script.google.com/macros/s/AKfycb.../exec`
7. Hãy **sao chép đường link này** để cấu hình cho client.

---

## BƯỚC 4: Cấu Hình Trên Phần Mềm Client (Trong App Của Khách)

Client Python đã được cấu hình tự động nhận diện nếu server là Google Sheets. Bạn chỉ cần trỏ URL Web App vừa copy vào cấu hình.

* **Cách 1 (Khi Dev/Test)**: Set biến môi trường hệ thống:
  ```cmd
  set LIC_SERVER=https://script.google.com/macros/s/AKfycb.../exec
  ```
* **Cách 2 (Khi Build/Đóng gói ứng dụng)**: Sửa biến `DEFAULT_BASE` trong file [lic_client.py](lic_client.py#L28):
  ```python
  DEFAULT_BASE = os.environ.get("LIC_SERVER", "https://script.google.com/macros/s/AKfycb.../exec")
  ```

---

## BƯỚC 5: Cách Bạn Quản Lý Khách Hàng Trên Sheet

Mỗi khi muốn bán tool hoặc quản lý thiết bị của khách hàng, bạn không cần dùng code nữa mà có thể thao tác trực tiếp bằng tay trên Google Sheet:

* **Tạo tài khoản / Bán gói**: 
  * Chỉ cần mở sheet `Users` và thêm dòng mới. Nhập `username`, `password` (bằng văn bản thường cho bạn dễ nhớ và quản lý), đặt `plan` là `pro` hoặc `unlimited`, `max_devices` là `1`, nhập ngày hết hạn dạng Unix Timestamp (Ví dụ: `1798732800` cho năm 2027). Khách chỉ cần mở app và đăng nhập đúng thông tin này là chạy được.
* **Khóa tài khoản (Revoke)**:
  * Khi khách hết hạn hoặc không muốn cho dùng nữa, tại cột `status` của user đó, chuyển từ `active` thành `revoked`. App của khách sẽ ngay lập tức báo bị khóa và chặn mọi chức năng.
* **Mở khóa thiết bị (Khi đổi máy / kẹt slot)**:
  * Khi khách báo đổi máy tính mới và bị chặn do quá số thiết bị cho phép: bạn mở sheet `Devices`, tìm dòng tương ứng với `username` đó và mã `hwid` cũ của họ, đổi cột `active` từ `1` thành `0`. Máy cũ sẽ bị giải phóng và khách có thể đăng nhập trên máy mới bình thường.
