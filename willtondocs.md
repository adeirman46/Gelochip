

- Implemented `wait.py` for socket handling in urllib3.
- Added `vendor.txt` to manage dependencies for pip's vendor packages.
- Created `py.typed` to provide typing information for pip.
- Configured virtual environment settings in `pyvenv.cfg`.
- Developed various RF components in `rf_blocks.py`, including:
  - `lna_block`: Cascode LNA block with AC-coupled input.
  - `rf_amp_block`: Single-stage RF amplifier.
  - `buffer_block`: Source follower buffer.
  - `combiner_8to1`: Passive 8:1 combiner.
  - `rx_frontend`: RX front-end combining LNA and switches.
  - `mtp_memory_wrapper`: MTP memory macro wrapper.

- DRC/LVS verification (gf180 via Magic/Netgen in IIC-OSIC-TOOLS):
  - Summary JSON: [outputs/rf_blocks_verification/summary.json](outputs/rf_blocks_verification/summary.json)
  - `lna_block`: DRC PASS; LVS FAIL (report generated, netlist stub/no devices).
  - `rf_amp_block`: DRC PASS; LVS FAIL (report generated, netlist stub/no devices).
  - `buffer_block`: DRC PASS; LVS FAIL (report generated, netlist stub/no devices).
  - `combiner_8to1`: DRC PASS; LVS ERROR (report missing).
  - `rx_frontend`: DRC PASS; LVS FAIL (report generated, netlist stub/no devices).
  - `mtp_memory_wrapper`: DRC PASS; LVS ERROR (report missing).