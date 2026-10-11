# Web research

Query: "xschem" "Error: undriven node"


## Grounded digest (Google Search via Gemini)
An **"Error: undriven node: <node_name>"** in Xschem is triggered by the built-in **Electrical Rule Check (ERC)** engine. During netlisting, Xschem evaluates the topology of every net. If a net contains only passive terminals or input pins with no active source (e.g., a voltage source, stimulus, or output pin `opin.sym`), the ERC flags it as **undriven/floating**.

---

### 1. Triage & Localization (How to Find the Node)
Often, the error refers to an auto-generated net name (e.g., `#net1`) rather than a labeled net. Use these diagnostic tools to pinpoint the coordinate of the error:

*   **Locate by Tcl Command:** Open the Xschem command line console (key: `x`) and execute:
    ```tcl
    xschem instances_to_net {#net1}
    ```
    This returns the instances, pins, and exact schematic coordinates connected to that net (e.g., `{{m5} {b} {690} {-290}}` represents transistor `m5`, bulk pin `b`, at coordinates $x=690, y=-290$).
*   **Reveal Pin Nets:** Go to the top menu and select **View $\rightarrow$ Show/Hide $\rightarrow$ Enable "Show hidden texts"**. This displays the net names assigned to the physical pins on the schematic.

---

### 2. Common Causes & Concrete Fixes

#### Scenario A: Subcircuit/Block-Level Schematic Netlisting
*   **The Cause:** You are netlisting a sub-block schematic (e.g., an OTA or NAND gate) by itself. Because the block contains only `ipin` (input pins), there are no voltage sources (`VDC`, `VPULSE`) inside the block to "drive" them, triggering false-positive ERC errors.
*   **The Fix:** **Ignore it** during subcircuit design. The warning will disappear once the block's symbol (`.sym`) is instantiated and connected to voltage stimuli inside a top-level **testbench schematic (`.sch`)**.

#### Scenario B: Connecting Two Input Pins Directly (e.g., Clock or Control Buses)
*   **The Cause:** You connected an input pin of Block A directly to an input pin of Block B. Xschem treats this net as having two inputs and zero drivers, flagging it as undriven.
*   **The Fix:** Change the port direction of the net:
    1.  Edit the subcircuit symbol: Change the pin direction attribute from `input` to `inout` (set `dir=inout` in the pin's properties).
    2.  In the schematic: Replace the `ipin.sym` component with `iopin.sym`.

#### Scenario C: Floating Transistor Bulk (Substrate) Terminals
*   **The Cause:** In PDKs like SkyWater 130nm (`sky130`), transistors are 4-terminal devices. If you forget to tie the bulk pin (`B` or `substrate`) to VDD/VSS, Xschem registers the bulk node as a floating, undriven net.
*   **The Fix:** Connect the bulk terminal (`B`) of PMOS transistors to `VDD` (or the highest local potential) and NMOS transistors to `VSS`/`GND`. 

#### Scenario D: Netlisting from the `.sym` File Instead of the `.sch` File
*   **The Cause:** If you click the **Netlist** button while viewing/editing a symbol file (`inverter.sym`), Xschem will attempt to generate a netlist from the symbol's pin definition, resulting in generic undriven port errors.
*   **The Fix:** Always switch to the schematic view (`.sch`) before generating the netlist. 

#### Scenario E: False Flags from `spice_ignore=true` Voltage Sources
*   **The Cause:** If you have voltage sources in your testbench configured with the `spice_ignore=true` attribute, legacy versions of Xschem will ignore the source but still evaluate the attached net, causing a false "undriven node" flag.
*   **The Fix:** Update Xschem to version **$\ge$ 3.4.1**, which resolves this evaluation bug. Alternatively, temporarily set `spice_ignore=false` during ERC debugging.