import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, MonitorSetting, MonitorWarning
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.services import monitor
from src.utils.security import hash_password
from src.utils.serialization import checksum


def monitoring_demo_records():
    """跨批次持续监测演示：三探头 × 多测量日，固定样本编号与偏差。"""
    days = ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04',
            '2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08']
    # P-101 连续 8 日超阈（持续失准，触发预警）；
    # P-102 仅 11/1–2、11/4–5 超阈且 11/3 缺日：最长连续段 2 日，缺日中断，永不预警；
    # P-103 始终正常。
    over_days = {
        'P-101': set(days),
        'P-102': {'2026-11-01', '2026-11-02', '2026-11-04', '2026-11-05'},
        'P-103': set(),
    }
    missing_days = {'P-101': set(), 'P-102': {'2026-11-03'}, 'P-103': set()}
    rows = []
    for probe in ('P-101', 'P-102', 'P-103'):
        for day in days:
            if day in missing_days[probe]:
                continue
            bias = 0.9 if day in over_days[probe] else 0.18
            for k in range(4):
                reference = 25.0 + k
                sample = f'MON-{probe}-{day}-{k + 1:02d}'
                rows.append({'sample': sample, 'probe': probe, 'measured_on': day,
                             'band': '常温', 'reference': reference,
                             'measured': round(reference + bias, 4)})
    return rows


def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        # 持续监测演示批次（自然键幂等，可重复执行）。
        mon_name='持续监测演示 · 三探头多日读数'
        mon_ds=db.scalar(select(Dataset).where(Dataset.name==mon_name))
        if not mon_ds:
            mon_rows=monitoring_demo_records()
            mon_ds=Dataset(name=mon_name,source='monitor-202611.csv',records=mon_rows,
                           checksum=checksum(mon_rows),created_at=time.time())
            db.add(mon_ds); db.flush()
            monitor.ingest_dataset_readings(db, mon_ds.id, mon_rows)
            s=monitor.get_settings(db)
            if not s.cutoff_date:
                s.threshold=monitor.DEFAULT_THRESHOLD
                s.cutoff_date='2026-11-08'
            monitor.settle(db, actor='seed', reason='demo-seed')
            db.add(Audit(actor='seed', action='demo.monitoring',
                         detail={'dataset': mon_ds.id, 'cutoff': '2026-11-08'}, at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit,MonitorWarning]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
