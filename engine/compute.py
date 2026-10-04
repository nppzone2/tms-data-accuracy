"""Tính KPI TMS Data Accuracy theo logic dashboard gốc (v65) + tiêu chí Created Date.
Đầu vào: TMS_Order_Detail.xlsx, Fill_Rate.xlsx (Sent_To_distributor = Created Date, ghép DocNo = OrderNumber).
Đầu ra: data.json (nhúng vào dashboard)."""
import pandas as pd, numpy as np, json, re, math, sys
from datetime import datetime

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
# Cách dùng: python engine/compute.py <thư mục chứa 2 file> <file json đầu ra>
INPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'input'
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'build' / 'data.json'

def find_input(*keys):
    """Tìm file .xlsx trong input/ có tên chứa đủ các từ khoá (không phân biệt hoa thường, bỏ dấu cách/gạch)."""
    norm = lambda s: re.sub(r'[\s_\-]', '', s.lower())
    hits = [p for p in INPUT.glob('*.xlsx') if not p.name.startswith('~$') and all(k in norm(p.name) for k in keys)]
    if not hits:
        sys.exit(f'LỖI: không tìm thấy file chứa {keys} trong {INPUT}.')
    if len(hits) > 1:
        hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        print(f'Cảnh báo: có {len(hits)} file khớp {keys}, dùng file mới nhất: {hits[0].name}')
    return hits[0]

TMS_F, FR_F = find_input('tms'), find_input('fill')
print('Đọc', TMS_F.name, 'và', FR_F.name)

TH = dict(username=100.0, geo=85.0, ontime=95.0, successful=95.0, payload_plans=0, created=100.0,
          dt_route_pct=0.30, dt_month_pct=0.05, dt_gap_min=2, dt_dist_min=10, payload_tol=0.05, geo_radius_m=50, geo_gap_min=2,
          payload_ratio=1.5, work_start=6, work_end=20)

t = pd.read_excel(TMS_F, header=2)
f = pd.read_excel(FR_F, header=2)
t['OrderNumber'] = t.OrderNumber.astype(str).str.strip()
f['DocNo'] = f.DocNo.astype(str).str.strip()
# ---------- loại trừ khoảng ngày theo engine/config.json ----------
CFG = json.load(open(ROOT / 'engine' / 'config.json', encoding='utf-8'))
EXCL = []
for x in CFG.get('exclude_dates', []):
    a, b = pd.Timestamp(x['from']), pd.Timestamp(x['to'])
    hit = t.Date.between(a, b + pd.Timedelta(hours=23, minutes=59, seconds=59))
    if hit.any():
        EXCL.append(dict(start=a.strftime('%d/%m/%Y'), end=b.strftime('%d/%m/%Y'), note=x.get('note', ''),
                         orders=int(hit.sum()), plans=int(t.loc[hit, 'PlanNumber'].nunique())))
        t = t[~hit].copy()
        print(f'Loại trừ {EXCL[-1]["start"]}–{EXCL[-1]["end"]}: {EXCL[-1]["orders"]:,} đơn, {EXCL[-1]["plans"]:,} chuyến')
n_file = len(t)
dup = int(t.OrderNumber.duplicated().sum())

m = t.merge(f[['DocNo', 'Sent_To_distributor', 'DisCode', 'Distributor_Name', 'Area_Name']],
            left_on='OrderNumber', right_on='DocNo', how='left')
assert len(m) == n_file

# ---------- loại tài khoản ----------
def utype(u):
    u = str(u).strip().upper()
    if 'DSA' in u: return 'DSA'
    if re.fullmatch(r'0\d{9}', u): return 'SĐT tài xế'
    if re.fullmatch(r'\d{2}[A-Z]{1,2}\d?-?\d{3,5}(\.\d{2})?', u.replace(' ', '')): return 'Biển số xe'
    return 'Không hợp lệ'
m['utype'] = m.username.map(utype)

# ---------- thứ tự trong chuyến + khoảng cách thời gian outlet-outlet ----------
m = m.sort_values(['PlanNumber', 'DeliverDateTime'], na_position='last').reset_index(drop=True)
m['seq'] = m.groupby('PlanNumber').cumcount() + 1
m['gap'] = m.groupby('PlanNumber').DeliverDateTime.diff().dt.total_seconds() / 60
m['plan_orders'] = m.groupby('PlanNumber').OrderNumber.transform('count')

# ---------- 1. User name ----------
m['f_user'] = m.utype.eq('Không hợp lệ')

# ---------- 2. Geo (bỏ DSA) ----------
m['geo_scope'] = m.utype.ne('DSA')
hr = m.DeliverDateTime.dt.hour + m.DeliverDateTime.dt.minute / 60
m['g_v'] = m.distance_to_dropped > TH['geo_radius_m']
m['g_w'] = (m.seq > 1) & m.gap.notna() & (m.gap <= TH['geo_gap_min'])
m['g_x'] = m.DeliverDateTime.isna() | (hr < TH['work_start']) | (hr >= TH['work_end'])
m['f_geo'] = m.geo_scope & (m.g_v | m.g_w | m.g_x)

# ---------- 3/4. On time + Successful (dùng chung is_ontime như bản gốc) ----------
m['f_ot'] = m.is_ontime.ne(1)
m['late_days'] = (m.DeliverDateTime.dt.normalize() - m.PromisedDate).dt.days

# ---------- 5. Distance & Time (theo chuyến) ----------
la, lo = m.lat_to, m.long_to
pla = la.groupby(m.PlanNumber).shift(); plo = lo.groupby(m.PlanNumber).shift()
_h = np.sin(np.radians(pla - la) / 2) ** 2 + np.cos(np.radians(la)) * np.cos(np.radians(pla)) * np.sin(np.radians(lo - plo) / 2) ** 2
m['dist_oo'] = 2 * 6371000 * np.arcsin(np.sqrt(_h))
# Đơn của tài khoản DSA không xét Distance & Time (outlet tới outlet) — cập nhật 04/10/2026
m['dt_scope'] = m.utype.ne('DSA')
m['dt_bad'] = m.dt_scope & (m.time_outlet_outlet < TH['dt_gap_min']) & (m.dist_oo > TH['dt_dist_min'])
pl = m.groupby('PlanNumber').agg(npp=('TenantName', 'first'), orders=('OrderNumber', 'count'),
                                 bad=('dt_bad', 'sum'), dt_n=('dt_scope', 'sum'), w=('Assigned_Weight', 'sum'),
                                 cap=('TruckCapacityWeight', 'max'), capmin=('TruckCapacityWeight', 'min'),
                                 truck=('DriverName', 'first'), user=('username', 'first'),
                                 date=('Date', 'min'))
pl['dt_in'] = pl.dt_n > 0                                   # chuyến có ít nhất 1 đơn không phải DSA
pl['dt_fail'] = pl.dt_in & (pl.bad / pl.dt_n.where(pl.dt_n > 0, 1) > TH['dt_route_pct'])
pl['ratio'] = (pl.w / pl.cap).round(3)
pl['pl_fail'] = (pl.w / pl.cap) >= TH['payload_ratio']
m = m.merge(pl[['dt_fail', 'ratio', 'pl_fail']].rename(columns={'dt_fail': 'plan_dt_fail', 'ratio': 'plan_ratio', 'pl_fail': 'plan_pl_fail'}),
            left_on='PlanNumber', right_index=True, how='left')
m['f_dt'] = m.dt_bad                       # đơn lỗi D&T (nhãn trên đơn)
m['f_pl'] = m.plan_pl_fail                 # đơn thuộc chuyến quá tải

# ---------- 7. Created Date ----------
m['cd_scope'] = m.Sent_To_distributor.notna() & m.DeliverDateTime.notna()
m['cd_gap_h'] = (m.DeliverDateTime - m.Sent_To_distributor).dt.total_seconds() / 3600
m['f_cd'] = m.cd_scope & (m.cd_gap_h < 0)

# ---------- On time 24H + Working Hour (theo dõi) ----------
# Đồng hồ 24H tính từ thời điểm tạo đơn (Sent_To_distributor) tới DeliverDateTime.
# Đơn tạo từ 17:00 trở đi và giao sau ngày tạo: đồng hồ bắt đầu 00:00 ngày kế tiếp;
#   tạo thứ 7 từ 17:00 thì bắt đầu 00:00 thứ 2 (trừ khi giao vào Chủ nhật: bắt đầu 00:00 Chủ nhật).
# Chủ nhật là ngày nghỉ: nếu đơn KHÔNG giao vào Chủ nhật thì trừ phần thời gian rơi vào Chủ nhật.
#   Nếu giao vào Chủ nhật thì thời lượng = giờ giao - giờ bắt đầu, không trừ.
# Thời lượng âm (tạo sau khi giao) là Fail. Giao sau 20:00:00 là lỗi Working Hour.
TH.update(sla_hours=24, send_cutoff=17, wh_end=20)
send, dlv = m.Sent_To_distributor, m.DeliverDateTime
m['h24_scope'] = send.notna() & dlv.notna()
def _dur(s, d):
    if pd.isna(s) or pd.isna(d): return np.nan
    start = s
    if s.hour >= TH['send_cutoff'] and d.normalize() > s.normalize():
        start = s.normalize() + pd.Timedelta(days=1)
        if s.dayofweek == 5 and d.dayofweek != 6: start += pd.Timedelta(days=1)   # thứ 7 -> thứ 2
    sec = (d - start).total_seconds()
    if d.dayofweek != 6 and sec > 0:
        day = start.normalize()
        while day <= d:
            if day.dayofweek == 6:
                lo, hi = max(start, day), min(d, day + pd.Timedelta(days=1))
                if hi > lo: sec -= (hi - lo).total_seconds()
            day += pd.Timedelta(days=1)
    return sec / 3600
m['h24_dur'] = [_dur(a, b) for a, b in zip(send, dlv)]
m['h24_fail'] = m.h24_scope & ~((m.h24_dur >= 0) & (m.h24_dur <= TH['sla_hours']))
m['wh_fail'] = dlv.notna() & ((dlv.dt.hour > TH['wh_end']) | ((dlv.dt.hour == TH['wh_end']) & ((dlv.dt.minute > 0) | (dlv.dt.second > 0))))
m['t24_scope'] = dlv.notna()
m['f_24'] = m.h24_fail | m.wh_fail

# On time và 24H đo năng lực giao hàng, KHÔNG tính là lỗi đơn (04/10/2026).
m['any_err'] = m[['f_user', 'f_geo', 'f_dt', 'f_pl', 'f_cd']].any(axis=1)
m['late'] = m.f_ot | m.f_24

# ---------- LOGIC MỚI (04/10/2026): chấm theo chuyến ----------
# Đơn lỗi = đơn có ít nhất 1 lỗi ở bất kỳ KPI nào. Chuyến fail khi đơn lỗi > 30% tổng đơn của chuyến.
# NPP đạt khi tỷ lệ chuyến fail <= 5% tổng chuyến VÀ không có đơn lỗi Created Date.
TH.update(plan_err_pct=0.30, npp_plan_tol=0.05)
pe = m.groupby('PlanNumber').agg(err=('any_err', 'sum'), e_geo=('f_geo', 'sum'), e_ot=('f_ot', 'sum'),
                                 e_dt=('f_dt', 'sum'), e_pl=('f_pl', 'sum'), e_cd=('f_cd', 'sum'), e_user=('f_user', 'sum'))
pl = pl.join(pe)
pl['err_ratio'] = pl.err / pl.orders
pl['plan_fail'] = pl.err_ratio > TH['plan_err_pct']
pl['cd_fail'] = pl.e_cd > 0
m = m.merge(pl[['err', 'err_ratio', 'plan_fail', 'cd_fail']].rename(columns={'cd_fail': 'plan_cd_fail', 'err': 'plan_err', 'err_ratio': 'plan_err_ratio'}),
            left_on='PlanNumber', right_index=True, how='left')

NPPS = sorted(m.TenantName.unique(), key=lambda s: (s.rstrip('0123456789'), int(re.sub(r'\D', '', s) or 0)))

def wilson(k, n, z=1.96):
    if n == 0: return [None, None]
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round((c - h) * 100, 2), round((c + h) * 100, 2)]

def pct(a, b): return round(a / b * 100, 2) if b else None

def score(d, p, name):
    n = len(d); np_ = len(p)
    gs = int(d.geo_scope.sum()); gf = int(d.f_geo.sum())
    otf = int(d.f_ot.sum())
    t24s = int(d.t24_scope.sum()); t24f = int(d.f_24.sum())
    cds = int(d.cd_scope.sum()); cdf = int(d.f_cd.sum())
    dtr = int(p.dt_fail.sum()); plf = int(p.pl_fail.sum()); dtn = int(p.dt_in.sum()); dts = int(d.dt_scope.sum())
    r = dict(npp=name, orders=n, plans=np_,
             date_min=str(d.Date.min().date()), date_max=str(d.Date.max().date()),
             username_pct=pct(n - int(d.f_user.sum()), n), username_fail=int(d.f_user.sum()),
             geo_scope=gs, geo_excluded=n - gs, geo_fail=gf, geo_pct=pct(gs - gf, gs),
             geo_v=int((d.geo_scope & d.g_v).sum()), geo_w=int((d.geo_scope & d.g_w).sum()),
             geo_x=int((d.geo_scope & d.g_x).sum()),
             geo_x_nodate=int((d.geo_scope & d.DeliverDateTime.isna()).sum()),
             ot_fail=otf, ot_pct=pct(n - otf, n),
             succ_fail=otf, succ_pct=pct(n - otf, n),
             t24_scope=t24s, t24_fail=t24f, t24_pct=pct(t24s - t24f, t24s),
             h24_scope=int(d.h24_scope.sum()), h24_fail=int(d.h24_fail.sum()), wh_fail=int(d.wh_fail.sum()),
             h24_na=int((~d.h24_scope).sum()),
             h24_bins=[int(x) for x in [(d.h24_scope & (d.h24_dur < 0)).sum(), ((d.h24_dur >= 0) & (d.h24_dur <= 12)).sum(),
                       ((d.h24_dur > 12) & (d.h24_dur <= 24)).sum(), ((d.h24_dur > 24) & (d.h24_dur <= 48)).sum(),
                       ((d.h24_dur > 48) & (d.h24_dur <= 72)).sum(), (d.h24_dur > 72).sum()]],
             dt_orders_fail=int(d.f_dt.sum()), dt_pct=pct(dts - int(d.f_dt.sum()), dts), dt_scope_orders=dts, dt_excl_orders=n - dts,
             dt_routes_any=int((p.bad > 0).sum()), dt_routes_fail=dtr, dt_plans=dtn, dt_excl_plans=np_ - dtn, dt_route_fail_pct=pct(dtr, dtn),
             payload_plans_fail=plf, pl_orders=int(d.f_pl.sum()), payload_pct=pct(np_ - plf, np_),
             payload_max_ratio=float(p.ratio.max()) if np_ else 0,
             cd_scope=cds, cd_fail=cdf, cd_pct=pct(cds - cdf, cds), cd_unmatched=n - cds,
             err_orders=int(d.any_err.sum()), err_pct=pct(int(d.any_err.sum()), n),
             user_types={k: int(v) for k, v in d.utype.value_counts().items()})
    users = d.drop_duplicates('username'); uw = int(users.utype.eq('Không hợp lệ').sum())
    r['users_total'] = len(users); r['users_wrong'] = uw
    r['users_wrong_list'] = users[users.utype.eq('Không hợp lệ')].username.tolist()[:20]
    cdr = int(p.cd_fail.sum()); r['cd_routes_fail'] = cdr
    r['payload_fail_pct'] = pct(plf, np_)
    # --- KẾT QUẢ DATA ACCURACY: 4 tiêu chí theo file chính thức ---
    r['v_username'] = 'PASS' if uw == 0 else 'FAIL'
    r['v_dt'] = 'PASS' if (r['dt_route_fail_pct'] or 0) < TH['dt_month_pct'] * 100 else 'FAIL'
    r['v_created'] = 'PASS' if cdr == 0 else 'FAIL'
    r['v_payload'] = 'PASS' if r['payload_fail_pct'] < TH['payload_tol'] * 100 else 'FAIL'
    keys = ['v_payload', 'v_dt', 'v_created', 'v_username']
    r['n_fail'] = sum(r[k] == 'FAIL' for k in keys)
    r['overall'] = 'PASS' if r['n_fail'] == 0 else 'FAIL'
    # --- theo dõi (không tính vào kết quả) ---
    r['v_geo'] = 'PASS' if r['geo_pct'] is not None and r['geo_pct'] >= TH['geo'] else 'FAIL'
    r['v_ontime'] = 'PASS' if r['ot_pct'] > TH['ontime'] else 'FAIL'
    r['v_24'] = 'PASS' if (r['t24_pct'] or 0) > TH['ontime'] else 'FAIL'
    pf = int(p.plan_fail.sum()); allow = math.floor(TH['npp_plan_tol'] * np_)
    r['plan_fail'] = pf; r['plan_fail_pct'] = pct(pf, np_); r['plan_allow'] = allow
    r['v_plan'] = 'PASS' if pf <= allow else 'FAIL'
    fp = p[p.plan_fail]
    r['plan_drivers'] = {k: int((fp[c] > 0).sum()) for k, c in
                         [('Geo', 'e_geo'), ('D&T', 'e_dt'), ('Payload', 'e_pl'), ('Created Date', 'e_cd'), ('User', 'e_user')]}
    r['plan_sizes'] = [dict(label=l, plans=int(((p.orders >= a) & (p.orders <= b)).sum()),
                            fail=int(((fp.orders >= a) & (fp.orders <= b)).sum())) for a, b, l in
                       [(1, 1, '1 đơn'), (2, 3, '2–3 đơn'), (4, 6, '4–6 đơn'), (7, 10, '7–10 đơn'), (11, 9999, '11+ đơn')]]
    # tỷ lệ đơn lỗi (kịch bản tham khảo nếu dung sai 5% tính theo đơn)
    r['ord_err_pct'] = pct(int(d.any_err.sum()), n)
    # biên an toàn
    geo_need = math.ceil(TH['geo'] / 100 * gs); ot_need = math.floor(TH['ontime'] / 100 * n) + 1
    dt_allow = max(0, math.ceil(TH['dt_month_pct'] * dtn) - 1)
    pl_allow = math.ceil(TH['payload_tol'] * np_) - 1
    r['margin'] = dict(geo_ok=gs - gf, geo_need=geo_need, geo_margin=(gs - gf) - geo_need, geo_ci=wilson(gs - gf, gs),
                       ot_ok=n - otf, ot_need=ot_need, ot_margin=(n - otf) - ot_need, ot_ci=wilson(n - otf, n),
                       dt_allow=dt_allow, dt_margin=dt_allow - dtr, pl_allow=pl_allow, pl_margin=pl_allow - plf, cd_margin=-cdr,
                       plan_margin=r['plan_allow'] - r['plan_fail'])
    return r

scorecard = [score(m[m.TenantName == n], pl[pl.npp == n], n) for n in NPPS]
total = score(m, pl, 'TỔNG')

# ---------- thông tin NPP ----------
info = (m.dropna(subset=['DisCode']).groupby('TenantName')
        .agg(code=('DisCode', 'first'), name=('Distributor_Name', 'first'), area=('Area_Name', 'first'),
             region=('Region', 'first')))
npp_info = {n: dict(code=str(int(info.loc[n, 'code'])),
                    name=re.sub(r'^[A-Z0-9]+-', '', info.loc[n, 'name']),
                    area=info.loc[n, 'area'], region=info.loc[n, 'region']) for n in NPPS}
auth = {n: npp_info[n]['code'] for n in NPPS}

# ---------- theo ngày ----------
m['day'] = m.Date.dt.strftime('%d/%m')
def daily(d):
    out = []
    for day, g in d.groupby(d.Date.dt.normalize()):
        gs = g.geo_scope.sum()
        out.append(dict(day=day.strftime('%d/%m'), orders=len(g),
                        geo=pct(gs - g.f_geo.sum(), gs), ot=pct(len(g) - g.f_ot.sum(), len(g)), t24=pct(g.t24_scope.sum() - g.f_24.sum(), g.t24_scope.sum()),
                        dt=pct(len(g) - g.f_dt.sum(), len(g)), err=int(g.any_err.sum()),
                        plans=int(g.PlanNumber.nunique()), pfail=int(g[g.plan_fail].PlanNumber.nunique()),
                        pfail_pct=pct(g[g.plan_fail].PlanNumber.nunique(), g.PlanNumber.nunique()),
                        dtr=int(g[g.plan_dt_fail].PlanNumber.nunique()),
                        dtr_pct=pct(g[g.plan_dt_fail].PlanNumber.nunique(), g[g.dt_scope].PlanNumber.nunique()),
                        cd=int(g.f_cd.sum())))
    return out
daily_d = {'ALL': daily(m), **{n: daily(m[m.TenantName == n]) for n in NPPS}}

# ---------- phân bố lệch vị trí ----------
bins = [(-1, 50, '0–50m'), (50, 200, '50–200m'), (200, 1000, '200m–1km'), (1000, 5000, '1–5km'), (5000, 1e12, '>5km')]
def gdist(d):
    d = d[d.geo_scope]
    return [dict(label=l, n=int(((d.distance_to_dropped > a) & (d.distance_to_dropped <= b)).sum())) for a, b, l in bins]
geo_dist = {'ALL': gdist(m), **{n: gdist(m[m.TenantName == n]) for n in NPPS}}

# ---------- giờ giao ----------
def hours(d):
    h = d.DeliverDateTime.dt.hour.dropna().astype(int).value_counts()
    return [int(h.get(i, 0)) for i in range(24)]
hours_d = {'ALL': hours(m), **{n: hours(m[m.TenantName == n]) for n in NPPS}}

# ---------- theo tài khoản ----------
def users(d):
    rows = []
    for u, g in d.groupby('username'):
        gs = int(g.geo_scope.sum())
        rows.append(dict(username=u, npp=g.TenantName.iloc[0], utype=g.utype.iloc[0], orders=len(g),
                         plans=g.PlanNumber.nunique(), err=int(g.any_err.sum()), geo=int(g.f_geo.sum()), geo_scope=gs,
                         ot=int(g.f_ot.sum()), t24=int(g.f_24.sum()), dt=int(g.f_dt.sum()), pl=int(g.f_pl.sum()), cd=int(g.f_cd.sum()),
                         err_pct=pct(int(g.any_err.sum()), len(g)),
                         plan_fail=int(g[g.plan_fail].PlanNumber.nunique())))
    return sorted(rows, key=lambda r: -r['err'])
users_d = {'ALL': users(m)}

# ---------- danh sách đơn lỗi ----------
def fmt_dt(x): return '' if pd.isna(x) else x.strftime('%d/%m/%Y %H:%M:%S')
def why(r):
    lab, rs = [], []
    if r.f_user: lab.append('User'); rs.append(f'Tài khoản không hợp lệ: {r.username}')
    if r.f_geo:
        lab.append('Geo')
        if r.g_v: rs.append(f'Sai vị trí: lệch {r.distance_to_dropped:,.0f}m (ngưỡng {TH["geo_radius_m"]}m)')
        if r.g_w: rs.append(f'Outlet tới outlet {r.gap:.1f} phút (yêu cầu trên {TH["geo_gap_min"]} phút)')
        if r.g_x:
            rs.append('Ngoài giờ làm việc: thiếu thời điểm giao' if pd.isna(r.DeliverDateTime)
                      else f'Ngoài giờ làm việc: hoàn tất {r.DeliverDateTime:%H:%M} (chỉ tính 06:00–20:00)')
    if r.f_dt:
        lab.append('D&T')
        rs.append(f'Cách outlet trước {r.time_outlet_outlet:.0f} phút, xa {r.dist_oo:,.0f}m' + (' — chuyến hỏng D&T' if r.plan_dt_fail else ' — chuyến vẫn trong mức cho phép'))
    if r.f_pl: lab.append('Payload'); rs.append(f'Chuyến chở {r.plan_ratio:.2f} lần tải trọng (lỗi từ {TH["payload_ratio"]} lần)')
    if r.f_cd:
        h = -r.cd_gap_h
        rs.append(f'Đơn tạo sau khi giao {h/24:.1f} ngày' if h >= 24 else f'Đơn tạo sau khi giao {h:.1f} giờ')
        lab.append('Created Date')
    return ' + '.join(lab), '; '.join(rs)

def late_why(r):
    rs = []
    if r.f_ot:
        rs.append('On time: trễ ' + (f'{int(r.late_days)} ngày so với ngày hứa' if pd.notna(r.late_days) and r.late_days > 0 else
                                    ('chưa có giờ giao' if pd.isna(r.DeliverDateTime) else 'theo SLA của TMS')))
    if r.h24_fail:
        rs.append('24H: tạo sau khi giao' if r.h24_dur < 0 else f'24H: {r.h24_dur:.1f} giờ (quá {TH["sla_hours"]} giờ)')
    if r.wh_fail: rs.append(f'Giao sau {TH["wh_end"]}:00 (lúc {r.DeliverDateTime:%H:%M})')
    return '; '.join(rs)

LT = m[m.late].sort_values(['TenantName', 'Date', 'PlanNumber', 'seq'])
late_list = [dict(npp=r.TenantName, day=r.Date.strftime('%d/%m'), plan=r.PlanNumber, order=r.OrderNumber, user=r.username,
                  created=fmt_dt(r.Sent_To_distributor), delivered=fmt_dt(r.DeliverDateTime),
                  promised=r.PromisedDate.strftime('%d/%m') if pd.notna(r.PromisedDate) else '',
                  hours=None if pd.isna(r.h24_dur) else round(float(r.h24_dur), 1),
                  ot=bool(r.f_ot), h24=bool(r.h24_fail), wh=bool(r.wh_fail), why=late_why(r)) for r in LT.itertuples()]

E = m[m.any_err].copy()
lr = E.apply(why, axis=1)
E['loi'] = [a for a, b in lr]; E['ly_do'] = [b for a, b in lr]
ECOLS = ['Date', 'TenantName', 'PlanNumber', 'OrderNumber', 'OutletCode', 'username', 'utype', 'DriverName',
         'Status', 'Sent_To_distributor', 'DeliverDateTime', 'PromisedDate', 'distance_to_dropped', 'gap', 'seq',
         'plan_orders', 'plan_err', 'plan_err_ratio', 'plan_fail', 'plan_ratio', 'TruckCategory', 'TruckCapacityWeight', 'Assigned_Weight', 'h24_dur', 'loi', 'ly_do']
def cell(v):
    if isinstance(v, (pd.Timestamp, datetime)): return fmt_dt(v)
    if v is None or (isinstance(v, float) and np.isnan(v)): return None
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating, float)): return round(float(v), 2)
    if isinstance(v, (np.bool_, bool)): return bool(v)
    return v
E = E.sort_values(['TenantName', 'Date', 'PlanNumber', 'seq'])
errors = [[cell(v) for v in row] for row in E[ECOLS].itertuples(index=False)]

# ---------- top chuyến ----------
dt_top = pl[pl.dt_fail].sort_values('bad', ascending=False).reset_index()
dt_top = [dict(plan=r.PlanNumber, npp=r.npp, truck=r.truck, user=r.user, orders=int(r.dt_n), bad=int(r.bad),
               date=r.date.strftime('%d/%m')) for r in dt_top.itertuples()]
pl_top = pl[pl.pl_fail].sort_values('ratio', ascending=False).reset_index()
pl_top = [dict(plan=r.PlanNumber, npp=r.npp, truck=r.truck, orders=int(r.orders), weight=round(r.w, 2),
               cap=r.cap, ratio=r.ratio, date=r.date.strftime('%d/%m')) for r in pl_top.itertuples()]
fpl = pl[pl.plan_fail].sort_values(['npp', 'err_ratio'], ascending=[True, False]).reset_index()
def ptypes(r): return ', '.join(k for k, c in [('Geo', r.e_geo), ('D&T', r.e_dt), ('Payload', r.e_pl), ('Created Date', r.e_cd), ('User', r.e_user)] if c > 0)
plan_list = [dict(plan=r.PlanNumber, npp=r.npp, date=r.date.strftime('%d/%m'), user=r.user, orders=int(r.orders), err=int(r.err),
                  ratio=round(r.err_ratio * 100, 1), types=ptypes(r)) for r in fpl.itertuples()]
cd_rows = m[m.f_cd].sort_values('cd_gap_h')
cd_list = [dict(npp=r.TenantName, order=r.OrderNumber, user=r.username, plan=r.PlanNumber,
                created=fmt_dt(r.Sent_To_distributor), delivered=fmt_dt(r.DeliverDateTime),
                hours=round(-r.cd_gap_h, 1)) for r in cd_rows.itertuples()]

# ---------- chất lượng dữ liệu ----------
fr_only = sorted(set(f.DocNo) - set(t.OrderNumber))
tms_only = m[m.Sent_To_distributor.isna()]
dq = dict(rows_tms=n_file, rows_fr=len(f), dup_orders=dup,
          matched=int(m.Sent_To_distributor.notna().sum()),
          tms_unmatched=len(tms_only),
          tms_unmatched_rows=[dict(npp=r.TenantName, order=r.OrderNumber, status=r.Status) for r in tms_only.itertuples()],
          fr_unmatched=len(fr_only), fr_unmatched_list=fr_only[:20],
          status={k: int(v) for k, v in m.Status.value_counts().items()},
          null_deliver=int(m.DeliverDateTime.isna().sum()),
          deliver_before_period=int((m.DeliverDateTime < m.Date.min().normalize().replace(day=1)).sum()),
          deliver_after_period=int((m.DeliverDateTime >= (m.Date.max().normalize().replace(day=1) + pd.offsets.MonthBegin(1))).sum()),
          geo_out5k=int((m.distance_to_dropped > 5000).sum()), geo_max=round(float(m.distance_to_dropped.max()), 1),
          user_types={k: int(v) for k, v in m.utype.value_counts().items()},
          gap_col_null=int(m.time_outlet_outlet.isna().sum()),
          gap_match=round(float((abs(m.gap - m.time_outlet_outlet) < 1)[m.gap.notna() & m.time_outlet_outlet.notna()].mean() * 100), 2),
          plans_mixed_cap=int((pl.cap != pl.capmin).sum()),
          actual_dist_null=int(m.TMS_Actual_Distance.isna().sum()),
          cd_neg=int(m.f_cd.sum()), cd_neg_gt24=int((m.f_cd & (m.cd_gap_h < -24)).sum()))

# ---------- kịch bản độ nhạy ----------
def variant(payload_zero=False, track_gates=False, any_rule=False):
    out = {}
    for n in NPPS:
        x = next(s for s in scorecard if s['npp'] == n)
        ok = x['v_dt'] == 'PASS' and x['v_created'] == 'PASS' and x['v_username'] == 'PASS'
        ok = ok and (x['payload_plans_fail'] == 0 if payload_zero else x['v_payload'] == 'PASS')
        if track_gates: ok = ok and x['v_geo'] == 'PASS'
        if any_rule: ok = x['v_plan'] == 'PASS' and x['v_created'] == 'PASS'
        out[n] = 'PASS' if ok else 'FAIL'
    return out
sens = [dict(label='Đang áp dụng: 4 tiêu chí theo file chính thức, Payload dung sai < 5% chuyến', v=variant()),
        dict(label='Payload không cho phép chuyến nào quá tải (như file gốc)', v=variant(payload_zero=True)),
        dict(label='Thêm Geo ≥ 85% vào kết quả', v=variant(track_gates=True)),
        dict(label='Chuyến lỗi > 30% với bất kỳ KPI nào, dung sai 5% chuyến', v=variant(any_rule=True))]
for s in sens: s['pass'] = sum(v == 'PASS' for v in s['v'].values())

DATA = dict(
    meta=dict(period=f'{m.Date.min():%d/%m/%Y} – {m.Date.max():%d/%m/%Y}', orders=n_file, plans=len(pl),
              npps=len(NPPS), bu=m.BU.iloc[0], regions=sorted(m.Region.unique().tolist()),
              src='TMS_Order_Detail.xlsx + Fill_Rate.xlsx', built=(datetime.utcnow()+pd.Timedelta(hours=7)).strftime('%d/%m/%Y %H:%M'),
              days=int(m.Date.dt.normalize().nunique()), excluded=EXCL),
    thresholds=TH, npps=NPPS, npp_info=npp_info, auth=auth, scorecard=scorecard, total=total,
    err_keys=ECOLS, errors=errors, daily=daily_d, geo_dist=geo_dist, hours=hours_d, users=users_d,
    dt_top=dt_top, pl_top=pl_top, plan_list=plan_list, late_list=late_list, cd_list=cd_list, dq=dq, sens=sens)

OUT.parent.mkdir(parents=True, exist_ok=True)
json.dump(DATA, open(OUT, 'w'), ensure_ascii=False, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print(f"Kỳ {DATA['meta']['period']}: {sum(s['overall'] == 'PASS' for s in scorecard)}/{len(scorecard)} NPP đạt · "
      f"{n_file:,} đơn · {len(errors):,} đơn lỗi -> {OUT.name}")
