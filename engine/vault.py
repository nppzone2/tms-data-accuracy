"""Lưu bản mã hoá của 2 file dữ liệu gần nhất để workflow dựng lại trang khi chỉ sửa giao diện hoặc logic,
mà không để file Excel gốc nằm công khai trong repo.

  python engine/vault.py save     mã hoá input/*.xlsx -> input/last_data.enc
  python engine/vault.py restore  nếu input/ chưa có file .xlsx thì giải mã input/last_data.enc ra input/

Khoá mã hoá dẫn xuất từ secret ADMIN_PASSWORD.
"""
import io, os, sys, zipfile
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'input'
VAULT = INPUT / 'last_data.enc'

pw = os.environ.get('ADMIN_PASSWORD', '').strip()
if not pw:
    sys.exit('LỖI: chưa đặt secret ADMIN_PASSWORD.')

def key(salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000).derive(pw.encode())

xlsx = [p for p in INPUT.glob('*.xlsx') if not p.name.startswith('~$')]
cmd = sys.argv[1] if len(sys.argv) > 1 else ''

if cmd == 'save':
    if not xlsx:
        sys.exit('Không có file .xlsx trong input/ để lưu.')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in xlsx: z.write(p, p.name)
    salt, iv = os.urandom(16), os.urandom(12)
    VAULT.write_bytes(b'TMSV1' + salt + iv + AESGCM(key(salt)).encrypt(iv, buf.getvalue(), None))
    print(f'Đã lưu bản mã hoá {len(xlsx)} file vào {VAULT.relative_to(ROOT)}')
elif cmd == 'restore':
    if xlsx:
        print('input/ đã có file mới, dùng file mới.')
    elif not VAULT.exists():
        sys.exit('LỖI: input/ chưa có file dữ liệu. Hãy tải 2 file TMS Order Detail và Fill Rate vào input/.')
    else:
        raw = VAULT.read_bytes()
        salt, iv, ct = raw[5:21], raw[21:33], raw[33:]
        try:
            data = AESGCM(key(salt)).decrypt(iv, ct, None)
        except Exception:
            sys.exit('LỖI: không giải mã được dữ liệu cũ (ADMIN_PASSWORD đã đổi?). Hãy tải lại 2 file vào input/.')
        zipfile.ZipFile(io.BytesIO(data)).extractall(INPUT)
        print('Dùng lại dữ liệu lần cập nhật trước.')
else:
    sys.exit('Cách dùng: python engine/vault.py save|restore')
