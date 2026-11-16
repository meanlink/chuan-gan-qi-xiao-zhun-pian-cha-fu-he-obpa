from pydantic import BaseModel, Field


class MonitorThresholdInput(BaseModel):
    threshold: float = Field(gt=0, le=10)


class MonitorCutoffInput(BaseModel):
    cutoff_date: str = Field(min_length=8, max_length=10)


class MonitorSettleInput(BaseModel):
    reason: str = Field(default='manual', max_length=80)
