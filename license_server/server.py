# -*- coding: utf-8 -*-
"""
FASTAPI LICENSE SERVER
Chạy trên VPS, Render, Railway hoặc Vercel để quản lý tài khoản và thiết bị (HWID) của khách hàng.
Sử dụng database sqlite3 qua `lic_db.py`.
"""

import os
import sys
import time
from typing import Optional
from pydantic import BaseModel
from fastapi import FastAPI, Header, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lic_db

# Khởi tạo DB lúc chạy app
lic_db.init_db()

app = FastAPI(title="ViralCrawl License Server", version="1.0.0")

# Cấu hình CORS để admin portal hoặc app có thể gọi qua web
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---
class RegisterDeviceRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = ""
    hwid: str
    device_name: Optional[str] = ""
    os: Optional[str] = ""

class LoginRequest(BaseModel):
    username: str
    password: str

class ActivateRequest(BaseModel):
    hwid: str
    device_name: Optional[str] = ""
    os: Optional[str] = ""
    hwid_cu: Optional[str] = ""

class CheckRequest(BaseModel):
    hwid: str
    hwid_cu: Optional[str] = ""

class DeactivateRequest(BaseModel):
    hwid: str

# Admin models
class CreateLicenseRequest(BaseModel):
    username: str
    plan: Optional[str] = "pro"       # free | pro | unlimited
    max_devices: Optional[int] = 1
    days: Optional[int] = 30          # số ngày hạn, 0 = vĩnh viễn

class DeactivateAdminRequest(BaseModel):
    username: str
    hwid: Optional[str] = ""          # rỗng = gỡ hết thiết bị

class DeleteUserRequest(BaseModel):
    username: str


# --- Dependency: Xác thực token người dùng ---
def get_current_user(x_token: Optional[str] = Header(None)):
    if not x_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu Token đăng nhập (X-Token)."
        )
    user = lic_db.user_tu_token(x_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn."
        )
    return user

# --- Dependency: Xác thực Admin ---
def get_current_admin(user = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Quyền truy cập bị từ chối. Cần quyền Admin."
        )
    return user


# ================= USER API ENDPOINTS =================

@app.post("/license/register")
def register_device(req: RegisterDeviceRequest):
    """
    Đăng ký tài khoản + kích hoạt thiết bị lần đầu (FREE dùng thử 7 ngày, giới hạn 1 máy).
    """
    sess, err = lic_db.dang_ky_thiet_bi(
        username=req.username,
        mat_khau=req.password,
        email=req.email,
        hwid=req.hwid,
        device_name=req.device_name,
        os_name=req.os
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    
    return {
        "ok": True,
        "session": sess["token"],
        "license_token": sess["license_token"],
        "info": sess["info"]
    }


@app.post("/license/login")
def login(req: LoginRequest):
    """
    Đăng nhập tài khoản để quản lý hoặc lấy session token trên thiết bị mới.
    """
    # Rate limit chống brute force
    ip_key = f"login_attempt:{req.username}"
    if lic_db.rate_limited(ip_key, limit=5, window=60):
         raise HTTPException(
             status_code=429, 
             detail="Thử đăng nhập quá nhiều lần. Vui lòng đợi 1 phút."
         )

    sess, err = lic_db.dang_nhap(req.username, req.password)
    if err:
        raise HTTPException(status_code=400, detail=err)
    
    return {
        "ok": True,
        "token": sess["token"],
        "username": sess["username"],
        "is_admin": sess["is_admin"]
    }


@app.post("/license/activate")
def activate_device(req: ActivateRequest, user = Depends(get_current_user)):
    """
    Kích hoạt thiết bị hiện tại (HWID) vào tài khoản của người dùng.
    """
    tok, info = lic_db.kich_hoat_thiet_bi(
        user_id=user["user_id"],
        hwid=req.hwid,
        device_name=req.device_name,
        os_name=req.os,
        hwid_cu=req.hwid_cu
    )
    if not tok:
        raise HTTPException(status_code=400, detail=info)
    
    return {
        "ok": True,
        "license_token": tok,
        "info": info
    }


@app.post("/license/check")
def check_license(req: CheckRequest, user = Depends(get_current_user)):
    """
    Kiểm tra trạng thái license định kỳ và trả về offline license token mới.
    """
    tok, info = lic_db.kiem_license(
        user_id=user["user_id"],
        hwid=req.hwid,
        hwid_cu=req.hwid_cu
    )
    if not tok:
        raise HTTPException(status_code=400, detail=info)
    
    return {
        "ok": True,
        "license_token": tok,
        "info": info
    }


@app.post("/license/deactivate")
def deactivate_device(req: DeactivateRequest, user = Depends(get_current_user)):
    """
    Hủy kích hoạt thiết bị (gỡ HWID) để giải phóng slot máy.
    """
    ok, err = lic_db.go_thiet_bi(user_id=user["user_id"], hwid=req.hwid)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "msg": "Đã hủy kích hoạt thiết bị."}


@app.get("/license/devices")
def list_devices(user = Depends(get_current_user)):
    """
    Liệt kê danh sách các thiết bị của tài khoản.
    """
    devices = lic_db.liet_ke_thiet_bi(user_id=user["user_id"])
    return {"ok": True, "devices": devices}


@app.get("/license/status")
def license_status(user = Depends(get_current_user)):
    """
    Lấy thông tin gói cước và giới hạn thiết bị của tài khoản.
    """
    info = lic_db.thong_tin_license(user_id=user["user_id"])
    if not info:
        return {"ok": True, "license": None}
    return {"ok": True, "license": info}


# ================= ADMIN MANAGEMENT API =================

@app.post("/admin/license/grant")
def grant_license(req: CreateLicenseRequest, admin = Depends(get_current_admin)):
    """
    Admin cấp hoặc gia hạn license cho một user.
    """
    uid, err = lic_db.user_id_theo_username(req.username)
    if err:
        raise HTTPException(status_code=404, detail=err)
    
    lic_id, err2 = lic_db.cap_license(
        user_id=uid,
        plan=req.plan,
        max_devices=req.max_devices,
        days=req.days
    )
    if err2:
        raise HTTPException(status_code=400, detail=err2)
    
    return {
        "ok": True, 
        "msg": f"Đã cấp gói '{req.plan}' ({req.days} ngày, tối đa {req.max_devices} máy) cho {req.username}."
    }


@app.post("/admin/license/revoke")
def revoke_license(req: DeleteUserRequest, admin = Depends(get_current_admin)):
    """
    Admin thu hồi license của một user (khóa tài khoản).
    """
    uid, err = lic_db.user_id_theo_username(req.username)
    if err:
        raise HTTPException(status_code=404, detail=err)
    
    lic_db.thu_hoi_license(user_id=uid)
    return {"ok": True, "msg": f"Đã thu hồi license của {req.username}."}


@app.post("/admin/devices/deactivate")
def admin_deactivate_device(req: DeactivateAdminRequest, admin = Depends(get_current_admin)):
    """
    Admin gỡ thiết bị của người dùng (giải phóng slot khi đổi máy/kẹt).
    """
    n, err = lic_db.go_thiet_bi_admin(username=req.username, hwid=req.hwid)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {
        "ok": True, 
        "msg": f"Đã gỡ {n} thiết bị của user {req.username}."
    }


@app.get("/admin/users")
def list_users(admin = Depends(get_current_admin)):
    """
    Admin liệt kê toàn bộ người dùng và trạng thái gói cước.
    """
    users = lic_db.liet_ke_users()
    return {"ok": True, "users": users}


@app.get("/admin/stats")
def admin_stats(admin = Depends(get_current_admin)):
    """
    Admin lấy thống kê tổng quan hệ thống.
    """
    stats = lic_db.thong_ke_admin()
    return {"ok": True, "stats": stats}


@app.get("/admin/churn")
def check_churn(window_days: int = 7, min_hwid: int = 3, admin = Depends(get_current_admin)):
    """
    Admin kiểm tra hành vi bất thường (đổi máy quá nhiều lần, nghi ngờ share tài khoản).
    """
    window_secs = window_days * 24 * 3600
    churn = lic_db.thong_ke_churn(window_secs=window_secs, min_hwid=min_hwid)
    return {"ok": True, "churn": churn}


@app.post("/admin/user/delete")
def delete_user(req: DeleteUserRequest, admin = Depends(get_current_admin)):
    """
    Admin xóa tài khoản người dùng khỏi hệ thống.
    """
    ok = lic_db.xoa_user(req.username)
    if not ok:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
    return {"ok": True, "msg": f"Đã xóa tài khoản {req.username}."}


# --- Khởi chạy trực tiếp (khi dev) ---
if __name__ == "__main__":
    import uvicorn
    # Đọc cấu hình cổng từ env
    port = int(os.environ.get("PORT", "8900"))
    print(f"Khởi chạy License Server tại cổng {port}...")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
