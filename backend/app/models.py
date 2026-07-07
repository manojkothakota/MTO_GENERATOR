"""
Pydantic data models for the Material Take-Off (MTO) domain.

Field definitions follow the domain primer (Section 2.2 of the brief):
pipe is quantified by length (unit=M), all other categories by count
(unit=EA/NO), bolts by SET. Gaskets and bolt sets are usually derived
(one of each per flanged joint) rather than detected as symbols.
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    PIPE = "PIPE"
    FITTING = "FITTING"
    FLANGE = "FLANGE"
    VALVE = "VALVE"
    GASKET = "GASKET"
    BOLT = "BOLT"
    SUPPORT = "SUPPORT"


class Unit(str, Enum):
    M = "M"          # metres - pipe only
    EA = "EA"         # each - discrete items
    NO = "NO"         # count - discrete items (alt notation)
    SET = "SET"       # bolt sets


class MTOItem(BaseModel):
    item_no: int
    category: Category
    description: str
    size_nps: Optional[str] = Field(
        default=None, description='Nominal pipe size, e.g. 6" or 6"x4"'
    )
    schedule_rating: Optional[str] = Field(
        default=None, description="SCH 40 / CL150 etc."
    )
    material_spec: Optional[str] = Field(
        default=None, description="ASTM/ASME material grade"
    )
    end_type: Optional[str] = Field(
        default=None, description="BW / SW / THD / FLGD"
    )
    quantity: float = 1
    unit: Unit
    length_m: Optional[float] = Field(
        default=None, description="Total cut length, pipe only"
    )
    confidence: Optional[float] = Field(
        default=None, ge=0, le=1, description="Model confidence 0-1"
    )
    remarks: Optional[str] = ""

    @field_validator("length_m")
    @classmethod
    def length_only_for_pipe(cls, v, info):
        # Non-pipe rows should not carry a length value.
        if v is not None and info.data.get("category") not in (Category.PIPE, None):
            return None
        return v


class DrawingMeta(BaseModel):
    drawing_no: Optional[str] = None
    revision: Optional[str] = None
    line_number: Optional[str] = None
    nps: Optional[str] = None
    material_class: Optional[str] = None
    service: Optional[str] = None


class Summary(BaseModel):
    total_pipe_length_m: float = 0
    fittings: int = 0
    flanges: int = 0
    valves: int = 0
    gaskets: int = 0
    bolt_sets: int = 0
    field_welds: int = 0
    supports: int = 0


class MTOResult(BaseModel):
    drawing_meta: DrawingMeta
    items: List[MTOItem]
    summary: Summary
    mode: str = Field(description='"mock", "gemini", or "groq"')
    warnings: List[str] = Field(default_factory=list)


class JobStatus(str, Enum):
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class Job(BaseModel):
    job_id: str
    status: JobStatus
    filename: Optional[str] = None
    result: Optional[MTOResult] = None
    error: Optional[str] = None
