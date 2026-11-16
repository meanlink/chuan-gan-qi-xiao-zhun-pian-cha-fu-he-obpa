from sqlalchemy import String, Text, Double, Integer, Boolean, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Reading(Base):
    """跨批次汇聚后的探头读数。sample 为全局自然键：同号同值不重复累加，同号异值拒绝。"""
    __tablename__ = 'monitor_readings'
    __table_args__ = (UniqueConstraint('sample', name='uq_monitor_reading_sample'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sample: Mapped[str] = mapped_column(String(120))
    probe: Mapped[str] = mapped_column(String(80), index=True)
    measured_on: Mapped[str] = mapped_column(String(10), index=True)  # ISO 日期 YYYY-MM-DD
    band: Mapped[str] = mapped_column(String(40), default='')
    reference: Mapped[float] = mapped_column(Double)
    measured: Mapped[float] = mapped_column(Double)
    residual: Mapped[float] = mapped_column(Double)  # 探头值 − 标准值
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    created_at: Mapped[float] = mapped_column(Double)


class MonitorSetting(Base):
    """监测配置单例：阈值、实验室确认的结算截止日与重算脏标记。"""
    __tablename__ = 'monitor_settings'
    id: Mapped[int] = mapped_column(primary_key=True)
    threshold: Mapped[float] = mapped_column(Double, default=0.5)
    cutoff_date: Mapped[str] = mapped_column(String(10), default='')  # 实验室确认的结算截止日
    dirty: Mapped[bool] = mapped_column(Boolean, default=True)
    lock_version: Mapped[int] = mapped_column(Integer, default=0)  # 结算串行化版本
    updated_at: Mapped[float] = mapped_column(Double, default=0.0)


class MonitorWarning(Base):
    """按探头的连续失准预警。原预警保留，状态可被更正或撤销。"""
    __tablename__ = 'monitor_warnings'
    id: Mapped[int] = mapped_column(primary_key=True)
    probe: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default='active')  # active / withdrawn
    streak_start: Mapped[str] = mapped_column(String(10))   # 连续超阈首日
    streak_end: Mapped[str] = mapped_column(String(10))     # 最近一个超阈日
    streak_days: Mapped[int] = mapped_column(Integer, default=0)
    max_abs_mean: Mapped[float] = mapped_column(Double, default=0.0)
    threshold: Mapped[float] = mapped_column(Double)        # 触发时阈值快照
    evidence: Mapped[list] = mapped_column(JSON)  # 逐日日均残差依据
    seq: Mapped[int] = mapped_column(Integer, default=1)    # 同一预警链的结论版本
    cutoff_date: Mapped[str] = mapped_column(String(10), default='')
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)


class MonitorNotice(Base):
    """预警通知（发预警/更正/撤销），版本号递增；旧计算晚到不覆盖新结论。"""
    __tablename__ = 'monitor_notices'
    id: Mapped[int] = mapped_column(primary_key=True)
    warning_id: Mapped[int] = mapped_column(ForeignKey('monitor_warnings.id'), index=True)
    probe: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # issue / correction / withdrawal
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    cutoff_date: Mapped[str] = mapped_column(String(10), default='')
    delivery_key: Mapped[str] = mapped_column(String(160), unique=True)  # 幂等键，重试不重复通知
    created_at: Mapped[float] = mapped_column(Double)
