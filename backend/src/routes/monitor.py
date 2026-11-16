from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from src.config.database import get_db
from src.models import MonitorWarning, MonitorNotice
from src.middlewares.auth import current_user, admin_only
from src.schemas.monitor import MonitorThresholdInput, MonitorCutoffInput, MonitorSettleInput
from src.services import monitor
from src.services.audit import record

router = APIRouter(prefix='/monitor')


@router.get('/settings')
def settings(db=Depends(get_db), u=Depends(current_user)):
    return monitor.setting_dict(monitor.get_settings(db))


@router.put('/settings/threshold')
def set_threshold(data: MonitorThresholdInput, db=Depends(get_db), u=Depends(admin_only)):
    s = monitor.update_settings(db, threshold=data.threshold)
    record(db, u.email, 'monitor.threshold', {'threshold': s.threshold})
    db.commit()
    return monitor.setting_dict(s)


@router.put('/settings/cutoff')
def advance_cutoff(data: MonitorCutoffInput, db=Depends(get_db), u=Depends(admin_only)):
    s = monitor.update_settings(db, cutoff_date=data.cutoff_date)
    record(db, u.email, 'monitor.cutoff', {'cutoff_date': s.cutoff_date})
    # 截止日推进后立即结算，页面马上得到新结论；失败可由 worker 兜底重算。
    result = monitor.settle(db, actor=u.email, reason='cutoff-advanced')
    db.commit()
    return {**monitor.setting_dict(s), 'settlement': result}


@router.post('/settle')
def resettle(data: MonitorSettleInput, db=Depends(get_db), u=Depends(admin_only)):
    result = monitor.settle(db, actor=u.email, reason=data.reason)
    db.commit()
    return result


@router.get('/daily')
def daily(probe: str | None = None, db=Depends(get_db), u=Depends(current_user)):
    series = monitor.daily_series(db, probe.strip() if probe else None)
    return [{'probe': p, 'days': days} for p, days in sorted(series.items())]


@router.get('/warnings')
def warnings(probe: str | None = None, db=Depends(get_db), u=Depends(current_user)):
    stmt = select(MonitorWarning).order_by(MonitorWarning.probe, MonitorWarning.id)
    items = db.scalars(stmt)
    if probe:
        items = [w for w in items if w.probe == probe.strip()]
    return [monitor.warning_dict(w) for w in items]


@router.get('/warnings/{id}')
def warning_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    w = db.get(MonitorWarning, id)
    if not w:
        raise HTTPException(404, '预警不存在')
    notices = db.scalars(select(MonitorNotice)
                         .where(MonitorNotice.warning_id == id)
                         .order_by(MonitorNotice.version, MonitorNotice.id))
    return {**monitor.warning_dict(w),
            'notices': [monitor.notice_dict(n) for n in notices]}


@router.get('/notices')
def notices(db=Depends(get_db), u=Depends(current_user)):
    # 收件箱按探头、预警链与版本依次呈现，天然满足并发下旧结论不覆盖新结论。
    rows = db.scalars(select(MonitorNotice)
                      .order_by(MonitorNotice.probe, MonitorNotice.warning_id,
                                MonitorNotice.version, MonitorNotice.id))
    return [monitor.notice_dict(n) for n in rows]
