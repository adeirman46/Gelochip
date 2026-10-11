# Verified xschem 3.4 + GF180MCU (gf180mcuD) authoring guide

You write xschem `.sch` files as plain text. The runtime is xschem 3.4.8 with
the GF180MCU-D PDK; netlisting and ngspice simulation run through OpenADA.
Everything below has been verified against this exact runtime.

## File skeleton

```
v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
<wires, components, texts>
```

## Wires and connectivity (IMPORTANT)

- Wire: `N x1 y1 x2 y2 {lab=NETNAME}`
- Connect with BOTH, always: real pin-to-pin `N` wires AND a
  `devices/lab_pin.sym` label at the EXACT pin coordinate of each pin.
  The labels guarantee netlist connectivity and net names; the wires make
  the drawing readable. A schematic whose wire count is below its
  component count is AUTO-REJECTED by netlist_schematic (code
  sch.quality) - label-only connectivity is not accepted.
- NEVER use ';' '#' or '//' comment lines in .sch files - they are not
  valid xschem records. Annotate with T records if needed.
- Coordinates are SPACE-separated integers (never commas!) on a 10-unit grid (use multiples of 10; pin
  offsets are multiples of 10 already).
- Ground: either `devices/gnd.sym` at a pin coordinate or `lab_pin` with
  `lab=0`. SPICE ground is net `0`.

## Components

`C {<symbol>} x y rotation flip {attributes}`

Use rotation 0 unless noted. flip 0 = normal, flip 1 = mirrored around the
vertical axis (pin x-offsets negate).

### GF180 3.3 V MOSFETs (real PDK devices, subcircuit models)

- `C {symbols/nfet_03v3.sym} x y 0 0 {name=M1 W=10u L=0.28u nf=2 m=1}`
- `C {symbols/pfet_03v3.sym} x y 0 0 {name=M2 W=20u L=0.28u nf=2 m=1}`
- Min L = 0.28u. W is TOTAL width (per device). Do not set model/spiceprefix;
  defaults are correct (they netlist as X-prefixed subcircuits).
- Pin coordinates relative to placement (x,y), rotation 0, flip 0:
  - nfet_03v3: D=(x+20, y-30), G=(x-20, y), S=(x+20, y+30), B=(x+20, y)
  - pfet_03v3: D=(x+20, y+30), G=(x-20, y), S=(x+20, y-30), B=(x+20, y)
  - with flip 1, negate the x-offsets: e.g. nfet D=(x-20, y-30), G=(x+20, y)
- ALWAYS label all four pins (D, G, S, B) with lab_pin. NMOS bulk B ties to
  net 0 (or source); PMOS bulk B ties to VDD (or source).

### Generic testbench devices (ideal elements, fine for stimulus/loads)

- Resistor: `C {devices/res.sym} x y 0 0 {name=R1 value=1k}`
  pins: p=(x, y-30), m=(x, y+30). With rotation 1: p=(x+30, y), m=(x-30, y).
- Capacitor: `C {devices/capa.sym} x y 0 0 {name=C1 value=1p}`
  pins: p=(x, y-30), m=(x, y+30)
- Voltage source: `C {devices/vsource.sym} x y 0 0 {name=V1 value="SIN(0 0.05 5MEG)"}`
  pins: p=(x, y-30) is +, m=(x, y+30) is −.
  DC source: `value=3.3`  Sine: `value="SIN(<offset> <ampl> <freq>)"`
- Current source: `C {devices/isource.sym} x y 0 0 {name=I1 value=1m}`
  pins: p=(x, y-30), m=(x, y+30); current flows INTO p, out of m
  (tail sink to ground: p at the tail net, m at net 0).
- Inductor: `C {devices/ind.sym} x y 0 0 {name=L1 value=270n}`
  pins: p=(x, y-30), m=(x, y+30). Ideal element for matching networks
  (models an off-chip component at these frequencies).
- Net label: `C {devices/lab_pin.sym} x y 0 0 {name=p1 lab=NETNAME}`
  (attach point exactly at (x, y); increment name= p1, p2, p3 ... uniquely)
- Ground symbol: `C {devices/gnd.sym} x y 0 0 {name=l1 lab=0}`

## SPICE control block (exactly one, required)

```
C {devices/code_shown.sym} 700 -600 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.tran 1n 10u
.save all"}
```

- BOTH model lines are REQUIRED, in this order: the `design.ngspice`
  include defines corner-switch parameters the PDK library needs, then
  `.lib ... typical` loads the real BSIM models. Without `design.ngspice`
  the simulation fails with `Undefined parameter [sw_stat_mismatch]`.
  The runtime handles include safety automatically (OpenADA control mode);
  you never need to work around it.
- NEVER define your own `.subckt nfet_03v3`, `.model`, or any other
  substitute for a PDK device. The `.lib` line provides the real BSIM
  models; a hand-written level-1 fake invalidates the evidence and fails
  review.
- Allowed analysis cards: one `.tran`, and optionally also one `.ac` in
  the same deck. When both are present the runtime produces
  `<name>_tran.raw` and `<name>_ac.raw` (see simulate_netlist's
  `raw_paths`). No `.control` blocks, no `.measure`, no other includes.
- NEVER use `.option savecurrents`: with hierarchical (subcircuit)
  devices ngspice emits `dims=0` current vectors that OpenADA's raw
  validator rejects (`raw.variable_dimensions_invalid`) - the whole
  simulation is then invalid evidence. Need a branch current? Read
  i(vsource) of an existing source, or insert a 0 V source in series.
- For an AC gain testbench: give the input source an AC magnitude, e.g.
  `value="DC 0.9 AC 1"` (or add AC to a SIN source:
  `value="SIN(0.9 0.01 100MEG) AC 1"`), then add
  `.ac dec 20 1k 1G`. Gain in dB at the output node then reads directly
  from analyze_raw (`gain_db_peak`, `gain_db_samples`, -3 dB corners).
- Real BSIM decks simulate slowly (a 10 us transient can take minutes);
  that is normal — do not shrink the analysis below what verification
  needs. A step of 1n over 10u is a good default FOR LOW-FREQUENCY blocks.
- HIGH FREQUENCY (RF) — CRITICAL to avoid timeouts: a transient at GHz
  frequencies over microseconds has BILLIONS of timesteps and WILL time
  out (the runtime kills sims after ~540 s). For any block at ~100 MHz or
  above:
  - Verify GAIN / frequency response with `.ac` (runs in seconds), not a
    long transient. E.g. `.ac dec 50 1MEG 10G` and read gain at the band.
  - If you need a transient, keep it to a few tens of PERIODS only:
    tstop = 30/f, timestep = 1/(200*f). At 2.4 GHz: `.tran 2p 12n`.
    Never run microseconds of transient at GHz.
  - Match the timestep to the frequency, not to a fixed 1n.
- Oscillators: an ideal ring settles into a metastable DC point and never
  starts in simulation — add a kick, e.g. `.ic V(OSC1)=0` line in the
  control block (allowed), or use `.option` uic on the tran line
  (`.tran 0.1n 2u uic`).
- Never use double quotes inside `value="..."` content, and never use
  curly braces inside any attribute value.

## Netlisting rules

- Every instance needs a unique `name=` (M1, M2..., R1..., V1..., p1, p2...).
- All nets you care about must be labeled with lab_pin so they keep their
  names in the netlist (RF_P, LO_P, IF_P, VDD, etc. — uppercase, no spaces).
- The netlist is generated from the top-level .sch; the control block text is
  inserted verbatim.

## Placement and wiring quality (required)

The schematic must be readable by a human engineer, not just netlist-correct:

- Signal flows left to right: stimulus sources on the left, stage 1 next,
  then stage 2, ..., output on the right.
- Consistent pitch: at least 240 units horizontally between stage centers;
  align the transistors of all stages on the same y rows.
- Draw REAL wires (`N` segments) for every local connection — drain to load
  resistor, source to ground, coupling cap between stages. Route pin-to-pin
  with at most one corner (horizontal segment then vertical segment), with
  endpoints exactly on the pin coordinates from the tables above.
- Use lab_pin labels for global rails (VDD, 0, bias) and to NAME nets; do
  not scatter unconnected symbols and rely on labels instead of wires
  between adjacent components.
- One horizontal VDD rail wire at the top of the circuit; grounds at the
  bottom. Do not overlap symbols or text; keep at least 60 units between a
  symbol and any unrelated object. All coordinates in multiples of 10.
- A wire that PASSES THROUGH a pin coordinate CONNECTS to that pin, and a
  wire ENDPOINT landing mid-segment on another wire makes a T-junction.
  Never route a wire across an unrelated instance pin or bus line - it
  silently shorts the nets (symptom: "shorted output node" warnings plus
  "undriven node" errors at netlist). Give every vertical riser its own
  x lane clear of all pins it must not touch.
- These rules are ENFORCED: netlist_schematic rejects schematics with too
  few wires or stacked symbols, and done(spec_met=true) is rejected while
  any schematic in the workspace fails the check.

## Verification completeness (required)

The testbench must make every block's function VISIBLE and verifiable:

- plan.md must carry an expected-values table for EVERY block before any
  schematic is drawn, e.g.:

  | Block | Node | Expected waveform | Freq | Ampl/Vpp | DC level |
  |---|---|---|---|---|---|
  | rectifier | IN_P/IN_N | sine (diff) | 50 MHz | 0.8 V ampl | ~VBIAS |
  | rectifier | VRECT | rectified ripple | 100 MHz ripple | <0.3 Vpp | ≥0.5 V |
  | dickson | N1/N2/N3 | stair-step charge-up | - | - | rising per stage |
  | top | VOUT | RC charge-up to plateau | - | - | ≥1.2 V |

  In the done evidence, quote measured-vs-expected for each row.
- RF specs speak in POWER: state the source in BOTH dBm and volts in
  plan.md and in the done evidence. Available power from a source with
  amplitude Va and series resistance Rs is P = Va^2/(8*Rs); at 50 ohm,
  -20 dBm = 63 mV, -10 dBm = 0.2 V, 0 dBm = 0.632 V amplitude. Always
  report the operating frequency and the DC output voltage together with
  the input power they were measured at.
- There is NO shell: writing a `.sh` file or shell commands does nothing
  (only the listed tools execute). Never write test.sh / fix_path.sh /
  ls etc. — fix the actual deck instead.
- Do NOT deadlock on one block. If a block's verification keeps failing
  or timing out after ~3 attempts, STOP polishing it: proceed to build
  the OTHER blocks (mixer, LO, PA, ...) and the rest of the system, note
  the block's open issue in your plan, and revisit it later. A partial
  system with every block drawn beats an endless loop on block 1.
- Verify EACH IP BLOCK before building the next one (and before the top
  level): after a block's .sch+.sym netlist cleanly, draw tb_<block>.sch
  — a testbench SCHEMATIC that instantiates <block>.sym, adds the ideal
  stimulus from the block's expected-values row and a realistic load,
  with the two PDK model lines and one .tran in its CONTROL block — then
  netlist_schematic it, simulate_netlist the produced deck, and
  analyze_raw the block's nodes. Only when the block meets its expected
  values do you move on. The tb rawfile shares the testbench's name, so
  both tb_<block>.sch and the block schematic get their waveform panes
  embedded automatically.
- Sweep evidence for RF harvester/receiver-class specs: after the top
  level passes at the nominal point, run sweep decks in exp/ (copies of
  the top netlist with the source amplitude or frequency changed - e.g.
  -10/-5/0/+5 dBm at the center frequency, and 3-5 frequencies across the
  band at 0 dBm), analyze_raw the settled output of each, then plot_xy
  TWO charts: output voltage vs input power (dBm) and output voltage vs
  frequency. Quote both curves in the done evidence.

- Label a probe net at the input, at the output of every internal stage,
  and at the final output (e.g. RF_P, VRECT, N1, N2, VOUT). Waveform plots
  are generated from these labeled nets - unlabeled nodes cannot be shown.
- Run the analyses that prove each claim: .tran for time-domain behaviour
  (rectification, charge-up, oscillation, mixing), plus .ac when gain or
  frequency response is part of the spec.
- analyze_raw EVERY stage's key node (at least 3 vectors: input, each
  intermediate, output) and quote the numbers in your done evidence.
  done(spec_met=true) is auto-rejected until a simulation succeeded, the
  per-stage vectors were analyzed, and waveform plots were generated.
- Waveform panes are embedded into every .sch automatically when you call
  done, matched by the net labels in that schematic - so LABEL the nets
  you want displayed. Opening any schematic in xschem then shows its
  waveforms immediately.

## Hierarchical designs (REQUIRED for any multi-block design)

For a chain of blocks (rectifier + charge pump, mixer + LO, ...), draw one
.sch per block plus a matching .sym, and instantiate the symbols in ONE
top-level testbench. Do NOT write per-block testbenches (no tb_block.sch
files): the single top-level testbench exercises every block, and probe
nets labeled inside each block schematic get their waveforms embedded
from the top-level simulation (hierarchy names like x1.node resolve
automatically). plan.md must cover ALL blocks and the top level before
you draw the first one.
This exact example is VERIFIED end-to-end (netlist + ngspice pass):

Block `csamp.sch` - ports drawn with devices/ipin.sym / opin.sym at the
port nets (names must match the .sym pins). Ground inside a block is the
global net 0 - never make 0 a port:

```text
v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 200 -200 200 -160 {lab=VDD}
N 200 -100 200 -60 {lab=OUT}
N 200 -60 260 -60 {lab=OUT}
N 120 -30 160 -30 {lab=IN}
N 200 0 200 40 {lab=0}
C {devices/ipin.sym} 120 -30 0 0 {name=pIN lab=IN}
C {devices/opin.sym} 260 -60 0 0 {name=pOUT lab=OUT}
C {devices/ipin.sym} 200 -200 0 0 {name=pVDD lab=VDD}
C {devices/res.sym} 200 -130 0 0 {name=R1 value=10k}
C {symbols/nfet_03v3.sym} 180 -30 0 0 {name=M1 L=0.28u W=10u nf=2 m=1}
C {devices/lab_pin.sym} 200 -160 0 0 {name=l1 lab=VDD}
C {devices/lab_pin.sym} 200 -100 0 0 {name=l2 lab=OUT}
C {devices/lab_pin.sym} 160 -30 0 0 {name=l3 lab=IN}
C {devices/lab_pin.sym} 200 0 0 0 {name=l4 lab=0}
C {devices/lab_pin.sym} 200 -30 0 0 {name=l5 lab=0}
C {devices/gnd.sym} 200 40 0 0 {name=g1 lab=0}
```

Symbol `csamp.sym` (same basename, same directory - the netlister then
expands csamp.sch as its .subckt automatically). Pin boxes are `B 5` 5x5
squares centered on the attach point; dir=in/out/inout:

```text
v {xschem version=3.4.8 file_version=1.2}
K {type=subcircuit
format="@name @pinlist @symname"
template="name=X1"}
G {}
V {}
S {}
E {}
L 4 -60 -30 60 -30 {}
L 4 -60 30 60 30 {}
L 4 -60 -30 -60 30 {}
L 4 60 -30 60 30 {}
B 5 -62.5 -2.5 -57.5 2.5 {name=IN dir=in}
B 5 57.5 -2.5 62.5 2.5 {name=OUT dir=out}
B 5 -2.5 -32.5 2.5 -27.5 {name=VDD dir=in}
T {csamp} -40 -8 0 0 0.3 0.3 {}
```

Top-level testbench instantiates it as
`C {csamp.sym} 300 -100 0 0 {name=X1}` (pin absolute position = placement
+ the B-box center from the .sym), wires the sources to the pins, and
carries the single CONTROL block. The netlist comes out as
`X1 IN OUT VDD csamp` + `.subckt csamp IN OUT VDD`.

GROUND GOTCHA (verified): a bare gnd.sym does NOT force the net name to
0 - the source's minus pin netlists as netN and floats. Always place
`devices/lab_pin.sym ... {lab=0}` at the EXACT pin coordinate as well
(and write gnd.sym with `{name=g1 lab=0}`).

## Experiments, golden models and versioning (REQUIRED working style)

Work exactly like the verified LNA run (`lna_v3.sch` → `lna_v4.sch` →
`lna_v5.sch` → `lna_final.spice`): the design history is part of the
evidence.

- Iterate IN THE ROOT with versioned candidates: `rectifier_v1.sch`,
  `rectifier_v2.sch`, ... Each version gets the full loop - netlist,
  simulate, analyze_raw - so each has its own raw and its waveform panes
  embed automatically (raw names share the schematic stem). Never
  overwrite a version you already simulated: the next attempt is a new
  version file.
- When a candidate wins, promote it by copying to the final name
  (`rectifier.sch` + `rectifier.sym`) that the top level instantiates.
- Use `exp/` for the rest of the lab bench: golden-model decks
  (ideal-element references - VCVS, ideal diodes - that show intended
  behaviour to compare the transistor version against), parameter/corner
  sweep decks (`exp/sweep_p0dbm.spice`), scratch analyses. These are
  visible in the run's file list but exempt from the root quality gates.
- Research real reference implementations: search_web for the topology
  plus "spice netlist" or "site:github.com", then fetch_reference the
  best hit (raw file URLs work) into context/refs/ and study it before
  sizing your own. Never paste foreign device models - reimplement with
  the real PDK devices.

## Workflow you must follow

Hierarchy is NOT optional: any design with more than one functional block
(rectifier + charge pump, mixer + LO, amp + filter, ...) MUST be built as
block .sch + .sym pairs with ONE top-level testbench, exactly as in the
hierarchical section above. A single flat .sch is acceptable ONLY for a
single-block circuit (one amplifier, one oscillator).

1. Plans first, as separate files: toplevel_plan.md (the chain, the
   integration, the overall pass criteria) plus one <block>_plan.md per
   block carrying its expected-values rows AND its test: stimulus, nodes
   measured, numeric pass/fail. The plan IS the test spec.
2. For EACH block in signal-chain order: `write_file` block.sch + block.sym,
   `netlist_schematic` the block, then draw and run its testbench
   schematic tb_<block>.sch (netlist_schematic + simulate_netlist +
   analyze_raw) against its expected values. Do not start the next block
   before this one passes.
3. `write_file` the top-level testbench .sch instantiating the block
   symbols; `netlist_schematic` it and CHECK the netlist_text: devices,
   nets, and values must be what you intended. Fix and repeat if not.
4. `simulate_netlist` the produced .spice file.
5. `analyze_raw` the produced .raw for EVERY stage node (inputs, each
   block boundary, output) and verify the engineering behaviour from the
   DC levels, amplitudes and FFT peaks.
6. Iterate until the evidence is convincing, then call `done` with a
   summary quoting measured-vs-expected per block.


## VERIFIED WORKED EXAMPLE

The following is a COMPLETE, verified-working schematic from this exact
runtime (a Gilbert-cell mixer testbench that netlists cleanly and passed
simulation). Imitate its structure precisely - record syntax, lab_pin
usage at pin coordinates, wire records with braced labels, and the
control block:

```
v {xschem version=3.4.8 file_version=1.2}
G {}
K {}
V {}
S {}
E {}

C {symbols/nfet_03v3.sym} 400 600 0 0 {name=M1 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 800 600 0 0 {name=M2 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 400 400 0 0 {name=M3 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 500 400 0 0 {name=M4 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 700 400 0 0 {name=M5 W=20u L=0.28u nf=2 m=1}
C {symbols/nfet_03v3.sym} 800 400 0 0 {name=M6 W=20u L=0.28u nf=2 m=1}
C {devices/res.sym} 450 250 0 0 {name=R1 value=5k}
C {devices/res.sym} 770 250 0 0 {name=R2 value=5k}
C {devices/isource.sym} 600 700 0 0 {name=I1 value=200u}
C {devices/vsource.sym} 100 100 0 0 {name=V1 value=3.3}
C {devices/vsource.sym} 100 600 0 0 {name=V2 value="SIN(1.5 0.05 5MEG)"}
C {devices/vsource.sym} 1100 600 0 0 {name=V3 value="SIN(1.5 0.05 5MEG 0 0 180)"}
C {devices/vsource.sym} 100 400 0 0 {name=V4 value="SIN(2.2 0.4 4MEG)"}
C {devices/vsource.sym} 1100 400 0 0 {name=V5 value="SIN(2.2 0.4 4MEG 0 0 180)"}
C {devices/code_shown.sym} 700 -600 0 0 {name=CONTROL only_toplevel=true value=".include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
E1 IF_DIFF 0 IF_P IF_N 1
.tran 1n 10u
.save all"}

N 450 220 770 220 {lab=VDD}
N 450 280 450 340 {lab=IF_P}
N 420 370 420 340 {lab=IF_P}
N 420 340 720 340 {lab=IF_P}
N 720 340 720 370 {lab=IF_P}
N 520 370 520 390 {lab=IF_N}
N 520 390 820 390 {lab=IF_N}
N 820 390 820 370 {lab=IF_N}
N 770 280 770 390 {lab=IF_N}
N 420 430 520 430 {lab=M1D}
N 420 430 420 570 {lab=M1D}
N 720 430 820 430 {lab=M2D}
N 820 430 820 570 {lab=M2D}
N 420 630 820 630 {lab=TAIL}
N 600 630 600 670 {lab=TAIL}

C {devices/lab_pin.sym} 420 570 0 0 {name=p1 lab=M1D}
C {devices/lab_pin.sym} 380 600 0 0 {name=p2 lab=RF_P}
C {devices/lab_pin.sym} 420 630 0 0 {name=p3 lab=TAIL}
C {devices/lab_pin.sym} 420 600 0 0 {name=p4 lab=0}
C {devices/lab_pin.sym} 820 570 0 0 {name=p5 lab=M2D}
C {devices/lab_pin.sym} 780 600 0 0 {name=p6 lab=RF_N}
C {devices/lab_pin.sym} 820 630 0 0 {name=p7 lab=TAIL}
C {devices/lab_pin.sym} 820 600 0 0 {name=p8 lab=0}
C {devices/lab_pin.sym} 420 370 0 0 {name=p9 lab=IF_P}
C {devices/lab_pin.sym} 380 400 0 0 {name=p10 lab=LO_P}
C {devices/lab_pin.sym} 420 430 0 0 {name=p11 lab=M1D}
C {devices/lab_pin.sym} 420 400 0 0 {name=p12 lab=0}
C {devices/lab_pin.sym} 520 370 0 0 {name=p13 lab=IF_N}
C {devices/lab_pin.sym} 480 400 0 0 {name=p14 lab=LO_N}
C {devices/lab_pin.sym} 520 430 0 0 {name=p15 lab=M1D}
C {devices/lab_pin.sym} 520 400 0 0 {name=p16 lab=0}
C {devices/lab_pin.sym} 720 370 0 0 {name=p17 lab=IF_P}
C {devices/lab_pin.sym} 680 400 0 0 {name=p18 lab=LO_N}
C {devices/lab_pin.sym} 720 430 0 0 {name=p19 lab=M2D}
C {devices/lab_pin.sym} 720 400 0 0 {name=p20 lab=0}
C {devices/lab_pin.sym} 820 370 0 0 {name=p21 lab=IF_N}
C {devices/lab_pin.sym} 780 400 0 0 {name=p22 lab=LO_P}
C {devices/lab_pin.sym} 820 430 0 0 {name=p23 lab=M2D}
C {devices/lab_pin.sym} 820 400 0 0 {name=p24 lab=0}
C {devices/lab_pin.sym} 450 220 0 0 {name=p25 lab=VDD}
C {devices/lab_pin.sym} 450 280 0 0 {name=p26 lab=IF_P}
C {devices/lab_pin.sym} 770 220 0 0 {name=p27 lab=VDD}
C {devices/lab_pin.sym} 770 280 0 0 {name=p28 lab=IF_N}
C {devices/lab_pin.sym} 600 670 0 0 {name=p29 lab=TAIL}
C {devices/lab_pin.sym} 600 730 0 0 {name=p30 lab=0}
C {devices/lab_pin.sym} 100 70 0 0 {name=p31 lab=VDD}
C {devices/lab_pin.sym} 100 130 0 0 {name=p32 lab=0}
C {devices/lab_pin.sym} 100 570 0 0 {name=p33 lab=RF_P}
C {devices/lab_pin.sym} 100 630 0 0 {name=p34 lab=0}
C {devices/lab_pin.sym} 1100 570 0 0 {name=p35 lab=RF_N}
C {devices/lab_pin.sym} 1100 630 0 0 {name=p36 lab=0}
C {devices/lab_pin.sym} 100 370 0 0 {name=p37 lab=LO_P}
C {devices/lab_pin.sym} 100 430 0 0 {name=p38 lab=0}
C {devices/lab_pin.sym} 1100 370 0 0 {name=p39 lab=LO_N}
C {devices/lab_pin.sym} 1100 430 0 0 {name=p40 lab=0}
```
