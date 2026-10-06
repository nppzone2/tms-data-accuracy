"""Điều phối dữ liệu nhiều tháng.

  python engine/run.py prepare   1) mở kho mã hoá input/vault/*.enc ra work/<YYYY-MM>/
                                 2) file mới tải lên input/*.xlsx: tự nhận tháng từ cột Date của file TMS,
                                    chuyển vào work/<YYYY-MM>/ (thay dữ liệu cũ của tháng đó)
                                 3) tính KPI cho các tháng gần nhất -> build/months/<YYYY-MM>.json
  python engine/run.py save      mã hoá lại các tháng vừa thay vào input/vault/<YYYY-MM>.enc

Mỗi tháng tải 2 file (TMS Order Detail + Fill Rate) của tháng đó. Tải lại giữa tháng thì dữ liệu tháng đó
được thay bằng file mới. Kho giữ mọi tháng; trang hiển thị tháng hiện tại (đang chạy) và
N tháng đã hoàn thành gần nhất (completed_months_shown trong engine/config.json, mặc định 3).
Khoá mã hoá dẫn xuất từ secret ADMIN_PASSWORD.
"""
import io, json, os, re, shutil, subprocess, sys, zipfile
from pathlib import Path
import pandas as pd
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parents[1]
INPUT, VAULT, WORK, BUILD = ROOT / 'input', ROOT / 'input' / 'vault', ROOT / 'work', ROOT / 'build' / 'months'
from datetime import datetime, timedelta, timezone
CFG = json.load(open(ROOT / 'engine' / 'config.json', encoding='utf-8'))
DONE_SHOWN = int(CFG.get('completed_months_shown', 3))
CHANGED = ROOT / 'work' / '.changed'

pw = os.environ.get('ADMIN_PASSWORD', '').strip()
if not pw:
    sys.exit('LỖI: chưa đặt secret ADMIN_PASSWORD.')

def key(salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000).derive(pw.encode())

def decrypt(path):
    raw = path.read_bytes()
    salt, iv, ct = raw[5:21], raw[21:33], raw[33:]
    try:
        return AESGCM(key(salt)).decrypt(iv, ct, None)
    except Exception:
        sys.exit(f'LỖI: không giải mã được {path.name} (ADMIN_PASSWORD đã đổi?). Hãy tải lại file dữ liệu.')

def encrypt(data):
    salt, iv = os.urandom(16), os.urandom(12)
    return b'TMSV1' + salt + iv + AESGCM(key(salt)).encrypt(iv, data, None)

norm = lambda s: re.sub(r'[\s_\-]', '', s.lower())
is_tms = lambda p: 'tms' in norm(p.name)
is_fill = lambda p: 'fill' in norm(p.name)

def month_of(tms_path):
    """Tháng của dữ liệu = tháng xuất hiện nhiều nhất ở cột Date của file TMS."""
    d = pd.read_excel(tms_path, header=2, usecols=['Date'])
    return pd.to_datetime(d['Date'], errors='coerce').dt.strftime('%Y-%m').mode().iloc[0]

def unpack(data, dest):
    dest.mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(data)).extractall(dest)

def tag(p, word):
    """Phần tên file ngoài chữ TMS Order Detail / Fill Rate, dùng để ghép cặp (vd. _20261005)."""
    return re.sub(word, '', norm(p.stem))

def pick_pairs(files):
    """Ghép từng file TMS với file Fill Rate cùng hậu tố; nếu một tháng có nhiều cặp thì lấy cặp có dữ liệu mới nhất."""
    tms = [p for p in files if is_tms(p)]; fill = [p for p in files if is_fill(p)]
    other = [p.name for p in files if p not in tms and p not in fill]
    if not tms or not fill or other:
        sys.exit(f'LỖI: input/ cần file TMS Order Detail và file Fill Rate, đang có: {[p.name for p in files]}')
    best = {}
    for tf in tms:
        ff = [x for x in fill if tag(x, 'fillrate|fill') == tag(tf, 'tmsorderdetail|tms')]
        if not ff and len(tms) == 1 and len(fill) == 1: ff = fill
        if len(ff) != 1:
            sys.exit(f'LỖI: không ghép được file Fill Rate cho {tf.name}. Đặt tên 2 file cùng hậu tố, vd. "TMS Order Detail_20261005.xlsx" và "Fill Rate_20261005.xlsx".')
        d = pd.to_datetime(pd.read_excel(tf, header=2, usecols=['Date'])['Date'], errors='coerce')
        m = d.dt.strftime('%Y-%m').mode().iloc[0]
        rank = (d.max(), len(d))
        if m in best: print(f'Tháng {m} có nhiều bộ file, so sánh {best[m][2].name} với {tf.name}')
        if m not in best or rank > best[m][0]: best[m] = (rank, tf, ff[0])
    return [(m, tf, ff) for m, (_, tf, ff) in sorted(best.items())]

def prepare():
    shutil.rmtree(WORK, ignore_errors=True); shutil.rmtree(BUILD, ignore_errors=True)
    WORK.mkdir(parents=True); BUILD.mkdir(parents=True)
    changed = set()
    # 1. kho mã hoá theo tháng
    for f in sorted(VAULT.glob('*.enc')):
        unpack(decrypt(f), WORK / f.stem)
    # chuyển đổi kho cũ (một file last_data.enc) sang kho theo tháng
    legacy = INPUT / 'last_data.enc'
    if legacy.exists():
        tmp = WORK / '_legacy'; unpack(decrypt(legacy), tmp)
        t = next((p for p in tmp.glob('*.xlsx') if is_tms(p)), None)
        if t:
            m = month_of(t)
            if not (WORK / m).exists():
                tmp.rename(WORK / m); changed.add(m); print(f'Chuyển dữ liệu cũ sang tháng {m}')
        shutil.rmtree(tmp, ignore_errors=True)
    # 2. file mới tải lên
    new = [p for p in INPUT.glob('*.xlsx') if not p.name.startswith('~$')]
    if new:
        for m, tf, ff in pick_pairs(new):
            dest = WORK / m
            shutil.rmtree(dest, ignore_errors=True); dest.mkdir(parents=True)
            for p in (tf, ff): shutil.copy2(p, dest / p.name)
            changed.add(m); print(f'Nhận dữ liệu mới cho tháng {m}: {tf.name}, {ff.name}')
    months = sorted(p.name for p in WORK.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}', p.name))
    if not months:
        sys.exit('LỖI: chưa có dữ liệu. Hãy tải 2 file TMS Order Detail và Fill Rate vào input/.')
    cur = (datetime.now(timezone.utc) + timedelta(hours=7)).strftime('%Y-%m')   # tháng hiện tại (giờ Việt Nam)
    done = [m for m in months if m < cur][-DONE_SHOWN:]
    live = [m for m in months if m >= cur][-1:]
    shown = done + live
    (ROOT / 'build').mkdir(exist_ok=True)
    (ROOT / 'build' / 'months_meta.json').write_text(json.dumps(dict(shown=shown, completed=done, current=live[0] if live else None)))
    print('Có dữ liệu các tháng:', ', '.join(months), '· hoàn thành hiển thị:', ', '.join(done) or '—', '· đang chạy:', ', '.join(live) or '—')
    # 3. tính KPI từng tháng
    for m in shown:
        r = subprocess.run([sys.executable, str(ROOT / 'engine' / 'compute.py'), str(WORK / m), str(BUILD / f'{m}.json')])
        if r.returncode: sys.exit(f'LỖI khi tính tháng {m}.')
    CHANGED.write_text('\n'.join(sorted(changed)))

def save():
    VAULT.mkdir(parents=True, exist_ok=True)
    changed = [m for m in (CHANGED.read_text().split() if CHANGED.exists() else []) if m]
    for m in changed:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted((WORK / m).glob('*.xlsx')): z.write(p, p.name)
        (VAULT / f'{m}.enc').write_bytes(encrypt(buf.getvalue()))
        print(f'Đã lưu kho mã hoá tháng {m}')
    legacy = INPUT / 'last_data.enc'
    if legacy.exists(): legacy.unlink()

{'prepare': prepare, 'save': save}.get(sys.argv[1] if len(sys.argv) > 1 else '', lambda: sys.exit('Cách dùng: python engine/run.py prepare|save'))()
