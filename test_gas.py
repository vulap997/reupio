import urllib.request
import json

url = "https://script.google.com/macros/s/AKfycbzV-jUrvEopJojHYBn-E1lvf8xFvvzyH7mVbpZX3lHWzMGv8PLrsmOUcm6JuSr1bPUy/exec"

# 1. Login
body_login = {"action": "login", "username": "testuser", "password": "123456"}
req_login = urllib.request.Request(url, data=json.dumps(body_login).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")

try:
    with urllib.request.urlopen(req_login, timeout=15) as r:
        res_login = json.loads(r.read().decode("utf-8"))
        print("Login Response:", res_login)
        
    if res_login.get("ok"):
        token = res_login.get("token")
        # 2. Activate
        body_act = {
            "action": "activate",
            "token": token,
            "hwid": "test_hwid_123",
            "device_name": "Test PC",
            "os": "Windows"
        }
        req_act = urllib.request.Request(url, data=json.dumps(body_act).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req_act, timeout=15) as r2:
            res_act = json.loads(r2.read().decode("utf-8"))
            print("Activate Response:", res_act)
except Exception as e:
    print("Error:", e)
    if hasattr(e, 'read'):
        print("Error Body:", e.read().decode("utf-8"))
