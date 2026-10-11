## ref 0 — books: Hastings 'The Art of Analog Layout' 2e; Baker 'CMOS: Circuit Design, Layout & Simulation' 3e; Pelgrom 1989
A current mirror lays out as an INTERDIGITIZED matched pair with SHARED (shorted) source and gate, the reference leg DIODE-CONNECTED (gate=drain), dummies on the edges, and a tapring tie — exactly glayout.cells.elementary.current_mirror.current_mirror(). This is the standard, DRC/LVS-clean realization. (Hastings current-source layout; glayout cell.)

## ref 1 — analog-layout-knowledge
For standard analog blocks, INSTANTIATE glayout's own cell generators instead of placing bare fets and hand-routing (hand-routed metal that crosses a device FAILS DRC, and a bare Component has no netlist so LVS can't run). Verified generators (all DRC+LVS clean, interdigitized, dummies tied to the tapring, netlist attached):
- CURRENT MIRROR: from glayout.cells.elementary.current_mirror.current_mirror import current_mirror, add_cm_labels; cm=current_mirror(pdk, numcols=2, device='nfet'|'pfet', with_dummy=True, with_tie=True, width=W_um, length=L_um, fingers=NF); cm=add_cm_labels(cm,pdk).
- DIFF PAIR: from glayout.cells.elementary.diff_pair.diff_pair import diff_pair.
- MATCHED PAIR: two_nfet_interdigitized / two_pfet_interdigitized.
These carry info['netlist'] so netgen LVS PASSES.

## ref 2 — glayout:src/glayout/cells/elementary/current_mirror/current_mirror.py
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized, two_pfet_interdigitized, two_tran_interdigitized_netlist
from glayout.pdk.mappedpdk import MappedPDK
from glayout.routing.c_route import c_route
from glayout.routing.L_route import L_route
from glayout.routing.straight_route import straight_route
from glayout.spice.netlist import Netlist
from glayout.primitives.fet import nmos, pmos
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import add_ports_perimeter,rename_ports_by_orientation
from glayout.backend import Component, cell, rectangle
from glayout.util.comp_utils import evaluate_bbox, prec_center, prec_ref_center, align_comp_to_port
from typing import Optional, Union 
from glayout.primitives.via_gen import via_stack
from glayout.pdk.sky130_mapped import sky130_mapped_pdk
try:
    from glayout.verification.evaluator_wrapper import run_evaluation
except ImportError:
    print("Warning: evaluator_wrapper not found. Evaluation will be skipped.")
    run_evaluation = None


def add_cm_labels(cm_in: Component,
                pdk: MappedPDK 
                ) -> Component:
	
    cm_in.unlock()
    met2_pin = (68,16)
    met2_label = (68,5)

    # list that will contain all port/comp info
    move_info = list()
    # create labels and append to info list
    # vss
    vsslabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vsslabel.add_label(text="VSS",layer=pdk.get_glayer("met2_label"))
    move_info.append((vsslabel,cm_in.ports["fet_A_source_E"],None))
    
    # vref
    vreflabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vreflabel.add_label(text="VREF",layer=pdk.get_glayer("met2_label"))
    move_info.append((vreflabel,cm_in.ports["fet_A_drain_N"],None))
    
    # vcopy
    vcopylabel = rectangle(layer=pdk.get_glayer("met2_pin"),size=(0.27,0.27),centered=True).copy()
    vcopylabel.add_label(text="VOUT",layer=pdk.get

## ref 3 — glayout:src/glayout/cells/composite/stacked_current_mirror/stacked_current_mirror.py
from glayout import MappedPDK, sky130,gf180
from glayout.backend import Component, ComponentReference, cell, clear_cache, copy, rectangle, route_quad
from typing import Optional, Union
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.cells.elementary.diff_pair import diff_pair
from glayout.primitives.guardring import tapring
from glayout.primitives.mimcap import mimcap_array, mimcap
from glayout.routing import c_route,L_route,straight_route
from glayout.primitives.via_gen import via_stack, via_array
from glayout.util.comp_utils import evaluate_bbox, prec_ref_center, movex, movey, to_decimal, to_float, move, align_comp_to_port, get_padding_points_cc
from glayout.util.port_utils import rename_ports_by_orientation, rename_ports_by_list, add_ports_perimeter, print_ports, set_port_orientation, rename_component_ports
from glayout.util.snap_to_grid import component_snap_to_grid
from pydantic import validate_arguments
from glayout.placement.two_transistor_interdigitized import two_nfet_interdigitized
from glayout.spice import Netlist


@validate_arguments
def stacked_nfet_current_mirror(pdk: MappedPDK, half_common_source_nbias: tuple[float, float, int, int], rmult: int, sd_route_left: bool, sd_route_topmet: Optional[str] = "met2") -> Component:
    cmirror_output = nmos(
        pdk,
        width=half_common_source_nbias[0],
        length=half_common_source_nbias[1],
        fingers=half_common_source_nbias[2],
        multipliers=half_common_source_nbias[3],
        with_tie=True,
        with_dnwell=False,
        with_substrate_tap=False,
        with_dummy=True,
        sd_route_left = sd_route_left,
        rmult=rmult,
        tie_layers=("met2","met2"),
        sd_route_topmet=sd_route_topmet,
    )
    cmirrorref = nmos(
        pdk,
        width=half_common_source_nbias[0],
        length=half_common_source_nbias[1],
        fingers=half_common_source_nbias[2],
        multipliers=1,
        with_tie=True,
        with_dnwell=False,
       

## ref 4 — glayout:tutorial/GLayout_Cmirror.ipynb
#!/usr/bin/env python
# coding: utf-8
# %% [markdown]
# # GLayout Current Mirror Tutorial
# ```
# OpenFASOC Team, June 2025
# SPDX-License-Identifier: Apache-2.0
# ```
#

# %% [markdown]
# ## Introduction
# Welcome!
# This notebook serves as an introduction to the GDSFactory-based layout automation tool **GLayout** and an example producing a VIA to explain grules and glayers, as a part of [OpenFASoC](https://github.com/idea-fasoc/OpenFASOC).  

# %%
from glayout import sky130, gf180
from glayout.primitives.via_gen import via_stack, via_array
from glayout.primitives.fet import nmos, pmos, multiplier
from glayout.primitives.guardring import tapring
from glayout.util.port_utils import PortTree, rename_ports_by_orientation
from glayout.util.comp_utils import move, movex, movey, align_comp_to_port, evaluate_bbox, prec_center
from glayout.routing.straight_route import straight_route
from glayout.routing.c_route import c_route
from gdsfactory import Component
import gdstk
import svgutils.transform as sg
import IPython.display
from IPython.display import clear_output
import ipywidgets as widgets

# Redirect all outputs here
hide = widgets.Output()

def display_gds(gds_file, scale = 3):
  # Generate an SVG image
  top_level_cell = gdstk.read_gds(gds_file).top_level()[0]
  top_level_cell.write_svg('out.svg')
  # Scale the image for displaying
  fig = sg.fromfile('out.svg')
  fig.set_size((str(float(fig.width) * scale), str(float(fig.height) * scale)))
  fig.save('out.svg')

  # Display the image
  IPython.display.display(IPython.display.SVG('out.svg'))

def display_component(component, scale = 3):
  # Save to a GDS file
  with hide:
    component.write_gds("out.gds")
  display_gds('out.gds', scale)


# %% [markdown]
# # Current Mirror Layout Design using GLayout API
#  
# ## Overview
# This document provides a detailed tutorial on using the GLayout API to design and generate a layout for a PMOS current mirror circuit. It outlines the steps to initialize the layout components,

## ref 5 — books: Hastings 'The Art of Analog Layout' 2e; Baker 'CMOS: Circuit Design, Layout & Simulation' 3e; Pelgrom 1989
Random device mismatch scales as sigma(dVth) = A_Vth / sqrt(W*L) (Pelgrom's law). To match better, use LARGER area and MORE fingers/unit devices. A current mirror's accuracy is set by the matching of its fets — size them generously and interdigitize. (Hastings ch.7; Pelgrom 1989.)

## ref 6 — analog-layout-knowledge
Matched devices (current-mirror legs, diff pairs) must be laid out for MATCHING: (1) same orientation; (2) INTERDIGITIZE (ABAB) or COMMON-CENTROID (ABBA) so gradients cancel; (3) add DUMMY devices on both edges so every real finger sees the same neighbourhood; (4) identical W/L/finger count. glayout's interdigitized placers do all of this.

## ref 7 — analog-layout-knowledge
A plain nmos/pmos exposes multiplier_0_{source,drain,gate}_{E,W,N,S}. An interdigitized/diff cell exposes A_0_/B_0_ (or fet_A_/fet_B_) names. current_mirror exposes fet_A_*, fet_B_*, welltie_*. A KeyError on a port = you used the wrong family; use the real component's ports (print get_ports_list) and prefer smart_route.

## ref 8 — https://github.com/camilotejeiro/aic_1_lab
// ===== aic_1_lab/ngspice_examples/simple/rfswitch.spice =====
RF switch circuit

* Component Definitions
Ci      in 4    1.6nF
D1      4 5     mydiode
Lc1     3 2     100uH
Lc2     5 0     100e-6
Rb      4 3     2.1k
Rload   out 0   1000
Rs      in 1    50ohm
cout    5 out   1.6n
vcc     2 0     5V
vs      1 0     dc 0V ac 1V sin(0V 1V 100MegHz 20ns 0)

* Model Definitions
.model mydiode d (is=1e-15A n=1)

* NG-Spice Simulation Commands
.PRINT DC V(2,0) V(5)
.DC Rload 0.00K 100.00K 10.00K

.END



// ===== aic_1_lab/ngspice_examples/montecarlo/montecarlo_simple_example.spice =====
Effecting a Monte Carlo calculation in ngspice
* Taken as verbatim reference from NGSPICE examples 
* Thoroughly commented for understanding (feel free to remove comments).

* ---
* Netlist
* ---
V1 N001 0 AC 1 DC 0
R1 N002 N001 141
 
C1 OUT 0 1e-09
L1 OUT 0 10e-06
C2 N002 0 1e-09
L2 N002 0 10e-06
L3 N003 N002 40e-06
C3 OUT N003 250e-12
 
R2 0 OUT 141

.CONTROL
    let mc_runs = 5
    let run = 0
    $ create a new plot
    set curplot=new          
    $ store its name to 'scratch'
    set scratch=$curplot     
    $ make 'scratch' the active plot 
    setplot $scratch         
    $ create a vector in plot 'scratch' to store bandwidth data
    let bwh=unitvec(mc_runs) 

    $ define distributions for random numbers:
    $ unif: uniform distribution, deviation relativ to nominal value
    $ aunif: uniform distribution, deviation absolut
    $ gauss: Gaussian distribution, deviation relativ to nominal value
    $ agauss: Gaussian distribution, deviation absolut
    $ limit: if unif. distributed value >=0 then add +avar to nom, else -avar
    define unif(nom, rvar) (nom + (nom*rvar) * sunif(0))
    define aunif(nom, avar) (nom + avar * sunif(0))
    define gauss(nom, rvar, sig) (nom + (nom*rvar)/sig * sgauss(0))
    define agauss(nom, avar, sig) (nom + avar/sig * sgauss(0))
    define limit(nom, avar) (nom + ((sgauss(0) >= 0) ? avar : -avar))

    dowhile run < mc_runs   
        alter c1

## ref 9 — https://github.com/SoumitroV/Design-and-Simulation-of-a-Gilbert-Cell-based-Mixer-on-CMOS-28nm-Technology
// ===== Design-and-Simulation-of-a-Gilbert-Cell-based-Mixer-on-CMOS-28nm-Technology/Netlist/Mixer_tb.sp =====
*  Generated for: PrimeSim
*  Design library name: Mixer
*  Design cell name: Mixer_tb
*  Design view name: schematic
.lib 'saed32nm.lib' TT
.param F=1meg
*Custom Compiler Version S-2021.09
*Mon Feb 28 12:08:53 2022

.global gnd!
********************************************************************************
* Library          : Mixer
* Cell             : Mixer
* View             : schematic
* View Search List : hspice hspiceD schematic spice veriloga
* View Stop List   : hspice hspiceD
********************************************************************************
.subckt mixer vdd vss v_lo+ v_lo- v_rf+ v_rf- v_out+ v_out-
xm7 net6 net6 vss vss n105 w=2u l=0.03u nf=20 m=1
xm6 net4 net4 vss vss n105 w=2u l=0.03u nf=20 m=1
xm5 net3 net4 vss vss n105 w=2u l=0.03u nf=20 m=1
xm4 net5 net6 vss vss n105 w=2u l=0.03u nf=20 m=1
xm3 v_out- v_lo+ net2 vss n105 w=6u l=0.03u nf=60 m=1
xm2 v_out+ v_lo- net2 vss n105 w=6u l=0.03u nf=60 m=1
xm1 v_out- v_lo- net5 vss n105 w=6u l=0.03u nf=60 m=1
xm0 v_out+ v_lo+ net5 vss n105 w=6u l=0.03u nf=60 m=1
xm21 net1 v_bias vdd vdd p105 w=3u l=0.03u nf=30 m=1
xm20 net7 v_bias vdd vdd p105 w=3u l=0.03u nf=30 m=1
xm19 net10 v_bias vdd vdd p105 w=6u l=0.03u nf=60 m=1
xm18 net8 v_bias2 net9 vdd p105 w=6u l=0.03u nf=60 m=1
xm17 net9 v_bias vdd vdd p105 w=6u l=0.03u nf=60 m=1
xm27 v_out+ v_bias2 net7 vdd p105 w=3u l=0.03u nf=30 m=1
xm28 v_out- v_bias2 net1 vdd p105 w=3u l=0.03u nf=30 m=1
xm9 net4 v_rf- net8 vdd p105 w=6u l=0.03u nf=60 m=1
xm8 net6 v_rf+ net8 vdd p105 w=6u l=0.03u nf=60 m=1
r16 net2 net3 r=1m
r26 v_bias v_bias2 r=3k
r29 net10 v_bias r=3k
i30 v_bias2 vss dc=100u
.ends mixer

********************************************************************************
* Library          : Mixer
* Cell             : Mixer_tb
* View             : schematic
* View Search List : hspice hspiceD schematic spice veriloga
* View Stop List   : 

## ref 10 — https://github.com/symbench/spice-datasets
// ===== spice-datasets/kicad_github/k.cir =====
.title KiCad schematic
.end


// ===== spice-datasets/kicad_github/x.cir =====
.title KiCad schematic
.end


// ===== spice-datasets/kicad_github/65.cir =====
.title KiCad schematic
.end


// ===== spice-datasets/kicad_github/9V.cir =====
.title KiCad schematic
U3 /12V /GND /9V LM7809
C7 /12V /GND 0,1uF
C8 /9V /GND 0,1uF
.end


// ===== spice-datasets/kicad_github/FA.cir =====
.title KiCad schematic
.include "C:\Users\Mind\Downloads\Kicad\new_file\libs\spice_models.lib"
V1 a GND dc 0
R2 GND carry 10meg
R1 GND sum 10meg
X5 Net-_X3-Pad3_ Net-_X4-Pad3_ carry VDD OR
X1 a b Net-_X1-Pad3_ VDD XOR
X2 Net-_X1-Pad3_ c sum VDD XOR
X3 c Net-_X1-Pad3_ Net-_X3-Pad3_ VDD AND
X4 b a Net-_X4-Pad3_ VDD AND
V2 b GND dc 5
V3 c GND dc 5
V4 VDD GND dc 5
.tran .25m 30m
.end


## ref 11 — https://docs.google.com/
Loading
# Sign in
Use your Google Account
Email or phone
Forgot email?
Type the text you hear or see
Not your computer? Use Guest mode to sign in privately. [Learn more about using Guest mode](https://support.google.com/chrome/answer/6130773?hl=en-US)
Next
Create account
English (United States)
  * Afrikaans
  * azərbaycan
  * bosanski
  * català
  * Čeština
  * Cymraeg
  * Dansk
  * Deutsch
  * eesti
  * English (United Kingdom)
  * English (United States)
  * Español (España)
  * Español (Latinoamérica)
  * euskara
  * Filipino
  * Français (Canada)
  * Français (France)
  * Gaeilge
  * galego
  * Hrvatski
  * Indonesia
  * isiZulu
  * íslenska
  * Italiano
  * Kiswahili
  * latviešu
  * lietuvių
  * magyar
  * Melayu
  * Nederlands
  * norsk
  * o‘zbek
  * polski
  * Português (Brasil)
  * Português (Portugal)
  * română
  * shqip
  * Slovenčina
  * slovenščina
  * srpski (latinica)
  * Suomi
  * Svenska
  * Tiếng Việt
  * Türkçe
  * Ελληνικά
  * беларуская
  * български
  * кыргызча
  * қазақ тілі
  * македонски
  * монгол
  * Русский
  * српски (ћирилица)
  * Українська
  * ქართული
  * հայերեն
  * ‫עברית‬‎
  * ‫اردو‬‎
  * ‫العربية‬‎
  * ‫فارسی‬‎
  * አማርኛ
  * नेपाली
  * मराठी
  * हिन्दी
  * অসমীয়া
  * বাংলা
  * ਪੰਜਾਬੀ
  * ગુજરાતી
  * ଓଡ଼ିଆ
  * தமிழ்
  * తెలుగు
  * ಕನ್ನಡ
  * മലയാളം
  * සිංහල
  * ไทย
  * ລາວ
  * မြန်မာ
  * ខ្មែរ
  * 한국어
  * 中文（香港）
  * 日本語
  * 简体中文
  * 繁體中文


  * [Help](https://support.google.com/accounts?hl=en-US&p=account_iph)
  * [Privacy](https://accounts.google.com/TOS?loc=ID&hl=en-US&privacy=true)
  * [Terms](https://accounts.google.com/TOS?loc=ID&hl=en-US)



## ref 12 — https://www.emergentmind.com/topics/eeschematic
[ ](https://www.emergentmind.com/)
[ Papers ](https://www.emergentmind.com/ "Papers") [ Videos ](https://www.emergentmind.com/videos "Videos") [ Whiteboards ](https://www.emergentmind.com/whiteboards "Whiteboards") [ Open Problems ](https://www.emergentmind.com/open-problems "Open Problems") [ Pricing ](https://www.emergentmind.com/pricing?utm_source=nav "Plans & Pricing") [ Log in ](https://www.emergentmind.com/users/sign_in "Log in") [ Sign up ](https://www.emergentmind.com/users/sign_up?redirect_to=https%3A%2F%2Fwww.emergentmind.com%2Ftopics%2Feeschematic "Sign up")
[ Papers ](https://www.emergentmind.com/ "Papers") [ Whiteboards ](https://www.emergentmind.com/whiteboards "Whiteboards") [ Videos ](https://www.emergentmind.com/videos "Videos") [ Open Problems ](https://www.emergentmind.com/open-problems "Open Problems") [ Pricing ](https://www.emergentmind.com/pricing?utm_source=nav "Plans & Pricing") [ Log in ](https://www.emergentmind.com/users/sign_in "Log in") [ Sign up ](https://www.emergentmind.com/users/sign_up?redirect_to=https%3A%2F%2Fwww.emergentmind.com%2Ftopics%2Feeschematic "Sign up")
EEschematic
Papers
Topics
Authors
Recent
[View all](https://www.emergentmind.com/history)
Search
Search
Search by paper, topic, or author
Research
Succinct overviews based on relevant paper abstracts
Deep Research Max
In-depth responses based on relevant abstracts and paper content
2000 character limit reached 
Chrome Extension 
[Install our Chrome Extension](https://chromewebstore.google.com/detail/emergent-mind-%E2%80%94-arxiv-int/hgmnadjffdiipehljmhagdgpaoiiklml) to automatically enhance arXiv. 
Sponsor 
[Promote your business](https://www.emergentmind.com/sponsorship) to millions of monthly visitors. 
#  EEschematic: AI Analog Schematic Generation 
Updated 26 October 2025 
  * EEschematic is a multimodal AI agent that converts textual SPICE netlists into human-editable analog schematics using iterative chain-of-thought reasoning.
  * It employs a Visual Chain-of-Thou

## ref 13 — https://www.scribd.com/doc/68262071/Current-Mirror-Cadence
Opens in a new window Opens an external website Opens an external website in a new window
<!---->Close this dialog<!----> 
This website utilizes technologies such as cookies to enable essential site functionality, as well as for performance cookies, personalization, and targeted advertising. To learn more, view the following link:  [Privacy Policy](https://support.scribd.com/hc/articles/210129366-Privacy-policy)
Your Privacy Choices 
<!---->Close Cookie Preferences<!----> 
Skip to main content
[Open navigation menu](https://www.scribd.com/doc/68262071/Current-Mirror-Cadence#sidebar)[![Scribd](https://www.scribd.com/doc/68262071/Current-Mirror-Cadence)](https://www.scribd.com/)
Close suggestionsSearchSearch
enChange Language, English
[Upload](https://www.scribd.com/upload-document)
[](https://www.scribd.com/oauth/signup?doc_id=68262071)
100%(2)100% found this document useful (2 votes)
443 views80 pages
Current Mirror Design in Cadence
This document provides an introduction and overview to the laboratory manual for the VLSI Circuit Design course ELEN 474. It outlines the objectives, tools, and approach used in the course l…
Full description
## Uploaded by
[juni khisha](https://www.scribd.com/user/5904040/juni-khisha)
AI-enhanced title and description
Go to previous items
  * Download
  * SaveSave Current Mirror Cadence For Later
  * Share
  * 100%100% found this document useful, Mark this document as useful
  * 0%0% found this document not useful, Mark this document as not useful
  * Print
  * Embed
  * Ask AI
  * Report

Go to next items
Download
Save Current Mirror Cadence For Later
Share
More options
Fullscreen
You are on page 1
80
Zoom outZoom in
1 
Lab 0:
Introduction 
This laboratory complements the course ELEN 474: VLSI Circuit Design. The lab manual details basic CMOS analog integrated Circuit design, simulation, and testing techniques. Several tools from the Cadence Development System have been integrated into the lab to teach students the idea of computer ai