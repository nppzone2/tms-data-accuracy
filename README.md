# TMS Data Accuracy

Dashboard KPI Data Accuracy của các nhà phân phối (NPP), tự cập nhật mỗi khi có file dữ liệu mới.

## Cập nhật dữ liệu

1. Mở thư mục **`input/`** trên trang GitHub của repo.
2. Bấm **Add file → Upload files**, kéo thả 2 file **của cùng một tháng**:
   - file TMS Order Detail (tên có chữ `TMS`)
   - file Fill Rate (tên có chữ `Fill`)
3. Bấm **Commit changes**.

Workflow tự nhận tháng từ cột `Date` của file TMS. Trang hiển thị **3 tháng đã hoàn thành gần nhất và tháng đang chạy** (ô chọn tháng ghi "đang chạy"); tab **3 tháng** chỉ tổng hợp các tháng đã hoàn thành. Trang tự dựng lại lúc 10:00 mỗi ngày (giờ Việt Nam).

**Loại trừ ngày:** khai báo trong `engine/config.json` (`exclude_dates`). Đơn có `Date` trong khoảng này bị loại khỏi toàn bộ KPI. Hiện đang loại trừ 16/09–23/09/2026. Sửa file này trên GitHub rồi Commit, trang tự dựng lại. Tải lại trong tháng thì dữ liệu tháng đó được thay bằng file mới; sang tháng mới thì tháng cũ được giữ lại. Trang hiển thị **3 tháng gần nhất**, có ô chọn tháng ở thanh tiêu đề và tab **3 tháng** để so sánh đạt / rớt từng tiêu chí.

Mỗi lần chỉ tải 2 file của một tháng. Muốn nạp nhiều tháng, tải lần lượt từng tháng và đợi lần trước chạy xong (dấu ✓ xanh ở tab **Actions**, khoảng 2–3 phút).

Dữ liệu từng tháng được lưu dạng **mã hoá** trong `input/vault/` (khoá từ `ADMIN_PASSWORD`). Nếu repo công khai, workflow xoá 2 file Excel gốc khỏi `input/` sau khi xử lý. Khi sửa giao diện hoặc logic trong `engine/`, trang tự dựng lại với dữ liệu đã lưu. Lưu ý: đổi `ADMIN_PASSWORD` thì kho cũ không mở được nữa, cần tải lại dữ liệu các tháng.

## Cài đặt lần đầu (làm một lần)

1. **Đặt mật khẩu** — Settings → Secrets and variables → Actions → New repository secret:
   - `ADMIN_PASSWORD`: mật khẩu tài khoản `admin` (xem tất cả NPP).
   - `NPP_PASSWORD`: mật khẩu chung cho tất cả NPP, ví dụ `User@123`.
   - (Tuỳ chọn) `NPP_PASSWORDS`: mật khẩu riêng cho từng NPP, dạng JSON `{"P444":"...","P461":"..."}`. NPP có trong đây dùng mật khẩu riêng, còn lại dùng mật khẩu chung.
2. **Bật trang web** — Settings → Pages → Build and deployment → Source: chọn **GitHub Actions**.
3. Tải 2 file dữ liệu vào `input/` như trên. Link trang hiện ở Settings → Pages, dạng `https://<tài-khoản>.github.io/tms-data-accuracy/`.

Đổi mật khẩu: sửa secret rồi tải lại 2 file dữ liệu.

## Bảo mật

Dữ liệu trên trang được mã hoá (AES-GCM, khoá dẫn xuất PBKDF2-SHA256 từ mật khẩu). Admin mở được toàn bộ; mỗi NPP chỉ mở được dữ liệu của mình. Nếu dùng mật khẩu chung, NPP nào biết mã của NPP khác thì mở được dữ liệu NPP đó — muốn tách hẳn thì đặt `NPP_PASSWORDS`. Xem mã nguồn trang cũng không đọc được số liệu. Mật khẩu không nằm trong repo.

Lưu ý: nếu repo công khai, file Excel đã tải lên vẫn còn trong lịch sử commit dù đã bị xoá khỏi thư mục. Muốn kín hoàn toàn, chuyển repo sang **Private** (GitHub Pages cho repo Private cần gói GitHub Pro/Team).

## Đăng nhập

| Tài khoản | Tên đăng nhập | Thấy gì |
|---|---|---|
| Admin | `admin` | Tất cả NPP, thêm tab Chất lượng dữ liệu |
| NPP | mã NPP (DisCode), ví dụ `10349819`; gõ tên NPP như `P467` cũng được | Chỉ dữ liệu của NPP đó |

## Cách chấm

**Kết quả tháng = đạt cả 4 tiêu chí:**

| Tiêu chí | Lỗi | NPP đạt khi |
|---|---|---|
| Payload | chuyến có tổng tải / tải trọng xe ≥ 1,5 | chuyến quá tải < 5% tổng chuyến |
| Distance & Time | đơn có `time_outlet_outlet` < 2 phút và cách outlet trước > 10m; chuyến hỏng khi đơn đúng < 70%; **không tính đơn tài khoản DSA** | chuyến hỏng < 5% tổng chuyến (không tính chuyến chỉ có DSA) |
| Created Date | đơn tạo (Fill Rate `Sent_To_distributor`, ghép `DocNo = OrderNumber`) sau giờ giao; 1 đơn lỗi là chuyến lỗi | 0 chuyến lỗi |
| User name | tài khoản không phải SĐT, biển số xe hoặc DSA | 0 tài khoản sai |

**Năng lực giao hàng (không tính là lỗi, không ảnh hưởng kết quả):** On time `is_ontime` (tham chiếu > 95%), On time 24H (tham chiếu > 95%; chốt 17:00, thứ 7 sau 17:00 sang thứ 2, trừ Chủ nhật nếu không giao Chủ nhật, giao sau 20:00 tính là chưa đạt).

**Chỉ số theo dõi (không tính vào kết quả):** Geo Compliance (≥ 85%), Chuyến lỗi > 30% gộp lỗi Payload, D&T, Created Date, User name, Geo (≤ 5% chuyến).

## Cấu trúc

```
input/                  nơi tải 2 file Excel lên
engine/compute.py       tính toàn bộ KPI -> build/data.json
engine/build_site.py    mã hoá dữ liệu, dựng docs/index.html
engine/template.html    giao diện dashboard
engine/run.py           nhận tháng, lưu / mở kho mã hoá theo tháng, tính KPI từng tháng
input/vault/            kho dữ liệu mã hoá, mỗi tháng một file
.github/workflows/      workflow tự chạy khi có file mới
```

Chạy trên máy: `pip install -r requirements.txt`, đặt 2 file vào `input/`, rồi
`ADMIN_PASSWORD=... python engine/run.py prepare && ADMIN_PASSWORD=... python engine/build_site.py`, mở `docs/index.html` qua một web server (ví dụ `python -m http.server -d docs`).
