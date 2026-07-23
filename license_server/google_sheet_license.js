// ==========================================
// GOOGLE APPS SCRIPT FOR GOOGLE SHEETS LICENSE SERVER
// Dán toàn bộ mã này vào mục: Tiện ích mở rộng -> Apps Script trong Google Sheet của bạn.
// Sau đó nhấn "Triển khai" -> "Triển khai mới" -> Chọn loại "Ứng dụng web" -> Cấu hình:
//   - Quyền truy cập: "Bất kỳ ai" (Anyone)
//   - Chạy dưới dạng: "Tôi" (Me)
// ==========================================

var SECRET_KEY = "your_secret_key_here"; // Khớp với LIC_SECRET bên Python client để xác minh offline

// Tên của các sheet/tab tương ứng trong Google Sheet
var USER_SHEET_NAME = "Users";
var DEVICE_SHEET_NAME = "Devices";

function doPost(e) {
  try {
    var postContent = e.postData.contents;
    var requestData = JSON.parse(postContent);
    var action = requestData.action;
    var result = { ok: false, msg: "Action không xác định" };
    
    if (action === "register") {
      result = registerUser(requestData);
    } else if (action === "login") {
      result = loginUser(requestData);
    } else if (action === "activate") {
      result = activateDevice(requestData);
    } else if (action === "check") {
      result = checkLicense(requestData);
    } else if (action === "deactivate") {
      result = deactivateDevice(requestData);
    } else if (action === "devices") {
      result = listDevices(requestData);
    }
    
    return ContentService.createTextOutput(JSON.stringify(result))
                         .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false, msg: "Lỗi máy chủ GAS: " + err.toString() }))
                         .setMimeType(ContentService.MimeType.JSON);
  }
}

// --- Helper Functions ---

function getSheet(name) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    // Tạo header mặc định
    if (name === USER_SHEET_NAME) {
      sheet.appendRow(["username", "password", "plan", "max_devices", "expires_at", "status", "created_at"]);
    } else if (name === DEVICE_SHEET_NAME) {
      sheet.appendRow(["username", "hwid", "device_name", "os", "active", "last_seen", "first_seen"]);
    }
  }
  return sheet;
}

function findRowByValue(sheet, colIndex, value) {
  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    if (data[i][colIndex - 1].toString().trim().toLowerCase() === value.toString().trim().toLowerCase()) {
      return { rowNum: i + 1, data: data[i] };
    }
  }
  return null;
}

function findDeviceRow(sheet, username, hwid) {
  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    var u = data[i][0].toString().trim().toLowerCase();
    var h = data[i][1].toString().trim().toLowerCase();
    if (u === username.toLowerCase() && h === hwid.toLowerCase()) {
      return i + 1;
    }
  }
  return null;
}

function countActiveDevices(sheet, username) {
  var data = sheet.getDataRange().getValues();
  var count = 0;
  for (var i = 1; i < data.length; i++) {
    var u = data[i][0].toString().trim().toLowerCase();
    var active = data[i][4]; // active là cột 5 (chỉ số 4)
    if (u === username.toLowerCase() && (active == 1 || active == "1" || active == true)) {
      count++;
    }
  }
  return count;
}

// Ký HMAC-SHA256 cho offline token tương thích với Python
function signToken(payload) {
  var rawText = JSON.stringify(payload);
  var signatureBytes = Utilities.computeHmacSignature(Utilities.MacAlgorithm.HMAC_SHA_256, rawText, SECRET_KEY);
  
  // Convert bytes sang Hex string
  var hexSig = signatureBytes.map(function(byte) {
    var v = (byte & 0xFF).toString(16);
    return v.length === 1 ? '0' + v : v;
  }).join('');
  
  // Encode Base64url cho raw payload
  var rawBytes = Utilities.newBlob(rawText).getBytes();
  var payloadBase64 = Utilities.base64EncodeWebSafe(rawBytes).replace(/=+$/, "");
  
  return payloadBase64 + "." + hexSig;
}

// Lấy thông tin gói
function getTier(plan, expiresAt, createdAt) {
  var now = Math.floor(Date.now() / 1000);
  if (plan === "free") {
    var trialSeconds = 7 * 86400; // 7 ngày
    if ((now - createdAt) > trialSeconds) {
      return "expired";
    }
    return "free";
  }
  var isExpired = expiresAt > 0 && expiresAt < now;
  if (isExpired) {
    return "expired"; // Gói trả phí hết hạn -> khóa luôn
  }
  return plan;
}

// --- API Implementation ---

function registerUser(req) {
  var username = (req.username || "").trim();
  var password = (req.password || "").trim();
  var hwid = (req.hwid || "").trim();
  var deviceName = req.device_name || "";
  var os = req.os || "";
  
  if (username.length < 3 || password.length < 6) {
    return { ok: false, msg: "Tên đăng nhập tối thiểu 3 ký tự, mật khẩu tối thiểu 6 ký tự." };
  }
  if (!hwid) {
    return { ok: false, msg: "Không lấy được mã thiết bị (HWID)." };
  }
  
  var userSheet = getSheet(USER_SHEET_NAME);
  var userExists = findRowByValue(userSheet, 1, username);
  if (userExists) {
    return { ok: false, msg: "Tên đăng nhập đã tồn tại trên hệ thống." };
  }
  
  // Đăng ký thành công -> mặc định cấp gói FREE vĩnh viễn (max 1 thiết bị)
  var now = Math.floor(Date.now() / 1000);
  userSheet.appendRow([username, password, "free", 1, 0, "active", now]);
  
  // Tự động kích hoạt thiết bị đầu tiên
  var deviceSheet = getSheet(DEVICE_SHEET_NAME);
  deviceSheet.appendRow([username, hwid, deviceName, os, 1, now, now]);
  
  // Ký token
  var expOffline = now + (7 * 86400); // 7 ngày offline grace
  var payload = {
    uid: username,
    lid: 1, // mock lic id
    hwid: hwid,
    plan: "free",
    tier: "free",
    lic_exp: 0,
    trial_exp: now + (7 * 86400),
    exp: expOffline
  };
  
  var token = signToken(payload);
  
  return {
    ok: true,
    session: "session_" + Utilities.getUuid(),
    license_token: token,
    info: {
      plan: "free",
      tier: "free",
      status: "active",
      max_devices: 1,
      expires_at: 0,
      hwid: hwid,
      lohapage: false
    }
  };
}

function loginUser(req) {
  var username = (req.username || "").trim();
  var password = (req.password || "").trim();
  
  var userSheet = getSheet(USER_SHEET_NAME);
  var user = findRowByValue(userSheet, 1, username);
  if (!user || user.data[1].toString() !== password) {
    return { ok: false, msg: "Sai tên đăng nhập hoặc mật khẩu." };
  }
  
  return {
    ok: true,
    token: "session_" + Utilities.getUuid() + "_" + username, // lưu tạm tên trong session
    username: username,
    is_admin: user.data[5] == 1 || user.data[5] == "1" || user.data[5] == true
  };
}

function activateDevice(req) {
  var session = req.token || "";
  var hwid = (req.hwid || "").trim();
  var deviceName = req.device_name || "";
  var os = req.os || "";
  
  if (!session || !session.startsWith("session_")) {
    return { ok: false, msg: "Phiên làm việc không hợp lệ." };
  }
  
  var parts = session.split("_");
  var username = parts[parts.length - 1]; // lấy username từ session
  
  var userSheet = getSheet(USER_SHEET_NAME);
  var user = findRowByValue(userSheet, 1, username);
  if (!user) {
    return { ok: false, msg: "Tài khoản không tồn tại." };
  }
  
  if (user.data[5] === "revoked") {
    return { ok: false, msg: "Tài khoản của bạn đã bị khóa." };
  }
  
  var now = Math.floor(Date.now() / 1000);
  var plan = user.data[2];
  var maxDevices = parseInt(user.data[3]) || 1;
  var expiresAt = parseInt(user.data[4]) || 0;
  var createdAt = parseInt(user.data[6]) || now;
  var status = user.data[5];
  
  var tier = getTier(plan, expiresAt, createdAt);
  
  var deviceSheet = getSheet(DEVICE_SHEET_NAME);
  var devRow = findDeviceRow(deviceSheet, username, hwid);
  
  if (devRow) {
    // Đã từng active máy này -> cập nhật thành active=1 và last_seen
    deviceSheet.getRange(devRow, 5).setValue(1); // active
    deviceSheet.getRange(devRow, 6).setValue(now); // last_seen
  } else {
    // Thiết bị mới -> kiểm tra giới hạn
    var activeCount = countActiveDevices(deviceSheet, username);
    if (activeCount >= maxDevices) {
      if (maxDevices <= 1) {
        return { ok: false, msg: "Tài khoản đã được dùng ở máy khác. Mỗi tài khoản chỉ dùng được trên 1 máy." };
      }
      return { ok: false, msg: "Đã đạt giới hạn " + maxDevices + " thiết bị. Vui lòng gỡ bớt máy cũ." };
    }
    
    // Ghi nhận thiết bị mới
    deviceSheet.appendRow([username, hwid, deviceName, os, 1, now, now]);
  }
  
  // Tạo token
  var expOffline = now + (7 * 86400);
  var trialExp = plan === "free" ? (createdAt + (7 * 86400)) : 0;
  
  var payload = {
    uid: username,
    lid: user.rowNum,
    hwid: hwid,
    plan: plan,
    tier: tier,
    lic_exp: expiresAt,
    trial_exp: trialExp,
    exp: expOffline
  };
  
  var token = signToken(payload);
  
  return {
    ok: true,
    license_token: token,
    info: {
      plan: plan,
      tier: tier,
      status: status,
      max_devices: maxDevices,
      expires_at: expiresAt,
      hwid: hwid,
      lohapage: plan === "unlimited" || plan === "pro" // Tự động mở LohaPage cho pro/unlimited
    }
  };
}

function checkLicense(req) {
  var session = req.token || "";
  var hwid = (req.hwid || "").trim();
  
  if (!session || !session.startsWith("session_")) {
    return { ok: false, msg: "Phiên làm việc hết hạn." };
  }
  
  var parts = session.split("_");
  var username = parts[parts.length - 1];
  
  var userSheet = getSheet(USER_SHEET_NAME);
  var user = findRowByValue(userSheet, 1, username);
  if (!user) {
    return { ok: false, msg: "Tài khoản không tồn tại." };
  }
  if (user.data[5] === "revoked") {
    return { ok: false, msg: "Tài khoản đã bị khóa." };
  }
  
  var now = Math.floor(Date.now() / 1000);
  var deviceSheet = getSheet(DEVICE_SHEET_NAME);
  var devRow = findDeviceRow(deviceSheet, username, hwid);
  
  if (!devRow) {
    return { ok: false, msg: "Thiết bị chưa được kích hoạt." };
  }
  
  // Kiểm tra xem thiết bị có đang ở trạng thái active không
  var activeVal = deviceSheet.getRange(devRow, 5).getValue();
  if (activeVal != 1 && activeVal != "1") {
    return { ok: false, msg: "Thiết bị đã bị hủy kích hoạt." };
  }
  
  // Cập nhật last_seen
  deviceSheet.getRange(devRow, 6).setValue(now);
  
  var plan = user.data[2];
  var maxDevices = parseInt(user.data[3]) || 1;
  var expiresAt = parseInt(user.data[4]) || 0;
  var createdAt = parseInt(user.data[6]) || now;
  var status = user.data[5];
  
  var tier = getTier(plan, expiresAt, createdAt);
  var trialExp = plan === "free" ? (createdAt + (7 * 86400)) : 0;
  
  var payload = {
    uid: username,
    lid: user.rowNum,
    hwid: hwid,
    plan: plan,
    tier: tier,
    lic_exp: expiresAt,
    trial_exp: trialExp,
    exp: now + (7 * 86400)
  };
  
  var token = signToken(payload);
  
  return {
    ok: true,
    license_token: token,
    info: {
      plan: plan,
      tier: tier,
      status: status,
      max_devices: maxDevices,
      expires_at: expiresAt,
      hwid: hwid,
      lohapage: plan === "unlimited" || plan === "pro"
    }
  };
}

function deactivateDevice(req) {
  var session = req.token || "";
  var hwid = (req.hwid || "").trim();
  
  if (!session || !session.startsWith("session_")) {
    return { ok: false, msg: "Phiên không hợp lệ." };
  }
  
  var parts = session.split("_");
  var username = parts[parts.length - 1];
  
  var deviceSheet = getSheet(DEVICE_SHEET_NAME);
  var devRow = findDeviceRow(deviceSheet, username, hwid);
  if (!devRow) {
    return { ok: false, msg: "Không tìm thấy thiết bị." };
  }
  
  deviceSheet.getRange(devRow, 5).setValue(0); // set active = 0
  return { ok: true, msg: "Đã hủy kích hoạt thiết bị thành công." };
}

function listDevices(req) {
  var session = req.token || "";
  if (!session || !session.startsWith("session_")) {
    return { ok: false, msg: "Phiên làm việc hết hạn." };
  }
  
  var parts = session.split("_");
  var username = parts[parts.length - 1];
  
  var deviceSheet = getSheet(DEVICE_SHEET_NAME);
  var data = deviceSheet.getDataRange().getValues();
  var devices = [];
  
  for (var i = 1; i < data.length; i++) {
    var u = data[i][0].toString().trim().toLowerCase();
    if (u === username.toLowerCase()) {
      devices.push({
        hwid: data[i][1],
        device_name: data[i][2],
        os: data[i][3],
        active: data[i][4],
        last_seen: data[i][5],
        first_seen: data[i][6]
      });
    }
  }
  return { ok: true, devices: devices };
}
