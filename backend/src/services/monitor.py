"""探头持续偏差监测引擎。

业务规则：
- 按探头 + 测量日聚合日均残差（残差=探头值−标准值），日均残差绝对值超阈且连续三个
  日历日才发预警；缺日（日历不连续）或任一日未超阈都会中断连续性。
- 仅结算测量日 <= 实验室确认截止日（cutoff_date）的读数；迟到记录回填已结算日后，
  置脏并由下次结算重算后续连续状态。
- 原预警记录保留：连续段变化发“更正”，不再满足条件发“撤销”。
- 通知带单调版本号与幂等键：进程中断可重试且不重复通知，旧计算晚到不覆盖新结论。
"""
import time
from datetime import date as date_cls

from fastapi import HTTPException
from sqlalchemy import select, func

from src.models import Reading, MonitorSetting, MonitorWarning, MonitorNotice
from src.services.audit import record

DEFAULT_THRESHOLD = 0.5
CONSECUTIVE_DAYS = 3
SETTING_ID = 1


def get_settings(db):
    s = db.get(MonitorSetting, SETTING_ID)
    if s is None:
        s = MonitorSetting(id=SETTING_ID, threshold=DEFAULT_THRESHOLD,
                           cutoff_date='', dirty=True, lock_version=0,
                           updated_at=time.time())
        db.add(s)
        db.flush()
    return s


def validate_iso_date(value, field):
    try:
        date_cls.fromisoformat(value)
        return value
    except (ValueError, TypeError):
        raise HTTPException(422, f'{field} 须为 YYYY-MM-DD 格式的有效日期')


def parse_monitor_fields(row, index):
    """探头编号与测量日为可选扩展字段。

    同时缺失：旧批次，不纳入持续监测；只给其一：口径不完整，整批拒绝。
    """
    probe = row.get('probe')
    measured_on = row.get('measured_on')
    probe_blank = probe is None or str(probe).strip() == ''
    date_blank = measured_on is None or str(measured_on).strip() == ''
    if probe_blank and date_blank:
        return None
    if probe_blank or date_blank:
        raise HTTPException(422, f'第 {index + 1} 行探头编号与测量日必须同时提供，或同时留空（旧批次不纳入监测）')
    return str(probe).strip(), validate_iso_date(str(measured_on).strip(), '测量日')


def ingest_dataset_readings(db, dataset_id, rows):
    """把批次中带探头/测量日的记录汇入跨批次读数池。

    - 跨批同号同值：视为重复补传，不重复累加；
    - 同号异值（含同批内）：整批拒绝，由外层事务回滚；
    - 旧批次缺探头或日期：跳过，不纳入监测。
    返回纳入监测的新增读数条数。
    """
    monitor_rows = []
    for i, row in enumerate(rows):
        meta = parse_monitor_fields(row, i)
        if meta is None:
            continue
        probe, measured_on = meta
        monitor_rows.append((i, str(row['sample']), probe, measured_on,
                             float(row['reference']), float(row['measured']),
                             str(row.get('band', ''))))
    if not monitor_rows:
        return 0
    samples = [r[1] for r in monitor_rows]
    if len(samples) != len(set(samples)):
        dup = next(s for s in samples if samples.count(s) > 1)
        raise HTTPException(422, f'读数编号 {dup} 在本批次内重复，整批已拒绝')
    existing = {r.sample: r for r in db.scalars(select(Reading).where(Reading.sample.in_(samples)))}
    seen = {}
    added = 0
    now = time.time()
    for _, sample, probe, measured_on, ref, measured, band in monitor_rows:
        signature = (round(ref, 8), round(measured, 8))
        prior = existing.get(sample) or seen.get(sample)
        if prior is not None:
            if (round(prior.reference, 8), round(prior.measured, 8)) != signature:
                raise HTTPException(422, f'读数编号 {sample} 同号异值，整批已拒绝（跨批次读数不允许覆盖）')
            continue  # 同号同值：重复补传不累加
        reading = Reading(sample=sample, probe=probe, measured_on=measured_on, band=band,
                          reference=ref, measured=measured, residual=measured - ref,
                          dataset_id=dataset_id, created_at=now)
        db.add(reading)
        seen[sample] = reading
        added += 1
    if added:
        get_settings(db).dirty = True
    return added


def update_settings(db, threshold=None, cutoff_date=None):
    s = get_settings(db)
    if threshold is not None:
        if not (isinstance(threshold, (int, float)) and threshold > 0 and threshold <= 10):
            raise HTTPException(422, '阈值须为 0–10°C 之间的正数')
        s.threshold = float(threshold)
    if cutoff_date is not None:
        validate_iso_date(cutoff_date, '结算截止日')
        if s.cutoff_date and cutoff_date < s.cutoff_date:
            raise HTTPException(422, f'截止日只能向前推进，当前截止日为 {s.cutoff_date}')
        s.cutoff_date = cutoff_date
    s.dirty = True
    s.updated_at = time.time()
    return s


def daily_series(db, probe=None):
    """按探头、测量日返回已结算窗口内的日均残差序列（日期升序）。

    口径：先对当日残差取均值，再取绝对值（日均残差绝对值 = |日均残差|）。
    """
    s = get_settings(db)
    stmt = select(Reading.probe, Reading.measured_on,
                  func.avg(Reading.residual), func.count(Reading.id))
    if s.cutoff_date:
        stmt = stmt.where(Reading.measured_on <= s.cutoff_date)
    if probe:
        stmt = stmt.where(Reading.probe == probe)
    stmt = stmt.group_by(Reading.probe, Reading.measured_on)
    series = {}
    for p, measured_on, mean_res, n in db.execute(stmt):
        mean_residual = round(float(mean_res), 6)
        series.setdefault(p, []).append({
            'probe': p, 'measured_on': measured_on, 'n': n,
            'mean_residual': mean_residual,
            'abs_mean_residual': abs(mean_residual),
            'over_threshold': abs(mean_residual) > s.threshold,
        })
    for days in series.values():
        days.sort(key=lambda d: d['measured_on'])
    return series


def evaluate_streak(days, threshold):
    """返回窗口内最近一段长度 >=3 的超阈连续日历日段；不存在则 None。

    缺日（日历间隔 > 1 天）中断连续性；未超阈日同样中断。
    历史上已成立的连续段不会因之后恢复正常而消失——只有重算（迟到回填或阈值
    调整）使窗口内不再存在任何合格连续段时，预警才会被撤销。
    """
    run, last_cal, best = [], None, None
    for d in days:
        cal = date_cls.fromisoformat(d['measured_on'])
        if d['abs_mean_residual'] > threshold:
            if last_cal is not None and (cal - last_cal).days == 1:
                run.append(d)
            else:
                run = [d]  # 缺日或重新起算
            last_cal = cal
            if len(run) >= CONSECUTIVE_DAYS:
                best = list(run)  # 持续更新，最终保留最近的合格连续段
        else:
            run, last_cal = [], None
    return best


def _notice_title(kind, probe, w):
    if kind == 'issue':
        return f'预警：探头 {probe} 连续 {w.streak_days} 日日均残差超阈'
    if kind == 'correction':
        return f'更正：探头 {probe} 连续失准依据已更新（第 {w.seq} 版）'
    return f'撤销：探头 {probe} 原连续失准预警不再成立（第 {w.seq} 版）'


def _notice_body(kind, w):
    span = f'{w.streak_start} 至 {w.streak_end}（{w.streak_days} 个连续日历日）'
    if kind == 'issue':
        return f'探头 {w.probe} 在 {span} 日均残差绝对值超过 {w.threshold}°C，触发持续失准预警。'
    if kind == 'correction':
        return f'迟到回填或参数调整后重算：探头 {w.probe} 当前连续超阈段为 {span}，原预警保留，以此版结论为准。'
    return f'截至结算截止日 {w.cutoff_date}，探头 {w.probe} 已不满足连续三日超阈条件，原预警保留并撤销。'


def emit_notice(db, w, kind):
    """追加版本化通知。delivery_key 唯一：中断重试不会产生重复通知。"""
    key = f'w{w.id}-v{w.seq}-{kind}'
    if db.scalar(select(MonitorNotice).where(MonitorNotice.delivery_key == key)):
        return None
    notice = MonitorNotice(warning_id=w.id, probe=w.probe, kind=kind, version=w.seq,
                           title=_notice_title(kind, w.probe, w), body=_notice_body(kind, w),
                           evidence=w.evidence, cutoff_date=w.cutoff_date,
                           delivery_key=key, created_at=time.time())
    db.add(notice)
    db.flush()
    return notice


def settle(db, actor='worker', reason='tick'):
    """按当前阈值与截止日重算全部探头的连续状态，幂等且可中断恢复。"""
    s = db.scalar(select(MonitorSetting)
                  .where(MonitorSetting.id == SETTING_ID).with_for_update())
    if s is None:  # 极端情况下首次由结算创建单例
        s = get_settings(db)
    s.lock_version += 1
    run_version = s.lock_version
    s.dirty = False
    s.updated_at = time.time()
    cutoff, threshold, now = s.cutoff_date, s.threshold, time.time()

    series = daily_series(db) if cutoff else {}
    active = {w.probe: w for w in db.scalars(
        select(MonitorWarning).where(MonitorWarning.status == 'active'))}
    for probe in sorted(set(active) | set(series)):
        days = series.get(probe, [])
        streak = evaluate_streak(days, threshold)
        w = active.get(probe)
        if streak:
            evidence = [{
                'measured_on': d['measured_on'], 'n': d['n'],
                'mean_residual': d['mean_residual'],
                'abs_mean_residual': d['abs_mean_residual'],
                'threshold': threshold, 'over_threshold': True,
            } for d in streak]
            start, end = streak[0]['measured_on'], streak[-1]['measured_on']
            max_abs = max(d['abs_mean_residual'] for d in streak)
            if w is None:
                w = MonitorWarning(probe=probe, status='active', streak_start=start,
                                   streak_end=end, streak_days=len(streak),
                                   max_abs_mean=max_abs, threshold=threshold,
                                   evidence=evidence, seq=1, cutoff_date=cutoff,
                                   created_at=now, updated_at=now)
                db.add(w)
                db.flush()
                emit_notice(db, w, 'issue')
                continue
            changed = (w.streak_start != start or w.streak_end != end
                       or w.streak_days != len(streak) or w.threshold != threshold
                       or w.evidence != evidence)
            if changed:  # 迟到回填/阈值调整导致连续段变化：更正而非覆盖
                w.seq += 1
                w.streak_start, w.streak_end = start, end
                w.streak_days, w.max_abs_mean = len(streak), max_abs
                w.threshold, w.evidence = threshold, evidence
                w.cutoff_date, w.updated_at = cutoff, now
                db.flush()
                emit_notice(db, w, 'correction')
            else:  # 结论不变：仅同步结算截止日，不重复通知
                w.cutoff_date, w.updated_at = cutoff, now
        elif w is not None:  # 原预警保留，发布撤销
            w.status = 'withdrawn'
            w.seq += 1
            w.cutoff_date, w.updated_at = cutoff, now
            db.flush()
            emit_notice(db, w, 'withdrawal')
    record(db, actor, 'monitor.settled',
           {'version': run_version, 'cutoff': cutoff, 'threshold': threshold, 'reason': reason})
    return {'version': run_version, 'cutoff_date': cutoff, 'threshold': threshold}


# ---------- 序列化 ----------

def setting_dict(s):
    return {'threshold': s.threshold, 'cutoff_date': s.cutoff_date, 'dirty': s.dirty,
            'lock_version': s.lock_version, 'updated_at': s.updated_at,
            'consecutive_days': CONSECUTIVE_DAYS}


def warning_dict(w):
    return {'id': w.id, 'probe': w.probe, 'status': w.status, 'streak_start': w.streak_start,
            'streak_end': w.streak_end, 'streak_days': w.streak_days,
            'max_abs_mean': w.max_abs_mean, 'threshold': w.threshold, 'seq': w.seq,
            'cutoff_date': w.cutoff_date, 'evidence': w.evidence,
            'created_at': w.created_at, 'updated_at': w.updated_at}


def notice_dict(n):
    return {'id': n.id, 'warning_id': n.warning_id, 'probe': n.probe, 'kind': n.kind,
            'version': n.version, 'title': n.title, 'body': n.body, 'evidence': n.evidence,
            'cutoff_date': n.cutoff_date, 'created_at': n.created_at}
