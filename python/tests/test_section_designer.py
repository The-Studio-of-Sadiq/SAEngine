"""Section Designer (saengine.library.section_designer): properties against hand formulas, RC
capacity against design/rc.py and a hand strain-compatibility point, φ from the pack, files."""

from __future__ import annotations

import itertools
import json
import math
from types import SimpleNamespace

import pytest

from saengine.design import rc
from saengine.library import objects as o
from saengine.library import section_designer as sd
from saengine.library.materials import Material, MaterialLibrary

C30 = Material.model_validate(
    {
        "id": "C30",
        "name": "C30",
        "category": "concrete",
        "mechanical": {"E": 25_700},
        "concrete": {"fc": 30},
    }
)
B420 = Material.model_validate(
    {
        "id": "B420",
        "name": "B420",
        "category": "rebar",
        "mechanical": {"E": 200_000},
        "steel": {"fy": 420},
    }
)
A36 = Material.model_validate(
    {
        "id": "A36",
        "name": "A36",
        "category": "steel",
        "mechanical": {"E": 200_000, "nu": 0.3},
        "steel": {"fy": 250},
    }
)
MATERIALS = MaterialLibrary(materials=[C30, B420, A36])


def rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def section(outline, holes=(), material="C30", bars=(), **kw) -> sd.DesignedSection:
    return sd.DesignedSection(
        id=kw.pop("id", "S1"),
        name=kw.pop("name", "test"),
        regions=[sd.Region(outline=outline, holes=list(holes), material=material)],
        bars=[sd.Bar(x=x, y=y, dia=d) for x, y, d in bars],
        rebar="B420" if bars else None,
        **kw,
    )


def composite(parts: list[tuple[float, float, float, float]]):
    """Area, centroid and centroidal Ixx, Iyy, Ixy of rectangles (x0, y0, x1, y1) by hand."""
    a = [(x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in parts]
    xc = [(x0 + x1) / 2 for x0, _, x1, _ in parts]
    yc = [(y0 + y1) / 2 for _, y0, _, y1 in parts]
    area = sum(a)
    cx = sum(ai * x for ai, x in zip(a, xc, strict=True)) / area
    cy = sum(ai * y for ai, y in zip(a, yc, strict=True)) / area
    ixx = iyy = ixy = 0.0
    for (x0, y0, x1, y1), ai, x, y in zip(parts, a, xc, yc, strict=True):
        b, h = x1 - x0, y1 - y0
        ixx += b * h**3 / 12 + ai * (y - cy) ** 2
        iyy += h * b**3 / 12 + ai * (x - cx) ** 2
        ixy += ai * (x - cx) * (y - cy)
    return area, cx, cy, ixx, iyy, ixy


# ─────────────────────────────────────── properties ───────────────────────────────────────


def test_l_section_properties_match_hand_formulas() -> None:
    # 600 x 400 L column, legs 250 thick: a 600 x 250 foot and a 250 x 150 upstand.
    outline = [(0, 0), (600, 0), (600, 250), (250, 250), (250, 400), (0, 400)]
    props = sd.properties(section(outline), MATERIALS)
    area, cx, cy, ixx, iyy, ixy = composite([(0, 0, 600, 250), (0, 250, 250, 400)])
    assert props.area == pytest.approx(area, rel=1e-9)
    assert (props.cx, props.cy) == pytest.approx((cx, cy), rel=1e-9)
    assert props.ixx == pytest.approx(ixx, rel=1e-9)
    assert props.iyy == pytest.approx(iyy, rel=1e-9)
    assert props.ixy == pytest.approx(ixy, rel=1e-9)
    # Principal moments from Mohr's circle.
    mean, radius = (ixx + iyy) / 2, math.hypot((ixx - iyy) / 2, ixy)
    assert (props.i11, props.i22) == pytest.approx((mean + radius, mean - radius), rel=1e-9)
    # Elastic moduli to the extreme fibres, plastic modulus about x (equal-area axis at y = 600
    # x yp = 237500 / 2 ... inside the foot: 600 yp = A / 2).
    assert props.sxTop == pytest.approx(ixx / (400 - cy), rel=1e-9)
    assert props.sxBottom == pytest.approx(ixx / cy, rel=1e-9)
    yp = area / 2 / 600
    zx = 600 * yp**2 / 2 + 600 * (250 - yp) ** 2 / 2 + 250 * 150 * (325 - yp)
    assert props.zx == pytest.approx(zx, rel=1e-6)
    # J of two thick rectangles, roughly Σ b t³ / 3 less the end effects: within 15 %.
    j_hand = sum(b * t**3 / 3 * (1 - 0.63 * t / b) for b, t in ((600, 250), (400, 250)))
    assert props.j == pytest.approx(j_hand, rel=0.15)
    assert props.massPerLength == pytest.approx(area * 1e-6 * 2400)


def test_box_section_properties_match_hand_formulas() -> None:
    b, h, t = 300.0, 500.0, 12.0
    box = section(rect(0, 0, b, h), holes=[rect(t, t, b - t, h - t)], material="A36")
    props = sd.properties(box, MATERIALS)
    bi, hi = b - 2 * t, h - 2 * t
    assert props.area == pytest.approx(b * h - bi * hi, rel=1e-9)
    assert props.ixx == pytest.approx((b * h**3 - bi * hi**3) / 12, rel=1e-9)
    assert props.iyy == pytest.approx((h * b**3 - hi * bi**3) / 12, rel=1e-9)
    assert (props.cx, props.cy) == pytest.approx((b / 2, h / 2))
    assert (props.scx, props.scy) == pytest.approx((b / 2, h / 2), abs=0.5)
    # Bredt: J = 4 Am² t / perimeter of the mid-line.
    am = (b - t) * (h - t)
    assert props.j == pytest.approx(4 * am**2 * t / (2 * (b - t + h - t)), rel=0.02)

    # Shear areas: Cowper's coefficients for thin-walled boxes (J. Appl. Mech. 1966), ν = 0.3.
    def cowper(m: float, n: float, nu: float = 0.3) -> float:
        top = 10 * (1 + nu) * (1 + 3 * m) ** 2
        bottom = (12 + 72 * m + 150 * m**2 + 90 * m**3) + nu * (
            11 + 66 * m + 135 * m**2 + 90 * m**3
        )
        return top / (bottom + 10 * n**2 * ((3 + nu) * m + 3 * m**2))

    assert props.asy == pytest.approx(cowper(b / h, b / h) * props.area, rel=0.05)
    # Along the short walls the flanges dominate, where Cowper's averaged warping and
    # sectionproperties' energy-based shear area differ most (6 % here).
    assert props.asx == pytest.approx(cowper(h / b, h / b) * props.area, rel=0.08)
    # Plastic modulus about x.
    assert props.zx == pytest.approx(b * h**2 / 4 - bi * hi**2 / 4, rel=1e-6)
    assert props.E == 200_000 and props.G == pytest.approx(200_000 / 2.6)


def test_composite_properties_are_transformed_to_the_first_material() -> None:
    # A 400 x 400 concrete column with an embedded... rather: a steel plate beside concrete.
    s = sd.DesignedSection(
        id="CMP",
        name="composite",
        regions=[
            sd.Region(outline=rect(0, 0, 400, 400), material="C30"),
            sd.Region(outline=rect(400, 0, 420, 400), material="A36"),
        ],
    )
    props = sd.properties(s, MATERIALS)
    n = 200_000 / 25_700
    assert props.area == pytest.approx(400 * 400 + n * 20 * 400, rel=1e-9)
    assert props.zx is None and props.referenceMaterial == "C30"


def test_properties_are_cached() -> None:
    s = section(rect(0, 0, 300, 300))
    assert sd.properties(s, MATERIALS) is sd.properties(s.model_copy(), MATERIALS)


def test_thin_walls_get_a_fine_mesh() -> None:
    core = section(rect(0, 0, 6000, 6000), holes=[rect(250, 250, 5750, 5750)])
    assert sd.mesh_size(core) <= 125**2


# ─────────────────────────────────────── validation ───────────────────────────────────────


@pytest.mark.parametrize(
    "build, message",
    [
        (lambda: section([(0, 0), (100, 100), (100, 0), (0, 100)]), "crosses itself"),
        (lambda: section(rect(0, 0, 300, 300), bars=[(10, 10, 25)]), "not inside"),
        (lambda: section(rect(0, 0, 300, 300), holes=[rect(100, 100, 400, 200)]), "crosses"),
        (
            lambda: sd.DesignedSection(
                id="X",
                name="x",
                regions=[
                    sd.Region(outline=rect(0, 0, 300, 300), material="C30"),
                    sd.Region(outline=rect(200, 0, 500, 300), material="C30"),
                ],
            ),
            "overlaps",
        ),
    ],
)
def test_invalid_sections_are_refused(build, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build()


def test_analyse_reports_problems_and_results() -> None:
    bad = json.dumps(
        {"id": "B", "name": "b", "regions": [{"outline": [[0, 0]], "material": "C30"}]}
    )
    assert sd.analyse(bad, MATERIALS.model_dump_json(by_alias=True))["problems"]
    steel = section(rect(0, 0, 200, 10), material="A36")
    result = sd.analyse(
        steel.model_dump_json(by_alias=True), MATERIALS.model_dump_json(by_alias=True)
    )
    assert result["problems"] == [] and result["properties"]["area"] == pytest.approx(2000)
    assert "concrete" in result["capacityNote"]


# ─────────────────────────────────────── RC capacity ───────────────────────────────────────


def rc_rectangle() -> tuple[rc.RcSection, sd.DesignedSection]:
    profile = o.RectangleProfile(xDim=400, yDim=600)
    reinforcement = o.LinearReinforcement(
        material="B420",
        cover=40,
        longitudinal=[o.BarGroup(position="perimeter", count=10, dia=20)],
        transverse=o.Transverse(type="tie", dia=10, spacing=150),
    )
    reference = rc.section_of(profile, reinforcement, 30, 420)
    designed = section(
        rect(-200, -300, 200, 300), bars=[(b.x, b.y, b.dia) for b in reference.bars], id="R"
    )
    return reference, designed


def test_rectangular_column_matches_design_rc() -> None:
    reference, designed = rc_rectangle()
    ref = rc.InteractionSurface(reference, coarse=True)
    mine = sd.design_surface(designed, MATERIALS, coarse=True)
    assert mine.symmetric
    assert mine.section.phi_pn_max == pytest.approx(reference.phi_pn_max, rel=1e-9)
    assert mine.section.phi_tension == pytest.approx(reference.phi_tension, rel=1e-9)
    for pu in (-400e3, 0.0, 1500e3, 3000e3):
        for angle in (0.0, 0.6, math.pi / 2):
            expected = ref.moment_capacity(pu, angle)
            assert mine.moment_capacity(pu, angle) == pytest.approx(expected, rel=0.01)
    check = mine.check(2000e3, 150e6, 80e6)
    assert check.utilisation == pytest.approx(ref.check(2000e3, 150e6, 80e6).utilisation, rel=0.01)


def test_uniaxial_diagram_points_match_design_rc() -> None:
    reference, designed = rc_rectangle()
    rcs = sd.DesignedRcSection(designed, MATERIALS)
    diagram = rcs.uniaxial("x", count=40)
    # Pure bending: interpolate the positive branch at P = 0 against rc.flexure.
    points = [p for p in diagram["points"] if p["M"] >= 0]
    for a, b in itertools.pairwise(points):
        if a["P"] <= 0 <= b["P"]:
            t = -a["P"] / (b["P"] - a["P"])
            mn = a["M"] + t * (b["M"] - a["M"])
            break
    assert mn == pytest.approx(rc.flexure(reference, hogging=False).mn, rel=0.02)
    # Uniform compression: P0 (φ capped at φPn,max on the factored curve).
    assert max(p["P"] for p in diagram["points"]) == pytest.approx(
        0.85 * 30 * (400 * 600 - reference.steel_area) + 420 * reference.steel_area, rel=1e-6
    )
    assert max(p["phiP"] for p in diagram["points"]) == pytest.approx(reference.phi_pn_max)


def test_t_wall_point_matches_hand_strain_compatibility() -> None:
    # A T-shaped wall: flange 2000 x 200 on top, web 200 x 1800 below; bars 20 mm.
    outline = [
        (-1000, 0), (1000, 0), (1000, -200), (100, -200), (100, -2000), (-100, -2000),
        (-100, -200), (-1000, -200),
    ]  # fmt: skip
    bars = [(x, -100, 20) for x in (-900, -500, 0, 500, 900)]
    bars += [(-50, y, 20) for y in (-600, -1200, -1900)] + [
        (50, y, 20) for y in (-600, -1200, -1900)
    ]
    wall = section(outline, bars=bars, id="TW")
    rcs = sd.DesignedRcSection(wall, MATERIALS)
    c = 150.0
    row = rcs.point(0.0, c)  # neutral axis horizontal, flange in compression

    # Hand: rectangular block 0.85 f'c over a = β1 c inside the flange; bars elastic-plastic,
    # bars inside the block displace its concrete.
    fc, fy, es, eps_cu = 30.0, 420.0, 200_000.0, 0.003
    a = rc.beta1(fc) * c
    area_bar = math.pi * 20**2 / 4
    cy = rcs.centroid[1]
    forces = [(0.85 * fc * 2000 * a, -a / 2)]
    for x, y, _ in bars:
        depth = -y
        strain = eps_cu * (c - depth) / c
        stress = max(-fy, min(fy, es * strain))
        displaced = 0.85 * fc if depth < a else 0.0
        forces.append((area_bar * (stress - displaced), y))
    p = sum(f for f, _ in forces)
    mx = sum(f * (y - cy) for f, y in forces)
    assert row["P"] == pytest.approx(p, rel=0.01)
    assert row["Mx"] == pytest.approx(mx, rel=0.01)
    # εt at the deepest bar (1900 mm): tension-controlled, φ = the pack's tension φ.
    assert row["epsT"] == pytest.approx(eps_cu * (1900 - c) / c, rel=1e-6)
    assert row["phi"] == pytest.approx(0.90)
    assert not rcs.symmetric


def _pack(tension: float, tied: float, spiral: float):
    phi = {"tension": tension, "compressionTied": tied, "compressionSpiral": spiral}
    return SimpleNamespace(table=lambda name: SimpleNamespace(phi=phi))


def test_phi_comes_from_the_code_pack() -> None:
    _, designed = rc_rectangle()
    default = sd.DesignedRcSection(designed, MATERIALS)
    assert (default.phi.tension, default.phi.compression) == (0.90, 0.65)
    custom = sd.DesignedRcSection(designed, MATERIALS, pack=_pack(0.85, 0.60, 0.70))
    assert custom.phi_pn_max == pytest.approx(default.phi_pn_max * 0.60 / 0.65)
    assert custom.phi.at(0.0, 0.0021) == 0.60
    assert custom.phi.at(0.0021 + 0.0015, 0.0021) == pytest.approx(0.725)
    assert custom.phi.at(0.01, 0.0021) == 0.85
    spiral = sd.DesignedRcSection(
        designed.model_copy(update={"confinement": "spiral"}), MATERIALS, pack=_pack(0.85, 0.6, 0.7)
    )
    assert spiral.phi_pn_max == pytest.approx(0.85 * 0.70 * default.p0)


def test_surface_for_the_viewer() -> None:
    _, designed = rc_rectangle()
    surface = sd.DesignedRcSection(designed, MATERIALS).surface(angles=8, count=6)
    assert len(surface["meridians"]) == 8
    caps = [row[0] for m in surface["meridians"] for row in m["points"]]
    assert max(caps) == pytest.approx(surface["phiPnMax"])


# ─────────────────────────────────────── files and the model ───────────────────────────────────────


def test_json_round_trip(tmp_path) -> None:
    wall = section(
        rect(0, 0, 3000, 3000), holes=[rect(200, 200, 2800, 2800)], bars=[(100, 100, 16)], cover=40
    )
    path = sd.save_section(tmp_path, wall)
    assert path == tmp_path / "04 Objects" / "sections" / "S1.json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "saengine.section/1"
    assert sd.load_section(tmp_path, "S1") == wall
    assert sd.list_sections(tmp_path) == ["S1"]


def test_designed_profile_in_object_types(tmp_path) -> None:
    from saengine.codes import context
    from saengine.library.sections import section_properties

    library = o.ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "CL1",
                    "name": "L column",
                    "kind": "column",
                    "material": "C30",
                    "profile": {"shape": "designed", "section": "L1"},
                },
                {
                    "id": "C1",
                    "name": "old",
                    "kind": "column",
                    "material": "C30",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                },
            ]
        }
    )
    profile = library.objects[0].profile
    assert isinstance(profile, o.DesignedProfile)
    (tmp_path / "02 Project Settings").mkdir()
    outline = [(0, 0), (600, 0), (600, 250), (250, 250), (250, 600), (0, 600)]
    sd.save_section(tmp_path, section(outline, id="L1"))
    with context.project(tmp_path):
        props = section_properties(profile)
        frame = sd.frame_section(profile, MATERIALS)
    assert props.area == pytest.approx(237_500)
    assert frame["Ixx"] == pytest.approx(props.ixx, rel=1e-3)
    assert frame["E"] == 25_700


def test_library_check_reports_a_missing_designed_section(tmp_path) -> None:
    from saengine.codes import context
    from saengine.library.check import check_library

    (tmp_path / "02 Project Settings").mkdir()
    text = json.dumps(
        {
            "objects": [
                {
                    "id": "CL1",
                    "name": "L",
                    "kind": "column",
                    "material": "C30",
                    "profile": {"shape": "designed", "section": "NOPE"},
                }
            ]
        }
    )
    with context.project(tmp_path):
        problems = check_library("objects", text, MATERIALS.model_dump_json(by_alias=True))
    assert any("NOPE" in p["message"] for p in problems)
