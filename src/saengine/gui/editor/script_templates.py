"""
Structural engineering script templates for SAEngine Code Studio.

Provides pre-built, ready-to-run automation scripts for OpenSeesPy
finite element analysis, parametric ETABS-style building generation,
section property calculation, and load combination automation.
"""

from typing import Dict

PORTAL_FRAME_TEMPLATE = '''"""
OpenSeesPy 2D Elastic Portal Frame Analysis
Analyzes a steel portal frame under gravity and lateral wind/seismic loads.
"""

import openseespy.opensees as ops
import numpy as np

# 1. Initialize model
ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)

# 2. Geometry: Span = 6.0 m, Height = 4.0 m
L = 6.0
H = 4.0

# Define Nodes: (NodeID, X, Y)
ops.node(1, 0.0, 0.0)
ops.node(2, L,   0.0)
ops.node(3, 0.0, H)
ops.node(4, L,   H)

# Boundary Conditions (Fixed base)
ops.fix(1, 1, 1, 1)
ops.fix(2, 1, 1, 1)

# 3. Material and Section Properties (Steel)
E = 200e9      # Pa (200 GPa)
A_col = 0.015  # m^2 (Columns)
I_col = 3.0e-4 # m^4
A_beam = 0.020 # m^2 (Beam)
I_beam = 5.0e-4# m^4

# Geometric Transformation (Linear)
ops.geomTransf('Linear', 1)

# Elements: (EleID, NodeI, NodeJ, A, E, I, TransfID)
ops.element('elasticBeamColumn', 1, 1, 3, A_col,  E, I_col,  1) # Left Column
ops.element('elasticBeamColumn', 2, 2, 4, A_col,  E, I_col,  1) # Right Column
ops.element('elasticBeamColumn', 3, 3, 4, A_beam, E, I_beam, 1) # Roof Beam

# 4. Loads: Lateral load 50 kN at roof (Node 3), Gravity 20 kN/m on beam
ops.timeSeries('Constant', 1)
ops.pattern('Plain', 1, 1)
ops.load(3, 50000.0, 0.0, 0.0)  # Lateral 50 kN

# 5. Analysis Settings
ops.system('BandSPD')
ops.numberer('RCM')
ops.constraints('Plain')
ops.integrator('LoadControl', 1.0)
ops.algorithm('Linear')
ops.analysis('Static')

# 6. Run Analysis
ops.analyze(1)

# 7. Print Results
ops.reactions()
print("=" * 50)
print("PORTAL FRAME ANALYSIS RESULTS")
print("=" * 50)
for node in [3, 4]:
    disp = ops.nodeDisp(node)
    print(f"Node {node} Displacements: dx = {disp[0]*1000:8.3f} mm, dy = {disp[1]*1000:8.3f} mm, rot = {disp[2]:8.5f} rad")

print("-" * 50)
for node in [1, 2]:
    rx = ops.nodeReaction(node, 1)
    ry = ops.nodeReaction(node, 2)
    rm = ops.nodeReaction(node, 3)
    print(f"Base Node {node} Reactions: Rx = {rx/1000:8.2f} kN, Ry = {ry/1000:8.2f} kN, Mz = {rm/1000:8.2f} kN*m")
print("=" * 50)
'''

PARAMETRIC_BUILDING_TEMPLATE = '''"""
Parametric Multi-Story Building Grid & Story Generator
Programmatically configures structural grids and stories in SAEngine.
"""

from saengine.core.project import Project
from saengine.core.grid import GridSystem, GridLine
from saengine.core.story import StorySystem, StoryLevel
from saengine.commands.model_commands import SetGridSystemCommand, SetStorySystemCommand

# When executed inside SAEngine, 'project' and 'cmd_manager' are automatically provided!
try:
    proj = project  # Injected by SAEngine Code Runner
except NameError:
    proj = Project.create_new("Parametric High-Rise")

# 1. Define Parametric Building Grid
# 4 Bays in X (8m spacing) and 3 Bays in Y (6m spacing)
grid = GridSystem()
x_spacings = [0.0, 8.0, 16.0, 24.0, 32.0]
x_labels = ["A", "B", "C", "D", "E"]
for label, x in zip(x_labels, x_spacings):
    grid.add_x_line(GridLine(label=label, coordinate=x, visible=True))

y_spacings = [0.0, 6.0, 12.0, 18.0]
y_labels = ["1", "2", "3", "4"]
for label, y in zip(y_labels, y_spacings):
    grid.add_y_line(GridLine(label=label, coordinate=y, visible=True))

# 2. Define Parametric Story Levels (10 Stories)
stories = StorySystem()
story_height = 3.6  # meters
for s in range(1, 11):
    level = StoryLevel(
        id=f"story_{s}",
        name=f"Story {s}",
        height=story_height,
        elevation=s * story_height,
        is_master=(s == 5 or s == 10),
        similar_to="Story 5" if s > 5 and s != 10 else None
    )
    stories.add_story(level)

# 3. Apply to SAEngine Project
if 'cmd_manager' in locals() or 'cmd_manager' in globals():
    cmd_manager.execute(SetGridSystemCommand(proj.grids, grid))
    cmd_manager.execute(SetStorySystemCommand(proj.stories, stories))
    proj.mark_dirty()
    print("Successfully generated parametric grids (5x4) and 10 stories!")
else:
    proj.grids = grid
    proj.stories = stories
    print(f"Project initialized with {len(grid.x_lines)} X-Grids, {len(grid.y_lines)} Y-Grids, and {len(stories.stories)} Stories.")
'''

MODAL_ANALYSIS_TEMPLATE = '''"""
OpenSeesPy Multi-Story Building Eigen / Modal Analysis
Computes natural periods, frequencies, and circular frequencies.
"""

import openseespy.opensees as ops
import numpy as np

ops.wipe()
ops.model('basic', '-ndm', 2, '-ndf', 3)

# 3-Story Shear Building representation
num_stories = 3
h = 3.5      # story height (m)
m_floor = 40.0e3  # 40 metric tons lumped mass per floor (kg)
k_story = 30.0e6  # 30 MN/m lateral stiffness

# Fixed base
ops.node(0, 0.0, 0.0)
ops.fix(0, 1, 1, 1)

# Story nodes and masses
for i in range(1, num_stories + 1):
    ops.node(i, 0.0, i * h)
    ops.fix(i, 0, 1, 1) # Restrain vertical and rotational DOF
    ops.mass(i, m_floor, 0.0, 0.0)

# Connect with elastic columns
ops.geomTransf('Linear', 1)
E = 30e9
for i in range(1, num_stories + 1):
    # I such that 12*E*I/h^3 = k_story -> I = k * h^3 / (12*E)
    I_eq = (k_story * (h**3)) / (12.0 * E)
    ops.element('elasticBeamColumn', i, i - 1, i, 1.0, E, I_eq, 1)

# Compute 3 Eigenvalues
num_modes = 3
lambdas = ops.eigen(num_modes)

print("=" * 60)
print(f"{'Mode':<8}{'Omega (rad/s)':<18}{'Freq (Hz)':<16}{'Period (s)':<12}")
print("=" * 60)
for i, lam in enumerate(lambdas, 1):
    omega = np.sqrt(lam)
    freq = omega / (2 * np.pi)
    period = 1.0 / freq
    print(f"{i:<8}{omega:<18.4f}{freq:<16.4f}{period:<12.4f}")
print("=" * 60)
'''

SECTION_CALCULATOR_TEMPLATE = '''"""
Structural Section Properties Calculator
Calculates cross-sectional properties for standard and built-up steel shapes.
"""

def calculate_i_beam(d_mm: float, bf_mm: float, tf_mm: float, tw_mm: float):
    """
    Calculate section properties for Wide Flange / I-Beam.
    d:  Total depth (mm)
    bf: Flange width (mm)
    tf: Flange thickness (mm)
    tw: Web thickness (mm)
    """
    d = d_mm / 1000.0
    bf = bf_mm / 1000.0
    tf = tf_mm / 1000.0
    tw = tw_mm / 1000.0
    hw = d - 2 * tf

    # Area
    area = 2 * (bf * tf) + (hw * tw)

    # Moment of Inertia - Strong Axis (Ix)
    ix = (1/12) * tw * (hw**3) + 2 * ((1/12) * bf * (tf**3) + (bf * tf) * ((d/2 - tf/2)**2))

    # Moment of Inertia - Weak Axis (Iy)
    iy = 2 * ((1/12) * tf * (bf**3)) + (1/12) * hw * (tw**3)

    # Radii of Gyration
    rx = (ix / area)**0.5
    ry = (iy / area)**0.5

    # Elastic Section Moduli
    sx = ix / (d / 2)
    sy = iy / (bf / 2)

    # Plastic Section Moduli
    zx = (tw * (hw**2) / 4) + (bf * tf * (d - tf))
    zy = (tf * (bf**2) / 2) + (hw * (tw**2) / 4)

    return {
        "Area (cm^2)": area * 1e4,
        "Ix (cm^4)": ix * 1e8,
        "Iy (cm^4)": iy * 1e8,
        "rx (cm)": rx * 100,
        "ry (cm)": ry * 100,
        "Sx (cm^3)": sx * 1e6,
        "Sy (cm^3)": sy * 1e6,
        "Zx (cm^3)": zx * 1e6,
        "Zy (cm^3)": zy * 1e6,
    }

# Example: W24x68 (d=603mm, bf=228mm, tf=14.9mm, tw=10.5mm)
props = calculate_i_beam(d_mm=603.0, bf_mm=228.0, tf_mm=14.9, tw_mm=10.5)

print("=" * 45)
print("WIDE FLANGE SECTION PROPERTIES (W24x68)")
print("=" * 45)
for k, v in props.items():
    print(f"{k:<20}: {v:>15.2f}")
print("=" * 45)
'''

TEMPLATES: Dict[str, str] = {
    "OpenSees 2D Portal Frame": PORTAL_FRAME_TEMPLATE,
    "Parametric Building Model": PARAMETRIC_BUILDING_TEMPLATE,
    "Modal / Eigen Analysis": MODAL_ANALYSIS_TEMPLATE,
    "Section Properties Calculator": SECTION_CALCULATOR_TEMPLATE,
}
