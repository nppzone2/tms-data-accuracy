"""Dựng trang dashboard đã mã hoá từ build/months/<YYYY-MM>.json -> docs/index.html.

Đăng nhập NPP: tên đăng nhập là mã NPP (DisCode trong file Fill Rate, dạng 8 chữ số);
gõ tên NPP (ví dụ P444) cũng được.
Mật khẩu lấy từ biến môi trường (GitHub Secrets):
  ADMIN_PASSWORD  mật khẩu tài khoản admin (xem toàn bộ NPP)
  NPP_PASSWORD    mật khẩu chung cho mọi NPP
  NPP_PASSWORDS   (tuỳ chọn) JSON {"P444": "matkhau", ...} để đặt mật khẩu riêng cho từng NPP
Mỗi tài khoản nhận một gói gồm mọi tháng đang hiển thị; NPP chỉ nhận dữ liệu của mình.
"""
import base64, gzip, json, os, sys
from pathlib import Path
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
ITER = 200_000

files = sorted((ROOT / 'build' / 'months').glob('*.json'))
if not files:
    sys.exit('LỖI: chưa có dữ liệu tháng nào trong build/months/. Chạy engine/run.py prepare trước.')
MM = json.load(open(ROOT / 'build' / 'months_meta.json')) if (ROOT / 'build' / 'months_meta.json').exists() else {}
MONTHS = {f.stem: json.load(open(f, encoding='utf-8')) for f in files if not MM or f.stem in MM['shown']}
ORDER = sorted(MONTHS)
DONE = [m for m in MM.get('completed', ORDER) if m in MONTHS]   # tháng đã hoàn thành
CUR = MM.get('current')
auth = {}
for d in MONTHS.values():
    auth.update(d.pop('auth'))       # mật khẩu mặc định (DisCode) — không bao giờ đưa vào trang
NPPS = sorted(auth)

admin_pw = os.environ.get('ADMIN_PASSWORD', '').strip()
npp_pw = json.loads(os.environ.get('NPP_PASSWORDS', '') or '{}')
common_pw = os.environ.get('NPP_PASSWORD', '').strip()
if not admin_pw:
    sys.exit('LỖI: chưa đặt secret ADMIN_PASSWORD. Vào Settings → Secrets and variables → Actions để thêm.')
warn = []
for n in NPPS:
    if not str(npp_pw.get(n, '')).strip():
        if common_pw: npp_pw[n] = common_pw
        else: npp_pw[n] = auth[n]; warn.append(n)
if warn:
    print('Cảnh báo: chưa đặt NPP_PASSWORD, dùng DisCode làm mật khẩu cho', ', '.join(warn))

def b64(b): return base64.b64encode(b).decode()

def seal(obj, password):
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password.strip().encode())
    raw = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode(), 9)
    return dict(salt=b64(salt), iv=b64(iv), ct=b64(AESGCM(key).encrypt(iv, raw, None)))

def slice_for(data, n):
    """Chỉ giữ dữ liệu của một NPP trong một tháng."""
    d = {k: v for k, v in data.items() if k not in ('dq', 'sens')}
    row = next(s for s in data['scorecard'] if s['npp'] == n)
    keep = lambda rows: [r for r in rows if (r.get('npp') or r.get('TenantName')) == n]
    ti = data['err_keys'].index('TenantName')
    d.update(npps=[n], scorecard=[row], total=row,
             npp_info={n: data['npp_info'][n]},
             errors=[e for e in data['errors'] if e[ti] == n],
             daily={n: data['daily'][n], 'ALL': data['daily'][n]}, geo_dist={n: data['geo_dist'][n]}, hours={n: data['hours'][n]},
             users={'ALL': keep(data['users']['ALL'])},
             dt_top=keep(data['dt_top']), pl_top=keep(data['pl_top']), cd_list=keep(data['cd_list']),
             plan_list=keep(data['plan_list']), late_list=keep(data.get('late_list', [])))
    d['meta'] = dict(data['meta'], npps=1)
    return d

blobs = {'admin': seal(dict(__role='admin', order=ORDER, completed=DONE, current=CUR, months=MONTHS), admin_pw)}
for n in NPPS:
    mine = {m: slice_for(d, n) for m, d in MONTHS.items() if n in d['npps']}
    blobs[auth[n]] = seal(dict(__role=n, order=sorted(mine), completed=[m for m in DONE if m in mine], current=CUR if CUR in mine else None, months=mine), npp_pw[n])
alias = {n.lower(): auth[n] for n in NPPS}   # gõ tên NPP cũng mở được

last = MONTHS[ORDER[-1]]['meta']
enc = dict(iter=ITER, period=', '.join(f'T{int(m[5:])}/{m[:4]}' for m in ORDER), built=last['built'], blobs=blobs, alias=alias)
tpl = (ROOT / 'engine' / 'template.html').read_text(encoding='utf-8')
page = tpl.replace('/*__ENC__*/', json.dumps(enc).replace('</', '<\\/'))
head = ('<!doctype html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="robots" content="noindex,nofollow"></head><body>')
out = ROOT / 'docs' / 'index.html'
out.parent.mkdir(exist_ok=True)
out.write_text(head + page + '</body></html>', encoding='utf-8')
(ROOT / 'docs' / '.nojekyll').write_text('')
print(f'Đã dựng {out.relative_to(ROOT)} ({out.stat().st_size/1024:,.0f} KB) · tháng: {", ".join(ORDER)} · {len(blobs)} tài khoản.')
