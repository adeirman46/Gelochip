PYTHON ?= python3
PDK_ROOT ?= $(CURDIR)/../pdks
PDK ?= gf180mcuD
GF_OPTION ?= A

.PHONY: all prelayout layout drc lvs postlayout report

all: prelayout layout drc lvs postlayout report

prelayout:
	$(PYTHON) scripts/run_prelayout.py

layout:
	USER=root $(PYTHON) scripts/generate_layout.py
	$(PYTHON) scripts/render_lvs_netlist.py
	$(PYTHON) scripts/generate_waveform_plot.py

drc:
	cd layout && PDK_ROOT=$(PDK_ROOT) PDK=$(PDK) $(PYTHON) ../../gf180mcu-pdk/libraries/gf180mcu_fd_pr/latest/rules/klayout/drc/run_drc.py --path=iris.gds --gf180mcu=$(GF_OPTION) --topcell=iris

lvs:
	cd ../pdks/gf180mcuD && PDK_ROOT=$(PDK_ROOT) PDK=$(PDK) $(PYTHON) ../../gf180mcu-pdk/libraries/gf180mcu_fd_pr/latest/rules/klayout/lvs/run_lvs.py --design=../../iris_rf/layout/iris.gds --net=../../iris_rf/netlist/iris_lvs.cdl --gf180mcu=$(GF_OPTION) --set_top_lvl_pins --set_spice_comments --set_verbose

postlayout:
	$(PYTHON) scripts/run_postlayout.py

report:
	$(PYTHON) scripts/render_report.py
