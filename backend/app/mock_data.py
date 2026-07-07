"""
Deterministic mock MTO so the app runs end-to-end with no API key.
Represents a plausible small 6" process line, matching the schema
example in the brief (Section 3.4).
"""
from app.models import (
    MTOResult, MTOItem, DrawingMeta, Summary, Category, Unit
)


def build_mock_mto(filename: str = "sample.png") -> MTOResult:
    items = [
        MTOItem(
            item_no=1, category=Category.PIPE,
            description="Pipe, Seamless, BE, ASME B36.10",
            size_nps='6"', schedule_rating="SCH 40",
            material_spec="ASTM A106 Gr.B", end_type="BW",
            quantity=1, unit=Unit.M, length_m=12.45, confidence=0.95,
        ),
        MTOItem(
            item_no=2, category=Category.FITTING,
            description="Elbow 90 Deg LR, BW, ASME B16.9",
            size_nps='6"', schedule_rating="SCH 40",
            material_spec="ASTM A234 WPB", end_type="BW",
            quantity=4, unit=Unit.EA, confidence=0.9,
        ),
        MTOItem(
            item_no=3, category=Category.FITTING,
            description="Tee, Equal, BW, ASME B16.9",
            size_nps='6"', schedule_rating="SCH 40",
            material_spec="ASTM A234 WPB", end_type="BW",
            quantity=1, unit=Unit.EA, confidence=0.85,
        ),
        MTOItem(
            item_no=4, category=Category.FLANGE,
            description="Flange, Weld Neck, CL150, ASME B16.5",
            size_nps='6"', schedule_rating="CL150",
            material_spec="ASTM A105", end_type="BW",
            quantity=2, unit=Unit.EA, confidence=0.88,
        ),
        MTOItem(
            item_no=5, category=Category.VALVE,
            description="Gate Valve, Flanged, CL150",
            size_nps='6"', schedule_rating="CL150",
            material_spec="ASTM A216 WCB", end_type="FLGD",
            quantity=1, unit=Unit.EA, confidence=0.8,
        ),
        MTOItem(
            item_no=6, category=Category.GASKET,
            description="Gasket, Spiral Wound, SS316/Graphite, ASME B16.20",
            size_nps='6"', schedule_rating="CL150",
            material_spec="SS316/Graphite", end_type="FLGD",
            quantity=2, unit=Unit.EA, confidence=None,
            remarks="Derived: 1 per flanged joint",
        ),
        MTOItem(
            item_no=7, category=Category.BOLT,
            description="Stud Bolt with 2 Nuts, ASTM A193 B7 / A194 2H",
            size_nps='6"', schedule_rating="CL150",
            material_spec="A193 B7 / A194 2H", end_type="FLGD",
            quantity=2, unit=Unit.SET, confidence=None,
            remarks="Derived: 1 set per flanged joint",
        ),
    ]
    summary = Summary(
        total_pipe_length_m=12.45,
        fittings=5,
        flanges=2,
        valves=1,
        gaskets=2,
        bolt_sets=2,
        field_welds=1,
        supports=0,
    )
    meta = DrawingMeta(
        drawing_no="ISO-1501-01",
        revision="2",
        line_number='6"-P-1501-A1A-IH',
        nps='6"',
        material_class="A1A",
        service="Process",
    )
    return MTOResult(
        drawing_meta=meta,
        items=items,
        summary=summary,
        mode="mock",
        warnings=[
            f"No AI provider configured (or extraction failed) — "
            f"showing a labelled mock MTO instead of real extraction for '{filename}'."
        ],
    )
