

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