# TMS Data Accuracy

Dashboard KPI Data Accuracy của các nhà phân phối (NPP), tự cập nhật mỗi khi có file dữ liệu mới.

## Cập nhật dữ liệu hằng ngày

1. Mở thư mục **`input/`** trên trang GitHub của repo.
2. Bấm **Add file → Upload files**, kéo thả 2 file:
   - file TMS Order Detail (tên có chữ `TMS`, ví dụ `TMS Order Detail.xlsx`)
   - file Fill Rate (tên có chữ `Fill`, ví dụ `Fill Rate.xlsx`)
3. Bấm **Commit changes**.

Khoảng 2–3 phút sau trang dashboard tự cập nhật. Theo dõi tiến trình ở tab **Actions**: dấu ✓ xanh là xong, dấu ✕ đỏ là lỗi (bấm vào để xem lý do).

Nếu repo để công khai (Public), sau khi dựng xong workflow sẽ tự xoá 2 file Excel khỏi `input/` để người ngoài không tải được dữ liệu gốc. Vì vậy mỗi lần cập nhật cần tải lên đủ cả 2 file.

## Cài đặt lần đầu (làm một lần)

1. **Đặt mật khẩu** — Settings → Secrets and variables → Actions → New repository secret:
   - `ADMIN_PASSWORD`: mật khẩu tài khoản `admin` (xem tất cả NPP).
   - `NPP_PASSWORDS`: mật khẩu từng NPP, dạng JSON, ví dụ
     `{"HM":"...","HM12":"...","P69":"...","P444":"...","P449":"...","P450":"...","P461":"...","P467":"...","P468":"..."}`
     NPP nào không khai báo thì dùng DisCode làm mật khẩu (không khuyến khích vì dễ đoán).
2. **Bật trang web** — Settings → Pages → Build and deployment → Source: chọn **GitHub Actions**.
3. Tải 2 file dữ liệu vào `input/` như trên. Link trang hiện ở Settings → Pages, dạng `https://<tài-khoản>.github.io/tms-data-accuracy/`.

Đổi mật khẩu: sửa secret rồi tải lại 2 file dữ liệu.

## Bảo mật

Dữ liệu trên trang được mã hoá (AES-GCM, khoá dẫn xuất PBKDF2-SHA256 từ mật khẩu). Admin mở được toàn bộ; mỗi NPP chỉ mở được dữ liệu của mình. Xem mã nguồn trang cũng không đọc được số liệu. Mật khẩu không nằm trong repo.

Lưu ý: nếu repo công khai, file Excel đã tải lên vẫn còn trong lịch sử commit dù đã bị xoá khỏi thư mục. Muốn kín hoàn toàn, chuyển repo sang **Private** (GitHub Pages cho repo Private cần gói GitHub Pro/Team).

## Đăng nhập

| Tài khoản | Tên đăng nhập | Thấy gì |
|---|---|---|
| Admin | `admin` | Tất cả NPP, thêm tab Chất lượng dữ liệu |
| NPP | mã NPP, ví dụ `P467` | Chỉ dữ liệu của NPP đó |

## Cách chấm

**Kết quả tháng = đạt cả 4 tiêu chí:**

| Tiêu chí | Lỗi | NPP đạt khi |
|---|---|---|
| Payload | chuyến có tổng tải / tải trọng xe ≥ 1,5 | chuyến quá tải < 5% tổng chuyến |
| Distance & Time | đơn có `time_outlet_outlet` < 2 phút và cách outlet trước > 10m; chuyến hỏng khi đơn đúng < 70% | chuyến hỏng < 5% tổng chuyến |
| Created Date | đơn tạo (Fill Rate `Sent_To_distributor`, ghép `DocNo = OrderNumber`) sau giờ giao; 1 đơn lỗi là chuyến lỗi | 0 chuyến lỗi |
| User name | tài khoản không phải SĐT, biển số xe hoặc DSA | 0 tài khoản sai |

**Chỉ số theo dõi (không tính vào kết quả):** Geo Compliance (≥ 85%), On time `is_ontime` (> 95%), On time 24H (> 95%; chốt 17:00, thứ 7 sau 17:00 sang thứ 2, trừ Chủ nhật nếu không giao Chủ nhật, giao sau 20:00 là lỗi), Chuyến lỗi > 30% với bất kỳ KPI nào (≤ 5% chuyến).

## Cấu trúc

```
input/                  nơi tải 2 file Excel lên
engine/compute.py       tính toàn bộ KPI -> build/data.json
engine/build_site.py    mã hoá dữ liệu, dựng docs/index.html
engine/template.html    giao diện dashboard
.github/workflows/      workflow tự chạy khi có file mới
```

Chạy trên máy: `pip install -r requirements.txt`, đặt 2 file vào `input/`, rồi
`python engine/compute.py && ADMIN_PASSWORD=... python engine/build_site.py`, mở `docs/index.html` qua một web server (ví dụ `python -m http.server -d docs`).
