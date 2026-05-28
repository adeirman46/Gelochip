# === chipster/setup_openlane.py ===
import os
import sys
import shutil
import subprocess
import logging

# --- Configuration ---
OPENLANE_VERSION = "version-2.1"
PDK = "gf180mcu"
PDK_ROOT = "~/.volare"

# --- Automatic Path Configuration ---
# All build files are placed in a clean directory in the user's home folder
# to avoid conflicts with existing Git repositories, which is a common
# source of errors with Nix.
HOME_DIR = os.path.expanduser('~')
INSTALL_DIR = os.path.join(HOME_DIR, "openlane_install_files")

def run_command(command, cwd=None, shell=False):
    """
    Runs a command and handles errors, printing the command for clarity.
    """
    cmd_str = command if shell else ' '.join(command)
    print(f"▶️  Running: {cmd_str}")
    try:
        # Using shell=True for commands that involve pipes or sudo redirection.
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            shell=shell,
            stdout=sys.stdout,
            stderr=sys.stderr
        )
    except FileNotFoundError:
        tool = command.split()[0] if shell else command[0]
        print(f"❌ Error: Command '{tool}' not found. Please ensure it is installed and in your PATH.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed with exit code {e.returncode}.")
        sys.exit(1)

def check_and_install_nix():
    """
    Checks if Nix is installed and, if not, installs it using the official script.
    This function handles the necessary administrative privileges.
    """
    if shutil.which("nix-env"):
        print("✅ Nix is already installed.")
        return

    print("--- ⚙️  Step 1: Installing Nix Package Manager ---")
    print("🔎 Nix not found. Starting installation...")
    print("🔔 This will require administrative privileges (sudo) and will prompt for your password.")

    # Install Nix using the official script. The `| bash` part requires shell=True.
    nix_install_cmd = "curl -L https://nixos.org/nix/install | bash -s -- --daemon --yes"
    run_command(nix_install_cmd, shell=True)

    # Enable the 'flakes' experimental feature by appending to the Nix config file.
    # This requires sudo privileges.
    flakes_config_line = "'extra-experimental-features = nix-command flakes'"
    nix_conf_path = "/etc/nix/nix.conf"
    config_cmd = f"echo {flakes_config_line} | sudo tee -a {nix_conf_path}"
    run_command(config_cmd, shell=True)

    # Restart the Nix daemon to apply the changes.
    kill_daemon_cmd = "sudo killall nix-daemon"
    run_command(kill_daemon_cmd, shell=True, check=False) # check=False because it may not be running

    print("✅ Nix installed and configured successfully.")
    print("🔔 You may need to restart your terminal for all changes to take effect.")
    # Add Nix to the PATH for the current session to ensure subsequent commands work.
    nix_profile_path = "/nix/var/nix/profiles/default/bin/"
    if nix_profile_path not in os.environ["PATH"]:
        os.environ["PATH"] = f"{nix_profile_path}:{os.getenv('PATH')}"


def setup_openlane_source():
    """
    Downloads and extracts the OpenLane source code into a clean directory.
    """
    print(f"--- ⬇️  Step 2: Downloading OpenLane source to '{INSTALL_DIR}' ---")
    if os.path.exists(INSTALL_DIR):
        print(f"🗑️ Removing existing installation directory...")
        shutil.rmtree(INSTALL_DIR)
    os.makedirs(INSTALL_DIR)

    version = "main" if OPENLANE_VERSION == "latest" else OPENLANE_VERSION
    url = f"https://github.com/efabless/openlane2/tarball/{version}"

    # Use a direct pipe for efficiency and to avoid intermediate files.
    download_command = f'curl -L "{url}" | tar -xzC {INSTALL_DIR} --strip-components 1'
    run_command(download_command, shell=True)
    print("✅ OpenLane source downloaded successfully.")

def install_dependencies():
    """
    Installs both Nix and Python dependencies for OpenLane.
    """
    # Install Nix dependencies
    print("\n--- 📦 Step 3: Installing Nix Dependencies ---")
    nix_command = "nix profile install .#colab-env --accept-flake-config"
    run_command(nix_command, cwd=INSTALL_DIR, shell=True)
    print("✅ Nix dependencies installed.")

    # Install Python dependencies
    print("\n--- 🐍 Step 4: Installing Python Dependencies ---")
    # Use sys.executable to ensure we use the correct pip for the current Python env.
    pip_command = f'"{sys.executable}" -m pip install .'
    run_command(pip_command, cwd=INSTALL_DIR, shell=True)
    print("✅ Python dependencies installed.")

def setup_volare_and_pdk():
    """
    Installs Volare and enables the specified PDK.
    """
    print(f"\n--- 🛠️  Step 5: Setting up Volare and enabling PDK '{PDK}' ---")
    
    # Temporarily add the OpenLane installation to Python's path
    # to import the 'volare' module that was just installed.
    sys.path.insert(0, INSTALL_DIR)
    try:
        import volare
        pdk_root_expanded = os.path.expanduser(PDK_ROOT)
        open_pdks_rev_path = os.path.join(INSTALL_DIR, "openlane", "open_pdks_rev")

        with open(open_pdks_rev_path, "r", encoding="utf8") as f:
            open_pdks_rev = f.read().strip()
        
        print(f"Enabling PDK with Open PDKs revision '{open_pdks_rev}'...")
        volare.enable(volare.get_volare_home(pdk_root_expanded), PDK, open_pdks_rev)
        print("✅ PDK enabled successfully.")

    except ImportError:
        print("❌ Critical Error: Failed to import 'volare' after installation.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ An error occurred during PDK setup: {e}")
        sys.exit(1)
    finally:
        # Clean up the path
        if INSTALL_DIR in sys.path:
            sys.path.remove(INSTALL_DIR)

def main():
    """
    Runs the entire setup process.
    """
    print("--- 🚀 Starting OpenLane 2 Local Setup ---")
    
    check_and_install_nix()
    setup_openlane_source()
    install_dependencies()
    setup_volare_and_pdk()

    # Final verification to confirm everything is working
    print("\n--- Verifying installation ---")
    sys.path.insert(0, INSTALL_DIR)
    try:
        import openlane
        print(f"✅ Success! OpenLane version {openlane.__version__} is installed.")
    except ImportError:
        print("❌ Verification failed. Could not import OpenLane.")
        sys.exit(1)
    finally:
        if INSTALL_DIR in sys.path:
            sys.path.remove(INSTALL_DIR)

    # Clear any default loggers to prevent conflicts
    logging.getLogger().handlers.clear()

    print("\n\n🎉 OpenLane setup is complete!")
    print(f"   Installation Location: {INSTALL_DIR}")
    print("   You may need to restart your terminal for all environment changes to take effect.")

if __name__ == "__main__":
    main()

# === chipster/data/analog_datasets/AMS_RF_Dataset/p31_SR Latch.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the SR Latch circuit
circuit = Circuit('SR Latch')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=250@u_ns,
    period=250@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delayed start
# Set input pulse
circuit.PulseVoltageSource('set', 'S', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=10@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=30@u_ns,
    period=100@u_ns
)

# Reset input pulse
circuit.PulseVoltageSource('reset', 'R', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=60@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=30@u_ns,
    period=100@u_ns
)

# Add input protection and parasitic capacitance
for node in ['S', 'R']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# NOR Gate 1 (Set side)
# PMOS transistors in series
circuit.MOSFET('M1', 'int1', 'S_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'Q', 'Qbar', 'int1', 'vdd_internal', model='PMOS')
circuit.C('CQ', 'Q', circuit.gnd, 0.1@u_pF)

# NMOS transistors in parallel
circuit.MOSFET('M3', 'Q', 'S_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M4', 'Q', 'Qbar', circuit.gnd, circuit.gnd, model='NMOS')

# NOR Gate 2 (Reset side)
# PMOS transistors in series
circuit.MOSFET('M5', 'int2', 'R_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'Qbar', 'Q', 'int2', 'vdd_internal', model='PMOS')
circuit.C('CQbar', 'Qbar', circuit.gnd, 0.1@u_pF)

# NMOS transistors in parallel
circuit.MOSFET('M7', 'Qbar', 'R_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M8', 'Qbar', 'Q', circuit.gnd, circuit.gnd, model='NMOS')

# Add weak pull-up/pull-down resistors for initial state
circuit.R('RQ_pu', 'Q', 'vdd_internal', 1@u_MΩ)
circuit.R('RQbar_pd', 'Qbar', circuit.gnd, 1@u_MΩ)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=200@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    vs = np.array([float(v) for v in analysis['S']])
    vr = np.array([float(v) for v in analysis['R']])
    vq = np.array([float(v) for v in analysis['Q']])
    vqbar = np.array([float(v) for v in analysis['Qbar']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, vs, label='Set', linestyle='--', color='blue')
    ax1.plot(time, vr, label='Reset', linestyle='--', color='red')
    ax1.grid(True)
    ax1.set_title('SR Latch - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs
    ax2.plot(time, vq, label='Q', color='green')
    ax2.plot(time, vqbar, label='Qbar', color='orange')
    ax2.grid(True)
    ax2.set_title('SR Latch - Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Analyze timing characteristics
    def analyze_timing(time, vs, vr, vq, vqbar, vth=1.65):
        """Calculate propagation delays and verify functionality"""
        def find_edges(time, signal, rising=True):
            edges = []
            for i in range(1, len(signal)):
                if rising and signal[i-1] < vth < signal[i]:
                    edges.append(i)
                elif not rising and signal[i-1] > vth > signal[i]:
                    edges.append(i)
            return edges

        # Find rising and falling edges
        s_edges = find_edges(time, vs, rising=True)
        r_edges = find_edges(time, vr, rising=True)
        q_edges_r = find_edges(time, vq, rising=True)
        q_edges_f = find_edges(time, vq, rising=False)

        # Calculate delays
        set_delays = []
        reset_delays = []

        for s_edge in s_edges:
            for q_edge in q_edges_r:
                if q_edge > s_edge:
                    delay = time[q_edge] - time[s_edge]
                    set_delays.append(delay)
                    break

        for r_edge in r_edges:
            for q_edge in q_edges_f:
                if q_edge > r_edge:
                    delay = time[q_edge] - time[r_edge]
                    reset_delays.append(delay)
                    break

        if set_delays:
            print(f"Average Set-to-Q delay: {np.mean(set_delays):.2e} seconds")
        if reset_delays:
            print(f"Average Reset-to-Q delay: {np.mean(reset_delays):.2e} seconds")

    analyze_timing(time, vs, vr, vq, vqbar)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p32_CMOS Buffer.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS Buffer circuit
circuit = Circuit('CMOS Buffer')

# Define power supply
Vdd = 5
circuit.V('dd', 'vdd', circuit.gnd, Vdd@u_V)

# Define input voltage source
circuit.PulseVoltageSource('in', 'input', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=Vdd@u_V,
    delay_time=0@u_ns,
    rise_time=5@u_ns,
    fall_time=5@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Add noise to the input
circuit.SinusoidalVoltageSource('noise', 'input_noisy', 'input',
    amplitude=0.5@u_V,
    frequency=50@u_MHz
)

# First Inverter Stage
circuit.MOSFET('M1', 'intermediate', 'input_noisy', 'vdd', 'vdd', model='PMOS1')
circuit.MOSFET('M2', 'intermediate', 'input_noisy', circuit.gnd, circuit.gnd, model='NMOS1')

# Second Inverter Stage
circuit.MOSFET('M3', 'output', 'intermediate', 'vdd', 'vdd', model='PMOS2')
circuit.MOSFET('M4', 'output', 'intermediate', circuit.gnd, circuit.gnd, model='NMOS2')

# Define MOSFET models - first stage
circuit.model('NMOS1', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=10e-6,
    l=1e-6
)

circuit.model('PMOS1', 'pmos',
    level=1,
    kp=60e-6,
    vto=-0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=20e-6,
    l=1e-6
)

# Define MOSFET models - second stage
circuit.model('NMOS2', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=20e-6,
    l=1e-6
)

circuit.model('PMOS2', 'pmos',
    level=1,
    kp=60e-6,
    vto=-0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=40e-6,
    l=1e-6
)

# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=160@u_ns)
    
    # Convert analysis results to numpy arrays for easier processing
    time = np.array([float(t) for t in analysis.time])
    input_signal = np.array([float(v) for v in analysis['input']])
    input_noisy = np.array([float(v) for v in analysis['input_noisy']])
    intermediate = np.array([float(v) for v in analysis['intermediate']])
    output = np.array([float(v) for v in analysis['output']])
    
    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # Plot input signals
    ax1.plot(time, input_signal, label='Clean Input', linestyle='--', color='blue')
    ax1.plot(time, input_noisy, label='Noisy Input', color='red', alpha=0.7)
    ax1.grid(True)
    ax1.set_title('CMOS Buffer - Input Signals')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-1, 6)
    
    # Plot intermediate and output signals
    ax2.plot(time, intermediate, label='Intermediate', linestyle='--', color='green')
    ax2.plot(time, output, label='Buffered Output', color='purple')
    ax2.grid(True)
    ax2.set_title('CMOS Buffer - Internal Node and Output')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-1, 6)
    
    plt.tight_layout()
    plt.show()

    # Analyze buffer characteristics
    def analyze_buffer(time, input_signal, output, vdd=5.0):
        v_low = 0.1 * vdd
        v_high = 0.9 * vdd
        
        def find_crossings(signal, threshold, rising=True):
            crossings = []
            for i in range(1, len(signal)):
                if rising:
                    if signal[i-1] < threshold < signal[i]:
                        crossings.append(i)
                else:
                    if signal[i-1] > threshold > signal[i]:
                        crossings.append(i)
            return crossings
        
        # Find rising and falling transitions
        input_rise = find_crossings(input_signal, v_high, rising=True)
        input_fall = find_crossings(input_signal, v_low, rising=False)
        output_rise = find_crossings(output, v_high, rising=True)
        output_fall = find_crossings(output, v_low, rising=False)
        
        # Calculate delays
        rise_delays = []
        fall_delays = []
        
        for in_idx, out_idx in zip(input_rise, output_rise):
            delay = time[out_idx] - time[in_idx]
            rise_delays.append(delay)
            
        for in_idx, out_idx in zip(input_fall, output_fall):
            delay = time[out_idx] - time[in_idx]
            fall_delays.append(delay)
        
        # Print results
        if rise_delays:
            print(f"Average rise propagation delay: {np.mean(rise_delays):.2e} seconds")
        if fall_delays:
            print(f"Average fall propagation delay: {np.mean(fall_delays):.2e} seconds")
        
        # Calculate noise reduction
        input_noise = np.std(input_signal)
        output_noise = np.std(output)
        noise_reduction = (1 - output_noise/input_noise) * 100
        print(f"Noise reduction: {noise_reduction:.1f}%")
    
    analyze_buffer(time, input_noisy, output)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")

print(circuit)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p17_Cascode Current Mirror.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Cascode Current Mirror')
# NMOS model (nominal)
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.7)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Reference current source: from Vdd to Iref
circuit.I('ref', 'Vdd', 'Iref', 100@u_uA)
# M1: Bottom input NMOS (diode-connected)
circuit.MOSFET('1', 'N1', 'N1', circuit.gnd, circuit.gnd, model='nmos_model', w=20e-6, l=1e-6)
# M2: Top input NMOS (cascode)
circuit.MOSFET('2', 'Iref', 'Iref', 'N1', 'N1', model='nmos_model', w=20e-6, l=1e-6)
# M3: Bottom output NMOS (mirror)
circuit.MOSFET('3', 'N3', 'N1', circuit.gnd, circuit.gnd, model='nmos_model', w=20e-6, l=1e-6)
# M4: Top output NMOS (cascode)
circuit.MOSFET('4', 'Iout', 'Iref', 'N3', 'N3', model='nmos_model', w=20e-6, l=1e-6)
# Output load resistor
circuit.R('1', 'Iout', 'Vdd', 10@u_kΩ)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p17_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

load_resistances = [100, 300, 500, 750, 1000]
currents = []

import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Resistor):
        resistor_name = element.name
        node1, node2 = element.nodes
        break


resistor = circuit[resistor_name]
for r_load in load_resistances:
    resistor.resistance = r_load
    analysis = simulator.operating_point()
    if str(node2) == "0":
        current = float(analysis[str(node1)][0]) / r_load
    elif str(node1) == "0":
        current = - float(analysis[str(node2)][0]) / r_load
    else:
        current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load
    currents.append(current)

for r_load, current in zip(load_resistances, currents):
    print(f"Load: {r_load}, Current: {current}")

tolerance = 1e-6

current_variations = []
for i in range(4):
    current_variations.append(abs(currents[i+1] - currents[i]))

import sys
if min(current_variations) < tolerance and min(currents) > 1e-5:
    pass
    # print("The circuit functions correctly as a constant current source within the given tolerance.")
    # sys.exit(0)
else:
    print("The circuit does not function correctly as a current source.")
    sys.exit(2)

iin_name = None
for element in circuit.elements:
    if "ref" in element.name.lower(): # and element.name.lower().startswith("v"):
        iin_name = element.name

# print("iin_name", iin_name)
if iin_name is None:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


circuit.element(iin_name).dc_value = "0.00155"

# print(str(circuit))
simulator = circuit.simulator()
resistor.resistance = 500
analysis = simulator.operating_point()
if str(node2) == "0":
    current = float(analysis[str(node1)][0]) / r_load
elif str(node1) == "0":
    current = - float(analysis[str(node2)][0]) / r_load
else:
    current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load

# print("current", current)
# print("currents", currents)
# print("abs(current - currents[2])", abs(current - currents[2]))
if abs(current - currents[2]) < 1e-6:
    print("The circuit does not as a current source because it cannot replicate the Iref current.")
    sys.exit(2)
else:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


# === chipster/data/analog_datasets/AMS_RF_Dataset/p8_NMOS Constant Current Source with Resistor Load.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Create a new circuit
circuit = Circuit('NMOS Constant Current Source with Resistor Load')
# Define the NMOS model
circuit.model('nmos', 'nmos', level=1, vto=0.5, kp=200e-6)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V Vdd
# Bias voltage for gate
circuit.V('bias', 'Vbias', circuit.gnd, 1.0)  # Bias voltage above Vth to turn on NMOS
# NMOS transistor: Drain connected to Vout, Gate to Vbias, Source to ground
circuit.MOSFET('M1', 'Vout', 'Vbias', circuit.gnd, circuit.gnd, model='nmos', w=10e-6, l=1e-6)
# Resistor R from Vout to Vdd
circuit.R('Rload', 'Vout', 'Vdd', 10e3)  # 10kΩ resistor
# The circuit is now ready for simulation
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p8_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

load_resistances = [100, 300, 500, 750, 1000]
currents = []

import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Resistor):
        resistor_name = element.name
        node1, node2 = element.nodes
        break


resistor = circuit[resistor_name]
for r_load in load_resistances:
    resistor.resistance = r_load
    analysis = simulator.operating_point()
    if str(node2) == "0":
        current = float(analysis[str(node1)][0]) / r_load
    elif str(node1) == "0":
        current = - float(analysis[str(node2)][0]) / r_load
    else:
        current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load
    currents.append(current)

for r_load, current in zip(load_resistances, currents):
    print(f"Load: {r_load}, Current: {current}")

tolerance = 1e-6

current_variations = []
for i in range(4):
    current_variations.append(abs(currents[i+1] - currents[i]))

import sys
if min(current_variations) < tolerance and min(currents) > 1e-5:
    pass
    # print("The circuit functions correctly as a constant current source within the given tolerance.")
    # sys.exit(0)
else:
    print("The circuit does not function correctly as a current source.")
    sys.exit(2)

iin_name = None
for element in circuit.elements:
    if "ref" in element.name.lower(): # and element.name.lower().startswith("v"):
        iin_name = element.name

# print("iin_name", iin_name)
if iin_name is None:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


circuit.element(iin_name).dc_value = "0.00155"

# print(str(circuit))
simulator = circuit.simulator()
resistor.resistance = 500
analysis = simulator.operating_point()
if str(node2) == "0":
    current = float(analysis[str(node1)][0]) / r_load
elif str(node1) == "0":
    current = - float(analysis[str(node2)][0]) / r_load
else:
    current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load

# print("current", current)
# print("currents", currents)
# print("abs(current - currents[2])", abs(current - currents[2]))
if abs(current - currents[2]) < 1e-6:
    print("The circuit does not as a current source because it cannot replicate the Iref current.")
    sys.exit(2)
else:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


# === chipster/data/analog_datasets/AMS_RF_Dataset/p41_4:1 CMOS Multiplexer.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Create a new circuit
circuit = Circuit('4:1 CMOS Multiplexer')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)

# Define input signals as pulse sources with different patterns
circuit.PulseVoltageSource('in0', 'in0_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=400@u_ns, period=800@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('in1', 'in1_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=200@u_ns, period=400@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('in2', 'in2_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=100@u_ns, period=200@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('in3', 'in3_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=50@u_ns, period=100@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)

# Define select signals (S0 and S1) with slower transitions
circuit.PulseVoltageSource('S0', 'S0_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=1000@u_ns, period=2000@u_ns,)
circuit.PulseVoltageSource('S1', 'S1_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=2000@u_ns, period=4000@u_ns,)

# Define MOSFET models
circuit.model('NMOS', 'nmos', 
              level=1, kp=120e-6, vto=0.7, lambda_=0.02, 
              w=10e-6, l=1e-6)
circuit.model('PMOS', 'pmos', 
              level=1, kp=60e-6, vto=-0.7, lambda_=0.02, 
              w=20e-6, l=1e-6)

# Generate complementary select signals using inverters
# Inverter for S0
circuit.MOSFET(1, 'S0_bar', 'S0_node', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET(2, 'S0_bar', 'S0_node', 'Vdd', 'Vdd', model='PMOS')

# Inverter for S1
circuit.MOSFET(3, 'S1_bar', 'S1_node', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET(4, 'S1_bar', 'S1_node', 'Vdd', 'Vdd', model='PMOS')

# Implement the 4:1 multiplexer using a hierarchical approach
# First level: Two 2:1 multiplexers controlled by S0
# Second level: 2:1 multiplexer controlled by S1

# First 2:1 mux (inputs 0 and 1, controlled by S0)
circuit.MOSFET(5, 'in0_node', 'S0_bar', 'mux1_out', circuit.gnd, model='NMOS')
circuit.MOSFET(6, 'in0_node', 'S0_node', 'mux1_out', 'Vdd', model='PMOS')
circuit.MOSFET(7, 'in1_node', 'S0_node', 'mux1_out', circuit.gnd, model='NMOS')
circuit.MOSFET(8, 'in1_node', 'S0_bar', 'mux1_out', 'Vdd', model='PMOS')

# Second 2:1 mux (inputs 2 and 3, controlled by S0)
circuit.MOSFET(9, 'in2_node', 'S0_bar', 'mux2_out', circuit.gnd, model='NMOS')
circuit.MOSFET(10, 'in2_node', 'S0_node', 'mux2_out', 'Vdd', model='PMOS')
circuit.MOSFET(11, 'in3_node', 'S0_node', 'mux2_out', circuit.gnd, model='NMOS')
circuit.MOSFET(12, 'in3_node', 'S0_bar', 'mux2_out', 'Vdd', model='PMOS')

# Final 2:1 mux (outputs of first two muxes, controlled by S1)
circuit.MOSFET(13, 'mux1_out', 'S1_bar', 'output', circuit.gnd, model='NMOS')
circuit.MOSFET(14, 'mux1_out', 'S1_node', 'output', 'Vdd', model='PMOS')
circuit.MOSFET(15, 'mux2_out', 'S1_node', 'output', circuit.gnd, model='NMOS')
circuit.MOSFET(16, 'mux2_out', 'S1_bar', 'output', 'Vdd', model='PMOS')

# Add a load resistor and capacitor at the output
circuit.R('load', 'output', circuit.gnd, 10@u_kΩ)
circuit.C('out_cap', 'output', circuit.gnd, 100e-15@u_F)

# Setup simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Perform transient analysis with a longer duration to see all combinations
analysis = simulator.transient(step_time=10@u_ns, end_time=4000@u_ns)

# Convert analysis time to nanoseconds for easier interpretation
time_ns = np.array(analysis.time) * 1e9

# Plot input signals in separate figures
plt.figure(figsize=(10, 8))

plt.subplot(4, 1, 1)
plt.plot(time_ns, analysis['in0_node'])
plt.title('Input 0 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.subplot(4, 1, 2)
plt.plot(time_ns, analysis['in1_node'])
plt.title('Input 1 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.subplot(4, 1, 3)
plt.plot(time_ns, analysis['in2_node'])
plt.title('Input 2 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.subplot(4, 1, 4)
plt.plot(time_ns, analysis['in3_node'])
plt.title('Input 3 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.tight_layout()
plt.show()

# Plot select signals
plt.figure(figsize=(10, 6))
plt.plot(time_ns, analysis['S0_node'], label='Select S0')
plt.plot(time_ns, analysis['S1_node'], label='Select S1')
plt.title('Select Signals')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid()
plt.show()

# Plot output signal
plt.figure(figsize=(10, 6))
plt.plot(time_ns, analysis['output'], label='Output')
plt.title('Multiplexer Output')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid()
plt.show()

# === chipster/data/analog_datasets/AMS_RF_Dataset/p42_Bandgap Reference Circuit.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create a simpler, more robust bandgap reference circuit
circuit = Circuit('Bandgap Reference Circuit')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 3.3@u_V)

# Define bipolar transistors with different areas (8:1 ratio)
circuit.BJT('Q1', 'Q1_collector', 'Q1_base', circuit.gnd, model='NPN', area=1)
circuit.BJT('Q2', 'Q2_collector', 'Q2_base', circuit.gnd, model='NPN', area=8)

# Add small resistors to collectors for better convergence
circuit.R('R1', 'Vdd', 'Q1_collector', 10@u_kΩ)
circuit.R('R2', 'Vdd', 'Q2_collector', 10@u_kΩ)

# Add base resistors
circuit.R('R3', 'Q1_base', 'Q1_collector', 5@u_kΩ)
circuit.R('R4', 'Q2_base', 'Q2_collector', 5@u_kΩ)

# Add a simple current mirror to bias the transistors
circuit.BJT('Q3', 'Q3_collector', 'Q3_collector', circuit.gnd, model='NPN', area=1)  # Diode-connected
circuit.R('R5', 'Vdd', 'Q3_collector', 10@u_kΩ)

# Connect the current mirror to the bandgap core
circuit.R('R6', 'Q3_collector', 'Q1_base', 5@u_kΩ)
circuit.R('R7', 'Q3_collector', 'Q2_base', 5@u_kΩ)

# Add a PTAT resistor between the collectors
circuit.R('Rptat', 'Q1_collector', 'Q2_collector', 2@u_kΩ)

# Output stage - simple voltage follower
circuit.BJT('Q4', 'Vout', 'Q2_collector', circuit.gnd, model='NPN', area=1)
circuit.R('Rout', 'Vdd', 'Vout', 5@u_kΩ)

# Define device models with proper parameters
circuit.model('NPN', 'npn',
              is_=1e-16,
              bf=100,
              br=1,
              vaf=50,
              ikf=0.1,
              ise=1e-15,
              ne=1.5,
              rc=10)

# Setup simulation with convergence helpers
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(
    reltol=1e-3,
    abstol=1e-9,
    vntol=1e-6,
    gmin=1e-12,
    method='gear',
    itl1=1000,
    itl2=1000,
    itl4=1000,
    srcsteps=100,
    pivtol=1e-12,
    pivrel=1e-3
)

print("Testing Bandgap Reference Circuit...")

# Operating point analysis
try:
    analysis_op = simulator.operating_point()
    vout = float(analysis_op['Vout'])
    print(f"Operating Point Analysis: Vout = {vout:.6f} V")
    
    # Test if circuit is working
    if 1.1 <= vout <= 1.3:  # Typical bandgap voltage range
        print("✓ PASS: Circuit is generating a proper reference voltage")
    else:
        print("✗ FAIL: Circuit is not generating a proper reference voltage")
        
except Exception as e:
    print(f"✗ FAIL: Operating point analysis failed: {e}")
    # Try a DC analysis instead
    try:
        analysis_dc = simulator.dc(Vdd=slice(0, 3.3, 0.1))
        vout = float(analysis_dc['Vout'][-1])  # Get the last value
        print(f"DC Analysis: Vout at 3.3V = {vout:.6f} V")
    except Exception as e2:
        print(f"DC analysis also failed: {e2}")

# DC analysis - temperature sweep
print("\nTemperature Stability Test:")
temperatures = np.linspace(-40, 125, 10)
vout_values = []
success_count = 0

for temp in temperatures:
    try:
        # Create a new simulator for each temperature
        temp_simulator = circuit.simulator(temperature=temp, nominal_temperature=25)
        temp_simulator.options(
            reltol=1e-3,
            abstol=1e-9,
            vntol=1e-6,
            gmin=1e-12,
            itl1=1000,
            itl2=1000,
            itl4=1000
        )
        analysis = temp_simulator.operating_point()
        vout_val = float(analysis['Vout'])
        vout_values.append(vout_val)
        print(f"Temperature {temp}°C: Vout = {vout_val:.6f} V")
        success_count += 1
    except Exception as e:
        print(f"Temperature {temp}°C: Failed - {e}")
        vout_values.append(np.nan)

# Plot the temperature stability results
if success_count > 0:
    plt.figure(figsize=(10, 6))
    
    # Filter out failed simulations
    valid_temps = []
    valid_vouts = []
    for i, (temp, vout) in enumerate(zip(temperatures, vout_values)):
        if not np.isnan(vout):
            valid_temps.append(temp)
            valid_vouts.append(vout)
    
    if len(valid_temps) > 1:
        plt.plot(valid_temps, valid_vouts, 'o-', linewidth=2, markersize=8)
        plt.xlabel('Temperature (°C)')
        plt.ylabel('Output Voltage (V)')
        plt.title('Bandgap Reference Voltage vs Temperature')
        plt.grid(True, alpha=0.3)
        
        # Add voltage range indicators
        if len(valid_vouts) > 0:
            avg_voltage = np.mean(valid_vouts)
            plt.axhline(y=avg_voltage, color='r', linestyle='--', alpha=0.7, label=f'Average: {avg_voltage:.3f} V')
            plt.legend()
        
        plt.tight_layout()
        plt.savefig('bandgap_temperature_stability.png', dpi=150)
        plt.show()
        
        # Calculate and display statistics
        vout_range = max(valid_vouts) - min(valid_vouts)
        vout_std = np.std(valid_vouts)
        print(f"\nTemperature Stability Statistics:")
        print(f"  Voltage range: {vout_range*1000:.2f} mV")
        print(f"  Standard deviation: {vout_std*1000:.2f} mV")
        
        # Test temperature stability
        if vout_range < 0.1:  # Less than 100mV variation
            print(f"✓ PASS: Good temperature stability (ΔV = {vout_range*1000:.2f} mV)")
        else:
            print(f"✗ FAIL: Poor temperature stability (ΔV = {vout_range*1000:.2f} mV)")
    else:
        print("✗ FAIL: Insufficient data for plotting")
else:
    print("✗ FAIL: Insufficient data for temperature stability test")

print("\nBandgap Reference Test Complete")

# === chipster/data/analog_datasets/AMS_RF_Dataset/p30_CMOS NOR Gate.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Library import SpiceLibrary
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS NOR Gate circuit
circuit = Circuit('CMOS NOR Gate')

# Define power supply
circuit.V('dd', 'vdd', circuit.gnd, 5@u_V)

# Define input voltage sources
# Input A: Full period pulse
circuit.PulseVoltageSource('inA', 'inputA', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B: Half period pulse
circuit.PulseVoltageSource('inB', 'inputB', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Define PMOS transistors in series
# PMOS1: Connected to inputA and VDD
circuit.MOSFET('M1', 'intermediate', 'inputA', 'vdd', 'vdd', model='PMOS')

# PMOS2: Connected to inputB and intermediate node
circuit.MOSFET('M2', 'output', 'inputB', 'intermediate', 'vdd', model='PMOS')

# Define NMOS transistors in parallel
# NMOS1: Connected to inputA
circuit.MOSFET('M3', 'output', 'inputA', circuit.gnd, circuit.gnd, model='NMOS')

# NMOS2: Connected to inputB
circuit.MOSFET('M4', 'output', 'inputB', circuit.gnd, circuit.gnd, model='NMOS')

# Define MOSFET models
# PMOS width is increased to 40µm (4x NMOS) because they're in series
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,    # Transconductance parameter
    vto=0.7,      # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=10e-6,      # Channel width
    l=1e-6        # Channel length
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=60e-6,     # Transconductance parameter
    vto=-0.7,     # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=40e-6,      # Channel width (4x NMOS width due to series connection)
    l=1e-6        # Channel length
)

# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Add simulation options for better convergence
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=160@u_ns)

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Plot inputs on first subplot
    ax1.plot(analysis.time, analysis['inputA'], 
             label='Input A', linestyle='--', color='blue')
    ax1.plot(analysis.time, analysis['inputB'], 
             label='Input B', linestyle='--', color='green')
    ax1.grid(True)
    ax1.set_title('CMOS NOR Gate - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 5.5)
    
    # Plot output on second subplot
    ax2.plot(analysis.time, analysis['output'], 
             label='Output', color='red')
    ax2.grid(True)
    ax2.set_title('CMOS NOR Gate - Output')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 5.5)
    
    # Add truth table annotation
    truth_table = """
    NOR Truth Table
    A B | Out
    0 0 | 1
    0 1 | 0
    1 0 | 0
    1 1 | 0
    """
    plt.figtext(1.02, 0.5, truth_table, fontfamily='monospace')
    
    # Adjust layout and display
    plt.tight_layout()
    plt.show()

    # Calculate and display timing characteristics
    def analyze_timing(analysis):
        """Calculate rise time, fall time, and propagation delay"""
        vdd = 5.0
        v_low = 0.1 * vdd
        v_high = 0.9 * vdd
        
        # Convert to numpy arrays to avoid UnitValue comparison issues
        output = np.array(analysis['output'])
        time = np.array(analysis.time)
        
        # Find rising and falling edges
        rising_edges = []
        falling_edges = []
        
        for i in range(1, len(output)):
            if output[i-1] < v_low and output[i] > v_high:
                rising_edges.append(i)
            elif output[i-1] > v_high and output[i] < v_low:
                falling_edges.append(i)
        
        # Calculate average rise and fall times
        rise_times = []
        fall_times = []
        
        for edge in rising_edges:
            rise_time = time[edge] - time[edge-1]
            rise_times.append(rise_time)
            
        for edge in falling_edges:
            fall_time = time[edge] - time[edge-1]
            fall_times.append(fall_time)
            
        if rise_times:
            print(f"Average rise time: {np.mean(rise_times):.2e} seconds")
        if fall_times:
            print(f"Average fall time: {np.mean(fall_times):.2e} seconds")
    
    analyze_timing(analysis)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")

# === chipster/data/analog_datasets/AMS_RF_Dataset/p10_Passive Low-Pass Filter.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive Low-Pass Filter')
# DC voltage source to Vin (input node)
circuit.V('in', 'Vin', circuit.gnd, 1.0@u_V)
# Resistor R1 between Vin and Vout
circuit.R('1', 'Vin', 'Vout', 10@u_kΩ)
# Capacitor C1 between Vout and ground
circuit.C('1', 'Vout', circuit.gnd, 10@u_nF)
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)


node = 'Vout'
has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)
vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac))
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of Low-Pass Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)


plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Point')
plt.legend()

plt.tight_layout()
plt.savefig('p10_waveform.png')

low_freq_gain = gain_db[0]
print(f"Gain at lowest frequency ({frequencies[0]:.2f} Hz): {low_freq_gain:.2f} dB")

high_freq_gain = gain_db[-1]
print(f"Gain at highest frequency ({frequencies[-1]:.2f} Hz): {high_freq_gain:.2f} dB")
high_freq_attenuation = low_freq_gain - high_freq_gain
print(f"High frequency attenuation: {high_freq_attenuation:.2f} dB")

idx_3db = np.argmin(np.abs(gain_db - (low_freq_gain-3)))
cutoff_freq = frequencies[idx_3db]
print(f"Approximate -3dB cutoff frequency: {cutoff_freq:.2f} Hz")

window_size = min(11, len(gain_db) // 20)
if window_size % 2 == 0:
    window_size += 1
    
if window_size > 2:
    from scipy.signal import savgol_filter
    smoothed_gain = savgol_filter(gain_db, window_size, 1)
else:
    smoothed_gain = gain_db
    
diff_gain = np.diff(smoothed_gain)
non_monotonic_points = np.sum(diff_gain > 0.5)

if non_monotonic_points > 0:
    monotonic_percentage = 100 * (1 - non_monotonic_points / len(diff_gain))
    print(f"Warning: Gain is not strictly monotonically decreasing.")
    print(f"Monotonicity: {monotonic_percentage:.1f}% of frequency points")
    if monotonic_percentage < 90:
        print("This may not be a well-behaved low-pass filter.")
else:
    print("Filter response is monotonically decreasing with frequency, as expected.")

if high_freq_attenuation > 2 and (non_monotonic_points == 0 or monotonic_percentage >= 90):
    print("The circuit exhibits proper low-pass filter characteristics.")
    sys.exit(0)
else:
    print("The circuit does not show expected low-pass filter characteristics.")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p36_D Flip-Flop.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the D Flip-Flop circuit
circuit = Circuit('D Flip-Flop')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=250@u_ns,
    period=250@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delayed start
# Clock signal
circuit.PulseVoltageSource('clk', 'clock', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=2@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Data input
circuit.PulseVoltageSource('din', 'D', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=5@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=30@u_ns,
    period=60@u_ns
)

# Add input protection and parasitic capacitance
for node in ['clock', 'D']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# Create clock inverter
circuit.MOSFET('M1', 'clock_inv', 'clock_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'clock_inv', 'clock_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('Cclk_inv', 'clock_inv', circuit.gnd, 0.1@u_pF)

# Master stage
# Input inverter
circuit.MOSFET('M3', 'D_inv', 'D_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M4', 'D_inv', 'D_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('CD_inv', 'D_inv', circuit.gnd, 0.1@u_pF)

# Master latch
circuit.MOSFET('M5', 'master_int', 'D_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'master_int', 'clock_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M7', 'master_out', 'master_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M8', 'master_out', 'master_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('Cmaster', 'master_out', circuit.gnd, 0.1@u_pF)

# Slave stage
circuit.MOSFET('M9', 'slave_int', 'master_out', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M10', 'slave_int', 'clock_inv', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M11', 'Q', 'slave_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M12', 'Q', 'slave_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('CQ', 'Q', circuit.gnd, 0.1@u_pF)

# Output inverter for Q_bar
circuit.MOSFET('M13', 'Q_bar', 'Q', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M14', 'Q_bar', 'Q', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('CQbar', 'Q_bar', circuit.gnd, 0.1@u_pF)

# Add weak pull-up/pull-down for initialization
circuit.R('Rpd_master', 'master_int', circuit.gnd, 1@u_MΩ)
circuit.R('Rpd_slave', 'slave_int', circuit.gnd, 1@u_MΩ)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=200@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    vclk = np.array([float(v) for v in analysis['clock']])
    vd = np.array([float(v) for v in analysis['D']])
    vq = np.array([float(v) for v in analysis['Q']])
    vqbar = np.array([float(v) for v in analysis['Q_bar']])
    vmaster = np.array([float(v) for v in analysis['master_out']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, vclk, label='Clock', color='blue')
    ax1.plot(time, vd, label='D', linestyle='--', color='red')
    ax1.grid(True)
    ax1.set_title('D Flip-Flop - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs and internal nodes
    ax2.plot(time, vmaster, label='Master', color='green', alpha=0.5)
    ax2.plot(time, vq, label='Q', color='purple')
    ax2.plot(time, vqbar, label='Q_bar', color='orange')
    ax2.grid(True)
    ax2.set_title('D Flip-Flop - Internal Nodes and Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Analyze timing characteristics
    def analyze_timing(time, vclk, vd, vq, vth=1.65):
        """Calculate setup time, hold time, and clock-to-Q delay"""
        def find_edges(time, signal, rising=True):
            edges = []
            for i in range(1, len(signal)):
                if rising and signal[i-1] < vth < signal[i]:
                    edges.append(i)
                elif not rising and signal[i-1] > vth > signal[i]:
                    edges.append(i)
            return edges

        # Find edges
        clk_edges = find_edges(time, vclk, rising=True)
        d_edges = find_edges(time, vd)
        q_edges = find_edges(time, vq)

        # Calculate delays
        clk_q_delays = []
        setup_times = []
        hold_times = []

        for clk_edge in clk_edges:
            # Clock-to-Q delay
            for q_edge in q_edges:
                if q_edge > clk_edge:
                    delay = time[q_edge] - time[clk_edge]
                    if delay < 10e-9:  # Reasonable delay window
                        clk_q_delays.append(delay)
                    break

            # Setup and hold times
            for d_edge in d_edges:
                if abs(time[d_edge] - time[clk_edge]) < 10e-9:
                    if d_edge < clk_edge:
                        setup_times.append(time[clk_edge] - time[d_edge])
                    else:
                        hold_times.append(time[d_edge] - time[clk_edge])

        if clk_q_delays:
            print(f"Average Clock-to-Q delay: {np.mean(clk_q_delays):.2e} seconds")
        if setup_times:
            print(f"Average setup time: {np.mean(setup_times):.2e} seconds")
        if hold_times:
            print(f"Average hold time: {np.mean(hold_times):.2e} seconds")

    analyze_timing(time, vclk, vd, vq)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p43_3-bit Flash ADC.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory
import matplotlib.pyplot as plt
import numpy as np

class Opamp(SubCircuitFactory):
    NAME = ('Opamp')
    NODES = ('Vinp', 'Vinn', 'Vout')
    def __init__(self):
        super().__init__()
        # Define the MOSFET models with higher gain for sharper transitions
        self.model('nmos_model', 'nmos', level=1, kp=200e-6, vto=0.5, lambda_=0.01)
        self.model('pmos_model', 'pmos', level=1, kp=100e-6, vto=-0.5, lambda_=0.01)
        
        # Internal power supply and bias
        self.V('dd_int', 'Vdd_int', self.gnd, 5.0)
        self.V('bias', 'Vbias', self.gnd, 1.5)
        
        # Differential pair with larger sizes for higher transconductance
        self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=100e-6, l=0.5e-6)
        self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=100e-6, l=0.5e-6)
        
        # Tail current source with larger width for more current
        self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=200e-6, l=1e-6)
        
        # Current mirror load with higher current capability
        self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd_int', 'Vdd_int', model='pmos_model', w=200e-6, l=0.5e-6)
        self.MOSFET('5', 'Vout', 'Voutp', 'Vdd_int', 'Vdd_int', model='pmos_model', w=200e-6, l=0.5e-6)

# Create a 3-bit Flash ADC circuit
circuit = Circuit('3-bit Flash ADC')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)

# Create precision resistor ladder for reference voltages
# Using smaller, matched resistors for better accuracy
r_ladder = 500@u_Ω  

# Create voltage divider chain from top to bottom
# This creates references at: 4.375V, 3.75V, 3.125V, 2.5V, 1.875V, 1.25V, 0.625V
circuit.R('R_top', 'Vdd', 'Vref7', r_ladder)      # Top resistor
circuit.R('R6', 'Vref7', 'Vref6', r_ladder)       # 4.375V to 3.75V
circuit.R('R5', 'Vref6', 'Vref5', r_ladder)       # 3.75V to 3.125V  
circuit.R('R4', 'Vref5', 'Vref4', r_ladder)       # 3.125V to 2.5V
circuit.R('R3', 'Vref4', 'Vref3', r_ladder)       # 2.5V to 1.875V
circuit.R('R2', 'Vref3', 'Vref2', r_ladder)       # 1.875V to 1.25V
circuit.R('R1', 'Vref2', 'Vref1', r_ladder)       # 1.25V to 0.625V
circuit.R('R_bot', 'Vref1', circuit.gnd, r_ladder) # Bottom resistor

# Add buffer resistors to prevent loading of reference voltages
for i in range(1, 8):
    circuit.R(f'Rbuf{i}', f'Vref{i}', f'Vref{i}_buf', 1@u_Ω)

# Declare the opamp subcircuit
circuit.subcircuit(Opamp())

# Create 7 comparators using the op-amp
# For proper Flash ADC operation:
# - Input goes to non-inverting input (+)
# - Reference goes to inverting input (-)
# - When Vin > Vref, output goes HIGH
# - When Vin < Vref, output goes LOW

for i in range(1, 8):
    # Create comparator: Vin(+) compared with Vref_i(-)
    circuit.X(f'cmp{i}', 'Opamp', 'Vin', f'Vref{i}_buf', f'Comp_out_{i}')
    
    # Add pull-up resistors to ensure proper HIGH levels
    circuit.R(f'Rpull{i}', f'Comp_out_{i}', 'Vdd', 10@u_kΩ)

# Input voltage source
circuit.V('input', 'Vin', circuit.gnd, 2.5@u_V)

# Setup simulation with improved convergence
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(
    reltol=1e-4,
    abstol=1e-10,
    vntol=1e-6,
    method='gear',
    maxiter=200,
    gmin=1e-15,
    pivrel=1e-3
)

try:
    # Perform DC analysis with finer resolution
    analysis = simulator.dc(Vinput=slice(0, 5, 0.02))
    
    # Extract results
    input_voltage = np.array(analysis.Vin)
    
    # Print actual reference voltages
    print("Actual Reference Voltages:")
    print("=" * 30)
    ref_voltages = {}
    for i in range(1, 8):
        vref_actual = float(analysis[f'Vref{i}'][0])
        vref_expected = 5.0 * i / 8.0
        ref_voltages[i] = vref_actual
        print(f"Vref{i}: {vref_actual:.3f}V (Expected: {vref_expected:.3f}V)")
    
    # Create comprehensive plots
    plt.figure(figsize=(16, 12))
    
    # Plot 1: Reference voltage verification
    plt.subplot(2, 2, 1)
    ref_values = [ref_voltages[i] for i in range(1, 8)]
    expected_values = [5.0 * i / 8.0 for i in range(1, 8)]
    x_pos = range(1, 8)
    
    plt.bar([x - 0.2 for x in x_pos], ref_values, 0.4, label='Actual', alpha=0.7)
    plt.bar([x + 0.2 for x in x_pos], expected_values, 0.4, label='Expected', alpha=0.7)
    plt.xlabel('Reference Number')
    plt.ylabel('Voltage (V)')
    plt.title('Reference Voltage Accuracy')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # Plot 2: Comparator outputs (analog)
    plt.subplot(2, 2, 2)
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2']
    
    for i in range(1, 8):
        comp_out = np.array(analysis[f'Comp_out_{i}'])
        plt.plot(input_voltage, comp_out, color=colors[i-1], 
                linewidth=2, label=f'Comp {i} (Vref={ref_voltages[i]:.2f}V)')
    
    plt.title('Flash ADC - Comparator Analog Outputs')
    plt.xlabel('Input Voltage (V)')
    plt.ylabel('Comparator Output Voltage (V)')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, alpha=0.3)
    
    # Plot 3: Digital thermometer code
    plt.subplot(2, 2, 3)
    
    threshold = 2.5  # Digital threshold voltage
    digital_outputs = []
    
    for i in range(1, 8):
        comp_out = np.array(analysis[f'Comp_out_{i}'])
        digital_out = (comp_out > threshold).astype(int)
        digital_outputs.append(digital_out)
        
        # Plot with offset for visibility
        plt.plot(input_voltage, digital_out * 0.8 + i - 0.5, 
                color=colors[i-1], linewidth=3, label=f'Comp {i}')
    
    plt.title('Flash ADC - Digital Thermometer Code')
    plt.xlabel('Input Voltage (V)')
    plt.ylabel('Comparator Number')
    plt.ylim(0, 8)
    plt.grid(True, alpha=0.3)
    plt.legend()
    
    # Plot 4: 3-bit binary output simulation
    plt.subplot(2, 2, 4)
    
    # Convert thermometer code to binary
    binary_codes = []
    for j in range(len(input_voltage)):
        # Count number of HIGH comparators
        high_count = sum([digital_outputs[i][j] for i in range(7)])
        binary_codes.append(high_count)
    
    plt.plot(input_voltage, binary_codes, 'ko-', linewidth=2, markersize=3)
    plt.title('Flash ADC - 3-bit Digital Output')
    plt.xlabel('Input Voltage (V)')
    plt.ylabel('Digital Code (0-7)')
    plt.grid(True, alpha=0.3)
    plt.ylim(-0.5, 7.5)
    
    # Add step annotations
    for code in range(8):
        plt.axhline(y=code, color='gray', linestyle='--', alpha=0.3)
        voltage_range = f"{code*5/8:.2f}V-{(code+1)*5/8:.2f}V"
        if code < 7:
            plt.text(0.1, code + 0.3, f"Code {code}", fontsize=8)
    
    plt.tight_layout()
    plt.savefig('flash_adc_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    # Performance analysis
    print(f"\nFlash ADC Performance Analysis:")
    print("=" * 50)
    
    transition_points = []
    for i in range(1, 8):
        comp_out = np.array(analysis[f'Comp_out_{i}'])
        
        # Find transition point where output crosses threshold
        try:
            # Find where output transitions from low to high or high to low
            diff_out = np.diff(comp_out)
            max_change_idx = np.argmax(np.abs(diff_out))
            transition_vin = input_voltage[max_change_idx]
            
            expected_vref = ref_voltages[i]
            error = abs(transition_vin - expected_vref)
            
            transition_points.append(transition_vin)
            print(f"Comparator {i}: Transitions at {transition_vin:.3f}V "
                  f"(Vref: {expected_vref:.3f}V, Error: {error:.3f}V)")
                  
        except:
            print(f"Comparator {i}: Could not determine clear transition point")
    
    # Overall ADC metrics
    if len(transition_points) > 1:
        step_sizes = np.diff(sorted(transition_points))
        avg_step = np.mean(step_sizes)
        step_variation = np.std(step_sizes)
        
        print(f"\nADC Metrics:")
        print(f"Average step size: {avg_step:.3f}V")
        print(f"Step size variation (std): {step_variation:.3f}V")
        print(f"Theoretical step size: {5.0/8:.3f}V")
        print(f"Resolution: 3 bits ({2**3} levels)")
        
        if step_variation < 0.1:  # Arbitrary threshold for "good" performance
            print("✓ Flash ADC is functioning correctly!")
        else:
            print("⚠ Large step size variation detected - check component matching")
    
except Exception as e:
    print(f"Simulation failed: {e}")
    import traceback
    traceback.print_exc()
    print("\nTroubleshooting suggestions:")
    print("1. The op-amp model may be too complex for convergence")
    print("2. Try reducing resistor values or increasing capacitive loading")
    print("3. Consider using ideal voltage sources for references initially")

# === chipster/data/analog_datasets/AMS_RF_Dataset/p7_CMOS Inverter.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('CMOS Inverter')
# 1. Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# 2. Define models for NMOS and PMOS with typical parameters
# These are generic models; for detailed design, use specific parameters
circuit.model('nmos', 'nmos', level=1, vto=0.7, kp=2e-3)  # NMOS threshold ~0.7V
circuit.model('pmos', 'pmos', level=1, vto=-0.7, kp=1.5e-3)  # PMOS threshold ~-0.7V
# 3. Add a voltage source for Vin
# For example, a DC voltage at 0V (logic LOW), can be swept later
circuit.V('in', 'Vin', circuit.gnd, 0@u_V)
# 4. Create NMOS transistor
# Correct order: name, drain, gate, source, bulk, model, w, l
circuit.MOSFET('M_N', 'Vout', 'Vin', 'GND', 'GND', model='nmos', w=10e-6, l=1e-6)
# 5. Create PMOS transistor
# Drain connected to Vout, gate to Vin, source to Vdd
circuit.MOSFET('M_P', 'Vout', 'Vin', 'Vdd', 'Vdd', model='pmos', w=10e-6, l=1e-6)
# 6. (Optional) Add a load resistor if needed for analysis
# Not necessary for basic inverter function
# 7. Ready for simulation
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p7_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

analysis = simulator.operating_point()
for node in analysis.nodes.values(): 
    print(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}")
vin_name = ""
for element in circuit.elements:
    for pin in element.pins:
        if "vin" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin_name = element.name
            break

circuit.element(vin_name).dc_value = "5"

simulator2 = circuit.simulator()
analysis2 = simulator2.operating_point()


node = 'vout'

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

vout2 = float(analysis2[node][0])

circuit.element(vin_name).dc_value = "0"

simulator3 = circuit.simulator()
analysis3 = simulator3.operating_point()

vout3 = float(analysis3[node][0])

import sys
if vout2 <= 2.5 and vout3 >= 2.5 and vout3 - vout2 >= 1.0:
    print("The circuit functions correctly.\n")
    sys.exit(0)

print("The circuit does not function correctly.\n"
    "It can not invert the input voltage.\n"
    f"When input is 5V, output is {vout2:.2f}V.\n"
    f"When input is 0V, output is {vout3:.2f}V.\n"
    "Please fix the wrong operating point.\n")

sys.exit(2)





# === chipster/data/analog_datasets/AMS_RF_Dataset/p27_Opamp Subtractor (Differential Amplifier).py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Subtractor (Differential Amplifier)')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Virtual ground at Vdd/2 for AC reference
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# DC bias voltages for inputs (example values, can be swept in simulation)
circuit.V('in1', 'Vin1', 'Vref', 3@u_V)
circuit.V('in2', 'Vin2', 'Vref', 4@u_V)
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Differential amplifier resistors (all 10kΩ)
circuit.R('1', 'Vin1', 'Vinn', 10@u_kΩ)     # R1
circuit.R('2', 'Vout', 'Vinn', 10@u_kΩ)     # R2 (feedback)
circuit.R('3', 'Vin2', 'Vinp', 10@u_kΩ)     # R3
circuit.R('4', 'Vref', 'Vinp', 10@u_kΩ)     # R4
# Opamp instance
circuit.X('op', 'Opamp', 'Vinp', 'Vinn', 'Vout')
simulator = circuit.simulator()
import numpy as np
# Define test parameters
BIAS_VOLTAGE = 2.5
TOLERANCE = 0.2  # Stricter 5% tolerance

# Create simulator
simulator = circuit.simulator()

# Test across a wider range of input voltages
vin1_values = np.linspace(2.5, 3.5, 5)  # Test from 1V to 4V
vin2_values = np.linspace(2.5, 3.5, 5)

print("Testing subtractor circuit with multiple input combinations...")
print("Using tolerance: {:.1f}%".format(TOLERANCE * 100))
print("-" * 60)
print("| Vin1 (V) | Vin2 (V) | Expected (V) | Actual (V) | Result |")
print("-" * 60)

all_tests_passed = True


for element in circuit.elements:
    for pin in element.pins:
        if "vin1" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin1_name = element.name
            break

for element in circuit.elements:
    for pin in element.pins:
        if "vin2" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin2_name = element.name
            break

circuit.element(vin1_name).detach()
circuit.element(vin2_name).detach()

circuit.V('in1', 'Vin1', circuit.gnd, '2.5')
circuit.V('in2', 'Vin2', circuit.gnd, '2.5')
        
import sys
# Test with multiple combinations of inputs
for vin1 in vin1_values:
    for vin2 in vin2_values:
        # Update input voltage sources
        circuit.element("Vin1").dc_value = vin1
        circuit.element("Vin2").dc_value = vin2

        
        # Run DC analysis
        try:
            analysis = simulator.operating_point()
        except Exception as e:
            print(f"Simulation failed: {e}")
            sys.exit(2)
        
        # Get actual output voltage
        actual_vout = float(analysis.Vout)
        
        # Calculate expected output for a proper subtractor: Vout = V2 - V1
        expected_vout = vin2 - vin1 + 2.5
        
        # Verify if the output voltage meets expectations
        if np.isclose(actual_vout, expected_vout, rtol=TOLERANCE):
            test_result = "PASS"
        else:
            test_result = "FAIL"
            all_tests_passed = False
        
        print(f"| {vin1:7.2f} | {vin2:7.2f} | {expected_vout:11.2f} | {actual_vout:10.2f} | {test_result:6} |")

print("-" * 60)


# Output final test result
if all_tests_passed:
    print("\nALL TESTS PASSED: The op-amp subtractor functions correctly.")
    sys.exit(0)
else:
    print("\nTESTS FAILED: The subtractor circuit is not functioning correctly.")
    print("Check the circuit configuration and component values.")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p2_Three-Stage Common-Source Amplifier with Proper Biasing.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Three-Stage Common-Source Amplifier with Proper Biasing')
# Define NMOS model parameters
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input voltage source
circuit.V('in', 'Vin', circuit.gnd, "dc 1.0 ac 1n")
# Bias voltage for drain of M1 (gate of M2)
circuit.V('bias_M2_gate', 'Bias_M2', 'Drain1', 2.0)  # 2V bias to ensure M2 is on
# Load resistors
R1_value = 10e3  # 10kΩ
R2_value = 10e3
R3_value = 10e3
# First stage: M1
circuit.MOSFET('M1', 'Drain1', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('R1', 'Drain1', 'Vdd', R1_value)
# Second stage: M2
circuit.MOSFET('M2', 'Drain2', 'Bias_M2', 'Drain1', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('R2', 'Drain2', 'Vdd', R2_value)
# Third stage: M3
circuit.MOSFET('M3', 'Vout', 'Drain2', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('R3', 'Vout', 'Vdd', R3_value)
# Simulation setup
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p2_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p39_Basic Charge Pump.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the circuit
circuit = Circuit('Basic Charge Pump')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)

# Define clock signals (non-overlapping clocks for charge pump operation)
circuit.PulseVoltageSource('clk1', 'phi1', circuit.gnd, 
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=500@u_ns, period=1@u_us,
                          rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('clk2', 'phi2', circuit.gnd, 
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=500@u_ns, period=1@u_us,
                          rise_time=10@u_ns, fall_time=10@u_ns,
                          delay_time=500@u_ns)  # Phase shifted

# Define MOSFET models
circuit.model('NMOS', 'nmos', 
              level=1,
              kp=120e-6,
              vto=0.7,
              lambda_=0.02,
              w=10e-6,
              l=1e-6)
circuit.model('PMOS', 'pmos', 
              level=1,
              kp=60e-6,
              vto=-0.7,
              lambda_=0.02,
              w=20e-6,
              l=1e-6)

# Charge pump components - corrected architecture
# First stage
circuit.MOSFET('M1', 'node1', 'phi1', circuit.gnd, circuit.gnd, model='NMOS')  # Switching NMOS
circuit.C('C1', 'node1', 'phi2', 10@u_pF)  # Pumping capacitor connected to phi2

# Second stage (diode-connected MOSFET for charge transfer)
circuit.MOSFET('M2', 'Vout', 'node1', 'node1', circuit.gnd, model='NMOS')  # Diode-connected transfer MOSFET
circuit.C('C2', 'Vout', circuit.gnd, 100@u_pF)  # Output storage capacitor

# Output load
circuit.R('load', 'Vout', circuit.gnd, 1@u_MΩ)

# Setup simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

# Perform transient analysis
try:
    analysis = simulator.transient(
        step_time=10@u_ns, 
        end_time=100@u_us,  # Increased to see the pump effect
        use_initial_condition=True
    )
except Exception as e:
    print(f"Simulation error: {e}")
    # Retry with adjusted parameters if needed
    analysis = simulator.transient(
        step_time=100@u_ns, 
        end_time=20@u_us
    )

# Plot results
plt.figure(figsize=(10, 8))

# Plot clock signals
plt.subplot(3, 1, 1)
plt.plot(analysis.time, analysis['phi1'], label='Phi1')
plt.plot(analysis.time, analysis['phi2'], label='Phi2')
plt.title('Charge Pump Clock Signals')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid(True)

# Plot intermediate node voltage
plt.subplot(3, 1, 2)
plt.plot(analysis.time, analysis['node1'], label='Node1 Voltage', color='green')
plt.title('Intermediate Node Voltage')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid(True)

# Plot output voltage
plt.subplot(3, 1, 3)
plt.plot(analysis.time, analysis['Vout'], label='Output Voltage', color='red')
plt.title('Charge Pump Output Voltage')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()

# Print final output voltage
final_voltage = analysis['Vout'][-1]
print(f"Final output voltage: {final_voltage}")

# === chipster/data/analog_datasets/AMS_RF_Dataset/p35_2-to-4 Decoder.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the 2-to-4 Decoder circuit
circuit = Circuit('2-to-4 Decoder')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=400@u_ns,
    period=400@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delayed start
# Input A (LSB)
circuit.PulseVoltageSource('inA', 'A', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B (MSB)
circuit.PulseVoltageSource('inB', 'B', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=80@u_ns,
    period=160@u_ns
)

# Add input protection and parasitic capacitance
for node in ['A', 'B']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# Inverters for input signals
# Inverter for A
circuit.MOSFET('M1', 'A_inv', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'A_inv', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C1', 'A_inv', circuit.gnd, 0.1@u_pF)

# Inverter for B
circuit.MOSFET('M3', 'B_inv', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M4', 'B_inv', 'B_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C2', 'B_inv', circuit.gnd, 0.1@u_pF)

# Output 0 decoder (B'A')
circuit.MOSFET('M5', 'Y0_int', 'B_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'Y0_int', 'A_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M7', 'Y0_int', 'B_inv', 'Y0_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M8', 'Y0_n', 'A_inv', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C3', 'Y0_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y0
circuit.MOSFET('M9', 'Y0', 'Y0_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M10', 'Y0', 'Y0_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C4', 'Y0', circuit.gnd, 0.1@u_pF)

# Output 1 decoder (B'A)
circuit.MOSFET('M11', 'Y1_int', 'B_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M12', 'Y1_int', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M13', 'Y1_int', 'B_inv', 'Y1_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M14', 'Y1_n', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C5', 'Y1_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y1
circuit.MOSFET('M15', 'Y1', 'Y1_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M16', 'Y1', 'Y1_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C6', 'Y1', circuit.gnd, 0.1@u_pF)

# Output 2 decoder (BA')
circuit.MOSFET('M17', 'Y2_int', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M18', 'Y2_int', 'A_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M19', 'Y2_int', 'B_int', 'Y2_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M20', 'Y2_n', 'A_inv', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C7', 'Y2_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y2
circuit.MOSFET('M21', 'Y2', 'Y2_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M22', 'Y2', 'Y2_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C8', 'Y2', circuit.gnd, 0.1@u_pF)

# Output 3 decoder (BA)
circuit.MOSFET('M23', 'Y3_int', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M24', 'Y3_int', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M25', 'Y3_int', 'B_int', 'Y3_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M26', 'Y3_n', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C9', 'Y3_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y3
circuit.MOSFET('M27', 'Y3', 'Y3_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M28', 'Y3', 'Y3_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C10', 'Y3', circuit.gnd, 0.1@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=200@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    va = np.array([float(v) for v in analysis['A']])
    vb = np.array([float(v) for v in analysis['B']])
    vy0 = np.array([float(v) for v in analysis['Y0']])
    vy1 = np.array([float(v) for v in analysis['Y1']])
    vy2 = np.array([float(v) for v in analysis['Y2']])
    vy3 = np.array([float(v) for v in analysis['Y3']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, vb, label='B (MSB)', linestyle='--', color='blue')
    ax1.plot(time, va, label='A (LSB)', linestyle='--', color='red')
    ax1.grid(True)
    ax1.set_title('2-to-4 Decoder - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs
    ax2.plot(time, vy0, label='Y0 (00)', color='purple')
    ax2.plot(time, vy1, label='Y1 (01)', color='orange')
    ax2.plot(time, vy2, label='Y2 (10)', color='green')
    ax2.plot(time, vy3, label='Y3 (11)', color='brown')
    ax2.grid(True)
    ax2.set_title('2-to-4 Decoder - Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Analyze decoder characteristics
    def analyze_decoder(time, va, vb, vy0, vy1, vy2, vy3, vth=1.65):
        """Verify decoder functionality and calculate delays"""
        def to_binary(v):
            return 1 if v > vth else 0
        
        def find_transitions(time, signal):
            binary = [to_binary(v) for v in signal]
            transitions = []
            for i in range(1, len(binary)):
                if binary[i] != binary[i-1]:
                    transitions.append(i)
            return transitions
        
        # Calculate propagation delays
        a_trans = find_transitions(time, va)
        output_delays = []
        
        for t_in in a_trans:
            for signal in [vy0, vy1, vy2, vy3]:
                out_trans = find_transitions(time, signal)
                for t_out in out_trans:
                    if t_out > t_in:
                        delay = time[t_out] - time[t_in]
                        output_delays.append(delay)
                        break
        
        if output_delays:
            print(f"Average propagation delay: {np.mean(output_delays):.2e} seconds")
            print(f"Maximum propagation delay: {np.max(output_delays):.2e} seconds")
            print(f"Minimum propagation delay: {np.min(output_delays):.2e} seconds")

    analyze_decoder(time, va, vb, vy0, vy1, vy2, vy3)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p5_Single-Stage Cascode NMOS Amplifier.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Create the circuit
circuit = Circuit('Single-Stage Cascode NMOS Amplifier')
# Define NMOS model
circuit.model('nmos', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Biasing voltages
# Increase bias voltage for M2 to ensure it's active
circuit.V('Vbias', 'Vbias', circuit.gnd, 3.0)  # Bias voltage for cascode transistor
# Increase Vin to ensure M1 is in saturation
circuit.V('Vin', 'Vin', circuit.gnd, "dc 1.5 ac 1n")
# Load resistor R
circuit.R('load', 'Vout', 'Vdd', 10@u_kΩ)  # 10kΩ load resistor
# Transistor M1: Main amplifying NMOS
# Drain node is 'Drain_M1'
circuit.MOSFET('M1', 'Drain_M1', 'Vin', circuit.gnd, circuit.gnd, model='nmos', w=50e-6, l=1e-6)
# Transistor M2: Cascode NMOS
# Drain connected to Vout node, gate connected to Vbias
circuit.MOSFET('M2', 'Vout', 'Vbias', 'Drain_M1', 'Drain_M1', model='nmos', w=50e-6, l=1e-6)
# Connect drain of M2 to load resistor and Vdd
# Vout node is at drain of M2, connected to R and Vdd
# Already connected via the resistor 'load'
# This configuration now ensures V_GS > V_th for both M1 and M2

simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p5_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p3_Common-Drain Source Follower.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('Common-Drain Source Follower')
# MOSFET models
circuit.model('nmos', 'nmos', level=1, vto=0.5, kp=100e-6)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input voltage
circuit.V('in', 'Vin', circuit.gnd, "dc 1.0 ac 1n")
# Load resistor R at the source
circuit.R('load', 'Vout', circuit.gnd, 10@u_kΩ)
# NMOS transistor M1: source follower
# Sequence: name, drain, gate, source, bulk, model, w, l
circuit.MOSFET('M1', 'Vdd', 'Vin', 'Vout', 'Vout', model='nmos', w=50e-6, l=1e-6)
# Note: bulk connected to source (Vout)
# For simplicity, bulk is connected to source node in the MOSFET definition

simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p3_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p40_Operational Transconductance Amplifier (OTA).py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the circuit
circuit = Circuit('Operational Transconductance Amplifier (OTA)')

# Define power supplies
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)  # Positive supply
circuit.V('ss', 'Vss', circuit.gnd, -5@u_V)  # Negative supply

# Define bias current source
circuit.I('bias', 'Vdd', 'bias_node', 50@u_uA)  # Bias current

# Define input signals (differential)
circuit.SinusoidalVoltageSource('in_p', 'in_p', circuit.gnd, 
                               dc_offset=0@u_V, amplitude=0.01@u_V, frequency=1@u_kHz)
circuit.V('in_n', 'in_n', circuit.gnd, 0@u_V)  # DC reference

# Define MOSFET models with proper parameters
circuit.model('NMOS', 'nmos', 
              level=1,
              kp=120e-6,
              vto=0.7,
              lambda_=0.02,
              gamma=0.5,
              phi=0.7)

circuit.model('PMOS', 'pmos', 
              level=1,
              kp=40e-6,
              vto=-0.7,
              lambda_=0.02,
              gamma=0.5,
              phi=0.7)

# Differential pair (NMOS transistors)
circuit.MOSFET(1, 'drain1', 'in_p', 'tail', circuit.gnd, model='NMOS', w=50e-6, l=1e-6)
circuit.MOSFET(2, 'drain2', 'in_n', 'tail', circuit.gnd, model='NMOS', w=50e-6, l=1e-6)

# Tail current source (NMOS current mirror)
circuit.MOSFET(3, 'tail', 'bias_node', 'Vss', 'Vss', model='NMOS', w=20e-6, l=1e-6)
circuit.MOSFET(4, 'bias_node', 'bias_node', 'Vss', 'Vss', model='NMOS', w=20e-6, l=1e-6)

# Current mirror load (PMOS transistors)
circuit.MOSFET(5, 'drain1', 'drain1', 'Vdd', 'Vdd', model='PMOS', w=100e-6, l=1e-6)
circuit.MOSFET(6, 'drain2', 'drain1', 'Vdd', 'Vdd', model='PMOS', w=100e-6, l=1e-6)

# Output stage
circuit.MOSFET(7, 'output', 'drain2', 'Vss', 'Vss', model='NMOS', w=50e-6, l=1e-6)
circuit.MOSFET(8, 'output', 'bias_node', 'Vdd', 'Vdd', model='PMOS', w=100e-6, l=1e-6)

# Add compensation for stability
circuit.C('comp', 'drain2', 'output', 2@u_pF)  # Miller compensation capacitor
circuit.R('comp_res', 'drain2', 'comp_node', 1@u_kΩ)  # Compensation resistor
circuit.C('comp2', 'comp_node', 'output', 2@u_pF)  # Second compensation capacitor

# Add a load capacitor
circuit.C('load', 'output', circuit.gnd, 10@u_pF)

# Add a small resistor in series with the load to prevent oscillations
circuit.R('series', 'output', 'out_node', 100@u_Ω)
circuit.C('load2', 'out_node', circuit.gnd, 10@u_pF)

# Setup simulation with more conservative options for stability
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(
    reltol=1e-6, 
    abstol=1e-12, 
    vntol=1e-6,
    method='gear',  # More stable integration method
    itl1=100,       # Increase DC iteration limit
    itl2=50,        # Increase transient iteration limit
    itl4=20,        # Increase transient timepoint iteration limit
    pivotrel=1e-3,  # Better pivot relative tolerance
    pivottol=1e-6   # Better pivot absolute tolerance
)

print("Circuit netlist:")
print(circuit)

# Run operating point analysis
print("\nOperating Point Analysis:")
try:
    dc_analysis = simulator.operating_point()
    # Convert to regular Python values
    for node_name in dc_analysis.nodes.keys():
        node_value = dc_analysis[node_name]
        if hasattr(node_value, 'as_ndarray'):
            node_value = node_value.as_ndarray()[0]
        print(f"{node_name}: {node_value:.6f} V")
except Exception as e:
    print(f"Operating point analysis failed: {e}")

# Run transient analysis with smaller steps for stability
print("\nRunning transient analysis...")
try:
    transient_analysis = simulator.transient(
        step_time=0.1@u_us,  # Smaller step time
        end_time=2@u_ms
    )
except Exception as e:
    print(f"Transient analysis failed: {e}")
    transient_analysis = None

# Run AC analysis
print("\nRunning AC analysis...")
try:
    ac_analysis = simulator.ac(
        start_frequency=1@u_Hz,
        stop_frequency=100@u_MHz,
        number_of_points=200,
        variation='dec'
    )
except Exception as e:
    print(f"AC analysis failed: {e}")
    ac_analysis = None

# Plot results if analyses were successful
if transient_analysis is not None:
    plt.figure(figsize=(12, 8))

    # Convert to numpy arrays
    time = np.array(transient_analysis.time)
    in_p = np.array(transient_analysis['in_p'])
    output = np.array(transient_analysis['out_node'])  # Use the node after series resistor
    
    # Transient analysis plot
    plt.subplot(2, 2, 1)
    plt.plot(time, in_p, label='Input+')
    plt.plot(time, output, label='Output')
    plt.xlabel('Time (s)')
    plt.ylabel('Voltage (V)')
    plt.title('Transient Response (Stabilized)')
    plt.legend()
    plt.grid(True)

if ac_analysis is not None:
    # Convert to numpy arrays
    frequency = np.array(ac_analysis.frequency)
    output_ac = np.array(ac_analysis['out_node'])  # Use the node after series resistor
    
    # AC analysis plot - magnitude
    plt.subplot(2, 2, 2)
    gain = np.abs(output_ac)
    plt.semilogx(frequency, 20*np.log10(np.where(gain > 0, gain, 1e-12)))
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Gain (dB)')
    plt.title('AC Response - Magnitude (Stabilized)')
    plt.grid(True)

    # AC analysis plot - phase
    plt.subplot(2, 2, 3)
    plt.semilogx(frequency, np.angle(output_ac, deg=True))
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Phase (degrees)')
    plt.title('AC Response - Phase (Stabilized)')
    plt.grid(True)

# DC transfer characteristic
try:
    dc_sweep = simulator.dc(Vin_p=slice(-0.1, 0.1, 0.005))
    plt.subplot(2, 2, 4)
    plt.plot(dc_sweep.Vin_p, dc_sweep.out_node)  # Use the node after series resistor
    plt.xlabel('Differential Input Voltage (V)')
    plt.ylabel('Output Voltage (V)')
    plt.title('DC Transfer Characteristic (Stabilized)')
    plt.grid(True)
except Exception as e:
    print(f"DC sweep failed: {e}")

plt.tight_layout()
plt.show()

# Calculate and print performance metrics
print("\nPerformance Metrics:")
    
# DC gain calculation
try:
    if ac_analysis is not None:
        # Get the low-frequency gain (first point in AC analysis)
        low_freq_gain = np.abs(output_ac[0])
        if low_freq_gain > 0:
            print(f"DC Gain: {low_freq_gain:.2f} ({20*np.log10(low_freq_gain):.2f} dB)")
        else:
            print("DC Gain: 0.00 (-inf dB)")
except Exception as e:
    print(f"Could not calculate DC gain: {e}")
        
# Phase margin calculation
try:
    if ac_analysis is not None:
        # Find unity gain frequency
        unity_gain_idx = np.where(gain <= 1)[0]
        if len(unity_gain_idx) > 0:
            ugf = frequency[unity_gain_idx[0]]
            phase_at_ugf = np.angle(output_ac[unity_gain_idx[0]], deg=True)
            phase_margin = 180 + phase_at_ugf
            print(f"Unity Gain Frequency: {ugf:.2e} Hz")
            print(f"Phase Margin: {phase_margin:.2f}°")
            
            # Check if phase margin is sufficient for stability
            if phase_margin > 45:
                print("Phase margin is sufficient for stability (>45°)")
            else:
                print("WARNING: Phase margin may be insufficient for stability")
        else:
            print("Could not find unity gain frequency")
except Exception as e:
    print(f"Could not calculate phase margin: {e}")

# Additional metrics from operating point
try:
    if 'dc_analysis' in locals():
        output_voltage = dc_analysis['out_node']
        if hasattr(output_voltage, 'as_ndarray'):
            output_voltage = output_voltage.as_ndarray()[0]
        print(f"Output DC voltage: {output_voltage:.3f} V")
        
        # Calculate approximate power consumption
        total_current = 100e-6  # 100μA
        power = 10 * total_current  # 10V total supply * current
        print(f"Approximate power consumption: {power*1e6:.2f} μW")
        
        # Calculate output swing range
        max_output = 4.0  # V
        min_output = -4.0  # V
        output_swing = max_output - min_output
        print(f"Estimated output swing: {output_swing:.1f} V")
except Exception as e:
    print(f"Could not calculate additional metrics: {e}")

# Check for stability in transient response
if transient_analysis is not None:
    output_signal = np.array(transient_analysis['out_node'])
    # Check if the output is oscillating by looking for significant variations
    std_dev = np.std(output_signal)
    mean_val = np.mean(output_signal)
    
    if std_dev > 0.1 * abs(mean_val):  # If standard deviation is more than 10% of mean
        print("WARNING: Output shows significant oscillation")
        print(f"Output standard deviation: {std_dev:.4f} V")
    else:
        print("Output appears stable")
        print(f"Output standard deviation: {std_dev:.6f} V")

# === chipster/data/analog_datasets/AMS_RF_Dataset/p33_3-Stage Ring Oscillator.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the Ring Oscillator circuit
circuit = Circuit('3-Stage Ring Oscillator')

# Define power supply with ramp-up to improve convergence
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=100@u_ns,
    period=100@u_ns
)

# Add small resistor in series with Vdd for better convergence
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)

# First Inverter Stage
circuit.MOSFET('M1', 'node1', 'node3', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'node1', 'node3', circuit.gnd, circuit.gnd, model='NMOS')
circuit.R('R1', 'node1', 'vdd_internal', 100@u_kΩ)  # Pull-up to help start oscillation

# Second Inverter Stage
circuit.MOSFET('M3', 'node2', 'node1', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M4', 'node2', 'node1', circuit.gnd, circuit.gnd, model='NMOS')

# Third Inverter Stage
circuit.MOSFET('M5', 'node3', 'node2', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'node3', 'node2', circuit.gnd, circuit.gnd, model='NMOS')

# Add parasitic capacitance
circuit.C('C1', 'node1', circuit.gnd, 0.5@u_pF)
circuit.C('C2', 'node2', circuit.gnd, 0.5@u_pF)
circuit.C('C3', 'node3', circuit.gnd, 0.5@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'  # Use Gear integration method for better stability
)

try:
    # Run transient analysis with modified parameters
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=50@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    v1 = np.array([float(v) for v in analysis['node1']])
    v2 = np.array([float(v) for v in analysis['node2']])
    v3 = np.array([float(v) for v in analysis['node3']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot node voltages
    ax1.plot(time, v1, label='Node 1', color='blue')
    ax1.plot(time, v2, label='Node 2', color='red')
    ax1.plot(time, v3, label='Node 3', color='green')
    ax1.grid(True)
    ax1.set_title('Ring Oscillator - Node Voltages')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Calculate and plot oscillation frequency
    def calculate_frequency(time, voltage, threshold=1.65):
        crossings = np.where(np.diff(voltage > threshold))[0]
        if len(crossings) >= 2:
            periods = np.diff(time[crossings])
            freq = 1.0 / np.mean(periods)
            return freq
        return None

    # Plot FFT of node3 (output)
    if len(time) > 1:
        sampling_rate = 1.0 / (time[1] - time[0])
        n = len(v3)
        freqs = np.fft.fftfreq(n, 1/sampling_rate)
        fft_v3 = np.abs(np.fft.fft(v3))
        
        # Plot only positive frequencies
        mask = freqs > 0
        ax2.plot(freqs[mask], fft_v3[mask])
        ax2.grid(True)
        ax2.set_title('Frequency Spectrum')
        ax2.set_xlabel('Frequency (Hz)')
        ax2.set_ylabel('Magnitude')
        ax2.set_xscale('log')

    plt.tight_layout()
    plt.show()

    # Calculate and display oscillation characteristics
    freq = calculate_frequency(time, v3)
    if freq is not None:
        print(f"Oscillation Frequency: {freq/1e6:.2f} MHz")
        print(f"Period: {1000/freq:.2f} ns")

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p11_Passive High-Pass Filter.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive High-Pass Filter')
# Input voltage source (DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 1.0) # 1V DC
# Capacitor in series with input
circuit.C('1', 'Vin', 'Vout', 10@u_nF)
# Resistor from output to ground
circuit.R('1', 'Vout', circuit.gnd, 10@u_kΩ)
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)

node = 'Vout'

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac))
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of High-Pass Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)

plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Point')
plt.legend()

plt.tight_layout()
plt.savefig('p11_figure.png')

# Basic High-Pass Filter Verification - Including Monotonicity Check
# 1. Check High-Frequency Gain
high_freq_gain = gain_db[-1]  # Gain at highest frequency
print(f"Gain at highest frequency ({frequencies[-1]:.2f} Hz): {high_freq_gain:.2f} dB")

# 2. Check low frequency attenuation
low_freq_gain = gain_db[0]  # Gain at lowest frequency
print(f"Gain at lowest frequency ({frequencies[0]:.2f} Hz): {low_freq_gain:.2f} dB")
low_freq_attenuation = high_freq_gain - low_freq_gain
print(f"Low frequency attenuation: {low_freq_attenuation:.2f} dB")

# 3. Find the approximate -3dB point
idx_3db = np.argmin(np.abs(gain_db - (high_freq_gain-3)))
cutoff_freq = frequencies[idx_3db]
print(f"Approximate -3dB cutoff frequency: {cutoff_freq:.2f} Hz")

# 4. Check monotonicity
# Use smoothing to reduce measurement noise
window_size = min(11, len(gain_db) // 20)  #  Use window smoothing
if window_size % 2 == 0:  # Ensure window size is odd
    window_size += 1
    
if window_size > 2:  # If there are enough points to smooth
    from scipy.signal import savgol_filter
    smoothed_gain = savgol_filter(gain_db, window_size, 1)  # Use 1st order polynomial smoothing
else:
    smoothed_gain = gain_db
    
# Calculate the difference of the smoothed gain - note that a high-pass filter should increase with frequency
diff_gain = np.diff(smoothed_gain)
non_monotonic_points = np.sum(diff_gain < -0.5)  # Allow a small decrease of 0.5dB

if non_monotonic_points > 0:
    monotonic_percentage = 100 * (1 - non_monotonic_points / len(diff_gain))
    print(f"Warning: Gain is not strictly monotonically increasing.")
    print(f"Monotonicity: {monotonic_percentage:.1f}% of frequency points")
    if monotonic_percentage < 90:  # if non-monotonic points exceed 10%
        print("This may not be a well-behaved high-pass filter.")
else:
    print("Filter response is monotonically increasing with frequency, as expected.")

# 5. Determine if it meets high-pass characteristics
if low_freq_attenuation > 2 and (non_monotonic_points == 0 or monotonic_percentage >= 90):
    print("The circuit exhibits proper high-pass filter characteristics.")
    sys.exit(0)
else:
    print("The circuit does not show expected high-pass filter characteristics.")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p19_Gilbert Cell Mixer.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Gilbert Cell Mixer')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.7)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
circuit.V('bias', 'Vbias', circuit.gnd, 1.5)  # Bias voltage for current source (Vth + 0.8V)
# RF and LO Input Voltages (DC bias points)
circuit.V('rfp', 'Vrfp', circuit.gnd, 2.5)  # RF+ input biased at mid-supply
circuit.V('rfn', 'Vrfn', circuit.gnd, 2.5)  # RF- input biased at mid-supply
circuit.V('lop', 'Vlop', circuit.gnd, 3.0)  # LO+ input biased above threshold
circuit.V('lon', 'Vlon', circuit.gnd, 2.0)  # LO- input biased below LO+
# Load Resistors
circuit.R('L1', 'Vdd', 'Voutp', 1@u_kΩ)
circuit.R('L2', 'Vdd', 'Voutn', 1@u_kΩ)
# Current Source Transistor
circuit.MOSFET('7', 'SourceNode', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=100e-6, l=1e-6)
# RF Differential Pair
circuit.MOSFET('1', 'RFp_out', 'Vrfp', 'SourceNode', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'RFn_out', 'Vrfn', 'SourceNode', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# LO Switching Quad
circuit.MOSFET('3', 'Voutp', 'Vlop', 'RFp_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Voutp', 'Vlon', 'RFn_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('5', 'Voutn', 'Vlon', 'RFp_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('6', 'Voutn', 'Vlop', 'RFn_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Analysis Part
simulator = circuit.simulator()
# Gilbert Cell Mixer Functionality Test with FFT Analysis
import sys
import numpy as np

detached_voltage_source = ['Vrfp', 'Vrfn', 'Vlop', 'Vlon']
for source in detached_voltage_source:
    circuit.element(source).detach()

# connected Vrfn and Vrfp
circuit.V('rfp', 'Vrfp', circuit.gnd, 2.0@u_V)
circuit.V('rfn', 'Vrfn', 'Vrfp', 0.0@u_V)

# connected Vlop and Vlon
circuit.V('lop', 'Vlop', circuit.gnd, 4.0@u_V)
circuit.V('lon', 'Vlon', 'Vlop', 0.0@u_V)

# Sweep the Vlop to get the operating point
simulator_dc = circuit.simulator(temperature=25, nominal_temperature=25)
try:
    analysis = simulator_dc.dc(Vlop=slice(0, 5, 0.1))
except Exception as e:
    print(f"Error during DC simulation: {e}")
    sys.exit(2)

# find the best operating point
voutp = np.array(analysis['Voutp'])
vlop = np.array(analysis['Vlop'])


# find the best operating point for Vrfp which can make the Voutp closest to 2.5V
best_i = 0
best_vlop = 2.5
for i in range(len(voutp)):
    # If current voutp is closer to 2.5V than the previously found best
    if abs(voutp[i] - 2.5) < abs(voutp[best_i] - 2.5):
        best_i = i
        best_vlop = vlop[i]
        best_voutp = voutp[i]
    # If current voutp is equally distant from 2.5V as the previously found best
    elif abs(voutp[i] - 2.5) == abs(voutp[best_i] - 2.5):
        # When multiple vlop values meet the requirements, we need to select the one with voutp closest to 2.5V
        # Since abs(voutp[i] - 2.5) == abs(voutp[best_i] - 2.5), we need to compare actual values
        # Choose the one closer to 2.5V (to handle cases where one is above 2.5 and one is below)
        if abs(voutp[i] - 2.5) == (voutp[i] - 2.5):  # Current value is >= 2.5
            if abs(voutp[best_i] - 2.5) != (voutp[best_i] - 2.5) or vlop[i] > best_vlop:
                best_i = i
                best_vlop = vlop[i]
                best_voutp = voutp[i]


print(f"Best Vlop: {best_vlop:.2f} V, Best Voutp: {best_voutp:.2f} V")

detached_voltage_source = ['Vrfp', 'Vrfn', 'Vlop', 'Vlon']
for source in detached_voltage_source:
    circuit.element(source).detach()

circuit.SinusoidalVoltageSource('rfp', 'Vrfp', circuit.gnd,
                              amplitude=0.1@u_V, frequency=1@u_kHz,
                              dc_offset=2.0@u_V, offset = 2.0@u_V,
                              ac_magnitude=0.1@u_V,
                              delay=0)
circuit.SinusoidalVoltageSource('rfn', 'Vrfn', circuit.gnd,
                              amplitude=0.1@u_V, frequency=1@u_kHz,
                              dc_offset=2.0@u_V, offset = 2.0@u_V,
                              ac_magnitude=0.1@u_V,
                              delay=0.5@u_ms)
circuit.SinusoidalVoltageSource('lop', 'Vlop', circuit.gnd,
                                amplitude=0.1@u_V, frequency=1.2@u_kHz,
                                dc_offset=best_vlop@u_V, offset = best_vlop@u_V,
                                ac_magnitude=0.1@u_V,
                                delay=0)
circuit.SinusoidalVoltageSource('lon', 'Vlon', circuit.gnd,
                                amplitude=0.1@u_V, frequency=1.2@u_kHz,
                                dc_offset=best_vlop@u_V, offset = best_vlop@u_V,
                                ac_magnitude=0.1@u_V,
                                delay=1/(2*1.2e3)@u_s)


circuit.R('R_filter_p', 'Voutp', 'Vdd', 1@u_kOhm)
circuit.C('C_filter_p', 'Voutp', 'Vdd', 10@u_nF)

circuit.R('R_filter_n', 'Voutn', 'Vdd', 1@u_kOhm)
circuit.C('C_filter_n', 'Voutn', 'Vdd', 10@u_nF)


simulator = circuit.simulator()

# Perform transient analysis to get mixer output
print("Performing transient analysis to obtain mixing output...")
sampling_rate = 1 / (20 * 1.2e3)  # Sampling rate 20x higher than LO frequency
simulation_time = 20e-3  # Observe 20ms, multiple cycles of RF and LO
try:
    analysis = simulator.transient(step_time=sampling_rate, end_time=simulation_time)
except Exception as e:
    print(f"Error during transient simulation: {e}")
    sys.exit(2)

# Extract signals
time = analysis.time
voutp = analysis['Voutp']
voutn = analysis['Voutn']
vlop = analysis['Vlop']
vlon = analysis['Vlon']
vrfp = analysis['Vrfp']
vrfn = analysis['Vrfn']
vout_diff = voutp - voutn  # Differential output

# Perform FFT analysis

from scipy.fft import fft
from matplotlib import pyplot as plt

# Calculate FFT
n = len(time)
fft_vout = fft(vout_diff)
fft_magnitude = np.abs(fft_vout) / n * 2  # Normalize magnitude
freq = np.fft.fftfreq(n, sampling_rate)  # Frequency axis

# Keep only positive frequencies
positive_freq_mask = freq > 0
freq = freq[positive_freq_mask]
fft_magnitude = fft_magnitude[positive_freq_mask]

# Output major frequency components
print("\nFFT Analysis Results - Major Frequency Components:")
# Find top 5 frequency components
indices = np.argsort(fft_magnitude)[::-1][:5]
for i in indices:
    print(f"Frequency: {freq[i]:.1f} Hz, Magnitude: {fft_magnitude[i]:.6f} V")

# Check for mixing products
rf_freq = 1e3  # 1 kHz
lo_freq = 1.2e3  # 1.2 kHz
expected_if_down = abs(lo_freq - rf_freq)  # Down-conversion: 200 Hz
expected_if_up = lo_freq + rf_freq  # Up-conversion: 2.2 kHz

# Search for expected IF frequencies in FFT results
tolerance = 50  # Hz
found_if_down = False
found_if_up = False
if_down_magnitude = 0
if_up_magnitude = 0

for i, f in enumerate(freq):
    if abs(f - expected_if_down) < tolerance and fft_magnitude[i] > 1e-4:
        found_if_down = True
        if_down_magnitude = fft_magnitude[i]
        print(f"\nDetected down-conversion IF signal (LO-RF): {f:.1f} Hz, Magnitude: {if_down_magnitude:.6f} V")
    
    if abs(f - expected_if_up) < tolerance and fft_magnitude[i] > 1e-4:
        found_if_up = True
        if_up_magnitude = fft_magnitude[i]
        print(f"Detected up-conversion IF signal (LO+RF): {f:.1f} Hz, Magnitude: {if_up_magnitude:.6f} V")

# Plot transient simulation and FFT results
plt.figure(figsize=(12, 10))

# Subplot 1: Input signals - RF pair
plt.subplot(3, 2, 1)
plt.plot(time*1000, vrfp, label='RF+')
plt.plot(time*1000, vrfn, label='RF-')
plt.title('RF Input Signals')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.legend()
plt.grid(True)

# Subplot 2: Input signals - LO pair
plt.subplot(3, 2, 2)
plt.plot(time*1000, vlop, label='LO+')
plt.plot(time*1000, vlon, label='LO-')
plt.title('LO Input Signals')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.legend()
plt.grid(True)

# Subplot 3: Output signals - Voutp, Voutn
plt.subplot(3, 2, 3)
plt.plot(time*1000, voutp, label='OUT+')
plt.plot(time*1000, voutn, label='OUT-')
plt.title('Output Signals')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.legend()
plt.grid(True)

# Subplot 4: Differential output
plt.subplot(3, 2, 4)
plt.plot(time*1000, vout_diff)
plt.title('Differential Output (OUT+ - OUT-)')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.grid(True)

# Subplot 5: FFT of differential output - Full spectrum
plt.subplot(3, 2, 5)
max_freq_display = 5000  # Limit to 5kHz for better visibility
mask = freq < max_freq_display
plt.plot(freq[mask], fft_magnitude[mask])
plt.title('FFT Spectrum Analysis')
plt.xlabel('Frequency (Hz)')
plt.ylabel('Magnitude (V)')
plt.grid(True)

# Mark key frequencies
plt.axvline(x=rf_freq, color='b', linestyle='--', label='RF')
plt.axvline(x=lo_freq, color='m', linestyle='--', label='LO')
if found_if_down:
    plt.axvline(x=expected_if_down, color='r', linestyle='--', label='IF down')
if found_if_up:
    plt.axvline(x=expected_if_up, color='g', linestyle='--', label='IF up')
plt.legend()

# Subplot 6: FFT - Zoomed in on important frequencies
plt.subplot(3, 2, 6)
zoom_mask = (freq < 3000) & (freq > 0)  # Focus on 0-3kHz range
plt.plot(freq[zoom_mask], fft_magnitude[zoom_mask])
plt.title('FFT Spectrum (Zoomed)')
plt.xlabel('Frequency (Hz)')
plt.ylabel('Magnitude (V)')
plt.grid(True)

# Mark and annotate key frequencies in zoomed view
key_freqs = [rf_freq, lo_freq, expected_if_down, expected_if_up]
key_labels = ['RF (1kHz)', 'LO (1.2kHz)', 'IF down (200Hz)', 'IF up (2.2kHz)']
key_colors = ['b', 'm', 'r', 'g']

for f, label, color in zip(key_freqs, key_labels, key_colors):
    if f < 3000:  # Only mark if in zoomed range
        plt.axvline(x=f, color=color, linestyle='--')
        # Find closest frequency in our FFT data
        idx = np.argmin(np.abs(freq - f))
        if idx < len(freq) and zoom_mask[idx]:
            plt.annotate(label, 
                         xy=(freq[idx], fft_magnitude[idx]),
                         xytext=(10, 10), 
                         textcoords='offset points',
                         arrowprops=dict(arrowstyle='->'),
                         color=color)

plt.tight_layout()
plt.savefig('p19_waveform.png')
# plt.show()

# Evaluate mixer performance
if found_if_down or found_if_up:
    print("\nMixer functioning correctly: Mixing products detected!")
    
    # Calculate conversion efficiency
    rf_index = np.argmin(np.abs(freq - rf_freq))
    rf_magnitude = fft_magnitude[rf_index]
    
    if found_if_down:
        conversion_gain_down = 20 * np.log10(if_down_magnitude / rf_magnitude)
        print(f"Down-conversion gain: {conversion_gain_down:.2f} dB")
    
    if found_if_up:
        conversion_gain_up = 20 * np.log10(if_up_magnitude / rf_magnitude)
        print(f"Up-conversion gain: {conversion_gain_up:.2f} dB")
    
    # Evaluate LO leakage
    lo_index = np.argmin(np.abs(freq - lo_freq))
    lo_leakage = fft_magnitude[lo_index]
    if found_if_down:
        lo_rejection = 20 * np.log10(if_down_magnitude / lo_leakage)
        print(f"LO rejection ratio: {lo_rejection:.2f} dB")
    
    # Overall evaluation
    print("\nMixer performance assessment:")
    if found_if_down and if_down_magnitude > 1e-3:
        print("✓ Down-conversion functioning properly")
    if found_if_up and if_up_magnitude > 1e-3:
        print("✓ Up-conversion functioning properly")
    
    print("The Gilbert Cell Mixer is functioning correctly.")
    print("Plots saved as 'mixer_analysis.png'")
    sys.exit(0)  # Exit with success status code
else:
    print("\nMixer malfunction: Expected mixing products not detected!")
    print("Check the following possible issues:")
    print("1. RF and LO signal amplitudes might be insufficient")
    print("2. Circuit connections might be incorrect")
    print("Plots saved as 'mixer_analysis.png'")
    sys.exit(2)  # Exit with error status code

# === chipster/data/analog_datasets/AMS_RF_Dataset/p13_Passive Band-Stop Filter.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive Band-Stop Filter')
# Input voltage source (DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 1.0)
# Series resistor R1 between Vin and Vout
circuit.R('1', 'Vin', 'Vout', 1@u_kΩ)
# Series LC branch from Vout to ground for notch
# Create an intermediate node for series connection
circuit.L('1', 'Vout', 'N1', 10@u_mH)   # L1 from Vout to N1
circuit.C('1', 'N1', circuit.gnd, 10@u_nF)  # C1 from N1 to ground
# Output node is 'Vout' by definition above
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)


node = 'Vout'
has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)
vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac)+1e-12)  # Avoid log(0)
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of Band-Stop Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)

plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Points')
plt.legend()

plt.tight_layout()
plt.savefig('p13_waveform.png')


min_gain_idx = np.argmin(gain_db)
min_gain = gain_db[min_gain_idx]
notch_freq = frequencies[min_gain_idx]

print(f"Minimum gain: {min_gain:.2f} dB at frequency {notch_freq:.2e} Hz")

relative_position = min_gain_idx / len(frequencies)
print(f"Relative position in frequency range: {relative_position:.2f}")

min_notch_depth = 10  # dB

low_gain_mask = gain_db < (min_gain + min_notch_depth/2)
high_gain_points = gain_db[~low_gain_mask]
avg_passband_gain = np.mean(high_gain_points) if len(high_gain_points) > 0 else 0

# Notch depth
notch_depth = avg_passband_gain - min_gain

print(f"Average passband gain: {avg_passband_gain:.2f} dB")
print(f"Calculated notch depth: {notch_depth:.2f} dB")

# Check if both sides have high gain regions
left_side = gain_db[:min_gain_idx]
right_side = gain_db[min_gain_idx+1:]

# If either side is too short, it may be a boundary stopband issue
min_side_length = max(5, len(gain_db) * 0.05)  # At least 5 points or 5% of the frequency range

if len(left_side) < min_side_length or len(right_side) < min_side_length:
    print("WARNING: Notch is very close to frequency range boundary.")

left_avg = np.mean(left_side) if len(left_side) >= min_side_length else None
right_avg = np.mean(right_side) if len(right_side) >= min_side_length else None

left_higher = (left_avg is not None) and (left_avg > min_gain + min_notch_depth)
right_higher = (right_avg is not None) and (right_avg > min_gain + min_notch_depth)

if left_avg is not None:
    print(f"Left side average gain: {left_avg:.2f} dB")
if right_avg is not None:
    print(f"Right side average gain: {right_avg:.2f} dB")

if notch_depth >= min_notch_depth and (left_higher and right_higher):
    print("PASS: This is a band-stop filter.")
    print(f"Notch frequency: {notch_freq:.2e} Hz")
    print(f"Notch depth: {notch_depth:.2f} dB")
    
    threshold = avg_passband_gain - 3
    
    if notch_depth > 30:
        print("This appears to be a deep notch filter.")
    
    sys.exit(0)
else:
    print("FAIL: This is NOT a band-stop filter.")
    
    if not (left_higher and right_higher):
        if left_higher and not right_higher:
            print("Only left side has high gain - may be a low-pass filter.")
        elif right_higher and not left_higher:
            print("Only right side has high gain - may be a high-pass filter.")
        else:
            print("Neither side shows significantly higher gain.")
    
    if notch_depth < min_notch_depth:
        print(f"The gain variation ({notch_depth:.2f} dB) is insufficient for a band-stop filter.")
    
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p38_Sample and Hold Circuit.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the circuit
circuit = Circuit('Sample and Hold Circuit')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)  # 5V power supply

# Define input signal (sinusoidal)
circuit.SinusoidalVoltageSource('input', 'Vin', circuit.gnd, 
                               amplitude=2.5@u_V,  # 2.5V amplitude
                               frequency=1@u_kHz)  # 1kHz frequency

# Define control signal (pulse for sampling)
circuit.PulseVoltageSource('control', 'Ctrl', circuit.gnd,
                          initial_value=0@u_V,      # Start at 0V
                          pulsed_value=5@u_V,       # Pulse to 5V
                          pulse_width=20@u_us,      # 20μs pulse width
                          period=100@u_us,          # 100μs period (10kHz)
                          rise_time=1@u_ns,         # Fast rise
                          fall_time=1@u_ns)         # Fast fall

# Define MOSFET as switch (NMOS)
circuit.MOSFET('M1', 'node1', 'Ctrl', 'Vin', circuit.gnd, model='NMOS')

# Define hold capacitor with initial condition
circuit.C('hold', 'node1', circuit.gnd, 10@u_nF, ic=0@u_V)  # 10nF capacitor with 0V initial condition

# Define buffer (source follower) to prevent loading of capacitor
circuit.MOSFET('M2', 'Vdd', 'node1', 'Vout', circuit.gnd, model='NMOS')
circuit.I('bias', 'Vout', circuit.gnd, 100@u_uA)  # 100μA current source bias

# MOSFET models
circuit.model('NMOS', 'nmos', 
              level=1,
              kp=120e-6,    # Transconductance parameter
              vto=0.7,      # Threshold voltage
              lambda_=0.02, # Channel-length modulation
              w=50e-6,      # Width
              l=1e-6)       # Length

# Setup simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Perform transient analysis
analysis = simulator.transient(
    step_time=0.1@u_us,    # 100ns step time
    end_time=3000@u_us,     # 500μs simulation time
)

# Plot results
plt.figure(figsize=(12, 8))

# Plot input signal
plt.subplot(3, 1, 1)
plt.plot(analysis.time*1e6, analysis['Vin'])  # Time in μs
plt.title('Input Signal')
plt.ylabel('Voltage (V)')
plt.grid(True)

# Plot control signal
plt.subplot(3, 1, 2)
plt.plot(analysis.time*1e6, analysis['Ctrl'])  # Time in μs
plt.title('Control Signal')
plt.ylabel('Voltage (V)')
plt.grid(True)

# Plot output signal
plt.subplot(3, 1, 3)
plt.plot(analysis.time*1e6, analysis['Vout'])  # Time in μs
plt.title('Output Signal (Sampled & Held)')
plt.xlabel('Time (μs)')
plt.ylabel('Voltage (V)')
plt.grid(True)

plt.tight_layout()
plt.show()

# Optional: Print some key measurements
print("Simulation completed successfully!")
print(f"Input signal frequency: 1 kHz")
print(f"Sampling frequency: 10 kHz")
print(f"Hold capacitor: 10 nF")

# === chipster/data/analog_datasets/AMS_RF_Dataset/p12_Passive Band-Pass Filter.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive Band-Pass Filter')
# Input voltage source (DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 1.0)  # 1V DC
# High-Pass Filter Stage
circuit.C('1', 'Vin', 'N1', 10@u_nF)      # C1: 10 nF
circuit.R('1', 'N1', circuit.gnd, 10@u_kΩ) # R1: 10 kΩ
# Low-Pass Filter Stage
circuit.R('2', 'N1', 'Vout', 10@u_kΩ)     # R2: 10 kΩ
circuit.C('2', 'Vout', circuit.gnd, 10@u_nF) # C2: 10 nF
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)

node = 'Vout'
has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)
vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac)+1e-12)  # Avoid log(0)
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of Band-Pass Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)

plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Points')
plt.legend()

plt.tight_layout()
plt.savefig('p12_waveform.png')

max_gain_idx = np.argmax(gain_db)
max_gain = gain_db[max_gain_idx]
peak_freq = frequencies[max_gain_idx]

print(f"Maximum gain: {max_gain:.2f} dB at frequency {peak_freq:.2e} Hz")

relative_position = max_gain_idx / len(frequencies)
print(f"Relative position in frequency range: {relative_position:.2f}")

min_peak_boost = 10  # dB

high_gain_mask = gain_db > (max_gain - min_peak_boost/2)
low_gain_points = gain_db[~high_gain_mask]
avg_stopband_gain = np.mean(low_gain_points) if len(low_gain_points) > 0 else 0

peak_boost = max_gain - avg_stopband_gain

print(f"Average stopband gain: {avg_stopband_gain:.2f} dB")
print(f"Calculated peak boost: {peak_boost:.2f} dB")

left_side = gain_db[:max_gain_idx]
right_side = gain_db[max_gain_idx+1:]

min_side_length = max(5, len(gain_db) * 0.05)

if len(left_side) < min_side_length or len(right_side) < min_side_length:
    print("WARNING: Peak is very close to frequency range boundary.")

left_avg = np.mean(left_side) if len(left_side) >= min_side_length else None
right_avg = np.mean(right_side) if len(right_side) >= min_side_length else None

left_lower = (left_avg is not None) and (left_avg < max_gain - min_peak_boost)
right_lower = (right_avg is not None) and (right_avg < max_gain - min_peak_boost)

if left_avg is not None:
    print(f"Left side average gain: {left_avg:.2f} dB")
if right_avg is not None:
    print(f"Right side average gain: {right_avg:.2f} dB")

if peak_boost >= min_peak_boost and (left_lower and right_lower):
    print("PASS: This is a band-pass filter.")
    print(f"Center frequency: {peak_freq:.2e} Hz")
    print(f"Peak gain: {max_gain:.2f} dB")
    print(f"Peak boost: {peak_boost:.2f} dB above stopband")
    
    threshold = max_gain - 3
    
    if peak_boost > 30:
        print("This appears to be a high-Q resonant band-pass filter.")
    
    sys.exit(0)
else:
    print("FAIL: This is NOT a band-pass filter.")
    
    if not (left_lower and right_lower):
        if left_lower and not right_lower:
            print("Only left side has low gain - may be a high-pass filter.")
        elif right_lower and not left_lower:
            print("Only right side has low gain - may be a low-pass filter.")
        else:
            print("Neither side shows significantly lower gain.")
    
    if peak_boost < min_peak_boost:
        print(f"The gain variation ({peak_boost:.2f} dB) is insufficient for a band-pass filter.")
    
    if relative_position < 0.1 or relative_position > 0.9:
        if relative_position < 0.1:
            print("Maximum gain is at the low frequency end - likely a low-pass filter.")
        else:
            print("Maximum gain is at the high frequency end - likely a high-pass filter.")
    
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p18_Single-Stage Differential Opamp with Resistive Loads.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Differential Opamp with Resistive Loads')
# Define NMOS model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input voltages (for DC operating point)
circuit.V('inp', 'Vinp', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 1.0 ac 1n")
# Bias voltage for tail current source
circuit.V('bias', 'Vbias', circuit.gnd, 1.0) # Vbias = Vth + 0.5V = 1.0V
# Differential Pair
# M1: Drain=Vout, Gate=Vinp, Source=SourceDiff, Bulk=SourceDiff
circuit.MOSFET('1', 'Vout', 'Vinp', 'SourceDiff', 'SourceDiff', model='nmos_model', w=50e-6, l=1e-6)
# M2: Drain=Drain2, Gate=Vinn, Source=SourceDiff, Bulk=SourceDiff
circuit.MOSFET('2', 'Drain2', 'Vinn', 'SourceDiff', 'SourceDiff', model='nmos_model', w=50e-6, l=1e-6)
# Tail current source
# Mtail: Drain=SourceDiff, Gate=Vbias, Source=0, Bulk=0
circuit.MOSFET('tail', 'SourceDiff', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=20e-6, l=1e-6)
# Load resistors
# R1: Vdd to Vout (drain of M1)
circuit.R('1', 'Vdd', 'Vout', 10@u_kΩ)
# R2: Vdd to Drain2 (drain of M2)
circuit.R('2', 'Vdd', 'Drain2', 10@u_kΩ)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p18_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p6_NMOS Inverter with Resistor Load.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('NMOS Inverter with Resistor Load')
# Define NMOS Model
circuit.model('nmos', 'nmos', level=1, kp=200e-6, vto=0.7)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Input node
# Vin will be a voltage source or a test signal, for now we set it as a DC source
circuit.V('in', 'Vin', circuit.gnd, 0@u_V)  # Can be varied during simulation
# Resistor R between Vdd and Vout
circuit.R('load', 'Vdd', 'Vout', 100@u_kΩ)  # 100kΩ resistor
# NMOS transistor M1
# Drain connected to Vout
# Gate connected to Vin
# Source connected to ground
circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos')
# The above assumes default width and length for the transistor
# For clarity, specify device parameters if needed
# For example:
# circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos', w=10e-6, l=1e-6)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p6_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

analysis = simulator.operating_point()
for node in analysis.nodes.values(): 
    print(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}")
vin_name = ""
for element in circuit.elements:
    for pin in element.pins:
        if "vin" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin_name = element.name
            break

circuit.element(vin_name).dc_value = "5"

simulator2 = circuit.simulator()
analysis2 = simulator2.operating_point()


node = 'vout'

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

vout2 = float(analysis2[node][0])

circuit.element(vin_name).dc_value = "0"

simulator3 = circuit.simulator()
analysis3 = simulator3.operating_point()

vout3 = float(analysis3[node][0])

import sys
if vout2 <= 2.5 and vout3 >= 2.5 and vout3 - vout2 >= 1.0:
    print("The circuit functions correctly.\n")
    sys.exit(0)

print("The circuit does not function correctly.\n"
    "It can not invert the input voltage.\n"
    f"When input is 5V, output is {vout2:.2f}V.\n"
    f"When input is 0V, output is {vout3:.2f}V.\n"
    "Please fix the wrong operating point.\n")

sys.exit(2)





# === chipster/data/analog_datasets/AMS_RF_Dataset/p26_Opamp Inverting Adder.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Inverting Adder')
# Power supply: 5V single supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Virtual ground/reference at 2.5V for opamp biasing
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltages (example DC values, you can set as needed)
circuit.V('in1', 'Vin1', circuit.gnd, 3@u_V)
circuit.V('in2', 'Vin2', circuit.gnd, 3@u_V)
# All resistors equal for unity gain from each input ---
R_value = 10@u_kΩ
# Both inputs connect through resistors to summing node 'Vsum' (inverting input) ---
circuit.R('1', 'Vin1', 'Vsum', R_value)  # Vin1 to Vsum
circuit.R('2', 'Vin2', 'Vsum', R_value)  # Vin2 to Vsum
# Feedback resistor from output to Vsum ---
circuit.R('f', 'Vout', 'Vsum', R_value)  # Vout to Vsum
# Non-inverting input of opamp connected to Vref (2.5V) ---
circuit.subcircuit(Opamp())
circuit.X('op', 'Opamp', 'Vref', 'Vsum', 'Vout')
# The circuit now forms a classic inverting adder:
# Vout = 2.5V - [(Vin1 - 2.5V) + (Vin2 - 2.5V)]
#      = -Vin1 - Vin2 + 5V
simulator = circuit.simulator()

bias_voltage = 2.5  # Set bias voltage to 2.5V
v1_amp = 3.0  # Original value from circuit
v2_amp = 3.0  # Original value from circuit
tolerance = 0.2  # 20% tolerance

# Testing approach: We'll run multiple tests to determine if the circuit functions as an adder

# Test 1: Get baseline with original values
simulator = circuit.simulator()
try:
    analysis_baseline = simulator.operating_point()
except Exception as e:
    print(f"DC analysis failed: {str(e)}")
    sys.exit(2)

baseline_output = float(analysis_baseline.Vout)
print(f"Baseline output: {baseline_output:.4f} V with Vin1 = {v1_amp:.4f} V, Vin2 = {v2_amp:.4f} V")

# Test 2: Change Vin1 and check effect
# First, find the Vin1 source to modify
vin1_found = False
for element in circuit.elements:
    if element.name.lower() == 'vin1' or (element.name.lower().startswith('v') and 'vin1' in [str(pin.node).lower() for pin in element.pins]):
        circuit.element(element.name).dc_value = v1_amp + 0.5
        vin1_found = True
        break

if not vin1_found:
    print("Could not find Vin1 source to modify")
    sys.exit(2)

# Run analysis with modified Vin1
simulator = circuit.simulator()
try:
    analysis_vin1_mod = simulator.operating_point()
except Exception as e:
    print(f"DC analysis failed with modified Vin1: {str(e)}")
    sys.exit(2)

vin1_mod_output = float(analysis_vin1_mod.Vout)
vin1_effect = vin1_mod_output - baseline_output
print(f"Effect of increasing Vin1 by 0.5V: {vin1_effect:.4f} V change in output")

# Reset Vin1 to original value
for element in circuit.elements:
    if element.name.lower() == 'vin1' or (element.name.lower().startswith('v') and 'vin1' in [str(pin.node).lower() for pin in element.pins]):
        circuit.element(element.name).dc_value = v1_amp
        break

# Test 3: Change Vin2 and check effect
vin2_found = False
for element in circuit.elements:
    if element.name.lower() == 'vin2' or (element.name.lower().startswith('v') and 'vin2' in [str(pin.node).lower() for pin in element.pins]):
        circuit.element(element.name).dc_value = v2_amp + 0.5
        vin2_found = True
        break

if not vin2_found:
    print("Could not find Vin2 source to modify")
    sys.exit(2)

# Run analysis with modified Vin2
simulator = circuit.simulator()
try:
    analysis_vin2_mod = simulator.operating_point()
except Exception as e:
    print(f"DC analysis failed with modified Vin2: {str(e)}")
    sys.exit(2)

vin2_mod_output = float(analysis_vin2_mod.Vout)
vin2_effect = vin2_mod_output - baseline_output
print(f"Effect of increasing Vin2 by 0.5V: {vin2_effect:.4f} V change in output")

# Verify adder properties
import sys
import numpy as np

# Check if inputs affect the output significantly
if abs(vin1_effect) < 0.05:
    print(f"The circuit is not an adder: Vin1 has minimal effect on output ({vin1_effect:.4f} V change)")
    sys.exit(2)

if abs(vin2_effect) < 0.05:
    print(f"The circuit is not an adder: Vin2 has minimal effect on output ({vin2_effect:.4f} V change)")
    sys.exit(2)

# For a proper inverting adder, increasing input should decrease output
if vin1_effect >= 0:
    print(f"The circuit is not an inverting adder: Increasing Vin1 does not decrease output (effect: {vin1_effect:.4f} V)")
    sys.exit(2)

if vin2_effect >= 0:
    print(f"The circuit is not an inverting adder: Increasing Vin2 does not decrease output (effect: {vin2_effect:.4f} V)")
    sys.exit(2)

# Check if inputs have similar effects (should be approximately equal for equal resistors)
effect_ratio = abs(vin1_effect / vin2_effect)
if not (1-tolerance <= effect_ratio <= 1+tolerance):
    print(f"The circuit has unbalanced input scaling: Vin1 effect = {vin1_effect:.4f} V, Vin2 effect = {vin2_effect:.4f} V")
    sys.exit(2)

# Collect additional test points to verify the adder behavior
test_points = [
    (2.5, 2.5),   # Both at reference
    (3.0, 2.5),   # Only Vin1 above reference
    (2.5, 3.0),   # Only Vin2 above reference
    (3.0, 3.0),   # Both above reference (baseline)
]

results = []
for v1, v2 in test_points:
    # Set Vin1
    for element in circuit.elements:
        if element.name.lower() == 'vin1' or (element.name.lower().startswith('v') and 'vin1' in [str(pin.node).lower() for pin in element.pins]):
            circuit.element(element.name).dc_value = v1
            break
    
    # Set Vin2
    for element in circuit.elements:
        if element.name.lower() == 'vin2' or (element.name.lower().startswith('v') and 'vin2' in [str(pin.node).lower() for pin in element.pins]):
            circuit.element(element.name).dc_value = v2
            break
    
    # Run analysis
    simulator = circuit.simulator()
    try:
        analysis = simulator.operating_point()
        vout = float(analysis.Vout)
        results.append((v1, v2, vout))
    except Exception as e:
        print(f"Analysis failed for Vin1 = {v1:.4f} V, Vin2 = {v2:.4f} V: {str(e)}")

# Calculate the adder's gain factor from data
input_diffs = []
output_diffs = []

for i in range(1, len(results)):
    v1, v2, vout = results[i]
    v1_ref, v2_ref, vout_ref = results[0]  # Reference point (both at 2.5V)
    
    input_diff = (v1 - bias_voltage) + (v2 - bias_voltage)
    output_diff = vout_ref - vout  # For inverting adder, output decreases as input increases
    
    if abs(input_diff) > 0.01:  # Avoid division by near-zero
        input_diffs.append(input_diff)
        output_diffs.append(output_diff)

# Calculate average gain factor
if input_diffs:
    gain_factors = [o/i for i, o in zip(input_diffs, output_diffs)]
    avg_gain = sum(gain_factors) / len(gain_factors)
else:
    avg_gain = 0.5  # Default fallback if we couldn't calculate

# Verify if output follows the adder formula with the determined gain
all_valid = True
for v1, v2, actual_vout in results:
    # Expected output based on inverting adder formula with measured gain
    expected_vout = bias_voltage - avg_gain * ((v1 - bias_voltage) + (v2 - bias_voltage))
    
    # Check if within tolerance
    if not np.isclose(actual_vout, expected_vout, rtol=tolerance):
        all_valid = False
        print(f"Output doesn't match formula at Vin1={v1:.2f}V, Vin2={v2:.2f}V:")
        print(f"  Expected: {expected_vout:.4f}V, Actual: {actual_vout:.4f}V")

if not all_valid:
    print("The circuit does not consistently follow the adder formula within 20% tolerance")
    sys.exit(2)

print("\nThe op-amp adder functions correctly!")
print(f"- Both inputs (Vin1 and Vin2) affect the output")
print(f"- Both have a negative (inverting) effect on the output")
print(f"- The input scaling is balanced (Vin1 effect ≈ Vin2 effect)")
print(f"- The output follows an inverting adder formula: Vout ≈ Vref - {avg_gain:.2f}*((Vin1-Vref) + (Vin2-Vref))")
print(f"- All test points are within {tolerance*100}% tolerance of the expected values")
sys.exit(0)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p21_Single-Stage Telescopic Cascode Opamp.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Telescopic Cascode Opamp')
# MOSFET Models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input sources (DC bias for now)
circuit.V('inp', 'Vinp', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 1.0 ac 1n")
# Bias voltages (choose values to ensure all devices are in saturation)
circuit.V('bias1', 'Vbias1', circuit.gnd, 0.7)   # Tail NMOS bias (Vgs > Vth)
circuit.V('bias2', 'Vbias2', circuit.gnd, 1.2)   # NMOS cascode bias (> Vth)
circuit.V('bias3', 'Vbias3', circuit.gnd, 4.0)   # PMOS load bias (Vdd - |Vth| - margin)
circuit.V('bias4', 'Vbias4', circuit.gnd, 3.5)   # PMOS cascode bias (Vdd - |Vth| - margin)
# Tail current source NMOS
circuit.MOSFET('9', 'S_tail', 'Vbias1', circuit.gnd, circuit.gnd, model='nmos_model', w=30e-6, l=1e-6)
# Differential input NMOS
circuit.MOSFET('1', 'N1', 'Vinp', 'S_tail', 'S_tail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'N2', 'Vinn', 'S_tail', 'S_tail', model='nmos_model', w=50e-6, l=1e-6)
# NMOS cascode
circuit.MOSFET('3', 'Voutp', 'Vbias2', 'N1', 'N1', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Vout', 'Vbias2', 'N2', 'N2', model='nmos_model', w=50e-6, l=1e-6)
# PMOS active load
circuit.MOSFET('5', 'Voutp', 'Vbias3', 'S5', 'S5', model='pmos_model', w=70e-6, l=1e-6)
circuit.MOSFET('6', 'Vout', 'Vbias3', 'S6', 'S6', model='pmos_model', w=70e-6, l=1e-6)
# PMOS cascode
circuit.MOSFET('7', 'S5', 'Vbias4', 'Vdd', 'Vdd', model='pmos_model', w=70e-6, l=1e-6)
circuit.MOSFET('8', 'S6', 'Vbias4', 'Vdd', 'Vdd', model='pmos_model', w=70e-6, l=1e-6)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p21_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p20_Two-Stage Differential Opamp.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Two-Stage Differential Opamp')
# MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Differential inputs
circuit.V('inp', 'Vinp', circuit.gnd, "dc 2.5 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 2.5 ac 1n")
# Bias voltages
circuit.V('b1', 'Vbias1', circuit.gnd, 1.0)   # NMOS bias
circuit.V('b2', 'Vbias2', circuit.gnd, 4.0)   # PMOS current mirror bias
circuit.V('b3', 'Vbias3', circuit.gnd, 4.0)   # PMOS second stage bias
# First Stage: Differential pair with current mirror load and tail current
circuit.MOSFET('1', 'Voutp', 'Vinp', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Outn', 'Vinn', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('3', 'Stail', 'Vbias1', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Voutp', 'Vbias2', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('5', 'Outn', 'Vbias2', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Second Stage: Common-source with active load
circuit.MOSFET('6', 'Vout', 'Voutp', circuit.gnd, circuit.gnd, model='nmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('7', 'Vout', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# PMOS bias diode for M7, with resistor to ground to ensure V_DS > 0
circuit.MOSFET('8', 'Nbias', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.R('b', 'Nbias', circuit.gnd, 10@u_kΩ)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p20_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p37_Voltage Controlled Oscillator.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the VCO circuit
circuit = Circuit('Voltage Controlled Oscillator')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=2500@u_ns,
    period=2500@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Control voltage source (sweep from 0V to 3.3V)
circuit.PulseVoltageSource('ctrl', 'v_control', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=5@u_ns,
    rise_time=500@u_ns,
    fall_time=500@u_ns,
    pulse_width=1000@u_ns,
    period=2000@u_ns
)

# Add control voltage protection and filtering
circuit.R('Rctrl', 'v_control', 'v_control_int', 100@u_Ω)
circuit.C('Cctrl', 'v_control_int', circuit.gnd, 0.1@u_pF)

# Current mirror bias circuit
circuit.MOSFET('M1', 'bias', 'bias', circuit.gnd, circuit.gnd, model='NMOS')
circuit.R('Rbias', 'vdd_internal', 'bias', 10@u_kΩ)
circuit.C('Cbias', 'bias', circuit.gnd, 0.1@u_pF)

# Voltage-controlled current source
circuit.MOSFET('M2', 'i_ctrl', 'v_control_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M3', 'i_ctrl', 'bias', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('Ci_ctrl', 'i_ctrl', circuit.gnd, 0.1@u_pF)

# Ring oscillator stages with parasitic capacitance
for i in range(1, 4):
    prev_stage = f'stage{3 if i == 1 else i-1}'
    curr_stage = f'stage{i}'
    
    # PMOS
    circuit.MOSFET(f'Mp{i}', curr_stage, prev_stage, 'vdd_internal', 'vdd_internal', model='PMOS')
    # NMOS
    circuit.MOSFET(f'Mn{i}', curr_stage, prev_stage, 'i_ctrl', circuit.gnd, model='NMOS')
    # Load capacitance
    circuit.C(f'C{i}', curr_stage, circuit.gnd, 0.1@u_pF)
    # Weak pull-up for initialization
    circuit.R(f'Rpu{i}', curr_stage, 'vdd_internal', 1@u_MΩ)

# Output buffer
circuit.MOSFET('M10', 'vco_out', 'stage3', 'vdd_internal', 'vdd_internal', model='PMOS_BUF')
circuit.MOSFET('M11', 'vco_out', 'stage3', circuit.gnd, circuit.gnd, model='NMOS_BUF')
circuit.C('Cout', 'vco_out', circuit.gnd, 0.1@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=4e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=12e-6,
    l=0.35e-6
)

# Buffer transistors (larger size for driving output load)
circuit.model('NMOS_BUF', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=8e-6,
    l=0.35e-6
)

circuit.model('PMOS_BUF', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=24e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=2000@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    vctrl = np.array([float(v) for v in analysis['v_control']])
    vout = np.array([float(v) for v in analysis['vco_out']])

    # Create figure with multiple subplots
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 12))

    # Plot control voltage
    ax1.plot(time, vctrl, label='Control Voltage', color='blue')
    ax1.grid(True)
    ax1.set_title('VCO Control Voltage')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot output waveform
    ax2.plot(time, vout, label='VCO Output', color='red')
    ax2.grid(True)
    ax2.set_title('VCO Output Waveform')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    # Calculate and plot instantaneous frequency
    def calculate_frequency(time, signal, window_size=100):
        frequencies = []
        times = []
        control_voltages = []
        
        for i in range(0, len(time)-window_size, window_size//2):
            window = signal[i:i+window_size]
            t_window = time[i:i+window_size]
            
            # Count zero crossings
            crossings = np.where(np.diff(window > np.mean(window)))[0]
            if len(crossings) >= 2:
                period = 2 * np.mean(np.diff(t_window[crossings]))
                freq = 1.0 / period if period > 0 else 0
                frequencies.append(freq)
                times.append(np.mean(t_window))
                control_voltages.append(np.mean(vctrl[i:i+window_size]))
        
        return np.array(times), np.array(frequencies), np.array(control_voltages)

    # Calculate frequencies and plot
    t_freq, freqs, v_ctrl = calculate_frequency(time, vout)
    
    if len(t_freq) > 0:
        # Plot frequency vs control voltage
        ax3.plot(v_ctrl, freqs/1e6, 'o-', label='Tuning Characteristic', color='green')
        ax3.grid(True)
        ax3.set_title('VCO Tuning Characteristic')
        ax3.set_xlabel('Control Voltage (V)')
        ax3.set_ylabel('Frequency (MHz)')
        ax3.legend()

        # Print VCO characteristics
        if len(freqs) > 1:
            freq_range = np.ptp(freqs)
            voltage_range = np.ptp(v_ctrl)
            kvco = freq_range / voltage_range if voltage_range > 0 else 0
            print(f"VCO Characteristics:")
            print(f"Frequency Range: {np.min(freqs)/1e6:.2f} MHz to {np.max(freqs)/1e6:.2f} MHz")
            print(f"Average Kvco: {kvco/1e6:.2f} MHz/V")

    plt.tight_layout()
    plt.show()

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p1_Single-Stage Common-Source Amplifier with Resistor Load.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Common-Source Amplifier with Resistor Load')
# Define the NMOS model with typical parameters
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V Vdd
# Input voltage source with bias above threshold to activate M1
circuit.V('in', 'Vin', circuit.gnd, "dc 1.0 ac 1n")
# Load resistor R
circuit.R('load', 'Vout', 'Vdd', 10@u_kΩ)  # 10kΩ resistor
# NMOS transistor M1
# Drain connected to Vout node
# Gate connected to Vin
# Source connected to ground
circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd,
               model='nmos_model', w=50e-6, l=1e-6)
# The circuit is now complete; the output is at Vout node
# No further code needed after this line
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p1_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p23_Wien Bridge Oscillator.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('RC Phase Shift Oscillator')
# Power supplies
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)  # Virtual ground at Vdd/2
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Connect non-inverting input to Vref (2.5V)
# The inverting input will be connected to the RC network and feedback resistor
# Output node is 'Vout'
# RC phase shift network (three stages)
circuit.R('1', 'Vout', 'N1', 10@u_kΩ)
circuit.C('1', 'N1', 'Vref', 10@u_nF)
circuit.R('2', 'N1', 'N2', 10@u_kΩ)
circuit.C('2', 'N2', 'Vref', 10@u_nF)
circuit.R('3', 'N2', 'N3', 10@u_kΩ)
circuit.C('3', 'N3', 'Vref', 10@u_nF)
# Feedback resistor from output to inverting input (Vinn)
circuit.R('f', 'Vout', 'Vinn', 330@u_kΩ)
# The RC network output connects to the inverting input
circuit.R('in', 'N3', 'Vinn', 1@u_Ω)  # Virtually a wire (for node naming clarity)
# Create opamp instance
circuit.X('1', 'Opamp', 'Vref', 'Vinn', 'Vout')
simulator = circuit.simulator()
del_vname = []
for element in circuit.elements:
    v_name = element.name
    if element.name.lower().startswith("v") and "bias" not in element.name.lower() and "ref" not in element.name.lower():
        del_vname.append(v_name)

pin_name = "Vinp"
pin_name_n = "Vinn"
for element in circuit.elements:
    if element.name.lower().startswith("x"):
        opamp_element = element
        pin_name = str(opamp_element.pins[0].node)
        pin_name_n = str(opamp_element.pins[1].node)
        break

params = {pin_name: 2.51, pin_name_n: 2.5}

simulator = circuit.simulator()
simulator.initial_condition(**params)

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=20@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

node = 'Vout'
# find any node with "vout"
has_node = False
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            node = str(pin.node)
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

import numpy as np
# Get the output node voltage
vout = np.array(analysis[node])

vlist = {}
for node_name in analysis.nodes.keys():
    vlist[node_name.lower()] = np.array(analysis[node_name])

time = np.array(analysis.time)

from scipy.signal import find_peaks, firwin, lfilter
import sys
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter, FormatStrFormatter

fig, axs = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

key_output = node.lower()
axs[0].plot(time, vlist[key_output], color='darkgreen', linewidth=3, label=key_output)
axs[0].set_title('Output Signal', fontsize=16)
axs[0].set_ylabel('Voltage [V]', fontsize=14)
axs[0].tick_params(axis='both', which='major', labelsize=12)
axs[0].grid(True, linestyle='--', alpha=0.7)
axs[0].legend(fontsize=12, loc='best')

axs[0].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))


feedback_node = None
ref_node = None
input_nodes = []

for node_name in vlist.keys():
    if 'feedback' in node_name or 'fb' in node_name:
        feedback_node = node_name
    elif 'ref' in node_name or 'vref' in node_name:
        ref_node = node_name
    elif node_name in [pin_name.lower(), pin_name_n.lower()]:
        input_nodes.append(node_name)
    elif ('in' in node_name or 'node' in node_name) and node_name != key_output:
        input_nodes.append(node_name)

if not input_nodes:
    for node_name in vlist.keys():
        if (node_name != key_output and 
            node_name != feedback_node and 
            node_name != ref_node and
            'vdd' not in node_name and 
            'vcc' not in node_name and
            'bias' not in node_name):
            input_nodes.append(node_name)
            if len(input_nodes) >= 3:
                break

if feedback_node:
    axs[1].plot(time, vlist[feedback_node], color='crimson', linewidth=2.5, label=feedback_node)
if ref_node:
    axs[1].plot(time, vlist[ref_node], color='navy', linewidth=2.5, label=ref_node)

colors = ['darkorange', 'purple', 'teal', 'olive', 'brown']
for i, node_name in enumerate(input_nodes):
    axs[1].plot(time, vlist[node_name], color=colors[i % len(colors)], linewidth=2, label=node_name)

axs[1].set_title('Input, Reference and Feedback Signals', fontsize=16)
axs[1].set_xlabel('Time [s]', fontsize=14)
axs[1].set_ylabel('Voltage [V]', fontsize=14)
axs[1].tick_params(axis='both', which='major', labelsize=12)
axs[1].grid(True, linestyle='--', alpha=0.7)
axs[1].legend(fontsize=12, loc='best')

axs[1].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))

vout_min = np.min(vlist[key_output])
vout_max = np.max(vlist[key_output])
vout_range = vout_max - vout_min
axs[0].set_ylim([vout_min - 0.1 * vout_range, vout_max + 0.1 * vout_range])

all_values = []
if feedback_node:
    all_values.extend(vlist[feedback_node])
if ref_node:
    all_values.extend(vlist[ref_node])
for node_name in input_nodes:
    all_values.extend(vlist[node_name])

if all_values:
    y_min = np.min(all_values)
    y_max = np.max(all_values)
    y_range = y_max - y_min
    axs[1].set_ylim([y_min - 0.1 * y_range, y_max + 0.1 * y_range])

axs[1].xaxis.set_major_formatter(FormatStrFormatter('%.4f'))

plt.tight_layout()
plt.savefig('p22_waveform.png', dpi=300)


def detect_oscillation_start(vout, time, threshold=0.001):
    dvout = np.abs(np.diff(vout))
    window_size = len(dvout) // 50
    window_size = max(window_size, 10)
    
    std_values = []
    for i in range(window_size, len(dvout)):
        window = dvout[i-window_size:i]
        std_values.append(np.std(window))
    
    std_values = np.array(std_values)
    threshold_value = threshold * np.max(std_values)
    start_indices = np.where(std_values > threshold_value)[0]
    
    if len(start_indices) > 0:
        oscillation_start_idx = start_indices[0] + window_size
        oscillation_start_idx = min(oscillation_start_idx, len(time)-1)
        return oscillation_start_idx
    else:
        return int(len(time) * 0.7)

def analyze_last_section(vout, time, fraction=0.3):
    start_idx = int(len(time) * (1 - fraction))
    return vout[start_idx:], time[start_idx:]

last_vout, last_time = analyze_last_section(vout, time, 0.3)

peaks, _ = find_peaks(last_vout)
troughs, _ = find_peaks(-last_vout)

error = 0

if len(peaks) > 2 and len(troughs) > 2:
    amplitudes = []
    
    for peak in peaks:
        nearest_trough_idx = np.argmin(np.abs(troughs - peak))
        nearest_trough = troughs[nearest_trough_idx]
        amplitude = np.abs(last_vout[peak] - last_vout[nearest_trough])
        amplitudes.append(amplitude)
    
    amplitudes = np.array(amplitudes)
    
    peak_times = last_time[peaks]
    periods = np.diff(peak_times)
    
    if len(periods) > 2:
        average_period = np.mean(periods)
        period_variation = np.std(periods) / average_period
        
        print(f"Detected {len(peaks)} peaks in the oscillation section")
        print(f"Average oscillation period: {average_period:.6f} s")
        print(f"Maximum amplitude: {np.max(amplitudes):.6f} V")
        
        if period_variation < 0.2:
            print("The oscillator works correctly and produces periodic oscillations")
        else:
            print("Periodicity is inconsistent, oscillation may not be ideal")
            error = 1
    else:
        print("Not enough peaks detected to determine periodicity")
        error = 1
else:
    print("Not enough peaks and troughs detected in the latter part to analyze oscillation")
    error = 1

if error == 1:
    sys.exit(2)
else:
    sys.exit(0)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p34_CMOS Full Adder.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the Full Adder circuit
circuit = Circuit('CMOS Full Adder')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=200@u_ns,
    period=200@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delays to ensure power-up completes first
# Input A
circuit.PulseVoltageSource('inA', 'A', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B
circuit.PulseVoltageSource('inB', 'B', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Carry In
circuit.PulseVoltageSource('inCin', 'Cin', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=10@u_ns,
    period=20@u_ns
)

# Add input protection and parasitic capacitance
for node in ['A', 'B', 'Cin']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# XOR gate for A ⊕ B
# NAND1
circuit.MOSFET('M1', 'nand1_out', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'nand1_out', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M3', 'nand1_out', 'A_int', 'nand1_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M4', 'nand1_n', 'B_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C1', 'nand1_out', circuit.gnd, 0.1@u_pF)

# Additional NANDs for XOR implementation
circuit.MOSFET('M5', 'xor_out', 'nand1_out', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'xor_out', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M7', 'xor_out', 'nand1_out', 'xor_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M8', 'xor_n', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C2', 'xor_out', circuit.gnd, 0.1@u_pF)

# Second XOR for Sum (XOR with Cin)
circuit.MOSFET('M9', 'sum_int', 'xor_out', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M10', 'sum_int', 'Cin_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M11', 'sum_int', 'xor_out', 'sum_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M12', 'sum_n', 'Cin_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C3', 'sum_int', circuit.gnd, 0.1@u_pF)

# Carry Out logic
circuit.MOSFET('M13', 'cout_int', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M14', 'cout_int', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M15', 'cout_int', 'Cin_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M16', 'cout_int', 'A_int', 'cout_n1', circuit.gnd, model='NMOS')
circuit.MOSFET('M17', 'cout_n1', 'B_int', 'cout_n2', circuit.gnd, model='NMOS')
circuit.MOSFET('M18', 'cout_n2', 'Cin_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C4', 'cout_int', circuit.gnd, 0.1@u_pF)

# Output buffers
circuit.MOSFET('M19', 'Sum', 'sum_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M20', 'Sum', 'sum_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C5', 'Sum', circuit.gnd, 0.1@u_pF)

circuit.MOSFET('M21', 'Cout', 'cout_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M22', 'Cout', 'cout_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C6', 'Cout', circuit.gnd, 0.1@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=10@u_ns,
        end_time=100@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data
    time = np.array([float(t) for t in analysis.time])
    va = np.array([float(v) for v in analysis['A']])
    vb = np.array([float(v) for v in analysis['B']])
    vcin = np.array([float(v) for v in analysis['Cin']])
    vsum = np.array([float(v) for v in analysis['Sum']])
    vcout = np.array([float(v) for v in analysis['Cout']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, va, label='A', linestyle='--')
    ax1.plot(time, vb, label='B', linestyle='--')
    ax1.plot(time, vcin, label='Cin', linestyle='--')
    ax1.grid(True)
    ax1.set_title('Full Adder - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs
    ax2.plot(time, vsum, label='Sum')
    ax2.plot(time, vcout, label='Cout')
    ax2.grid(True)
    ax2.set_title('Full Adder - Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Verify functionality
    def analyze_full_adder(time, va, vb, vcin, vsum, vcout, vth=1.65):
        """Verify full adder logic and calculate delays"""
        def to_binary(v):
            return 1 if v > vth else 0
        
        def find_transitions(time, signal):
            binary = [to_binary(v) for v in signal]
            transitions = []
            for i in range(1, len(binary)):
                if binary[i] != binary[i-1]:
                    transitions.append(time[i])
            return transitions
        
        # Calculate propagation delays
        a_trans = find_transitions(time, va)
        sum_trans = find_transitions(time, vsum)
        cout_trans = find_transitions(time, vcout)
        
        if a_trans and sum_trans:
            sum_delay = min(abs(st - at) for st in sum_trans for at in a_trans)
            print(f"Average Sum propagation delay: {sum_delay:.2e} seconds")
        
        if a_trans and cout_trans:
            cout_delay = min(abs(ct - at) for ct in cout_trans for at in a_trans)
            print(f"Average Cout propagation delay: {cout_delay:.2e} seconds")

    analyze_full_adder(time, va, vb, vcin, vsum, vcout)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p14_Two-Stage Amplifier with Miller Compensation.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Two-Stage Amplifier with Miller Compensation')
# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Define bias voltage for active load
circuit.V('bias', 'Vbias', circuit.gnd, 2.5@u_V)
# Transistor models
circuit.model('nmos', 'nmos', level=1, vto=0.5, kp=100e-6)
circuit.model('pmos', 'pmos', level=1, vto=-0.5, kp=50e-6)
# First Stage: NMOS common-source with PMOS active load
# M1: NMOS input transistor
circuit.MOSFET('M1', 'Vmid', 'Vin', 'gnd', 'gnd', model='nmos', w=10e-6, l=1e-6)
# M2: PMOS active load
circuit.MOSFET('M2', 'Vmid', 'Vbias', 'Vdd', 'Vdd', model='pmos', w=20e-6, l=1e-6)
# Second Stage: NMOS common-source
circuit.MOSFET('M3', 'Vout', 'Vmid', 'gnd', 'gnd', model='nmos', w=10e-6, l=1e-6)
# Load resistor for second stage
circuit.R('load', 'Vout', 'Vdd', 10@u_kΩ)
# Miller Compensation Capacitor
circuit.C('miller', 'Vmid', 'Vout', 1@u_pF)
# Input source
circuit.V('in', 'Vin', circuit.gnd, "dc 1@u_V ac 1n")
# Connect all components properly
# (Connections are made via node names above)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p14_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p22_RC Phase Shift Oscillator.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('RC Phase Shift Oscillator')
# Power supplies
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)  # Virtual ground at Vdd/2
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Connect non-inverting input to Vref (2.5V)
# The inverting input will be connected to the RC network and feedback resistor
# Output node is 'Vout'
# RC phase shift network (three stages)
circuit.R('1', 'Vout', 'N1', 10@u_kΩ)
circuit.C('1', 'N1', 'Vref', 10@u_nF)
circuit.R('2', 'N1', 'N2', 10@u_kΩ)
circuit.C('2', 'N2', 'Vref', 10@u_nF)
circuit.R('3', 'N2', 'N3', 10@u_kΩ)
circuit.C('3', 'N3', 'Vref', 10@u_nF)
# Feedback resistor from output to inverting input (Vinn)
circuit.R('f', 'Vout', 'Vinn', 330@u_kΩ)
# The RC network output connects to the inverting input
circuit.R('in', 'N3', 'Vinn', 1@u_Ω)  # Virtually a wire (for node naming clarity)
# Create opamp instance
circuit.X('1', 'Opamp', 'Vref', 'Vinn', 'Vout')
simulator = circuit.simulator()
del_vname = []
for element in circuit.elements:
    v_name = element.name
    if element.name.lower().startswith("v") and "bias" not in element.name.lower() and "ref" not in element.name.lower():
        del_vname.append(v_name)

pin_name = "Vinp"
pin_name_n = "Vinn"
for element in circuit.elements:
    if element.name.lower().startswith("x"):
        opamp_element = element
        pin_name = str(opamp_element.pins[0].node)
        pin_name_n = str(opamp_element.pins[1].node)
        break

params = {pin_name: 2.51, pin_name_n: 2.5}

simulator = circuit.simulator()
simulator.initial_condition(**params)

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=20@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

node = 'Vout'
# find any node with "vout"
has_node = False
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            node = str(pin.node)
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

import numpy as np
# Get the output node voltage
vout = np.array(analysis[node])

vlist = {}
for node_name in analysis.nodes.keys():
    vlist[node_name.lower()] = np.array(analysis[node_name])

time = np.array(analysis.time)

from scipy.signal import find_peaks, firwin, lfilter
import sys
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter, FormatStrFormatter

fig, axs = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

key_output = node.lower()
axs[0].plot(time, vlist[key_output], color='darkgreen', linewidth=3, label=key_output)
axs[0].set_title('Output Signal', fontsize=16)
axs[0].set_ylabel('Voltage [V]', fontsize=14)
axs[0].tick_params(axis='both', which='major', labelsize=12)
axs[0].grid(True, linestyle='--', alpha=0.7)
axs[0].legend(fontsize=12, loc='best')

axs[0].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))


feedback_node = None
ref_node = None
input_nodes = []

for node_name in vlist.keys():
    if 'feedback' in node_name or 'fb' in node_name:
        feedback_node = node_name
    elif 'ref' in node_name or 'vref' in node_name:
        ref_node = node_name
    elif node_name in [pin_name.lower(), pin_name_n.lower()]:
        input_nodes.append(node_name)
    elif ('in' in node_name or 'node' in node_name) and node_name != key_output:
        input_nodes.append(node_name)

if not input_nodes:
    for node_name in vlist.keys():
        if (node_name != key_output and 
            node_name != feedback_node and 
            node_name != ref_node and
            'vdd' not in node_name and 
            'vcc' not in node_name and
            'bias' not in node_name):
            input_nodes.append(node_name)
            if len(input_nodes) >= 3:
                break

if feedback_node:
    axs[1].plot(time, vlist[feedback_node], color='crimson', linewidth=2.5, label=feedback_node)
if ref_node:
    axs[1].plot(time, vlist[ref_node], color='navy', linewidth=2.5, label=ref_node)

colors = ['darkorange', 'purple', 'teal', 'olive', 'brown']
for i, node_name in enumerate(input_nodes):
    axs[1].plot(time, vlist[node_name], color=colors[i % len(colors)], linewidth=2, label=node_name)

axs[1].set_title('Input, Reference and Feedback Signals', fontsize=16)
axs[1].set_xlabel('Time [s]', fontsize=14)
axs[1].set_ylabel('Voltage [V]', fontsize=14)
axs[1].tick_params(axis='both', which='major', labelsize=12)
axs[1].grid(True, linestyle='--', alpha=0.7)
axs[1].legend(fontsize=12, loc='best')

axs[1].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))

vout_min = np.min(vlist[key_output])
vout_max = np.max(vlist[key_output])
vout_range = vout_max - vout_min
axs[0].set_ylim([vout_min - 0.1 * vout_range, vout_max + 0.1 * vout_range])

all_values = []
if feedback_node:
    all_values.extend(vlist[feedback_node])
if ref_node:
    all_values.extend(vlist[ref_node])
for node_name in input_nodes:
    all_values.extend(vlist[node_name])

if all_values:
    y_min = np.min(all_values)
    y_max = np.max(all_values)
    y_range = y_max - y_min
    axs[1].set_ylim([y_min - 0.1 * y_range, y_max + 0.1 * y_range])

axs[1].xaxis.set_major_formatter(FormatStrFormatter('%.4f'))

plt.tight_layout()
plt.savefig('p22_waveform.png', dpi=300)


def detect_oscillation_start(vout, time, threshold=0.001):
    dvout = np.abs(np.diff(vout))
    window_size = len(dvout) // 50
    window_size = max(window_size, 10)
    
    std_values = []
    for i in range(window_size, len(dvout)):
        window = dvout[i-window_size:i]
        std_values.append(np.std(window))
    
    std_values = np.array(std_values)
    threshold_value = threshold * np.max(std_values)
    start_indices = np.where(std_values > threshold_value)[0]
    
    if len(start_indices) > 0:
        oscillation_start_idx = start_indices[0] + window_size
        oscillation_start_idx = min(oscillation_start_idx, len(time)-1)
        return oscillation_start_idx
    else:
        return int(len(time) * 0.7)

def analyze_last_section(vout, time, fraction=0.3):
    start_idx = int(len(time) * (1 - fraction))
    return vout[start_idx:], time[start_idx:]

last_vout, last_time = analyze_last_section(vout, time, 0.3)

peaks, _ = find_peaks(last_vout)
troughs, _ = find_peaks(-last_vout)

error = 0

if len(peaks) > 2 and len(troughs) > 2:
    amplitudes = []
    
    for peak in peaks:
        nearest_trough_idx = np.argmin(np.abs(troughs - peak))
        nearest_trough = troughs[nearest_trough_idx]
        amplitude = np.abs(last_vout[peak] - last_vout[nearest_trough])
        amplitudes.append(amplitude)
    
    amplitudes = np.array(amplitudes)
    
    peak_times = last_time[peaks]
    periods = np.diff(peak_times)
    
    if len(periods) > 2:
        average_period = np.mean(periods)
        period_variation = np.std(periods) / average_period
        
        print(f"Detected {len(peaks)} peaks in the oscillation section")
        print(f"Average oscillation period: {average_period:.6f} s")
        print(f"Maximum amplitude: {np.max(amplitudes):.6f} V")
        
        if period_variation < 0.2:
            print("The oscillator works correctly and produces periodic oscillations")
        else:
            print("Periodicity is inconsistent, oscillation may not be ideal")
            error = 1
    else:
        print("Not enough peaks detected to determine periodicity")
        error = 1
else:
    print("Not enough peaks and troughs detected in the latter part to analyze oscillation")
    error = 1

if error == 1:
    sys.exit(2)
else:
    sys.exit(0)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p25_Opamp Differentiator.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Differentiator')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Reference voltage for virtual ground
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltage (set to DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 3@u_V)
# Opamp subcircuit
circuit.subcircuit(Opamp())
# Differentiator components
circuit.C('1', 'Vin', 'Ninv', 10@u_nF)      # C1: input capacitor
circuit.R('f', 'Vout', 'Ninv', 10@u_kΩ)     # Rf: feedback resistor
circuit.R('b', 'Ninv', 'Vref', 1@u_MΩ)      # Rb: bias resistor for DC stability
# Opamp connections
circuit.X('op', 'Opamp', 'Vref', 'Ninv', 'Vout')
simulator = circuit.simulator()
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

bias_voltage = 2.5

# Detach the previous Vin if it exists and attach a new triangular wave source
if vin_name != "":
    circuit.element(vin_name).detach()
    circuit.V('tri', 'Vin', circuit.gnd, f"PULSE({bias_voltage-0.5} {bias_voltage+0.5} 0 50m 50m 1n 100m)")
else:
    circuit.V('in', 'Vin', circuit.gnd, f"PULSE({bias_voltage-0.5} {bias_voltage+0.5} 0 50m 50m 1n 100m)")

# Adjust R1 resistance if needed
for element in circuit.elements:
    if element.name.lower().startswith("rf") or element.name.lower().startswith("rrf") or element.name.lower().startswith("r1"):
        r_name = element.name
circuit.element(r_name).resistance = "10k"

# Adjust C1 capacitance if needed
for element in circuit.elements:
    if element.name.lower().startswith("c1") or element.name.lower().startswith("cc1"):
        c_name = element.name
circuit.element(c_name).capacitance = "3u"

# Initialize the simulator
simulator = circuit.simulator()

import sys
# Perform transient analysis
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

import numpy as np
vlist = {}
for node in analysis.nodes.values():
    vlist[node.name] = np.array(analysis[node.name])

import numpy as np
# Extract data from the analysis
time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

plt.rcParams.update({
    'font.size': 12,
    'axes.titlesize': 16,
    'axes.labelsize': 14,
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    'legend.fontsize': 11,
    'lines.linewidth': 2.5
})

# Plot the response
plt.figure(figsize=(12, 8))

colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#6A994E', '#7209B7', '#F72585', 
          '#264653', '#2A9D8F', '#E9C46A', '#F4A261', '#E76F51', '#8E44AD', '#3498DB',
          '#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#34495E', '#E67E22']

linestyles = ['-', '--', '-.', ':', '-', '--', '-.', '-', '--', '-.', ':', 
              '-', '--', '-.', ':', '-', '--', '-.', ':', '-', '--']

for i, node in enumerate(analysis.nodes.values()):
    plt.plot(time, vlist[node.name], 
             color=colors[i % len(colors)], 
             linestyle=linestyles[i % len(linestyles)],
             linewidth=2.5,
             label=node.name,
             alpha=0.9)


plt.title('Transient Response of Op-amp Differentiator', fontsize=16, fontweight='bold', pad=20)
plt.xlabel('Time [s]', fontsize=14, fontweight='semibold')
plt.ylabel('Voltage [V]', fontsize=14, fontweight='semibold')

plt.grid(True, linestyle='--', alpha=0.6, color='gray', linewidth=0.8)

plt.legend(frameon=True, fancybox=True, shadow=True, ncol=2, 
           loc='best', framealpha=0.9, edgecolor='black')

ax = plt.gca()
ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
ax.xaxis.set_major_formatter(FormatStrFormatter('%.3f'))

for spine in ax.spines.values():
    spine.set_visible(True)
    spine.set_linewidth(1.2)
    spine.set_color('black')

plt.tick_params(axis='both', which='major', direction='out', length=6, width=1.2)
plt.tick_params(axis='both', which='minor', direction='out', length=4, width=1)

plt.tight_layout()
plt.savefig("p25_waveform.png", dpi=300, bbox_inches='tight', facecolor='white')

from scipy.signal import find_peaks
# Check for square wave characteristics in the output
# Calculate the mean voltage level of the peaks and troughs

min_height = (max(vout) + min(vout)) / 2
num_of_peaks = 2
min_distance = len(vout) / (2 * num_of_peaks) / 1.5 

peaks, _ = find_peaks(vout, height=min_height, distance=min_distance)
troughs, _ = find_peaks(-vout, height=-min_height, distance=min_distance)

average_peak_voltage = np.mean(vout[peaks])
average_trough_voltage = np.mean(vout[troughs])

if len(peaks) == 0 or len(troughs) == 0:
    print("No peaks or troughs found in output voltage. Please check the netlist.")
    sys.exit(2)

peak_voltages = vout[peaks]
trough_voltages = vout[troughs]
mean_peak = np.mean(peak_voltages)
mean_trough = np.mean(trough_voltages)

def is_square_wave(waveform, mean_peak, mean_trough, rtol=0.1):
    high_level = np.mean([x for x in waveform if x > (mean_peak + mean_trough) / 2])
    low_level = np.mean([x for x in waveform if x <= (mean_peak + mean_trough) / 2])
    is_high_close = np.isclose(high_level, mean_peak, rtol=rtol)
    is_low_close = np.isclose(low_level, mean_trough, rtol=rtol)
    return is_high_close and is_low_close

# Check if the output is approximately a square wave by comparing the mean of the peaks and troughs
if np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2) and \
     np.isclose(mean_peak - bias_voltage, 0.6, rtol=0.2) and \
     is_square_wave(vout, mean_peak, mean_trough):  # 20% tolerance
    pass
elif not np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2):
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"When the input is a triangle wave and the output is not a square wave.\n")
    sys.exit(2)
elif not is_square_wave(vout, mean_peak, mean_trough):
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"When the input is a triangle wave and the output is not a square wave.\n")
    sys.exit(2)
else:
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"Output voltage peak value is wrong. Mean peak voltage: {mean_peak} V | Mean trough voltage: {mean_trough} V\n")
    sys.exit(2)

for element in circuit.elements:
    if element.name.lower().startswith("x"):
        x_name = element.name

# Detach the subcircuit
circuit.element(x_name).detach()
simulator = circuit.simulator()
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("The op-amp differentiator functions correctly.\n")
    sys.exit(0)

time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

min_height = (max(vout) + min(vout)) / 2
num_of_peaks = 2
min_distance = len(vout) / (2 * num_of_peaks) / 1.5 

peaks, _ = find_peaks(vout, height=min_height, distance=min_distance)
troughs, _ = find_peaks(-vout, height=-min_height, distance=min_distance)

average_peak_voltage = np.mean(vout[peaks])
average_trough_voltage = np.mean(vout[troughs])

if len(peaks) == 0 or len(troughs) == 0:
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(0)

peak_voltages = vout[peaks]
trough_voltages = vout[troughs]
mean_peak = np.mean(peak_voltages)
mean_trough = np.mean(trough_voltages)

if np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2) and np.isclose(mean_peak - bias_voltage, 0.6, rtol=0.2):  # 20% tolerance
    print("The differentiator maybe a passive differentiator.\n")
    sys.exit(2)
elif not np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2):
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(0)
else:
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(0)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p24_Opamp Integrator.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Integrator')
# Define MOSFET models (for completeness in case the Opamp needs them)
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Reference voltage (virtual ground at Vdd/2)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input DC bias voltage
circuit.V('in', 'Vin', circuit.gnd, 3@u_V)
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Opamp instance: non-inverting input at Vref, inverting input at node 'Vinn', output at 'Vout'
circuit.X('op', 'Opamp', 'Vref', 'Vinn', 'Vout')
# Input resistor R1 from Vin to Vinn (inverting input)
circuit.R('1', 'Vin', 'Vinn', 10@u_kΩ)
# Feedback capacitor Cf from Vout to Vinn
circuit.C('f', 'Vout', 'Vinn', 100@u_nF)
simulator = circuit.simulator()
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

bias_voltage = 2.5

if vin_name != "":
    circuit.element(vin_name).detach()
    circuit.V('pulse', 'Vin', circuit.gnd, f"PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")
else:
    circuit.V('in', 'Vin', circuit.gnd, f" PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")

r_name = None
for element in circuit.elements:
    if element.name.lower().startswith("r1") or element.name.lower().startswith("rr1"):
        r_name = element.name

if r_name is None:
    for element in circuit.elements:
        if element.name.lower().startswith("r"):
            r_name = element.name

if r_name is None:
    print("No resistor found in the netlist. Please check the netlist.")
    sys.exit(2)
circuit.element(r_name).resistance = "10k"

c_name = None
for element in circuit.elements:
    if element.name.lower().startswith("cf") or element.name.lower().startswith("ccf") or element.name.lower().startswith("c1"):
        c_name = element.name

if c_name is None:
    for element in circuit.elements:
        if element.name.lower().startswith("c"):
            c_name = element.name

if c_name is None:
    print("No capacitor found in the netlist. Please check the netlist.")
    sys.exit(2)
circuit.element(c_name).capacitance = "3u"

simulator = circuit.simulator()

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=1000@u_ms, start_time=800@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

import numpy as np
vlist = {}
for node in analysis.nodes.values():
    vlist[node.name] = np.array(analysis[node.name])

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

plt.rcParams.update({
    'font.size': 12,
    'axes.titlesize': 16,
    'axes.labelsize': 14,
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    'legend.fontsize': 11,
    'lines.linewidth': 2.5
})

# Plot the step response
time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

plt.figure(figsize=(12, 8))

colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#6A994E', '#7209B7', '#F72585', 
          '#264653', '#2A9D8F', '#E9C46A', '#F4A261', '#E76F51', '#8E44AD', '#3498DB',
          '#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#34495E', '#E67E22']

linestyles = ['-', '--', '-.', ':', '-', '--', '-.', '-', '--', '-.', ':', 
              '-', '--', '-.', ':', '-', '--', '-.', ':', '-', '--']

for i, node in enumerate(analysis.nodes.values()):
    plt.plot(time, vlist[node.name], 
             color=colors[i % len(colors)], 
             linestyle=linestyles[i % len(linestyles)],
             linewidth=2.5,
             label=node.name,
             alpha=0.9)

plt.title('Transient Response of Op-amp Integrator', fontsize=16, fontweight='bold', pad=20)
plt.xlabel('Time [s]', fontsize=14, fontweight='semibold')
plt.ylabel('Voltage [V]', fontsize=14, fontweight='semibold')

plt.grid(True, linestyle='--', alpha=0.6, color='gray', linewidth=0.8)

plt.legend(frameon=True, fancybox=True, shadow=True, ncol=2, 
           loc='best', framealpha=0.9, edgecolor='black')

ax = plt.gca()
ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
ax.xaxis.set_major_formatter(FormatStrFormatter('%.3f'))

ax = plt.gca()
for spine in ax.spines.values():
    spine.set_visible(True)
    spine.set_linewidth(1.2)
    spine.set_color('black')

plt.tick_params(axis='both', which='major', direction='out', length=6, width=1.2)
plt.tick_params(axis='both', which='minor', direction='out', length=4, width=1)

plt.tight_layout()
plt.savefig("p24_waveform.png", dpi=300, bbox_inches='tight', facecolor='white')

expected_slope = 0.5 / 0.03

from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)
troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("No peaks or troughs found in output voltage. Please check the netlist.")
    sys.exit(2)

start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])

import sys
if not np.isclose(slope, expected_slope, rtol=0.3):
    print(f"The circuit does not function correctly as an integrator.\n"
          f"Expected slope: {expected_slope:.2f} V/s | Actual slope: {slope:.2f} V/s\n")
    sys.exit(2)

if not r_value** 2 >= 0.9:
    print("The op-amp integrator does not have a linear response.\n")
    sys.exit(2)

for element in circuit.elements:
    if element.name.lower().startswith("x"):
        x_name = element.name

circuit.element(x_name).detach()
simulator = circuit.simulator()
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)

time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

expected_slope = 0.5 / 0.03

from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)
troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)

start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])

if np.isclose(slope, expected_slope, rtol=0.5):
    print("The integrator maybe a passive integrator.\n")
    sys.exit(2)

print("The op-amp integrator functions correctly.\n")
sys.exit(0)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p29_CMOS NAND Gate.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Library import SpiceLibrary
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS NAND Gate circuit
circuit = Circuit('CMOS NAND Gate')

# Define power supply
circuit.V('dd', 'vdd', circuit.gnd, 5@u_V)

# Define input voltage sources
# Input A: Full period pulse
circuit.PulseVoltageSource('inA', 'inputA', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B: Half period pulse
circuit.PulseVoltageSource('inB', 'inputB', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Define PMOS transistors in parallel
# PMOS1: Connected to inputA
circuit.MOSFET('M1', 'output', 'inputA', 'vdd', 'vdd', model='PMOS')

# PMOS2: Connected to inputB
circuit.MOSFET('M2', 'output', 'inputB', 'vdd', 'vdd', model='PMOS')

# Define NMOS transistors in series
# NMOS1: Connected to inputA and intermediate node
circuit.MOSFET('M3', 'output', 'inputA', 'intermediate', circuit.gnd, model='NMOS')

# NMOS2: Connected to inputB and ground
circuit.MOSFET('M4', 'intermediate', 'inputB', circuit.gnd, circuit.gnd, model='NMOS')

# Define MOSFET models
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,    # Transconductance parameter
    vto=0.7,      # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=10e-6,      # Channel width
    l=1e-6        # Channel length
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=60e-6,     # Transconductance parameter
    vto=-0.7,     # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=20e-6,      # Channel width (2x NMOS width)
    l=1e-6        # Channel length
)

# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Add simulation options for better convergence
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=160@u_ns)

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Plot inputs on first subplot
    ax1.plot(analysis.time, analysis['inputA'], 
             label='Input A', linestyle='--', color='blue')
    ax1.plot(analysis.time, analysis['inputB'], 
             label='Input B', linestyle='--', color='green')
    ax1.grid(True)
    ax1.set_title('CMOS NAND Gate - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 5.5)
    
    # Plot output on second subplot
    ax2.plot(analysis.time, analysis['output'], 
             label='Output', color='red')
    ax2.grid(True)
    ax2.set_title('CMOS NAND Gate - Output')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 5.5)
    
    # Adjust layout and display
    plt.tight_layout()
    plt.show()

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")

# Optional: Add timing analysis
def analyze_timing(analysis):
    """Calculate propagation delays and transition times"""
    vdd = 5.0
    v_th = vdd / 2  # Threshold voltage for timing measurements
    
    # Find rising and falling edges
    edges = {
        'input_a': np.where(np.diff(analysis['inputA'] > v_th))[0],
        'input_b': np.where(np.diff(analysis['inputB'] > v_th))[0],
        'output': np.where(np.diff(analysis['output'] > v_th))[0]
    }
    
    # Calculate propagation delays
    prop_delays = []
    for i in range(min(len(edges['input_a']), len(edges['output']))):
        delay = abs(analysis.time[edges['output'][i]] - 
                   analysis.time[edges['input_a'][i]])
        prop_delays.append(float(delay))
    
    print(f"Average propagation delay: {np.mean(prop_delays):.2e} seconds")

# === chipster/data/analog_datasets/AMS_RF_Dataset/p28_Non-inverting Schmitt Trigger.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Non-inverting Schmitt Trigger')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Reference voltage (virtual ground)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltage (DC operating point)
circuit.V('in', 'Vin', circuit.gnd, 2.7@u_V)
# Declare opamp subcircuit
circuit.subcircuit(Opamp())
# Non-inverting Schmitt trigger configuration:
# Non-inverting input (Vp): receives Vin through R1, feedback from Vout through R2, and pulled to Vref through R3
# Inverting input (Vn): connected to Vref
# Resistor from Vin to non-inverting input
circuit.R('1', 'Vin', 'Vp', 10@u_kΩ)
# Feedback resistor from Vout to non-inverting input
circuit.R('2', 'Vout', 'Vp', 100@u_kΩ)
# Pull-down resistor from non-inverting input to Vref
circuit.R('3', 'Vp', 'Vref', 10@u_kΩ)
# Instantiate opamp: X('name', 'subckt', non-inv, inv, out)
circuit.X('op', 'Opamp', 'Vp', 'Vref', 'Vout')
simulator = circuit.simulator()
for element in circuit.elements:
    if element.name.lower().startswith("vin"):
        v_name = element.name

circuit.element(v_name).detach()

circuit.V('in_pulse', 'Vin', circuit.gnd, 'PULSE(1.7 3.3 0 1m 1m 10m 20m)')  # Triangle-like pulse
pin_name = "Vinp"
pin_name_n = "Vinn"
pin_name_out = "Vout"
for element in circuit.elements:
    if element.name.lower().startswith("x"):
        opamp_element = element
        pin_name = str(opamp_element.pins[0].node)
        pin_name_n = str(opamp_element.pins[1].node)
        pin_name_out = str(opamp_element.pins[2].node)
        break

circuit.C('stab1', pin_name, circuit.gnd, 1@u_pF)
circuit.C('stab2', pin_name_n, circuit.gnd, 1@u_pF)
circuit.C('stab3', pin_name_out, circuit.gnd, 1@u_pF)

import sys
try:
    analysis = simulator.transient(step_time=10@u_us, end_time=50@u_ms, 
                                  use_initial_condition=True)
except:
    print("Analysis failed.")
    sys.exit(2)

import numpy as np
# Extract data
time = np.array(analysis.time)
vin = np.array(analysis['Vin'])
vout = np.array(analysis['Vout'])

# Find sections of rising and falling input
# Alternative approach to separate rising and falling data
rising_indices = np.where(np.diff(vin) > 0)[0]
falling_indices = np.where(np.diff(vin) < 0)[0]

# Extract rising and falling data
vin_rising = vin[rising_indices]
vout_rising = vout[rising_indices]
vin_falling = vin[falling_indices]
vout_falling = vout[falling_indices]

# Set threshold for detecting trigger points (half of power supply)
threshold = 2.5

# ===========================================
# First plot basic waveforms for debugging
# ===========================================

import matplotlib.pyplot as plt
plt.figure(figsize=(12, 12))

# First subplot - Time domain response
plt.subplot(3, 1, 1)
plt.plot(time*1000, vin, 'b-', label='Vin')
plt.plot(time*1000, vout, 'r-', label='Vout')
plt.axhline(y=threshold, color='g', linestyle='--', label='Threshold (2.5V)')
plt.legend()
plt.title('Schmitt Trigger Time Domain Response')
plt.xlabel('Time [ms]')
plt.ylabel('Voltage [V]')
plt.grid(True)

# Second subplot - Input/Output transfer curve (hysteresis)
plt.subplot(3, 1, 2)
plt.plot(vin, vout, 'g-', label='Transfer Curve')
plt.axhline(y=threshold, color='k', linestyle='--', label='Threshold (2.5V)')
plt.legend()
plt.title('Hysteresis Curve')
plt.xlabel('Vin [V]')
plt.ylabel('Vout [V]')
plt.grid(True)

# Third subplot - Separate rising and falling edge responses
plt.subplot(3, 1, 3)
plt.plot(vin_rising, vout_rising, 'b-', label='Rising Edge')
plt.plot(vin_falling, vout_falling, 'r-', label='Falling Edge')
plt.axhline(y=threshold, color='k', linestyle='--', label='Threshold (2.5V)')
plt.legend()
plt.title('Rising vs Falling Edge Response')
plt.xlabel('Vin [V]')
plt.ylabel('Vout [V]')
plt.grid(True)

plt.tight_layout()
plt.savefig("p28_waveform.png")

# ===========================================
# Perform quantitative analysis after viewing waveforms
# ===========================================

print("\nStarting trigger point analysis...")

try:
    # Find rising edge trigger point
    rising_cross_indices = np.where(np.diff(vout_rising > threshold) > 0)[0]
    if len(rising_cross_indices) > 0:
        rising_index = rising_cross_indices[0]
        # Use linear interpolation for more precise trigger point
        v1 = vout_rising[rising_index]
        v2 = vout_rising[rising_index + 1]
        i1 = vin_rising[rising_index]
        i2 = vin_rising[rising_index + 1]
        
        # Linear interpolation to calculate exact trigger voltage
        if v2 != v1:  # Avoid division by zero
            t = (threshold - v1) / (v2 - v1)
            trigger_vin_rising = i1 + t * (i2 - i1)
        else:
            trigger_vin_rising = i1
    else:
        print("Warning: No threshold crossing detected for rising edge")
        trigger_vin_rising = None

    # Find falling edge trigger point
    falling_cross_indices = np.where(np.diff(vout_falling < threshold) > 0)[0]
    if len(falling_cross_indices) > 0:
        falling_index = falling_cross_indices[0]
        # Use linear interpolation for more precise trigger point
        v1 = vout_falling[falling_index]
        v2 = vout_falling[falling_index + 1]
        i1 = vin_falling[falling_index]
        i2 = vin_falling[falling_index + 1]
        
        # Linear interpolation to calculate exact trigger voltage
        if v2 != v1:  # Avoid division by zero
            t = (threshold - v1) / (v2 - v1)
            trigger_vin_falling = i1 + t * (i2 - i1)
        else:
            trigger_vin_falling = i1
    else:
        print("Warning: No threshold crossing detected for falling edge")
        trigger_vin_falling = None
        
    # Output detection results
    if trigger_vin_rising is not None and trigger_vin_falling is not None:
        hysteresis_width = abs(trigger_vin_rising - trigger_vin_falling)
        print(f"Rising edge trigger point: {trigger_vin_rising:.5f}V")
        print(f"Falling edge trigger point: {trigger_vin_falling:.5f}V")
        print(f"Hysteresis width: {hysteresis_width:.5f}V")
        
        # Check if Schmitt trigger is working properly
        if hysteresis_width <= 0.01:
            print("The circuit does not function correctly. Trigger points are too close.")
            print(f"Trigger points: {trigger_vin_rising:.5f}V and {trigger_vin_falling:.5f}V are not sufficiently different.")
            print("Please ensure proper positive feedback connection, where Rf should connect to the non-inverting input of the op-amp.")
            sys.exit(2)
        elif max(vout) - min(vout) < 2.5:
            print("The circuit does not function correctly. The output voltage does not vary more than Vdd/2.")
            sys.exit(2)
        else:
            print("The circuit functions correctly with different trigger points.")
        # Plot final graph with detected trigger points
        plt.figure(figsize=(12, 12))
        
        # Time domain response - with trigger points marked
        plt.subplot(3, 1, 1)
        plt.plot(time*1000, vin, 'b-', label='Vin')
        plt.plot(time*1000, vout, 'r-', label='Vout')
        plt.axhline(y=threshold, color='g', linestyle='--', label='Threshold (2.5V)')
        # Mark rising and falling edge trigger points (need to find closest time point)
        rising_time_idx = np.argmin(np.abs(vin_rising - trigger_vin_rising))
        falling_time_idx = np.argmin(np.abs(vin_falling - trigger_vin_falling))
        plt.plot(time[rising_indices[rising_time_idx]]*1000, threshold, 'go', markersize=8, label='Rising Trigger')
        plt.plot(time[falling_indices[falling_time_idx]]*1000, threshold, 'mo', markersize=8, label='Falling Trigger')
        plt.legend()
        plt.title('Schmitt Trigger Response with Trigger Points')
        plt.xlabel('Time [ms]')
        plt.ylabel('Voltage [V]')
        plt.grid(True)
        
        # Hysteresis curve - with trigger points marked
        plt.subplot(3, 1, 2)
        plt.plot(vin, vout, 'g-', label='Transfer Curve')
        plt.plot(trigger_vin_rising, threshold, 'bo', markersize=8, 
                 label=f'Rising Trigger: {trigger_vin_rising:.3f}V')
        plt.plot(trigger_vin_falling, threshold, 'ro', markersize=8, 
                 label=f'Falling Trigger: {trigger_vin_falling:.3f}V')
        plt.axhline(y=threshold, color='k', linestyle='--')
        plt.legend()
        plt.title(f'Hysteresis Curve (Width: {hysteresis_width:.3f}V)')
        plt.xlabel('Vin [V]')
        plt.ylabel('Vout [V]')
        plt.grid(True)
        
        # Separate rising and falling responses
        plt.subplot(3, 1, 3)
        plt.plot(vin_rising, vout_rising, 'b-', label='Rising Edge')
        plt.plot(vin_falling, vout_falling, 'r-', label='Falling Edge')
        plt.plot(trigger_vin_rising, threshold, 'bo', markersize=8)
        plt.plot(trigger_vin_falling, threshold, 'ro', markersize=8)
        plt.axhline(y=threshold, color='k', linestyle='--', label='Threshold')
        plt.legend()
        plt.title('Rising vs Falling Response with Trigger Points')
        plt.xlabel('Vin [V]')
        plt.ylabel('Vout [V]')
        plt.grid(True)
        
        plt.tight_layout()
        plt.savefig("p28_waveform.png")
    else:
        print("Analysis could not be completed as one or more trigger points were not detected.")
        sys.exit(2)

except Exception as e:
    print(f"Error analyzing trigger points: {e}")
    sys.exit(2)
    # import traceback
    # traceback.print_exc()

print("Simulation and analysis completed successfully!")
sys.exit(0)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p9_Opamp Comparator.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Comparator')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Set reference voltage (2.5V) as virtual ground
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltage source (example: 3V, can be swept in simulation)
circuit.V('in', 'Vin', circuit.gnd, 3@u_V)
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Create opamp instance (comparator configuration)
# Non-inverting input: Vin, Inverting input: Vref, Output: Vout
circuit.X('cmp', 'Opamp', 'Vin', 'Vref', 'Vout')
simulator = circuit.simulator()
# Perform DC analysis, sweep input voltage from 0V to 5V
params = {'Vin': slice(0, 5, 0.01)}

try:
    analysis = simulator.dc(**params)
except:
    print("DC analysis failed.")
    import sys
    sys.exit(2)

import numpy as np

# Get analysis results
in_voltage = np.array(analysis.Vin)
out_voltage = np.array(analysis.Vout)
ref_voltage = np.array(analysis.Vref)

# Verify comparator functionality
import sys


for element in circuit.elements:
    if "ref" in element.name.lower():
        vref_name = element.name
        vref_voltage = float(analysis[vref_name][0])
        print(f"Reference Voltage (Vref): {vref_voltage:.2f} V")
        break
# Define transition point
transition_point = vref_voltage  # Voltage where output should switch

# Modified test to check for monotonic behavior instead of absolute values
all_passed = True

# Check that outputs are distinct for values well below and well above the threshold
low_region_outputs = out_voltage[in_voltage < (transition_point - 0.5)]
high_region_outputs = out_voltage[in_voltage > (transition_point + 0.5)]

if len(low_region_outputs) > 0 and len(high_region_outputs) > 0:
    avg_low = np.mean(low_region_outputs)
    avg_high = np.mean(high_region_outputs)
    
    # Check if there's a significant difference between high and low outputs
    if avg_high - avg_low < 2.0:  # At least 2V difference expected
        print(f"Comparator test failed: Not enough distinction between high ({avg_high:.2f}V) and low ({avg_low:.2f}V) outputs")
        all_passed = False
    
    # Check that the transition is monotonic (always increasing or always decreasing)
    # For standard comparator, output should decrease as input increases
    diff_output = np.diff(out_voltage)
    if not (np.all(diff_output <= 0.1) or np.all(diff_output >= -0.1)):
        print("Comparator test failed: Output is not monotonic around the transition region")
        all_passed = False
else:
    print("Comparator test failed: Not enough data points to evaluate")
    all_passed = False

# Check transition behavior
transition_idx = np.argmin(np.abs(in_voltage - transition_point))
before_idx = max(0, transition_idx - 5)
after_idx = min(len(in_voltage) - 1, transition_idx + 5)

transition_inputs = in_voltage[before_idx:after_idx+1]
transition_outputs = out_voltage[before_idx:after_idx+1]

# Print observed behavior for debugging
print("\nObserved Comparator Behavior:")
print("---------------------------")
print("Vin (V) | Vout (V)")
print("---------------------------")
for i, vin in enumerate(transition_inputs):
    vout = transition_outputs[i]
    print(f"{vin:.2f}    | {vout:.2f}")

if all_passed:
    print("\nThe op-amp comparator functions as expected based on observed behavior.")
    # sys.exit(0)
else:
    print("\nThe op-amp comparator test failed.")
    sys.exit(2)

# Optional: Plot comparator response curve
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 6))
plt.plot(in_voltage, out_voltage, 'b-', label='Comparator Output (Vout)')
plt.axvline(x=transition_point, color='k', linestyle='--', label='Reference Voltage (Vref)')
plt.grid(True)
plt.xlabel('Input Voltage (V)')
plt.ylabel('Output Voltage (V)')
plt.title('Op-Amp Comparator Response')
plt.legend()
plt.tight_layout()
plt.savefig('p9_waveform.png')

# === chipster/data/analog_datasets/AMS_RF_Dataset/p4_Single-Stage Common-Gate Amplifier.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('Single-Stage Common-Gate Amplifier')
# Define NMOS model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V supply
# Bias voltage at gate to set the bias point
circuit.V('bias', 'Vbias', circuit.gnd, 2.0)  # Higher bias voltage to ensure V_GS > V_TH
# Input signal at source (Vin)
# During simulation, Vin will be a time-varying source or DC value
# Here, for operating point, we can set a DC value, say 0.5V
# For transient analysis, a voltage source with AC or waveform can be used
# For now, set a DC value for initial operating point
circuit.V('in', 'Vin', circuit.gnd, "dc 0.5 ac 1n")
# Device: M1 (NMOS)
# Drain connected to Vdd through Rload
# Gate connected to Vbias
# Source connected to Vin
W = 50e-6
L = 1e-6
circuit.MOSFET('M1', 'Vout', 'Vbias', 'Vin', 'Vin', model='nmos_model', w=W, l=L)
# Load resistor at drain
R_value = 10e3  # 10 kΩ
circuit.R('load', 'Vout', 'Vdd', R_value)
# Note: For operating point analysis, Vin is DC at 0.5V
# For transient analysis, replace 'Vin' with a time-dependent source
# Initialize simulator
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p4_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p15_Single-Stage Common-Source with PMOS Diode-Connected Load.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('Single-Stage Common-Source with PMOS Diode-Connected Load')
# Define NMOS and PMOS models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Input voltage
circuit.V('in', 'Vin', circuit.gnd, "dc 1@u_V ac 1n")
# Single NMOS transistor (M1)
# Drain connected to Vout, Gate to Vin, Source to GND
circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd,
               model='nmos_model', w=50e-6, l=1e-6)
# PMOS diode-connected load (M2)
# Drain and Gate connected together, Source to Vdd
circuit.MOSFET('M2', 'Vout', 'Vout', 'Vdd', 'Vdd',
               model='pmos_model', w=50e-6, l=1e-6)
# Note: The drain of M1 and M2 is at Vout
# The source of M1 is GND
# The source of M2 is Vdd
# The diode connection for M2 is achieved by connecting gate and drain together
# The output node is Vout
# Ready for simulation
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p15_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === chipster/data/analog_datasets/AMS_RF_Dataset/p16_Differential Opamp with PMOS Current Mirror Load.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Differential Opamp with PMOS Current Mirror Load')
# MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Differential inputs and bias
circuit.V('inp', 'Vinp', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('bias', 'Vbias', circuit.gnd, 1.0)
# Tail current source (NMOS)
circuit.MOSFET('tail', 'Stail', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Differential pair (NMOS)
circuit.MOSFET('1', 'Voutp', 'Vinp', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Vout', 'Vinn', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
# PMOS current mirror load
circuit.MOSFET('3', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('4', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p16_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)

# === chipster/src/std_cell_generator/main.py ===
import streamlit as st
import os
import time
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import random
import re
import asyncio
import nest_asyncio
from dotenv import load_dotenv
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document

# Fix for the asyncio event loop error in Streamlit's thread
nest_asyncio.apply()


def run():
    """
    This function contains the entire Streamlit UI and logic for the Standard Cell Generator.
    """
    # --- Configuration ---
    FAISS_INDEX_PATH = "../../data/std_cell_datasets/faiss_mag_index_st"
    GENERATED_MAG_DIR = "../../examples/std_cells/generated_mag_st"

    # ==============================================================================
    # VISUALIZATION LOGIC
    # ==============================================================================
    _parsed_cell_cache = {}

    def parse_mag_data_hierarchical(file_path, current_dir=None):
        abs_file_path = os.path.abspath(file_path)
        if abs_file_path in _parsed_cell_cache:
            return _parsed_cell_cache[abs_file_path]
        if current_dir is None: current_dir = os.path.dirname(abs_file_path)
        full_file_path = os.path.join(current_dir, os.path.basename(file_path))
        try:
            with open(full_file_path, 'r') as file: mag_content = file.read()
        except FileNotFoundError:
            st.warning(f"Sub-cell file not found: '{os.path.basename(full_file_path)}'. Instance will be skipped.")
            return None
        except Exception as e:
            st.error(f"Error reading file '{full_file_path}': {e}"); return None

        parsed_data = {"header": {}, "layers": {}, "instances": []}
        current_layer, current_instance = None, None
        for line in mag_content.strip().split('\n'):
            line = line.strip()
            if not line: continue
            parts = line.split()
            command = parts[0] if parts else ""
            if line.startswith("<<") and line.endswith(">>"):
                layer_name = line.strip("<<>> ").strip()
                if layer_name != "end":
                    current_layer = layer_name
                    if current_layer not in parsed_data["layers"]:
                        parsed_data["layers"][current_layer] = {"rects": [], "labels": []}
            elif command == "rect" and len(parts) == 5 and current_layer:
                try: parsed_data["layers"][current_layer]["rects"].append({"x1": int(parts[1]), "y1": int(parts[2]), "x2": int(parts[3]), "y2": int(parts[4])})
                except (ValueError, IndexError): pass
            elif command == "use":
                if current_instance: parsed_data["instances"].append(current_instance)
                if len(parts) >= 3:
                    sub_file_path = os.path.join(os.path.dirname(full_file_path), f"{parts[1]}.mag")
                    current_instance = {"cell_type": parts[1], "instance_name": parts[2], "parsed_content": parse_mag_data_hierarchical(sub_file_path, os.path.dirname(full_file_path)),"transform": [1, 0, 0, 0, 1, 0], "box": [0, 0, 0, 0]}
                    if not current_instance["parsed_content"]: current_instance = None
            elif command == "transform" and current_instance:
                try: current_instance["transform"] = [int(v) for v in parts[1:]]
                except (ValueError, IndexError): pass
            elif command == "box" and current_instance:
                try: current_instance["box"] = [int(v) for v in parts[1:]]
                except (ValueError, IndexError): pass
            elif line == "<< end >>" and current_instance:
                parsed_data["instances"].append(current_instance)
                current_instance = None
        if current_instance: parsed_data["instances"].append(current_instance)
        _parsed_cell_cache[abs_file_path] = parsed_data
        return parsed_data

    def visualize_hierarchical_layout(file_path: str):
        _parsed_cell_cache.clear()
        parsed_data = parse_mag_data_hierarchical(file_path)
        if not parsed_data: return None
        fig, ax = plt.subplots(figsize=(15, 12))
        min_x, max_x, min_y, max_y = float('inf'), float('-inf'), float('inf'), float('-inf')
        layer_colors = {}
        def get_random_color(): return (random.random(), random.random(), random.random())
        def _apply_transform(x, y, T): return (T[0] * x + T[1] * y + T[2], T[3] * x + T[4] * y + T[5])
        def _draw_elements(data_to_draw, current_transform=[1, 0, 0, 0, 1, 0]):
            nonlocal min_x, max_x, min_y, max_y
            for layer_name, layer_data in data_to_draw["layers"].items():
                if layer_name not in layer_colors: layer_colors[layer_name] = get_random_color()
                color = layer_colors[layer_name]
                for rect in layer_data.get("rects", []):
                    tx1, ty1 = _apply_transform(rect["x1"], rect["y1"], current_transform)
                    tx2, ty2 = _apply_transform(rect["x2"], rect["y2"], current_transform)
                    width, height = abs(tx2 - tx1), abs(ty2 - ty1)
                    x_start, y_start = min(tx1, tx2), min(ty1, ty2)
                    min_x, max_x = min(min_x, x_start), max(max_x, x_start + width)
                    min_y, max_y = min(min_y, y_start), max(max_y, y_start + height)
                    ax.add_patch(patches.Rectangle((x_start, y_start), width, height, linewidth=1, edgecolor='black', facecolor=color, alpha=0.7))
            for instance in data_to_draw.get("instances", []):
                if instance.get("parsed_content"): _draw_elements(instance["parsed_content"], instance["transform"])
        _draw_elements(parsed_data)
        if not all(v != float('inf') and v != float('-inf') for v in [min_x, max_x, min_y, max_y]):
            plt.close(fig); return None
        padding = (max_x - min_x) * 0.1 if (max_x > min_x) else 10
        ax.set_xlim(min_x - padding, max_x + padding)
        ax.set_ylim(min_y - padding, max_y + padding)
        ax.set_aspect('equal', adjustable='box'); ax.set_title(f"Hierarchical Layout: {os.path.basename(file_path)}", fontsize=16); ax.grid(True, linestyle='--', alpha=0.6)
        return fig

    # ==============================================================================
    # DATA LOADING & AI GENERATION
    # ==============================================================================
    @st.cache_resource(show_spinner="Initializing Vector Store...")
    def get_retriever():
        load_dotenv(); api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key: st.error("GOOGLE_API_KEY not found."); st.stop()
        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=api_key)
        if not os.path.exists(FAISS_INDEX_PATH):
            st.error(f"FAISS index not found at '{FAISS_INDEX_PATH}'. Please ensure the index is created and available.")
            st.stop()
        vector_store = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
        return vector_store.as_retriever(search_kwargs={"k": 3})

    class MagicLayoutGenerator:
        def __init__(self, retriever):
            load_dotenv(); api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key: raise ValueError("GOOGLE_API_KEY not found.")
            self.llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", google_api_key=api_key, temperature=0.1)
            self.retriever = retriever
            self.synthesis_chain = PromptTemplate.from_template("CONTEXTS:\n{context}\n\nQUESTION:\n{question}\n\nBased on the contexts, generate a .mag file for the question. The response must be ONLY the raw .mag file content, starting with 'magic' and ending with '<< end >>'.") | self.llm
            self.improvement_chain = PromptTemplate.from_template("ORIGINAL .MAG FILE:\n{original_mag}\n\nUSER'S IMPROVEMENT REQUEST:\n{improvement_request}\n\nRegenerate the .mag file to incorporate the request. The output MUST be a complete, valid .mag file.") | self.llm

        def stream_single_cell(self, query: str):
            """Yields context first, then streams the LLM response for the .mag file."""
            retrieved_docs = self.retriever.invoke(query)
            if not retrieved_docs:
                yield {"type": "context", "data": "No relevant contexts found."}
                yield {"type": "content_chunk", "data": ""}
                return

            context_str = "".join([f"--- CONTEXT {i+1}: From file '{os.path.basename(doc.metadata.get('source', 'Unknown'))}' ---\n{doc.page_content}\n\n" for i, doc in enumerate(retrieved_docs)])
            yield {"type": "context", "data": context_str}
            
            llm_stream = self.synthesis_chain.stream({"context": context_str, "question": query})
            for chunk in llm_stream:
                yield {"type": "content_chunk", "data": chunk.content}

        def improve_single_cell(self, original_mag_content: str, improvement_request: str):
            response = self.improvement_chain.invoke({"original_mag": original_mag_content, "improvement_request": improvement_request})
            new_mag_content = response.content
            dependencies = set(re.findall(r"^\s*use\s+([\w\d_]+)", new_mag_content, re.MULTILINE))
            return {"content": new_mag_content, "dependencies": dependencies}

    # ==============================================================================
    # STREAMLIT APPLICATION UI
    # ==============================================================================
    try:
        retriever = get_retriever()
        generator = MagicLayoutGenerator(retriever)
    except Exception as e:
        st.error(f"💥 **Initialization Error:** {e}"); st.stop()

    if "generation_queue" not in st.session_state: st.session_state.generation_queue = []
    if "completed_cells" not in st.session_state: st.session_state.completed_cells = {}
    if "current_cell_data" not in st.session_state: st.session_state.current_cell_data = None
    if "mode" not in st.session_state: st.session_state.mode = "Automatic"

    st.title("🤖 Interactive Chip Layout Designer")
    st.write("An AI tool for generating, visualizing, and iteratively refining VLSI layouts.")

    with st.container(border=True):
        st.subheader("⚙️ Control Panel")
        st.session_state.mode = st.radio("**Select Mode**", ["Automatic", "Strict Review"], horizontal=True, help="**Automatic**: Generate all components at once. **Strict Review**: Pause to review and improve each component.")
        with st.form(key='design_form'):
            query = st.text_input("**Design Prompt**", "a 2-input NAND gate")
            filename = st.text_input("**Top-level Filename**", "my_nand.mag")
            if st.form_submit_button(label="🚀 Start New Generation", use_container_width=True):
                if query and filename:
                    st.session_state.generation_queue = [(query, os.path.splitext(filename)[0])]
                    st.session_state.completed_cells = {}
                    st.session_state.current_cell_data = None
                    os.makedirs(GENERATED_MAG_DIR, exist_ok=True)
                else: st.error("Please provide both a prompt and a filename.")
    st.divider()

    if st.session_state.generation_queue:
        if st.session_state.current_cell_data is None:
            current_query, current_cell_name = st.session_state.generation_queue[0]
            st.header(f"Processing: `{current_cell_name}`")
            st.info("Live generation in progress...", icon="⚡")

            col1, col2 = st.columns(2)
            with col1: st.subheader("📄 Live Generated Code"); code_area = st.empty()
            with col2: st.subheader("🖼️ Live Visualization"); plot_area = st.empty()
            context_area = st.empty()

            fig, ax = plt.subplots(figsize=(15, 12))
            ax.set_aspect('equal', adjustable='box'); ax.set_title("Live Layout Generation", fontsize=18); ax.grid(True, linestyle='--', alpha=0.6)
            plot_area.pyplot(fig)

            full_mag_content, line_buffer, current_layer = "", "", None
            layer_colors = {}
            def get_random_color(): return (random.random(), random.random(), random.random())

            response_stream = generator.stream_single_cell(current_query)
            for response in response_stream:
                if response["type"] == "context":
                    context_area.expander("View AI Context Used for this Generation").text(response["data"])
                elif response["type"] == "content_chunk":
                    chunk = response["data"]
                    full_mag_content += chunk
                    line_buffer += chunk
                    code_area.code(full_mag_content, language='text')
                    if '\n' in line_buffer:
                        lines, line_buffer = line_buffer.rsplit('\n', 1)
                        for line in lines.split('\n'):
                            line = line.strip()
                            parts = line.split()
                            if line.startswith("<<"):
                                layer_name = line.strip("<<>> ").strip()
                                if layer_name != "end" and layer_name not in layer_colors:
                                    current_layer = layer_name
                                    layer_colors[current_layer] = get_random_color()
                                    ax.legend(handles=[patches.Patch(color=c, label=n, alpha=0.7) for n, c in layer_colors.items()], loc='upper right')
                            elif parts and parts[0] == "rect" and len(parts) == 5 and current_layer:
                                try:
                                    x1, y1, x2, y2 = map(int, parts[1:5])
                                    width, height = abs(x2 - x1), abs(y2 - y1)
                                    x_start, y_start = min(x1, x2), min(y1, y2)
                                    ax.add_patch(patches.Rectangle((x_start, y_start), width, height, linewidth=1.5, edgecolor='black', facecolor=layer_colors[current_layer], alpha=0.75))
                                    ax.relim(); ax.autoscale_view()
                                    plot_area.pyplot(fig)
                                except (ValueError, IndexError): continue
            
            st.session_state.current_cell_data = {"name": current_cell_name, "content": full_mag_content}
            plt.close(fig)

        if st.session_state.current_cell_data:
            data = st.session_state.current_cell_data
            cell_name, mag_content = data['name'], data['content']
            
            file_path = os.path.join(GENERATED_MAG_DIR, f"{cell_name}.mag")
            with open(file_path, "w") as f: f.write(mag_content)

            dependencies = set(re.findall(r"^\s*use\s+([\w\d_]+)", mag_content, re.MULTILINE))

            if st.session_state.mode == "Strict Review":
                st.info("Generation complete. Please review the final layout below.", icon="✅")
                st.subheader("🔬 Review Component")
                with st.container(border=True):
                    with st.form("review_form"):
                        improvement_prompt = st.text_area("Improvement Request (optional)", placeholder="e.g., Make the routing more compact.")
                        approve_button = st.form_submit_button("👍 Looks Good, Continue", use_container_width=True)
                        improve_button = st.form_submit_button("💡 Improve This Component", use_container_width=True)
                    
                    if approve_button:
                        st.session_state.completed_cells[cell_name] = mag_content
                        st.session_state.generation_queue.pop(0)
                        for dep in dependencies:
                            if dep not in st.session_state.completed_cells and all(dep != item[1] for item in st.session_state.generation_queue):
                                st.session_state.generation_queue.append((f"a {dep} layout", dep))
                        st.session_state.current_cell_data = None
                        st.rerun()
                    
                    if improve_button and improvement_prompt:
                        with st.spinner(f"AI is improving '{cell_name}'..."):
                            improved_result = generator.improve_single_cell(mag_content, improvement_prompt)
                            st.session_state.current_cell_data = {
                                "name": cell_name,
                                "content": improved_result['content']
                            }
                        st.rerun()
            else: # Automatic Mode
                st.session_state.completed_cells[cell_name] = mag_content
                st.session_state.generation_queue.pop(0)
                for dep in dependencies:
                    if dep not in st.session_state.completed_cells and all(dep != item[1] for item in st.session_state.generation_queue):
                        st.session_state.generation_queue.append((f"a {dep} layout", dep))
                st.session_state.current_cell_data = None
                st.success(f"Automatically approved '{cell_name}'. Continuing...")
                time.sleep(1)
                st.rerun()

    elif st.session_state.completed_cells:
        st.balloons(); st.header("🎉 Generation Complete!"); st.write("All components have been successfully generated.")

if __name__ == "__main__":
    run()

# === chipster/src/verilog_generator/main.py ===
import streamlit as st
import os
import glob
import pandas as pd
from typing import List, TypedDict, Dict
import torch
import re
import json
import graphviz
import subprocess
import difflib
import base64

from dotenv import load_dotenv

from langchain_community.document_loaders import CSVLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from langgraph.graph import StateGraph, END

# For the web agent
import asyncio
import nest_asyncio
from crawl4ai import AsyncWebCrawler
from googlesearch import search
from langchain.docstore.document import Document

# For Waveform visualization
from sootty import WireTrace, Visualizer, Style

# --- Configuration & Setup ---

load_dotenv()
nest_asyncio.apply()

st.set_page_config(page_title="Chipster Agent", layout="wide")
st.title("🤖 Chipster Agent: A Self-Correcting Verilog Designer")
st.markdown("Powered by LangGraph and Gemini 2.5 Pro")

try:
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
except KeyError:
    st.error("🚨 GOOGLE_API_KEY not found! Please create a .env file with your key.")
    st.stop()

# --- Part 1: FAISS Index & Model Loading ---

DATASET_PATH = "../../data/verilog_datasets"
INDEX_PATH_DATASET = os.path.join(DATASET_PATH, "faiss_verilog_db")
INDEX_PATH_QFT = os.path.join(DATASET_PATH, "faiss_qft_verieval") # NEW: Path for the second index
GENERATED_CODE_PATH = "../../examples/verilog_designs"
MAX_RETRIES = 10 # Maximum number of correction attempts

@st.cache_resource
def get_embedding_model():
    """Loads the local HuggingFace embedding model, cached for performance."""
    st.write("Loading Local Embedding Model (all-MiniLM-L6-v2)...")
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    st.write(f"Using device: {device}")
    return HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2', model_kwargs={'device': device})

@st.cache_resource
def load_dataset_vectorstore():
    """Loads the main dataset FAISS index if it exists."""
    if os.path.exists(INDEX_PATH_DATASET):
        st.write(f"Loading existing dataset FAISS index from '{INDEX_PATH_DATASET}'...")
        return FAISS.load_local(INDEX_PATH_DATASET, get_embedding_model(), allow_dangerous_deserialization=True)
    else:
        st.warning(f"Local dataset index not found at '{INDEX_PATH_DATASET}'. This data source will be skipped.")
        return None

@st.cache_resource
def load_qft_vectorstore():
    """Loads the QFT and VerilogEval FAISS index if it exists."""
    if os.path.exists(INDEX_PATH_QFT):
        st.write(f"Loading existing QFT/VeriEval FAISS index from '{INDEX_PATH_QFT}'...")
        return FAISS.load_local(INDEX_PATH_QFT, get_embedding_model(), allow_dangerous_deserialization=True)
    else:
        st.warning(f"Local QFT index not found at '{INDEX_PATH_QFT}'. This data source will be skipped.")
        return None

db_verilog_dataset = load_dataset_vectorstore()
db_qft_verieval = load_qft_vectorstore() # NEW: Load the second database


# --- Part 2: LangGraph Multi-Agent Setup ---

class GraphState(TypedDict):
    query: str
    log: List[str]
    documents: List[Document]
    generation: str
    decomposed_files: Dict[str, str]
    testbench_code: Dict[str, str]
    output_path: str
    simulation_output: str
    error_count: int
    top_module_name: str
    summary: str
    theory: str
    waveform_svg: str


def get_graph_viz(active_node: str = None):
    """Generates a Graphviz object to visualize the agent workflow."""
    dot = graphviz.Digraph(comment='Chipster Agent Workflow')
    dot.attr('node', shape='box', style='rounded,filled', fillcolor='lightgrey')
    dot.attr(rankdir='TB', splines='ortho')

    nodes = {
        "dataset_retriever": "1. Dataset Retriever",
        "web_retriever": "2. Web Researcher",
        "code_generator": "3. Verilog Generator",
        "decomposer": "4. Decomposer & Header Extractor", # UPDATED
        "testbench_generator": "5. Testbench Writer",
        "file_writer": "6. File Writer",
        "simulator": "7. Icarus Simulator",
        "check_simulation": "8. Check Results",
        "module_corrector": "9a. Module Corrector",
        "testbench_corrector": "9b. Testbench Corrector",
        "summarizer": "10. Code Summarizer",
        "theory_researcher": "11. Theory Researcher",
        "waveform_viewer": "12. Waveform Viewer"
    }
    for name, label in nodes.items():
        if name == active_node:
            dot.node(name, label, shape='square', style='filled,bold', fillcolor='#FFFF99', fontcolor='black') # Yellow highlight
        else:
            dot.node(name, label, shape='box', style='rounded,filled', fillcolor='#E0E0E0', fontcolor='black') # Light Grey

    # Main flow
    dot.edge("dataset_retriever", "web_retriever")
    dot.edge("web_retriever", "code_generator")
    dot.edge("code_generator", "decomposer")
    dot.edge("decomposer", "testbench_generator")
    dot.edge("testbench_generator", "file_writer")
    dot.edge("file_writer", "simulator")
    dot.edge("simulator", "check_simulation")

    # Success Path
    dot.edge("check_simulation", "summarizer", label="Success", color="green", style="bold")
    dot.edge("summarizer", "theory_researcher")
    dot.edge("theory_researcher", "waveform_viewer")
     
    # Add an END node for clarity
    dot.node("END", "🏁 END", shape="ellipse", style="filled", fillcolor="palegreen")
    dot.edge("waveform_viewer", "END")


    # Conditional Edges from Router
    dot.edge("check_simulation", "testbench_corrector", label="Fix Testbench", color="orange", style="dashed")
    dot.edge("check_simulation", "module_corrector", label="Fix Design", color="red", style="dashed")

    # Correction loop paths
    dot.edge("testbench_corrector", "file_writer", style="dashed")
    dot.edge("module_corrector", "file_writer", style="dashed")

    return dot

# --- Helper Functions ---
def log_code_changes(log: List[str], filename: str, old_code: str, new_code: str) -> List[str]:
    """Generates a diff and adds it to the log."""
    diff = difflib.unified_diff(
        old_code.splitlines(keepends=True),
        new_code.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    diff_str = "".join(diff)
    if diff_str:
        log.append(f"🔍 Code changes for `{filename}`:\n```diff\n{diff_str}```")
    else:
        log.append(f"🔍 No functional changes detected for `{filename}`.")
    return log

# --- Agent Nodes ---

def dataset_retriever_node(state):
    query = state["query"]
    log = state.get("log", []) + ["\n--- AGENT: Dataset Retriever ---"]
    all_docs = []

    # No change to this node, keeping it concise
    if db_verilog_dataset:
        docs1 = db_verilog_dataset.as_retriever(search_kwargs={"k": 10}).invoke(query)
        all_docs.extend(docs1)
        log.append(f"Found {len(docs1)} docs in 'faiss_verilog_db'.")
    if db_qft_verieval:
        docs2 = db_qft_verieval.as_retriever(search_kwargs={"k": 10}).invoke(query)
        all_docs.extend(docs2)
        log.append(f"Found {len(docs2)} docs in 'faiss_qft_verieval'.")
     
    log.append(f"Total documents retrieved from local DBs: {len(all_docs)}")
    return {"documents": all_docs, "log": log}

def web_retriever_node(state):
    return asyncio.run(web_retriever_node_async(state))

async def web_retriever_node_async(state):
    """
    UPDATED NODE: This node has an improved search and crawling strategy
    to find more relevant Verilog code on GitHub.
    """
    query = state["query"]
    existing_docs = state.get("documents", [])
    log = state.get("log", []) + ["\n--- AGENT: Web Researcher ---"]
    embeddings = get_embedding_model()
    sanitized_prompt = re.sub(r'\W+', '_', query).lower()
    index_name = f"faiss_github_{sanitized_prompt}"
    INDEX_PATH_WEB = os.path.join(DATASET_PATH, index_name)
    log.append(f"Checking for cached web index: '{INDEX_PATH_WEB}'")
    web_vectorstore = None
    if os.path.exists(INDEX_PATH_WEB):
        log.append("✅ Cached index found! Loading.")
        web_vectorstore = FAISS.load_local(INDEX_PATH_WEB, embeddings, allow_dangerous_deserialization=True)
    else:
        log.append("❌ No cache. Searching and crawling web...")

        # --- IMPROVED SEARCH LOGIC ---
        # Broader search query to find repositories and code
        search_query = f'"{query}" verilog source code OR design files site:github.com'
        log.append(f"Executing Google search with query: '{search_query}'")
        # Increase search results to get more diverse code examples
        urls = list(search(search_query, num_results=10, lang="en"))
        log.append(f"Found {len(urls)} potential URLs from Google.")
        # Log the first few URLs for debugging
        for i, url in enumerate(urls[:5]):
            log.append(f"  - URL {i+1}: {url}")
        # --- END IMPROVEMENT ---

        if not urls:
             log.append("⚠️ No relevant URLs found on Google search.")
             return {"documents": existing_docs, "log": log}

        new_web_docs = []
        crawled_count = 0
        async with AsyncWebCrawler() as crawler:
            # --- IMPROVED CRAWLING LOGIC ---
            # Process all found URLs instead of just a subset
            log.append(f"Crawling up to {len(urls)} URLs...")
            for url in urls:
                if url and "github.com" in url: # Ensure it's a GitHub link
                    try:
                        result = await crawler.arun(url=url)
                        if result and result.markdown:
                            # Add a check for code content to avoid empty READMEs
                            if "```" in result.markdown or "module" in result.markdown or "input" in result.markdown:
                                new_web_docs.append(Document(page_content=result.markdown, metadata={"source": url}))
                                crawled_count += 1
                                log.append(f"  - ✅ Successfully crawled: {url}")
                            else:
                                log.append(f"  - 🟡 Skipped (no code indicators): {url}")
                        else:
                            log.append(f"  - ⚠️ Crawled but no markdown content: {url}")
                    except Exception as e:
                        log.append(f"  - ❌ Failed to crawl {url}: {e}")
            # --- END IMPROVEMENT ---

        if new_web_docs:
            log.append(f"Successfully extracted content from {crawled_count} URLs.")
            split_docs = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200).split_documents(new_web_docs)
            web_vectorstore = FAISS.from_documents(split_docs, embeddings)
            web_vectorstore.save_local(INDEX_PATH_WEB)
            log.append(f"✅ New web index saved with {len(split_docs)} document chunks.")
        else:
            log.append("Could not retrieve any valid documents from the web.")

    docs_from_web = []
    if web_vectorstore:
        # Retrieve more documents to give the generator more context
        retriever = web_vectorstore.as_retriever(search_kwargs={"k": 15}) # Increased k
        docs_from_web = retriever.invoke(query)
        log.append(f"✅ Retrieved {len(docs_from_web)} relevant document chunks from web cache for the query.")
    else:
        log.append("⚠️ No web vectorstore available to retrieve from.")

    return {"documents": existing_docs + docs_from_web, "log": log}

def code_generator_node(state):
    query = state["query"]
    documents = state["documents"]
    log = state.get("log", []) + ["\n--- AGENT: Verilog Generator ---"]
    log.append("✍️ Generating monolithic code from scratch...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert Verilog HDL designer.
Based on the context from reference documents and the user's request, generate the complete, monolithic Verilog code.
The code should be well-structured and include any necessary `define` macros or parameters at the top.
Your output **MUST** be only the Verilog code, enclosed in a single markdown block. Do not include any other text.

**CONTEXT:**
{context}

**REQUEST:**
{question}

**GENERATED VERILOG CODE:**
```verilog
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
     
    def format_docs(docs):
        if not docs: return "No context documents found."
        return "\n\n".join(f"Source: {doc.metadata.get('source', 'N/A')}\n\n{doc.page_content}" for doc in docs)
         
    rag_chain = ({"context": lambda x: format_docs(x["documents"]), "question": RunnablePassthrough()}| prompt | llm | StrOutputParser())
    generation = rag_chain.invoke({"documents": documents, "question": query}).replace("```verilog", "").replace("```", "").strip()
    log.append("✅ Monolithic code generated.")
     
    return {"generation": generation, "log": log, "simulation_output": ""}

def module_corrector_node(state):
    log = state.get("log", []) + ["\n--- AGENT: Verilog Module Corrector ---"]
    log.append("♻️ Attempting to fix previous design error...")
     
    decomposed_files = state["decomposed_files"]
    error_log = state["simulation_output"]
     
    # Improved logic to find the faulty file
    faulty_filename = None
    for fname in decomposed_files.keys():
        # Icarus often reports errors with file:line format
        if fname in error_log:
            faulty_filename = fname
            break
     
    if not faulty_filename:
        log.append("⚠️ Could not identify a specific faulty module from the error log. No correction applied.")
        return {"decomposed_files": decomposed_files, "log": log}

    faulty_code = decomposed_files[faulty_filename]
    log.append(f"Identified faulty file: `{faulty_filename}`")

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert Verilog debugger.
**TASK:** You are given a single Verilog module that failed during simulation. Analyze the error message and the code, identify the bug, and provide a corrected version of **only that module's code**.
Your output **MUST** be only the corrected Verilog code for the module, enclosed in a single markdown block.

**FAULTY VERILOG MODULE (`{faulty_filename}`):**
```verilog
{faulty_code}
```

**SIMULATION ERROR LOG:**
```
{error_log}
```

**YOUR RESPONSE (Corrected, Complete Verilog Code for the Module Only):**
```verilog
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm | StrOutputParser()
     
    corrected_module_code = chain.invoke({
        "faulty_filename": faulty_filename,
        "faulty_code": faulty_code,
        "error_log": error_log
    }).replace("```verilog", "").replace("```", "").strip()

    updated_files = decomposed_files.copy()
    updated_files[faulty_filename] = corrected_module_code
    log.append(f"✅ Design correction generated for `{faulty_filename}`.")
     
    log = log_code_changes(log, faulty_filename, faulty_code, corrected_module_code)

    return {"decomposed_files": updated_files, "log": log}


def decomposer_node(state):
    """
    UPDATED NODE: This node now also extracts `define` macros and parameters
    into a separate .vh header file and adds `include` statements where needed.
    """
    generation = state["generation"]
    log = state.get("log", []) + ["\n--- AGENT: Decomposer & Header Extractor ---"]
    log.append("Decomposing code and extracting headers...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.0, google_api_key=GOOGLE_API_KEY)
     
    decomposer_prompt_template = """You are an expert Verilog refactoring tool.
Your task is to analyze monolithic Verilog code and decompose it into multiple files.

**RULES:**
1.  Identify the top-level module.
2.  Separate each `module` into its own file (e.g., `module_name.v`).
3.  **Crucially: Identify all `` `define `` macros and shared `parameter` declarations. Move them into a single header file (e.g., `shared_header.vh`).**
4.  In each `.v` file that uses a macro/parameter from the header, add the `` `include "shared_header.vh" `` directive at the top.
5.  Return a single, valid JSON object with two keys: "top_module_name" and "files".
6.  `files` must be an object where keys are filenames (`.v` or `.vh`) and values are the code content.
7.  Your final output **MUST** be only the JSON object.

**USER REQUEST:** {query}
**MONOLITHIC VERILOG CODE:**
```verilog
{verilog_code}
```

**RESPONSE (Valid JSON object only):**
"""
    decomposer_prompt = ChatPromptTemplate.from_template(decomposer_prompt_template)
     
    chain = decomposer_prompt | llm | StrOutputParser()
    response = chain.invoke({"verilog_code": generation, "query": state["query"]})
     
    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            raise json.JSONDecodeError("No JSON object found in the LLM response.", response, 0)
         
        json_str = json_match.group(0)
        parsed_json = json.loads(json_str)
         
        decomposed_files = parsed_json.get("files", {})
        top_module_name = parsed_json.get("top_module_name", "")

        if not decomposed_files or not top_module_name:
             raise ValueError("Parsed JSON is missing 'files' or 'top_module_name' keys.")

        log.append(f"✅ Decomposed into {len(decomposed_files)} files. Top module: `{top_module_name}`")
        if any(".vh" in f for f in decomposed_files.keys()):
            log.append("✅ Header file extracted successfully.")

    except (json.JSONDecodeError, ValueError) as e:
        log.append(f"❌ Failed to parse valid JSON from decomposer. Error: {e}. Falling back to monolithic code.")
        log.append(f"   Raw LLM Response: {response}")
        top_module_match = re.search(r'module\s+([\w#\(\)]+)', generation)
        top_module_name = top_module_match.group(1).split('#')[0].strip() if top_module_match else "unknown_module"
        decomposed_files = {f"{top_module_name}.v": generation}
         
    return {"decomposed_files": decomposed_files, "top_module_name": top_module_name, "log": log}

def testbench_generator_node(state):
    log = state.get("log", []) + ["\n--- AGENT: Testbench Writer ---"]
    decomposed_files = state["decomposed_files"]
    top_module_name = state["top_module_name"]

    if not decomposed_files:
        log.append("❌ Cannot generate testbench: No decomposed module files were provided.")
        return {"testbench_code": {}, "log": log}

    log.append("✍️ Generating new testbench...")
    top_module_code = decomposed_files.get(f"{top_module_name}.v", list(decomposed_files.values())[0])
    # Check if a header file exists to include it in the testbench
    header_file = next((f for f in decomposed_files if f.endswith('.vh')), None)
    header_include_line = f'- **Include the header file: `` `include "{header_file}" ``**' if header_file else ''


    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert in Verilog testbench design.
**TASK:** Write a comprehensive testbench for the provided top-level module.
- The testbench module name **MUST** be `{top_module_name}_tb`.
- Instantiate the DUT, provide realistic stimuli, and use `$display` or `$monitor` to show results.
- It must include a clock signal if needed and terminate automatically using `$finish`.
- **CRITICAL: You MUST include these two lines at the start of the initial block for waveform generation:**
  `$dumpfile("design.vcd");`
  `$dumpvars(0, {top_module_name}_tb);`
{header_include}
- Your final output **MUST** be a single, valid JSON object with one key-value pair: the key is the testbench filename (`{top_module_name}_tb.v`) and the value is the complete testbench code. **DO NOT** include the DUT's code in your response.

**TOP-LEVEL MODULE CODE (for context only):**
```verilog
{top_module_code}
```
**RESPONSE (Valid JSON object containing only the testbench code):**
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
     
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke({
        "top_module_name": top_module_name,
        "top_module_code": top_module_code,
        "header_include": header_include_line
    })

    try:
        json_str = response[response.find('{'):response.rfind('}')+1]
        testbench_json = json.loads(json_str)
        log.append(f"✅ Testbench generated: `{list(testbench_json.keys())[0]}`")
    except Exception as e:
        log.append(f"❌ Failed to generate valid testbench JSON. Error: {e}")
        testbench_json = {}
         
    return {"testbench_code": testbench_json, "log": log}

def testbench_corrector_node(state):
    log = state.get("log", []) + ["\n--- AGENT: Testbench Corrector ---"]
    log.append("♻️ Attempting to fix previous testbench error...")

    decomposed_files = state["decomposed_files"]
    top_module_name = state["top_module_name"]
    faulty_tb_code_dict = state["testbench_code"]
    error_log = state["simulation_output"]

    top_module_code = decomposed_files.get(f"{top_module_name}.v", list(decomposed_files.values())[0])
    faulty_tb_filename = list(faulty_tb_code_dict.keys())[0] if faulty_tb_code_dict else f"{top_module_name}_tb.v"
    faulty_tb_code = list(faulty_tb_code_dict.values())[0] if faulty_tb_code_dict else "# Faulty testbench code was not found"

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert Verilog testbench debugger.
**TASK:** You are given a testbench that failed during simulation. Analyze the error message, the testbench code, and the module it is testing (DUT). Provide a corrected version of **only the testbench code**.
- **CRITICAL: Ensure the corrected testbench includes `$dumpfile("design.vcd");` and `$dumpvars(0, {top_module_name}_tb);` for waveform generation.**
- Your final output **MUST** be a single JSON object containing the corrected testbench. The key must be the original testbench filename.

**SIMULATION ERROR LOG:**
```
{error_log}
```

**FAULTY TESTBENCH CODE (`{faulty_tb_filename}`):**
```verilog
{faulty_tb_code}
```

**DEVICE UNDER TEST (DUT) CODE (`{top_module_name}.v`) (for context only):**
```verilog
{top_module_code}
```

**RESPONSE (Valid JSON object containing only the corrected testbench code):**
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm | StrOutputParser()
     
    response = chain.invoke({
        "top_module_name": top_module_name,
        "top_module_code": top_module_code,
        "error_log": error_log,
        "faulty_tb_filename": faulty_tb_filename,
        "faulty_tb_code": faulty_tb_code
    })

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            raise json.JSONDecodeError("No JSON object found in the LLM response.", response, 0)
         
        json_str = json_match.group(0)
        corrected_testbench_json = json.loads(json_str)

        if not isinstance(corrected_testbench_json, dict) or not corrected_testbench_json:
            raise ValueError("Parsed JSON is not a valid, non-empty dictionary.")
         
        corrected_tb_filename = list(corrected_testbench_json.keys())[0]
        corrected_tb_code = corrected_testbench_json[corrected_tb_filename]

        log.append(f"✅ Testbench correction generated for: `{corrected_tb_filename}`")
        log = log_code_changes(log, corrected_tb_filename, faulty_tb_code, corrected_tb_code)

    except (json.JSONDecodeError, ValueError) as e:
        log.append(f"❌ Failed to generate valid corrected testbench JSON. Error: {e}")
        log.append(f"   Raw LLM Response: {response}")
        corrected_testbench_json = faulty_tb_code_dict
         
    return {"testbench_code": corrected_testbench_json, "log": log}


def file_writer_node(state):
    log = state.get("log", []) + ["\n--- AGENT: File Writer ---"]
    query = state["query"]
    decomposed_files = state["decomposed_files"]
    testbench_code = state.get("testbench_code", {})
    sanitized_prompt = re.sub(r'\W+', '_', query).lower()
    output_path = os.path.join(GENERATED_CODE_PATH, f"generated_{sanitized_prompt}")
    os.makedirs(output_path, exist_ok=True)
    log.append(f"Writing files to: `{output_path}`")

    all_files_to_write = {**decomposed_files, **testbench_code}
    for filename, content in all_files_to_write.items():
        # Sanitize filename just in case
        safe_filename = re.sub(r'[^\w\.\-]', '_', filename)
        if isinstance(content, str) and content.strip():
            with open(os.path.join(output_path, safe_filename), 'w') as f:
                f.write(content)
            log.append(f"  - Wrote `{safe_filename}`")
        else:
            log.append(f"  - ⚠️ Skipped writing `{safe_filename}` due to invalid content.")
             
    return {"output_path": output_path, "log": log}

def simulator_node(state):
    """
    UPDATED NODE: Runs simulation inside the output directory to ensure
    VCD files are generated in the correct location.
    """
    log = state.get("log", []) + ["\n--- AGENT: Icarus Simulator ---"]
    output_path = state["output_path"]
    log.append(f"Preparing to simulate files in `{output_path}`")

    # Get relative paths for the commands to be run inside the output_path
    verilog_filenames = [os.path.basename(f) for f in glob.glob(os.path.join(output_path, "*.v"))]
    if not verilog_filenames:
        log.append("❌ No `.v` files found to simulate.")
        return {"simulation_output": "Error: No Verilog files found.", "log": log}
     
    output_vvp_filename = "design.vvp"
    # Command uses relative filenames now
    command = ["iverilog", "-o", output_vvp_filename] + verilog_filenames
     
    simulation_output = ""
    try:
        log.append(f"Running compilation in `{output_path}`...")
        log.append(f"Command: `{' '.join(command)}`")
        # Run compilation from within the output directory
        compile_process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=output_path # Change working directory
        )
         
        if compile_process.returncode != 0:
            raise subprocess.CalledProcessError(compile_process.returncode, compile_process.args, output=compile_process.stdout, stderr=compile_process.stderr)
             
        log.append("✅ Compilation successful.")
         
        # Command for simulation now just needs the relative filename
        sim_command = ["vvp", output_vvp_filename]
        log.append(f"Running simulation in `{output_path}`...")
        log.append(f"Command: `{' '.join(sim_command)}`")
        # Run simulation from within the output directory
        sim_process = subprocess.run(
            sim_command,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd=output_path # Change working directory
        )
        simulation_output = sim_process.stdout
        log.append("✅ Simulation finished.")
         
    except subprocess.CalledProcessError as e:
        error_message = e.stderr or e.stdout or "Unknown simulation error."
        simulation_output = f"ERROR during {'compilation' if 'iverilog' in ' '.join(e.cmd) else 'simulation'}:\n{error_message}"
        log.append(f"❌ Simulation Failed.")
    except subprocess.TimeoutExpired:
        simulation_output = "ERROR: Simulation timed out. The testbench may have an infinite loop or is not finishing with `$finish`."
        log.append(f"❌ {simulation_output}")

    # Clear simulation output on success, keep it on error
    if "ERROR" not in simulation_output:
        return {"simulation_output": "", "log": log}
    else:
        error_count = state.get("error_count", 0) + 1
        return {"simulation_output": simulation_output, "error_count": error_count, "log": log}


def check_simulation_results_node(state):
    log = state.get("log", []) + ["\n--- ROUTER: Checking Results ---"]
    simulation_output = state.get("simulation_output", "")
    error_count = state.get("error_count", 0)
     
    if not simulation_output:
        log.append("✅ Success! Routing to final documentation.")
        return "success"

    log.append(f"⚠️ Error detected on attempt {error_count + 1}.")
    if error_count >= MAX_RETRIES:
        log.append(f"❌ Maximum retry limit ({MAX_RETRIES}) reached. Halting workflow.")
        return "end"
     
    tb_files = [f for f in state.get("testbench_code", {}).keys()]
    is_tb_error = any(tb_file in simulation_output for tb_file in tb_files if tb_file) or "timeout" in simulation_output.lower()

    if is_tb_error:
        log.append("Routing to: Testbench Corrector")
        return "fix_testbench"
    else:
        log.append("Routing to: Module Corrector")
        return "fix_design"

def summarizer_node(state):
    log = state.get("log", []) + ["\n--- AGENT: Code Summarizer ---"]
    log.append("Generating code summary...")
     
    top_module_name = state["top_module_name"]
    top_module_code = state["decomposed_files"].get(f"{top_module_name}.v", "")

    if not top_module_code:
        log.append("⚠️ Top module code not found for summarization.")
        return {"summary": "Could not generate summary because the top-level module code was not found.", "log": log}

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.0, google_api_key=GOOGLE_API_KEY)
    prompt = ChatPromptTemplate.from_template(
        """You are a technical writer for hardware design. Based on the Verilog code, create a concise summary.
        Include:
        1.  **Purpose**: One sentence on what the module does.
        2.  **Ports**: Lists of input and output ports with bit widths.
        3.  **Functionality**: A short paragraph on its behavior.

        **Top-Level Module Code (`{module_name}.v`):**
        ```verilog
        {module_code}
        ```
        **Your Summary:**
        """
    )
     
    chain = prompt | llm | StrOutputParser()
    summary = chain.invoke({"module_name": top_module_name, "module_code": top_module_code})
     
    log.append("✅ Summary generated.")
    return {"summary": summary, "log": log}

async def theory_researcher_node_async(state):
    log = state.get("log", []) + ["\n--- AGENT: Theory Researcher ---"]
    query = state["query"]
    log.append(f"Researching theory for: '{query}'...")

    search_query = f"explain {query} digital logic design"
    urls = list(search(search_query, num_results=1, lang="en"))

    if not urls:
        log.append("⚠️ No relevant theory explanation found on the web.")
        return {"theory": "Could not find a relevant theoretical explanation for this topic.", "log": log}

    explanation_content = ""
    async with AsyncWebCrawler() as crawler:
        if urls[0]:
            try:
                result = await crawler.arun(url=urls[0])
                if result and result.markdown:
                    explanation_content = result.markdown
            except Exception as e:
                log.append(f"⚠️ Failed to crawl {urls[0]}: {e}")
                return {"theory": "Failed to retrieve information from the web.", "log": log}

    if not explanation_content:
        log.append("⚠️ Crawled page has no content.")
        return {"theory": "Could not extract content from the web page.", "log": log}

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.0, google_api_key=GOOGLE_API_KEY)
    prompt = ChatPromptTemplate.from_template(
        """You are an expert in digital logic. Based on the text provided, write a concise explanation of the concept requested by the user.
        Focus on fundamental principles.

        **User's Request:** {original_query}
        **Content from Webpage:**
        ```
        {web_content}
        ```
        **Your Concise Explanation:**
        """
    )
    chain = prompt | llm | StrOutputParser()
    theory = chain.invoke({"original_query": query, "web_content": explanation_content})

    log.append("✅ Theoretical explanation generated.")
    return {"theory": theory, "log": log}

def theory_researcher_node(state):
    return asyncio.run(theory_researcher_node_async(state))

def waveform_viewer_node(state):
    """Generates an SVG waveform from the VCD file using Sootty."""
    log = state.get("log", []) + ["\n--- AGENT: Waveform Viewer ---"]
    output_path = state["output_path"]
    vcd_path = os.path.join(output_path, "design.vcd")
     
    log.append(f"Looking for VCD file at: `{vcd_path}`")

    if not os.path.exists(vcd_path) or os.path.getsize(vcd_path) == 0:
        log.append("⚠️ VCD file not found or is empty. Skipping waveform generation.")
        return {"waveform_svg": "", "log": log}
         
    log.append("✅ Found VCD file. Generating waveform image with Sootty...")
     
    try:
        wiretrace = WireTrace.from_vcd(vcd_path)
        # Render all wires for a comprehensive view
        wires_to_render = wiretrace.get_wires()
        image = Visualizer(Style.Dark).to_svg(wiretrace, start=0, length=2000, wires=wires_to_render)
        # Convert SVG object to a base64 encoded string for reliable display
        svg_string = image.decode('utf-8')
        log.append("✅ Waveform SVG generated successfully.")
        return {"waveform_svg": svg_string, "log": log}
    except Exception as e:
        log.append(f"❌ Failed to generate waveform with Sootty: {e}")
        return {"waveform_svg": "", "log": log}

# --- Graph Definition ---
def build_graph():
    workflow = StateGraph(GraphState)
    workflow.add_node("dataset_retriever", dataset_retriever_node)
    workflow.add_node("web_retriever", web_retriever_node)
    workflow.add_node("code_generator", code_generator_node)
    workflow.add_node("module_corrector", module_corrector_node)
    workflow.add_node("decomposer", decomposer_node)
    workflow.add_node("testbench_generator", testbench_generator_node)
    workflow.add_node("testbench_corrector", testbench_corrector_node)
    workflow.add_node("file_writer", file_writer_node)
    workflow.add_node("simulator", simulator_node)
    workflow.add_node("summarizer", summarizer_node)
    workflow.add_node("theory_researcher", theory_researcher_node)
    workflow.add_node("waveform_viewer", waveform_viewer_node)

    workflow.set_entry_point("dataset_retriever")
    workflow.add_edge("dataset_retriever", "web_retriever")
    workflow.add_edge("web_retriever", "code_generator")
    workflow.add_edge("code_generator", "decomposer")
    workflow.add_edge("decomposer", "testbench_generator")
    workflow.add_edge("testbench_generator", "file_writer")
    workflow.add_edge("file_writer", "simulator")
     
    workflow.add_edge("summarizer", "theory_researcher")
    workflow.add_edge("theory_researcher", "waveform_viewer")
    workflow.add_edge("waveform_viewer", END)

    workflow.add_edge("module_corrector", "file_writer")
    workflow.add_edge("testbench_corrector", "file_writer")
     
    workflow.add_conditional_edges(
        "simulator",
        check_simulation_results_node,
        {
            "success": "summarizer",
            "fix_testbench": "testbench_corrector",
            "fix_design": "module_corrector",
            "end": END
        }
    )
     
    # The recursion limit is set during the stream/invoke call, not at compile time.
    return workflow.compile()

app = build_graph()


# --- Part 3: Streamlit UI ---
st.sidebar.header("Controls")
user_query = st.sidebar.text_area("Describe the Verilog module you want to build:", height=150, value="risc v 32 bit")

if st.sidebar.button("✨ Generate & Verify Code", use_container_width=True):
    if not user_query:
        st.sidebar.error("Please enter a description for the Verilog module.")
    else:
        st.subheader("🚀 Agent Workflow Visualization")
        graph_placeholder = st.empty()
         
        col1, col2 = st.columns([1, 2])
        with col1:
            log_expander = st.expander("Agent Activity Log", expanded=True)
            log_container = log_expander.container()
         
        with col2:
            results_expander = st.expander("Final Results & Files", expanded=True)
            results_placeholder = results_expander.container()


        graph_placeholder.graphviz_chart(get_graph_viz())
        inputs = {"query": user_query, "error_count": 0, "summary": "", "theory": "", "waveform_svg": ""}
         
        with st.spinner("Chipster Agent is thinking... This may take a few minutes for complex designs."):
            final_result = None
            log_messages = []
             
            # Set the recursion limit for this specific run in the config.
            config = {"recursion_limit": 100}
            for s in app.stream(inputs, config=config, stream_mode="values"):
                active_node = list(s.keys())[-1]
                graph_placeholder.graphviz_chart(get_graph_viz(active_node))
                final_result = s
                if "log" in final_result:
                    new_logs = final_result["log"][len(log_messages):]
                    for msg in new_logs:
                        log_container.markdown(f"{msg.strip()}", unsafe_allow_html=True)
                        log_messages.append(msg)
             
            graph_placeholder.graphviz_chart(get_graph_viz("END"))
             
            results_placeholder.subheader("🏁 Final Outcome")
            if final_result.get("simulation_output"): # Check if error output exists
                results_placeholder.error(f"Workflow halted with an error after {final_result.get('error_count', 0)} retries.")
                with results_placeholder.expander("🚨 View Final Simulation Error", expanded=True):
                    st.code(final_result.get("simulation_output"), language='bash')
            else:
                st.balloons()
                results_placeholder.success(f"✅ All Verilog files generated, verified, and saved to: `{final_result.get('output_path', 'N/A')}`")
             
            if final_result.get("summary"):
                with results_placeholder.expander("📝 Code Summary", expanded=True):
                    st.markdown(final_result["summary"])
             
            if final_result.get("theory"):
                with results_placeholder.expander("🎓 Theory & Explanation", expanded=True):
                    st.markdown(final_result["theory"])
             
            # Display Waveform if it exists
            if final_result.get("waveform_svg"):
                with results_placeholder.expander("📈 Waveform Visualization", expanded=True):
                    # Display SVG directly for better rendering
                    st.image(final_result["waveform_svg"], use_column_width=True)
            elif not final_result.get("simulation_output"): # Only show if successful
                 with results_placeholder.expander("📈 Waveform Visualization", expanded=True):
                    st.warning("Waveform data was not generated. This can happen if the testbench does not properly exercise the design or if the simulation is very short.")


            results_placeholder.write("---")
            results_placeholder.subheader("Generated Files & Content")
            all_files = {
                **final_result.get("decomposed_files", {}),
                **final_result.get("testbench_code", {})
            }
            if all_files:
                # Sort files to show headers first, then top module, then others
                sorted_files = sorted(all_files.items(), key=lambda item: (not item[0].endswith('.vh'), item[0] != f"{final_result.get('top_module_name')}.v", item[0]))
                for filename, content in sorted_files:
                    icon = "📄"
                    if filename.endswith("_tb.v"):
                        icon = "🧪"
                    elif filename.endswith(".vh"):
                        icon = "📚"
                    with results_placeholder.expander(f"{icon} **{filename}**"):
                        st.code(content, language='verilog')
else:
    st.info("Enter your Verilog design requirements in the sidebar and click 'Generate & Verify'.")


# === chipster/src/verilog_generator/main2.py ===
import streamlit as st
import os
import glob
import pandas as pd
from typing import List, TypedDict, Dict
import torch
import re
import json
import graphviz
import subprocess
import difflib
import base64

from dotenv import load_dotenv

from langchain_community.document_loaders import CSVLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

from langgraph.graph import StateGraph, END

# For the web agent
import asyncio
import nest_asyncio
from crawl4ai import AsyncWebCrawler
from googlesearch import search
from langchain.docstore.document import Document

# For Waveform visualization
from sootty import WireTrace, Visualizer, Style

# --- Configuration & Setup ---

load_dotenv()
nest_asyncio.apply()

st.set_page_config(page_title="Chipster Agent", layout="wide")
st.title("🤖 Chipster Agent: A Self-Correcting Verilog Designer")
st.markdown("Powered by LangGraph and Gemini 2.5 Pro")

try:
    GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
except KeyError:
    st.error("🚨 GOOGLE_API_KEY not found! Please create a .env file with your key.")
    st.stop()

# --- Part 1: FAISS Index & Model Loading ---

DATASET_PATH = "../../data/verilog_datasets"
INDEX_PATH_DATASET = os.path.join(DATASET_PATH, "faiss_verilog_db")
INDEX_PATH_QFT = os.path.join(DATASET_PATH, "faiss_qft_verieval") # NEW: Path for the second index
GENERATED_CODE_PATH = "../../examples/verilog_designs"
MAX_RETRIES = 10 # Maximum number of correction attempts

@st.cache_resource
def get_embedding_model():
    """Loads the local HuggingFace embedding model, cached for performance."""
    st.write("Loading Local Embedding Model (all-MiniLM-L6-v2)...")
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    st.write(f"Using device: {device}")
    return HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2', model_kwargs={'device': device})

@st.cache_resource
def load_dataset_vectorstore():
    """Loads the main dataset FAISS index if it exists."""
    if os.path.exists(INDEX_PATH_DATASET):
        st.write(f"Loading existing dataset FAISS index from '{INDEX_PATH_DATASET}'...")
        return FAISS.load_local(INDEX_PATH_DATASET, get_embedding_model(), allow_dangerous_deserialization=True)
    else:
        st.warning(f"Local dataset index not found at '{INDEX_PATH_DATASET}'. This data source will be skipped.")
        return None

@st.cache_resource
def load_qft_vectorstore():
    """Loads the QFT and VerilogEval FAISS index if it exists."""
    if os.path.exists(INDEX_PATH_QFT):
        st.write(f"Loading existing QFT/VeriEval FAISS index from '{INDEX_PATH_QFT}'...")
        return FAISS.load_local(INDEX_PATH_QFT, get_embedding_model(), allow_dangerous_deserialization=True)
    else:
        st.warning(f"Local QFT index not found at '{INDEX_PATH_QFT}'. This data source will be skipped.")
        return None

db_verilog_dataset = load_dataset_vectorstore()
db_qft_verieval = load_qft_vectorstore() # NEW: Load the second database


# --- Part 2: LangGraph Multi-Agent Setup ---

class GraphState(TypedDict):
    query: str
    log: List[str]
    documents: List[Document]
    generation: str
    decomposed_files: Dict[str, str]
    testbench_code: Dict[str, str]
    output_path: str
    simulation_output: str
    error_count: int
    top_module_name: str
    summary: str
    theory: str
    waveform_svg: str


def get_graph_viz(active_node: str = None):
    """Generates a Graphviz object to visualize the agent workflow."""
    dot = graphviz.Digraph(comment='Chipster Agent Workflow')
    dot.attr('node', shape='box', style='rounded,filled', fillcolor='lightgrey')
    dot.attr(rankdir='TB', splines='ortho')

    nodes = {
        "dataset_retriever": "1. Dataset Retriever",
        "web_retriever": "2. Web Researcher",
        "code_generator": "3. Verilog Generator",
        "decomposer": "4. Decomposer & Header Extractor", # UPDATED
        "testbench_generator": "5. Testbench Writer",
        "file_writer": "6. File Writer",
        "simulator": "7. Icarus Simulator",
        "check_simulation": "8. Check Results",
        "module_corrector": "9a. Module Corrector",
        "testbench_corrector": "9b. Testbench Corrector",
        "summarizer": "10. Code Summarizer",
        "theory_researcher": "11. Theory Researcher",
        "waveform_viewer": "12. Waveform Viewer"
    }
    for name, label in nodes.items():
        if name == active_node:
            dot.node(name, label, shape='square', style='filled,bold', fillcolor='#FFFF99', fontcolor='black') # Yellow highlight
        else:
            dot.node(name, label, shape='box', style='rounded,filled', fillcolor='#E0E0E0', fontcolor='black') # Light Grey

    # Main flow
    dot.edge("dataset_retriever", "web_retriever")
    dot.edge("web_retriever", "code_generator")
    dot.edge("code_generator", "decomposer")
    dot.edge("decomposer", "testbench_generator")
    dot.edge("testbench_generator", "file_writer")
    dot.edge("file_writer", "simulator")
    dot.edge("simulator", "check_simulation")

    # Success Path
    dot.edge("check_simulation", "summarizer", label="Success", color="green", style="bold")
    dot.edge("summarizer", "theory_researcher")
    dot.edge("theory_researcher", "waveform_viewer")
     
    # Add an END node for clarity
    dot.node("END", "🏁 END", shape="ellipse", style="filled", fillcolor="palegreen")
    dot.edge("waveform_viewer", "END")


    # Conditional Edges from Router
    dot.edge("check_simulation", "testbench_corrector", label="Fix Testbench", color="orange", style="dashed")
    dot.edge("check_simulation", "module_corrector", label="Fix Design", color="red", style="dashed")

    # Correction loop paths
    dot.edge("testbench_corrector", "file_writer", style="dashed")
    dot.edge("module_corrector", "file_writer", style="dashed")

    return dot

# --- Helper Functions ---
def log_code_changes(log: List[str], filename: str, old_code: str, new_code: str) -> List[str]:
    """Generates a diff and adds it to the log."""
    diff = difflib.unified_diff(
        old_code.splitlines(keepends=True),
        new_code.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    diff_str = "".join(diff)
    if diff_str:
        log.append(f"🔍 Code changes for `{filename}`:\n```diff\n{diff_str}```")
    else:
        log.append(f"🔍 No functional changes detected for `{filename}`.")
    return log

# --- Agent Nodes ---

def dataset_retriever_node(state):
    query = state["query"]
    log = state.get("log", []) + ["\n--- AGENT: Dataset Retriever ---"]
    all_docs = []

    # No change to this node, keeping it concise
    if db_verilog_dataset:
        docs1 = db_verilog_dataset.as_retriever(search_kwargs={"k": 10}).invoke(query)
        all_docs.extend(docs1)
        log.append(f"Found {len(docs1)} docs in 'faiss_verilog_db'.")
    if db_qft_verieval:
        docs2 = db_qft_verieval.as_retriever(search_kwargs={"k": 10}).invoke(query)
        all_docs.extend(docs2)
        log.append(f"Found {len(docs2)} docs in 'faiss_qft_verieval'.")
     
    log.append(f"Total documents retrieved from local DBs: {len(all_docs)}")
    return {"documents": all_docs, "log": log}

def web_retriever_node(state):
    return asyncio.run(web_retriever_node_async(state))

async def web_retriever_node_async(state):
    """
    UPDATED NODE: This node has an improved search and crawling strategy
    to find more relevant Verilog code on GitHub.
    """
    query = state["query"]
    existing_docs = state.get("documents", [])
    log = state.get("log", []) + ["\n--- AGENT: Web Researcher ---"]
    embeddings = get_embedding_model()
    sanitized_prompt = re.sub(r'\W+', '_', query).lower()
    index_name = f"faiss_github_{sanitized_prompt}"
    INDEX_PATH_WEB = os.path.join(DATASET_PATH, index_name)
    log.append(f"Checking for cached web index: '{INDEX_PATH_WEB}'")
    web_vectorstore = None
    if os.path.exists(INDEX_PATH_WEB):
        log.append("✅ Cached index found! Loading.")
        web_vectorstore = FAISS.load_local(INDEX_PATH_WEB, embeddings, allow_dangerous_deserialization=True)
    else:
        log.append("❌ No cache. Searching and crawling web...")

        # --- IMPROVED SEARCH LOGIC ---
        # Broader search query to find repositories and code
        search_query = f'"{query}" verilog source code OR design files site:github.com'
        log.append(f"Executing Google search with query: '{search_query}'")
        # Increase search results to get more diverse code examples
        urls = list(search(search_query, num_results=10, lang="en"))
        log.append(f"Found {len(urls)} potential URLs from Google.")
        # Log the first few URLs for debugging
        for i, url in enumerate(urls[:5]):
            log.append(f"  - URL {i+1}: {url}")
        # --- END IMPROVEMENT ---

        if not urls:
             log.append("⚠️ No relevant URLs found on Google search.")
             return {"documents": existing_docs, "log": log}

        new_web_docs = []
        crawled_count = 0
        async with AsyncWebCrawler() as crawler:
            # --- IMPROVED CRAWLING LOGIC ---
            # Process all found URLs instead of just a subset
            log.append(f"Crawling up to {len(urls)} URLs...")
            for url in urls:
                if url and "github.com" in url: # Ensure it's a GitHub link
                    try:
                        result = await crawler.arun(url=url)
                        if result and result.markdown:
                            # Add a check for code content to avoid empty READMEs
                            if "```" in result.markdown or "module" in result.markdown or "input" in result.markdown:
                                new_web_docs.append(Document(page_content=result.markdown, metadata={"source": url}))
                                crawled_count += 1
                                log.append(f"  - ✅ Successfully crawled: {url}")
                            else:
                                log.append(f"  - 🟡 Skipped (no code indicators): {url}")
                        else:
                            log.append(f"  - ⚠️ Crawled but no markdown content: {url}")
                    except Exception as e:
                        log.append(f"  - ❌ Failed to crawl {url}: {e}")
            # --- END IMPROVEMENT ---

        if new_web_docs:
            log.append(f"Successfully extracted content from {crawled_count} URLs.")
            split_docs = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200).split_documents(new_web_docs)
            web_vectorstore = FAISS.from_documents(split_docs, embeddings)
            web_vectorstore.save_local(INDEX_PATH_WEB)
            log.append(f"✅ New web index saved with {len(split_docs)} document chunks.")
        else:
            log.append("Could not retrieve any valid documents from the web.")

    docs_from_web = []
    if web_vectorstore:
        # Retrieve more documents to give the generator more context
        retriever = web_vectorstore.as_retriever(search_kwargs={"k": 15}) # Increased k
        docs_from_web = retriever.invoke(query)
        log.append(f"✅ Retrieved {len(docs_from_web)} relevant document chunks from web cache for the query.")
    else:
        log.append("⚠️ No web vectorstore available to retrieve from.")

    return {"documents": existing_docs + docs_from_web, "log": log}

def code_generator_node(state):
    query = state["query"]
    documents = state["documents"]
    log = state.get("log", []) + ["\n--- AGENT: Verilog Generator ---"]
    log.append("✍️ Generating monolithic code from scratch...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert Verilog HDL designer.
Based on the context from reference documents and the user's request, generate the complete, monolithic Verilog code.
The code should be well-structured and include any necessary `define` macros or parameters at the top.
Your output **MUST** be only the Verilog code, enclosed in a single markdown block. Do not include any other text.

**CONTEXT:**
{context}

**REQUEST:**
{question}

**GENERATED VERILOG CODE:**
```verilog
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
     
    def format_docs(docs):
        if not docs: return "No context documents found."
        return "\n\n".join(f"Source: {doc.metadata.get('source', 'N/A')}\n\n{doc.page_content}" for doc in docs)
         
    rag_chain = ({"context": lambda x: format_docs(x["documents"]), "question": RunnablePassthrough()}| prompt | llm | StrOutputParser())
    generation = rag_chain.invoke({"documents": documents, "question": query}).replace("```verilog", "").replace("```", "").strip()
    log.append("✅ Monolithic code generated.")
     
    return {"generation": generation, "log": log, "simulation_output": ""}

def module_corrector_node(state):
    log = state.get("log", []) + ["\n--- AGENT: Verilog Module Corrector ---"]
    log.append("♻️ Attempting to fix previous design error...")
     
    decomposed_files = state["decomposed_files"]
    error_log = state["simulation_output"]
     
    # Improved logic to find the faulty file
    faulty_filename = None
    for fname in decomposed_files.keys():
        # Icarus often reports errors with file:line format
        if fname in error_log:
            faulty_filename = fname
            break
     
    if not faulty_filename:
        log.append("⚠️ Could not identify a specific faulty module from the error log. No correction applied.")
        return {"decomposed_files": decomposed_files, "log": log}

    faulty_code = decomposed_files[faulty_filename]
    log.append(f"Identified faulty file: `{faulty_filename}`")

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert Verilog debugger.
**TASK:** You are given a single Verilog module that failed during simulation. Analyze the error message and the code, identify the bug, and provide a corrected version of **only that module's code**.
Your output **MUST** be only the corrected Verilog code for the module, enclosed in a single markdown block.

**FAULTY VERILOG MODULE (`{faulty_filename}`):**
```verilog
{faulty_code}
```

**SIMULATION ERROR LOG:**
```
{error_log}
```

**YOUR RESPONSE (Corrected, Complete Verilog Code for the Module Only):**
```verilog
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm | StrOutputParser()
     
    corrected_module_code = chain.invoke({
        "faulty_filename": faulty_filename,
        "faulty_code": faulty_code,
        "error_log": error_log
    }).replace("```verilog", "").replace("```", "").strip()

    updated_files = decomposed_files.copy()
    updated_files[faulty_filename] = corrected_module_code
    log.append(f"✅ Design correction generated for `{faulty_filename}`.")
     
    log = log_code_changes(log, faulty_filename, faulty_code, corrected_module_code)

    return {"decomposed_files": updated_files, "log": log}


def decomposer_node(state):
    """
    UPDATED NODE: This node now also extracts `define` macros and parameters
    into a separate .vh header file and adds `include` statements where needed.
    """
    generation = state["generation"]
    log = state.get("log", []) + ["\n--- AGENT: Decomposer & Header Extractor ---"]
    log.append("Decomposing code and extracting headers...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.0, google_api_key=GOOGLE_API_KEY)
     
    decomposer_prompt_template = """You are an expert Verilog refactoring tool.
Your task is to analyze monolithic Verilog code and decompose it into multiple files.

**RULES:**
1.  Identify the top-level module.
2.  Separate each `module` into its own file (e.g., `module_name.v`).
3.  **Crucially: Identify all `` `define `` macros and shared `parameter` declarations. Move them into a single header file (e.g., `shared_header.vh`).**
4.  In each `.v` file that uses a macro/parameter from the header, add the `` `include "shared_header.vh" `` directive at the top.
5.  Return a single, valid JSON object with two keys: "top_module_name" and "files".
6.  `files` must be an object where keys are filenames (`.v` or `.vh`) and values are the code content.
7.  Your final output **MUST** be only the JSON object.

**USER REQUEST:** {query}
**MONOLITHIC VERILOG CODE:**
```verilog
{verilog_code}
```

**RESPONSE (Valid JSON object only):**
"""
    decomposer_prompt = ChatPromptTemplate.from_template(decomposer_prompt_template)
     
    chain = decomposer_prompt | llm | StrOutputParser()
    response = chain.invoke({"verilog_code": generation, "query": state["query"]})
     
    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            raise json.JSONDecodeError("No JSON object found in the LLM response.", response, 0)
         
        json_str = json_match.group(0)
        parsed_json = json.loads(json_str)
         
        decomposed_files = parsed_json.get("files", {})
        top_module_name = parsed_json.get("top_module_name", "")

        if not decomposed_files or not top_module_name:
             raise ValueError("Parsed JSON is missing 'files' or 'top_module_name' keys.")

        log.append(f"✅ Decomposed into {len(decomposed_files)} files. Top module: `{top_module_name}`")
        if any(".vh" in f for f in decomposed_files.keys()):
            log.append("✅ Header file extracted successfully.")

    except (json.JSONDecodeError, ValueError) as e:
        log.append(f"❌ Failed to parse valid JSON from decomposer. Error: {e}. Falling back to monolithic code.")
        log.append(f"   Raw LLM Response: {response}")
        top_module_match = re.search(r'module\s+([\w#\(\)]+)', generation)
        top_module_name = top_module_match.group(1).split('#')[0].strip() if top_module_match else "unknown_module"
        decomposed_files = {f"{top_module_name}.v": generation}
         
    return {"decomposed_files": decomposed_files, "top_module_name": top_module_name, "log": log}

def testbench_generator_node(state):
    """
    UPDATED NODE: This node now instructs the LLM to create a self-checking
    testbench that explicitly prints PASSED, SUCCESS, or FAILED.
    """
    log = state.get("log", []) + ["\n--- AGENT: Testbench Writer ---"]
    decomposed_files = state["decomposed_files"]
    top_module_name = state["top_module_name"]

    if not decomposed_files:
        log.append("❌ Cannot generate testbench: No decomposed module files were provided.")
        return {"testbench_code": {}, "log": log}

    log.append("✍️ Generating new self-checking testbench...")
    top_module_code = decomposed_files.get(f"{top_module_name}.v", list(decomposed_files.values())[0])
    header_file = next((f for f in decomposed_files if f.endswith('.vh')), None)
    header_include_line = f'- **Include the header file: `` `include "{header_file}" ``**' if header_file else ''

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert in Verilog testbench design.
**TASK:** Write a comprehensive, self-checking testbench for the provided top-level module.

**CRITICAL REQUIREMENTS:**
1.  The testbench module name **MUST** be `{top_module_name}_tb`.
2.  Instantiate the DUT, provide realistic stimuli, and use `$display` or `$monitor` to show results.
3.  It must include a clock signal if needed and terminate automatically using `$finish`.
4.  **Self-Checking:** At the end of the simulation, the testbench must determine if the test passed or failed.
5.  **Clear Output Message:** You **MUST** add a final block that uses `$display` to print **EXACTLY** `"SIMULATION PASSED"` on a new line if all checks are correct.
6.  If any check fails, it must use `$display` to print **EXACTLY** `"SIMULATION FAILED"` on a new line, and then immediately call `$finish`.
7.  **Waveform Generation:** You MUST include these two lines at the start of the initial block:
    `$dumpfile("design.vcd");`
    `$dumpvars(0, {top_module_name}_tb);`
{header_include}
8.  Your final output **MUST** be a single, valid JSON object with one key-value pair: the key is the testbench filename (`{top_module_name}_tb.v`) and the value is the complete testbench code. **DO NOT** include the DUT's code in your response.

**TOP-LEVEL MODULE CODE (for context only):**
```verilog
{top_module_code}
```
**RESPONSE (Valid JSON object containing only the testbench code):**
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
     
    chain = prompt | llm | StrOutputParser()
    response = chain.invoke({
        "top_module_name": top_module_name,
        "top_module_code": top_module_code,
        "header_include": header_include_line
    })

    try:
        json_str = response[response.find('{'):response.rfind('}')+1]
        testbench_json = json.loads(json_str)
        log.append(f"✅ Self-checking testbench generated: `{list(testbench_json.keys())[0]}`")
    except Exception as e:
        log.append(f"❌ Failed to generate valid testbench JSON. Error: {e}")
        testbench_json = {}
         
    return {"testbench_code": testbench_json, "log": log}


def testbench_corrector_node(state):
    log = state.get("log", []) + ["\n--- AGENT: Testbench Corrector ---"]
    log.append("♻️ Attempting to fix previous testbench error...")

    decomposed_files = state["decomposed_files"]
    top_module_name = state["top_module_name"]
    faulty_tb_code_dict = state["testbench_code"]
    error_log = state["simulation_output"]

    top_module_code = decomposed_files.get(f"{top_module_name}.v", list(decomposed_files.values())[0])
    faulty_tb_filename = list(faulty_tb_code_dict.keys())[0] if faulty_tb_code_dict else f"{top_module_name}_tb.v"
    faulty_tb_code = list(faulty_tb_code_dict.values())[0] if faulty_tb_code_dict else "# Faulty testbench code was not found"

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2, google_api_key=GOOGLE_API_KEY)
     
    prompt_template = """You are an expert Verilog testbench debugger.
**TASK:** You are given a testbench that failed during simulation. Analyze the error message, the testbench code, and the module it is testing (DUT). Provide a corrected version of **only the testbench code**.

**CRITICAL REQUIREMENTS:**
1.  **Self-Checking:** Ensure the corrected testbench explicitly prints `"SIMULATION PASSED"` or `"SIMULATION FAILED"` at the end.
2.  **Waveform Generation:** Ensure the corrected testbench includes `$dumpfile("design.vcd");` and `$dumpvars(0, {top_module_name}_tb);`.
3.  Your final output **MUST** be a single JSON object containing the corrected testbench. The key must be the original testbench filename.

**SIMULATION ERROR LOG:**
```
{error_log}
```

**FAULTY TESTBENCH CODE (`{faulty_tb_filename}`):**
```verilog
{faulty_tb_code}
```

**DEVICE UNDER TEST (DUT) CODE (`{top_module_name}.v`) (for context only):**
```verilog
{top_module_code}
```

**RESPONSE (Valid JSON object containing only the corrected testbench code):**
"""
    prompt = ChatPromptTemplate.from_template(prompt_template)
    chain = prompt | llm | StrOutputParser()
     
    response = chain.invoke({
        "top_module_name": top_module_name,
        "top_module_code": top_module_code,
        "error_log": error_log,
        "faulty_tb_filename": faulty_tb_filename,
        "faulty_tb_code": faulty_tb_code
    })

    try:
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            raise json.JSONDecodeError("No JSON object found in the LLM response.", response, 0)
         
        json_str = json_match.group(0)
        corrected_testbench_json = json.loads(json_str)

        if not isinstance(corrected_testbench_json, dict) or not corrected_testbench_json:
            raise ValueError("Parsed JSON is not a valid, non-empty dictionary.")
         
        corrected_tb_filename = list(corrected_testbench_json.keys())[0]
        corrected_tb_code = corrected_testbench_json[corrected_tb_filename]

        log.append(f"✅ Testbench correction generated for: `{corrected_tb_filename}`")
        log = log_code_changes(log, corrected_tb_filename, faulty_tb_code, corrected_tb_code)

    except (json.JSONDecodeError, ValueError) as e:
        log.append(f"❌ Failed to generate valid corrected testbench JSON. Error: {e}")
        log.append(f"   Raw LLM Response: {response}")
        corrected_testbench_json = faulty_tb_code_dict
         
    return {"testbench_code": corrected_testbench_json, "log": log}


def file_writer_node(state):
    log = state.get("log", []) + ["\n--- AGENT: File Writer ---"]
    query = state["query"]
    decomposed_files = state["decomposed_files"]
    testbench_code = state.get("testbench_code", {})
    sanitized_prompt = re.sub(r'\W+', '_', query).lower()
    output_path = os.path.join(GENERATED_CODE_PATH, f"generated_{sanitized_prompt}")
    os.makedirs(output_path, exist_ok=True)
    log.append(f"Writing files to: `{output_path}`")

    all_files_to_write = {**decomposed_files, **testbench_code}
    for filename, content in all_files_to_write.items():
        # Sanitize filename just in case
        safe_filename = re.sub(r'[^\w\.\-]', '_', filename)
        if isinstance(content, str) and content.strip():
            with open(os.path.join(output_path, safe_filename), 'w') as f:
                f.write(content)
            log.append(f"  - Wrote `{safe_filename}`")
        else:
            log.append(f"  - ⚠️ Skipped writing `{safe_filename}` due to invalid content.")
             
    return {"output_path": output_path, "log": log}

def simulator_node(state):
    """
    UPDATED NODE: Runs simulation and checks stdout for explicit
    PASSED, SUCCESS, or FAILED messages to determine the outcome.
    """
    log = state.get("log", []) + ["\n--- AGENT: Icarus Simulator ---"]
    output_path = state["output_path"]
    log.append(f"Preparing to simulate files in `{output_path}`")

    verilog_filenames = [os.path.basename(f) for f in glob.glob(os.path.join(output_path, "*.v"))]
    if not verilog_filenames:
        log.append("❌ No `.v` files found to simulate.")
        return {"simulation_output": "Error: No Verilog files found.", "log": log}
     
    output_vvp_filename = "design.vvp"
    command = ["iverilog", "-o", output_vvp_filename] + verilog_filenames
     
    simulation_output = ""
    try:
        log.append(f"Running compilation in `{output_path}`...")
        log.append(f"Command: `{' '.join(command)}`")
        compile_process = subprocess.run(
            command, capture_output=True, text=True, timeout=30, cwd=output_path
        )
         
        if compile_process.returncode != 0:
            raise subprocess.CalledProcessError(compile_process.returncode, compile_process.args, output=compile_process.stdout, stderr=compile_process.stderr)
             
        log.append("✅ Compilation successful.")
         
        sim_command = ["vvp", output_vvp_filename]
        log.append(f"Running simulation in `{output_path}`...")
        log.append(f"Command: `{' '.join(sim_command)}`")
        sim_process = subprocess.run(
            sim_command, capture_output=True, text=True, check=True, timeout=30, cwd=output_path
        )
        
        # --- NEW VERIFICATION LOGIC ---
        stdout = sim_process.stdout
        log.append("✅ Simulation finished. Verifying output...")
        log.append(f"```\n{stdout}\n```")

        if re.search(r'SIMULATION PASSED|SUCCESS', stdout, re.IGNORECASE):
            log.append("✅ Verification PASSED.")
            simulation_output = "" # Clear output on success
        elif re.search(r'SIMULATION FAILED|FAIL', stdout, re.IGNORECASE):
            log.append("❌ Verification FAILED.")
            simulation_output = f"ERROR: Testbench reported failure.\n{stdout}"
        else:
            log.append("⚠️ Verification AMBIGUOUS: No explicit PASS/FAIL message found.")
            # Treat ambiguous as failure to enforce good testbench practice
            simulation_output = f"ERROR: Ambiguous result. Testbench did not report PASS or FAIL.\n{stdout}"
        # --- END NEW LOGIC ---

    except subprocess.CalledProcessError as e:
        error_message = e.stderr or e.stdout or "Unknown simulation error."
        simulation_output = f"ERROR during {'compilation' if 'iverilog' in ' '.join(e.cmd) else 'simulation'}:\n{error_message}"
        log.append(f"❌ Simulation Failed.")
    except subprocess.TimeoutExpired:
        simulation_output = "ERROR: Simulation timed out. The testbench may have an infinite loop or is not finishing with `$finish`."
        log.append(f"❌ {simulation_output}")

    if "ERROR" not in simulation_output and not simulation_output:
        return {"simulation_output": "", "log": log}
    else:
        error_count = state.get("error_count", 0) + 1
        return {"simulation_output": simulation_output, "error_count": error_count, "log": log}


def check_simulation_results_node(state):
    log = state.get("log", []) + ["\n--- ROUTER: Checking Results ---"]
    simulation_output = state.get("simulation_output", "")
    error_count = state.get("error_count", 0)
     
    if not simulation_output:
        log.append("✅ Success! Routing to final documentation.")
        return "success"

    log.append(f"⚠️ Error detected on attempt {error_count + 1}.")
    if error_count >= MAX_RETRIES:
        log.append(f"❌ Maximum retry limit ({MAX_RETRIES}) reached. Halting workflow.")
        return "end"
     
    tb_files = [f for f in state.get("testbench_code", {}).keys()]
    # Check for testbench file names in the error, timeout, or explicit failure messages
    is_tb_error = (
        any(tb_file in simulation_output for tb_file in tb_files if tb_file) or
        "timeout" in simulation_output.lower() or
        "reported failure" in simulation_output.lower() or
        "ambiguous result" in simulation_output.lower()
    )

    if is_tb_error:
        log.append("Routing to: Testbench Corrector")
        return "fix_testbench"
    else:
        log.append("Routing to: Module Corrector")
        return "fix_design"

def summarizer_node(state):
    log = state.get("log", []) + ["\n--- AGENT: Code Summarizer ---"]
    log.append("Generating code summary...")
     
    top_module_name = state["top_module_name"]
    top_module_code = state["decomposed_files"].get(f"{top_module_name}.v", "")

    if not top_module_code:
        log.append("⚠️ Top module code not found for summarization.")
        return {"summary": "Could not generate summary because the top-level module code was not found.", "log": log}

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.0, google_api_key=GOOGLE_API_KEY)
    prompt = ChatPromptTemplate.from_template(
        """You are a technical writer for hardware design. Based on the Verilog code, create a concise summary.
        Include:
        1.  **Purpose**: One sentence on what the module does.
        2.  **Ports**: Lists of input and output ports with bit widths.
        3.  **Functionality**: A short paragraph on its behavior.

        **Top-Level Module Code (`{module_name}.v`):**
        ```verilog
        {module_code}
        ```
        **Your Summary:**
        """
    )
     
    chain = prompt | llm | StrOutputParser()
    summary = chain.invoke({"module_name": top_module_name, "module_code": top_module_code})
     
    log.append("✅ Summary generated.")
    return {"summary": summary, "log": log}

async def theory_researcher_node_async(state):
    log = state.get("log", []) + ["\n--- AGENT: Theory Researcher ---"]
    query = state["query"]
    log.append(f"Researching theory for: '{query}'...")

    search_query = f"explain {query} digital logic design"
    urls = list(search(search_query, num_results=1, lang="en"))

    if not urls:
        log.append("⚠️ No relevant theory explanation found on the web.")
        return {"theory": "Could not find a relevant theoretical explanation for this topic.", "log": log}

    explanation_content = ""
    async with AsyncWebCrawler() as crawler:
        if urls[0]:
            try:
                result = await crawler.arun(url=urls[0])
                if result and result.markdown:
                    explanation_content = result.markdown
            except Exception as e:
                log.append(f"⚠️ Failed to crawl {urls[0]}: {e}")
                return {"theory": "Failed to retrieve information from the web.", "log": log}

    if not explanation_content:
        log.append("⚠️ Crawled page has no content.")
        return {"theory": "Could not extract content from the web page.", "log": log}

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.0, google_api_key=GOOGLE_API_KEY)
    prompt = ChatPromptTemplate.from_template(
        """You are an expert in digital logic. Based on the text provided, write a concise explanation of the concept requested by the user.
        Focus on fundamental principles.

        **User's Request:** {original_query}
        **Content from Webpage:**
        ```
        {web_content}
        ```
        **Your Concise Explanation:**
        """
    )
    chain = prompt | llm | StrOutputParser()
    theory = chain.invoke({"original_query": query, "web_content": explanation_content})

    log.append("✅ Theoretical explanation generated.")
    return {"theory": theory, "log": log}

def theory_researcher_node(state):
    return asyncio.run(theory_researcher_node_async(state))

def waveform_viewer_node(state):
    """Generates an SVG waveform from the VCD file using Sootty."""
    log = state.get("log", []) + ["\n--- AGENT: Waveform Viewer ---"]
    output_path = state["output_path"]
    vcd_path = os.path.join(output_path, "design.vcd")
     
    log.append(f"Looking for VCD file at: `{vcd_path}`")

    if not os.path.exists(vcd_path) or os.path.getsize(vcd_path) == 0:
        log.append("⚠️ VCD file not found or is empty. Skipping waveform generation.")
        return {"waveform_svg": "", "log": log}
         
    log.append("✅ Found VCD file. Generating waveform image with Sootty...")
     
    try:
        wiretrace = WireTrace.from_vcd(vcd_path)
        # Render all wires for a comprehensive view
        wires_to_render = wiretrace.get_wires()
        image = Visualizer(Style.Dark).to_svg(wiretrace, start=0, length=2000, wires=wires_to_render)
        # Convert SVG object to a base64 encoded string for reliable display
        svg_string = image.decode('utf-8')
        log.append("✅ Waveform SVG generated successfully.")
        return {"waveform_svg": svg_string, "log": log}
    except Exception as e:
        log.append(f"❌ Failed to generate waveform with Sootty: {e}")
        return {"waveform_svg": "", "log": log}

# --- Graph Definition ---
def build_graph():
    workflow = StateGraph(GraphState)
    workflow.add_node("dataset_retriever", dataset_retriever_node)
    workflow.add_node("web_retriever", web_retriever_node)
    workflow.add_node("code_generator", code_generator_node)
    workflow.add_node("module_corrector", module_corrector_node)
    workflow.add_node("decomposer", decomposer_node)
    workflow.add_node("testbench_generator", testbench_generator_node)
    workflow.add_node("testbench_corrector", testbench_corrector_node)
    workflow.add_node("file_writer", file_writer_node)
    workflow.add_node("simulator", simulator_node)
    workflow.add_node("summarizer", summarizer_node)
    workflow.add_node("theory_researcher", theory_researcher_node)
    workflow.add_node("waveform_viewer", waveform_viewer_node)

    workflow.set_entry_point("dataset_retriever")
    workflow.add_edge("dataset_retriever", "web_retriever")
    workflow.add_edge("web_retriever", "code_generator")
    workflow.add_edge("code_generator", "decomposer")
    workflow.add_edge("decomposer", "testbench_generator")
    workflow.add_edge("testbench_generator", "file_writer")
    workflow.add_edge("file_writer", "simulator")
     
    workflow.add_edge("summarizer", "theory_researcher")
    workflow.add_edge("theory_researcher", "waveform_viewer")
    workflow.add_edge("waveform_viewer", END)

    workflow.add_edge("module_corrector", "file_writer")
    workflow.add_edge("testbench_corrector", "file_writer")
     
    workflow.add_conditional_edges(
        "simulator",
        check_simulation_results_node,
        {
            "success": "summarizer",
            "fix_testbench": "testbench_corrector",
            "fix_design": "module_corrector",
            "end": END
        }
    )
     
    # The recursion limit is set during the stream/invoke call, not at compile time.
    return workflow.compile()

app = build_graph()


# --- Part 3: Streamlit UI ---
st.sidebar.header("Controls")
user_query = st.sidebar.text_area("Describe the Verilog module you want to build:", height=150, value="risc v 32 bit")

if st.sidebar.button("✨ Generate & Verify Code", use_container_width=True):
    if not user_query:
        st.sidebar.error("Please enter a description for the Verilog module.")
    else:
        st.subheader("🚀 Agent Workflow Visualization")
        graph_placeholder = st.empty()
         
        col1, col2 = st.columns([1, 2])
        with col1:
            log_expander = st.expander("Agent Activity Log", expanded=True)
            log_container = log_expander.container()
         
        with col2:
            results_expander = st.expander("Final Results & Files", expanded=True)
            results_placeholder = results_expander.container()


        graph_placeholder.graphviz_chart(get_graph_viz())
        inputs = {"query": user_query, "error_count": 0, "summary": "", "theory": "", "waveform_svg": ""}
         
        with st.spinner("Chipster Agent is thinking... This may take a few minutes for complex designs."):
            final_result = None
            log_messages = []
             
            # Set the recursion limit for this specific run in the config.
            config = {"recursion_limit": 100}
            for s in app.stream(inputs, config=config, stream_mode="values"):
                active_node = list(s.keys())[-1]
                graph_placeholder.graphviz_chart(get_graph_viz(active_node))
                final_result = s
                if "log" in final_result:
                    new_logs = final_result["log"][len(log_messages):]
                    for msg in new_logs:
                        log_container.markdown(f"{msg.strip()}", unsafe_allow_html=True)
                        log_messages.append(msg)
             
            graph_placeholder.graphviz_chart(get_graph_viz("END"))
             
            results_placeholder.subheader("🏁 Final Outcome")
            if final_result.get("simulation_output"): # Check if error output exists
                results_placeholder.error(f"Workflow halted with an error after {final_result.get('error_count', 0)} retries.")
                with results_placeholder.expander("🚨 View Final Simulation Error", expanded=True):
                    st.code(final_result.get("simulation_output"), language='bash')
            else:
                st.balloons()
                results_placeholder.success(f"✅ All Verilog files generated, verified, and saved to: `{final_result.get('output_path', 'N/A')}`")
             
            if final_result.get("summary"):
                with results_placeholder.expander("📝 Code Summary", expanded=True):
                    st.markdown(final_result["summary"])
             
            if final_result.get("theory"):
                with results_placeholder.expander("🎓 Theory & Explanation", expanded=True):
                    st.markdown(final_result["theory"])
             
            # Display Waveform if it exists
            if final_result.get("waveform_svg"):
                with results_placeholder.expander("📈 Waveform Visualization", expanded=True):
                    # Display SVG directly for better rendering
                    st.image(final_result["waveform_svg"], use_column_width=True)
            elif not final_result.get("simulation_output"): # Only show if successful
                 with results_placeholder.expander("📈 Waveform Visualization", expanded=True):
                    st.warning("Waveform data was not generated. This can happen if the testbench does not properly exercise the design or if the simulation is very short.")


            results_placeholder.write("---")
            results_placeholder.subheader("Generated Files & Content")
            all_files = {
                **final_result.get("decomposed_files", {}),
                **final_result.get("testbench_code", {})
            }
            if all_files:
                # Sort files to show headers first, then top module, then others
                sorted_files = sorted(all_files.items(), key=lambda item: (not item[0].endswith('.vh'), item[0] != f"{final_result.get('top_module_name')}.v", item[0]))
                for filename, content in sorted_files:
                    icon = "📄"
                    if filename.endswith("_tb.v"):
                        icon = "🧪"
                    elif filename.endswith(".vh"):
                        icon = "📚"
                    with results_placeholder.expander(f"{icon} **{filename}**"):
                        st.code(content, language='verilog')
else:
    st.info("Enter your Verilog design requirements in the sidebar and click 'Generate & Verify'.")


# === chipster/src/chip_digital_generator/main.py ===
import streamlit as st
import os
import json
import pandas as pd
from langgraph.graph import StateGraph, END, START
from typing import TypedDict, List, Dict, Any, Optional
import shutil
from openlane.state import State
from openlane.steps import Step
from openlane.config import Config
from pathlib import Path
import re
import subprocess
import difflib
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Gemini LLM Initialization ---
try:
    # Use a more advanced model for better reasoning in code generation
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro")
    st.sidebar.success("Gemini 2.5 Pro Initialized")
except Exception as e:
    st.error(f"Error initializing Gemini LLM: {e}. Make sure your GOOGLE_API_KEY is set in a .env file.")
    llm = None

# --- Agentic Workflow State ---
class AgentState(TypedDict):
    uploaded_files: List[Any]
    top_level_module: str
    design_name: str
    verilog_files: List[str]
    original_verilog_code: Dict[str, str]
    modified_verilog_code: Optional[str]
    decomposed_files: Dict[str, str]
    testbench_file: Optional[str]
    original_testbench_code: Optional[str]
    modified_testbench_code: Optional[str]
    config: Dict[str, Any]
    run_path: str
    current_src_dir: str # Tracks the latest source code directory
    update_attempt: int
    # Constraints
    max_die_width_mm: float
    max_die_height_mm: float
    max_pins: int
    # Metrics
    die_width_mm: float
    die_height_mm: float
    pin_count: int
    # Flow Control
    simulation_passed: bool
    simulation_output: str
    simulation_verified: bool
    feedback_log: List[str]
    lvs_passed: bool
    # OpenLane States
    synthesis_state_out: Optional[State]
    floorplan_state_out: Optional[State]
    tap_endcap_state_out: Optional[State]
    io_placement_state_out: Optional[State]
    pdn_state_out: Optional[State]
    global_placement_state_out: Optional[State]
    detailed_placement_state_out: Optional[State]
    cts_state_out: Optional[State]
    global_routing_state_out: Optional[State]
    detailed_routing_state_out: Optional[State]
    fill_insertion_state_out: Optional[State]
    rcx_state_out: Optional[State]
    sta_state_out: Optional[State]
    stream_out_state_out: Optional[State]
    drc_state_out: Optional[State]
    spice_extraction_state_out: Optional[State]
    lvs_state_out: Optional[State]
    lvs_step_dir: Optional[str]
    worst_tns: Optional[float]
    worst_wns: Optional[float]


# --- Agent Definitions ---

def file_processing_agent(state: AgentState) -> Dict[str, Any]:
    """
    Initial agent to set up the environment, process uploaded files,
    and separate design files from the testbench.
    """
    st.write("---")
    st.write("### 📂 Agent 1: File Processing")
    st.info("This agent processes uploaded Verilog files, creates a dedicated run directory, and separates design files from the testbench.")
    uploaded_files = state["uploaded_files"]
    top_level_module = state["top_level_module"]
    design_name = top_level_module

    # Create a clean, dedicated directory for this run
    run_path = os.path.abspath(os.path.join("..", "..", "examples", "generated_chips", f"generated_{design_name}"))
    if os.path.exists(run_path):
        shutil.rmtree(run_path)
    os.makedirs(run_path, exist_ok=True)

    src_dir = os.path.join(run_path, "src")
    os.makedirs(src_dir, exist_ok=True)

    verilog_files = []
    original_verilog_code = {}
    testbench_file = None
    original_testbench_code = None

    # Process and save each uploaded file
    for file in uploaded_files:
        file_path = os.path.join(src_dir, file.name)
        file_content_buffer = file.getbuffer()
        with open(file_path, "wb") as f:
            f.write(file_content_buffer)

        if file.name.endswith((".v", ".vh")):
            decoded_content = file_content_buffer.tobytes().decode('utf-8', errors='ignore')
            # Heuristic to identify testbench files
            if "tb" in file.name.lower() or "testbench" in file.name.lower():
                    testbench_file = file_path
                    original_testbench_code = decoded_content
            else:
                    verilog_files.append(file_path)
                    original_verilog_code[file.name] = decoded_content

    st.write(f"✅ Top-level module '{top_level_module}' selected.")
    st.write(f"✅ Verilog files saved in: `{src_dir}`")
    if testbench_file:
        st.write(f"✅ Testbench file found: `{os.path.basename(testbench_file)}`")
    else:
        st.warning("⚠️ No testbench file detected. Simulation will be skipped.")

    # Change the current working directory to the run path for tool compatibility
    os.chdir(run_path)
    st.write(f"✅ Changed working directory to: `{os.getcwd()}`")

    # Ensure testbench_file path is relative if it exists
    relative_tb_path = os.path.relpath(testbench_file, os.getcwd()) if testbench_file else None

    return {
        "design_name": design_name,
        "verilog_files": [os.path.relpath(p, os.getcwd()) for p in verilog_files],
        "original_verilog_code": original_verilog_code,
        "decomposed_files": original_verilog_code, # Initially, decomposed is same as original
        "testbench_file": relative_tb_path,
        "original_testbench_code": original_testbench_code,
        "run_path": os.getcwd(),
        "current_src_dir": src_dir, # Set the initial src directory
        "feedback_log": ["Starting the design flow."],
        "update_attempt": 0,
    }

def verilog_corrector_agent(state: AgentState) -> Dict[str, Any]:
    """
    Uses an LLM to rewrite Verilog code based on feedback from failed tool runs,
    focusing on reducing area or fixing simulation errors.
    """
    st.write("---")
    st.write("### 🧠 Agent 2: Verilog Area/Sim Corrector (LLM)")
    st.info("This agent uses an LLM to rewrite Verilog to fix simulation errors or reduce the design's physical area.")

    if not llm:
        st.error("Gemini LLM not initialized. Skipping correction.")
        return {"modified_verilog_code": "\n".join(state["original_verilog_code"].values())}

    feedback = "\n".join(state['feedback_log'])
    st.write("#### Feedback for Correction (Area/Simulation):")
    st.code(feedback, language='text')

    prompt = f"""
    You are an expert Verilog designer. Your task is to optimize the given Verilog code based on the following feedback from a failed EDA tool run.
    The primary goal is to **simplify the design to reduce its area** or fix simulation errors.

    **Feedback from Tools:**
    {feedback}

    **Optimization Strategies (Apply in order of priority):**
    1.  **Operator Strength Reduction:** Replace expensive operators like multipliers (`*`) with a series of additions or bit-shifts if possible.
    2.  **Module Simplification/Removal:** If a module is used with constant inputs, replace its instantiation with the pre-calculated result. Simplify or remove modules if their full functionality is not required.
    3.  **Aggressive Bit-width Reduction:** This is a critical step for area reduction. Analyze the logic and drastically reduce the bit-width of registers, wires, and parameters. For example, if a 32-bit register only ever holds values up to 100, reduce it to 7 bits (`[6:0]`). You MUST ensure this change is propagated to all connected modules and calculations.

    **RULES:**
    - You MUST generate pure, synthesizable Verilog-2001 compatible code.
    - Combine all Verilog modules into a single, monolithic block of code.
    - Do NOT include the testbench.
    - Your output MUST be only the Verilog code, enclosed in a single markdown block.

    **Original Verilog Code:**
    ---
    """
    code_to_correct = state.get("decomposed_files") or state["original_verilog_code"]
    for filename, code in code_to_correct.items():
        prompt += f"--- {filename} ---\n{code}\n"
    prompt += "---"

    st.write("🤖 Asking Gemini to optimize the Verilog code for Area/Sim...")
    try:
        response = llm.invoke(prompt)
        response_content = response.content
        st.write("#### Gemini's Raw Response:")
        st.markdown(response_content)

        # Robustly extract Verilog code from the markdown response
        modified_code_match = re.search(r"```(?:verilog)?\s*\n(.*?)```", response_content, re.DOTALL)
        if not modified_code_match:
            st.error("LLM response parsing failed. Could not find a valid Verilog code block. Falling back to previous code version.")
            return {"modified_verilog_code": "\n".join(code_to_correct.values())}

        modified_verilog_code = modified_code_match.group(1).strip()
        if not modified_verilog_code:
            st.error("LLM response parsing failed. The Verilog code block was empty. Falling back to previous code version.")
            return {"modified_verilog_code": "\n".join(code_to_correct.values())}

        st.success("✅ Successfully extracted optimized Verilog code from LLM response.")
        return {"modified_verilog_code": modified_verilog_code}

    except Exception as e:
        st.error(f"An error occurred while communicating with the Gemini API: {e}")
        import traceback
        st.code(traceback.format_exc())
        return {"modified_verilog_code": "\n".join(code_to_correct.values())}

def code_decomposer_agent(state: AgentState) -> Dict[str, Any]:
    """
    After an LLM generates a single block of Verilog, this agent splits it
    back into separate files, one for each module.
    """
    st.write("---")
    st.write("### 🧩 Agent 3: Code Decomposer (LLM-Powered)")
    st.info("After an LLM generates a single block of corrected Verilog, this agent intelligently splits it back into separate files, one for each module.")

    monolithic_code = state.get("modified_verilog_code")
    if not monolithic_code:
        st.error("No modified Verilog code found to decompose.")
        return {"decomposed_files": state.get("decomposed_files", state["original_verilog_code"])}

    st.write("Decomposing LLM-generated code into separate files using Gemini...")

    prompt = f"""
    You are an expert Verilog refactoring tool.
    Your task is to analyze the following monolithic Verilog code and decompose it into multiple files.

    **RULES:**
    1.  Separate each `module` into its own file. The filename should be the module name with a `.v` extension (e.g., `module_name.v`).
    2.  Any file that starts with `// --- Start of content from <filename> ---` should be extracted into its own file with that <filename>.
    3.  Return a single, valid JSON object where keys are the filenames and values are the complete code content for that file.
    4.  Your final output **MUST** be only the JSON object, enclosed in a markdown block.

    **MONOLITHIC VERILOG CODE:**
    ```verilog
    {monolithic_code}
    ```
    """

    response = llm.invoke(prompt)
    st.write("#### Decomposer LLM Response:")
    st.markdown(response.content)

    try:
        # Robustly extract JSON from the markdown response
        json_str = None
        match = re.search(r"```json\s*(\{.*?\})\s*```", response.content, re.DOTALL)
        if match:
            json_str = match.group(1)
        else: # Fallback for cases where the markdown block is missing
            start = response.content.find('{')
            end = response.content.rfind('}')
            if start != -1 and end != -1 and end > start:
                json_str = response.content[start:end+1]

        if not json_str:
            raise json.JSONDecodeError("No valid JSON object found in the LLM response.", response.content, 0)

        decomposed_files = json.loads(json_str)

        if not isinstance(decomposed_files, dict) or not decomposed_files:
            raise ValueError("Parsed JSON is not a valid, non-empty dictionary.")

        st.write("✅ Decomposed code successfully:")
        for filename in decomposed_files.keys():
            st.write(f"  - Created `{filename}`")

    except (json.JSONDecodeError, ValueError) as e:
        st.error(f"Failed to parse valid JSON from decomposer. Error: {e}. Falling back to previous version.")
        return {"decomposed_files": state.get("decomposed_files", state["original_verilog_code"])}

    return {"decomposed_files": decomposed_files}

def design_name_updater_agent(state: AgentState) -> Dict[str, Any]:
    """
    Analyzes decomposed files to find the new top-level module name after
    code modifications, as the LLM might rename it.
    """
    st.write("---")
    st.write("### 📝 Agent 3.5: Design Name Updater")
    st.info("This agent analyzes the decomposed files to find the new top-level module name after code modifications.")

    decomposed_files = state["decomposed_files"]
    if not decomposed_files:
        st.warning("No decomposed files to analyze. Keeping original design name.")
        return {}

    # Find all defined modules (from filenames, excluding .vh files)
    defined_modules = {Path(f).stem for f in decomposed_files.keys() if f.endswith(".v")}

    # Find all instantiated modules by scanning the code
    instantiated_modules = set()
    # Regex to find module instantiations, ignoring keywords and port connections
    instantiation_re = re.compile(r"^\s*(\w+)\s+(?:#\s*\(.*\)\s*)?\w+\s*\(", re.MULTILINE)

    for content in decomposed_files.values():
        matches = instantiation_re.findall(content)
        for module_name in matches:
            # Filter out Verilog keywords that might look like instantiations
            if module_name not in ["module", "input", "output", "wire", "reg", "always", "assign", "case", "if", "for", "function"]:
                instantiated_modules.add(module_name)

    # The top-level module is defined but never instantiated
    top_level_candidates = defined_modules - instantiated_modules

    new_design_name = state["design_name"]

    if len(top_level_candidates) == 1:
        new_design_name = top_level_candidates.pop()
        if new_design_name != state["design_name"]:
            st.success(f"✅ New top-level module detected: **{new_design_name}**")
        else:
            st.write("✅ Top-level module name remains the same.")
    elif len(top_level_candidates) > 1:
        st.warning(f"Multiple top-level candidates found: {top_level_candidates}. Defaulting to the previous name: {new_design_name}")
    else: # No candidates found, might be a single-module design
        if len(defined_modules) == 1:
            new_design_name = defined_modules.pop()
            st.write(f"✅ Single module design detected. Setting top-level to: **{new_design_name}**")
        else:
            st.warning(f"Could not determine a unique top-level module. Defaulting to the previous name: {new_design_name}")

    return {
        "design_name": new_design_name,
        "top_level_module": new_design_name
    }

def testbench_corrector_agent(state: AgentState) -> Dict[str, Any]:
    """
    Uses an LLM to update the testbench to match the (potentially modified)
    design and adds explicit, timed self-checking logic.
    """
    st.write("---")
    st.write("### 🧠 Agent 4: Testbench Corrector (LLM)")
    st.info("This agent updates the testbench to match the design and adds explicit, timed self-checking.")

    if not llm or not state.get("original_testbench_code"):
        st.warning("No LLM or original testbench found. Skipping testbench correction.")
        return {}

    # Use the most recently modified testbench if available, otherwise use the original
    tb_to_correct = state.get("modified_testbench_code") or state["original_testbench_code"]

    prompt = f"""
    You are an expert Verilog testbench writer. Your task is to create a robust, self-checking testbench compatible with the provided design modules. The design may be pipelined and require time to produce a valid output.

    **Design Modules:**
    ---
    """
    for filename, code in state['decomposed_files'].items():
        prompt += f"--- {filename} ---\n{code}\n"

    prompt += f"""
    ---
    **Original Testbench Code (`{os.path.basename(state['testbench_file'])}`):**
    ---
    {tb_to_correct}
    ---

    **CRITICAL INSTRUCTIONS FOR A ROBUST TESTBENCH:**
    1.  **Update Instantiation:** Ensure the testbench correctly instantiates and connects to the design under test, especially if the module name or ports have changed. The top-level module is `{state['top_level_module']}`.
    2.  **Initial Reset:** The testbench MUST start with a proper reset sequence for the design.
    3.  **Wait for Pipeline Latency:** After applying the stimulus (inputs), you MUST add a significant delay (e.g., `#100` or more) before checking the outputs. This allows time for the pipelined logic to compute the result.
    4.  **Self-Checking Logic:** At the end of the simulation, the testbench must determine if the test passed or failed based on the final output values.
    5.  **Clear Output Message:** You **MUST** add a final block that uses `$display` to print **EXACTLY** `"Result: PASSED"` on a new line if all checks are correct. Do not add any other characters or emojis.
    6.  If any check fails, it must use `$display` to print **EXACTLY** `"Result: FAILED"` on a new line, and then immediately call `$finish`.
    7.  The testbench must end with a `$finish;` statement after the final check.

    Provide the updated, complete, and robust self-checking testbench code in a single Verilog code block.
    """

    st.write("🤖 Asking Gemini to update the testbench with self-checking and proper timing...")
    response = llm.invoke(prompt)
    st.write("#### Gemini's Response:")
    st.markdown(response.content)

    modified_code = re.search(r"```(?:verilog)?\s*\n(.*?)```", response.content, re.DOTALL)
    if not modified_code:
        st.error("Could not extract corrected testbench code from LLM response.")
        return {"modified_testbench_code": tb_to_correct}

    corrected_tb_code = modified_code.group(1).strip()

    st.write("#### Testbench Changes:")
    diff = difflib.unified_diff(
        tb_to_correct.splitlines(keepends=True),
        corrected_tb_code.splitlines(keepends=True),
        fromfile='original_tb', tofile='modified_tb',
    )
    st.code(''.join(diff), language='diff')

    return {"modified_testbench_code": corrected_tb_code}


def file_saver_agent(state: AgentState) -> Dict[str, Any]:
    """
    Saves the corrected and decomposed Verilog files to a versioned subdirectory
    to ensure a clean state for the next tool run.
    """
    st.write("---")
    st.write("### 💾 Agent 5: File Saver")
    st.info("This agent saves the newly corrected and decomposed Verilog files to a versioned subdirectory, ensuring a clean state for the next simulation or layout attempt.")

    update_attempt = state.get("update_attempt", 0) + 1

    # Create a new versioned directory for this update attempt
    save_path = os.path.join(state['run_path'], f"updated_codes_{update_attempt}")
    os.makedirs(save_path, exist_ok=True)
    st.write(f"Saving updated files to: `{save_path}`")

    verilog_to_save = state["decomposed_files"]
    tb_to_save = state.get("modified_testbench_code") or state["original_testbench_code"]

    saved_verilog_files = []

    # Save design files
    for filename, content in verilog_to_save.items():
        file_path = os.path.join(save_path, filename)
        with open(file_path, 'w') as f: f.write(content)
        saved_verilog_files.append(os.path.relpath(file_path, state['run_path']))
        st.write(f"  - Saved `{filename}`")

    # Save testbench file if it exists
    if state.get("testbench_file") and tb_to_save:
        tb_filename = os.path.basename(state["testbench_file"])
        file_path = os.path.join(save_path, tb_filename)
        with open(file_path, 'w') as f: f.write(tb_to_save)
        st.write(f"  - Saved `{tb_filename}`")
        # Update the state to point to the new testbench location
        state["testbench_file"] = os.path.relpath(file_path, state['run_path'])


    return {
        "verilog_files": saved_verilog_files,
        "update_attempt": update_attempt,
        "current_src_dir": save_path # IMPORTANT: Update the current source directory
    }


def icarus_simulation_agent(state: AgentState) -> Dict[str, Any]:
    """
    Compiles and runs a simulation using the Icarus Verilog simulator.
    """
    st.write("---")
    st.write("### 🔬 Agent 6: Icarus Simulation")
    st.info("This agent compiles and runs a simulation using the Icarus Verilog simulator to functionally verify the design's behavior.")

    if not state.get('testbench_file'):
        st.warning("No testbench file found. Skipping simulation.")
        # Treat as passed so the flow can continue to synthesis
        return {"simulation_passed": True, "simulation_verified": True, "simulation_output": "No testbench provided."}

    run_path = state['run_path']
    current_src_dir = state['current_src_dir'] # Get the current source directory

    # Files are already relative to the run_path, so we just need the directory for the -I flag
    verilog_files_to_sim = [os.path.join(run_path, f) for f in state['verilog_files']]
    testbench_path = os.path.join(run_path, state['testbench_file'])
    all_files_for_sim = verilog_files_to_sim + [testbench_path]

    output_vvp_file = os.path.join(run_path, "design.vvp")

    # Use the current_src_dir for the include path
    compile_command = ["iverilog", "-g2005-sv", "-o", output_vvp_file, "-I", current_src_dir] + all_files_for_sim

    try:
        st.write(f"Running compilation: `{' '.join(compile_command)}`")
        # Use a timeout to prevent hanging
        compile_process = subprocess.run(compile_command, capture_output=True, text=True, check=True, timeout=60)
        st.write("✅ Compilation successful.")

        sim_command = ["vvp", output_vvp_file]
        st.write(f"Running simulation: `{' '.join(sim_command)}`")
        sim_process = subprocess.run(sim_command, capture_output=True, text=True, check=True, timeout=60)

        st.write("✅ Simulation process completed.")
        st.text_area("Simulation Output", sim_process.stdout, height=150, key=f"sim_output_{state.get('update_attempt', 0)}")
        return {"simulation_passed": True, "simulation_output": sim_process.stdout}

    except subprocess.CalledProcessError as e:
        # This catches errors where the tool runs but returns a non-zero exit code
        error_message = f"ERROR during {'compilation' if 'iverilog' in ' '.join(e.cmd) else 'simulation'}:\n{e.stderr or e.stdout}"
        st.error(error_message)
        return {"simulation_passed": False, "simulation_output": error_message}
    except subprocess.TimeoutExpired as e:
        # This catches if the simulation takes too long
        error_message = f"ERROR: {'Compilation' if 'iverilog' in ' '.join(e.cmd) else 'Simulation'} timed out."
        st.error(error_message)
        return {"simulation_passed": False, "simulation_output": error_message}

def simulation_verifier_agent(state: AgentState) -> Dict[str, Any]:
    """
    Checks the simulation output. On the first run, it is lenient.
    On subsequent runs, it strictly checks for a 'PASSED' or 'SUCCESS' message.
    """
    st.write("---")
    st.write("### 🧐 Agent 6.5: Simulation Verifier")
    st.info("This agent checks the simulation output for a 'PASSED' or 'SUCCESS' message from the self-checking testbench.")

    update_attempt = state.get("update_attempt", 0)
    simulation_output = state.get("simulation_output", "")
    ascii_output = simulation_output.encode('ascii', 'ignore').decode('ascii').strip()

    # On the very first run (attempt 0), if the simulation process completed but
    # produced no output, we will pass it. This handles cases where the initial
    # testbench is not self-checking. The loop will later add self-checking if needed.
    if update_attempt == 0 and state["simulation_passed"] and not ascii_output:
        st.warning("⚠️ First simulation run produced no output. Passing to allow the flow to proceed. The testbench will be updated if a later stage fails and triggers a correction loop.")
        return {"simulation_verified": True}

    # For all subsequent runs, or if the first run produced any output,
    # we strictly enforce that the testbench must be self-checking.
    if re.search(r'Result:\s*PASSED', ascii_output, re.IGNORECASE):
        st.success("✅ Verification PASSED: 'Result: PASSED' found in simulation output.")
        return {"simulation_verified": True}
    else:
        st.error("❌ Verification FAILED: 'Result: PASSED' not found in simulation output.")
        st.write("Sanitized output that was checked:")
        st.code(ascii_output if ascii_output else "[No output produced by simulation]")
        return {"simulation_verified": False}


def setup_agent(state: AgentState) -> Dict[str, Any]:
    """
    Initializes or updates the OpenLane 2.0 configuration for the design.
    """
    st.write("---")
    st.write("### 🛠️ Agent 7: OpenLane Setup")
    st.info("This agent initializes the OpenLane 2.0 configuration for the design.")

    config_or_dict = state.get('config')
    design_name = state["design_name"]

    # If the design name has changed, we must re-initialize the config
    if config_or_dict and config_or_dict.get("DESIGN_NAME") != design_name:
        st.warning(f"Design name changed from '{config_or_dict['DESIGN_NAME']}' to '{design_name}'. Re-initializing configuration.")
        config_or_dict = None

    if config_or_dict:
        st.write("♻️ Looping back: Using existing (potentially modified) configuration.")
        if isinstance(config_or_dict, dict):
            config = Config(config_or_dict)
        else:
            config = config_or_dict

        # Clean up old OpenLane run directories to ensure a fresh start
        for item in os.listdir(state['run_path']):
            if item.startswith('runs'):
                shutil.rmtree(os.path.join(state['run_path'], item))
                st.write(f"🧹 Removed old OpenLane run directory: {item}")
    else:
        st.write("🚀 Initial run or Design Name changed: Creating new OpenLane configuration.")
        # Create a default configuration
        config = Config.interactive(
            design_name, PDK="gf180mcuC",
            CLOCK_PORT="clk", CLOCK_NET="clk", CLOCK_PERIOD=2000.0, # Start with a reasonable clock period
            PRIMARY_GDSII_STREAMOUT_TOOL="klayout",
        )
    st.write("✅ OpenLane configuration loaded.")
    st.info(f"**Design Name for this run: {config['DESIGN_NAME']}**")
    st.info(f"**Clock Period set to: {config['CLOCK_PERIOD']} ns**")
    return {"config": config}


def synthesis_agent(state: AgentState) -> Dict[str, Any]:
    """
    Converts the high-level Verilog RTL into a gate-level netlist using Yosys.
    """
    st.write("---")
    st.write("### 🔬 Agent 8: Synthesis")
    st.info("This agent converts the high-level Verilog RTL into a gate-level netlist.")

    # Use the current source directory from the state
    src_path = state['current_src_dir']

    synthesizable_files = [
        os.path.join(src_path, f) for f in os.listdir(src_path)
        if f.endswith(('.v', '.vh')) and 'tb' not in f.lower() and 'testbench' not in f.lower()
    ]

    st.write(f"Synthesizing files from: `{src_path}`")
    for f in synthesizable_files:
        st.write(f"- `{os.path.basename(f)}`")

    Synthesis = Step.factory.get("Yosys.Synthesis")
    synthesis_step = Synthesis(config=state["config"], state_in=State(), VERILOG_FILES=synthesizable_files)
    synthesis_step.start()
    report_path = os.path.join(synthesis_step.step_dir, "reports", "stat.json")
    with open(report_path) as f: metrics = json.load(f)
    st.write("#### Synthesis Metrics")
    st.table(pd.DataFrame.from_dict(metrics, orient='index', columns=["Value"]).astype(str))
    return {"synthesis_state_out": synthesis_step.state_out}


def floorplan_agent(state: AgentState) -> Dict[str, Any]:
    """
    Defines the chip's dimensions (die area) and core area.
    """
    st.write("---")
    st.write("### 🏗️ Agent 9: Floorplanning")
    st.info("This agent defines the overall chip dimensions (die area).")
    Floorplan = Step.factory.get("OpenROAD.Floorplan")
    floorplan_step = Floorplan(config=state["config"], state_in=state["synthesis_state_out"])
    floorplan_step.start()
    metrics_path = os.path.join(floorplan_step.step_dir, "or_metrics_out.json")
    with open(metrics_path) as f: metrics = json.load(f)

    st.write("#### Floorplan Metrics")
    st.table(pd.DataFrame(metrics.items(), columns=["Metric", "Value"]).astype(str))

    # Extract die dimensions from the metrics report
    die_width_um, die_height_um = 0, 0
    bbox_str = metrics.get('design__die__bbox')
    if bbox_str:
        try:
            coords = [float(x) for x in bbox_str.split()]
            if len(coords) == 4:
                llx, lly, urx, ury = coords
                die_width_um, die_height_um = urx - llx, ury - lly
        except (ValueError, IndexError):
            st.warning("Could not parse 'design__die__bbox'.")

    die_width_mm, die_height_mm = die_width_um / 1000, die_height_um / 1000

    st.write("---")
    st.write(f"#### Die Area Analysis")
    st.write(f"Your design is **{die_width_mm:.3f} mm** x **{die_height_mm:.3f} mm**.")
    st.write(f"Maximum allowed size is **{state['max_die_width_mm']:.3f} mm** x **{state['max_die_height_mm']:.3f} mm**.")

    return {
        "floorplan_state_out": floorplan_step.state_out,
        "die_width_mm": die_width_mm, "die_height_mm": die_height_mm
    }

# --- Placeholder agents for standard PnR steps ---
# These agents simply run their corresponding OpenLane step.

def tap_endcap_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 💠 Agent 10: Tap/Endcap Insertion")
    st.info("This agent inserts special cells to prevent latch-up issues.")
    TapEndcap = Step.factory.get("OpenROAD.TapEndcapInsertion")
    tap_step = TapEndcap(config=state["config"], state_in=state["floorplan_state_out"])
    tap_step.start()
    return {"tap_endcap_state_out": tap_step.state_out}

def io_placement_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 📍 Agent 11: I/O Pin Placement")
    st.info("This agent performs the detailed placement of the I/O pads.")
    IOPlacement = Step.factory.get("OpenROAD.IOPlacement")
    ioplace_step = IOPlacement(config=state["config"], state_in=state["tap_endcap_state_out"])
    ioplace_step.start()
    return {"io_placement_state_out": ioplace_step.state_out}

def generate_pdn_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ⚡ Agent 12: Power Distribution Network (PDN)")
    st.info("This agent generates the grid of power and ground stripes.")
    GeneratePDN = Step.factory.get("OpenROAD.GeneratePDN")
    pdn_step = GeneratePDN(config=state["config"], state_in=state["io_placement_state_out"], FP_PDN_VWIDTH=2, FP_PDN_HWIDTH=2, FP_PDN_VPITCH=30, FP_PDN_HPITCH=30)
    pdn_step.start()
    return {"pdn_state_out": pdn_step.state_out}

def global_placement_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🌍 Agent 13: Global Placement")
    st.info("This agent determines the approximate locations for all standard cells.")
    GlobalPlacement = Step.factory.get("OpenROAD.GlobalPlacement")
    gpl_step = GlobalPlacement(config=state["config"], state_in=state["pdn_state_out"])
    gpl_step.start()
    return {"global_placement_state_out": gpl_step.state_out}

def detailed_placement_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 📐 Agent 14: Detailed Placement")
    st.info("This agent refines placement, legalizing all cell positions.")
    DetailedPlacement = Step.factory.get("OpenROAD.DetailedPlacement")
    dpl_step = DetailedPlacement(config=state["config"], state_in=state["global_placement_state_out"])
    dpl_step.start()
    return {"detailed_placement_state_out": dpl_step.state_out}

def cts_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🌳 Agent 15: Clock Tree Synthesis (CTS)")
    st.info("This agent builds the clock tree to distribute the clock signal.")
    CTS = Step.factory.get("OpenROAD.CTS")
    cts_step = CTS(config=state["config"], state_in=state["detailed_placement_state_out"])
    cts_step.start()
    return {"cts_state_out": cts_step.state_out}

def global_routing_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🗺️ Agent 16: Global Routing")
    st.info("This agent plans the paths for the interconnect wires.")
    GlobalRouting = Step.factory.get("OpenROAD.GlobalRouting")
    grt_step = GlobalRouting(config=state["config"], state_in=state["cts_state_out"])
    grt_step.start()
    metrics_path = os.path.join(grt_step.step_dir, "or_metrics_out.json")
    with open(metrics_path) as f: metrics = json.load(f)
    st.write("#### Global Routing Metrics")
    st.table(pd.DataFrame(metrics.items(), columns=["Metric", "Value"]).astype(str))
    return {"global_routing_state_out": grt_step.state_out}

def detailed_routing_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ✍️ Agent 17: Detailed Routing")
    st.info("This agent performs the final, exact routing of all wires.")
    DetailedRouting = Step.factory.get("OpenROAD.DetailedRouting")
    drt_step = DetailedRouting(config=state["config"], state_in=state["global_routing_state_out"])
    drt_step.start()
    return {"detailed_routing_state_out": drt_step.state_out}

def fill_insertion_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🧱 Agent 18: Fill Insertion")
    st.info("This agent adds 'filler' cells to ensure metal density uniformity.")
    FillInsertion = Step.factory.get("OpenROAD.FillInsertion")
    fill_step = FillInsertion(config=state["config"], state_in=state["detailed_routing_state_out"])
    fill_step.start()
    return {"fill_insertion_state_out": fill_step.state_out}

def rcx_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🔌 Agent 19: Parasitics Extraction (RCX)")
    st.info("This agent extracts the parasitic resistance (R) and capacitance (C) of wires.")
    RCX = Step.factory.get("OpenROAD.RCX")
    rcx_step = RCX(config=state["config"], state_in=state["fill_insertion_state_out"])
    rcx_step.start()
    return {"rcx_state_out": rcx_step.state_out}

def sta_agent(state: AgentState) -> Dict[str, Any]:
    """
    Performs Static Timing Analysis (STA) to check for timing violations.
    """
    st.write("---")
    st.write("### ⏱️ Agent 20: Static Timing Analysis (STA)")
    st.info("This analysis step verifies that the chip meets its timing constraints.")
    STAPostPNR = Step.factory.get("OpenROAD.STAPostPNR")
    sta_step = STAPostPNR(config=state["config"], state_in=state["rcx_state_out"])
    sta_step.start()
    st.write("#### STA Timing Violation Summary")
    sta_results = []
    value_re = re.compile(r":\s*(-?[\d\.]+)")
    reports_to_find = ["tns.max.rpt", "tns.min.rpt", "wns.max.rpt", "wns.min.rpt"]
    all_tns, all_wns = [], []

    # Walk through the STA step directory to find all timing reports
    for root, _, files in os.walk(sta_step.step_dir):
        for file in files:
            if file in reports_to_find:
                corner = os.path.basename(root) # e.g., 'ss_100C_1v60'
                metric_name = file.replace(".rpt", "").replace(".", " ").title()
                with open(os.path.join(root, file)) as f:
                    content = f.read()
                    match = value_re.search(content)
                    if match:
                        value = float(match.group(1))
                        sta_results.append([corner, metric_name, value])
                        if "Tns Max" in metric_name: all_tns.append(value)
                        if "Wns Max" in metric_name: all_wns.append(value)

    # Find the worst (most negative) slack values across all corners
    worst_tns = min(all_tns) if all_tns else 0
    worst_wns = min(all_wns) if all_wns else 0
    st.info(f"**Worst Total Negative Slack (TNS): {worst_tns:.2f} ps** | **Worst Negative Slack (WNS): {worst_wns:.2f} ps**")

    if sta_results:
        df_sta = pd.DataFrame(sta_results, columns=["Corner", "Metric", "Value (ps)"])
        # Pivot the table for better readability
        pivoted_df = df_sta.pivot(index='Metric', columns='Corner', values='Value (ps)').fillna(0)
        # Color-code the results for quick analysis
        styled_df = pivoted_df.style.applymap(lambda val: f'color: {"red" if val < 0 else "green"}').format("{:.2f}")
        st.dataframe(styled_df, use_container_width=True)
    else:
        st.warning("Could not parse key STA report files (TNS, WNS).")

    return {
        "sta_state_out": sta_step.state_out,
        "worst_tns": worst_tns / 1000.0, # Convert to ns for correction logic
        "worst_wns": worst_wns / 1000.0, # Convert to ns
    }

def sta_correction_agent(state: AgentState) -> Dict[str, Any]:
    """
    If timing violations are found, this agent attempts to fix them by
    increasing the clock period (i.e., slowing down the clock).
    """
    st.write("---")
    st.write("### 🤖 Agent 21: STA Corrector")
    st.info("If timing violations are found, this agent attempts to fix them by increasing the clock period.")
    st.error("❌ Timing violations detected! Attempting to fix by adjusting clock period.")

    config_dict = dict(state["config"])
    current_period = float(config_dict["CLOCK_PERIOD"])
    worst_tns_ns = state["worst_tns"]
    worst_wns_ns = state["worst_wns"]
    feedback_msg, new_period = "", current_period

    # Apply increasingly aggressive corrections based on the severity of the violation
    if abs(worst_tns_ns) > 500:
        new_period, feedback_msg = current_period * 10, f"CRITICAL TNS ({worst_tns_ns:.2f} ns). Drastically increasing clock period 10x."
    elif abs(worst_tns_ns) > 50:
        new_period, feedback_msg = current_period * 2, f"HIGH TNS ({worst_tns_ns:.2f} ns). Increasing clock period 2x."
    elif worst_tns_ns < 0:
        new_period, feedback_msg = current_period * 1.5, f"Small TNS ({worst_tns_ns:.2f} ns). Increasing clock period 1.5x."
    elif worst_wns_ns < 0:
        # TNS might be ok, but WNS (the single worst path) is failing
        new_period, feedback_msg = current_period * 1.15, f"TNS OK, but WNS violation ({worst_wns_ns:.2f} ns). Slightly increasing clock period by 15%."

    st.warning(feedback_msg)
    st.write(f"Old Clock Period: {current_period:.2f} ns")
    st.success(f"**New Clock Period: {new_period:.2f} ns**")

    config_dict["CLOCK_PERIOD"] = new_period
    feedback = state.get("feedback_log", []) + [f"STA Correction: {feedback_msg} Changed clock from {current_period}ns to {new_period}ns."]
    return {"config": Config(config_dict), "feedback_log": feedback}


def stream_out_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 💾 Agent 22: GDSII Stream Out")
    st.info("This agent generates the final GDSII file for manufacturing.")
    StreamOut = Step.factory.get("KLayout.StreamOut")
    gds_step = StreamOut(config=state["config"], state_in=state["sta_state_out"])
    gds_step.start()
    return {"stream_out_state_out": gds_step.state_out}

def drc_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ✅ Agent 23: Design Rule Check (DRC)")
    st.info("This agent checks if the final layout adheres to the foundry's geometric and electrical rules.")
    DRC = Step.factory.get("Magic.DRC")
    drc_step = DRC(config=state["config"], state_in=state["stream_out_state_out"])
    drc_step.start()
    report_path = os.path.join(drc_step.step_dir, "reports", "drc_violations.magic.rpt")
    try:
        with open(report_path) as f:
            content = f.read()
            count_match = re.search(r"\[INFO\] COUNT: (\d+)", content)
            if count_match:
                count = int(count_match.group(1))
                if count == 0: st.success("✅ No DRC violations found.")
                else: st.error(f"❌ Found {count} DRC violations.")
                st.text_area("DRC Report", content, height=200, key=f"drc_report_{state.get('update_attempt', 0)}")
    except FileNotFoundError: st.warning("DRC report file not found.")
    return {"drc_state_out": drc_step.state_out}

def spice_extraction_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ⚡ Agent 24: SPICE Extraction")
    st.info("This agent extracts a detailed SPICE netlist from the final layout.")
    SpiceExtraction = Step.factory.get("Magic.SpiceExtraction")
    spx_step = SpiceExtraction(config=state["config"], state_in=state["drc_state_out"])
    spx_step.start()
    return {"spice_extraction_state_out": spx_step.state_out}

def lvs_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ↔️ Agent 25: Layout vs. Schematic (LVS)")
    st.info("Compares the extracted SPICE netlist (layout) against the original Verilog netlist.")
    LVS = Step.factory.get("Netgen.LVS")
    lvs_step = LVS(config=state["config"], state_in=state["spice_extraction_state_out"])
    lvs_step.start()

    return {
        "lvs_state_out": lvs_step.state_out,
        "lvs_step_dir": lvs_step.step_dir
    }

def lvs_verifier_agent(state: AgentState) -> Dict[str, Any]:
    """
    Parses the LVS report to determine if the layout and schematic match.
    """
    st.write("---")
    st.write("### 🧐 Agent 25.5: LVS Verifier")
    st.info("This agent parses the LVS report to verify that the layout and schematic match.")

    lvs_step_dir = state.get("lvs_step_dir")
    if not lvs_step_dir:
        st.error("LVS step directory not found in state. Cannot verify LVS.")
        return {"lvs_passed": False}

    report_path = os.path.join(lvs_step_dir, "reports", "lvs.netgen.rpt")
    lvs_passed = False

    try:
        with open(report_path) as f:
            content = f.read()
            st.text_area("LVS Report", content, height=200, key=f"lvs_report_{state.get('update_attempt', 0)}")
            # The key phrase for a successful LVS run in Netgen
            if "Circuits match uniquely" in content:
                st.success("✅ LVS PASSED: Circuits match uniquely.")
                lvs_passed = True
            else:
                st.error("❌ LVS FAILED: Circuits do not match.")
                lvs_passed = False
    except FileNotFoundError:
        st.error(f"LVS report file not found at: {report_path}")
        lvs_passed = False

    return {"lvs_passed": lvs_passed}


def pin_counter_agent(state: AgentState) -> Dict[str, Any]:
    """
    Inspects the LVS report to count the number of non-power/ground I/O pins.
    """
    st.write("---")
    st.write("### 🔢 Agent 26: Pin Counter")
    st.info("This agent inspects the LVS report to count the number of I/O pins.")

    lvs_step_dir = state.get("lvs_step_dir")
    design_name = state["design_name"]
    if not lvs_step_dir:
        st.error("LVS step directory not found in state. Cannot count pins.")
        return {"pin_count": -1}

    json_report_path = os.path.join(lvs_step_dir, "reports", "lvs.netgen.json")
    pin_count = 0

    if not os.path.exists(json_report_path):
        st.error(f"LVS JSON report not found at: {json_report_path}. Cannot count pins.")
        return {"pin_count": -1}

    try:
        with open(json_report_path, 'r') as f:
            lvs_data = json.load(f)

            top_module_data = None
            # The JSON report is a list of dictionaries, one for each module
            if isinstance(lvs_data, list):
                for item in lvs_data:
                    if isinstance(item, dict) and 'name' in item:
                        # Find the dictionary corresponding to our top-level module
                        if item['name'][0] == design_name:
                            top_module_data = item
                            break

            if top_module_data:
                pin_list = top_module_data["pins"][0]
                # Define a set of common power/ground pin names to exclude
                power_ground_pins = {'vccd1', 'vssd1', 'vccd', 'vssd', 'gnd', 'vdd', 'vpw', 'vnw'}

                # Count pins that are not in the power/ground set
                core_pins = [p for p in pin_list if p.lower() not in power_ground_pins]
                pin_count = len(core_pins)
                st.success(f"✅ Successfully parsed LVS report for '{design_name}'. Found {pin_count} I/O pins.")
            else:
                st.error(f"Could not find pin data for top-level module '{design_name}' in the LVS JSON report.")
                pin_count = -1

    except (json.JSONDecodeError, KeyError, IndexError) as e:
        st.error(f"Error reading or parsing LVS JSON report: {e}")
        pin_count = -1

    st.write(f"Pin Count: **{pin_count}** / Max Allowed: **{state['max_pins']}**")
    return {"pin_count": pin_count}

def pin_reduction_corrector_agent(state: AgentState) -> Dict[str, Any]:
    """
    A specialized LLM agent that creates a new top-level module to integrate a
    serial interface with the original design, reducing pin count.
    """
    st.write("---")
    st.write("### 🧠 Agent 27: Pin Reduction Corrector (LLM)")
    st.info("This agent uses an LLM to build a serial interface and a new top-level module to reduce I/O pins.")

    feedback = "\n".join(state['feedback_log'])
    st.write("#### Feedback for Correction (Pin Count):")
    st.code(feedback, language='text')

    original_top_module = state['top_level_module']

    prompt = f"""
    You are an expert Verilog designer specializing in I/O optimization. Your goal is to reduce the pin count of a design by creating a new top-level module that integrates a serial communication block.
    The design currently has **{state['pin_count']}** pins, but the maximum allowed is **{state['max_pins']}**.

    **REQUIRED STRATEGY: MODULAR SERIAL INTEGRATION**
    You MUST NOT modify the original Verilog modules. Instead, you will create two new modules:
    1. A generic, reusable serial communication module (e.g., an SPI slave or a simple UART).
    2. A new top-level module that instantiates BOTH the serial module AND the original design, connecting them together.

    **INSTRUCTIONS:**
    1.  **Preserve Original Code:** Keep all the original Verilog modules provided below completely unchanged.
    2.  **Create a Serial Interface Module:**
        -   Design a self-contained module for serial communication. Let's call it `spi_interface`.
        -   This module will have serial pins (e.g., `sclk`, `cs`, `mosi`, `miso`) on one side and parallel data buses on the other side to connect to the main design.
    3.  **Create a New Top-Level Module:**
        -   Create a new module named `{original_top_module}_with_serial`. This will be the new top-level for the entire system.
        -   The port list for this new top-level module MUST have fewer than {state['max_pins']} pins. It will expose the serial interface pins.
        -   Inside this new top-level, you MUST instantiate two sub-modules:
            a. The `spi_interface` module you just created.
            b. The original top-level design: `{original_top_module}`.
        -   Connect the parallel data buses from the serial module to the corresponding inputs/outputs of the original design.
    4.  **Final Output:** Your output MUST be a single, monolithic block of synthesizable Verilog-2001 code. It must contain:
        - The **UNCHANGED original modules**.
        - The **NEW serial interface module**.
        - The **NEW top-level module** that connects everything.
    5.  Enclose the final complete Verilog code in a single markdown block. Do NOT include a testbench.

    **Original Verilog Code (Do NOT modify this part):**
    ---
    """
    code_to_correct = state.get("decomposed_files")
    for filename, code in code_to_correct.items():
        prompt += f"--- {filename} ---\n{code}\n"
    prompt += "---"

    st.write("🤖 Asking Gemini to create a serial interface and new top-level to reduce pin count...")
    response = llm.invoke(prompt)
    st.write("#### Gemini's Raw Response:")
    st.markdown(response.content)

    modified_code_match = re.search(r"```(?:verilog)?\s*\n(.*?)```", response.content, re.DOTALL)
    if not modified_code_match:
        st.error("LLM response parsing failed. Could not find a valid Verilog code block. Falling back.")
        return {"modified_verilog_code": "\n".join(code_to_correct.values())}

    modified_verilog_code = modified_code_match.group(1).strip()
    st.success("✅ Successfully extracted pin-optimized Verilog code from LLM response.")
    return {"modified_verilog_code": modified_verilog_code}


def pin_reduction_testbench_agent(state: AgentState) -> Dict[str, Any]:
    """
    A specialized LLM agent that rewrites the testbench to work with the new,
    pin-reduced serial wrapper of the design.
    """
    st.write("---")
    st.write("### 🧠 Agent 28: Pin Reduction Testbench Corrector (LLM)")
    st.info("This agent rewrites the testbench to work with the new serial wrapper interface.")

    if not llm or not state.get("original_testbench_code"):
        st.warning("No LLM or original testbench found. Skipping testbench correction.")
        return {}

    tb_to_correct = state.get("modified_testbench_code") or state["original_testbench_code"]

    # The new top-level module is the wrapper
    new_top_level = state['top_level_module']
    original_top_module = state.get("top_level_module").replace("_with_serial", "")


    prompt = f"""
    You are an expert Verilog testbench writer. The design under test has been integrated into a new top-level module with a serial interface to reduce its pin count. You MUST update the testbench to communicate using this new serial protocol.

    **New Design Modules (including the serial interface and new top-level):**
    ---
    """
    for filename, code in state['decomposed_files'].items():
        prompt += f"--- {filename} ---\n{code}\n"

    prompt += f"""
    ---
    **Original Testbench Code (for the parallel version):**
    ---
    {tb_to_correct}
    ---

    **CRITICAL INSTRUCTIONS FOR THE NEW TESTBENCH:**
    1.  **Instantiate the New Top-Level:** The testbench must now instantiate the new top-level module, which is `{new_top_level}` (e.g., `{original_top_module}_with_serial`). This module contains both the serial interface and the original design.
    2.  **Implement Serial Communication:**
        -   You must drive the serial interface pins (`sclk`, `cs`, `mosi`, etc.) correctly.
        -   To send data to the DUT, create a task or loop that drives the `mosi` pin one bit at a time on each clock edge while `cs` is active.
        -   After sending all bits, allow time for the internal core logic to compute.
        -   To receive data, create a similar loop to capture the `miso` pin's value on each clock edge.
    3.  **Maintain Core Test Logic:** The fundamental test (the data you send and the expected result) remains the same as the original testbench. You are only changing the *method* of communication from parallel to serial at the boundary of the new top-level module.
    4.  **Verify Correctness:** After receiving the full serial output, reconstruct the parallel data and compare it with the expected result.
    5.  **Self-Checking:** The testbench MUST use `$display` to print **EXACTLY** `"Result: PASSED"` or `"Result: FAILED"` and then call `$finish`.

    Provide the updated, complete, and robust self-checking testbench for the **new serially-integrated design** in a single Verilog code block.
    """

    st.write("🤖 Asking Gemini to update the testbench for the new serial interface...")
    response = llm.invoke(prompt)
    st.write("#### Gemini's Response:")
    st.markdown(response.content)

    modified_code = re.search(r"```(?:verilog)?\s*\n(.*?)```", response.content, re.DOTALL)
    if not modified_code:
        st.error("Could not extract corrected testbench code from LLM response.")
        return {"modified_testbench_code": tb_to_correct}

    corrected_tb_code = modified_code.group(1).strip()

    st.write("#### Testbench Changes (Serial vs. Parallel):")
    diff = difflib.unified_diff(
        tb_to_correct.splitlines(keepends=True),
        corrected_tb_code.splitlines(keepends=True),
        fromfile='original_parallel_tb', tofile='modified_serial_tb',
    )
    st.code(''.join(diff), language='diff')

    return {"modified_testbench_code": corrected_tb_code}

def pin_reduction_decomposer_agent(state: AgentState) -> Dict[str, Any]:
    """
    Decomposes the pin-reduced Verilog code.
    This is a wrapper around the main decomposer agent.
    """
    st.write("---")
    st.write("### 🧩 Agent 29: Pin Reduction Code Decomposer")
    st.info("Splitting the pin-reduced Verilog back into separate files.")
    return code_decomposer_agent(state)

def pin_reduction_saver_agent(state: AgentState) -> Dict[str, Any]:
    """
    Saves the pin-reduced Verilog and new testbench.
    This is a wrapper around the main file saver agent.
    """
    st.write("---")
    st.write("### 💾 Agent 30: Pin Reduction File Saver")
    st.info("Saving the pin-reduced Verilog and new testbench to a new versioned directory.")
    return file_saver_agent(state)


def render_step_image(state: AgentState, state_key_in: str, caption: str):
    """
    A utility agent that generates a PNG image of the chip layout at various stages.
    """
    st.write(f"#### 🖼️ Visualizing: {caption}")
    Render = Step.factory.get("KLayout.Render")
    # Use a try-except block to prevent rendering failures from halting the flow
    try:
        render_step = Render(config=state["config"], state_in=state[state_key_in])
        render_step.start()
        image_path = os.path.join(render_step.step_dir, "out.png")
        if os.path.exists(image_path):
            st.image(image_path, caption=caption, width=400)
        else:
            st.warning(f"Could not render image for {caption}")
    except Exception as e:
        st.warning(f"Image rendering failed for {caption}: {e}")
    return {}

# --- Conditional Logic for Graph Branching ---

def check_simulation_exit_code(state: AgentState) -> str:
    """
    Checks if the simulation process itself ran without crashing.
    """
    if state["simulation_passed"]:
        return "verify_simulation_output" # Proceed to check the content of the output
    else:
        st.error("❌ Simulation process failed to execute.")
        feedback = state.get("feedback_log", []) + [f"Icarus simulation failed to compile or run. Fix the Verilog code:\n{state['simulation_output']}"]
        state['feedback_log'] = feedback
        if state.get("update_attempt", 0) > 5:
            st.error("Simulation failed after multiple correction attempts. Halting.")
            return "end"
        st.warning("Looping back to Verilog Corrector for another attempt.")
        return "fix_verilog"

def check_simulation_results(state: AgentState) -> str:
    """
    Checks if the testbench reported a 'PASSED' status.
    """
    if state["simulation_verified"]:
        return "continue_to_synthesis" # Success, move to the PnR flow
    else:
        st.error("❌ Testbench reported failure.")
        feedback = state.get("feedback_log", []) + [f"Testbench did not report PASSED or SUCCESS. The design may have functional bugs. Please fix the Verilog code based on the simulation output:\n{state['simulation_output']}"]
        state['feedback_log'] = feedback
        if state.get("update_attempt", 0) > 5:
            st.error("Simulation verification failed after multiple correction attempts. Halting.")
            return "end"
        st.warning("Looping back to Verilog Corrector for another attempt.")
        return "fix_verilog"

def check_floorplan(state: AgentState) -> str:
    """
    Checks if the die size from floorplanning is within the user-defined constraints.
    """
    width_ok = state['die_width_mm'] <= state['max_die_width_mm']
    height_ok = state['die_height_mm'] <= state['max_die_height_mm']

    if width_ok and height_ok:
        st.success("✅ Die size is within limits. Proceeding with Place and Route.")
        return "continue_to_pnr"
    else:
        st.error("❌ Die size exceeds maximum limits.")
        feedback = state.get("feedback_log", []) + [f"Floorplan failed. Die size {state['die_width_mm']:.3f}x{state['die_height_mm']:.3f}mm exceeds limit. Simplify the design to reduce area."]
        state['feedback_log'] = feedback
        if state.get("update_attempt", 0) > 10:
            st.error("Die size too large after multiple correction attempts. Halting.")
            return "end"
        return "fix_verilog" # Go back to the Verilog corrector to reduce area

def check_sta_violations(state: AgentState) -> str:
    """
    Checks if the design has any timing violations (negative slack).
    """
    worst_tns = state.get("worst_tns", 0.0)
    worst_wns = state.get("worst_wns", 0.0)
    if worst_tns < 0 or worst_wns < 0:
        st.error(f"❌ STA VIOLATION (TNS={worst_tns:.2f} ns, WNS={worst_wns:.2f} ns).")
        if state.get("update_attempt", 0) > 15:
                        st.error("Could not meet timing after multiple attempts. Halting.")
                        return "end"
        return "fix_sta" # Go to the STA corrector agent
    else:
        st.success(f"✅ Timing constraints met. Proceeding to final signoff.")
        return "continue_to_signoff"

def check_lvs_results(state: AgentState) -> str:
    """
    Checks if the LVS verifier agent passed.
    """
    if state["lvs_passed"]:
        st.success("✅ LVS passed. Proceeding to pin count check.")
        return "continue_to_pin_count"
    else:
        st.error("❌ LVS check failed. The layout does not match the schematic.")
        feedback = state.get("feedback_log", []) + ["LVS check failed. This is a critical error indicating a problem with the physical design tools or the Verilog code that is causing a mismatch. Attempting to fix the Verilog code."]
        state['feedback_log'] = feedback
        if state.get("update_attempt", 0) > 18:
                        st.error("LVS failed after multiple correction attempts. Halting.")
                        return "end"
        st.warning("Looping back to Verilog Corrector to attempt a fix.")
        return "fix_verilog"

def check_pin_count(state: AgentState) -> str:
    """
    Checks if the final pin count is within the user-defined constraints.
    """
    if state["pin_count"] < 0: # Error case from the pin counter agent
        st.error("Halting due to pin counting error.")
        return "end"
    if state["pin_count"] <= state["max_pins"]:
        st.success("✅ Pin count is within limits. Flow complete!")
        return "end" # Final success
    else:
        st.error(f"❌ Pin count ({state['pin_count']}) exceeds maximum of {state['max_pins']}.")
        feedback = state.get("feedback_log", []) + [f"LVS passed, but pin count {state['pin_count']} exceeds limit of {state['max_pins']}. You must reduce the number of I/O ports using serialization or other techniques."]
        state['feedback_log'] = feedback
        if state.get("update_attempt", 0) > 20:
                        st.error("Could not meet pin count constraint after multiple attempts. Halting.")
                        return "end"
        st.warning("Looping back to Verilog Pin Reduction Corrector.")
        return "fix_pins" # Go to the specialized pin reduction loop

# --- Build the StateGraph ---
workflow = StateGraph(AgentState)

# Add Nodes for all agents
node_definitions = {
    "file_processing": file_processing_agent,
    "verilog_corrector": verilog_corrector_agent,
    "code_decomposer": code_decomposer_agent,
    "design_name_updater": design_name_updater_agent,
    "testbench_corrector": testbench_corrector_agent,
    "file_saver": file_saver_agent,
    "icarus_simulation": icarus_simulation_agent,
    "simulation_verifier": simulation_verifier_agent,
    "setup": setup_agent,
    "synthesis": synthesis_agent,
    "floorplan": floorplan_agent,
    "tap_endcap": tap_endcap_agent,
    "io_placement": io_placement_agent,
    "generate_pdn": generate_pdn_agent,
    "global_placement": global_placement_agent,
    "detailed_placement": detailed_placement_agent,
    "cts": cts_agent,
    "global_routing": global_routing_agent,
    "detailed_routing": detailed_routing_agent,
    "fill_insertion": fill_insertion_agent,
    "rcx": rcx_agent,
    "sta": sta_agent,
    "sta_correction": sta_correction_agent,
    "stream_out": stream_out_agent,
    "drc": drc_agent,
    "spice_extraction": spice_extraction_agent,
    "lvs": lvs_agent,
    "lvs_verifier": lvs_verifier_agent,
    "pin_counter": pin_counter_agent,
    "pin_reduction_corrector": pin_reduction_corrector_agent,
    "pin_reduction_decomposer": pin_reduction_decomposer_agent,
    # FIX: Add a uniquely named node that calls the same function to resolve ambiguity
    "pin_reduction_design_name_updater": design_name_updater_agent,
    "pin_reduction_testbench": pin_reduction_testbench_agent,
    "pin_reduction_saver": pin_reduction_saver_agent,
    "render_floorplan": lambda s: render_step_image(s, "floorplan_state_out", "Floorplan Layout"),
    "render_tap_endcap": lambda s: render_step_image(s, "tap_endcap_state_out", "Tap/Endcap Insertion"),
    "render_io": lambda s: render_step_image(s, "io_placement_state_out", "I/O Placement"),
    "render_pdn": lambda s: render_step_image(s, "pdn_state_out", "Power Distribution Network"),
    "render_global_placement": lambda s: render_step_image(s, "global_placement_state_out", "Global Placement"),
    "render_detailed_placement": lambda s: render_step_image(s, "detailed_placement_state_out", "Detailed Placement"),
    "render_cts": lambda s: render_step_image(s, "cts_state_out", "Clock Tree Synthesis"),
    "render_routing": lambda s: render_step_image(s, "detailed_routing_state_out", "Detailed Routing"),
    "render_fill": lambda s: render_step_image(s, "fill_insertion_state_out", "Fill Insertion"),
    "render_gds": lambda s: render_step_image(s, "stream_out_state_out", "Final GDSII Layout")
}
for name, func in node_definitions.items():
    workflow.add_node(name, func)

# --- Define Edges and Graph Structure ---

# 1. Initial File Processing and Simulation
workflow.add_edge(START, "file_processing")
workflow.add_edge("file_processing", "icarus_simulation")

# 2. Simulation Check and Correction Loop
workflow.add_conditional_edges(
    "icarus_simulation",
    check_simulation_exit_code,
    {"verify_simulation_output": "simulation_verifier", "fix_verilog": "verilog_corrector", "end": END},
)
workflow.add_conditional_edges(
    "simulation_verifier",
    check_simulation_results,
    {"continue_to_synthesis": "setup", "fix_verilog": "verilog_corrector", "end": END},
)

# Define the standard Verilog correction flow
workflow.add_edge("verilog_corrector", "code_decomposer")
workflow.add_edge("code_decomposer", "design_name_updater")
workflow.add_edge("design_name_updater", "testbench_corrector")
workflow.add_edge("testbench_corrector", "file_saver")
workflow.add_edge("file_saver", "icarus_simulation") # Loop back to re-simulate

# 3. Main PnR Flow
workflow.add_edge("setup", "synthesis")
workflow.add_edge("synthesis", "floorplan")
workflow.add_edge("floorplan", "render_floorplan")

# 4. Floorplan (Area) Check and Correction Loop
workflow.add_conditional_edges("render_floorplan", check_floorplan,
    {"continue_to_pnr": "tap_endcap", "fix_verilog": "verilog_corrector", "end": END})

# Chain together the PnR and rendering steps for a linear flow
pnr_chain = ["tap_endcap", "render_tap_endcap", "io_placement", "render_io", "generate_pdn", "render_pdn",
             "global_placement", "render_global_placement", "detailed_placement", "render_detailed_placement",
             "cts", "render_cts", "global_routing", "detailed_routing", "render_routing"]
for i in range(len(pnr_chain) - 1):
    workflow.add_edge(pnr_chain[i], pnr_chain[i+1])

workflow.add_edge("render_routing", "fill_insertion")
workflow.add_edge("fill_insertion", "render_fill")
workflow.add_edge("render_fill", "rcx")
workflow.add_edge("rcx", "sta")

# 5. STA (Timing) Check and Correction Loop
workflow.add_conditional_edges("sta", check_sta_violations,
    {"continue_to_signoff": "stream_out", "fix_sta": "sta_correction", "end": END})
workflow.add_edge("sta_correction", "setup") # Loop back to re-run PnR with new clock period

# 6. Final Signoff Flow
signoff_chain = ["stream_out", "render_gds", "drc", "spice_extraction", "lvs"]
for i in range(len(signoff_chain) - 1):
    workflow.add_edge(signoff_chain[i], signoff_chain[i+1])

# 7. LVS Check and Correction Loop
workflow.add_edge("lvs", "lvs_verifier")
workflow.add_conditional_edges("lvs_verifier", check_lvs_results,
    {"continue_to_pin_count": "pin_counter", "fix_verilog": "verilog_corrector", "end": END})

# 8. Pin Count Check and Correction Loop
workflow.add_conditional_edges("pin_counter", check_pin_count,
    {"fix_pins": "pin_reduction_corrector", "end": END})

# Define the pin reduction correction flow
workflow.add_edge("pin_reduction_corrector", "pin_reduction_decomposer")
# FIX: Use the new, uniquely named node to create a deterministic path
workflow.add_edge("pin_reduction_decomposer", "pin_reduction_design_name_updater")
workflow.add_edge("pin_reduction_design_name_updater", "pin_reduction_testbench")
workflow.add_edge("pin_reduction_testbench", "pin_reduction_saver")
workflow.add_edge("pin_reduction_saver", "icarus_simulation") # Loop all the way back to re-verify

# Compile the graph
app = workflow.compile()

# --- Streamlit UI ---
st.set_page_config(layout="wide")
st.title("🤖 LLM for Chip Design Automation")
st.write("This application uses a multi-agent workflow to automate the digital chip design flow, from RTL to GDSII. It includes intelligent feedback loops to correct functional, area, timing, and I/O pin count violations.")

st.sidebar.header("1. Upload Your Files")
uploaded_files = st.sidebar.file_uploader(
    "Upload Verilog design (.v) and a single testbench (tb.v) file", accept_multiple_files=True
)

if uploaded_files:
    verilog_file_names = [f.name for f in uploaded_files if f.name.endswith((".v", ".vh")) and "tb" not in f.name.lower()]
    if not verilog_file_names:
        st.sidebar.warning("Please upload at least one Verilog design file (not a testbench).")
    else:
        top_level_module_options = [Path(name).stem for name in verilog_file_names]
        top_level_module = st.sidebar.selectbox("Select the top-level module", options=top_level_module_options)

        st.sidebar.header("2. Set Constraints")
        max_w = st.sidebar.number_input("Max Die Width (mm)", min_value=0.01, value=0.8, step=0.01, format="%.3f")
        max_h = st.sidebar.number_input("Max Die Height (mm)", min_value=0.01, value=0.8, step=0.01, format="%.3f")
        max_p = st.sidebar.number_input("Max I/O Pins", min_value=4, value=30, step=1)

        if st.sidebar.button("🚀 Run Agentic Flow"):
            if not llm:
                st.error("Cannot run flow: Gemini LLM is not initialized.")
            else:
                original_cwd = os.getcwd()
                try:
                    with st.spinner("🚀 Agents at work... This will take several minutes."):
                        initial_state = {
                            "uploaded_files": uploaded_files,
                            "top_level_module": top_level_module,
                            "max_die_width_mm": max_w,
                            "max_die_height_mm": max_h,
                            "max_pins": max_p,
                        }
                        # Invoke the graph with a high recursion limit to allow for many loops
                        app.invoke(initial_state, {"recursion_limit": 200})
                    st.success("✅ Agentic flow completed!")
                except Exception as e:
                    st.error(f"An error occurred during the flow: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                finally:
                    # Restore the original working directory
                    os.chdir(original_cwd)
                    st.write(f"✅ Restored working directory to: `{os.getcwd()}`")

# --- Detailed Workflow Graph Visualization ---
st.write("### Agentic Workflow Graph")
st.graphviz_chart("""
digraph G {
    graph [fontname="sans-serif", label="Digital Design Flow with Intelligent Correction Loops", labelloc=t, fontsize=20, rankdir=TB, splines=ortho, nodesep=0.4, ranksep=0.8];
    node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10, width=2.2, height=0.5];
    edge [fontname="sans-serif", fontsize=8];

    subgraph cluster_prep {
        label="1. Pre-Processing & Verification"; style="rounded,filled"; color="#e3f2fd"; node[fillcolor="#bbdefb"];
        file_processing [label="1. File Processing"];
        icarus_simulation [label="6. Icarus Simulation", shape=diamond, style="rounded,filled", fillcolor="#fff9c4"];
        simulation_verifier [label="6.5 Simulation Verifier", shape=diamond, style="rounded,filled", fillcolor="#fff9c4"];
    }

    subgraph cluster_correction_verilog {
        label="A. Area/Sim/LVS Correction Loop"; style="rounded,filled"; color="#ffebee"; node[fillcolor="#ffcdd2"];
        verilog_corrector [label="2. Verilog Corrector"];
        code_decomposer [label="3. Code Decomposer"];
        design_name_updater [label="3.5. Design Name Updater"];
        testbench_corrector [label="4. Testbench Corrector"];
        file_saver [label="5. File Saver"];
    }

    subgraph cluster_pnr {
        label="2. Physical Design (PnR) & Timing"; style="rounded,filled"; color="#e8f5e9"; node[fillcolor="#c8e6c9"];
        setup [label="7. OpenLane Setup"];
        synthesis [label="8. Synthesis"];
        floorplan [label="9. Floorplan", shape=diamond, style="rounded,filled", fillcolor="#fff9c4"];
        pnr_group [label="PnR & Vis Steps (10-19)"];
        sta [label="20. STA", shape=diamond, style="rounded,filled", fillcolor="#fff9c4"];
    }

    subgraph cluster_correction_sta {
        label="B. Timing Correction Loop"; style="rounded,filled"; color="#fff3e0"; node[fillcolor="#ffe0b2"];
        sta_correction [label="21. STA Corrector"];
    }

    subgraph cluster_signoff {
        label="3. Final Signoff"; style="rounded,filled"; color="#f3e5f5"; node[fillcolor="#e1bee7"];
        stream_out [label="22. GDSII Stream Out"];
        drc [label="23. DRC"];
        spice_extraction [label="24. SPICE Extraction"];
        lvs [label="25. LVS"];
        lvs_verifier [label="25.5 LVS Verifier", shape=diamond, style="rounded,filled", fillcolor="#fff9c4"];
        pin_counter [label="26. Pin Counter", shape=diamond, style="rounded,filled", fillcolor="#fff9c4"];
    }

    subgraph cluster_correction_pins {
        label="C. Pin Reduction Loop"; style="rounded,filled"; color="#dcedc8"; node[fillcolor="#c5e1a5"];
        pin_reduction_corrector [label="27. Pin Reduction Corrector"];
        pin_reduction_decomposer [label="28. Decomposer"];
        pin_reduction_testbench [label="29. Testbench Corrector"];
        pin_reduction_saver [label="30. File Saver"];
    }

    end_node [label="Flow Complete", shape=ellipse, style=filled, fillcolor="#b2dfdb"];

    // Main Flow
    file_processing -> icarus_simulation;
    icarus_simulation -> simulation_verifier [label="Sim OK", color=darkgreen];
    simulation_verifier -> setup [label="Verify OK", color=darkgreen];
    setup -> synthesis -> floorplan;
    floorplan -> pnr_group [label="Area OK", color=darkgreen];
    pnr_group -> sta;
    sta -> stream_out [label="Timing OK", color=darkgreen];
    stream_out -> drc -> spice_extraction -> lvs -> lvs_verifier;
    lvs_verifier -> pin_counter [label="LVS OK", color=darkgreen];
    pin_counter -> end_node [label="Pins OK", color=darkgreen, style=bold];

    // Correction Loops
    icarus_simulation -> verilog_corrector [label="Sim FAIL", style=dashed, color=red, fontcolor=red, constraint=false];
    simulation_verifier -> verilog_corrector [label="Verify FAIL", style=dashed, color=red, fontcolor=red, constraint=false];
    floorplan -> verilog_corrector [label="Area TOO BIG", style=dashed, color=red, fontcolor=red, constraint=false];
    lvs_verifier -> verilog_corrector [label="LVS FAIL", style=dashed, color=red, fontcolor=red, constraint=false];
    verilog_corrector -> code_decomposer -> design_name_updater -> testbench_corrector -> file_saver -> icarus_simulation [style=dashed, color=red];

    sta -> sta_correction [label="Timing FAIL", style=dashed, color=blue, fontcolor=blue, constraint=false];
    sta_correction -> setup [style=dashed, color=blue, label="Re-run PnR"];

    pin_counter -> pin_reduction_corrector [label="Too Many Pins", style=dashed, color="#E65100", fontcolor="#E65100", constraint=false];
    pin_reduction_corrector -> pin_reduction_decomposer -> design_name_updater -> pin_reduction_testbench -> pin_reduction_saver -> icarus_simulation [style=dashed, color="#E65100", label="Re-verify new I/O"];
}
""")


# === chipster/src/analog_generator/main.py ===
import streamlit as st
import os
import asyncio
import traceback

# LangChain and Gemini specific imports
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain.prompts import PromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnablePassthrough
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import DirectoryLoader
from dotenv import load_dotenv

# Core simulation and plotting imports
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import schemdraw
import schemdraw.elements as elm
import matplotlib.pyplot as plt
import numpy as np

# --- App Configuration & Initialization ---

st.set_page_config(layout="wide", page_title="LLM for Analog Chip Design ⚡️")
load_dotenv()

# Check for API Key
if not os.getenv("GOOGLE_API_KEY"):
    st.error("🚨 GOOGLE_API_KEY environment variable not found. Please create a .env file with your key.")
    st.stop()

# Initialize Session State Variables
for key in ['pyspice_code', 'schematic_code', 'simulation_code', 'initial_prompt']:
    if key not in st.session_state:
        st.session_state[key] = ""

# --- RAG Setup with Persistent FAISS Index ---

FAISS_INDEX_PATH = "../../data/analog_datasets/pyspice_index"

@st.cache_resource
def get_or_create_retriever():
    """Loads a FAISS index from disk if it exists, otherwise creates and saves it."""
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

        if os.path.exists(FAISS_INDEX_PATH):
            st.info(f"Loading existing FAISS index from '{FAISS_INDEX_PATH}'...")
            vectorstore = FAISS.load_local(FAISS_INDEX_PATH, embeddings, allow_dangerous_deserialization=True)
            st.success("FAISS index loaded successfully.")
            return vectorstore.as_retriever(search_kwargs={"k": 3})
        else:
            st.info(f"FAISS index not found. Creating a new one from the 'datasets' directory...")
            if not os.path.exists("datasets"):
                st.error("The 'datasets' directory was not found. Please create it and add your Python files.")
                return None

            loader = DirectoryLoader('./datasets/', glob="**/*.py", show_progress=True)
            raw_documents = loader.load()

            if not raw_documents:
                st.error("No .py files found in the 'datasets' directory. Cannot build knowledge base.")
                return None

            text_splitter = RecursiveCharacterTextSplitter.from_language(language="python", chunk_size=1000, chunk_overlap=100)
            documents = text_splitter.split_documents(raw_documents)

            st.info(f"Creating embeddings for {len(documents)} document chunks. This may take a moment...")
            vectorstore = FAISS.from_documents(documents, embeddings)
            vectorstore.save_local(FAISS_INDEX_PATH)
            st.success(f"New FAISS index created and saved to '{FAISS_INDEX_PATH}'.")
            return vectorstore.as_retriever(search_kwargs={"k": 3})

    except Exception as e:
        st.error(f"Failed to create or load the RAG retriever: {e}")
        st.code(traceback.format_exc())
        return None

# Initialize LLM and Retriever
LLM = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0.2)
RETRIEVER = get_or_create_retriever()


# --- Core Functions & Prompts ---

def extract_code_from_response(response: str) -> str:
    """Extracts Python code from a markdown formatted string."""
    if "```python" in response:
        return response.split("```python\n")[1].split("```")[0].strip()
    elif "```" in response:
        return response.split("```")[1].strip()
    return response

def generate_with_rag(prompt_template, query: str, retriever=RETRIEVER):
    """Generates code using a RAG chain, expecting a 'query'."""
    if not LLM or not retriever:
        st.error("ERROR: LLM or Retriever not initialized.")
        return ""
    rag_chain = (
        {"context": retriever.get_relevant_documents, "query": RunnablePassthrough()}
        | prompt_template
        | LLM
        | StrOutputParser()
    )
    response = rag_chain.invoke(query)
    return extract_code_from_response(response)

def generate_from_template(prompt_template, input_dict: dict):
    """Generates code using a simple prompt-to-LLM chain, no RAG."""
    if not LLM:
        st.error("ERROR: LLM not initialized.")
        return ""
    simple_chain = prompt_template | LLM | StrOutputParser()
    response = simple_chain.invoke(input_dict)
    return extract_code_from_response(response)

# --- Prompt Templates ---

PYSPICE_PROMPT = PromptTemplate.from_template("""
You are an expert in analog circuit design using PySpice. Generate a complete, runnable PySpice script based on the user's request, using the provided context for guidance.
CONTEXT: {context}
USER REQUEST: {query}
INSTRUCTIONS:
1. Create a single, complete Python script defining the circuit.
2. Import `PySpice.Spice.Netlist.Circuit` and `PySpice.Unit`.
3. Define necessary models (e.g., `circuit.model(...)`).
4. Construct the full circuit including all sources and components.
5. DO NOT include `simulator` or any analysis calls.
6. Output ONLY the Python code inside a markdown block.
""")

# --- FIX: Updated Schematic Prompt ---
SCHEMATIC_PROMPT = PromptTemplate.from_template("""
You are a `schemdraw` expert. Convert the following PySpice code into a `schemdraw` visualization.

PYSPICE CODE:
{pyspice_code}

MODIFICATION REQUEST:
{modification_prompt}

INSTRUCTIONS:
1. Create a `schemdraw.Drawing()` object named `d`.
2. Accurately represent all components and connections.
3. **IMPORTANT**: If the PySpice code defines a 4-terminal MOSFET (with a bulk connection), you MUST use `elm.NFet(bulk=True)` or `elm.PFet(bulk=True)`.
4. Label key nodes and components (e.g., 'Vin', 'Vout', 'R1', 'M1').
5. The final line of the script MUST be `d.draw()`. The application will handle rendering.
6. Output ONLY the Python code inside a markdown block.
""")

SIMULATION_PROMPT = PromptTemplate.from_template("""
You are a PySpice simulation expert. Generate a Python script to perform a DC sweep on the input 'Vin' of the given circuit and plot the 'Vout' using Matplotlib.
PYSPICE CODE:
{pyspice_code}
MODIFICATION REQUEST:
{modification_prompt}
INSTRUCTIONS:
1. Assume the `circuit` object from the PySpice code already exists.
2. Create the simulator and run a `.dc()` analysis on `Vin` from 0V to 5V.
3. Use `matplotlib.pyplot` to create the plot. Name the figure object `figure`.
4. Set a clear title for the plot and labels for the x and y axes.
5. Output ONLY the Python code for simulation and plotting inside a markdown block.
""")


# --- Streamlit UI ---

st.title("LLM for Analog Chip Design ⚡️")
st.write("Your AI assistant for analog circuit design, powered by LLM.")

st.header("1. Describe Your Circuit")
initial_prompt = st.text_area(
    "Start by describing the circuit you want to design (e.g., 'a common-source amplifier with a 4kOhm load').",
    height=100,
    key="initial_prompt_input"
)

if st.button("🚀 Generate Design", use_container_width=True, type="primary"):
    if initial_prompt and RETRIEVER:
        st.session_state.initial_prompt = initial_prompt
        with st.spinner("Step 1/3: Generating PySpice circuit..."):
            st.session_state.pyspice_code = generate_with_rag(PYSPICE_PROMPT, initial_prompt)
        with st.spinner("Step 2/3: Visualizing with Schemdraw..."):
            schematic_input = {"pyspice_code": st.session_state.pyspice_code, "modification_prompt": "None"}
            st.session_state.schematic_code = generate_from_template(SCHEMATIC_PROMPT, schematic_input)
        with st.spinner("Step 3/3: Simulating DC characteristics..."):
            simulation_input = {"pyspice_code": st.session_state.pyspice_code, "modification_prompt": "None"}
            st.session_state.simulation_code = generate_from_template(SIMULATION_PROMPT, simulation_input)
    elif not initial_prompt:
        st.warning("Please describe the circuit you want to build.")
    else:
        st.error("Retriever is not available. Please check the console for errors.")

if st.session_state.pyspice_code:
    st.header("2. Review and Refine Your Design")

    col_code1, col_code2, col_code3 = st.columns(3)
    with col_code1:
        st.subheader("PySpice Code")
        st.session_state.pyspice_code = st.text_area("Circuit Definition", value=st.session_state.pyspice_code, height=300, key="pyspice_editor")
    with col_code2:
        st.subheader("Schematic Code")
        st.session_state.schematic_code = st.text_area("`schemdraw` Visualization", value=st.session_state.schematic_code, height=300, key="schematic_editor")
    with col_code3:
        st.subheader("Simulation Code")
        st.session_state.simulation_code = st.text_area("`matplotlib` Plotting", value=st.session_state.simulation_code, height=300, key="simulation_editor")

    st.header("3. Visualize and Simulate")

    col_vis1, col_vis2 = st.columns(2)
    with col_vis1:
        st.subheader("Circuit Schematic")
        if st.session_state.schematic_code:
            try:
                # --- FIX: Correctly render schemdraw by capturing the Matplotlib figure ---
                plt.figure() # Create a new figure to draw on
                exec_globals = {'schemdraw': schemdraw, 'elm': elm, 'plt': plt}
                exec(st.session_state.schematic_code, exec_globals)
                fig = plt.gcf() # Get the current figure that schemdraw drew on
                st.pyplot(fig)
            except Exception:
                st.error("Error in schematic code:")
                st.code(traceback.format_exc())

    with col_vis2:
        st.subheader("DC Simulation Plot")
        if st.session_state.pyspice_code and st.session_state.simulation_code:
            try:
                full_code = st.session_state.pyspice_code + "\n" + st.session_state.simulation_code
                exec_globals = {
                    'Circuit': Circuit, 'u_kOhm': u_kOhm, 'u_V': u_V, 'u_uA': u_uA,
                    'u_uF': u_uF, 'u_nH': u_nH, 'u_pF': u_pF, 'u_Ohm': u_Ohm,
                    'u_mH': u_mH, 'u_mV': u_mV, '@u_kΩ': u_kOhm,
                    'plt': plt, 'np': np
                }
                exec(full_code, exec_globals)
                fig = exec_globals.get('figure')
                if fig:
                    st.pyplot(fig)
                else:
                    st.warning("Could not find a `figure` object in the simulation code to plot.")
            except Exception:
                st.error("Error during simulation:")
                st.code(traceback.format_exc())


# === chipster/src/analog_generator/graph_maker/graph.py ===
import streamlit as st
import os
import networkx as nx
import matplotlib.pyplot as plt
import traceback
import numpy as np
from io import BytesIO
from typing import TypedDict, List
from collections import defaultdict
import re

# LangChain and Gemini specific imports
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import PromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.schema.runnable import RunnablePassthrough
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.docstore.document import Document
from dotenv import load_dotenv

from langgraph.graph import StateGraph, END

# Load environment variables
load_dotenv()


# --- Agent Definitions ---

def pyspice_parser_agent(state):
    """Parses PySpice code to extract components and their named connections."""
    pyspice_code = state['pyspice_code']
    components = []
    lines = pyspice_code.split('\n')
    
    for line in lines:
        # Handle both circuit. and self. formats
        if ('circuit.' in line or 'self.' in line) and '(' in line:
            try:
                clean_line = line.split('#')[0].strip()
                
                # Skip lines that are just comments or empty
                if not clean_line or clean_line.startswith('#'):
                    continue
                
                # Find the component call
                if '(' not in clean_line or ')' not in clean_line:
                    continue
                    
                parts = clean_line.split('(')
                if len(parts) < 2:
                    continue
                    
                comp_type_part = parts[0].split('.')[-1]
                args_part = parts[1].split(')')[0]
                
                # Handle arguments that might contain @ symbol (PySpice units)
                args = []
                for arg in args_part.split(','):
                    arg = arg.strip().strip("'\"")
                    # Handle PySpice unit syntax like 1@u_mA
                    if '@' in arg:
                        arg = arg.split('@')[0].strip()
                    # Handle keyword arguments by taking only the value
                    if '=' in arg:
                        arg = arg.split('=')[1].strip().strip("'\"")
                    args.append(arg)

                terminals, connections = [], []
                
                # Parse different component types
                if comp_type_part in ["V", "I"]:
                    if len(args) >= 4:  # name, n+, n-, value
                        connections = args[1:3]
                        terminals = ['n+', 'n-']
                elif comp_type_part == "R":
                    if len(args) >= 4:  # name, n1, n2, value
                        connections = args[1:3]
                        terminals = ['n1', 'n2']
                elif comp_type_part == "MOSFET":
                    if len(args) >= 5:  # name, drain, gate, source, body, [model, ...]
                        connections = args[1:5]
                        terminals = ['D', 'G', 'S', 'B']

                # Clean up connection names
                if connections:
                    cleaned_connections = []
                    for conn in connections:
                        # Replace both circuit.gnd and self.gnd with gnd
                        conn = conn.replace("circuit.gnd", "gnd").replace("self.gnd", "gnd")
                        cleaned_connections.append(conn)
                    
                    named_connections = list(zip(terminals, cleaned_connections))
                    components.append({
                        "name": args[0], 
                        "type": comp_type_part, 
                        "connections": named_connections
                    })
                    
            except (IndexError, ValueError) as e:
                # Skip malformed lines
                continue
            
    return {"components": components}


def graph_builder_agent(state):
    """Builds a networkx MultiGraph to allow for parallel edges."""
    components = state.get('components', [])
    if not components: return {"graph": None}
    
    g = nx.MultiGraph() 
    
    for comp in components:
        comp_name = f"{comp['type']}_{comp['name']}"
        g.add_node(comp_name, type='component')
        for terminal, conn_net in comp['connections']:
            g.add_node(conn_net, type='net')
            g.add_edge(comp_name, conn_net, label=terminal)
    return {"graph": g}


def calculate_label_offset(angle, offset_distance=0.15):
    """Calculate offset position for edge labels to avoid overlaps."""
    return offset_distance * np.cos(angle), offset_distance * np.sin(angle)


def lcapy_converter_agent(state):
    """Converts the parsed components to LCapy netlist format with smart node naming."""
    components = state.get('components', [])
    if not components:
        return {"lcapy_netlist": None}

    # 1. Create base node mapping (gnd -> 0, Vdd -> 1, etc.)
    net_to_node = {}
    node_counter = 0
    if 'gnd' not in net_to_node:
        net_to_node['gnd'] = 0
        node_counter = 1
    
    all_nets = sorted({net for comp in components for _, net in comp['connections']})
    for net in all_nets:
        if net not in net_to_node:
            net_to_node[net] = node_counter
            node_counter += 1

    # 2. Pre-scan components to understand how nets are used
    other_node_usage = defaultdict(int)
    for comp in components:
        if comp['type'] != 'MOSFET':
            for _, net in comp['connections']:
                base_node = net_to_node[net]
                other_node_usage[base_node] += 1

    # 3. Build the LCapy netlist with smart node naming
    lcapy_lines = [
        "# LCapy Netlist",
        "from lcapy import Circuit",
        "cct = Circuit()",
        ""
    ]
    node_suffix_counters = defaultdict(lambda: 2)

    for comp in components:
        comp_name = comp['name']
        comp_type = comp['type']
        
        node_strings = []
        for _, net in comp['connections']:
            base_node = net_to_node[net]
            node_name = ""

            if comp_type == 'MOSFET':
                # MOSFETs always use the simple, base node name
                node_name = str(base_node)
            else:
                # For other components, check if the net is "busy"
                if other_node_usage[base_node] > 1:
                    # If a net connects to more than one non-MOSFET, it needs a unique, suffixed name
                    suffix = node_suffix_counters[base_node]
                    node_name = f"{base_node}_{suffix}"
                    node_suffix_counters[base_node] += 1
                else:
                    # Otherwise, use the simple base name
                    node_name = str(base_node)
            
            node_strings.append(node_name)

        # Format the LCapy `add` command based on component type
        connections_str = ' '.join(node_strings)
        if comp_type == 'V':
            lcapy_lines.append(f"cct.add('V{comp_name} {connections_str}; down')")
        elif comp_type == 'I':
            lcapy_lines.append(f"cct.add('I{comp_name} {connections_str}; down')")
        elif comp_type == 'R':
            lcapy_lines.append(f"cct.add('R{comp_name} {connections_str}; right')")
        elif comp_type == 'MOSFET':
            lcapy_lines.append(f"cct.add('M{comp_name} {connections_str}; up')")

    lcapy_lines.extend(["", "# Draw the circuit", "cct.draw()"])
    lcapy_netlist = '\n'.join(lcapy_lines)

    return {
        "lcapy_netlist": lcapy_netlist,
        "net_to_node_mapping": net_to_node
    }


def lcapy_plotter_agent(state):
    """Plots the schematic using matplotlib by executing LCapy code."""
    lcapy_netlist = state.get('lcapy_netlist')
    if lcapy_netlist is None:
        return {"schematic_image": None}
    
    try:
        # Create a temporary module to execute the LCapy code
        import tempfile
        import subprocess
        import sys
        
        # Create temporary file for the LCapy script
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            # Write the LCapy code with matplotlib integration
            lcapy_code = f"""
{lcapy_netlist}

# Save the schematic to a file
import matplotlib.pyplot as plt
plt.savefig('temp_schematic.png', dpi=300, bbox_inches='tight')
plt.close()

# Read the image back as bytes
with open('temp_schematic.png', 'rb') as img_file:
    img_data = img_file.read()
    
# Save to a location we can access
with open('schematic_output.png', 'wb') as out_file:
    out_file.write(img_data)
"""
            f.write(lcapy_code)
            temp_script = f.name
        
        # Execute the script in a subprocess (safer than exec)
        try:
            result = subprocess.run([sys.executable, temp_script], 
                                    capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                # Try to read the generated image
                try:
                    with open('schematic_output.png', 'rb') as img_file:
                        img_data = img_file.read()
                        buf = BytesIO(img_data)
                        return {"schematic_image": buf}
                except FileNotFoundError:
                    pass
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        
        # If LCapy fails, create a simple matplotlib representation
        return create_simple_schematic_plot(state)
        
    except Exception as e:
        # Fallback: create a simple schematic representation
        return create_simple_schematic_plot(state)
    finally:
        # Cleanup temporary files
        try:
            os.unlink(temp_script)
            os.unlink('temp_schematic.png')
            os.unlink('schematic_output.png')
        except:
            pass


def create_simple_schematic_plot(state):
    """Creates a simple schematic-like plot when LCapy is not available."""
    components = state.get('components', [])
    net_to_node = state.get('net_to_node_mapping', {})
    
    if not components:
        return {"schematic_image": None}
    
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Simple schematic layout
    y_pos = 0
    component_positions = {}
    
    for i, comp in enumerate(components):
        comp_name = f"{comp['type']}_{comp['name']}"
        y_pos = len(components) - i - 1
        
        if comp['type'] == 'V':
            # Draw voltage source as circle with +/-
            circle = plt.Circle((1, y_pos), 0.3, fill=False, color='blue', linewidth=2)
            ax.add_patch(circle)
            ax.text(1, y_pos, 'V', ha='center', va='center', fontsize=10, fontweight='bold')
            ax.text(0.5, y_pos, comp['name'], ha='center', va='center', fontsize=8)
            
        elif comp['type'] == 'R':
            # Draw resistor as zigzag rectangle
            rect = plt.Rectangle((0.5, y_pos-0.1), 1, 0.2, fill=False, color='green', linewidth=2)
            ax.add_patch(rect)
            ax.text(1, y_pos, 'R', ha='center', va='center', fontsize=10, fontweight='bold')
            ax.text(0.3, y_pos, comp['name'], ha='center', va='center', fontsize=8)
            
        elif comp['type'] == 'I':
            # Draw current source as circle with arrow
            circle = plt.Circle((1, y_pos), 0.3, fill=False, color='red', linewidth=2)
            ax.add_patch(circle)
            ax.text(1, y_pos, 'I', ha='center', va='center', fontsize=10, fontweight='bold')
            ax.text(0.5, y_pos, comp['name'], ha='center', va='center', fontsize=8)
            
        elif comp['type'] == 'MOSFET':
            # Draw MOSFET as rectangle with terminals
            rect = plt.Rectangle((0.5, y_pos-0.2), 1, 0.4, fill=False, color='purple', linewidth=2)
            ax.add_patch(rect)
            ax.text(1, y_pos, 'M', ha='center', va='center', fontsize=10, fontweight='bold')
            ax.text(0.3, y_pos, comp['name'], ha='center', va='center', fontsize=8)
            
            # Add terminal labels
            connections = comp['connections']
            ax.text(1.7, y_pos+0.1, f"D:{net_to_node.get(connections[0][1], connections[0][1])}", fontsize=7)
            ax.text(1.7, y_pos, f"G:{net_to_node.get(connections[1][1], connections[1][1])}", fontsize=7)
            ax.text(1.7, y_pos-0.1, f"S:{net_to_node.get(connections[2][1], connections[2][1])}", fontsize=7)
        
        # Draw connection lines and labels
        for j, (terminal, net) in enumerate(comp['connections']):
            node_num = net_to_node.get(net, net)
            connection_x = 2.5 + j * 0.5
            ax.plot([1.5, connection_x], [y_pos, y_pos], 'k-', linewidth=1)
            ax.text(connection_x, y_pos + 0.15, f"{terminal}", fontsize=8, ha='center', color='red')
            ax.text(connection_x, y_pos - 0.15, f"({node_num})", fontsize=8, ha='center', color='blue')
    
    # Add title and formatting
    ax.set_title("Circuit Schematic Representation", fontsize=14, fontweight='bold')
    ax.set_xlim(-0.5, 5)
    ax.set_ylim(-0.5, len(components))
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)
    ax.set_xticks([])
    ax.set_yticks([])
    
    # Add legend for node mapping
    legend_text = "Node Mapping:\n"
    for net, node in sorted(net_to_node.items(), key=lambda x: x[1]):
        legend_text += f"{net} → {node}\n"
    
    ax.text(4.5, len(components)-1, legend_text, fontsize=9, 
            bbox=dict(boxstyle="round,pad=0.5", facecolor='lightgray', alpha=0.8),
            verticalalignment='top')
    
    plt.tight_layout()
    
    # Save to buffer
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=300, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    
    return {"schematic_image": buf}

def graph_drawer_agent(state):
    """
    Draws the MultiGraph with separate visible edges for each connection.
    """
    g = state.get('graph')
    if g is None: return {"image": None}
    
    # Use a larger figure for better readability
    fig, ax = plt.subplots(figsize=(18, 14))
    
    # Use a layout that spreads nodes better
    pos = nx.spring_layout(g, k=2.5, iterations=100, seed=42)

    # Draw nodes with better spacing and colors
    component_nodes = [n for n, d in g.nodes(data=True) if d.get('type') == 'component']
    net_nodes = [n for n, d in g.nodes(data=True) if d.get('type') == 'net']
    
    nx.draw_networkx_nodes(g, pos, nodelist=component_nodes, 
                           node_shape='s', node_color='lightblue', 
                           node_size=5000, ax=ax, edgecolors='navy', linewidths=2)
    nx.draw_networkx_nodes(g, pos, nodelist=net_nodes, 
                           node_shape='o', node_color='lightgreen', 
                           node_size=3000, ax=ax, edgecolors='darkgreen', linewidths=2)

    # Draw node labels
    nx.draw_networkx_labels(g, pos, font_size=9, font_weight='bold', ax=ax)

    # --- Draw separate edges for each connection ---
    # Group edges by connected nodes to handle multiple edges
    edge_groups = defaultdict(list)
    for u, v, key in g.edges(keys=True):
        edge_key = (u, v) if u < v else (v, u)  # Normalize edge direction for grouping
        edge_groups[edge_key].append((u, v, key))

    # Draw each edge separately with proper curves for multiple connections
    for edge_key, edges in edge_groups.items():
        u_base, v_base = edge_key
        pos_u = np.array(pos[u_base])
        pos_v = np.array(pos[v_base])
        
        num_edges = len(edges)
        
        for i, (u, v, key) in enumerate(edges):
            # Get the label for this edge
            label = g[u][v][key].get('label', '')
            
            if num_edges == 1:
                # Single edge: draw straight line
                nx.draw_networkx_edges(g, pos, edgelist=[(u, v)], 
                                     width=2, edge_color='gray', alpha=0.8, ax=ax)
                
                # Place label at midpoint
                midpoint = (pos_u + pos_v) / 2
                edge_vector = pos_v - pos_u
                edge_length = np.linalg.norm(edge_vector)
                if edge_length > 0:
                    perp_vector = np.array([-edge_vector[1], edge_vector[0]]) / edge_length
                    label_pos = midpoint + perp_vector * 0.08
                else:
                    label_pos = midpoint
            else:
                # Multiple edges: draw with curves to separate them visually
                # Calculate curve radius based on edge index
                curve_offset = 0.15 + (i // 2) * 0.1
                if i % 2 == 1:
                    curve_offset = -curve_offset
                
                # Draw curved edge
                connectionstyle = f"arc3,rad={curve_offset}"
                nx.draw_networkx_edges(g, pos, edgelist=[(u, v)], 
                                     width=2, edge_color='gray', alpha=0.8, ax=ax,
                                     connectionstyle=connectionstyle)
                
                # Calculate label position on the curve
                # For curved edges, we need to calculate the midpoint of the curve
                edge_vector = pos_v - pos_u
                edge_length = np.linalg.norm(edge_vector)
                if edge_length > 0:
                    # Calculate the curved midpoint
                    straight_midpoint = (pos_u + pos_v) / 2
                    perp_vector = np.array([-edge_vector[1], edge_vector[0]]) / edge_length
                    curve_midpoint = straight_midpoint + perp_vector * curve_offset * edge_length * 0.5
                    
                    # Add small offset for label readability
                    label_offset = perp_vector * 0.05
                    label_pos = curve_midpoint + label_offset
                else:
                    label_pos = pos_u
            
            # Draw the label with background for better readability
            ax.annotate(label, xy=label_pos, fontsize=9, fontweight='bold',
                        color='red', ha='center', va='center',
                        bbox=dict(boxstyle="round,pad=0.2", facecolor='white', 
                                  edgecolor='red', alpha=0.8))

    # Improve the legend
    legend_elements = [
        plt.Line2D([0], [0], marker='s', color='w', label='Component', 
                   markerfacecolor='lightblue', markersize=15, markeredgecolor='navy', markeredgewidth=2),
        plt.Line2D([0], [0], marker='o', color='w', label='Net', 
                   markerfacecolor='lightgreen', markersize=15, markeredgecolor='darkgreen', markeredgewidth=2)
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=12, framealpha=0.9)

    # Set title and clean up the plot
    ax.set_title("Circuit Graph Visualization", fontsize=16, fontweight='bold', pad=20)
    ax.set_aspect('equal')
    
    # Remove axes ticks and labels for cleaner look
    ax.set_xticks([])
    ax.set_yticks([])
    
    # Add grid for better visual reference
    ax.grid(True, alpha=0.3)
    
    # Adjust margins
    plt.tight_layout()
    
    # Save to buffer
    buf = BytesIO()
    plt.savefig(buf, format="png", dpi=300, bbox_inches='tight')
    plt.close(fig) # Close the figure to free memory
    buf.seek(0)
    return {"image": buf}


# --- RAG Agent Setup ---
def create_rag_chain(pyspice_code):
    """Creates a RAG chain to analyze component parameters from the PySpice code."""
    docs = [Document(page_content=pyspice_code)]
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(docs)
    embeddings = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')
    vectorstore = FAISS.from_documents(documents=splits, embedding=embeddings)
    retriever = vectorstore.as_retriever()
    template = """You are a meticulous PySpice code analyzer. Your task is to analyze the provided code and explain the parameters for each component with high accuracy.
**Instructions:**
1.  Identify each line of code that defines a component (`circuit.V`, `circuit.R`, `circuit.I`, `circuit.MOSFET`).
2.  Use the standard PySpice syntax below as a reference template.
3.  For each component instance in the code, list its parameters one-by-one, matching them to the reference syntax. **Do not miss any parameters.**
---
**Reference Syntax Template:**
* `circuit.V(name, n_plus, n_minus, dc_value)`
* `circuit.I(name, n_plus, n_minus, dc_value)`
* `circuit.R(name, node1, node2, resistance_value)`
* `circuit.MOSFET(name, drain, gate, source, body, model='model_name')`
---
**Code Context to Analyze:**
{context}
**Your Detailed Analysis:**
{question}
"""
    prompt = PromptTemplate.from_template(template)
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-pro", temperature=0)
    rag_chain = ({"context": retriever, "question": RunnablePassthrough()} | prompt | llm | StrOutputParser())
    return rag_chain

# --- LangGraph Workflow ---
class GraphState(TypedDict, total=False):
    pyspice_code: str
    components: List[dict]
    graph: nx.Graph
    image: BytesIO
    lcapy_netlist: str
    net_to_node_mapping: dict
    schematic_image: BytesIO

workflow = StateGraph(GraphState)
workflow.add_node("parser", pyspice_parser_agent)
workflow.add_node("builder", graph_builder_agent)
workflow.add_node("drawer", graph_drawer_agent)
workflow.add_node("lcapy_converter", lcapy_converter_agent)
workflow.add_node("lcapy_plotter", lcapy_plotter_agent)

workflow.set_entry_point("parser")
workflow.add_edge("parser", "builder")
workflow.add_edge("builder", "drawer")
workflow.add_edge("drawer", "lcapy_converter")
workflow.add_edge("lcapy_converter", "lcapy_plotter")
workflow.add_edge("lcapy_plotter", END)

app_graph = workflow.compile()

# --- Streamlit UI ---
st.set_page_config(page_title="LLM for Chip Design Automation", layout="wide")
st.title("Circuit Visualizer and Analyzer")

# Create three columns for better layout
col1, col2, col3 = st.columns([1, 1, 1])

with col1:
    st.header("PySpice Code Input")
    pyspice_code_input = st.text_area(
        "Enter your PySpice code here:",
        height=450,
        value="""from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class CommonDrainAmp(SubCircuitFactory):
    NAME = ('CommonDrainAmp')
    NODES = ('Vin', 'Vout')
    def __init__(self):
        super().__init__()
        # Define the MOSFET model
        self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
        # Power Supply for the power
        self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
        # Common-Drain Amplifier with Resistor Load
        self.MOSFET('1', 'Vdd', 'Vin', 'Vout', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
        self.R('load', 'Vout', self.gnd, 1@u_kOhm)
"""
    )
    if st.button("Generate Circuit Visualizations", use_container_width=True):
        with st.spinner("Generating visualizations..."):
            initial_state = {"pyspice_code": pyspice_code_input}
            final_state = app_graph.invoke(initial_state)
            if final_state:
                if final_state.get('image'):
                    st.session_state.graph_image = final_state.get('image')
                if final_state.get('schematic_image'):
                    st.session_state.schematic_image = final_state.get('schematic_image')
                if final_state.get('lcapy_netlist'):
                    st.session_state.lcapy_netlist = final_state.get('lcapy_netlist')
                if final_state.get('net_to_node_mapping'):
                    st.session_state.net_mapping = final_state.get('net_to_node_mapping')
                st.session_state.pyspice_code_for_rag = pyspice_code_input
                st.rerun()
            else:
                st.error("Failed to generate visualizations. Check code for errors.")

with col2:
    st.header("Graph Visualization")
    if 'graph_image' in st.session_state and st.session_state.graph_image:
        st.image(st.session_state.graph_image, caption="Circuit Graph", use_container_width=True)
    else:
        st.write("Graph will be displayed here once generated.")

with col3:
    st.header("Schematic Visualization")
    if 'schematic_image' in st.session_state and st.session_state.schematic_image:
        st.image(st.session_state.schematic_image, caption="Circuit Schematic", use_container_width=True)
    else:
        st.write("Schematic will be displayed here once generated.")

# LCapy Netlist Display
st.divider()
st.header("🔌 Generated LCapy Netlist")
if 'lcapy_netlist' in st.session_state and st.session_state.lcapy_netlist:
    col_netlist, col_mapping = st.columns([2, 1])
    
    with col_netlist:
        st.code(st.session_state.lcapy_netlist, language='python')
    
    with col_mapping:
        st.subheader("Node Mapping")
        if 'net_mapping' in st.session_state:
            mapping_text = ""
            for net, node in sorted(st.session_state.net_mapping.items(), key=lambda x: x[1]):
                mapping_text += f"**{net}** → Node {node}\n"
            st.markdown(mapping_text)
else:
    st.info("LCapy netlist will be displayed here once generated.")

st.divider()
st.header("⚙️ Detailed Component Parameter Analysis (RAG)")
if 'pyspice_code_for_rag' in st.session_state and st.session_state.pyspice_code_for_rag:
    if st.button("Analyze Component Parameters", use_container_width=True):
        with st.spinner("Performing detailed analysis..."):
            try:
                rag_chain = create_rag_chain(st.session_state.pyspice_code_for_rag)
                fixed_question = "Provide a detailed analysis of the component parameters found in the code."
                answer = rag_chain.invoke(fixed_question)
                st.markdown(answer)
            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.error(traceback.format_exc())
else:
    st.info("Generate visualizations first to enable parameter analysis.")

# === chipster/src/chip_digital_generator/openlane2_workflow/main.py ===
import streamlit as st
import os
import json
import pandas as pd
from langgraph.graph import StateGraph, END, START
from typing import TypedDict, List, Dict, Any
import shutil
from openlane.state import State
from openlane.steps import Step
from openlane.config import Config
from pathlib import Path
import re 

# --- Agentic Workflow using LangGraph ---

class AgentState(TypedDict):
    uploaded_files: List[Any]
    top_level_module: str
    design_name: str
    verilog_files: List[str]
    config: Dict[str, Any]
    run_path: str
    synthesis_state_out: State
    floorplan_state_out: State
    tap_endcap_state_out: State
    io_placement_state_out: State
    pdn_state_out: State
    global_placement_state_out: State
    detailed_placement_state_out: State
    cts_state_out: State
    global_routing_state_out: State
    detailed_routing_state_out: State
    fill_insertion_state_out: State
    rcx_state_out: State
    sta_state_out: State
    stream_out_state_out: State
    drc_state_out: State
    spice_extraction_state_out: State
    lvs_state_out: State


# Agent 1: File Processing and Setup
def file_processing_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 📂 Agent 1: File Processing")
    uploaded_files = state["uploaded_files"]
    top_level_module = state["top_level_module"]
    design_name = top_level_module
    
    run_path = os.path.abspath(os.path.join("..", "..", "examples", "generated_chips", f"generated_{design_name}"))
    if os.path.exists(run_path):
        shutil.rmtree(run_path)
    os.makedirs(run_path, exist_ok=True)

    src_dir = os.path.join(run_path, "src")
    os.makedirs(src_dir, exist_ok=True)
    verilog_files = []
    for file in uploaded_files:
        file_path = os.path.join(src_dir, file.name)
        with open(file_path, "wb") as f: f.write(file.getbuffer())
        if file.name.endswith((".v", ".vh")): verilog_files.append(file_path)

    st.write(f"✅ Top-level module '{top_level_module}' selected.")
    st.write(f"✅ Verilog files saved in: `{src_dir}`")
    
    os.chdir(run_path)
    st.write(f"✅ Changed working directory to: `{os.getcwd()}`")

    return {
        "design_name": design_name,
        "verilog_files": [os.path.relpath(p, os.getcwd()) for p in verilog_files],
        "run_path": os.getcwd(),
    }

# Agent 2: OpenLane Setup
def setup_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🛠️ Agent 2: OpenLane Setup")
    config = Config.interactive(
        state["design_name"],
        PDK="gf180mcuC",
        CLOCK_PORT="clk", CLOCK_NET="clk", CLOCK_PERIOD=10,
        PRIMARY_GDSII_STREAMOUT_TOOL="klayout",
    )
    st.write("✅ OpenLane configuration created successfully.")
    return {"config": config}


# Physical Step Agents ...
def synthesis_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🔬 Agent 3: Synthesis")
    st.write("""Converting high-level Verilog to a netlist of standard cells.""")
    Synthesis = Step.factory.get("Yosys.Synthesis")
    synthesis_step = Synthesis(config=state["config"], state_in=State(), VERILOG_FILES=state["verilog_files"])
    synthesis_step.start()
    report_path = os.path.join(synthesis_step.step_dir, "reports", "stat.json")
    with open(report_path) as f: metrics = json.load(f)
    st.write("#### Synthesis Metrics")
    st.table(pd.DataFrame.from_dict(metrics, orient='index', columns=["Value"]).astype(str))
    return {"synthesis_state_out": synthesis_step.state_out}

def floorplan_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🏗️ Agent 4: Floorplanning")
    st.write("""Determining the chip's dimensions and creating the cell placement grid.""")
    Floorplan = Step.factory.get("OpenROAD.Floorplan")
    floorplan_step = Floorplan(config=state["config"], state_in=state["synthesis_state_out"])
    floorplan_step.start()
    metrics_path = os.path.join(floorplan_step.step_dir, "or_metrics_out.json")
    with open(metrics_path) as f: metrics = json.load(f)
    st.write("#### Floorplan Metrics")
    st.table(pd.DataFrame(metrics.items(), columns=["Metric", "Value"]).astype(str))
    return {"floorplan_state_out": floorplan_step.state_out}

def tap_endcap_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 💠 Agent 5: Tap/Endcap Insertion")
    st.write("""Placing tap and endcap cells for power stability.""")
    TapEndcap = Step.factory.get("OpenROAD.TapEndcapInsertion")
    tap_step = TapEndcap(config=state["config"], state_in=state["floorplan_state_out"])
    tap_step.start()
    return {"tap_endcap_state_out": tap_step.state_out}

def io_placement_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 📍 Agent 6: I/O Pin Placement")
    st.write("Placing I/O pins at the edges of the design.")
    IOPlacement = Step.factory.get("OpenROAD.IOPlacement")
    ioplace_step = IOPlacement(config=state["config"], state_in=state["tap_endcap_state_out"])
    ioplace_step.start()
    return {"io_placement_state_out": ioplace_step.state_out}

def generate_pdn_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ⚡ Agent 7: Power Distribution Network (PDN) Generation")
    st.write("""Creating the metal grid for power and ground.""")
    GeneratePDN = Step.factory.get("OpenROAD.GeneratePDN")
    pdn_step = GeneratePDN(config=state["config"], state_in=state["io_placement_state_out"], FP_PDN_VWIDTH=2, FP_PDN_HWIDTH=2, FP_PDN_VPITCH=30, FP_PDN_HPITCH=30)
    pdn_step.start()
    return {"pdn_state_out": pdn_step.state_out}

def global_placement_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🌍 Agent 8: Global Placement")
    st.write("""Finding an approximate location for all standard cells.""")
    GlobalPlacement = Step.factory.get("OpenROAD.GlobalPlacement")
    gpl_step = GlobalPlacement(config=state["config"], state_in=state["pdn_state_out"])
    gpl_step.start()
    return {"global_placement_state_out": gpl_step.state_out}

def detailed_placement_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 📐 Agent 9: Detailed Placement")
    st.write("""Snapping cells to the legal manufacturing grid.""")
    DetailedPlacement = Step.factory.get("OpenROAD.DetailedPlacement")
    dpl_step = DetailedPlacement(config=state["config"], state_in=state["global_placement_state_out"])
    dpl_step.start()
    return {"detailed_placement_state_out": dpl_step.state_out}

def cts_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🌳 Agent 10: Clock Tree Synthesis (CTS)")
    st.write("""Building the clock distribution network.""")
    CTS = Step.factory.get("OpenROAD.CTS")
    cts_step = CTS(config=state["config"], state_in=state["detailed_placement_state_out"])
    cts_step.start()
    return {"cts_state_out": cts_step.state_out}

def global_routing_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🗺️ Agent 11: Global Routing")
    st.write("""Planning the paths for the interconnect wires.""")
    GlobalRouting = Step.factory.get("OpenROAD.GlobalRouting")
    grt_step = GlobalRouting(config=state["config"], state_in=state["cts_state_out"])
    grt_step.start()
    metrics_path = os.path.join(grt_step.step_dir, "or_metrics_out.json")
    with open(metrics_path) as f: metrics = json.load(f)
    st.write("#### Global Routing Metrics")
    st.table(pd.DataFrame(metrics.items(), columns=["Metric", "Value"]).astype(str))
    return {"global_routing_state_out": grt_step.state_out}

def detailed_routing_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ✍️ Agent 12: Detailed Routing")
    st.write("""Creating the final physical wires on the metal layers.""")
    DetailedRouting = Step.factory.get("OpenROAD.DetailedRouting")
    drt_step = DetailedRouting(config=state["config"], state_in=state["global_routing_state_out"])
    drt_step.start()
    return {"detailed_routing_state_out": drt_step.state_out}

def fill_insertion_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🧱 Agent 13: Fill Insertion")
    st.write("""Filling empty gaps in the design with 'fill cells' for manufacturability.""")
    FillInsertion = Step.factory.get("OpenROAD.FillInsertion")
    fill_step = FillInsertion(config=state["config"], state_in=state["detailed_routing_state_out"])
    fill_step.start()
    return {"fill_insertion_state_out": fill_step.state_out}

def rcx_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 🔌 Agent 14: Parasitics Extraction (RCX)")
    st.write("""This step computes the parasitic resistance and capacitance of the wires, which affect timing.""")
    RCX = Step.factory.get("OpenROAD.RCX")
    rcx_step = RCX(config=state["config"], state_in=state["fill_insertion_state_out"])
    rcx_step.start()
    metrics_path = os.path.join(rcx_step.step_dir, "or_metrics_out.json")
    with open(metrics_path) as f: metrics = json.load(f)
    st.write("#### Parasitics Extraction Metrics")
    st.table(pd.DataFrame(metrics.items(), columns=["Metric", "Value"]).astype(str))
    return {"rcx_state_out": rcx_step.state_out}

def sta_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ⏱️ Agent 15: Static Timing Analysis (STA)")
    st.write("""This final analysis step verifies that the chip meets its timing constraints to run at the rated clock speed.""")
    STAPostPNR = Step.factory.get("OpenROAD.STAPostPNR")
    sta_step = STAPostPNR(config=state["config"], state_in=state["rcx_state_out"])
    sta_step.start()
    st.write("#### STA Timing Violation Summary")
    sta_results = []
    value_re = re.compile(r":\s*(-?[\d\.]+)")
    reports_to_find = ["tns.max.rpt", "tns.min.rpt", "wns.max.rpt", "wns.min.rpt", "ws.max.rpt", "ws.min.rpt"]
    for root, _, files in os.walk(sta_step.step_dir):
        for file in files:
            if file in reports_to_find:
                corner = os.path.basename(root)
                metric = file.replace(".rpt", "").replace(".", " ").title()
                with open(os.path.join(root, file)) as f:
                    content = f.read()
                    match = value_re.search(content)
                    if match:
                        value = float(match.group(1))
                        sta_results.append([corner, metric, value])
    if sta_results:
        df_sta = pd.DataFrame(sta_results, columns=["Corner", "Metric", "Value (ps)"])
        pivoted_df = df_sta.pivot(index='Metric', columns='Corner', values='Value (ps)')
        def style_violations(val):
            try:
                color = 'green' if float(val) >= 0 else 'red'
                return f'color: {color}'
            except (ValueError, TypeError): return ''
        styled_df = pivoted_df.style.applymap(style_violations).format("{:.2f}")
        st.dataframe(styled_df)
    else:
        st.warning("Could not parse key STA report files (TNS, WNS, WS).")
    return {"sta_state_out": sta_step.state_out}

def stream_out_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### 💾 Agent 16: GDSII Stream Out")
    st.write("This step converts the final layout into GDSII format, the file that is sent to the foundry for fabrication.")
    StreamOut = Step.factory.get("KLayout.StreamOut")
    gds_step = StreamOut(config=state["config"], state_in=state["sta_state_out"])
    gds_step.start()
    return {"stream_out_state_out": gds_step.state_out}

def drc_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ✅ Agent 17: Design Rule Check (DRC)")
    st.write("Checks if the final layout violates any of the foundry's manufacturing rules.")
    DRC = Step.factory.get("Magic.DRC")
    drc_step = DRC(config=state["config"], state_in=state["stream_out_state_out"])
    drc_step.start()
    st.write("#### DRC Violation Report")
    report_path = os.path.join(drc_step.step_dir, "reports", "drc_violations.magic.rpt")
    try:
        with open(report_path) as f:
            content = f.read()
            count_match = re.search(r"\[INFO\] COUNT: (\d+)", content)
            if count_match:
                count = int(count_match.group(1))
                if count == 0: st.success("✅ No DRC violations found.")
                else: st.error(f"❌ Found {count} DRC violations.")
                st.text(content)
            else: st.text(content)
    except FileNotFoundError: st.warning("DRC report file not found.")
    return {"drc_state_out": drc_step.state_out}

def spice_extraction_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ⚡ Agent 18: SPICE Extraction")
    st.write("Extracts a SPICE netlist from the final GDSII layout. This is needed for the LVS check.")
    SpiceExtraction = Step.factory.get("Magic.SpiceExtraction")
    spx_step = SpiceExtraction(config=state["config"], state_in=state["drc_state_out"])
    spx_step.start()
    return {"spice_extraction_state_out": spx_step.state_out}

def lvs_agent(state: AgentState) -> Dict[str, Any]:
    st.write("---")
    st.write("### ↔️ Agent 19: Layout vs. Schematic (LVS)")
    st.write("Compares the extracted SPICE netlist (from the layout) against the original Verilog netlist to ensure they match.")
    LVS = Step.factory.get("Netgen.LVS")
    lvs_step = LVS(config=state["config"], state_in=state["spice_extraction_state_out"])
    lvs_step.start()
    st.write("#### LVS Report Summary")
    report_path = os.path.join(lvs_step.step_dir, "reports", "lvs.netgen.rpt")
    try:
        with open(report_path) as f:
            content = f.read()
            summary_match = re.search(r"Subcircuit summary:(.*?)Final result:", content, re.DOTALL)
            final_result_match = re.search(r"Final result:\s*(.*)", content)
            if summary_match: st.text(summary_match.group(1).strip())
            if final_result_match:
                result = final_result_match.group(1).strip()
                if "Circuits match uniquely" in result: st.success(f"✅ **Final Result:** {result}")
                else: st.error(f"❌ **Final Result:** {result}")
            else: st.warning("Could not parse LVS final result.")
    except FileNotFoundError: st.warning("LVS report file not found.")
    return {"lvs_state_out": lvs_step.state_out}

# RENDER AGENT (Generic)
def render_step_image(state: AgentState, state_key_in: str, caption: str):
    st.write(f"### 🖼️ Rendering: {caption}")
    Render = Step.factory.get("KLayout.Render")
    render_step = Render(config=state["config"], state_in=state[state_key_in])
    render_step.start()
    image_path = os.path.join(render_step.step_dir, "out.png")
    if os.path.exists(image_path):
        st.image(image_path, caption=caption, width=400)
    else:
        st.warning(f"Image not found for {caption} at: {image_path}")
    return {}

# Build the graph
workflow = StateGraph(AgentState)
nodes = [
    ("file_processing", file_processing_agent), ("setup", setup_agent),
    ("synthesis", synthesis_agent), ("floorplan", floorplan_agent),
    ("render_floorplan", lambda s: render_step_image(s, "floorplan_state_out", "Floorplan")),
    ("tap_endcap", tap_endcap_agent),
    ("render_tap_endcap", lambda s: render_step_image(s, "tap_endcap_state_out", "Tap/Endcap Insertion")),
    ("io_placement", io_placement_agent),
    ("render_io", lambda s: render_step_image(s, "io_placement_state_out", "I/O Placement")),
    ("generate_pdn", generate_pdn_agent),
    ("render_pdn", lambda s: render_step_image(s, "pdn_state_out", "PDN")),
    ("global_placement", global_placement_agent),
    ("render_global_placement", lambda s: render_step_image(s, "global_placement_state_out", "Global Placement")),
    ("detailed_placement", detailed_placement_agent),
    ("render_detailed_placement", lambda s: render_step_image(s, "detailed_placement_state_out", "Detailed Placement")),
    ("cts", cts_agent),
    ("render_cts", lambda s: render_step_image(s, "cts_state_out", "Clock Tree Synthesis")),
    ("global_routing", global_routing_agent),
    ("detailed_routing", detailed_routing_agent),
    ("render_detailed_routing", lambda s: render_step_image(s, "detailed_routing_state_out", "Detailed Routing")),
    ("fill_insertion", fill_insertion_agent),
    ("render_fill", lambda s: render_step_image(s, "fill_insertion_state_out", "Fill Insertion")),
    ("rcx", rcx_agent),
    ("sta", sta_agent),
    ("stream_out", stream_out_agent),
    ("render_gds", lambda s: render_step_image(s, "stream_out_state_out", "Final GDSII Layout")),
    ("drc", drc_agent),
    ("spice_extraction", spice_extraction_agent),
    ("lvs", lvs_agent)
]
for name, node in nodes:
    workflow.add_node(name, node)

# Define the sequential flow
chain = [
    "file_processing", "setup", "synthesis", "floorplan", "render_floorplan",
    "tap_endcap", "render_tap_endcap", "io_placement", "render_io",
    "generate_pdn", "render_pdn", "global_placement", "render_global_placement",
    "detailed_placement", "render_detailed_placement", "cts", "render_cts",
    "global_routing", "detailed_routing", "render_detailed_routing",
    "fill_insertion", "render_fill", "rcx", "sta",
    "stream_out", "render_gds", "drc", "spice_extraction", "lvs"
]
workflow.add_edge(START, chain[0])
for i in range(len(chain) - 1):
    workflow.add_edge(chain[i], chain[i+1])
workflow.add_edge(chain[-1], END)

app = workflow.compile()

# --- Streamlit UI ---
st.set_page_config(layout="wide")
st.title("🤖 LLM for Chip Design Automation")
st.write("Welcome! This application uses an agentic AI to guide you through the full ASIC PnR flow using OpenLane 2.")

st.write("### Agentic Workflow Graph")
st.graphviz_chart(
    """
    digraph {
        graph [splines=ortho, nodesep=0.4, ranksep=0.8];
        node [shape=box, style="rounded,filled", fillcolor="#a9def9", width=2, height=0.5, fontsize=10];
        edge [color="#555555", arrowhead=vee];

        // Define Ranks for horizontal layout
        { rank=same; prep_1; prep_2; prep_3; }
        { rank=same; fp_1; fp_2; fp_3; fp_4;}
        { rank=same; place_1; place_2; place_3;}
        { rank=same; route_1; route_2; route_3;}
        { rank=same; signoff_1; signoff_2; signoff_3; signoff_4; signoff_5;}

        // Nodes
        prep_1 [label="File Processing"];
        prep_2 [label="Setup"];
        prep_3 [label="Synthesis"];
        
        fp_1 [label="Floorplanning"];
        fp_2 [label="Tap/Endcap"];
        fp_3 [label="I/O Placement"];
        fp_4 [label="PDN"];
        
        place_1 [label="Global Placement"];
        place_2 [label="Detailed Placement"];
        place_3 [label="CTS"];
        
        route_1 [label="Global Routing"];
        route_2 [label="Detailed Routing"];
        route_3 [label="Fill Insertion"];

        signoff_1 [label="Stream Out (GDS)"];
        signoff_2 [label="RCX"];
        signoff_3 [label="STA"];
        signoff_4 [label="DRC"];
        signoff_5 [label="LVS"];

        // Edges
        prep_1 -> prep_2 -> prep_3 -> fp_1;
        fp_1 -> fp_2 -> fp_3 -> fp_4 -> place_1;
        place_1 -> place_2 -> place_3 -> route_1;
        route_1 -> route_2 -> route_3 -> signoff_1;
        signoff_1 -> signoff_2 -> signoff_3 -> signoff_4 -> signoff_5;
    }
    """
)

st.sidebar.header("1. Upload Your Files")
uploaded_files = st.sidebar.file_uploader(
    "Upload your Verilog files (.v, .vh)", accept_multiple_files=True
)

if uploaded_files:
    verilog_file_names = [f.name for f in uploaded_files if f.name.endswith(".v")]
    top_level_module = st.sidebar.selectbox(
        "Select the top-level module",
        options=[name.replace(".v", "") for name in verilog_file_names],
    )

    if st.sidebar.button("🚀 Run Agentic Flow"):
        original_cwd = os.getcwd()
        try:
            with st.spinner("🚀 Agents at work... This flow is long and will take several minutes."):
                initial_state = { "uploaded_files": uploaded_files, "top_level_module": top_level_module }
                app.invoke(initial_state, {"recursion_limit": 100})
            st.success("✅ Agentic flow completed successfully!")
        except Exception as e:
            st.error(f"An error occurred during the flow: {e}")
            import traceback
            st.code(traceback.format_exc())
        finally:
            os.chdir(original_cwd)
            st.write(f"✅ Restored working directory to: `{os.getcwd()}`")

# === chipster/notebooks/glayout_autolayout.ipynb ===
import os
from pathlib import Path
import sys

# ==============================================================================
# Set up the PDK Environment
# ==============================================================================
def setup_pdk_environment():
    """
    Sets the PDK_ROOT environment variable so glayout can find the PDKs.
    """
    # Define the path to your volare-managed PDKs
    pdk_root_path = "~/.volare"
    
    # Expand the user home directory (e.g., '~') to get the full path
    pdk_root_expanded = Path(pdk_root_path).expanduser()

    # Check if the volare directory actually exists
    if not pdk_root_expanded.is_dir():
        print(f"❌ ERROR: The specified PDK_ROOT path does not exist.")
        print(f"   Checked Path: {pdk_root_expanded}")
        print(f"   Please ensure volare is installed and has downloaded PDKs.")
        sys.exit(1)

    # Set the environment variable. This is the crucial step.
    os.environ['PDK_ROOT'] = str(pdk_root_expanded)
    print(f"✅ PDK_ROOT set to: {os.environ['PDK_ROOT']}")

# --- Run the setup function immediately ---
setup_pdk_environment()
# ---
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
# ---
def currentMirror(pdk):
  currMirrComp = Component()
  pfet_ref = pmos(pdk, with_substrate_tap=False, with_dummy=(False, True))
  pfet_mir = pmos(pdk, with_substrate_tap=False, with_dummy=(True, False))
  cref_ref = currMirrComp << pfet_ref
  cmir_ref = currMirrComp << pfet_mir
  pdk.util_max_metal_seperation()
  cref_ref.movex(evaluate_bbox(pfet_mir)[0] + pdk.util_max_metal_seperation())
  tap_ring = tapring(pdk, enclosed_rectangle=evaluate_bbox(currMirrComp.flatten(), padding=pdk.get_grule("nwell", "active_diff")["min_enclosure"]))
  shift_amount = -prec_center(currMirrComp.flatten())[0]
  tring_ref = currMirrComp << tap_ring
  tring_ref.movex(destination=shift_amount)
  currMirrComp << straight_route(pdk, cref_ref.ports["multiplier_0_source_E"], cmir_ref.ports["multiplier_0_source_E"])
  currMirrComp << straight_route(pdk, cref_ref.ports["multiplier_0_gate_E"], cmir_ref.ports["multiplier_0_gate_E"])
  currMirrComp << c_route(pdk, cref_ref.ports["multiplier_0_gate_E"], cref_ref.ports["multiplier_0_drain_E"])
  return currMirrComp

currentMirror(gf180).write_gds("cmirror_example.gds")
display_gds("cmirror_example.gds")

# === chipster/notebooks/openlane2_flow_tutorial.ipynb ===
%%writefile fixed_point_params.vh

//
// fixed_point_params.vh
// Defines the fixed-point data type for the QFT project.
//

// Total bits for our signed fixed-point number
`define TOTAL_WIDTH 8

// Number of fractional bits
`define FRAC_WIDTH 4

// Width for intermediate multiplication results (before scaling)
`define MULT_WIDTH (`TOTAL_WIDTH * 2)

// Width for intermediate addition results
`define ADD_WIDTH (`TOTAL_WIDTH + 1)

# ---
%%writefile qft3_top_pipelined.v

`include "fixed_point_params.vh"

//======================================================================
// 3-Qubit QFT Top Level (Corrected and Optimized)
//======================================================================
module qft3_top_pipelined(
    input clk,
    input rst_n,

    // Initial 3-qubit state vector [α000, ..., α111]
    input  signed [`TOTAL_WIDTH-1:0] i000_r, i000_i, i001_r, i001_i, i010_r, i010_i, i011_r, i011_i,
    input  signed [`TOTAL_WIDTH-1:0] i100_r, i100_i, i101_r, i101_i, i110_r, i110_i, i111_r, i111_i,

    // Final state vector after the QFT
    output signed [`TOTAL_WIDTH-1:0] f000_r, f000_i, f001_r, f001_i, f010_r, f010_i, f011_r, f011_i,
    output signed [`TOTAL_WIDTH-1:0] f100_r, f100_i, f101_r, f101_i, f110_r, f110_i, f111_r, f111_i
);

    // --- CORRECTED Pre-calculated Rotation Constants ---
    // For theta = pi/2: cos=0, sin=1.0
    localparam signed [`TOTAL_WIDTH-1:0] C_PI_2_R = 0;  // <-- THE FIX
    localparam signed [`TOTAL_WIDTH-1:0] C_PI_2_I = 16;
    // For theta = pi/4: cos=0.707, sin=0.707
    localparam signed [`TOTAL_WIDTH-1:0] C_PI_4_R = 11;
    localparam signed [`TOTAL_WIDTH-1:0] C_PI_4_I = 11;

    // --- Latency Definition ---
    localparam STAGE_LATENCY = 3;

    // --- Intermediate Wires for Pipeline Stages ---
    wire signed [`TOTAL_WIDTH-1:0] s1_r[0:7], s1_i[0:7];
    wire signed [`TOTAL_WIDTH-1:0] s2_r[0:7], s2_i[0:7];
    wire signed [`TOTAL_WIDTH-1:0] s3_r[0:7], s3_i[0:7];
    wire signed [`TOTAL_WIDTH-1:0] s4_r[0:7], s4_i[0:7];
    wire signed [`TOTAL_WIDTH-1:0] s5_r[0:7], s5_i[0:7];
    wire signed [`TOTAL_WIDTH-1:0] s6_r[0:7], s6_i[0:7];

    integer i, j;

    // --- STAGE 1: H on q2 (bit 2) --- Latency: 3 ---
    h_gate_simplified h_q2_p0 (.clk(clk), .rst_n(rst_n), .alpha_r(i000_r), .alpha_i(i000_i), .beta_r(i100_r), .beta_i(i100_i), .new_alpha_r(s1_r[0]), .new_alpha_i(s1_i[0]), .new_beta_r(s1_r[4]), .new_beta_i(s1_i[4]));
    h_gate_simplified h_q2_p1 (.clk(clk), .rst_n(rst_n), .alpha_r(i001_r), .alpha_i(i001_i), .beta_r(i101_r), .beta_i(i101_i), .new_alpha_r(s1_r[1]), .new_alpha_i(s1_i[1]), .new_beta_r(s1_r[5]), .new_beta_i(s1_i[5]));
    h_gate_simplified h_q2_p2 (.clk(clk), .rst_n(rst_n), .alpha_r(i010_r), .alpha_i(i010_i), .beta_r(i110_r), .beta_i(i110_i), .new_alpha_r(s1_r[2]), .new_alpha_i(s1_i[2]), .new_beta_r(s1_r[6]), .new_beta_i(s1_i[6]));
    h_gate_simplified h_q2_p3 (.clk(clk), .rst_n(rst_n), .alpha_r(i011_r), .alpha_i(i011_i), .beta_r(i111_r), .beta_i(i111_i), .new_alpha_r(s1_r[3]), .new_alpha_i(s1_i[3]), .new_beta_r(s1_r[7]), .new_beta_i(s1_i[7]));

    // --- STAGE 2: CROT(π/2) from q1 to q2 --- Latency: 3 ---
    ccmult_pipelined c21_p0 (.clk(clk), .rst_n(rst_n), .ar(s1_r[6]), .ai(s1_i[6]), .br(C_PI_2_R), .bi(C_PI_2_I), .pr(s2_r[6]), .pi(s2_i[6]));
    ccmult_pipelined c21_p1 (.clk(clk), .rst_n(rst_n), .ar(s1_r[7]), .ai(s1_i[7]), .br(C_PI_2_R), .bi(C_PI_2_I), .pr(s2_r[7]), .pi(s2_i[7]));
    // Pass-through with 3-cycle delay
    reg signed [`TOTAL_WIDTH-1:0] s1_passthru_s2_r [0:5][STAGE_LATENCY-1:0];
    reg signed [`TOTAL_WIDTH-1:0] s1_passthru_s2_i [0:5][STAGE_LATENCY-1:0];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) for(j=0;j<6;j=j+1) for(i=0;i<STAGE_LATENCY;i=i+1) {s1_passthru_s2_r[j][i],s1_passthru_s2_i[j][i]} <= 0;
        else begin
            {s1_passthru_s2_r[0][0],s1_passthru_s2_i[0][0]} <= {s1_r[0],s1_i[0]}; {s1_passthru_s2_r[1][0],s1_passthru_s2_i[1][0]} <= {s1_r[1],s1_i[1]};
            {s1_passthru_s2_r[2][0],s1_passthru_s2_i[2][0]} <= {s1_r[2],s1_i[2]}; {s1_passthru_s2_r[3][0],s1_passthru_s2_i[3][0]} <= {s1_r[3],s1_i[3]};
            {s1_passthru_s2_r[4][0],s1_passthru_s2_i[4][0]} <= {s1_r[4],s1_i[4]}; {s1_passthru_s2_r[5][0],s1_passthru_s2_i[5][0]} <= {s1_r[5],s1_i[5]};
            for(j=0;j<6;j=j+1) for(i=1;i<STAGE_LATENCY;i=i+1) {s1_passthru_s2_r[j][i],s1_passthru_s2_i[j][i]} <= {s1_passthru_s2_r[j][i-1],s1_passthru_s2_i[j][i-1]};
        end
    end
    assign {s2_r[0],s2_i[0]}={s1_passthru_s2_r[0][STAGE_LATENCY-1],s1_passthru_s2_i[0][STAGE_LATENCY-1]}; assign {s2_r[1],s2_i[1]}={s1_passthru_s2_r[1][STAGE_LATENCY-1],s1_passthru_s2_i[1][STAGE_LATENCY-1]};
    assign {s2_r[2],s2_i[2]}={s1_passthru_s2_r[2][STAGE_LATENCY-1],s1_passthru_s2_i[2][STAGE_LATENCY-1]}; assign {s2_r[3],s2_i[3]}={s1_passthru_s2_r[3][STAGE_LATENCY-1],s1_passthru_s2_i[3][STAGE_LATENCY-1]};
    assign {s2_r[4],s2_i[4]}={s1_passthru_s2_r[4][STAGE_LATENCY-1],s1_passthru_s2_i[4][STAGE_LATENCY-1]}; assign {s2_r[5],s2_i[5]}={s1_passthru_s2_r[5][STAGE_LATENCY-1],s1_passthru_s2_i[5][STAGE_LATENCY-1]};

    // --- STAGE 3: CROT(π/4) from q0 to q2 --- Latency: 3 ---
    ccmult_pipelined c20_p0 (.clk(clk), .rst_n(rst_n), .ar(s2_r[5]), .ai(s2_i[5]), .br(C_PI_4_R), .bi(C_PI_4_I), .pr(s3_r[5]), .pi(s3_i[5]));
    ccmult_pipelined c20_p1 (.clk(clk), .rst_n(rst_n), .ar(s2_r[7]), .ai(s2_i[7]), .br(C_PI_4_R), .bi(C_PI_4_I), .pr(s3_r[7]), .pi(s3_i[7]));
    // Pass-through with 3-cycle delay
    reg signed [`TOTAL_WIDTH-1:0] s2_passthru_s3_r [0:5][STAGE_LATENCY-1:0];
    reg signed [`TOTAL_WIDTH-1:0] s2_passthru_s3_i [0:5][STAGE_LATENCY-1:0];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) for(j=0;j<6;j=j+1) for(i=0;i<STAGE_LATENCY;i=i+1) {s2_passthru_s3_r[j][i],s2_passthru_s3_i[j][i]} <= 0;
        else begin
            {s2_passthru_s3_r[0][0],s2_passthru_s3_i[0][0]} <= {s2_r[0],s2_i[0]}; {s2_passthru_s3_r[1][0],s2_passthru_s3_i[1][0]} <= {s2_r[1],s2_i[1]};
            {s2_passthru_s3_r[2][0],s2_passthru_s3_i[2][0]} <= {s2_r[2],s2_i[2]}; {s2_passthru_s3_r[3][0],s2_passthru_s3_i[3][0]} <= {s2_r[3],s2_i[3]};
            {s2_passthru_s3_r[4][0],s2_passthru_s3_i[4][0]} <= {s2_r[4],s2_i[4]}; {s2_passthru_s3_r[5][0],s2_passthru_s3_i[5][0]} <= {s2_r[6],s2_i[6]};
            for(j=0;j<6;j=j+1) for(i=1;i<STAGE_LATENCY;i=i+1) {s2_passthru_s3_r[j][i],s2_passthru_s3_i[j][i]} <= {s2_passthru_s3_r[j][i-1],s2_passthru_s3_i[j][i-1]};
        end
    end
    assign {s3_r[0],s3_i[0]}={s2_passthru_s3_r[0][STAGE_LATENCY-1],s2_passthru_s3_i[0][STAGE_LATENCY-1]}; assign {s3_r[1],s3_i[1]}={s2_passthru_s3_r[1][STAGE_LATENCY-1],s2_passthru_s3_i[1][STAGE_LATENCY-1]};
    assign {s3_r[2],s3_i[2]}={s2_passthru_s3_r[2][STAGE_LATENCY-1],s2_passthru_s3_i[2][STAGE_LATENCY-1]}; assign {s3_r[3],s3_i[3]}={s2_passthru_s3_r[3][STAGE_LATENCY-1],s2_passthru_s3_i[3][STAGE_LATENCY-1]};
    assign {s3_r[4],s3_i[4]}={s2_passthru_s3_r[4][STAGE_LATENCY-1],s2_passthru_s3_i[4][STAGE_LATENCY-1]}; assign {s3_r[6],s3_i[6]}={s2_passthru_s3_r[5][STAGE_LATENCY-1],s2_passthru_s3_i[5][STAGE_LATENCY-1]};

    // --- STAGE 4: H on q1 (bit 1) --- Latency: 3 ---
    h_gate_simplified h_q1_p0 (.clk(clk), .rst_n(rst_n), .alpha_r(s3_r[0]), .alpha_i(s3_i[0]), .beta_r(s3_r[2]), .beta_i(s3_i[2]), .new_alpha_r(s4_r[0]), .new_alpha_i(s4_i[0]), .new_beta_r(s4_r[2]), .new_beta_i(s4_i[2]));
    h_gate_simplified h_q1_p1 (.clk(clk), .rst_n(rst_n), .alpha_r(s3_r[1]), .alpha_i(s3_i[1]), .beta_r(s3_r[3]), .beta_i(s3_i[3]), .new_alpha_r(s4_r[1]), .new_alpha_i(s4_i[1]), .new_beta_r(s4_r[3]), .new_beta_i(s4_i[3]));
    h_gate_simplified h_q1_p2 (.clk(clk), .rst_n(rst_n), .alpha_r(s3_r[4]), .alpha_i(s3_i[4]), .beta_r(s3_r[6]), .beta_i(s3_i[6]), .new_alpha_r(s4_r[4]), .new_alpha_i(s4_i[4]), .new_beta_r(s4_r[6]), .new_beta_i(s4_i[6]));
    h_gate_simplified h_q1_p3 (.clk(clk), .rst_n(rst_n), .alpha_r(s3_r[5]), .alpha_i(s3_i[5]), .beta_r(s3_r[7]), .beta_i(s3_i[7]), .new_alpha_r(s4_r[5]), .new_alpha_i(s4_i[5]), .new_beta_r(s4_r[7]), .new_beta_i(s4_i[7]));

    // --- STAGE 5: CROT(π/2) from q0 to q1 --- Latency: 3 ---
    ccmult_pipelined c10_p0 (.clk(clk), .rst_n(rst_n), .ar(s4_r[3]), .ai(s4_i[3]), .br(C_PI_2_R), .bi(C_PI_2_I), .pr(s5_r[3]), .pi(s5_i[3]));
    ccmult_pipelined c10_p1 (.clk(clk), .rst_n(rst_n), .ar(s4_r[7]), .ai(s4_i[7]), .br(C_PI_2_R), .bi(C_PI_2_I), .pr(s5_r[7]), .pi(s5_i[7]));
    // Pass-through with 3-cycle delay
    reg signed [`TOTAL_WIDTH-1:0] s4_passthru_s5_r [0:5][STAGE_LATENCY-1:0];
    reg signed [`TOTAL_WIDTH-1:0] s4_passthru_s5_i [0:5][STAGE_LATENCY-1:0];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) for(j=0;j<6;j=j+1) for(i=0;i<STAGE_LATENCY;i=i+1) {s4_passthru_s5_r[j][i],s4_passthru_s5_i[j][i]} <= 0;
        else begin
            {s4_passthru_s5_r[0][0],s4_passthru_s5_i[0][0]} <= {s4_r[0],s4_i[0]}; {s4_passthru_s5_r[1][0],s4_passthru_s5_i[1][0]} <= {s4_r[1],s4_i[1]};
            {s4_passthru_s5_r[2][0],s4_passthru_s5_i[2][0]} <= {s4_r[2],s4_i[2]}; {s4_passthru_s5_r[3][0],s4_passthru_s5_i[3][0]} <= {s4_r[4],s4_i[4]};
            {s4_passthru_s5_r[4][0],s4_passthru_s5_i[4][0]} <= {s4_r[5],s4_i[5]}; {s4_passthru_s5_r[5][0],s4_passthru_s5_i[5][0]} <= {s4_r[6],s4_i[6]};
            for(j=0;j<6;j=j+1) for(i=1;i<STAGE_LATENCY;i=i+1) {s4_passthru_s5_r[j][i],s4_passthru_s5_i[j][i]} <= {s4_passthru_s5_r[j][i-1],s4_passthru_s5_i[j][i-1]};
        end
    end
    assign {s5_r[0],s5_i[0]}={s4_passthru_s5_r[0][STAGE_LATENCY-1],s4_passthru_s5_i[0][STAGE_LATENCY-1]}; assign {s5_r[1],s5_i[1]}={s4_passthru_s5_r[1][STAGE_LATENCY-1],s4_passthru_s5_i[1][STAGE_LATENCY-1]};
    assign {s5_r[2],s5_i[2]}={s4_passthru_s5_r[2][STAGE_LATENCY-1],s4_passthru_s5_i[2][STAGE_LATENCY-1]}; assign {s5_r[4],s5_i[4]}={s4_passthru_s5_r[3][STAGE_LATENCY-1],s4_passthru_s5_i[3][STAGE_LATENCY-1]};
    assign {s5_r[5],s5_i[5]}={s4_passthru_s5_r[4][STAGE_LATENCY-1],s4_passthru_s5_i[4][STAGE_LATENCY-1]}; assign {s5_r[6],s5_i[6]}={s4_passthru_s5_r[5][STAGE_LATENCY-1],s4_passthru_s5_i[5][STAGE_LATENCY-1]};

    // --- STAGE 6: H on q0 (bit 0) --- Latency: 3 ---
    h_gate_simplified h_q0_p0 (.clk(clk), .rst_n(rst_n), .alpha_r(s5_r[0]), .alpha_i(s5_i[0]), .beta_r(s5_r[1]), .beta_i(s5_i[1]), .new_alpha_r(s6_r[0]), .new_alpha_i(s6_i[0]), .new_beta_r(s6_r[1]), .new_beta_i(s6_i[1]));
    h_gate_simplified h_q0_p1 (.clk(clk), .rst_n(rst_n), .alpha_r(s5_r[2]), .alpha_i(s5_i[2]), .beta_r(s5_r[3]), .beta_i(s5_i[3]), .new_alpha_r(s6_r[2]), .new_alpha_i(s6_i[2]), .new_beta_r(s6_r[3]), .new_beta_i(s6_i[3]));
    h_gate_simplified h_q0_p2 (.clk(clk), .rst_n(rst_n), .alpha_r(s5_r[4]), .alpha_i(s5_i[4]), .beta_r(s5_r[5]), .beta_i(s5_i[5]), .new_alpha_r(s6_r[4]), .new_alpha_i(s6_i[4]), .new_beta_r(s6_r[5]), .new_beta_i(s6_i[5]));
    h_gate_simplified h_q0_p3 (.clk(clk), .rst_n(rst_n), .alpha_r(s5_r[6]), .alpha_i(s5_i[6]), .beta_r(s5_r[7]), .beta_i(s5_i[7]), .new_alpha_r(s6_r[6]), .new_alpha_i(s6_i[6]), .new_beta_r(s6_r[7]), .new_beta_i(s6_i[7]));

    // --- STAGE 7: SWAP q0 and q2 (Bit Reversal) --- Latency: 1 ---
    swap_gate_pipelined final_swap (
        .clk(clk), .rst_n(rst_n),
        .in_001_r(s6_r[1]), .in_001_i(s6_i[1]), .in_100_r(s6_r[4]), .in_100_i(s6_i[4]),
        .in_011_r(s6_r[3]), .in_011_i(s6_i[3]), .in_110_r(s6_r[6]), .in_110_i(s6_i[6]),
        .out_001_r(f001_r), .out_001_i(f001_i),
        .out_100_r(f100_r), .out_100_i(f100_i),
        .out_011_r(f011_r), .out_011_i(f011_i),
        .out_110_r(f110_r), .out_110_i(f110_i)
    );
    // Pass-through the amplitudes not affected by swap, with a 1-cycle delay to match SWAP latency.
    reg signed [`TOTAL_WIDTH-1:0] f000_r_reg, f000_i_reg;
    reg signed [`TOTAL_WIDTH-1:0] f010_r_reg, f010_i_reg;
    reg signed [`TOTAL_WIDTH-1:0] f101_r_reg, f101_i_reg;
    reg signed [`TOTAL_WIDTH-1:0] f111_r_reg, f111_i_reg;

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            {f000_r_reg, f000_i_reg} <= 0; {f010_r_reg, f010_i_reg} <= 0;
            {f101_r_reg, f101_i_reg} <= 0; {f111_r_reg, f111_i_reg} <= 0;
        end else begin
            {f000_r_reg, f000_i_reg} <= {s6_r[0], s6_i[0]};
            {f010_r_reg, f010_i_reg} <= {s6_r[2], s6_i[2]};
            {f101_r_reg, f101_i_reg} <= {s6_r[5], s6_i[5]};
            {f111_r_reg, f111_i_reg} <= {s6_r[7], s6_i[7]};
        end
    end

    assign f000_r = f000_r_reg; assign f000_i = f000_i_reg;
    assign f010_r = f010_r_reg; assign f010_i = f010_i_reg;
    assign f101_r = f101_r_reg; assign f101_i = f101_i_reg;
    assign f111_r = f111_r_reg; assign f111_i = f111_i_reg;

endmodule

`include "fixed_point_params.vh"

//======================================================================
// Complex-Complex Multiplier (Pipelined)
//======================================================================
// This module is retained as it is used for the CROT gates.
// Latency: 3 cycles
module ccmult_pipelined(
    input                         clk,
    input                         rst_n,
    input  signed [`TOTAL_WIDTH-1:0] ar, ai,
    input  signed [`TOTAL_WIDTH-1:0] br, bi,
    output signed [`TOTAL_WIDTH-1:0] pr, pi
);

    // Pipeline Stage 1: multiplication
    reg signed [`MULT_WIDTH-1:0] p_ar_br_s1, p_ai_bi_s1, p_ar_bi_s1, p_ai_br_s1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            p_ar_br_s1 <= 0;
            p_ai_bi_s1 <= 0;
            p_ar_bi_s1 <= 0;
            p_ai_br_s1 <= 0;
        end else begin
            p_ar_br_s1 <= ar * br;
            p_ai_bi_s1 <= ai * bi;
            p_ar_bi_s1 <= ar * bi;
            p_ai_br_s1 <= ai * br;
        end
    end

    // Pipeline Stage 2: addition/subtraction
    reg signed [`MULT_WIDTH:0] real_sum_s2, imag_sum_s2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            real_sum_s2 <= 0;
            imag_sum_s2 <= 0;
        end else begin
            real_sum_s2 <= p_ar_br_s1 - p_ai_bi_s1;
            imag_sum_s2 <= p_ar_bi_s1 + p_ai_br_s1;
        end
    end

    // Pipeline Stage 3: scaling (output register)
    reg signed [`TOTAL_WIDTH-1:0] pr_s3, pi_s3;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pr_s3 <= 0;
            pi_s3 <= 0;
        end else begin
            pr_s3 <= real_sum_s2 >>> `FRAC_WIDTH;
            pi_s3 <= imag_sum_s2 >>> `FRAC_WIDTH;
        end
    end
    
    assign pr = pr_s3;
    assign pi = pi_s3;
    
endmodule


`include "fixed_point_params.vh"

//======================================================================
// Simplified Hadamard Gate (Corrected and Pipelined)
//======================================================================
module h_gate_simplified(
    input                         clk,
    input                         rst_n,
    input  signed [`TOTAL_WIDTH-1:0] alpha_r, alpha_i,
    input  signed [`TOTAL_WIDTH-1:0] beta_r,  beta_i,
    output signed [`TOTAL_WIDTH-1:0] new_alpha_r, new_alpha_i,
    output signed [`TOTAL_WIDTH-1:0] new_beta_r,  new_beta_i
);

    // S3.4 constant for 1/sqrt(2)
    localparam signed [`TOTAL_WIDTH-1:0] ONE_OVER_SQRT2 = 11;

    // --- Pipeline Stage 1: Addition/Subtraction ---
    reg signed [`ADD_WIDTH-1:0] add_r_s1, add_i_s1;
    reg signed [`ADD_WIDTH-1:0] sub_r_s1, sub_i_s1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            add_r_s1 <= 0; add_i_s1 <= 0;
            sub_r_s1 <= 0; sub_i_s1 <= 0;
        end else begin
            add_r_s1 <= alpha_r + beta_r;
            add_i_s1 <= alpha_i + beta_i;
            sub_r_s1 <= alpha_r - beta_r;
            sub_i_s1 <= alpha_i - beta_i;
        end
    end

    // --- Pipeline Stage 2: Multiplication by 1/sqrt(2) ---
    // Define a wider intermediate product width to prevent overflow
    localparam H_MULT_WIDTH = `ADD_WIDTH + `TOTAL_WIDTH;
    reg signed [H_MULT_WIDTH-1:0] mult_add_r_s2, mult_add_i_s2;
    reg signed [H_MULT_WIDTH-1:0] mult_sub_r_s2, mult_sub_i_s2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mult_add_r_s2 <= 0; mult_add_i_s2 <= 0;
            mult_sub_r_s2 <= 0; mult_sub_i_s2 <= 0;
        end else begin
            // --- THE FIX ---
            // Perform multiplication on the FULL 9-bit adder result to prevent overflow.
            mult_add_r_s2 <= add_r_s1 * ONE_OVER_SQRT2;
            mult_add_i_s2 <= add_i_s1 * ONE_OVER_SQRT2;
            mult_sub_r_s2 <= sub_r_s1 * ONE_OVER_SQRT2;
            mult_sub_i_s2 <= sub_i_s1 * ONE_OVER_SQRT2;
        end
    end

    // --- Pipeline Stage 3: Scaling (Output) ---
    reg signed [`TOTAL_WIDTH-1:0] new_alpha_r_s3, new_alpha_i_s3;
    reg signed [`TOTAL_WIDTH-1:0] new_beta_r_s3,  new_beta_i_s3;
    
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            new_alpha_r_s3 <= 0; new_alpha_i_s3 <= 0;
            new_beta_r_s3  <= 0; new_beta_i_s3  <= 0;
        end else begin
            // Scale the wider product back down to the target width
            new_alpha_r_s3 <= mult_add_r_s2 >>> `FRAC_WIDTH;
            new_alpha_i_s3 <= mult_add_i_s2 >>> `FRAC_WIDTH;
            new_beta_r_s3  <= mult_sub_r_s2 >>> `FRAC_WIDTH;
            new_beta_i_s3  <= mult_sub_i_s2 >>> `FRAC_WIDTH;
        end
    end
    
    assign new_alpha_r = new_alpha_r_s3;
    assign new_alpha_i = new_alpha_i_s3;
    assign new_beta_r  = new_beta_r_s3;
    assign new_beta_i  = new_beta_i_s3;
    
endmodule


`include "fixed_point_params.vh"

//======================================================================
// SWAP Gate (Pipelined)
//======================================================================
// This module is retained as-is.
// Latency: 1 cycle
module swap_gate_pipelined(
    input                         clk,
    input                         rst_n,
    input  signed [`TOTAL_WIDTH-1:0] in_001_r, in_001_i,
    input  signed [`TOTAL_WIDTH-1:0] in_100_r, in_100_i,
    input  signed [`TOTAL_WIDTH-1:0] in_011_r, in_011_i,
    input  signed [`TOTAL_WIDTH-1:0] in_110_r, in_110_i,
    output signed [`TOTAL_WIDTH-1:0] out_001_r, out_001_i,
    output signed [`TOTAL_WIDTH-1:0] out_100_r, out_100_i,
    output signed [`TOTAL_WIDTH-1:0] out_011_r, out_011_i,
    output signed [`TOTAL_WIDTH-1:0] out_110_r, out_110_i
);

    reg signed [`TOTAL_WIDTH-1:0] out_001_r_reg, out_001_i_reg;
    reg signed [`TOTAL_WIDTH-1:0] out_100_r_reg, out_100_i_reg;
    reg signed [`TOTAL_WIDTH-1:0] out_011_r_reg, out_011_i_reg;
    reg signed [`TOTAL_WIDTH-1:0] out_110_r_reg, out_110_i_reg;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_001_r_reg <= 0; out_001_i_reg <= 0;
            out_100_r_reg <= 0; out_100_i_reg <= 0;
            out_011_r_reg <= 0; out_011_i_reg <= 0;
            out_110_r_reg <= 0; out_110_i_reg <= 0;
        end else begin
            // Perform swaps
            out_001_r_reg <= in_100_r; out_001_i_reg <= in_100_i;
            out_100_r_reg <= in_001_r; out_100_i_reg <= in_001_i;
            out_011_r_reg <= in_110_r; out_011_i_reg <= in_110_i;
            out_110_r_reg <= in_011_r; out_110_i_reg <= in_011_i;
        end
    end

    assign out_001_r = out_001_r_reg;
    assign out_001_i = out_001_i_reg;
    assign out_100_r = out_100_r_reg;
    assign out_100_i = out_100_i_reg;
    assign out_011_r = out_011_r_reg;
    assign out_011_i = out_011_i_reg;
    assign out_110_r = out_110_r_reg;
    assign out_110_i = out_110_i_reg;

endmodule

# ---
from openlane.config import Config

Config.interactive(
    "qft3_top_pipelined_with_serial",
    PDK="gf180mcuC",
    CLOCK_PORT="clk",
    CLOCK_NET="clk",
    CLOCK_PERIOD=2000,
    PRIMARY_GDSII_STREAMOUT_TOOL="klayout",
)
# ---
Synthesis = Step.factory.get("Yosys.Synthesis")

Synthesis.display_help()
# ---
Floorplan = Step.factory.get("OpenROAD.Floorplan")

floorplan = Floorplan(state_in=synthesis.state_out)
floorplan.start()
# ---
TapEndcapInsertion = Step.factory.get("OpenROAD.TapEndcapInsertion")

tdi = TapEndcapInsertion(state_in=floorplan.state_out)
tdi.start()
# ---
IOPlacement = Step.factory.get("OpenROAD.IOPlacement")

ioplace = IOPlacement(state_in=tdi.state_out)
ioplace.start()
# ---
GeneratePDN = Step.factory.get("OpenROAD.GeneratePDN")

pdn = GeneratePDN(
    state_in=ioplace.state_out,
    FP_PDN_VWIDTH=2,
    FP_PDN_HWIDTH=2,
    FP_PDN_VPITCH=30,
    FP_PDN_HPITCH=30,
)
pdn.start()
# ---
GlobalPlacement = Step.factory.get("OpenROAD.GlobalPlacement")

gpl = GlobalPlacement(state_in=pdn.state_out)
gpl.start()
# ---
DetailedPlacement = Step.factory.get("OpenROAD.DetailedPlacement")

dpl = DetailedPlacement(state_in=gpl.state_out)
dpl.start()
# ---
CTS = Step.factory.get("OpenROAD.CTS")

cts = CTS(state_in=dpl.state_out)
cts.start()
# ---
GlobalRouting = Step.factory.get("OpenROAD.GlobalRouting")

grt = GlobalRouting(state_in=cts.state_out)
grt.start()
# ---
DetailedRouting = Step.factory.get("OpenROAD.DetailedRouting")

drt = DetailedRouting(state_in=grt.state_out)
drt.start()
# ---
FillInsertion = Step.factory.get("OpenROAD.FillInsertion")

fill = FillInsertion(state_in=drt.state_out)
fill.start()
# ---
RCX = Step.factory.get("OpenROAD.RCX")

rcx = RCX(state_in=fill.state_out)
rcx.start()
# ---
STAPostPNR = Step.factory.get("OpenROAD.STAPostPNR")

sta_post_pnr = STAPostPNR(state_in=rcx.state_out)
sta_post_pnr.start()
# ---
StreamOut = Step.factory.get("KLayout.StreamOut")

gds = StreamOut(state_in=sta_post_pnr.state_out)
gds.start()
# ---
DRC = Step.factory.get("Magic.DRC")

drc = DRC(state_in=gds.state_out)
drc.start()
# ---
SpiceExtraction = Step.factory.get("Magic.SpiceExtraction")

spx = SpiceExtraction(state_in=drc.state_out)
spx.start()
# ---
LVS = Step.factory.get("Netgen.LVS")

lvs = LVS(state_in=spx.state_out)
lvs.start()

# === chipster/notebooks/AMS_RF.ipynb ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Common-Source Amplifier with Resistor Load')
# Define the NMOS model with typical parameters
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V Vdd
# Input voltage source with bias above threshold to activate M1
circuit.V('in', 'Vin', circuit.gnd, "dc 1.0 ac 1n")
# Load resistor R
circuit.R('load', 'Vout', 'Vdd', 10@u_kΩ)  # 10kΩ resistor
# NMOS transistor M1
# Drain connected to Vout node
# Gate connected to Vin
# Source connected to ground
circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd,
               model='nmos_model', w=50e-6, l=1e-6)
# The circuit is now complete; the output is at Vout node
# No further code needed after this line
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p1_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Three-Stage Common-Source Amplifier with Proper Biasing')
# Define NMOS model parameters
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input voltage source
circuit.V('in', 'Vin', circuit.gnd, "dc 1.0 ac 1n")
# Bias voltage for drain of M1 (gate of M2)
circuit.V('bias_M2_gate', 'Bias_M2', 'Drain1', 2.0)  # 2V bias to ensure M2 is on
# Load resistors
R1_value = 10e3  # 10kΩ
R2_value = 10e3
R3_value = 10e3
# First stage: M1
circuit.MOSFET('M1', 'Drain1', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('R1', 'Drain1', 'Vdd', R1_value)
# Second stage: M2
circuit.MOSFET('M2', 'Drain2', 'Bias_M2', 'Drain1', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('R2', 'Drain2', 'Vdd', R2_value)
# Third stage: M3
circuit.MOSFET('M3', 'Vout', 'Drain2', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('R3', 'Vout', 'Vdd', R3_value)
# Simulation setup
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p2_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('Common-Drain Source Follower')
# MOSFET models
circuit.model('nmos', 'nmos', level=1, vto=0.5, kp=100e-6)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input voltage
circuit.V('in', 'Vin', circuit.gnd, "dc 1.0 ac 1n")
# Load resistor R at the source
circuit.R('load', 'Vout', circuit.gnd, 10@u_kΩ)
# NMOS transistor M1: source follower
# Sequence: name, drain, gate, source, bulk, model, w, l
circuit.MOSFET('M1', 'Vdd', 'Vin', 'Vout', 'Vout', model='nmos', w=50e-6, l=1e-6)
# Note: bulk connected to source (Vout)
# For simplicity, bulk is connected to source node in the MOSFET definition

simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p3_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('Single-Stage Common-Gate Amplifier')
# Define NMOS model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V supply
# Bias voltage at gate to set the bias point
circuit.V('bias', 'Vbias', circuit.gnd, 2.0)  # Higher bias voltage to ensure V_GS > V_TH
# Input signal at source (Vin)
# During simulation, Vin will be a time-varying source or DC value
# Here, for operating point, we can set a DC value, say 0.5V
# For transient analysis, a voltage source with AC or waveform can be used
# For now, set a DC value for initial operating point
circuit.V('in', 'Vin', circuit.gnd, "dc 0.5 ac 1n")
# Device: M1 (NMOS)
# Drain connected to Vdd through Rload
# Gate connected to Vbias
# Source connected to Vin
W = 50e-6
L = 1e-6
circuit.MOSFET('M1', 'Vout', 'Vbias', 'Vin', 'Vin', model='nmos_model', w=W, l=L)
# Load resistor at drain
R_value = 10e3  # 10 kΩ
circuit.R('load', 'Vout', 'Vdd', R_value)
# Note: For operating point analysis, Vin is DC at 0.5V
# For transient analysis, replace 'Vin' with a time-dependent source
# Initialize simulator
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p4_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Create the circuit
circuit = Circuit('Single-Stage Cascode NMOS Amplifier')
# Define NMOS model
circuit.model('nmos', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Biasing voltages
# Increase bias voltage for M2 to ensure it's active
circuit.V('Vbias', 'Vbias', circuit.gnd, 3.0)  # Bias voltage for cascode transistor
# Increase Vin to ensure M1 is in saturation
circuit.V('Vin', 'Vin', circuit.gnd, "dc 1.5 ac 1n")
# Load resistor R
circuit.R('load', 'Vout', 'Vdd', 10@u_kΩ)  # 10kΩ load resistor
# Transistor M1: Main amplifying NMOS
# Drain node is 'Drain_M1'
circuit.MOSFET('M1', 'Drain_M1', 'Vin', circuit.gnd, circuit.gnd, model='nmos', w=50e-6, l=1e-6)
# Transistor M2: Cascode NMOS
# Drain connected to Vout node, gate connected to Vbias
circuit.MOSFET('M2', 'Vout', 'Vbias', 'Drain_M1', 'Drain_M1', model='nmos', w=50e-6, l=1e-6)
# Connect drain of M2 to load resistor and Vdd
# Vout node is at drain of M2, connected to R and Vdd
# Already connected via the resistor 'load'
# This configuration now ensures V_GS > V_th for both M1 and M2

simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p5_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('NMOS Inverter with Resistor Load')
# Define NMOS Model
circuit.model('nmos', 'nmos', level=1, kp=200e-6, vto=0.7)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Input node
# Vin will be a voltage source or a test signal, for now we set it as a DC source
circuit.V('in', 'Vin', circuit.gnd, 0@u_V)  # Can be varied during simulation
# Resistor R between Vdd and Vout
circuit.R('load', 'Vdd', 'Vout', 100@u_kΩ)  # 100kΩ resistor
# NMOS transistor M1
# Drain connected to Vout
# Gate connected to Vin
# Source connected to ground
circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos')
# The above assumes default width and length for the transistor
# For clarity, specify device parameters if needed
# For example:
# circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos', w=10e-6, l=1e-6)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p6_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

analysis = simulator.operating_point()
for node in analysis.nodes.values(): 
    print(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}")
vin_name = ""
for element in circuit.elements:
    for pin in element.pins:
        if "vin" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin_name = element.name
            break

circuit.element(vin_name).dc_value = "5"

simulator2 = circuit.simulator()
analysis2 = simulator2.operating_point()


node = 'vout'

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

vout2 = float(analysis2[node][0])

circuit.element(vin_name).dc_value = "0"

simulator3 = circuit.simulator()
analysis3 = simulator3.operating_point()

vout3 = float(analysis3[node][0])

import sys
if vout2 <= 2.5 and vout3 >= 2.5 and vout3 - vout2 >= 1.0:
    print("The circuit functions correctly.\n")
    sys.exit(0)

print("The circuit does not function correctly.\n"
    "It can not invert the input voltage.\n"
    f"When input is 5V, output is {vout2:.2f}V.\n"
    f"When input is 0V, output is {vout3:.2f}V.\n"
    "Please fix the wrong operating point.\n")

sys.exit(2)




# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('CMOS Inverter')
# 1. Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# 2. Define models for NMOS and PMOS with typical parameters
# These are generic models; for detailed design, use specific parameters
circuit.model('nmos', 'nmos', level=1, vto=0.7, kp=2e-3)  # NMOS threshold ~0.7V
circuit.model('pmos', 'pmos', level=1, vto=-0.7, kp=1.5e-3)  # PMOS threshold ~-0.7V
# 3. Add a voltage source for Vin
# For example, a DC voltage at 0V (logic LOW), can be swept later
circuit.V('in', 'Vin', circuit.gnd, 0@u_V)
# 4. Create NMOS transistor
# Correct order: name, drain, gate, source, bulk, model, w, l
circuit.MOSFET('M_N', 'Vout', 'Vin', 'GND', 'GND', model='nmos', w=10e-6, l=1e-6)
# 5. Create PMOS transistor
# Drain connected to Vout, gate to Vin, source to Vdd
circuit.MOSFET('M_P', 'Vout', 'Vin', 'Vdd', 'Vdd', model='pmos', w=10e-6, l=1e-6)
# 6. (Optional) Add a load resistor if needed for analysis
# Not necessary for basic inverter function
# 7. Ready for simulation
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p7_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

analysis = simulator.operating_point()
for node in analysis.nodes.values(): 
    print(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}")
vin_name = ""
for element in circuit.elements:
    for pin in element.pins:
        if "vin" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin_name = element.name
            break

circuit.element(vin_name).dc_value = "5"

simulator2 = circuit.simulator()
analysis2 = simulator2.operating_point()


node = 'vout'

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

vout2 = float(analysis2[node][0])

circuit.element(vin_name).dc_value = "0"

simulator3 = circuit.simulator()
analysis3 = simulator3.operating_point()

vout3 = float(analysis3[node][0])

import sys
if vout2 <= 2.5 and vout3 >= 2.5 and vout3 - vout2 >= 1.0:
    print("The circuit functions correctly.\n")
    sys.exit(0)

print("The circuit does not function correctly.\n"
    "It can not invert the input voltage.\n"
    f"When input is 5V, output is {vout2:.2f}V.\n"
    f"When input is 0V, output is {vout3:.2f}V.\n"
    "Please fix the wrong operating point.\n")

sys.exit(2)




# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Create a new circuit
circuit = Circuit('NMOS Constant Current Source with Resistor Load')
# Define the NMOS model
circuit.model('nmos', 'nmos', level=1, vto=0.5, kp=200e-6)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V Vdd
# Bias voltage for gate
circuit.V('bias', 'Vbias', circuit.gnd, 1.0)  # Bias voltage above Vth to turn on NMOS
# NMOS transistor: Drain connected to Vout, Gate to Vbias, Source to ground
circuit.MOSFET('M1', 'Vout', 'Vbias', circuit.gnd, circuit.gnd, model='nmos', w=10e-6, l=1e-6)
# Resistor R from Vout to Vdd
circuit.R('Rload', 'Vout', 'Vdd', 10e3)  # 10kΩ resistor
# The circuit is now ready for simulation
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p8_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

load_resistances = [100, 300, 500, 750, 1000]
currents = []

import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Resistor):
        resistor_name = element.name
        node1, node2 = element.nodes
        break


resistor = circuit[resistor_name]
for r_load in load_resistances:
    resistor.resistance = r_load
    analysis = simulator.operating_point()
    if str(node2) == "0":
        current = float(analysis[str(node1)][0]) / r_load
    elif str(node1) == "0":
        current = - float(analysis[str(node2)][0]) / r_load
    else:
        current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load
    currents.append(current)

for r_load, current in zip(load_resistances, currents):
    print(f"Load: {r_load}, Current: {current}")

tolerance = 1e-6

current_variations = []
for i in range(4):
    current_variations.append(abs(currents[i+1] - currents[i]))

import sys
if min(current_variations) < tolerance and min(currents) > 1e-5:
    pass
    # print("The circuit functions correctly as a constant current source within the given tolerance.")
    # sys.exit(0)
else:
    print("The circuit does not function correctly as a current source.")
    sys.exit(2)

iin_name = None
for element in circuit.elements:
    if "ref" in element.name.lower(): # and element.name.lower().startswith("v"):
        iin_name = element.name

# print("iin_name", iin_name)
if iin_name is None:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


circuit.element(iin_name).dc_value = "0.00155"

# print(str(circuit))
simulator = circuit.simulator()
resistor.resistance = 500
analysis = simulator.operating_point()
if str(node2) == "0":
    current = float(analysis[str(node1)][0]) / r_load
elif str(node1) == "0":
    current = - float(analysis[str(node2)][0]) / r_load
else:
    current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load

# print("current", current)
# print("currents", currents)
# print("abs(current - currents[2])", abs(current - currents[2]))
if abs(current - currents[2]) < 1e-6:
    print("The circuit does not as a current source because it cannot replicate the Iref current.")
    sys.exit(2)
else:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)

# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Comparator')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Set reference voltage (2.5V) as virtual ground
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltage source (example: 3V, can be swept in simulation)
circuit.V('in', 'Vin', circuit.gnd, 3@u_V)
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Create opamp instance (comparator configuration)
# Non-inverting input: Vin, Inverting input: Vref, Output: Vout
circuit.X('cmp', 'Opamp', 'Vin', 'Vref', 'Vout')
simulator = circuit.simulator()
# Perform DC analysis, sweep input voltage from 0V to 5V
params = {'Vin': slice(0, 5, 0.01)}

try:
    analysis = simulator.dc(**params)
except:
    print("DC analysis failed.")
    import sys
    sys.exit(2)

import numpy as np

# Get analysis results
in_voltage = np.array(analysis.Vin)
out_voltage = np.array(analysis.Vout)
ref_voltage = np.array(analysis.Vref)

# Verify comparator functionality
import sys


for element in circuit.elements:
    if "ref" in element.name.lower():
        vref_name = element.name
        vref_voltage = float(analysis[vref_name][0])
        print(f"Reference Voltage (Vref): {vref_voltage:.2f} V")
        break
# Define transition point
transition_point = vref_voltage  # Voltage where output should switch

# Modified test to check for monotonic behavior instead of absolute values
all_passed = True

# Check that outputs are distinct for values well below and well above the threshold
low_region_outputs = out_voltage[in_voltage < (transition_point - 0.5)]
high_region_outputs = out_voltage[in_voltage > (transition_point + 0.5)]

if len(low_region_outputs) > 0 and len(high_region_outputs) > 0:
    avg_low = np.mean(low_region_outputs)
    avg_high = np.mean(high_region_outputs)
    
    # Check if there's a significant difference between high and low outputs
    if avg_high - avg_low < 2.0:  # At least 2V difference expected
        print(f"Comparator test failed: Not enough distinction between high ({avg_high:.2f}V) and low ({avg_low:.2f}V) outputs")
        all_passed = False
    
    # Check that the transition is monotonic (always increasing or always decreasing)
    # For standard comparator, output should decrease as input increases
    diff_output = np.diff(out_voltage)
    if not (np.all(diff_output <= 0.1) or np.all(diff_output >= -0.1)):
        print("Comparator test failed: Output is not monotonic around the transition region")
        all_passed = False
else:
    print("Comparator test failed: Not enough data points to evaluate")
    all_passed = False

# Check transition behavior
transition_idx = np.argmin(np.abs(in_voltage - transition_point))
before_idx = max(0, transition_idx - 5)
after_idx = min(len(in_voltage) - 1, transition_idx + 5)

transition_inputs = in_voltage[before_idx:after_idx+1]
transition_outputs = out_voltage[before_idx:after_idx+1]

# Print observed behavior for debugging
print("\nObserved Comparator Behavior:")
print("---------------------------")
print("Vin (V) | Vout (V)")
print("---------------------------")
for i, vin in enumerate(transition_inputs):
    vout = transition_outputs[i]
    print(f"{vin:.2f}    | {vout:.2f}")

if all_passed:
    print("\nThe op-amp comparator functions as expected based on observed behavior.")
    # sys.exit(0)
else:
    print("\nThe op-amp comparator test failed.")
    sys.exit(2)

# Optional: Plot comparator response curve
import matplotlib.pyplot as plt

plt.figure(figsize=(10, 6))
plt.plot(in_voltage, out_voltage, 'b-', label='Comparator Output (Vout)')
plt.axvline(x=transition_point, color='k', linestyle='--', label='Reference Voltage (Vref)')
plt.grid(True)
plt.xlabel('Input Voltage (V)')
plt.ylabel('Output Voltage (V)')
plt.title('Op-Amp Comparator Response')
plt.legend()
plt.tight_layout()
plt.savefig('p9_waveform.png')
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive Low-Pass Filter')
# DC voltage source to Vin (input node)
circuit.V('in', 'Vin', circuit.gnd, 1.0@u_V)
# Resistor R1 between Vin and Vout
circuit.R('1', 'Vin', 'Vout', 10@u_kΩ)
# Capacitor C1 between Vout and ground
circuit.C('1', 'Vout', circuit.gnd, 10@u_nF)
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)


node = 'Vout'
has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)
vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac))
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of Low-Pass Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)


plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Point')
plt.legend()

plt.tight_layout()
plt.savefig('p10_waveform.png')

low_freq_gain = gain_db[0]
print(f"Gain at lowest frequency ({frequencies[0]:.2f} Hz): {low_freq_gain:.2f} dB")

high_freq_gain = gain_db[-1]
print(f"Gain at highest frequency ({frequencies[-1]:.2f} Hz): {high_freq_gain:.2f} dB")
high_freq_attenuation = low_freq_gain - high_freq_gain
print(f"High frequency attenuation: {high_freq_attenuation:.2f} dB")

idx_3db = np.argmin(np.abs(gain_db - (low_freq_gain-3)))
cutoff_freq = frequencies[idx_3db]
print(f"Approximate -3dB cutoff frequency: {cutoff_freq:.2f} Hz")

window_size = min(11, len(gain_db) // 20)
if window_size % 2 == 0:
    window_size += 1
    
if window_size > 2:
    from scipy.signal import savgol_filter
    smoothed_gain = savgol_filter(gain_db, window_size, 1)
else:
    smoothed_gain = gain_db
    
diff_gain = np.diff(smoothed_gain)
non_monotonic_points = np.sum(diff_gain > 0.5)

if non_monotonic_points > 0:
    monotonic_percentage = 100 * (1 - non_monotonic_points / len(diff_gain))
    print(f"Warning: Gain is not strictly monotonically decreasing.")
    print(f"Monotonicity: {monotonic_percentage:.1f}% of frequency points")
    if monotonic_percentage < 90:
        print("This may not be a well-behaved low-pass filter.")
else:
    print("Filter response is monotonically decreasing with frequency, as expected.")

if high_freq_attenuation > 2 and (non_monotonic_points == 0 or monotonic_percentage >= 90):
    print("The circuit exhibits proper low-pass filter characteristics.")
    sys.exit(0)
else:
    print("The circuit does not show expected low-pass filter characteristics.")
    sys.exit(2)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive High-Pass Filter')
# Input voltage source (DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 1.0) # 1V DC
# Capacitor in series with input
circuit.C('1', 'Vin', 'Vout', 10@u_nF)
# Resistor from output to ground
circuit.R('1', 'Vout', circuit.gnd, 10@u_kΩ)
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)

node = 'Vout'

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac))
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of High-Pass Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)

plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Point')
plt.legend()

plt.tight_layout()
plt.savefig('p11_figure.png')

# Basic High-Pass Filter Verification - Including Monotonicity Check
# 1. Check High-Frequency Gain
high_freq_gain = gain_db[-1]  # Gain at highest frequency
print(f"Gain at highest frequency ({frequencies[-1]:.2f} Hz): {high_freq_gain:.2f} dB")

# 2. Check low frequency attenuation
low_freq_gain = gain_db[0]  # Gain at lowest frequency
print(f"Gain at lowest frequency ({frequencies[0]:.2f} Hz): {low_freq_gain:.2f} dB")
low_freq_attenuation = high_freq_gain - low_freq_gain
print(f"Low frequency attenuation: {low_freq_attenuation:.2f} dB")

# 3. Find the approximate -3dB point
idx_3db = np.argmin(np.abs(gain_db - (high_freq_gain-3)))
cutoff_freq = frequencies[idx_3db]
print(f"Approximate -3dB cutoff frequency: {cutoff_freq:.2f} Hz")

# 4. Check monotonicity
# Use smoothing to reduce measurement noise
window_size = min(11, len(gain_db) // 20)  #  Use window smoothing
if window_size % 2 == 0:  # Ensure window size is odd
    window_size += 1
    
if window_size > 2:  # If there are enough points to smooth
    from scipy.signal import savgol_filter
    smoothed_gain = savgol_filter(gain_db, window_size, 1)  # Use 1st order polynomial smoothing
else:
    smoothed_gain = gain_db
    
# Calculate the difference of the smoothed gain - note that a high-pass filter should increase with frequency
diff_gain = np.diff(smoothed_gain)
non_monotonic_points = np.sum(diff_gain < -0.5)  # Allow a small decrease of 0.5dB

if non_monotonic_points > 0:
    monotonic_percentage = 100 * (1 - non_monotonic_points / len(diff_gain))
    print(f"Warning: Gain is not strictly monotonically increasing.")
    print(f"Monotonicity: {monotonic_percentage:.1f}% of frequency points")
    if monotonic_percentage < 90:  # if non-monotonic points exceed 10%
        print("This may not be a well-behaved high-pass filter.")
else:
    print("Filter response is monotonically increasing with frequency, as expected.")

# 5. Determine if it meets high-pass characteristics
if low_freq_attenuation > 2 and (non_monotonic_points == 0 or monotonic_percentage >= 90):
    print("The circuit exhibits proper high-pass filter characteristics.")
    sys.exit(0)
else:
    print("The circuit does not show expected high-pass filter characteristics.")
    sys.exit(2)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive Band-Pass Filter')
# Input voltage source (DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 1.0)  # 1V DC
# High-Pass Filter Stage
circuit.C('1', 'Vin', 'N1', 10@u_nF)      # C1: 10 nF
circuit.R('1', 'N1', circuit.gnd, 10@u_kΩ) # R1: 10 kΩ
# Low-Pass Filter Stage
circuit.R('2', 'N1', 'Vout', 10@u_kΩ)     # R2: 10 kΩ
circuit.C('2', 'Vout', circuit.gnd, 10@u_nF) # C2: 10 nF
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)

node = 'Vout'
has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)
vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac)+1e-12)  # Avoid log(0)
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of Band-Pass Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)

plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Points')
plt.legend()

plt.tight_layout()
plt.savefig('p12_waveform.png')

max_gain_idx = np.argmax(gain_db)
max_gain = gain_db[max_gain_idx]
peak_freq = frequencies[max_gain_idx]

print(f"Maximum gain: {max_gain:.2f} dB at frequency {peak_freq:.2e} Hz")

relative_position = max_gain_idx / len(frequencies)
print(f"Relative position in frequency range: {relative_position:.2f}")

min_peak_boost = 10  # dB

high_gain_mask = gain_db > (max_gain - min_peak_boost/2)
low_gain_points = gain_db[~high_gain_mask]
avg_stopband_gain = np.mean(low_gain_points) if len(low_gain_points) > 0 else 0

peak_boost = max_gain - avg_stopband_gain

print(f"Average stopband gain: {avg_stopband_gain:.2f} dB")
print(f"Calculated peak boost: {peak_boost:.2f} dB")

left_side = gain_db[:max_gain_idx]
right_side = gain_db[max_gain_idx+1:]

min_side_length = max(5, len(gain_db) * 0.05)

if len(left_side) < min_side_length or len(right_side) < min_side_length:
    print("WARNING: Peak is very close to frequency range boundary.")

left_avg = np.mean(left_side) if len(left_side) >= min_side_length else None
right_avg = np.mean(right_side) if len(right_side) >= min_side_length else None

left_lower = (left_avg is not None) and (left_avg < max_gain - min_peak_boost)
right_lower = (right_avg is not None) and (right_avg < max_gain - min_peak_boost)

if left_avg is not None:
    print(f"Left side average gain: {left_avg:.2f} dB")
if right_avg is not None:
    print(f"Right side average gain: {right_avg:.2f} dB")

if peak_boost >= min_peak_boost and (left_lower and right_lower):
    print("PASS: This is a band-pass filter.")
    print(f"Center frequency: {peak_freq:.2e} Hz")
    print(f"Peak gain: {max_gain:.2f} dB")
    print(f"Peak boost: {peak_boost:.2f} dB above stopband")
    
    threshold = max_gain - 3
    
    if peak_boost > 30:
        print("This appears to be a high-Q resonant band-pass filter.")
    
    sys.exit(0)
else:
    print("FAIL: This is NOT a band-pass filter.")
    
    if not (left_lower and right_lower):
        if left_lower and not right_lower:
            print("Only left side has low gain - may be a high-pass filter.")
        elif right_lower and not left_lower:
            print("Only right side has low gain - may be a low-pass filter.")
        else:
            print("Neither side shows significantly lower gain.")
    
    if peak_boost < min_peak_boost:
        print(f"The gain variation ({peak_boost:.2f} dB) is insufficient for a band-pass filter.")
    
    if relative_position < 0.1 or relative_position > 0.9:
        if relative_position < 0.1:
            print("Maximum gain is at the low frequency end - likely a low-pass filter.")
        else:
            print("Maximum gain is at the high frequency end - likely a high-pass filter.")
    
    sys.exit(2)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Passive Band-Stop Filter')
# Input voltage source (DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 1.0)
# Series resistor R1 between Vin and Vout
circuit.R('1', 'Vin', 'Vout', 1@u_kΩ)
# Series LC branch from Vout to ground for notch
# Create an intermediate node for series connection
circuit.L('1', 'Vout', 'N1', 10@u_mH)   # L1 from Vout to N1
circuit.C('1', 'N1', circuit.gnd, 10@u_nF)  # C1 from N1 to ground
# Output node is 'Vout' by definition above
simulator = circuit.simulator()
has_vin = False
for element in circuit.elements:
    if "vin" in element.name.lower():
        element.dc_value = "dc 2.5 ac 1"
        has_vin = True
        break

if not has_vin:
    circuit.V('in', 'Vin', circuit.gnd, dc_value=0, ac_value=1)

import sys
import numpy as np
import matplotlib.pyplot as plt
try:
    # Only AC analysis
    ac_analysis = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_GHz, 
                              number_of_points=1000, variation='dec')
except:
    print("Analysis failed.")
    sys.exit(2)


node = 'Vout'
has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

# Get frequency response data
frequencies = np.array(ac_analysis.frequency)
vout_ac = np.array(ac_analysis[node])
gain_db = 20 * np.log10(np.abs(vout_ac)+1e-12)  # Avoid log(0)
phase = np.angle(vout_ac, deg=True)

# Create frequency domain plot
plt.figure(figsize=(10, 6))
plt.semilogx(frequencies, gain_db)
plt.title('Frequency Response of Band-Stop Filter')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid(True)

plt.axhline(y=-3, color='g', linestyle='--', label='-3dB Points')
plt.legend()

plt.tight_layout()
plt.savefig('p13_waveform.png')


min_gain_idx = np.argmin(gain_db)
min_gain = gain_db[min_gain_idx]
notch_freq = frequencies[min_gain_idx]

print(f"Minimum gain: {min_gain:.2f} dB at frequency {notch_freq:.2e} Hz")

relative_position = min_gain_idx / len(frequencies)
print(f"Relative position in frequency range: {relative_position:.2f}")

min_notch_depth = 10  # dB

low_gain_mask = gain_db < (min_gain + min_notch_depth/2)
high_gain_points = gain_db[~low_gain_mask]
avg_passband_gain = np.mean(high_gain_points) if len(high_gain_points) > 0 else 0

# Notch depth
notch_depth = avg_passband_gain - min_gain

print(f"Average passband gain: {avg_passband_gain:.2f} dB")
print(f"Calculated notch depth: {notch_depth:.2f} dB")

# Check if both sides have high gain regions
left_side = gain_db[:min_gain_idx]
right_side = gain_db[min_gain_idx+1:]

# If either side is too short, it may be a boundary stopband issue
min_side_length = max(5, len(gain_db) * 0.05)  # At least 5 points or 5% of the frequency range

if len(left_side) < min_side_length or len(right_side) < min_side_length:
    print("WARNING: Notch is very close to frequency range boundary.")

left_avg = np.mean(left_side) if len(left_side) >= min_side_length else None
right_avg = np.mean(right_side) if len(right_side) >= min_side_length else None

left_higher = (left_avg is not None) and (left_avg > min_gain + min_notch_depth)
right_higher = (right_avg is not None) and (right_avg > min_gain + min_notch_depth)

if left_avg is not None:
    print(f"Left side average gain: {left_avg:.2f} dB")
if right_avg is not None:
    print(f"Right side average gain: {right_avg:.2f} dB")

if notch_depth >= min_notch_depth and (left_higher and right_higher):
    print("PASS: This is a band-stop filter.")
    print(f"Notch frequency: {notch_freq:.2e} Hz")
    print(f"Notch depth: {notch_depth:.2f} dB")
    
    threshold = avg_passband_gain - 3
    
    if notch_depth > 30:
        print("This appears to be a deep notch filter.")
    
    sys.exit(0)
else:
    print("FAIL: This is NOT a band-stop filter.")
    
    if not (left_higher and right_higher):
        if left_higher and not right_higher:
            print("Only left side has high gain - may be a low-pass filter.")
        elif right_higher and not left_higher:
            print("Only right side has high gain - may be a high-pass filter.")
        else:
            print("Neither side shows significantly higher gain.")
    
    if notch_depth < min_notch_depth:
        print(f"The gain variation ({notch_depth:.2f} dB) is insufficient for a band-stop filter.")
    
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Two-Stage Amplifier with Miller Compensation')
# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Define bias voltage for active load
circuit.V('bias', 'Vbias', circuit.gnd, 2.5@u_V)
# Transistor models
circuit.model('nmos', 'nmos', level=1, vto=0.5, kp=100e-6)
circuit.model('pmos', 'pmos', level=1, vto=-0.5, kp=50e-6)
# First Stage: NMOS common-source with PMOS active load
# M1: NMOS input transistor
circuit.MOSFET('M1', 'Vmid', 'Vin', 'gnd', 'gnd', model='nmos', w=10e-6, l=1e-6)
# M2: PMOS active load
circuit.MOSFET('M2', 'Vmid', 'Vbias', 'Vdd', 'Vdd', model='pmos', w=20e-6, l=1e-6)
# Second Stage: NMOS common-source
circuit.MOSFET('M3', 'Vout', 'Vmid', 'gnd', 'gnd', model='nmos', w=10e-6, l=1e-6)
# Load resistor for second stage
circuit.R('load', 'Vout', 'Vdd', 10@u_kΩ)
# Miller Compensation Capacitor
circuit.C('miller', 'Vmid', 'Vout', 1@u_pF)
# Input source
circuit.V('in', 'Vin', circuit.gnd, "dc 1@u_V ac 1n")
# Connect all components properly
# (Connections are made via node names above)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p14_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
# Define the circuit
circuit = Circuit('Single-Stage Common-Source with PMOS Diode-Connected Load')
# Define NMOS and PMOS models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Input voltage
circuit.V('in', 'Vin', circuit.gnd, "dc 1@u_V ac 1n")
# Single NMOS transistor (M1)
# Drain connected to Vout, Gate to Vin, Source to GND
circuit.MOSFET('M1', 'Vout', 'Vin', circuit.gnd, circuit.gnd,
               model='nmos_model', w=50e-6, l=1e-6)
# PMOS diode-connected load (M2)
# Drain and Gate connected together, Source to Vdd
circuit.MOSFET('M2', 'Vout', 'Vout', 'Vdd', 'Vdd',
               model='pmos_model', w=50e-6, l=1e-6)
# Note: The drain of M1 and M2 is at Vout
# The source of M1 is GND
# The source of M2 is Vdd
# The diode connection for M2 is achieved by connecting gate and drain together
# The output node is Vout
# Ready for simulation
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p15_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'

# find whether vout in the circuit

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Differential Opamp with PMOS Current Mirror Load')
# MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Differential inputs and bias
circuit.V('inp', 'Vinp', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('bias', 'Vbias', circuit.gnd, 1.0)
# Tail current source (NMOS)
circuit.MOSFET('tail', 'Stail', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Differential pair (NMOS)
circuit.MOSFET('1', 'Voutp', 'Vinp', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Vout', 'Vinn', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
# PMOS current mirror load
circuit.MOSFET('3', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('4', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p16_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Cascode Current Mirror')
# NMOS model (nominal)
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.7)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Reference current source: from Vdd to Iref
circuit.I('ref', 'Vdd', 'Iref', 100@u_uA)
# M1: Bottom input NMOS (diode-connected)
circuit.MOSFET('1', 'N1', 'N1', circuit.gnd, circuit.gnd, model='nmos_model', w=20e-6, l=1e-6)
# M2: Top input NMOS (cascode)
circuit.MOSFET('2', 'Iref', 'Iref', 'N1', 'N1', model='nmos_model', w=20e-6, l=1e-6)
# M3: Bottom output NMOS (mirror)
circuit.MOSFET('3', 'N3', 'N1', circuit.gnd, circuit.gnd, model='nmos_model', w=20e-6, l=1e-6)
# M4: Top output NMOS (cascode)
circuit.MOSFET('4', 'Iout', 'Iref', 'N3', 'N3', model='nmos_model', w=20e-6, l=1e-6)
# Output load resistor
circuit.R('1', 'Iout', 'Vdd', 10@u_kΩ)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p17_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

load_resistances = [100, 300, 500, 750, 1000]
currents = []

import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Resistor):
        resistor_name = element.name
        node1, node2 = element.nodes
        break


resistor = circuit[resistor_name]
for r_load in load_resistances:
    resistor.resistance = r_load
    analysis = simulator.operating_point()
    if str(node2) == "0":
        current = float(analysis[str(node1)][0]) / r_load
    elif str(node1) == "0":
        current = - float(analysis[str(node2)][0]) / r_load
    else:
        current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load
    currents.append(current)

for r_load, current in zip(load_resistances, currents):
    print(f"Load: {r_load}, Current: {current}")

tolerance = 1e-6

current_variations = []
for i in range(4):
    current_variations.append(abs(currents[i+1] - currents[i]))

import sys
if min(current_variations) < tolerance and min(currents) > 1e-5:
    pass
    # print("The circuit functions correctly as a constant current source within the given tolerance.")
    # sys.exit(0)
else:
    print("The circuit does not function correctly as a current source.")
    sys.exit(2)

iin_name = None
for element in circuit.elements:
    if "ref" in element.name.lower(): # and element.name.lower().startswith("v"):
        iin_name = element.name

# print("iin_name", iin_name)
if iin_name is None:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


circuit.element(iin_name).dc_value = "0.00155"

# print(str(circuit))
simulator = circuit.simulator()
resistor.resistance = 500
analysis = simulator.operating_point()
if str(node2) == "0":
    current = float(analysis[str(node1)][0]) / r_load
elif str(node1) == "0":
    current = - float(analysis[str(node2)][0]) / r_load
else:
    current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load

# print("current", current)
# print("currents", currents)
# print("abs(current - currents[2])", abs(current - currents[2]))
if abs(current - currents[2]) < 1e-6:
    print("The circuit does not as a current source because it cannot replicate the Iref current.")
    sys.exit(2)
else:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)

# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Differential Opamp with Resistive Loads')
# Define NMOS model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input voltages (for DC operating point)
circuit.V('inp', 'Vinp', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 1.0 ac 1n")
# Bias voltage for tail current source
circuit.V('bias', 'Vbias', circuit.gnd, 1.0) # Vbias = Vth + 0.5V = 1.0V
# Differential Pair
# M1: Drain=Vout, Gate=Vinp, Source=SourceDiff, Bulk=SourceDiff
circuit.MOSFET('1', 'Vout', 'Vinp', 'SourceDiff', 'SourceDiff', model='nmos_model', w=50e-6, l=1e-6)
# M2: Drain=Drain2, Gate=Vinn, Source=SourceDiff, Bulk=SourceDiff
circuit.MOSFET('2', 'Drain2', 'Vinn', 'SourceDiff', 'SourceDiff', model='nmos_model', w=50e-6, l=1e-6)
# Tail current source
# Mtail: Drain=SourceDiff, Gate=Vbias, Source=0, Bulk=0
circuit.MOSFET('tail', 'SourceDiff', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=20e-6, l=1e-6)
# Load resistors
# R1: Vdd to Vout (drain of M1)
circuit.R('1', 'Vdd', 'Vout', 10@u_kΩ)
# R2: Vdd to Drain2 (drain of M2)
circuit.R('2', 'Vdd', 'Drain2', 10@u_kΩ)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p18_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Gilbert Cell Mixer')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.7)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
circuit.V('bias', 'Vbias', circuit.gnd, 1.5)  # Bias voltage for current source (Vth + 0.8V)
# RF and LO Input Voltages (DC bias points)
circuit.V('rfp', 'Vrfp', circuit.gnd, 2.5)  # RF+ input biased at mid-supply
circuit.V('rfn', 'Vrfn', circuit.gnd, 2.5)  # RF- input biased at mid-supply
circuit.V('lop', 'Vlop', circuit.gnd, 3.0)  # LO+ input biased above threshold
circuit.V('lon', 'Vlon', circuit.gnd, 2.0)  # LO- input biased below LO+
# Load Resistors
circuit.R('L1', 'Vdd', 'Voutp', 1@u_kΩ)
circuit.R('L2', 'Vdd', 'Voutn', 1@u_kΩ)
# Current Source Transistor
circuit.MOSFET('7', 'SourceNode', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=100e-6, l=1e-6)
# RF Differential Pair
circuit.MOSFET('1', 'RFp_out', 'Vrfp', 'SourceNode', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'RFn_out', 'Vrfn', 'SourceNode', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# LO Switching Quad
circuit.MOSFET('3', 'Voutp', 'Vlop', 'RFp_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Voutp', 'Vlon', 'RFn_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('5', 'Voutn', 'Vlon', 'RFp_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('6', 'Voutn', 'Vlop', 'RFn_out', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Analysis Part
simulator = circuit.simulator()
# Gilbert Cell Mixer Functionality Test with FFT Analysis
import sys
import numpy as np

detached_voltage_source = ['Vrfp', 'Vrfn', 'Vlop', 'Vlon']
for source in detached_voltage_source:
    circuit.element(source).detach()

# connected Vrfn and Vrfp
circuit.V('rfp', 'Vrfp', circuit.gnd, 2.0@u_V)
circuit.V('rfn', 'Vrfn', 'Vrfp', 0.0@u_V)

# connected Vlop and Vlon
circuit.V('lop', 'Vlop', circuit.gnd, 4.0@u_V)
circuit.V('lon', 'Vlon', 'Vlop', 0.0@u_V)

# Sweep the Vlop to get the operating point
simulator_dc = circuit.simulator(temperature=25, nominal_temperature=25)
try:
    analysis = simulator_dc.dc(Vlop=slice(0, 5, 0.1))
except Exception as e:
    print(f"Error during DC simulation: {e}")
    sys.exit(2)

# find the best operating point
voutp = np.array(analysis['Voutp'])
vlop = np.array(analysis['Vlop'])


# find the best operating point for Vrfp which can make the Voutp closest to 2.5V
best_i = 0
best_vlop = 2.5
for i in range(len(voutp)):
    # If current voutp is closer to 2.5V than the previously found best
    if abs(voutp[i] - 2.5) < abs(voutp[best_i] - 2.5):
        best_i = i
        best_vlop = vlop[i]
        best_voutp = voutp[i]
    # If current voutp is equally distant from 2.5V as the previously found best
    elif abs(voutp[i] - 2.5) == abs(voutp[best_i] - 2.5):
        # When multiple vlop values meet the requirements, we need to select the one with voutp closest to 2.5V
        # Since abs(voutp[i] - 2.5) == abs(voutp[best_i] - 2.5), we need to compare actual values
        # Choose the one closer to 2.5V (to handle cases where one is above 2.5 and one is below)
        if abs(voutp[i] - 2.5) == (voutp[i] - 2.5):  # Current value is >= 2.5
            if abs(voutp[best_i] - 2.5) != (voutp[best_i] - 2.5) or vlop[i] > best_vlop:
                best_i = i
                best_vlop = vlop[i]
                best_voutp = voutp[i]


print(f"Best Vlop: {best_vlop:.2f} V, Best Voutp: {best_voutp:.2f} V")

detached_voltage_source = ['Vrfp', 'Vrfn', 'Vlop', 'Vlon']
for source in detached_voltage_source:
    circuit.element(source).detach()

circuit.SinusoidalVoltageSource('rfp', 'Vrfp', circuit.gnd,
                              amplitude=0.1@u_V, frequency=1@u_kHz,
                              dc_offset=2.0@u_V, offset = 2.0@u_V,
                              ac_magnitude=0.1@u_V,
                              delay=0)
circuit.SinusoidalVoltageSource('rfn', 'Vrfn', circuit.gnd,
                              amplitude=0.1@u_V, frequency=1@u_kHz,
                              dc_offset=2.0@u_V, offset = 2.0@u_V,
                              ac_magnitude=0.1@u_V,
                              delay=0.5@u_ms)
circuit.SinusoidalVoltageSource('lop', 'Vlop', circuit.gnd,
                                amplitude=0.1@u_V, frequency=1.2@u_kHz,
                                dc_offset=best_vlop@u_V, offset = best_vlop@u_V,
                                ac_magnitude=0.1@u_V,
                                delay=0)
circuit.SinusoidalVoltageSource('lon', 'Vlon', circuit.gnd,
                                amplitude=0.1@u_V, frequency=1.2@u_kHz,
                                dc_offset=best_vlop@u_V, offset = best_vlop@u_V,
                                ac_magnitude=0.1@u_V,
                                delay=1/(2*1.2e3)@u_s)


circuit.R('R_filter_p', 'Voutp', 'Vdd', 1@u_kOhm)
circuit.C('C_filter_p', 'Voutp', 'Vdd', 10@u_nF)

circuit.R('R_filter_n', 'Voutn', 'Vdd', 1@u_kOhm)
circuit.C('C_filter_n', 'Voutn', 'Vdd', 10@u_nF)


simulator = circuit.simulator()

# Perform transient analysis to get mixer output
print("Performing transient analysis to obtain mixing output...")
sampling_rate = 1 / (20 * 1.2e3)  # Sampling rate 20x higher than LO frequency
simulation_time = 20e-3  # Observe 20ms, multiple cycles of RF and LO
try:
    analysis = simulator.transient(step_time=sampling_rate, end_time=simulation_time)
except Exception as e:
    print(f"Error during transient simulation: {e}")
    sys.exit(2)

# Extract signals
time = analysis.time
voutp = analysis['Voutp']
voutn = analysis['Voutn']
vlop = analysis['Vlop']
vlon = analysis['Vlon']
vrfp = analysis['Vrfp']
vrfn = analysis['Vrfn']
vout_diff = voutp - voutn  # Differential output

# Perform FFT analysis

from scipy.fft import fft
from matplotlib import pyplot as plt

# Calculate FFT
n = len(time)
fft_vout = fft(vout_diff)
fft_magnitude = np.abs(fft_vout) / n * 2  # Normalize magnitude
freq = np.fft.fftfreq(n, sampling_rate)  # Frequency axis

# Keep only positive frequencies
positive_freq_mask = freq > 0
freq = freq[positive_freq_mask]
fft_magnitude = fft_magnitude[positive_freq_mask]

# Output major frequency components
print("\nFFT Analysis Results - Major Frequency Components:")
# Find top 5 frequency components
indices = np.argsort(fft_magnitude)[::-1][:5]
for i in indices:
    print(f"Frequency: {freq[i]:.1f} Hz, Magnitude: {fft_magnitude[i]:.6f} V")

# Check for mixing products
rf_freq = 1e3  # 1 kHz
lo_freq = 1.2e3  # 1.2 kHz
expected_if_down = abs(lo_freq - rf_freq)  # Down-conversion: 200 Hz
expected_if_up = lo_freq + rf_freq  # Up-conversion: 2.2 kHz

# Search for expected IF frequencies in FFT results
tolerance = 50  # Hz
found_if_down = False
found_if_up = False
if_down_magnitude = 0
if_up_magnitude = 0

for i, f in enumerate(freq):
    if abs(f - expected_if_down) < tolerance and fft_magnitude[i] > 1e-4:
        found_if_down = True
        if_down_magnitude = fft_magnitude[i]
        print(f"\nDetected down-conversion IF signal (LO-RF): {f:.1f} Hz, Magnitude: {if_down_magnitude:.6f} V")
    
    if abs(f - expected_if_up) < tolerance and fft_magnitude[i] > 1e-4:
        found_if_up = True
        if_up_magnitude = fft_magnitude[i]
        print(f"Detected up-conversion IF signal (LO+RF): {f:.1f} Hz, Magnitude: {if_up_magnitude:.6f} V")

# Plot transient simulation and FFT results
plt.figure(figsize=(12, 10))

# Subplot 1: Input signals - RF pair
plt.subplot(3, 2, 1)
plt.plot(time*1000, vrfp, label='RF+')
plt.plot(time*1000, vrfn, label='RF-')
plt.title('RF Input Signals')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.legend()
plt.grid(True)

# Subplot 2: Input signals - LO pair
plt.subplot(3, 2, 2)
plt.plot(time*1000, vlop, label='LO+')
plt.plot(time*1000, vlon, label='LO-')
plt.title('LO Input Signals')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.legend()
plt.grid(True)

# Subplot 3: Output signals - Voutp, Voutn
plt.subplot(3, 2, 3)
plt.plot(time*1000, voutp, label='OUT+')
plt.plot(time*1000, voutn, label='OUT-')
plt.title('Output Signals')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.legend()
plt.grid(True)

# Subplot 4: Differential output
plt.subplot(3, 2, 4)
plt.plot(time*1000, vout_diff)
plt.title('Differential Output (OUT+ - OUT-)')
plt.xlabel('Time (ms)')
plt.ylabel('Voltage (V)')
plt.grid(True)

# Subplot 5: FFT of differential output - Full spectrum
plt.subplot(3, 2, 5)
max_freq_display = 5000  # Limit to 5kHz for better visibility
mask = freq < max_freq_display
plt.plot(freq[mask], fft_magnitude[mask])
plt.title('FFT Spectrum Analysis')
plt.xlabel('Frequency (Hz)')
plt.ylabel('Magnitude (V)')
plt.grid(True)

# Mark key frequencies
plt.axvline(x=rf_freq, color='b', linestyle='--', label='RF')
plt.axvline(x=lo_freq, color='m', linestyle='--', label='LO')
if found_if_down:
    plt.axvline(x=expected_if_down, color='r', linestyle='--', label='IF down')
if found_if_up:
    plt.axvline(x=expected_if_up, color='g', linestyle='--', label='IF up')
plt.legend()

# Subplot 6: FFT - Zoomed in on important frequencies
plt.subplot(3, 2, 6)
zoom_mask = (freq < 3000) & (freq > 0)  # Focus on 0-3kHz range
plt.plot(freq[zoom_mask], fft_magnitude[zoom_mask])
plt.title('FFT Spectrum (Zoomed)')
plt.xlabel('Frequency (Hz)')
plt.ylabel('Magnitude (V)')
plt.grid(True)

# Mark and annotate key frequencies in zoomed view
key_freqs = [rf_freq, lo_freq, expected_if_down, expected_if_up]
key_labels = ['RF (1kHz)', 'LO (1.2kHz)', 'IF down (200Hz)', 'IF up (2.2kHz)']
key_colors = ['b', 'm', 'r', 'g']

for f, label, color in zip(key_freqs, key_labels, key_colors):
    if f < 3000:  # Only mark if in zoomed range
        plt.axvline(x=f, color=color, linestyle='--')
        # Find closest frequency in our FFT data
        idx = np.argmin(np.abs(freq - f))
        if idx < len(freq) and zoom_mask[idx]:
            plt.annotate(label, 
                         xy=(freq[idx], fft_magnitude[idx]),
                         xytext=(10, 10), 
                         textcoords='offset points',
                         arrowprops=dict(arrowstyle='->'),
                         color=color)

plt.tight_layout()
plt.savefig('p19_waveform.png')
# plt.show()

# Evaluate mixer performance
if found_if_down or found_if_up:
    print("\nMixer functioning correctly: Mixing products detected!")
    
    # Calculate conversion efficiency
    rf_index = np.argmin(np.abs(freq - rf_freq))
    rf_magnitude = fft_magnitude[rf_index]
    
    if found_if_down:
        conversion_gain_down = 20 * np.log10(if_down_magnitude / rf_magnitude)
        print(f"Down-conversion gain: {conversion_gain_down:.2f} dB")
    
    if found_if_up:
        conversion_gain_up = 20 * np.log10(if_up_magnitude / rf_magnitude)
        print(f"Up-conversion gain: {conversion_gain_up:.2f} dB")
    
    # Evaluate LO leakage
    lo_index = np.argmin(np.abs(freq - lo_freq))
    lo_leakage = fft_magnitude[lo_index]
    if found_if_down:
        lo_rejection = 20 * np.log10(if_down_magnitude / lo_leakage)
        print(f"LO rejection ratio: {lo_rejection:.2f} dB")
    
    # Overall evaluation
    print("\nMixer performance assessment:")
    if found_if_down and if_down_magnitude > 1e-3:
        print("✓ Down-conversion functioning properly")
    if found_if_up and if_up_magnitude > 1e-3:
        print("✓ Up-conversion functioning properly")
    
    print("The Gilbert Cell Mixer is functioning correctly.")
    print("Plots saved as 'mixer_analysis.png'")
    sys.exit(0)  # Exit with success status code
else:
    print("\nMixer malfunction: Expected mixing products not detected!")
    print("Check the following possible issues:")
    print("1. RF and LO signal amplitudes might be insufficient")
    print("2. Circuit connections might be incorrect")
    print("Plots saved as 'mixer_analysis.png'")
    sys.exit(2)  # Exit with error status code
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Two-Stage Differential Opamp')
# MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Differential inputs
circuit.V('inp', 'Vinp', circuit.gnd, "dc 2.5 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 2.5 ac 1n")
# Bias voltages
circuit.V('b1', 'Vbias1', circuit.gnd, 1.0)   # NMOS bias
circuit.V('b2', 'Vbias2', circuit.gnd, 4.0)   # PMOS current mirror bias
circuit.V('b3', 'Vbias3', circuit.gnd, 4.0)   # PMOS second stage bias
# First Stage: Differential pair with current mirror load and tail current
circuit.MOSFET('1', 'Voutp', 'Vinp', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Outn', 'Vinn', 'Stail', 'Stail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('3', 'Stail', 'Vbias1', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Voutp', 'Vbias2', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('5', 'Outn', 'Vbias2', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Second Stage: Common-source with active load
circuit.MOSFET('6', 'Vout', 'Voutp', circuit.gnd, circuit.gnd, model='nmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('7', 'Vout', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# PMOS bias diode for M7, with resistor to ground to ensure V_DS > 0
circuit.MOSFET('8', 'Nbias', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.R('b', 'Nbias', circuit.gnd, 10@u_kΩ)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p20_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Telescopic Cascode Opamp')
# MOSFET Models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)
# Input sources (DC bias for now)
circuit.V('inp', 'Vinp', circuit.gnd, "dc 1.0 ac 1n")
circuit.V('inn', 'Vinn', circuit.gnd, "dc 1.0 ac 1n")
# Bias voltages (choose values to ensure all devices are in saturation)
circuit.V('bias1', 'Vbias1', circuit.gnd, 0.7)   # Tail NMOS bias (Vgs > Vth)
circuit.V('bias2', 'Vbias2', circuit.gnd, 1.2)   # NMOS cascode bias (> Vth)
circuit.V('bias3', 'Vbias3', circuit.gnd, 4.0)   # PMOS load bias (Vdd - |Vth| - margin)
circuit.V('bias4', 'Vbias4', circuit.gnd, 3.5)   # PMOS cascode bias (Vdd - |Vth| - margin)
# Tail current source NMOS
circuit.MOSFET('9', 'S_tail', 'Vbias1', circuit.gnd, circuit.gnd, model='nmos_model', w=30e-6, l=1e-6)
# Differential input NMOS
circuit.MOSFET('1', 'N1', 'Vinp', 'S_tail', 'S_tail', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'N2', 'Vinn', 'S_tail', 'S_tail', model='nmos_model', w=50e-6, l=1e-6)
# NMOS cascode
circuit.MOSFET('3', 'Voutp', 'Vbias2', 'N1', 'N1', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Vout', 'Vbias2', 'N2', 'N2', model='nmos_model', w=50e-6, l=1e-6)
# PMOS active load
circuit.MOSFET('5', 'Voutp', 'Vbias3', 'S5', 'S5', model='pmos_model', w=70e-6, l=1e-6)
circuit.MOSFET('6', 'Vout', 'Vbias3', 'S6', 'S6', model='pmos_model', w=70e-6, l=1e-6)
# PMOS cascode
circuit.MOSFET('7', 'S5', 'Vbias4', 'Vdd', 'Vdd', model='pmos_model', w=70e-6, l=1e-6)
circuit.MOSFET('8', 'S6', 'Vbias4', 'Vdd', 'Vdd', model='pmos_model', w=70e-6, l=1e-6)
simulator = circuit.simulator()

try:
    analysis = simulator.operating_point()
    fopen = open("p21_op.txt", "w")
    for node in analysis.nodes.values(): 
        fopen.write(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}\n")
    fopen.close()
except Exception as e:
    print("Analysis failed due to an error:")
    print(str(e))

simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = "Vout"

has_node = False
# find any node with "vout"
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            node = str(pin.node)
            has_node = True
            break

if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-9))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-9)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('RC Phase Shift Oscillator')
# Power supplies
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)  # Virtual ground at Vdd/2
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Connect non-inverting input to Vref (2.5V)
# The inverting input will be connected to the RC network and feedback resistor
# Output node is 'Vout'
# RC phase shift network (three stages)
circuit.R('1', 'Vout', 'N1', 10@u_kΩ)
circuit.C('1', 'N1', 'Vref', 10@u_nF)
circuit.R('2', 'N1', 'N2', 10@u_kΩ)
circuit.C('2', 'N2', 'Vref', 10@u_nF)
circuit.R('3', 'N2', 'N3', 10@u_kΩ)
circuit.C('3', 'N3', 'Vref', 10@u_nF)
# Feedback resistor from output to inverting input (Vinn)
circuit.R('f', 'Vout', 'Vinn', 330@u_kΩ)
# The RC network output connects to the inverting input
circuit.R('in', 'N3', 'Vinn', 1@u_Ω)  # Virtually a wire (for node naming clarity)
# Create opamp instance
circuit.X('1', 'Opamp', 'Vref', 'Vinn', 'Vout')
simulator = circuit.simulator()
del_vname = []
for element in circuit.elements:
    v_name = element.name
    if element.name.lower().startswith("v") and "bias" not in element.name.lower() and "ref" not in element.name.lower():
        del_vname.append(v_name)

pin_name = "Vinp"
pin_name_n = "Vinn"
for element in circuit.elements:
    if element.name.lower().startswith("x"):
        opamp_element = element
        pin_name = str(opamp_element.pins[0].node)
        pin_name_n = str(opamp_element.pins[1].node)
        break

params = {pin_name: 2.51, pin_name_n: 2.5}

simulator = circuit.simulator()
simulator.initial_condition(**params)

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=20@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

node = 'Vout'
# find any node with "vout"
has_node = False
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            node = str(pin.node)
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

import numpy as np
# Get the output node voltage
vout = np.array(analysis[node])

vlist = {}
for node_name in analysis.nodes.keys():
    vlist[node_name.lower()] = np.array(analysis[node_name])

time = np.array(analysis.time)

from scipy.signal import find_peaks, firwin, lfilter
import sys
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter, FormatStrFormatter

fig, axs = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

key_output = node.lower()
axs[0].plot(time, vlist[key_output], color='darkgreen', linewidth=3, label=key_output)
axs[0].set_title('Output Signal', fontsize=16)
axs[0].set_ylabel('Voltage [V]', fontsize=14)
axs[0].tick_params(axis='both', which='major', labelsize=12)
axs[0].grid(True, linestyle='--', alpha=0.7)
axs[0].legend(fontsize=12, loc='best')

axs[0].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))


feedback_node = None
ref_node = None
input_nodes = []

for node_name in vlist.keys():
    if 'feedback' in node_name or 'fb' in node_name:
        feedback_node = node_name
    elif 'ref' in node_name or 'vref' in node_name:
        ref_node = node_name
    elif node_name in [pin_name.lower(), pin_name_n.lower()]:
        input_nodes.append(node_name)
    elif ('in' in node_name or 'node' in node_name) and node_name != key_output:
        input_nodes.append(node_name)

if not input_nodes:
    for node_name in vlist.keys():
        if (node_name != key_output and 
            node_name != feedback_node and 
            node_name != ref_node and
            'vdd' not in node_name and 
            'vcc' not in node_name and
            'bias' not in node_name):
            input_nodes.append(node_name)
            if len(input_nodes) >= 3:
                break

if feedback_node:
    axs[1].plot(time, vlist[feedback_node], color='crimson', linewidth=2.5, label=feedback_node)
if ref_node:
    axs[1].plot(time, vlist[ref_node], color='navy', linewidth=2.5, label=ref_node)

colors = ['darkorange', 'purple', 'teal', 'olive', 'brown']
for i, node_name in enumerate(input_nodes):
    axs[1].plot(time, vlist[node_name], color=colors[i % len(colors)], linewidth=2, label=node_name)

axs[1].set_title('Input, Reference and Feedback Signals', fontsize=16)
axs[1].set_xlabel('Time [s]', fontsize=14)
axs[1].set_ylabel('Voltage [V]', fontsize=14)
axs[1].tick_params(axis='both', which='major', labelsize=12)
axs[1].grid(True, linestyle='--', alpha=0.7)
axs[1].legend(fontsize=12, loc='best')

axs[1].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))

vout_min = np.min(vlist[key_output])
vout_max = np.max(vlist[key_output])
vout_range = vout_max - vout_min
axs[0].set_ylim([vout_min - 0.1 * vout_range, vout_max + 0.1 * vout_range])

all_values = []
if feedback_node:
    all_values.extend(vlist[feedback_node])
if ref_node:
    all_values.extend(vlist[ref_node])
for node_name in input_nodes:
    all_values.extend(vlist[node_name])

if all_values:
    y_min = np.min(all_values)
    y_max = np.max(all_values)
    y_range = y_max - y_min
    axs[1].set_ylim([y_min - 0.1 * y_range, y_max + 0.1 * y_range])

axs[1].xaxis.set_major_formatter(FormatStrFormatter('%.4f'))

plt.tight_layout()
plt.savefig('p22_waveform.png', dpi=300)


def detect_oscillation_start(vout, time, threshold=0.001):
    dvout = np.abs(np.diff(vout))
    window_size = len(dvout) // 50
    window_size = max(window_size, 10)
    
    std_values = []
    for i in range(window_size, len(dvout)):
        window = dvout[i-window_size:i]
        std_values.append(np.std(window))
    
    std_values = np.array(std_values)
    threshold_value = threshold * np.max(std_values)
    start_indices = np.where(std_values > threshold_value)[0]
    
    if len(start_indices) > 0:
        oscillation_start_idx = start_indices[0] + window_size
        oscillation_start_idx = min(oscillation_start_idx, len(time)-1)
        return oscillation_start_idx
    else:
        return int(len(time) * 0.7)

def analyze_last_section(vout, time, fraction=0.3):
    start_idx = int(len(time) * (1 - fraction))
    return vout[start_idx:], time[start_idx:]

last_vout, last_time = analyze_last_section(vout, time, 0.3)

peaks, _ = find_peaks(last_vout)
troughs, _ = find_peaks(-last_vout)

error = 0

if len(peaks) > 2 and len(troughs) > 2:
    amplitudes = []
    
    for peak in peaks:
        nearest_trough_idx = np.argmin(np.abs(troughs - peak))
        nearest_trough = troughs[nearest_trough_idx]
        amplitude = np.abs(last_vout[peak] - last_vout[nearest_trough])
        amplitudes.append(amplitude)
    
    amplitudes = np.array(amplitudes)
    
    peak_times = last_time[peaks]
    periods = np.diff(peak_times)
    
    if len(periods) > 2:
        average_period = np.mean(periods)
        period_variation = np.std(periods) / average_period
        
        print(f"Detected {len(peaks)} peaks in the oscillation section")
        print(f"Average oscillation period: {average_period:.6f} s")
        print(f"Maximum amplitude: {np.max(amplitudes):.6f} V")
        
        if period_variation < 0.2:
            print("The oscillator works correctly and produces periodic oscillations")
        else:
            print("Periodicity is inconsistent, oscillation may not be ideal")
            error = 1
    else:
        print("Not enough peaks detected to determine periodicity")
        error = 1
else:
    print("Not enough peaks and troughs detected in the latter part to analyze oscillation")
    error = 1

if error == 1:
    sys.exit(2)
else:
    sys.exit(0)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Wien Bridge Oscillator')
# Power supply: 5V single supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Virtual ground/reference at 2.5V (Vref)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# --- Wien Bridge RC Network ---
# Series RC: Vout -> N1 -> N2
circuit.R('1', 'Vout', 'N1', 10@u_kΩ)    # R1: Output to N1
circuit.C('1', 'N1', 'N2', 10@u_nF)      # C1: N1 to N2
# Parallel RC: N2 to Vref
circuit.R('2', 'N2', 'Vref', 10@u_kΩ)    # R2: N2 to Vref
circuit.C('2', 'N2', 'Vref', 10@u_nF)    # C2: N2 to Vref
# --- Feedback Network for Gain ---
# Feedback from output to inverting input, then to Vref
circuit.R('f1', 'Vout', 'Vinn', 21@u_kΩ)   # Feedback resistor (Rf1)
circuit.R('f2', 'Vinn', 'Vref', 10@u_kΩ)   # Gain resistor (Rf2)
# --- Opamp Subcircuit ---
circuit.subcircuit(Opamp())
# Opamp instance: non-inverting input = N2, inverting input = Vinn, output = Vout
circuit.X('1', 'Opamp', 'N2', 'Vinn', 'Vout')
# --- (Optional) Initial Condition to Start Oscillation ---
# Add a tiny voltage source to "kick" the oscillator (not strictly necessary in all simulators)
# circuit.V('kick', 'N2', 'Vref', 1@u_uV)  # 1 microvolt at non-inverting input
simulator = circuit.simulator()
del_vname = []
for element in circuit.elements:
    v_name = element.name
    if element.name.lower().startswith("v") and "bias" not in element.name.lower() and "ref" not in element.name.lower():
        del_vname.append(v_name)

pin_name = "Vinp"
pin_name_n = "Vinn"
for element in circuit.elements:
    if element.name.lower().startswith("x"):
        opamp_element = element
        pin_name = str(opamp_element.pins[0].node)
        pin_name_n = str(opamp_element.pins[1].node)
        break

params = {pin_name: 2.51, pin_name_n: 2.5}

simulator = circuit.simulator()
simulator.initial_condition(**params)

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=20@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

node = 'Vout'
# find any node with "vout"
has_node = False
for element in circuit.elements:
    # get pins
    for pin in element.pins:
        if "vout" == str(pin.node).lower():
            has_node = True
            node = str(pin.node)
            break
if has_node == False:
    for element in circuit.elements:
        for pin in element.pins:
            if "vout" in str(pin.node).lower():
                node = str(pin.node)
                break

import numpy as np
# Get the output node voltage
vout = np.array(analysis[node])

vlist = {}
for node_name in analysis.nodes.keys():
    vlist[node_name.lower()] = np.array(analysis[node_name])

time = np.array(analysis.time)

from scipy.signal import find_peaks, firwin, lfilter
import sys
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter, FormatStrFormatter

fig, axs = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

key_output = node.lower()
axs[0].plot(time, vlist[key_output], color='darkgreen', linewidth=3, label=key_output)
axs[0].set_title('Output Signal', fontsize=16)
axs[0].set_ylabel('Voltage [V]', fontsize=14)
axs[0].tick_params(axis='both', which='major', labelsize=12)
axs[0].grid(True, linestyle='--', alpha=0.7)
axs[0].legend(fontsize=12, loc='best')

axs[0].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))


feedback_node = None
ref_node = None
input_nodes = []

for node_name in vlist.keys():
    if 'feedback' in node_name or 'fb' in node_name:
        feedback_node = node_name
    elif 'ref' in node_name or 'vref' in node_name:
        ref_node = node_name
    elif node_name in [pin_name.lower(), pin_name_n.lower()]:
        input_nodes.append(node_name)
    elif ('in' in node_name or 'node' in node_name) and node_name != key_output:
        input_nodes.append(node_name)

if not input_nodes:
    for node_name in vlist.keys():
        if (node_name != key_output and 
            node_name != feedback_node and 
            node_name != ref_node and
            'vdd' not in node_name and 
            'vcc' not in node_name and
            'bias' not in node_name):
            input_nodes.append(node_name)
            if len(input_nodes) >= 3:
                break

if feedback_node:
    axs[1].plot(time, vlist[feedback_node], color='crimson', linewidth=2.5, label=feedback_node)
if ref_node:
    axs[1].plot(time, vlist[ref_node], color='navy', linewidth=2.5, label=ref_node)

colors = ['darkorange', 'purple', 'teal', 'olive', 'brown']
for i, node_name in enumerate(input_nodes):
    axs[1].plot(time, vlist[node_name], color=colors[i % len(colors)], linewidth=2, label=node_name)

axs[1].set_title('Input, Reference and Feedback Signals', fontsize=16)
axs[1].set_xlabel('Time [s]', fontsize=14)
axs[1].set_ylabel('Voltage [V]', fontsize=14)
axs[1].tick_params(axis='both', which='major', labelsize=12)
axs[1].grid(True, linestyle='--', alpha=0.7)
axs[1].legend(fontsize=12, loc='best')

axs[1].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))

vout_min = np.min(vlist[key_output])
vout_max = np.max(vlist[key_output])
vout_range = vout_max - vout_min
axs[0].set_ylim([vout_min - 0.1 * vout_range, vout_max + 0.1 * vout_range])

all_values = []
if feedback_node:
    all_values.extend(vlist[feedback_node])
if ref_node:
    all_values.extend(vlist[ref_node])
for node_name in input_nodes:
    all_values.extend(vlist[node_name])

if all_values:
    y_min = np.min(all_values)
    y_max = np.max(all_values)
    y_range = y_max - y_min
    axs[1].set_ylim([y_min - 0.1 * y_range, y_max + 0.1 * y_range])

axs[1].xaxis.set_major_formatter(FormatStrFormatter('%.4f'))

plt.tight_layout()
plt.savefig('p23_waveform.png', dpi=300)


def detect_oscillation_start(vout, time, threshold=0.001):
    dvout = np.abs(np.diff(vout))
    window_size = len(dvout) // 50
    window_size = max(window_size, 10)
    
    std_values = []
    for i in range(window_size, len(dvout)):
        window = dvout[i-window_size:i]
        std_values.append(np.std(window))
    
    std_values = np.array(std_values)
    threshold_value = threshold * np.max(std_values)
    start_indices = np.where(std_values > threshold_value)[0]
    
    if len(start_indices) > 0:
        oscillation_start_idx = start_indices[0] + window_size
        oscillation_start_idx = min(oscillation_start_idx, len(time)-1)
        return oscillation_start_idx
    else:
        return int(len(time) * 0.7)

def analyze_last_section(vout, time, fraction=0.3):
    start_idx = int(len(time) * (1 - fraction))
    return vout[start_idx:], time[start_idx:]

last_vout, last_time = analyze_last_section(vout, time, 0.3)

peaks, _ = find_peaks(last_vout)
troughs, _ = find_peaks(-last_vout)

error = 0

if len(peaks) > 2 and len(troughs) > 2:
    amplitudes = []
    
    for peak in peaks:
        nearest_trough_idx = np.argmin(np.abs(troughs - peak))
        nearest_trough = troughs[nearest_trough_idx]
        amplitude = np.abs(last_vout[peak] - last_vout[nearest_trough])
        amplitudes.append(amplitude)
    
    amplitudes = np.array(amplitudes)
    
    peak_times = last_time[peaks]
    periods = np.diff(peak_times)
    
    if len(periods) > 2:
        average_period = np.mean(periods)
        period_variation = np.std(periods) / average_period
        
        print(f"Detected {len(peaks)} peaks in the oscillation section")
        print(f"Average oscillation period: {average_period:.6f} s")
        print(f"Maximum amplitude: {np.max(amplitudes):.6f} V")
        
        if period_variation < 0.2:
            print("The oscillator works correctly and produces periodic oscillations")
        else:
            print("Periodicity is inconsistent, oscillation may not be ideal")
            error = 1
    else:
        print("Not enough peaks detected to determine periodicity")
        error = 1
else:
    print("Not enough peaks and troughs detected in the latter part to analyze oscillation")
    error = 1

if error == 1:
    sys.exit(2)
else:
    sys.exit(0)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Integrator')
# Define MOSFET models (for completeness in case the Opamp needs them)
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Reference voltage (virtual ground at Vdd/2)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input DC bias voltage
circuit.V('in', 'Vin', circuit.gnd, 3@u_V)
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Opamp instance: non-inverting input at Vref, inverting input at node 'Vinn', output at 'Vout'
circuit.X('op', 'Opamp', 'Vref', 'Vinn', 'Vout')
# Input resistor R1 from Vin to Vinn (inverting input)
circuit.R('1', 'Vin', 'Vinn', 10@u_kΩ)
# Feedback capacitor Cf from Vout to Vinn
circuit.C('f', 'Vout', 'Vinn', 100@u_nF)
simulator = circuit.simulator()
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

bias_voltage = 2.5

if vin_name != "":
    circuit.element(vin_name).detach()
    circuit.V('pulse', 'Vin', circuit.gnd, f"dc {bias_voltage} PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")
else:
    circuit.V('in', 'Vin', circuit.gnd, f"dc {bias_voltage} PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")

r_name = None
for element in circuit.elements:
    if element.name.lower().startswith("r1") or element.name.lower().startswith("rr1"):
        r_name = element.name

if r_name is None:
    for element in circuit.elements:
        if element.name.lower().startswith("r"):
            r_name = element.name

if r_name is None:
    print("No resistor found in the netlist. Please check the netlist.")
    sys.exit(2)
circuit.element(r_name).resistance = "10k"

c_name = None
for element in circuit.elements:
    if element.name.lower().startswith("cf") or element.name.lower().startswith("ccf") or element.name.lower().startswith("c1"):
        c_name = element.name

if c_name is None:
    for element in circuit.elements:
        if element.name.lower().startswith("c"):
            c_name = element.name

if c_name is None:
    print("No capacitor found in the netlist. Please check the netlist.")
    sys.exit(2)
circuit.element(c_name).capacitance = "3u"

simulator = circuit.simulator()

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=1000@u_ms, start_time=800@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

import numpy as np
vlist = {}
for node in analysis.nodes.values():
    vlist[node.name] = np.array(analysis[node.name])

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

plt.rcParams.update({
    'font.size': 12,
    'axes.titlesize': 16,
    'axes.labelsize': 14,
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    'legend.fontsize': 11,
    'lines.linewidth': 2.5
})

# Plot the step response
time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

plt.figure(figsize=(12, 8))

colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#6A994E', '#7209B7', '#F72585', 
          '#264653', '#2A9D8F', '#E9C46A', '#F4A261', '#E76F51', '#8E44AD', '#3498DB',
          '#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#34495E', '#E67E22']

linestyles = ['-', '--', '-.', ':', '-', '--', '-.', '-', '--', '-.', ':', 
              '-', '--', '-.', ':', '-', '--', '-.', ':', '-', '--']

for i, node in enumerate(analysis.nodes.values()):
    plt.plot(time, vlist[node.name], 
             color=colors[i % len(colors)], 
             linestyle=linestyles[i % len(linestyles)],
             linewidth=2.5,
             label=node.name,
             alpha=0.9)

plt.title('Transient Response of Op-amp Integrator', fontsize=16, fontweight='bold', pad=20)
plt.xlabel('Time [s]', fontsize=14, fontweight='semibold')
plt.ylabel('Voltage [V]', fontsize=14, fontweight='semibold')

plt.grid(True, linestyle='--', alpha=0.6, color='gray', linewidth=0.8)

plt.legend(frameon=True, fancybox=True, shadow=True, ncol=2, 
           loc='best', framealpha=0.9, edgecolor='black')

ax = plt.gca()
ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
ax.xaxis.set_major_formatter(FormatStrFormatter('%.3f'))

ax = plt.gca()
for spine in ax.spines.values():
    spine.set_visible(True)
    spine.set_linewidth(1.2)
    spine.set_color('black')

plt.tick_params(axis='both', which='major', direction='out', length=6, width=1.2)
plt.tick_params(axis='both', which='minor', direction='out', length=4, width=1)

plt.tight_layout()
plt.savefig("p24_waveform.png", dpi=300, bbox_inches='tight', facecolor='white')

expected_slope = 0.5 / 0.03

from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)
troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("No peaks or troughs found in output voltage. Please check the netlist.")
    sys.exit(2)

start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])

import sys
if not np.isclose(slope, expected_slope, rtol=0.3):
    print(f"The circuit does not function correctly as an integrator.\n"
          f"Expected slope: {expected_slope:.2f} V/s | Actual slope: {slope:.2f} V/s\n")
    sys.exit(2)

if not r_value** 2 >= 0.9:
    print("The op-amp integrator does not have a linear response.\n")
    sys.exit(2)

for element in circuit.elements:
    if element.name.lower().startswith("x"):
        x_name = element.name

circuit.element(x_name).detach()
simulator = circuit.simulator()
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)

time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

expected_slope = 0.5 / 0.03

from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)
troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)

start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])

if np.isclose(slope, expected_slope, rtol=0.5):
    print("The integrator maybe a passive integrator.\n")
    sys.exit(2)

print("The op-amp integrator functions correctly.\n")
sys.exit(0)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Integrator')
# Define MOSFET models (for completeness in case the Opamp needs them)
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Reference voltage (virtual ground at Vdd/2)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input DC bias voltage
circuit.V('in', 'Vin', circuit.gnd, 3@u_V)
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Opamp instance: non-inverting input at Vref, inverting input at node 'Vinn', output at 'Vout'
circuit.X('op', 'Opamp', 'Vref', 'Vinn', 'Vout')
# Input resistor R1 from Vin to Vinn (inverting input)
circuit.R('1', 'Vin', 'Vinn', 10@u_kΩ)
# Feedback capacitor Cf from Vout to Vinn
circuit.C('f', 'Vout', 'Vinn', 100@u_nF)
simulator = circuit.simulator()
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

bias_voltage = 2.5

if vin_name != "":
    circuit.element(vin_name).detach()
    circuit.V('pulse', 'Vin', circuit.gnd, f"PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")
else:
    circuit.V('in', 'Vin', circuit.gnd, f" PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")

r_name = None
for element in circuit.elements:
    if element.name.lower().startswith("r1") or element.name.lower().startswith("rr1"):
        r_name = element.name

if r_name is None:
    for element in circuit.elements:
        if element.name.lower().startswith("r"):
            r_name = element.name

if r_name is None:
    print("No resistor found in the netlist. Please check the netlist.")
    sys.exit(2)
circuit.element(r_name).resistance = "10k"

c_name = None
for element in circuit.elements:
    if element.name.lower().startswith("cf") or element.name.lower().startswith("ccf") or element.name.lower().startswith("c1"):
        c_name = element.name

if c_name is None:
    for element in circuit.elements:
        if element.name.lower().startswith("c"):
            c_name = element.name

if c_name is None:
    print("No capacitor found in the netlist. Please check the netlist.")
    sys.exit(2)
circuit.element(c_name).capacitance = "3u"

simulator = circuit.simulator()

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=1000@u_ms, start_time=800@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

import numpy as np
vlist = {}
for node in analysis.nodes.values():
    vlist[node.name] = np.array(analysis[node.name])

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

# 设置图形样式
plt.rcParams.update({
    'font.size': 12,
    'axes.titlesize': 16,
    'axes.labelsize': 14,
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    'legend.fontsize': 11,
    'lines.linewidth': 2.5
})

# Plot the step response
time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

plt.figure(figsize=(12, 8))

colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#6A994E', '#7209B7', '#F72585', 
          '#264653', '#2A9D8F', '#E9C46A', '#F4A261', '#E76F51', '#8E44AD', '#3498DB',
          '#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#34495E', '#E67E22']

linestyles = ['-', '--', '-.', ':', '-', '--', '-.', '-', '--', '-.', ':', 
              '-', '--', '-.', ':', '-', '--', '-.', ':', '-', '--']

for i, node in enumerate(analysis.nodes.values()):
    plt.plot(time, vlist[node.name], 
             color=colors[i % len(colors)], 
             linestyle=linestyles[i % len(linestyles)],
             linewidth=2.5,
             label=node.name,
             alpha=0.9)

plt.title('Transient Response of Op-amp Integrator', fontsize=16, fontweight='bold', pad=20)
plt.xlabel('Time [s]', fontsize=14, fontweight='semibold')
plt.ylabel('Voltage [V]', fontsize=14, fontweight='semibold')

plt.grid(True, linestyle='--', alpha=0.6, color='gray', linewidth=0.8)

plt.legend(frameon=True, fancybox=True, shadow=True, ncol=2, 
           loc='best', framealpha=0.9, edgecolor='black')

ax = plt.gca()
ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
ax.xaxis.set_major_formatter(FormatStrFormatter('%.3f'))

ax = plt.gca()
for spine in ax.spines.values():
    spine.set_visible(True)
    spine.set_linewidth(1.2)
    spine.set_color('black')

plt.tick_params(axis='both', which='major', direction='out', length=6, width=1.2)
plt.tick_params(axis='both', which='minor', direction='out', length=4, width=1)

plt.tight_layout()
plt.savefig("p24_waveform.png", dpi=300, bbox_inches='tight', facecolor='white')

expected_slope = 0.5 / 0.03

from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)
troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("No peaks or troughs found in output voltage. Please check the netlist.")
    sys.exit(2)

start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])

import sys
if not np.isclose(slope, expected_slope, rtol=0.3):
    print(f"The circuit does not function correctly as an integrator.\n"
          f"Expected slope: {expected_slope:.2f} V/s | Actual slope: {slope:.2f} V/s\n")
    sys.exit(2)

if not r_value** 2 >= 0.9:
    print("The op-amp integrator does not have a linear response.\n")
    sys.exit(2)

for element in circuit.elements:
    if element.name.lower().startswith("x"):
        x_name = element.name

circuit.element(x_name).detach()
simulator = circuit.simulator()
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)

time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

expected_slope = 0.5 / 0.03

from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)
troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)

start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])

if np.isclose(slope, expected_slope, rtol=0.5):
    print("The integrator maybe a passive integrator.\n")
    sys.exit(2)

print("The op-amp integrator functions correctly.\n")
sys.exit(0)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Differentiator')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Reference voltage for virtual ground
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltage (set to DC for operating point)
circuit.V('in', 'Vin', circuit.gnd, 3@u_V)
# Opamp subcircuit
circuit.subcircuit(Opamp())
# Differentiator components
circuit.C('1', 'Vin', 'Ninv', 10@u_nF)      # C1: input capacitor
circuit.R('f', 'Vout', 'Ninv', 10@u_kΩ)     # Rf: feedback resistor
circuit.R('b', 'Ninv', 'Vref', 1@u_MΩ)      # Rb: bias resistor for DC stability
# Opamp connections
circuit.X('op', 'Opamp', 'Vref', 'Ninv', 'Vout')
simulator = circuit.simulator()
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

bias_voltage = 2.5

# Detach the previous Vin if it exists and attach a new triangular wave source
if vin_name != "":
    circuit.element(vin_name).detach()
    circuit.V('tri', 'Vin', circuit.gnd, f"PULSE({bias_voltage-0.5} {bias_voltage+0.5} 0 50m 50m 1n 100m)")
else:
    circuit.V('in', 'Vin', circuit.gnd, f"PULSE({bias_voltage-0.5} {bias_voltage+0.5} 0 50m 50m 1n 100m)")

# Adjust R1 resistance if needed
for element in circuit.elements:
    if element.name.lower().startswith("rf") or element.name.lower().startswith("rrf") or element.name.lower().startswith("r1"):
        r_name = element.name
circuit.element(r_name).resistance = "10k"

# Adjust C1 capacitance if needed
for element in circuit.elements:
    if element.name.lower().startswith("c1") or element.name.lower().startswith("cc1"):
        c_name = element.name
circuit.element(c_name).capacitance = "3u"

# Initialize the simulator
simulator = circuit.simulator()

import sys
# Perform transient analysis
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

import numpy as np
vlist = {}
for node in analysis.nodes.values():
    vlist[node.name] = np.array(analysis[node.name])

import numpy as np
# Extract data from the analysis
time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

plt.rcParams.update({
    'font.size': 12,
    'axes.titlesize': 16,
    'axes.labelsize': 14,
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    'legend.fontsize': 11,
    'lines.linewidth': 2.5
})

# Plot the response
plt.figure(figsize=(12, 8))

colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#6A994E', '#7209B7', '#F72585', 
          '#264653', '#2A9D8F', '#E9C46A', '#F4A261', '#E76F51', '#8E44AD', '#3498DB',
          '#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#34495E', '#E67E22']

linestyles = ['-', '--', '-.', ':', '-', '--', '-.', '-', '--', '-.', ':', 
              '-', '--', '-.', ':', '-', '--', '-.', ':', '-', '--']

for i, node in enumerate(analysis.nodes.values()):
    plt.plot(time, vlist[node.name], 
             color=colors[i % len(colors)], 
             linestyle=linestyles[i % len(linestyles)],
             linewidth=2.5,
             label=node.name,
             alpha=0.9)


plt.title('Transient Response of Op-amp Differentiator', fontsize=16, fontweight='bold', pad=20)
plt.xlabel('Time [s]', fontsize=14, fontweight='semibold')
plt.ylabel('Voltage [V]', fontsize=14, fontweight='semibold')

plt.grid(True, linestyle='--', alpha=0.6, color='gray', linewidth=0.8)

plt.legend(frameon=True, fancybox=True, shadow=True, ncol=2, 
           loc='best', framealpha=0.9, edgecolor='black')

ax = plt.gca()
ax.yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
ax.xaxis.set_major_formatter(FormatStrFormatter('%.3f'))

for spine in ax.spines.values():
    spine.set_visible(True)
    spine.set_linewidth(1.2)
    spine.set_color('black')

plt.tick_params(axis='both', which='major', direction='out', length=6, width=1.2)
plt.tick_params(axis='both', which='minor', direction='out', length=4, width=1)

plt.tight_layout()
plt.savefig("p25_waveform.png", dpi=300, bbox_inches='tight', facecolor='white')

from scipy.signal import find_peaks
# Check for square wave characteristics in the output
# Calculate the mean voltage level of the peaks and troughs

min_height = (max(vout) + min(vout)) / 2
num_of_peaks = 2
min_distance = len(vout) / (2 * num_of_peaks) / 1.5 

peaks, _ = find_peaks(vout, height=min_height, distance=min_distance)
troughs, _ = find_peaks(-vout, height=-min_height, distance=min_distance)

average_peak_voltage = np.mean(vout[peaks])
average_trough_voltage = np.mean(vout[troughs])

if len(peaks) == 0 or len(troughs) == 0:
    print("No peaks or troughs found in output voltage. Please check the netlist.")
    sys.exit(2)

peak_voltages = vout[peaks]
trough_voltages = vout[troughs]
mean_peak = np.mean(peak_voltages)
mean_trough = np.mean(trough_voltages)

def is_square_wave(waveform, mean_peak, mean_trough, rtol=0.1):
    high_level = np.mean([x for x in waveform if x > (mean_peak + mean_trough) / 2])
    low_level = np.mean([x for x in waveform if x <= (mean_peak + mean_trough) / 2])
    is_high_close = np.isclose(high_level, mean_peak, rtol=rtol)
    is_low_close = np.isclose(low_level, mean_trough, rtol=rtol)
    return is_high_close and is_low_close

# Check if the output is approximately a square wave by comparing the mean of the peaks and troughs
if np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2) and \
     np.isclose(mean_peak - bias_voltage, 0.6, rtol=0.2) and \
     is_square_wave(vout, mean_peak, mean_trough):  # 20% tolerance
    pass
elif not np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2):
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"When the input is a triangle wave and the output is not a square wave.\n")
    sys.exit(2)
elif not is_square_wave(vout, mean_peak, mean_trough):
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"When the input is a triangle wave and the output is not a square wave.\n")
    sys.exit(2)
else:
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"Output voltage peak value is wrong. Mean peak voltage: {mean_peak} V | Mean trough voltage: {mean_trough} V\n")
    sys.exit(2)

for element in circuit.elements:
    if element.name.lower().startswith("x"):
        x_name = element.name

# Detach the subcircuit
circuit.element(x_name).detach()
simulator = circuit.simulator()
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("The op-amp differentiator functions correctly.\n")
    sys.exit(0)

time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

min_height = (max(vout) + min(vout)) / 2
num_of_peaks = 2
min_distance = len(vout) / (2 * num_of_peaks) / 1.5 

peaks, _ = find_peaks(vout, height=min_height, distance=min_distance)
troughs, _ = find_peaks(-vout, height=-min_height, distance=min_distance)

average_peak_voltage = np.mean(vout[peaks])
average_trough_voltage = np.mean(vout[troughs])

if len(peaks) == 0 or len(troughs) == 0:
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(0)

peak_voltages = vout[peaks]
trough_voltages = vout[troughs]
mean_peak = np.mean(peak_voltages)
mean_trough = np.mean(trough_voltages)

if np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2) and np.isclose(mean_peak - bias_voltage, 0.6, rtol=0.2):  # 20% tolerance
    print("The differentiator maybe a passive differentiator.\n")
    sys.exit(2)
elif not np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2):
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(0)
else:
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(0)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Inverting Adder')
# Power supply: 5V single supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Virtual ground/reference at 2.5V for opamp biasing
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltages (example DC values, you can set as needed)
circuit.V('in1', 'Vin1', circuit.gnd, 3@u_V)
circuit.V('in2', 'Vin2', circuit.gnd, 3@u_V)
# All resistors equal for unity gain from each input ---
R_value = 10@u_kΩ
# Both inputs connect through resistors to summing node 'Vsum' (inverting input) ---
circuit.R('1', 'Vin1', 'Vsum', R_value)  # Vin1 to Vsum
circuit.R('2', 'Vin2', 'Vsum', R_value)  # Vin2 to Vsum
# Feedback resistor from output to Vsum ---
circuit.R('f', 'Vout', 'Vsum', R_value)  # Vout to Vsum
# Non-inverting input of opamp connected to Vref (2.5V) ---
circuit.subcircuit(Opamp())
circuit.X('op', 'Opamp', 'Vref', 'Vsum', 'Vout')
# The circuit now forms a classic inverting adder:
# Vout = 2.5V - [(Vin1 - 2.5V) + (Vin2 - 2.5V)]
#      = -Vin1 - Vin2 + 5V
simulator = circuit.simulator()

bias_voltage = 2.5  # Set bias voltage to 2.5V
v1_amp = 3.0  # Original value from circuit
v2_amp = 3.0  # Original value from circuit
tolerance = 0.2  # 20% tolerance

# Testing approach: We'll run multiple tests to determine if the circuit functions as an adder

# Test 1: Get baseline with original values
simulator = circuit.simulator()
try:
    analysis_baseline = simulator.operating_point()
except Exception as e:
    print(f"DC analysis failed: {str(e)}")
    sys.exit(2)

baseline_output = float(analysis_baseline.Vout)
print(f"Baseline output: {baseline_output:.4f} V with Vin1 = {v1_amp:.4f} V, Vin2 = {v2_amp:.4f} V")

# Test 2: Change Vin1 and check effect
# First, find the Vin1 source to modify
vin1_found = False
for element in circuit.elements:
    if element.name.lower() == 'vin1' or (element.name.lower().startswith('v') and 'vin1' in [str(pin.node).lower() for pin in element.pins]):
        circuit.element(element.name).dc_value = v1_amp + 0.5
        vin1_found = True
        break

if not vin1_found:
    print("Could not find Vin1 source to modify")
    sys.exit(2)

# Run analysis with modified Vin1
simulator = circuit.simulator()
try:
    analysis_vin1_mod = simulator.operating_point()
except Exception as e:
    print(f"DC analysis failed with modified Vin1: {str(e)}")
    sys.exit(2)

vin1_mod_output = float(analysis_vin1_mod.Vout)
vin1_effect = vin1_mod_output - baseline_output
print(f"Effect of increasing Vin1 by 0.5V: {vin1_effect:.4f} V change in output")

# Reset Vin1 to original value
for element in circuit.elements:
    if element.name.lower() == 'vin1' or (element.name.lower().startswith('v') and 'vin1' in [str(pin.node).lower() for pin in element.pins]):
        circuit.element(element.name).dc_value = v1_amp
        break

# Test 3: Change Vin2 and check effect
vin2_found = False
for element in circuit.elements:
    if element.name.lower() == 'vin2' or (element.name.lower().startswith('v') and 'vin2' in [str(pin.node).lower() for pin in element.pins]):
        circuit.element(element.name).dc_value = v2_amp + 0.5
        vin2_found = True
        break

if not vin2_found:
    print("Could not find Vin2 source to modify")
    sys.exit(2)

# Run analysis with modified Vin2
simulator = circuit.simulator()
try:
    analysis_vin2_mod = simulator.operating_point()
except Exception as e:
    print(f"DC analysis failed with modified Vin2: {str(e)}")
    sys.exit(2)

vin2_mod_output = float(analysis_vin2_mod.Vout)
vin2_effect = vin2_mod_output - baseline_output
print(f"Effect of increasing Vin2 by 0.5V: {vin2_effect:.4f} V change in output")

# Verify adder properties
import sys
import numpy as np

# Check if inputs affect the output significantly
if abs(vin1_effect) < 0.05:
    print(f"The circuit is not an adder: Vin1 has minimal effect on output ({vin1_effect:.4f} V change)")
    sys.exit(2)

if abs(vin2_effect) < 0.05:
    print(f"The circuit is not an adder: Vin2 has minimal effect on output ({vin2_effect:.4f} V change)")
    sys.exit(2)

# For a proper inverting adder, increasing input should decrease output
if vin1_effect >= 0:
    print(f"The circuit is not an inverting adder: Increasing Vin1 does not decrease output (effect: {vin1_effect:.4f} V)")
    sys.exit(2)

if vin2_effect >= 0:
    print(f"The circuit is not an inverting adder: Increasing Vin2 does not decrease output (effect: {vin2_effect:.4f} V)")
    sys.exit(2)

# Check if inputs have similar effects (should be approximately equal for equal resistors)
effect_ratio = abs(vin1_effect / vin2_effect)
if not (1-tolerance <= effect_ratio <= 1+tolerance):
    print(f"The circuit has unbalanced input scaling: Vin1 effect = {vin1_effect:.4f} V, Vin2 effect = {vin2_effect:.4f} V")
    sys.exit(2)

# Collect additional test points to verify the adder behavior
test_points = [
    (2.5, 2.5),   # Both at reference
    (3.0, 2.5),   # Only Vin1 above reference
    (2.5, 3.0),   # Only Vin2 above reference
    (3.0, 3.0),   # Both above reference (baseline)
]

results = []
for v1, v2 in test_points:
    # Set Vin1
    for element in circuit.elements:
        if element.name.lower() == 'vin1' or (element.name.lower().startswith('v') and 'vin1' in [str(pin.node).lower() for pin in element.pins]):
            circuit.element(element.name).dc_value = v1
            break
    
    # Set Vin2
    for element in circuit.elements:
        if element.name.lower() == 'vin2' or (element.name.lower().startswith('v') and 'vin2' in [str(pin.node).lower() for pin in element.pins]):
            circuit.element(element.name).dc_value = v2
            break
    
    # Run analysis
    simulator = circuit.simulator()
    try:
        analysis = simulator.operating_point()
        vout = float(analysis.Vout)
        results.append((v1, v2, vout))
    except Exception as e:
        print(f"Analysis failed for Vin1 = {v1:.4f} V, Vin2 = {v2:.4f} V: {str(e)}")

# Calculate the adder's gain factor from data
input_diffs = []
output_diffs = []

for i in range(1, len(results)):
    v1, v2, vout = results[i]
    v1_ref, v2_ref, vout_ref = results[0]  # Reference point (both at 2.5V)
    
    input_diff = (v1 - bias_voltage) + (v2 - bias_voltage)
    output_diff = vout_ref - vout  # For inverting adder, output decreases as input increases
    
    if abs(input_diff) > 0.01:  # Avoid division by near-zero
        input_diffs.append(input_diff)
        output_diffs.append(output_diff)

# Calculate average gain factor
if input_diffs:
    gain_factors = [o/i for i, o in zip(input_diffs, output_diffs)]
    avg_gain = sum(gain_factors) / len(gain_factors)
else:
    avg_gain = 0.5  # Default fallback if we couldn't calculate

# Verify if output follows the adder formula with the determined gain
all_valid = True
for v1, v2, actual_vout in results:
    # Expected output based on inverting adder formula with measured gain
    expected_vout = bias_voltage - avg_gain * ((v1 - bias_voltage) + (v2 - bias_voltage))
    
    # Check if within tolerance
    if not np.isclose(actual_vout, expected_vout, rtol=tolerance):
        all_valid = False
        print(f"Output doesn't match formula at Vin1={v1:.2f}V, Vin2={v2:.2f}V:")
        print(f"  Expected: {expected_vout:.4f}V, Actual: {actual_vout:.4f}V")

if not all_valid:
    print("The circuit does not consistently follow the adder formula within 20% tolerance")
    sys.exit(2)

print("\nThe op-amp adder functions correctly!")
print(f"- Both inputs (Vin1 and Vin2) affect the output")
print(f"- Both have a negative (inverting) effect on the output")
print(f"- The input scaling is balanced (Vin1 effect ≈ Vin2 effect)")
print(f"- The output follows an inverting adder formula: Vout ≈ Vref - {avg_gain:.2f}*((Vin1-Vref) + (Vin2-Vref))")
print(f"- All test points are within {tolerance*100}% tolerance of the expected values")
sys.exit(0)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Opamp Subtractor (Differential Amplifier)')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Virtual ground at Vdd/2 for AC reference
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# DC bias voltages for inputs (example values, can be swept in simulation)
circuit.V('in1', 'Vin1', 'Vref', 3@u_V)
circuit.V('in2', 'Vin2', 'Vref', 4@u_V)
# Declare the opamp subcircuit
circuit.subcircuit(Opamp())
# Differential amplifier resistors (all 10kΩ)
circuit.R('1', 'Vin1', 'Vinn', 10@u_kΩ)     # R1
circuit.R('2', 'Vout', 'Vinn', 10@u_kΩ)     # R2 (feedback)
circuit.R('3', 'Vin2', 'Vinp', 10@u_kΩ)     # R3
circuit.R('4', 'Vref', 'Vinp', 10@u_kΩ)     # R4
# Opamp instance
circuit.X('op', 'Opamp', 'Vinp', 'Vinn', 'Vout')
simulator = circuit.simulator()
import numpy as np
# Define test parameters
BIAS_VOLTAGE = 2.5
TOLERANCE = 0.2  # Stricter 5% tolerance

# Create simulator
simulator = circuit.simulator()

# Test across a wider range of input voltages
vin1_values = np.linspace(2.5, 3.5, 5)  # Test from 1V to 4V
vin2_values = np.linspace(2.5, 3.5, 5)

print("Testing subtractor circuit with multiple input combinations...")
print("Using tolerance: {:.1f}%".format(TOLERANCE * 100))
print("-" * 60)
print("| Vin1 (V) | Vin2 (V) | Expected (V) | Actual (V) | Result |")
print("-" * 60)

all_tests_passed = True


for element in circuit.elements:
    for pin in element.pins:
        if "vin1" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin1_name = element.name
            break

for element in circuit.elements:
    for pin in element.pins:
        if "vin2" in str(pin.node).lower() and element.name.lower().startswith("v"):
            vin2_name = element.name
            break

circuit.element(vin1_name).detach()
circuit.element(vin2_name).detach()

circuit.V('in1', 'Vin1', circuit.gnd, '2.5')
circuit.V('in2', 'Vin2', circuit.gnd, '2.5')
        
import sys
# Test with multiple combinations of inputs
for vin1 in vin1_values:
    for vin2 in vin2_values:
        # Update input voltage sources
        circuit.element("Vin1").dc_value = vin1
        circuit.element("Vin2").dc_value = vin2

        
        # Run DC analysis
        try:
            analysis = simulator.operating_point()
        except Exception as e:
            print(f"Simulation failed: {e}")
            sys.exit(2)
        
        # Get actual output voltage
        actual_vout = float(analysis.Vout)
        
        # Calculate expected output for a proper subtractor: Vout = V2 - V1
        expected_vout = vin2 - vin1 + 2.5
        
        # Verify if the output voltage meets expectations
        if np.isclose(actual_vout, expected_vout, rtol=TOLERANCE):
            test_result = "PASS"
        else:
            test_result = "FAIL"
            all_tests_passed = False
        
        print(f"| {vin1:7.2f} | {vin2:7.2f} | {expected_vout:11.2f} | {actual_vout:10.2f} | {test_result:6} |")

print("-" * 60)


# Output final test result
if all_tests_passed:
    print("\nALL TESTS PASSED: The op-amp subtractor functions correctly.")
    sys.exit(0)
else:
    print("\nTESTS FAILED: The subtractor circuit is not functioning correctly.")
    print("Check the circuit configuration and component values.")
    sys.exit(2)
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class Opamp(SubCircuitFactory):
	NAME = ('Opamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

circuit = Circuit('Non-inverting Schmitt Trigger')
# Power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)
# Reference voltage (virtual ground)
circuit.V('ref', 'Vref', circuit.gnd, 2.5@u_V)
# Input voltage (DC operating point)
circuit.V('in', 'Vin', circuit.gnd, 2.7@u_V)
# Declare opamp subcircuit
circuit.subcircuit(Opamp())
# Non-inverting Schmitt trigger configuration:
# Non-inverting input (Vp): receives Vin through R1, feedback from Vout through R2, and pulled to Vref through R3
# Inverting input (Vn): connected to Vref
# Resistor from Vin to non-inverting input
circuit.R('1', 'Vin', 'Vp', 10@u_kΩ)
# Feedback resistor from Vout to non-inverting input
circuit.R('2', 'Vout', 'Vp', 100@u_kΩ)
# Pull-down resistor from non-inverting input to Vref
circuit.R('3', 'Vp', 'Vref', 10@u_kΩ)
# Instantiate opamp: X('name', 'subckt', non-inv, inv, out)
circuit.X('op', 'Opamp', 'Vp', 'Vref', 'Vout')
simulator = circuit.simulator()
for element in circuit.elements:
    if element.name.lower().startswith("vin"):
        v_name = element.name

circuit.element(v_name).detach()

circuit.V('in_pulse', 'Vin', circuit.gnd, 'PULSE(1.7 3.3 0 1m 1m 10m 20m)')  # Triangle-like pulse
pin_name = "Vinp"
pin_name_n = "Vinn"
pin_name_out = "Vout"
for element in circuit.elements:
    if element.name.lower().startswith("x"):
        opamp_element = element
        pin_name = str(opamp_element.pins[0].node)
        pin_name_n = str(opamp_element.pins[1].node)
        pin_name_out = str(opamp_element.pins[2].node)
        break

circuit.C('stab1', pin_name, circuit.gnd, 1@u_pF)
circuit.C('stab2', pin_name_n, circuit.gnd, 1@u_pF)
circuit.C('stab3', pin_name_out, circuit.gnd, 1@u_pF)

import sys
try:
    analysis = simulator.transient(step_time=10@u_us, end_time=50@u_ms, 
                                  use_initial_condition=True)
except:
    print("Analysis failed.")
    sys.exit(2)

import numpy as np
# Extract data
time = np.array(analysis.time)
vin = np.array(analysis['Vin'])
vout = np.array(analysis['Vout'])

# Find sections of rising and falling input
# Alternative approach to separate rising and falling data
rising_indices = np.where(np.diff(vin) > 0)[0]
falling_indices = np.where(np.diff(vin) < 0)[0]

# Extract rising and falling data
vin_rising = vin[rising_indices]
vout_rising = vout[rising_indices]
vin_falling = vin[falling_indices]
vout_falling = vout[falling_indices]

# Set threshold for detecting trigger points (half of power supply)
threshold = 2.5

# ===========================================
# First plot basic waveforms for debugging
# ===========================================

import matplotlib.pyplot as plt
plt.figure(figsize=(12, 12))

# First subplot - Time domain response
plt.subplot(3, 1, 1)
plt.plot(time*1000, vin, 'b-', label='Vin')
plt.plot(time*1000, vout, 'r-', label='Vout')
plt.axhline(y=threshold, color='g', linestyle='--', label='Threshold (2.5V)')
plt.legend()
plt.title('Schmitt Trigger Time Domain Response')
plt.xlabel('Time [ms]')
plt.ylabel('Voltage [V]')
plt.grid(True)

# Second subplot - Input/Output transfer curve (hysteresis)
plt.subplot(3, 1, 2)
plt.plot(vin, vout, 'g-', label='Transfer Curve')
plt.axhline(y=threshold, color='k', linestyle='--', label='Threshold (2.5V)')
plt.legend()
plt.title('Hysteresis Curve')
plt.xlabel('Vin [V]')
plt.ylabel('Vout [V]')
plt.grid(True)

# Third subplot - Separate rising and falling edge responses
plt.subplot(3, 1, 3)
plt.plot(vin_rising, vout_rising, 'b-', label='Rising Edge')
plt.plot(vin_falling, vout_falling, 'r-', label='Falling Edge')
plt.axhline(y=threshold, color='k', linestyle='--', label='Threshold (2.5V)')
plt.legend()
plt.title('Rising vs Falling Edge Response')
plt.xlabel('Vin [V]')
plt.ylabel('Vout [V]')
plt.grid(True)

plt.tight_layout()
plt.savefig("p28_waveform.png")

# ===========================================
# Perform quantitative analysis after viewing waveforms
# ===========================================

print("\nStarting trigger point analysis...")

try:
    # Find rising edge trigger point
    rising_cross_indices = np.where(np.diff(vout_rising > threshold) > 0)[0]
    if len(rising_cross_indices) > 0:
        rising_index = rising_cross_indices[0]
        # Use linear interpolation for more precise trigger point
        v1 = vout_rising[rising_index]
        v2 = vout_rising[rising_index + 1]
        i1 = vin_rising[rising_index]
        i2 = vin_rising[rising_index + 1]
        
        # Linear interpolation to calculate exact trigger voltage
        if v2 != v1:  # Avoid division by zero
            t = (threshold - v1) / (v2 - v1)
            trigger_vin_rising = i1 + t * (i2 - i1)
        else:
            trigger_vin_rising = i1
    else:
        print("Warning: No threshold crossing detected for rising edge")
        trigger_vin_rising = None

    # Find falling edge trigger point
    falling_cross_indices = np.where(np.diff(vout_falling < threshold) > 0)[0]
    if len(falling_cross_indices) > 0:
        falling_index = falling_cross_indices[0]
        # Use linear interpolation for more precise trigger point
        v1 = vout_falling[falling_index]
        v2 = vout_falling[falling_index + 1]
        i1 = vin_falling[falling_index]
        i2 = vin_falling[falling_index + 1]
        
        # Linear interpolation to calculate exact trigger voltage
        if v2 != v1:  # Avoid division by zero
            t = (threshold - v1) / (v2 - v1)
            trigger_vin_falling = i1 + t * (i2 - i1)
        else:
            trigger_vin_falling = i1
    else:
        print("Warning: No threshold crossing detected for falling edge")
        trigger_vin_falling = None
        
    # Output detection results
    if trigger_vin_rising is not None and trigger_vin_falling is not None:
        hysteresis_width = abs(trigger_vin_rising - trigger_vin_falling)
        print(f"Rising edge trigger point: {trigger_vin_rising:.5f}V")
        print(f"Falling edge trigger point: {trigger_vin_falling:.5f}V")
        print(f"Hysteresis width: {hysteresis_width:.5f}V")
        
        # Check if Schmitt trigger is working properly
        if hysteresis_width <= 0.01:
            print("The circuit does not function correctly. Trigger points are too close.")
            print(f"Trigger points: {trigger_vin_rising:.5f}V and {trigger_vin_falling:.5f}V are not sufficiently different.")
            print("Please ensure proper positive feedback connection, where Rf should connect to the non-inverting input of the op-amp.")
            sys.exit(2)
        elif max(vout) - min(vout) < 2.5:
            print("The circuit does not function correctly. The output voltage does not vary more than Vdd/2.")
            sys.exit(2)
        else:
            print("The circuit functions correctly with different trigger points.")
        # Plot final graph with detected trigger points
        plt.figure(figsize=(12, 12))
        
        # Time domain response - with trigger points marked
        plt.subplot(3, 1, 1)
        plt.plot(time*1000, vin, 'b-', label='Vin')
        plt.plot(time*1000, vout, 'r-', label='Vout')
        plt.axhline(y=threshold, color='g', linestyle='--', label='Threshold (2.5V)')
        # Mark rising and falling edge trigger points (need to find closest time point)
        rising_time_idx = np.argmin(np.abs(vin_rising - trigger_vin_rising))
        falling_time_idx = np.argmin(np.abs(vin_falling - trigger_vin_falling))
        plt.plot(time[rising_indices[rising_time_idx]]*1000, threshold, 'go', markersize=8, label='Rising Trigger')
        plt.plot(time[falling_indices[falling_time_idx]]*1000, threshold, 'mo', markersize=8, label='Falling Trigger')
        plt.legend()
        plt.title('Schmitt Trigger Response with Trigger Points')
        plt.xlabel('Time [ms]')
        plt.ylabel('Voltage [V]')
        plt.grid(True)
        
        # Hysteresis curve - with trigger points marked
        plt.subplot(3, 1, 2)
        plt.plot(vin, vout, 'g-', label='Transfer Curve')
        plt.plot(trigger_vin_rising, threshold, 'bo', markersize=8, 
                 label=f'Rising Trigger: {trigger_vin_rising:.3f}V')
        plt.plot(trigger_vin_falling, threshold, 'ro', markersize=8, 
                 label=f'Falling Trigger: {trigger_vin_falling:.3f}V')
        plt.axhline(y=threshold, color='k', linestyle='--')
        plt.legend()
        plt.title(f'Hysteresis Curve (Width: {hysteresis_width:.3f}V)')
        plt.xlabel('Vin [V]')
        plt.ylabel('Vout [V]')
        plt.grid(True)
        
        # Separate rising and falling responses
        plt.subplot(3, 1, 3)
        plt.plot(vin_rising, vout_rising, 'b-', label='Rising Edge')
        plt.plot(vin_falling, vout_falling, 'r-', label='Falling Edge')
        plt.plot(trigger_vin_rising, threshold, 'bo', markersize=8)
        plt.plot(trigger_vin_falling, threshold, 'ro', markersize=8)
        plt.axhline(y=threshold, color='k', linestyle='--', label='Threshold')
        plt.legend()
        plt.title('Rising vs Falling Response with Trigger Points')
        plt.xlabel('Vin [V]')
        plt.ylabel('Vout [V]')
        plt.grid(True)
        
        plt.tight_layout()
        plt.savefig("p28_waveform.png")
    else:
        print("Analysis could not be completed as one or more trigger points were not detected.")
        sys.exit(2)

except Exception as e:
    print(f"Error analyzing trigger points: {e}")
    sys.exit(2)
    # import traceback
    # traceback.print_exc()

print("Simulation and analysis completed successfully!")
sys.exit(0)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Initialize the circuit
circuit = Circuit('Common-Drain Amplifier (Source Follower)')

# Define the supply voltage Vdd = 5V
circuit.V(1, 'Vdd', circuit.gnd, 5@u_V)

# Define the input voltage signal (DC = 0V, AC = 1V, Sinusoidal at 1kHz)
circuit.SinusoidalVoltageSource('Vin', 'input', circuit.gnd, 
                                amplitude=1@u_V, frequency=1@u_kHz)

# Input coupling capacitor (C1) from input to gate
circuit.C(1, 'input', 'gate', 1@u_uF)

# Bias resistors
circuit.R(2, 'Vdd', 'gate', 100@u_kΩ)  # Resistor R2
circuit.R(3, 'gate', circuit.gnd, 100@u_kΩ)  # Resistor R3

# NMOS transistor definition
circuit.MOSFET('M1', 'Vdd', 'gate', 'output', circuit.gnd, model='NMOS')

# Load resistor at the source (R1)
circuit.R(1, 'output', circuit.gnd, 1@u_kΩ)

# Output coupling capacitor (C2)
circuit.C(2, 'output', circuit.gnd, 1@u_uF)

# NMOS transistor model
circuit.model('NMOS', 'nmos', kp=0.00012, l=1e-6, lambda_=0.02, vto=1, w=1e-5)

# Set up the AC and transient simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Run transient analysis (step time = 1 µs, end time = 5 ms)
analysis_transient = simulator.transient(step_time=1@u_us, end_time=5@u_ms)

# Run AC analysis (from 1 Hz to 1 MHz)
analysis_ac = simulator.ac(start_frequency=1@u_Hz, stop_frequency=1@u_MHz, number_of_points=1000,variation='dec')

# Plot the transient response
plt.figure()
plt.plot(analysis_transient.time, analysis_transient['input'], label='Input (Vin)')
plt.plot(analysis_transient.time, analysis_transient['output'], label='Output (Vout)')
plt.title('Transient Analysis of Common-Drain Amplifier (Source Follower)')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid()
plt.show()

# Plot the AC response (magnitude in dB)
plt.figure()
plt.plot(analysis_ac.frequency, 20*np.log10(np.absolute(analysis_ac['output'])))
plt.title('AC Analysis of Common-Drain Amplifier (Source Follower)')
plt.xlabel('Frequency [Hz]')
plt.ylabel('Gain [dB]')
plt.grid()
plt.show()
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Library import SpiceLibrary
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS Inverter circuit
circuit = Circuit('CMOS Inverter')

# Define the power supply and input voltage source
# VDD connected between vdd and ground
circuit.V('dd', 'vdd', circuit.gnd, 5@u_V)

# Input pulse for switching behavior
# Pulse parameters: initial value, pulsed value, delay, rise time, fall time, pulse width, period
circuit.PulseVoltageSource('in', 'input', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Define NMOS and PMOS transistors
# PMOS: drain, gate, source, bulk
circuit.MOSFET('M1', 'output', 'input', 'vdd', 'vdd', model='PMOS')

# NMOS: drain, gate, source, bulk
circuit.MOSFET('M2', 'output', 'input', circuit.gnd, circuit.gnd, model='NMOS')

# Define MOSFET models with appropriate parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,    # Transconductance parameter
    vto=0.7,      # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=10e-6,      # Channel width
    l=1e-6        # Channel length
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=60e-6,     # Transconductance parameter (half of NMOS due to mobility)
    vto=-0.7,     # Threshold voltage (negative for PMOS)
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=20e-6,      # Channel width (2x NMOS to compensate for mobility)
    l=1e-6        # Channel length
)

print(circuit)
# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Add simulation options for convergence
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=100@u_ns)

    # Create plot
    plt.figure(figsize=(10, 6))
    
    # Plot input voltage
    plt.plot(analysis.time, analysis['input'], 
             label='Input', linestyle='--', color='blue')
    
    # Plot output voltage
    plt.plot(analysis.time, analysis['output'], 
             label='Output', color='red')
    
    # Customize plot
    plt.grid(True)
    plt.title('CMOS Inverter Transient Analysis')
    plt.xlabel('Time (s)')
    plt.ylabel('Voltage (V)')
    plt.legend()

    plt.ylim(-0.5, 5.5)
    
    # Show plot
    plt.show()

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Library import SpiceLibrary
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS NAND Gate circuit
circuit = Circuit('CMOS NAND Gate')

# Define power supply
circuit.V('dd', 'vdd', circuit.gnd, 5@u_V)

# Define input voltage sources
# Input A: Full period pulse
circuit.PulseVoltageSource('inA', 'inputA', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B: Half period pulse
circuit.PulseVoltageSource('inB', 'inputB', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Define PMOS transistors in parallel
# PMOS1: Connected to inputA
circuit.MOSFET('M1', 'output', 'inputA', 'vdd', 'vdd', model='PMOS')

# PMOS2: Connected to inputB
circuit.MOSFET('M2', 'output', 'inputB', 'vdd', 'vdd', model='PMOS')

# Define NMOS transistors in series
# NMOS1: Connected to inputA and intermediate node
circuit.MOSFET('M3', 'output', 'inputA', 'intermediate', circuit.gnd, model='NMOS')

# NMOS2: Connected to inputB and ground
circuit.MOSFET('M4', 'intermediate', 'inputB', circuit.gnd, circuit.gnd, model='NMOS')

# Define MOSFET models
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,    # Transconductance parameter
    vto=0.7,      # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=10e-6,      # Channel width
    l=1e-6        # Channel length
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=60e-6,     # Transconductance parameter
    vto=-0.7,     # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=20e-6,      # Channel width (2x NMOS width)
    l=1e-6        # Channel length
)

# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Add simulation options for better convergence
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=160@u_ns)

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Plot inputs on first subplot
    ax1.plot(analysis.time, analysis['inputA'], 
             label='Input A', linestyle='--', color='blue')
    ax1.plot(analysis.time, analysis['inputB'], 
             label='Input B', linestyle='--', color='green')
    ax1.grid(True)
    ax1.set_title('CMOS NAND Gate - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 5.5)
    
    # Plot output on second subplot
    ax2.plot(analysis.time, analysis['output'], 
             label='Output', color='red')
    ax2.grid(True)
    ax2.set_title('CMOS NAND Gate - Output')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 5.5)
    
    # Adjust layout and display
    plt.tight_layout()
    plt.show()

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")

# Optional: Add timing analysis
def analyze_timing(analysis):
    """Calculate propagation delays and transition times"""
    vdd = 5.0
    v_th = vdd / 2  # Threshold voltage for timing measurements
    
    # Find rising and falling edges
    edges = {
        'input_a': np.where(np.diff(analysis['inputA'] > v_th))[0],
        'input_b': np.where(np.diff(analysis['inputB'] > v_th))[0],
        'output': np.where(np.diff(analysis['output'] > v_th))[0]
    }
    
    # Calculate propagation delays
    prop_delays = []
    for i in range(min(len(edges['input_a']), len(edges['output']))):
        delay = abs(analysis.time[edges['output'][i]] - 
                   analysis.time[edges['input_a'][i]])
        prop_delays.append(float(delay))
    
    print(f"Average propagation delay: {np.mean(prop_delays):.2e} seconds")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Probe.Plot import plot
import matplotlib.pyplot as plt

# Create a new circuit
circuit = Circuit('CMOS NAND Gate')

# Define the power supply (Vdd = 5V)
circuit.V(1, 'Vdd', circuit.gnd, 5@u_V)

# Define input voltage sources (Pulse for both inputs)
circuit.PulseVoltageSource('Vin1', 'input1', circuit.gnd, 
                           initial_value=0@u_V, pulsed_value=5@u_V, 
                           rise_time=1@u_ns, fall_time=1@u_ns, 
                           pulse_width=20@u_ns, period=40@u_ns)

circuit.PulseVoltageSource('Vin2', 'input2', circuit.gnd, 
                           initial_value=0@u_V, pulsed_value=5@u_V, 
                           rise_time=1@u_ns, fall_time=1@u_ns, 
                           pulse_width=20@u_ns, period=80@u_ns)

# Define the two PMOS transistors in parallel
circuit.MOSFET('P1', 'Vdd', 'input1', 'output', 'Vdd', model='PMOS')
circuit.MOSFET('P2', 'Vdd', 'input2', 'output', 'Vdd', model='PMOS')

# Define the two NMOS transistors in series
circuit.MOSFET('N1', 'output', 'input1', 'n1', circuit.gnd, model='NMOS')
circuit.MOSFET('N2', 'n1', 'input2', circuit.gnd, circuit.gnd, model='NMOS')

# Define the NMOS and PMOS transistor models
circuit.model('NMOS', 'nmos', kp=120e-6, vto=1, lambda_=0.02, w=10e-6, l=1e-6)
circuit.model('PMOS', 'pmos', kp=60e-6, vto=-1, lambda_=0.02, w=20e-6, l=1e-6)

# Set up the transient analysis
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
analysis = simulator.transient(step_time=10@u_ns, end_time=200@u_ns)

# Plot the input and output signals
fig, axs = plt.subplots(3, 1, sharex=True)  # Create 3 subplots, sharing the x-axis

# Input 1
axs[0].plot(analysis.time, analysis['input1'], label='Input 1', color='blue')
axs[0].set_ylabel('Voltage [V]')
axs[0].legend()
axs[0].grid()

# Input 2
axs[1].plot(analysis.time, analysis['input2'], label='Input 2', color='orange')
axs[1].set_ylabel('Voltage [V]')
axs[1].legend()
axs[1].grid()

# Output
axs[2].plot(analysis.time, analysis['output'], label='Output (NAND)', color='green')
axs[2].set_xlabel('Time [s]')
axs[2].set_ylabel('Voltage [V]')
axs[2].legend()
axs[2].grid()

fig.suptitle('CMOS NAND Gate Transient Analysis')  # Overall title for the figure

plt.tight_layout()  # Adjust spacing to prevent overlap
plt.show()
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Library import SpiceLibrary
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS NOR Gate circuit
circuit = Circuit('CMOS NOR Gate')

# Define power supply
circuit.V('dd', 'vdd', circuit.gnd, 5@u_V)

# Define input voltage sources
# Input A: Full period pulse
circuit.PulseVoltageSource('inA', 'inputA', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B: Half period pulse
circuit.PulseVoltageSource('inB', 'inputB', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Define PMOS transistors in series
# PMOS1: Connected to inputA and VDD
circuit.MOSFET('M1', 'intermediate', 'inputA', 'vdd', 'vdd', model='PMOS')

# PMOS2: Connected to inputB and intermediate node
circuit.MOSFET('M2', 'output', 'inputB', 'intermediate', 'vdd', model='PMOS')

# Define NMOS transistors in parallel
# NMOS1: Connected to inputA
circuit.MOSFET('M3', 'output', 'inputA', circuit.gnd, circuit.gnd, model='NMOS')

# NMOS2: Connected to inputB
circuit.MOSFET('M4', 'output', 'inputB', circuit.gnd, circuit.gnd, model='NMOS')

# Define MOSFET models
# PMOS width is increased to 40µm (4x NMOS) because they're in series
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,    # Transconductance parameter
    vto=0.7,      # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=10e-6,      # Channel width
    l=1e-6        # Channel length
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=60e-6,     # Transconductance parameter
    vto=-0.7,     # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=40e-6,      # Channel width (4x NMOS width due to series connection)
    l=1e-6        # Channel length
)

# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Add simulation options for better convergence
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=160@u_ns)

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Plot inputs on first subplot
    ax1.plot(analysis.time, analysis['inputA'], 
             label='Input A', linestyle='--', color='blue')
    ax1.plot(analysis.time, analysis['inputB'], 
             label='Input B', linestyle='--', color='green')
    ax1.grid(True)
    ax1.set_title('CMOS NOR Gate - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 5.5)
    
    # Plot output on second subplot
    ax2.plot(analysis.time, analysis['output'], 
             label='Output', color='red')
    ax2.grid(True)
    ax2.set_title('CMOS NOR Gate - Output')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 5.5)
    
    # Add truth table annotation
    truth_table = """
    NOR Truth Table
    A B | Out
    0 0 | 1
    0 1 | 0
    1 0 | 0
    1 1 | 0
    """
    plt.figtext(1.02, 0.5, truth_table, fontfamily='monospace')
    
    # Adjust layout and display
    plt.tight_layout()
    plt.show()

    # Calculate and display timing characteristics
    def analyze_timing(analysis):
        """Calculate rise time, fall time, and propagation delay"""
        vdd = 5.0
        v_low = 0.1 * vdd
        v_high = 0.9 * vdd
        
        # Find transitions
        output = analysis['output']
        time = analysis.time
        
        # Find rising and falling edges
        rising_edges = []
        falling_edges = []
        
        for i in range(1, len(output)):
            if output[i-1] < v_low and output[i] > v_high:
                rising_edges.append(i)
            elif output[i-1] > v_high and output[i] < v_low:
                falling_edges.append(i)
        
        # Calculate average rise and fall times
        rise_times = []
        fall_times = []
        
        for edge in rising_edges:
            rise_time = float(time[edge] - time[edge-1])
            rise_times.append(rise_time)
            
        for edge in falling_edges:
            fall_time = float(time[edge] - time[edge-1])
            fall_times.append(fall_time)
            
        if rise_times:
            print(f"Average rise time: {np.mean(rise_times):.2e} seconds")
        if fall_times:
            print(f"Average fall time: {np.mean(fall_times):.2e} seconds")
    
    analyze_timing(analysis)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
from PySpice.Probe.Plot import plot

# Create the circuit
circuit = Circuit('CMOS NOR Gate')

# Supply voltage (Vdd)
circuit.V(1, 'Vdd', circuit.gnd, 5@u_V)

# Inputs
circuit.PulseVoltageSource('Vin1', 'input1', circuit.gnd, initial_value=0@u_V, pulsed_value=5@u_V, rise_time=1@u_ns, fall_time=1@u_ns, pulse_width=20@u_ns, period=40@u_ns)
circuit.PulseVoltageSource('Vin2', 'input2', circuit.gnd, initial_value=0@u_V, pulsed_value=5@u_V, rise_time=1@u_ns, fall_time=1@u_ns, pulse_width=20@u_ns, period=40@u_ns)

# Define NMOS transistors (parallel connection)
circuit.MOSFET('M1', 'output', 'input1', circuit.gnd, circuit.gnd, model='NMOS')  # NMOS1
circuit.MOSFET('M2', 'output', 'input2', circuit.gnd, circuit.gnd, model='NMOS')  # NMOS2

# Define PMOS transistors (series connection)
circuit.MOSFET('M3', 'output', 'input1', 'Vdd', 'Vdd', model='PMOS')  # PMOS1
circuit.MOSFET('M4', 'output', 'input2', 'Vdd', 'Vdd', model='PMOS')  # PMOS2

# Define MOSFET models
circuit.model('NMOS', 'nmos', kp=120e-6, vto=1, lambda_=0.02, w=10e-6, l=1e-6)
circuit.model('PMOS', 'pmos', kp=60e-6, vto=-1, lambda_=0.02, w=20e-6, l=1e-6)

# Simulation settings: Transient analysis
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
analysis = simulator.transient(step_time=10@u_ns, end_time=100@u_ns)

# Plot output
plt.figure()
plt.plot(analysis.time, analysis['output'], label='Vout (NOR Gate Output)')
plt.plot(analysis.time, analysis['input1'], label='Vin1')
plt.plot(analysis.time, analysis['input2'], label='Vin2')
plt.title('Transient Analysis of CMOS NOR Gate')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid()
plt.show()
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Library import SpiceLibrary
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS NOR Gate circuit
circuit = Circuit('CMOS NOR Gate')

# Define power supply
circuit.V('dd', 'vdd', circuit.gnd, 5@u_V)

# Define input voltage sources
# Input A: Full period pulse
circuit.PulseVoltageSource('inA', 'inputA', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B: Half period pulse
circuit.PulseVoltageSource('inB', 'inputB', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=5@u_V,
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Define PMOS transistors in series
# PMOS1: Connected to inputA and VDD
circuit.MOSFET('M1', 'intermediate', 'inputA', 'vdd', 'vdd', model='PMOS')

# PMOS2: Connected to inputB and intermediate node
circuit.MOSFET('M2', 'output', 'inputB', 'intermediate', 'vdd', model='PMOS')

# Define NMOS transistors in parallel
# NMOS1: Connected to inputA
circuit.MOSFET('M3', 'output', 'inputA', circuit.gnd, circuit.gnd, model='NMOS')

# NMOS2: Connected to inputB
circuit.MOSFET('M4', 'output', 'inputB', circuit.gnd, circuit.gnd, model='NMOS')

# Define MOSFET models
# PMOS width is increased to 40µm (4x NMOS) because they're in series
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,    # Transconductance parameter
    vto=0.7,      # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=10e-6,      # Channel width
    l=1e-6        # Channel length
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=60e-6,     # Transconductance parameter
    vto=-0.7,     # Threshold voltage
    lambda_=0.02, # Channel length modulation
    gamma=0.37,   # Body effect parameter
    phi=0.65,     # Surface potential
    w=40e-6,      # Channel width (4x NMOS width due to series connection)
    l=1e-6        # Channel length
)

# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Add simulation options for better convergence
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=160@u_ns)

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Plot inputs on first subplot
    ax1.plot(analysis.time, analysis['inputA'], 
             label='Input A', linestyle='--', color='blue')
    ax1.plot(analysis.time, analysis['inputB'], 
             label='Input B', linestyle='--', color='green')
    ax1.grid(True)
    ax1.set_title('CMOS NOR Gate - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 5.5)
    
    # Plot output on second subplot
    ax2.plot(analysis.time, analysis['output'], 
             label='Output', color='red')
    ax2.grid(True)
    ax2.set_title('CMOS NOR Gate - Output')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 5.5)
    
    # Add truth table annotation
    truth_table = """
    NOR Truth Table
    A B | Out
    0 0 | 1
    0 1 | 0
    1 0 | 0
    1 1 | 0
    """
    plt.figtext(1.02, 0.5, truth_table, fontfamily='monospace')
    
    # Adjust layout and display
    plt.tight_layout()
    plt.show()

    # Calculate and display timing characteristics
    def analyze_timing(analysis):
        """Calculate rise time, fall time, and propagation delay"""
        vdd = 5.0
        v_low = 0.1 * vdd
        v_high = 0.9 * vdd
        
        # Convert to numpy arrays to avoid UnitValue comparison issues
        output = np.array(analysis['output'])
        time = np.array(analysis.time)
        
        # Find rising and falling edges
        rising_edges = []
        falling_edges = []
        
        for i in range(1, len(output)):
            if output[i-1] < v_low and output[i] > v_high:
                rising_edges.append(i)
            elif output[i-1] > v_high and output[i] < v_low:
                falling_edges.append(i)
        
        # Calculate average rise and fall times
        rise_times = []
        fall_times = []
        
        for edge in rising_edges:
            rise_time = time[edge] - time[edge-1]
            rise_times.append(rise_time)
            
        for edge in falling_edges:
            fall_time = time[edge] - time[edge-1]
            fall_times.append(fall_time)
            
        if rise_times:
            print(f"Average rise time: {np.mean(rise_times):.2e} seconds")
        if fall_times:
            print(f"Average fall time: {np.mean(fall_times):.2e} seconds")
    
    analyze_timing(analysis)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the SR Latch circuit
circuit = Circuit('SR Latch')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=250@u_ns,
    period=250@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delayed start
# Set input pulse
circuit.PulseVoltageSource('set', 'S', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=10@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=30@u_ns,
    period=100@u_ns
)

# Reset input pulse
circuit.PulseVoltageSource('reset', 'R', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=60@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=30@u_ns,
    period=100@u_ns
)

# Add input protection and parasitic capacitance
for node in ['S', 'R']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# NOR Gate 1 (Set side)
# PMOS transistors in series
circuit.MOSFET('M1', 'int1', 'S_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'Q', 'Qbar', 'int1', 'vdd_internal', model='PMOS')
circuit.C('CQ', 'Q', circuit.gnd, 0.1@u_pF)

# NMOS transistors in parallel
circuit.MOSFET('M3', 'Q', 'S_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M4', 'Q', 'Qbar', circuit.gnd, circuit.gnd, model='NMOS')

# NOR Gate 2 (Reset side)
# PMOS transistors in series
circuit.MOSFET('M5', 'int2', 'R_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'Qbar', 'Q', 'int2', 'vdd_internal', model='PMOS')
circuit.C('CQbar', 'Qbar', circuit.gnd, 0.1@u_pF)

# NMOS transistors in parallel
circuit.MOSFET('M7', 'Qbar', 'R_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M8', 'Qbar', 'Q', circuit.gnd, circuit.gnd, model='NMOS')

# Add weak pull-up/pull-down resistors for initial state
circuit.R('RQ_pu', 'Q', 'vdd_internal', 1@u_MΩ)
circuit.R('RQbar_pd', 'Qbar', circuit.gnd, 1@u_MΩ)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=200@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    vs = np.array([float(v) for v in analysis['S']])
    vr = np.array([float(v) for v in analysis['R']])
    vq = np.array([float(v) for v in analysis['Q']])
    vqbar = np.array([float(v) for v in analysis['Qbar']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, vs, label='Set', linestyle='--', color='blue')
    ax1.plot(time, vr, label='Reset', linestyle='--', color='red')
    ax1.grid(True)
    ax1.set_title('SR Latch - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs
    ax2.plot(time, vq, label='Q', color='green')
    ax2.plot(time, vqbar, label='Qbar', color='orange')
    ax2.grid(True)
    ax2.set_title('SR Latch - Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Analyze timing characteristics
    def analyze_timing(time, vs, vr, vq, vqbar, vth=1.65):
        """Calculate propagation delays and verify functionality"""
        def find_edges(time, signal, rising=True):
            edges = []
            for i in range(1, len(signal)):
                if rising and signal[i-1] < vth < signal[i]:
                    edges.append(i)
                elif not rising and signal[i-1] > vth > signal[i]:
                    edges.append(i)
            return edges

        # Find rising and falling edges
        s_edges = find_edges(time, vs, rising=True)
        r_edges = find_edges(time, vr, rising=True)
        q_edges_r = find_edges(time, vq, rising=True)
        q_edges_f = find_edges(time, vq, rising=False)

        # Calculate delays
        set_delays = []
        reset_delays = []

        for s_edge in s_edges:
            for q_edge in q_edges_r:
                if q_edge > s_edge:
                    delay = time[q_edge] - time[s_edge]
                    set_delays.append(delay)
                    break

        for r_edge in r_edges:
            for q_edge in q_edges_f:
                if q_edge > r_edge:
                    delay = time[q_edge] - time[r_edge]
                    reset_delays.append(delay)
                    break

        if set_delays:
            print(f"Average Set-to-Q delay: {np.mean(set_delays):.2e} seconds")
        if reset_delays:
            print(f"Average Reset-to-Q delay: {np.mean(reset_delays):.2e} seconds")

    analyze_timing(time, vs, vr, vq, vqbar)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
from PySpice.Probe.Plot import plot

# Create the circuit
circuit = Circuit('CMOS Buffer')

# Supply voltage (Vdd)
circuit.V(1, 'Vdd', circuit.gnd, 5@u_V)

# Input signal
circuit.PulseVoltageSource('Vin', 'input', circuit.gnd, initial_value=0@u_V, pulsed_value=5@u_V, rise_time=1@u_ns, fall_time=1@u_ns, pulse_width=20@u_ns, period=40@u_ns)

# First Inverter (Inverter 1)
# PMOS transistor
circuit.MOSFET('PM1', 'out1', 'input', 'Vdd', 'Vdd', model='PMOS')
# NMOS transistor
circuit.MOSFET('NM1', 'out1', 'input', circuit.gnd, circuit.gnd, model='NMOS')

# Second Inverter (Inverter 2, connected to the output of the first)
# PMOS transistor
circuit.MOSFET('PM2', 'output', 'out1', 'Vdd', 'Vdd', model='PMOS')
# NMOS transistor
circuit.MOSFET('NM2', 'output', 'out1', circuit.gnd, circuit.gnd, model='NMOS')

# Define MOSFET models (NMOS and PMOS)
circuit.model('NMOS', 'nmos', kp=120e-6, vto=1, lambda_=0.02, w=10e-6, l=1e-6)
circuit.model('PMOS', 'pmos', kp=60e-6, vto=-1, lambda_=0.02, w=20e-6, l=1e-6)

# Simulation settings: Transient analysis
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
analysis = simulator.transient(step_time=1@u_ns, end_time=100@u_ns)

# Plot input and output signals
plt.figure()
plt.plot(analysis.time, analysis['input'], label='Vin (Input)')
plt.plot(analysis.time, analysis['output'], label='Vout (Buffered Output)')
plt.title('Transient Analysis of CMOS Buffer')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid()
plt.show()
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the CMOS Buffer circuit
circuit = Circuit('CMOS Buffer')

# Define power supply
Vdd = 5
circuit.V('dd', 'vdd', circuit.gnd, Vdd@u_V)

# Define input voltage source
circuit.PulseVoltageSource('in', 'input', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=Vdd@u_V,
    delay_time=0@u_ns,
    rise_time=5@u_ns,
    fall_time=5@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Add noise to the input
circuit.SinusoidalVoltageSource('noise', 'input_noisy', 'input',
    amplitude=0.5@u_V,
    frequency=50@u_MHz
)

# First Inverter Stage
circuit.MOSFET('M1', 'intermediate', 'input_noisy', 'vdd', 'vdd', model='PMOS1')
circuit.MOSFET('M2', 'intermediate', 'input_noisy', circuit.gnd, circuit.gnd, model='NMOS1')

# Second Inverter Stage
circuit.MOSFET('M3', 'output', 'intermediate', 'vdd', 'vdd', model='PMOS2')
circuit.MOSFET('M4', 'output', 'intermediate', circuit.gnd, circuit.gnd, model='NMOS2')

# Define MOSFET models - first stage
circuit.model('NMOS1', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=10e-6,
    l=1e-6
)

circuit.model('PMOS1', 'pmos',
    level=1,
    kp=60e-6,
    vto=-0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=20e-6,
    l=1e-6
)

# Define MOSFET models - second stage
circuit.model('NMOS2', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=20e-6,
    l=1e-6
)

circuit.model('PMOS2', 'pmos',
    level=1,
    kp=60e-6,
    vto=-0.7,
    lambda_=0.02,
    gamma=0.37,
    phi=0.65,
    w=40e-6,
    l=1e-6
)

# Create simulator
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

try:
    # Run transient analysis
    analysis = simulator.transient(step_time=0.1@u_ns, end_time=160@u_ns)
    
    # Convert analysis results to numpy arrays for easier processing
    time = np.array([float(t) for t in analysis.time])
    input_signal = np.array([float(v) for v in analysis['input']])
    input_noisy = np.array([float(v) for v in analysis['input_noisy']])
    intermediate = np.array([float(v) for v in analysis['intermediate']])
    output = np.array([float(v) for v in analysis['output']])
    
    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # Plot input signals
    ax1.plot(time, input_signal, label='Clean Input', linestyle='--', color='blue')
    ax1.plot(time, input_noisy, label='Noisy Input', color='red', alpha=0.7)
    ax1.grid(True)
    ax1.set_title('CMOS Buffer - Input Signals')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-1, 6)
    
    # Plot intermediate and output signals
    ax2.plot(time, intermediate, label='Intermediate', linestyle='--', color='green')
    ax2.plot(time, output, label='Buffered Output', color='purple')
    ax2.grid(True)
    ax2.set_title('CMOS Buffer - Internal Node and Output')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-1, 6)
    
    plt.tight_layout()
    plt.show()

    # Analyze buffer characteristics
    def analyze_buffer(time, input_signal, output, vdd=5.0):
        v_low = 0.1 * vdd
        v_high = 0.9 * vdd
        
        def find_crossings(signal, threshold, rising=True):
            crossings = []
            for i in range(1, len(signal)):
                if rising:
                    if signal[i-1] < threshold < signal[i]:
                        crossings.append(i)
                else:
                    if signal[i-1] > threshold > signal[i]:
                        crossings.append(i)
            return crossings
        
        # Find rising and falling transitions
        input_rise = find_crossings(input_signal, v_high, rising=True)
        input_fall = find_crossings(input_signal, v_low, rising=False)
        output_rise = find_crossings(output, v_high, rising=True)
        output_fall = find_crossings(output, v_low, rising=False)
        
        # Calculate delays
        rise_delays = []
        fall_delays = []
        
        for in_idx, out_idx in zip(input_rise, output_rise):
            delay = time[out_idx] - time[in_idx]
            rise_delays.append(delay)
            
        for in_idx, out_idx in zip(input_fall, output_fall):
            delay = time[out_idx] - time[in_idx]
            fall_delays.append(delay)
        
        # Print results
        if rise_delays:
            print(f"Average rise propagation delay: {np.mean(rise_delays):.2e} seconds")
        if fall_delays:
            print(f"Average fall propagation delay: {np.mean(fall_delays):.2e} seconds")
        
        # Calculate noise reduction
        input_noise = np.std(input_signal)
        output_noise = np.std(output)
        noise_reduction = (1 - output_noise/input_noise) * 100
        print(f"Noise reduction: {noise_reduction:.1f}%")
    
    analyze_buffer(time, input_noisy, output)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Try adjusting simulation parameters or check circuit connections.")

print(circuit)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the Ring Oscillator circuit
circuit = Circuit('3-Stage Ring Oscillator')

# Define power supply with ramp-up to improve convergence
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=100@u_ns,
    period=100@u_ns
)

# Add small resistor in series with Vdd for better convergence
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)

# First Inverter Stage
circuit.MOSFET('M1', 'node1', 'node3', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'node1', 'node3', circuit.gnd, circuit.gnd, model='NMOS')
circuit.R('R1', 'node1', 'vdd_internal', 100@u_kΩ)  # Pull-up to help start oscillation

# Second Inverter Stage
circuit.MOSFET('M3', 'node2', 'node1', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M4', 'node2', 'node1', circuit.gnd, circuit.gnd, model='NMOS')

# Third Inverter Stage
circuit.MOSFET('M5', 'node3', 'node2', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'node3', 'node2', circuit.gnd, circuit.gnd, model='NMOS')

# Add parasitic capacitance
circuit.C('C1', 'node1', circuit.gnd, 0.5@u_pF)
circuit.C('C2', 'node2', circuit.gnd, 0.5@u_pF)
circuit.C('C3', 'node3', circuit.gnd, 0.5@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'  # Use Gear integration method for better stability
)

try:
    # Run transient analysis with modified parameters
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=50@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    v1 = np.array([float(v) for v in analysis['node1']])
    v2 = np.array([float(v) for v in analysis['node2']])
    v3 = np.array([float(v) for v in analysis['node3']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot node voltages
    ax1.plot(time, v1, label='Node 1', color='blue')
    ax1.plot(time, v2, label='Node 2', color='red')
    ax1.plot(time, v3, label='Node 3', color='green')
    ax1.grid(True)
    ax1.set_title('Ring Oscillator - Node Voltages')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Calculate and plot oscillation frequency
    def calculate_frequency(time, voltage, threshold=1.65):
        crossings = np.where(np.diff(voltage > threshold))[0]
        if len(crossings) >= 2:
            periods = np.diff(time[crossings])
            freq = 1.0 / np.mean(periods)
            return freq
        return None

    # Plot FFT of node3 (output)
    if len(time) > 1:
        sampling_rate = 1.0 / (time[1] - time[0])
        n = len(v3)
        freqs = np.fft.fftfreq(n, 1/sampling_rate)
        fft_v3 = np.abs(np.fft.fft(v3))
        
        # Plot only positive frequencies
        mask = freqs > 0
        ax2.plot(freqs[mask], fft_v3[mask])
        ax2.grid(True)
        ax2.set_title('Frequency Spectrum')
        ax2.set_xlabel('Frequency (Hz)')
        ax2.set_ylabel('Magnitude')
        ax2.set_xscale('log')

    plt.tight_layout()
    plt.show()

    # Calculate and display oscillation characteristics
    freq = calculate_frequency(time, v3)
    if freq is not None:
        print(f"Oscillation Frequency: {freq/1e6:.2f} MHz")
        print(f"Period: {1000/freq:.2f} ns")

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the Full Adder circuit
circuit = Circuit('CMOS Full Adder')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=200@u_ns,
    period=200@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delays to ensure power-up completes first
# Input A
circuit.PulseVoltageSource('inA', 'A', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B
circuit.PulseVoltageSource('inB', 'B', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Carry In
circuit.PulseVoltageSource('inCin', 'Cin', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=10@u_ns,
    period=20@u_ns
)

# Add input protection and parasitic capacitance
for node in ['A', 'B', 'Cin']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# XOR gate for A ⊕ B
# NAND1
circuit.MOSFET('M1', 'nand1_out', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'nand1_out', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M3', 'nand1_out', 'A_int', 'nand1_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M4', 'nand1_n', 'B_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C1', 'nand1_out', circuit.gnd, 0.1@u_pF)

# Additional NANDs for XOR implementation
circuit.MOSFET('M5', 'xor_out', 'nand1_out', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'xor_out', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M7', 'xor_out', 'nand1_out', 'xor_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M8', 'xor_n', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C2', 'xor_out', circuit.gnd, 0.1@u_pF)

# Second XOR for Sum (XOR with Cin)
circuit.MOSFET('M9', 'sum_int', 'xor_out', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M10', 'sum_int', 'Cin_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M11', 'sum_int', 'xor_out', 'sum_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M12', 'sum_n', 'Cin_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C3', 'sum_int', circuit.gnd, 0.1@u_pF)

# Carry Out logic
circuit.MOSFET('M13', 'cout_int', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M14', 'cout_int', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M15', 'cout_int', 'Cin_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M16', 'cout_int', 'A_int', 'cout_n1', circuit.gnd, model='NMOS')
circuit.MOSFET('M17', 'cout_n1', 'B_int', 'cout_n2', circuit.gnd, model='NMOS')
circuit.MOSFET('M18', 'cout_n2', 'Cin_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C4', 'cout_int', circuit.gnd, 0.1@u_pF)

# Output buffers
circuit.MOSFET('M19', 'Sum', 'sum_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M20', 'Sum', 'sum_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C5', 'Sum', circuit.gnd, 0.1@u_pF)

circuit.MOSFET('M21', 'Cout', 'cout_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M22', 'Cout', 'cout_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C6', 'Cout', circuit.gnd, 0.1@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=10@u_ns,
        end_time=100@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data
    time = np.array([float(t) for t in analysis.time])
    va = np.array([float(v) for v in analysis['A']])
    vb = np.array([float(v) for v in analysis['B']])
    vcin = np.array([float(v) for v in analysis['Cin']])
    vsum = np.array([float(v) for v in analysis['Sum']])
    vcout = np.array([float(v) for v in analysis['Cout']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, va, label='A', linestyle='--')
    ax1.plot(time, vb, label='B', linestyle='--')
    ax1.plot(time, vcin, label='Cin', linestyle='--')
    ax1.grid(True)
    ax1.set_title('Full Adder - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs
    ax2.plot(time, vsum, label='Sum')
    ax2.plot(time, vcout, label='Cout')
    ax2.grid(True)
    ax2.set_title('Full Adder - Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Verify functionality
    def analyze_full_adder(time, va, vb, vcin, vsum, vcout, vth=1.65):
        """Verify full adder logic and calculate delays"""
        def to_binary(v):
            return 1 if v > vth else 0
        
        def find_transitions(time, signal):
            binary = [to_binary(v) for v in signal]
            transitions = []
            for i in range(1, len(binary)):
                if binary[i] != binary[i-1]:
                    transitions.append(time[i])
            return transitions
        
        # Calculate propagation delays
        a_trans = find_transitions(time, va)
        sum_trans = find_transitions(time, vsum)
        cout_trans = find_transitions(time, vcout)
        
        if a_trans and sum_trans:
            sum_delay = min(abs(st - at) for st in sum_trans for at in a_trans)
            print(f"Average Sum propagation delay: {sum_delay:.2e} seconds")
        
        if a_trans and cout_trans:
            cout_delay = min(abs(ct - at) for ct in cout_trans for at in a_trans)
            print(f"Average Cout propagation delay: {cout_delay:.2e} seconds")

    analyze_full_adder(time, va, vb, vcin, vsum, vcout)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the 2-to-4 Decoder circuit
circuit = Circuit('2-to-4 Decoder')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=400@u_ns,
    period=400@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delayed start
# Input A (LSB)
circuit.PulseVoltageSource('inA', 'A', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=40@u_ns,
    period=80@u_ns
)

# Input B (MSB)
circuit.PulseVoltageSource('inB', 'B', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=1@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=80@u_ns,
    period=160@u_ns
)

# Add input protection and parasitic capacitance
for node in ['A', 'B']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# Inverters for input signals
# Inverter for A
circuit.MOSFET('M1', 'A_inv', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'A_inv', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C1', 'A_inv', circuit.gnd, 0.1@u_pF)

# Inverter for B
circuit.MOSFET('M3', 'B_inv', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M4', 'B_inv', 'B_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C2', 'B_inv', circuit.gnd, 0.1@u_pF)

# Output 0 decoder (B'A')
circuit.MOSFET('M5', 'Y0_int', 'B_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'Y0_int', 'A_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M7', 'Y0_int', 'B_inv', 'Y0_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M8', 'Y0_n', 'A_inv', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C3', 'Y0_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y0
circuit.MOSFET('M9', 'Y0', 'Y0_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M10', 'Y0', 'Y0_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C4', 'Y0', circuit.gnd, 0.1@u_pF)

# Output 1 decoder (B'A)
circuit.MOSFET('M11', 'Y1_int', 'B_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M12', 'Y1_int', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M13', 'Y1_int', 'B_inv', 'Y1_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M14', 'Y1_n', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C5', 'Y1_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y1
circuit.MOSFET('M15', 'Y1', 'Y1_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M16', 'Y1', 'Y1_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C6', 'Y1', circuit.gnd, 0.1@u_pF)

# Output 2 decoder (BA')
circuit.MOSFET('M17', 'Y2_int', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M18', 'Y2_int', 'A_inv', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M19', 'Y2_int', 'B_int', 'Y2_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M20', 'Y2_n', 'A_inv', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C7', 'Y2_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y2
circuit.MOSFET('M21', 'Y2', 'Y2_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M22', 'Y2', 'Y2_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C8', 'Y2', circuit.gnd, 0.1@u_pF)

# Output 3 decoder (BA)
circuit.MOSFET('M23', 'Y3_int', 'B_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M24', 'Y3_int', 'A_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M25', 'Y3_int', 'B_int', 'Y3_n', circuit.gnd, model='NMOS')
circuit.MOSFET('M26', 'Y3_n', 'A_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C9', 'Y3_int', circuit.gnd, 0.1@u_pF)

# Output buffer for Y3
circuit.MOSFET('M27', 'Y3', 'Y3_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M28', 'Y3', 'Y3_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('C10', 'Y3', circuit.gnd, 0.1@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=200@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    va = np.array([float(v) for v in analysis['A']])
    vb = np.array([float(v) for v in analysis['B']])
    vy0 = np.array([float(v) for v in analysis['Y0']])
    vy1 = np.array([float(v) for v in analysis['Y1']])
    vy2 = np.array([float(v) for v in analysis['Y2']])
    vy3 = np.array([float(v) for v in analysis['Y3']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, vb, label='B (MSB)', linestyle='--', color='blue')
    ax1.plot(time, va, label='A (LSB)', linestyle='--', color='red')
    ax1.grid(True)
    ax1.set_title('2-to-4 Decoder - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs
    ax2.plot(time, vy0, label='Y0 (00)', color='purple')
    ax2.plot(time, vy1, label='Y1 (01)', color='orange')
    ax2.plot(time, vy2, label='Y2 (10)', color='green')
    ax2.plot(time, vy3, label='Y3 (11)', color='brown')
    ax2.grid(True)
    ax2.set_title('2-to-4 Decoder - Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Analyze decoder characteristics
    def analyze_decoder(time, va, vb, vy0, vy1, vy2, vy3, vth=1.65):
        """Verify decoder functionality and calculate delays"""
        def to_binary(v):
            return 1 if v > vth else 0
        
        def find_transitions(time, signal):
            binary = [to_binary(v) for v in signal]
            transitions = []
            for i in range(1, len(binary)):
                if binary[i] != binary[i-1]:
                    transitions.append(i)
            return transitions
        
        # Calculate propagation delays
        a_trans = find_transitions(time, va)
        output_delays = []
        
        for t_in in a_trans:
            for signal in [vy0, vy1, vy2, vy3]:
                out_trans = find_transitions(time, signal)
                for t_out in out_trans:
                    if t_out > t_in:
                        delay = time[t_out] - time[t_in]
                        output_delays.append(delay)
                        break
        
        if output_delays:
            print(f"Average propagation delay: {np.mean(output_delays):.2e} seconds")
            print(f"Maximum propagation delay: {np.max(output_delays):.2e} seconds")
            print(f"Minimum propagation delay: {np.min(output_delays):.2e} seconds")

    analyze_decoder(time, va, vb, vy0, vy1, vy2, vy3)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the D Flip-Flop circuit
circuit = Circuit('D Flip-Flop')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=0.5@u_ns,
    fall_time=0.5@u_ns,
    pulse_width=250@u_ns,
    period=250@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Define input voltage sources with delayed start
# Clock signal
circuit.PulseVoltageSource('clk', 'clock', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=2@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=20@u_ns,
    period=40@u_ns
)

# Data input
circuit.PulseVoltageSource('din', 'D', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=5@u_ns,
    rise_time=0.1@u_ns,
    fall_time=0.1@u_ns,
    pulse_width=30@u_ns,
    period=60@u_ns
)

# Add input protection and parasitic capacitance
for node in ['clock', 'D']:
    circuit.R(f'Rin_{node}', node, f'{node}_int', 100@u_Ω)
    circuit.C(f'Cin_{node}', f'{node}_int', circuit.gnd, 0.1@u_pF)

# Create clock inverter
circuit.MOSFET('M1', 'clock_inv', 'clock_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M2', 'clock_inv', 'clock_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('Cclk_inv', 'clock_inv', circuit.gnd, 0.1@u_pF)

# Master stage
# Input inverter
circuit.MOSFET('M3', 'D_inv', 'D_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M4', 'D_inv', 'D_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('CD_inv', 'D_inv', circuit.gnd, 0.1@u_pF)

# Master latch
circuit.MOSFET('M5', 'master_int', 'D_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M6', 'master_int', 'clock_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M7', 'master_out', 'master_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M8', 'master_out', 'master_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('Cmaster', 'master_out', circuit.gnd, 0.1@u_pF)

# Slave stage
circuit.MOSFET('M9', 'slave_int', 'master_out', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M10', 'slave_int', 'clock_inv', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M11', 'Q', 'slave_int', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M12', 'Q', 'slave_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('CQ', 'Q', circuit.gnd, 0.1@u_pF)

# Output inverter for Q_bar
circuit.MOSFET('M13', 'Q_bar', 'Q', 'vdd_internal', 'vdd_internal', model='PMOS')
circuit.MOSFET('M14', 'Q_bar', 'Q', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('CQbar', 'Q_bar', circuit.gnd, 0.1@u_pF)

# Add weak pull-up/pull-down for initialization
circuit.R('Rpd_master', 'master_int', circuit.gnd, 1@u_MΩ)
circuit.R('Rpd_slave', 'slave_int', circuit.gnd, 1@u_MΩ)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=2e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=6e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=200@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    vclk = np.array([float(v) for v in analysis['clock']])
    vd = np.array([float(v) for v in analysis['D']])
    vq = np.array([float(v) for v in analysis['Q']])
    vqbar = np.array([float(v) for v in analysis['Q_bar']])
    vmaster = np.array([float(v) for v in analysis['master_out']])

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # Plot inputs
    ax1.plot(time, vclk, label='Clock', color='blue')
    ax1.plot(time, vd, label='D', linestyle='--', color='red')
    ax1.grid(True)
    ax1.set_title('D Flip-Flop - Inputs')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot outputs and internal nodes
    ax2.plot(time, vmaster, label='Master', color='green', alpha=0.5)
    ax2.plot(time, vq, label='Q', color='purple')
    ax2.plot(time, vqbar, label='Q_bar', color='orange')
    ax2.grid(True)
    ax2.set_title('D Flip-Flop - Internal Nodes and Outputs')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    plt.tight_layout()
    plt.show()

    # Analyze timing characteristics
    def analyze_timing(time, vclk, vd, vq, vth=1.65):
        """Calculate setup time, hold time, and clock-to-Q delay"""
        def find_edges(time, signal, rising=True):
            edges = []
            for i in range(1, len(signal)):
                if rising and signal[i-1] < vth < signal[i]:
                    edges.append(i)
                elif not rising and signal[i-1] > vth > signal[i]:
                    edges.append(i)
            return edges

        # Find edges
        clk_edges = find_edges(time, vclk, rising=True)
        d_edges = find_edges(time, vd)
        q_edges = find_edges(time, vq)

        # Calculate delays
        clk_q_delays = []
        setup_times = []
        hold_times = []

        for clk_edge in clk_edges:
            # Clock-to-Q delay
            for q_edge in q_edges:
                if q_edge > clk_edge:
                    delay = time[q_edge] - time[clk_edge]
                    if delay < 10e-9:  # Reasonable delay window
                        clk_q_delays.append(delay)
                    break

            # Setup and hold times
            for d_edge in d_edges:
                if abs(time[d_edge] - time[clk_edge]) < 10e-9:
                    if d_edge < clk_edge:
                        setup_times.append(time[clk_edge] - time[d_edge])
                    else:
                        hold_times.append(time[d_edge] - time[clk_edge])

        if clk_q_delays:
            print(f"Average Clock-to-Q delay: {np.mean(clk_q_delays):.2e} seconds")
        if setup_times:
            print(f"Average setup time: {np.mean(setup_times):.2e} seconds")
        if hold_times:
            print(f"Average hold time: {np.mean(hold_times):.2e} seconds")

    analyze_timing(time, vclk, vd, vq)

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the VCO circuit
circuit = Circuit('Voltage Controlled Oscillator')

# Define power supply with ramp-up
circuit.PulseVoltageSource('dd', 'vdd', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,  # Using 3.3V for better stability
    delay_time=0@u_ns,
    rise_time=1@u_ns,
    fall_time=1@u_ns,
    pulse_width=2500@u_ns,
    period=2500@u_ns
)

# Add supply resistor and decoupling capacitor
circuit.R('Rvdd', 'vdd', 'vdd_internal', 1@u_Ω)
circuit.C('Cvdd', 'vdd_internal', circuit.gnd, 1@u_pF)

# Control voltage source (sweep from 0V to 3.3V)
circuit.PulseVoltageSource('ctrl', 'v_control', circuit.gnd,
    initial_value=0@u_V,
    pulsed_value=3.3@u_V,
    delay_time=5@u_ns,
    rise_time=500@u_ns,
    fall_time=500@u_ns,
    pulse_width=1000@u_ns,
    period=2000@u_ns
)

# Add control voltage protection and filtering
circuit.R('Rctrl', 'v_control', 'v_control_int', 100@u_Ω)
circuit.C('Cctrl', 'v_control_int', circuit.gnd, 0.1@u_pF)

# Current mirror bias circuit
circuit.MOSFET('M1', 'bias', 'bias', circuit.gnd, circuit.gnd, model='NMOS')
circuit.R('Rbias', 'vdd_internal', 'bias', 10@u_kΩ)
circuit.C('Cbias', 'bias', circuit.gnd, 0.1@u_pF)

# Voltage-controlled current source
circuit.MOSFET('M2', 'i_ctrl', 'v_control_int', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET('M3', 'i_ctrl', 'bias', circuit.gnd, circuit.gnd, model='NMOS')
circuit.C('Ci_ctrl', 'i_ctrl', circuit.gnd, 0.1@u_pF)

# Ring oscillator stages with parasitic capacitance
for i in range(1, 4):
    prev_stage = f'stage{3 if i == 1 else i-1}'
    curr_stage = f'stage{i}'
    
    # PMOS
    circuit.MOSFET(f'Mp{i}', curr_stage, prev_stage, 'vdd_internal', 'vdd_internal', model='PMOS')
    # NMOS
    circuit.MOSFET(f'Mn{i}', curr_stage, prev_stage, 'i_ctrl', circuit.gnd, model='NMOS')
    # Load capacitance
    circuit.C(f'C{i}', curr_stage, circuit.gnd, 0.1@u_pF)
    # Weak pull-up for initialization
    circuit.R(f'Rpu{i}', curr_stage, 'vdd_internal', 1@u_MΩ)

# Output buffer
circuit.MOSFET('M10', 'vco_out', 'stage3', 'vdd_internal', 'vdd_internal', model='PMOS_BUF')
circuit.MOSFET('M11', 'vco_out', 'stage3', circuit.gnd, circuit.gnd, model='NMOS_BUF')
circuit.C('Cout', 'vco_out', circuit.gnd, 0.1@u_pF)

# Define MOSFET models with more realistic parameters
circuit.model('NMOS', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=4e-6,
    l=0.35e-6
)

circuit.model('PMOS', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=12e-6,
    l=0.35e-6
)

# Buffer transistors (larger size for driving output load)
circuit.model('NMOS_BUF', 'nmos',
    level=1,
    kp=120e-6,
    vto=0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=8e-6,
    l=0.35e-6
)

circuit.model('PMOS_BUF', 'pmos',
    level=1,
    kp=40e-6,
    vto=-0.7,
    lambda_=0.01,
    gamma=0.4,
    phi=0.65,
    cgso=0.6e-9,
    cgdo=0.6e-9,
    cbd=0.1e-12,
    cbs=0.1e-12,
    w=24e-6,
    l=0.35e-6
)

# Create simulator with modified parameters
simulator = circuit.simulator(temperature=27, nominal_temperature=27)

# Add simulation options for better convergence
simulator.options(
    reltol=1e-3,
    abstol=1e-6,
    vntol=1e-4,
    chgtol=1e-14,
    trtol=7,
    itl1=100,
    itl2=50,
    itl4=50,
    method='gear'
)

try:
    # Run transient analysis
    analysis = simulator.transient(
        step_time=0.1@u_ns,
        end_time=2000@u_ns,
        start_time=0@u_ns,
        max_time=0.2@u_ns,
        use_initial_condition=True
    )

    # Convert time and voltage data to numpy arrays
    time = np.array([float(t) for t in analysis.time])
    vctrl = np.array([float(v) for v in analysis['v_control']])
    vout = np.array([float(v) for v in analysis['vco_out']])

    # Create figure with multiple subplots
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 12))

    # Plot control voltage
    ax1.plot(time, vctrl, label='Control Voltage', color='blue')
    ax1.grid(True)
    ax1.set_title('VCO Control Voltage')
    ax1.set_xlabel('Time (s)')
    ax1.set_ylabel('Voltage (V)')
    ax1.legend()
    ax1.set_ylim(-0.5, 4)

    # Plot output waveform
    ax2.plot(time, vout, label='VCO Output', color='red')
    ax2.grid(True)
    ax2.set_title('VCO Output Waveform')
    ax2.set_xlabel('Time (s)')
    ax2.set_ylabel('Voltage (V)')
    ax2.legend()
    ax2.set_ylim(-0.5, 4)

    # Calculate and plot instantaneous frequency
    def calculate_frequency(time, signal, window_size=100):
        frequencies = []
        times = []
        control_voltages = []
        
        for i in range(0, len(time)-window_size, window_size//2):
            window = signal[i:i+window_size]
            t_window = time[i:i+window_size]
            
            # Count zero crossings
            crossings = np.where(np.diff(window > np.mean(window)))[0]
            if len(crossings) >= 2:
                period = 2 * np.mean(np.diff(t_window[crossings]))
                freq = 1.0 / period if period > 0 else 0
                frequencies.append(freq)
                times.append(np.mean(t_window))
                control_voltages.append(np.mean(vctrl[i:i+window_size]))
        
        return np.array(times), np.array(frequencies), np.array(control_voltages)

    # Calculate frequencies and plot
    t_freq, freqs, v_ctrl = calculate_frequency(time, vout)
    
    if len(t_freq) > 0:
        # Plot frequency vs control voltage
        ax3.plot(v_ctrl, freqs/1e6, 'o-', label='Tuning Characteristic', color='green')
        ax3.grid(True)
        ax3.set_title('VCO Tuning Characteristic')
        ax3.set_xlabel('Control Voltage (V)')
        ax3.set_ylabel('Frequency (MHz)')
        ax3.legend()

        # Print VCO characteristics
        if len(freqs) > 1:
            freq_range = np.ptp(freqs)
            voltage_range = np.ptp(v_ctrl)
            kvco = freq_range / voltage_range if voltage_range > 0 else 0
            print(f"VCO Characteristics:")
            print(f"Frequency Range: {np.min(freqs)/1e6:.2f} MHz to {np.max(freqs)/1e6:.2f} MHz")
            print(f"Average Kvco: {kvco/1e6:.2f} MHz/V")

    plt.tight_layout()
    plt.show()

except Exception as e:
    print(f"Simulation failed: {str(e)}")
    print("Detailed error information:")
    import traceback
    traceback.print_exc()

print(circuit)
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the circuit
circuit = Circuit('Sample and Hold Circuit')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)  # 5V power supply

# Define input signal (sinusoidal)
circuit.SinusoidalVoltageSource('input', 'Vin', circuit.gnd, 
                               amplitude=2.5@u_V,  # 2.5V amplitude
                               frequency=1@u_kHz)  # 1kHz frequency

# Define control signal (pulse for sampling)
circuit.PulseVoltageSource('control', 'Ctrl', circuit.gnd,
                          initial_value=0@u_V,      # Start at 0V
                          pulsed_value=5@u_V,       # Pulse to 5V
                          pulse_width=20@u_us,      # 20μs pulse width
                          period=100@u_us,          # 100μs period (10kHz)
                          rise_time=1@u_ns,         # Fast rise
                          fall_time=1@u_ns)         # Fast fall

# Define MOSFET as switch (NMOS)
circuit.MOSFET('M1', 'node1', 'Ctrl', 'Vin', circuit.gnd, model='NMOS')

# Define hold capacitor with initial condition
circuit.C('hold', 'node1', circuit.gnd, 10@u_nF, ic=0@u_V)  # 10nF capacitor with 0V initial condition

# Define buffer (source follower) to prevent loading of capacitor
circuit.MOSFET('M2', 'Vdd', 'node1', 'Vout', circuit.gnd, model='NMOS')
circuit.I('bias', 'Vout', circuit.gnd, 100@u_uA)  # 100μA current source bias

# MOSFET models
circuit.model('NMOS', 'nmos', 
              level=1,
              kp=120e-6,    # Transconductance parameter
              vto=0.7,      # Threshold voltage
              lambda_=0.02, # Channel-length modulation
              w=50e-6,      # Width
              l=1e-6)       # Length

# Setup simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Perform transient analysis
analysis = simulator.transient(
    step_time=0.1@u_us,    # 100ns step time
    end_time=3000@u_us,     # 500μs simulation time
)

# Plot results
plt.figure(figsize=(12, 8))

# Plot input signal
plt.subplot(3, 1, 1)
plt.plot(analysis.time*1e6, analysis['Vin'])  # Time in μs
plt.title('Input Signal')
plt.ylabel('Voltage (V)')
plt.grid(True)

# Plot control signal
plt.subplot(3, 1, 2)
plt.plot(analysis.time*1e6, analysis['Ctrl'])  # Time in μs
plt.title('Control Signal')
plt.ylabel('Voltage (V)')
plt.grid(True)

# Plot output signal
plt.subplot(3, 1, 3)
plt.plot(analysis.time*1e6, analysis['Vout'])  # Time in μs
plt.title('Output Signal (Sampled & Held)')
plt.xlabel('Time (μs)')
plt.ylabel('Voltage (V)')
plt.grid(True)

plt.tight_layout()
plt.show()

# Optional: Print some key measurements
print("Simulation completed successfully!")
print(f"Input signal frequency: 1 kHz")
print(f"Sampling frequency: 10 kHz")
print(f"Hold capacitor: 10 nF")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the circuit
circuit = Circuit('Basic Charge Pump')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)

# Define clock signals (non-overlapping clocks for charge pump operation)
circuit.PulseVoltageSource('clk1', 'phi1', circuit.gnd, 
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=500@u_ns, period=1@u_us,
                          rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('clk2', 'phi2', circuit.gnd, 
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=500@u_ns, period=1@u_us,
                          rise_time=10@u_ns, fall_time=10@u_ns,
                          delay_time=500@u_ns)  # Phase shifted

# Define MOSFET models
circuit.model('NMOS', 'nmos', 
              level=1,
              kp=120e-6,
              vto=0.7,
              lambda_=0.02,
              w=10e-6,
              l=1e-6)
circuit.model('PMOS', 'pmos', 
              level=1,
              kp=60e-6,
              vto=-0.7,
              lambda_=0.02,
              w=20e-6,
              l=1e-6)

# Charge pump components - corrected architecture
# First stage
circuit.MOSFET('M1', 'node1', 'phi1', circuit.gnd, circuit.gnd, model='NMOS')  # Switching NMOS
circuit.C('C1', 'node1', 'phi2', 10@u_pF)  # Pumping capacitor connected to phi2

# Second stage (diode-connected MOSFET for charge transfer)
circuit.MOSFET('M2', 'Vout', 'node1', 'node1', circuit.gnd, model='NMOS')  # Diode-connected transfer MOSFET
circuit.C('C2', 'Vout', circuit.gnd, 100@u_pF)  # Output storage capacitor

# Output load
circuit.R('load', 'Vout', circuit.gnd, 1@u_MΩ)

# Setup simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(reltol=1e-4, abstol=1e-9, vntol=1e-6)

# Perform transient analysis
try:
    analysis = simulator.transient(
        step_time=10@u_ns, 
        end_time=100@u_us,  # Increased to see the pump effect
        use_initial_condition=True
    )
except Exception as e:
    print(f"Simulation error: {e}")
    # Retry with adjusted parameters if needed
    analysis = simulator.transient(
        step_time=100@u_ns, 
        end_time=20@u_us
    )

# Plot results
plt.figure(figsize=(10, 8))

# Plot clock signals
plt.subplot(3, 1, 1)
plt.plot(analysis.time, analysis['phi1'], label='Phi1')
plt.plot(analysis.time, analysis['phi2'], label='Phi2')
plt.title('Charge Pump Clock Signals')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid(True)

# Plot intermediate node voltage
plt.subplot(3, 1, 2)
plt.plot(analysis.time, analysis['node1'], label='Node1 Voltage', color='green')
plt.title('Intermediate Node Voltage')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid(True)

# Plot output voltage
plt.subplot(3, 1, 3)
plt.plot(analysis.time, analysis['Vout'], label='Output Voltage', color='red')
plt.title('Charge Pump Output Voltage')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()

# Print final output voltage
final_voltage = analysis['Vout'][-1]
print(f"Final output voltage: {final_voltage}")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the circuit
circuit = Circuit('Operational Transconductance Amplifier (OTA)')

# Define power supplies
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)  # Positive supply
circuit.V('ss', 'Vss', circuit.gnd, -5@u_V)  # Negative supply

# Define bias current source
circuit.I('bias', 'Vdd', 'bias_node', 50@u_uA)  # Bias current

# Define input signals (differential)
circuit.SinusoidalVoltageSource('in_p', 'in_p', circuit.gnd, 
                               dc_offset=0@u_V, amplitude=0.01@u_V, frequency=1@u_kHz)
circuit.V('in_n', 'in_n', circuit.gnd, 0@u_V)  # DC reference

# Define MOSFET models with proper parameters
circuit.model('NMOS', 'nmos', 
              level=1,
              kp=120e-6,
              vto=0.7,
              lambda_=0.02,
              gamma=0.5,
              phi=0.7)

circuit.model('PMOS', 'pmos', 
              level=1,
              kp=40e-6,
              vto=-0.7,
              lambda_=0.02,
              gamma=0.5,
              phi=0.7)

# Differential pair (NMOS transistors)
circuit.MOSFET(1, 'drain1', 'in_p', 'tail', circuit.gnd, model='NMOS', w=50e-6, l=1e-6)
circuit.MOSFET(2, 'drain2', 'in_n', 'tail', circuit.gnd, model='NMOS', w=50e-6, l=1e-6)

# Tail current source (NMOS current mirror)
circuit.MOSFET(3, 'tail', 'bias_node', 'Vss', 'Vss', model='NMOS', w=20e-6, l=1e-6)
circuit.MOSFET(4, 'bias_node', 'bias_node', 'Vss', 'Vss', model='NMOS', w=20e-6, l=1e-6)

# Current mirror load (PMOS transistors)
circuit.MOSFET(5, 'drain1', 'drain1', 'Vdd', 'Vdd', model='PMOS', w=100e-6, l=1e-6)
circuit.MOSFET(6, 'drain2', 'drain1', 'Vdd', 'Vdd', model='PMOS', w=100e-6, l=1e-6)

# Output stage
circuit.MOSFET(7, 'output', 'drain2', 'Vss', 'Vss', model='NMOS', w=50e-6, l=1e-6)
circuit.MOSFET(8, 'output', 'bias_node', 'Vdd', 'Vdd', model='PMOS', w=100e-6, l=1e-6)

# Add compensation for stability
circuit.C('comp', 'drain2', 'output', 2@u_pF)  # Miller compensation capacitor
circuit.R('comp_res', 'drain2', 'comp_node', 1@u_kΩ)  # Compensation resistor
circuit.C('comp2', 'comp_node', 'output', 2@u_pF)  # Second compensation capacitor

# Add a load capacitor
circuit.C('load', 'output', circuit.gnd, 10@u_pF)

# Add a small resistor in series with the load to prevent oscillations
circuit.R('series', 'output', 'out_node', 100@u_Ω)
circuit.C('load2', 'out_node', circuit.gnd, 10@u_pF)

# Setup simulation with more conservative options for stability
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(
    reltol=1e-6, 
    abstol=1e-12, 
    vntol=1e-6,
    method='gear',  # More stable integration method
    itl1=100,       # Increase DC iteration limit
    itl2=50,        # Increase transient iteration limit
    itl4=20,        # Increase transient timepoint iteration limit
    pivotrel=1e-3,  # Better pivot relative tolerance
    pivottol=1e-6   # Better pivot absolute tolerance
)

print("Circuit netlist:")
print(circuit)

# Run operating point analysis
print("\nOperating Point Analysis:")
try:
    dc_analysis = simulator.operating_point()
    # Convert to regular Python values
    for node_name in dc_analysis.nodes.keys():
        node_value = dc_analysis[node_name]
        if hasattr(node_value, 'as_ndarray'):
            node_value = node_value.as_ndarray()[0]
        print(f"{node_name}: {node_value:.6f} V")
except Exception as e:
    print(f"Operating point analysis failed: {e}")

# Run transient analysis with smaller steps for stability
print("\nRunning transient analysis...")
try:
    transient_analysis = simulator.transient(
        step_time=0.1@u_us,  # Smaller step time
        end_time=2@u_ms
    )
except Exception as e:
    print(f"Transient analysis failed: {e}")
    transient_analysis = None

# Run AC analysis
print("\nRunning AC analysis...")
try:
    ac_analysis = simulator.ac(
        start_frequency=1@u_Hz,
        stop_frequency=100@u_MHz,
        number_of_points=200,
        variation='dec'
    )
except Exception as e:
    print(f"AC analysis failed: {e}")
    ac_analysis = None

# Plot results if analyses were successful
if transient_analysis is not None:
    plt.figure(figsize=(12, 8))

    # Convert to numpy arrays
    time = np.array(transient_analysis.time)
    in_p = np.array(transient_analysis['in_p'])
    output = np.array(transient_analysis['out_node'])  # Use the node after series resistor
    
    # Transient analysis plot
    plt.subplot(2, 2, 1)
    plt.plot(time, in_p, label='Input+')
    plt.plot(time, output, label='Output')
    plt.xlabel('Time (s)')
    plt.ylabel('Voltage (V)')
    plt.title('Transient Response (Stabilized)')
    plt.legend()
    plt.grid(True)

if ac_analysis is not None:
    # Convert to numpy arrays
    frequency = np.array(ac_analysis.frequency)
    output_ac = np.array(ac_analysis['out_node'])  # Use the node after series resistor
    
    # AC analysis plot - magnitude
    plt.subplot(2, 2, 2)
    gain = np.abs(output_ac)
    plt.semilogx(frequency, 20*np.log10(np.where(gain > 0, gain, 1e-12)))
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Gain (dB)')
    plt.title('AC Response - Magnitude (Stabilized)')
    plt.grid(True)

    # AC analysis plot - phase
    plt.subplot(2, 2, 3)
    plt.semilogx(frequency, np.angle(output_ac, deg=True))
    plt.xlabel('Frequency (Hz)')
    plt.ylabel('Phase (degrees)')
    plt.title('AC Response - Phase (Stabilized)')
    plt.grid(True)

# DC transfer characteristic
try:
    dc_sweep = simulator.dc(Vin_p=slice(-0.1, 0.1, 0.005))
    plt.subplot(2, 2, 4)
    plt.plot(dc_sweep.Vin_p, dc_sweep.out_node)  # Use the node after series resistor
    plt.xlabel('Differential Input Voltage (V)')
    plt.ylabel('Output Voltage (V)')
    plt.title('DC Transfer Characteristic (Stabilized)')
    plt.grid(True)
except Exception as e:
    print(f"DC sweep failed: {e}")

plt.tight_layout()
plt.show()

# Calculate and print performance metrics
print("\nPerformance Metrics:")
    
# DC gain calculation
try:
    if ac_analysis is not None:
        # Get the low-frequency gain (first point in AC analysis)
        low_freq_gain = np.abs(output_ac[0])
        if low_freq_gain > 0:
            print(f"DC Gain: {low_freq_gain:.2f} ({20*np.log10(low_freq_gain):.2f} dB)")
        else:
            print("DC Gain: 0.00 (-inf dB)")
except Exception as e:
    print(f"Could not calculate DC gain: {e}")
        
# Phase margin calculation
try:
    if ac_analysis is not None:
        # Find unity gain frequency
        unity_gain_idx = np.where(gain <= 1)[0]
        if len(unity_gain_idx) > 0:
            ugf = frequency[unity_gain_idx[0]]
            phase_at_ugf = np.angle(output_ac[unity_gain_idx[0]], deg=True)
            phase_margin = 180 + phase_at_ugf
            print(f"Unity Gain Frequency: {ugf:.2e} Hz")
            print(f"Phase Margin: {phase_margin:.2f}°")
            
            # Check if phase margin is sufficient for stability
            if phase_margin > 45:
                print("Phase margin is sufficient for stability (>45°)")
            else:
                print("WARNING: Phase margin may be insufficient for stability")
        else:
            print("Could not find unity gain frequency")
except Exception as e:
    print(f"Could not calculate phase margin: {e}")

# Additional metrics from operating point
try:
    if 'dc_analysis' in locals():
        output_voltage = dc_analysis['out_node']
        if hasattr(output_voltage, 'as_ndarray'):
            output_voltage = output_voltage.as_ndarray()[0]
        print(f"Output DC voltage: {output_voltage:.3f} V")
        
        # Calculate approximate power consumption
        total_current = 100e-6  # 100μA
        power = 10 * total_current  # 10V total supply * current
        print(f"Approximate power consumption: {power*1e6:.2f} μW")
        
        # Calculate output swing range
        max_output = 4.0  # V
        min_output = -4.0  # V
        output_swing = max_output - min_output
        print(f"Estimated output swing: {output_swing:.1f} V")
except Exception as e:
    print(f"Could not calculate additional metrics: {e}")

# Check for stability in transient response
if transient_analysis is not None:
    output_signal = np.array(transient_analysis['out_node'])
    # Check if the output is oscillating by looking for significant variations
    std_dev = np.std(output_signal)
    mean_val = np.mean(output_signal)
    
    if std_dev > 0.1 * abs(mean_val):  # If standard deviation is more than 10% of mean
        print("WARNING: Output shows significant oscillation")
        print(f"Output standard deviation: {std_dev:.4f} V")
    else:
        print("Output appears stable")
        print(f"Output standard deviation: {std_dev:.6f} V")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Create a new circuit
circuit = Circuit('4:1 CMOS Multiplexer')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)

# Define input signals as pulse sources with different patterns
circuit.PulseVoltageSource('in0', 'in0_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=400@u_ns, period=800@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('in1', 'in1_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=200@u_ns, period=400@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('in2', 'in2_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=100@u_ns, period=200@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)
circuit.PulseVoltageSource('in3', 'in3_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=50@u_ns, period=100@u_ns,
                          delay_time=0@u_ns, rise_time=10@u_ns, fall_time=10@u_ns)

# Define select signals (S0 and S1) with slower transitions
circuit.PulseVoltageSource('S0', 'S0_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=1000@u_ns, period=2000@u_ns,)
circuit.PulseVoltageSource('S1', 'S1_node', circuit.gnd,
                          initial_value=0@u_V, pulsed_value=5@u_V,
                          pulse_width=2000@u_ns, period=4000@u_ns,)

# Define MOSFET models
circuit.model('NMOS', 'nmos', 
              level=1, kp=120e-6, vto=0.7, lambda_=0.02, 
              w=10e-6, l=1e-6)
circuit.model('PMOS', 'pmos', 
              level=1, kp=60e-6, vto=-0.7, lambda_=0.02, 
              w=20e-6, l=1e-6)

# Generate complementary select signals using inverters
# Inverter for S0
circuit.MOSFET(1, 'S0_bar', 'S0_node', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET(2, 'S0_bar', 'S0_node', 'Vdd', 'Vdd', model='PMOS')

# Inverter for S1
circuit.MOSFET(3, 'S1_bar', 'S1_node', circuit.gnd, circuit.gnd, model='NMOS')
circuit.MOSFET(4, 'S1_bar', 'S1_node', 'Vdd', 'Vdd', model='PMOS')

# Implement the 4:1 multiplexer using a hierarchical approach
# First level: Two 2:1 multiplexers controlled by S0
# Second level: 2:1 multiplexer controlled by S1

# First 2:1 mux (inputs 0 and 1, controlled by S0)
circuit.MOSFET(5, 'in0_node', 'S0_bar', 'mux1_out', circuit.gnd, model='NMOS')
circuit.MOSFET(6, 'in0_node', 'S0_node', 'mux1_out', 'Vdd', model='PMOS')
circuit.MOSFET(7, 'in1_node', 'S0_node', 'mux1_out', circuit.gnd, model='NMOS')
circuit.MOSFET(8, 'in1_node', 'S0_bar', 'mux1_out', 'Vdd', model='PMOS')

# Second 2:1 mux (inputs 2 and 3, controlled by S0)
circuit.MOSFET(9, 'in2_node', 'S0_bar', 'mux2_out', circuit.gnd, model='NMOS')
circuit.MOSFET(10, 'in2_node', 'S0_node', 'mux2_out', 'Vdd', model='PMOS')
circuit.MOSFET(11, 'in3_node', 'S0_node', 'mux2_out', circuit.gnd, model='NMOS')
circuit.MOSFET(12, 'in3_node', 'S0_bar', 'mux2_out', 'Vdd', model='PMOS')

# Final 2:1 mux (outputs of first two muxes, controlled by S1)
circuit.MOSFET(13, 'mux1_out', 'S1_bar', 'output', circuit.gnd, model='NMOS')
circuit.MOSFET(14, 'mux1_out', 'S1_node', 'output', 'Vdd', model='PMOS')
circuit.MOSFET(15, 'mux2_out', 'S1_node', 'output', circuit.gnd, model='NMOS')
circuit.MOSFET(16, 'mux2_out', 'S1_bar', 'output', 'Vdd', model='PMOS')

# Add a load resistor and capacitor at the output
circuit.R('load', 'output', circuit.gnd, 10@u_kΩ)
circuit.C('out_cap', 'output', circuit.gnd, 100e-15@u_F)

# Setup simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

# Perform transient analysis with a longer duration to see all combinations
analysis = simulator.transient(step_time=10@u_ns, end_time=4000@u_ns)

# Convert analysis time to nanoseconds for easier interpretation
time_ns = np.array(analysis.time) * 1e9

# Plot input signals in separate figures
plt.figure(figsize=(10, 8))

plt.subplot(4, 1, 1)
plt.plot(time_ns, analysis['in0_node'])
plt.title('Input 0 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.subplot(4, 1, 2)
plt.plot(time_ns, analysis['in1_node'])
plt.title('Input 1 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.subplot(4, 1, 3)
plt.plot(time_ns, analysis['in2_node'])
plt.title('Input 2 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.subplot(4, 1, 4)
plt.plot(time_ns, analysis['in3_node'])
plt.title('Input 3 Signal')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.grid()

plt.tight_layout()
plt.show()

# Plot select signals
plt.figure(figsize=(10, 6))
plt.plot(time_ns, analysis['S0_node'], label='Select S0')
plt.plot(time_ns, analysis['S1_node'], label='Select S1')
plt.title('Select Signals')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid()
plt.show()

# Plot output signal
plt.figure(figsize=(10, 6))
plt.plot(time_ns, analysis['output'], label='Output')
plt.title('Multiplexer Output')
plt.xlabel('Time [ns]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid()
plt.show()
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create a simpler, more robust bandgap reference circuit
circuit = Circuit('Bandgap Reference Circuit')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 3.3@u_V)

# Define bipolar transistors with different areas (8:1 ratio)
circuit.BJT('Q1', 'Q1_collector', 'Q1_base', circuit.gnd, model='NPN', area=1)
circuit.BJT('Q2', 'Q2_collector', 'Q2_base', circuit.gnd, model='NPN', area=8)

# Add small resistors to collectors for better convergence
circuit.R('R1', 'Vdd', 'Q1_collector', 10@u_kΩ)
circuit.R('R2', 'Vdd', 'Q2_collector', 10@u_kΩ)

# Add base resistors
circuit.R('R3', 'Q1_base', 'Q1_collector', 5@u_kΩ)
circuit.R('R4', 'Q2_base', 'Q2_collector', 5@u_kΩ)

# Add a simple current mirror to bias the transistors
circuit.BJT('Q3', 'Q3_collector', 'Q3_collector', circuit.gnd, model='NPN', area=1)  # Diode-connected
circuit.R('R5', 'Vdd', 'Q3_collector', 10@u_kΩ)

# Connect the current mirror to the bandgap core
circuit.R('R6', 'Q3_collector', 'Q1_base', 5@u_kΩ)
circuit.R('R7', 'Q3_collector', 'Q2_base', 5@u_kΩ)

# Add a PTAT resistor between the collectors
circuit.R('Rptat', 'Q1_collector', 'Q2_collector', 2@u_kΩ)

# Output stage - simple voltage follower
circuit.BJT('Q4', 'Vout', 'Q2_collector', circuit.gnd, model='NPN', area=1)
circuit.R('Rout', 'Vdd', 'Vout', 5@u_kΩ)

# Define device models with proper parameters
circuit.model('NPN', 'npn',
              is_=1e-16,
              bf=100,
              br=1,
              vaf=50,
              ikf=0.1,
              ise=1e-15,
              ne=1.5,
              rc=10)

# Setup simulation with convergence helpers
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(
    reltol=1e-3,
    abstol=1e-9,
    vntol=1e-6,
    gmin=1e-12,
    method='gear',
    itl1=1000,
    itl2=1000,
    itl4=1000,
    srcsteps=100,
    pivtol=1e-12,
    pivrel=1e-3
)

print("Testing Bandgap Reference Circuit...")

# Operating point analysis
try:
    analysis_op = simulator.operating_point()
    vout = float(analysis_op['Vout'])
    print(f"Operating Point Analysis: Vout = {vout:.6f} V")
    
    # Test if circuit is working
    if 1.1 <= vout <= 1.3:  # Typical bandgap voltage range
        print("✓ PASS: Circuit is generating a proper reference voltage")
    else:
        print("✗ FAIL: Circuit is not generating a proper reference voltage")
        
except Exception as e:
    print(f"✗ FAIL: Operating point analysis failed: {e}")
    # Try a DC analysis instead
    try:
        analysis_dc = simulator.dc(Vdd=slice(0, 3.3, 0.1))
        vout = float(analysis_dc['Vout'][-1])  # Get the last value
        print(f"DC Analysis: Vout at 3.3V = {vout:.6f} V")
    except Exception as e2:
        print(f"DC analysis also failed: {e2}")

# DC analysis - temperature sweep
print("\nTemperature Stability Test:")
temperatures = np.linspace(-40, 125, 10)
vout_values = []
success_count = 0

for temp in temperatures:
    try:
        # Create a new simulator for each temperature
        temp_simulator = circuit.simulator(temperature=temp, nominal_temperature=25)
        temp_simulator.options(
            reltol=1e-3,
            abstol=1e-9,
            vntol=1e-6,
            gmin=1e-12,
            itl1=1000,
            itl2=1000,
            itl4=1000
        )
        analysis = temp_simulator.operating_point()
        vout_val = float(analysis['Vout'])
        vout_values.append(vout_val)
        print(f"Temperature {temp}°C: Vout = {vout_val:.6f} V")
        success_count += 1
    except Exception as e:
        print(f"Temperature {temp}°C: Failed - {e}")
        vout_values.append(np.nan)

# Plot the temperature stability results
if success_count > 0:
    plt.figure(figsize=(10, 6))
    
    # Filter out failed simulations
    valid_temps = []
    valid_vouts = []
    for i, (temp, vout) in enumerate(zip(temperatures, vout_values)):
        if not np.isnan(vout):
            valid_temps.append(temp)
            valid_vouts.append(vout)
    
    if len(valid_temps) > 1:
        plt.plot(valid_temps, valid_vouts, 'o-', linewidth=2, markersize=8)
        plt.xlabel('Temperature (°C)')
        plt.ylabel('Output Voltage (V)')
        plt.title('Bandgap Reference Voltage vs Temperature')
        plt.grid(True, alpha=0.3)
        
        # Add voltage range indicators
        if len(valid_vouts) > 0:
            avg_voltage = np.mean(valid_vouts)
            plt.axhline(y=avg_voltage, color='r', linestyle='--', alpha=0.7, label=f'Average: {avg_voltage:.3f} V')
            plt.legend()
        
        plt.tight_layout()
        plt.savefig('bandgap_temperature_stability.png', dpi=150)
        plt.show()
        
        # Calculate and display statistics
        vout_range = max(valid_vouts) - min(valid_vouts)
        vout_std = np.std(valid_vouts)
        print(f"\nTemperature Stability Statistics:")
        print(f"  Voltage range: {vout_range*1000:.2f} mV")
        print(f"  Standard deviation: {vout_std*1000:.2f} mV")
        
        # Test temperature stability
        if vout_range < 0.1:  # Less than 100mV variation
            print(f"✓ PASS: Good temperature stability (ΔV = {vout_range*1000:.2f} mV)")
        else:
            print(f"✗ FAIL: Poor temperature stability (ΔV = {vout_range*1000:.2f} mV)")
    else:
        print("✗ FAIL: Insufficient data for plotting")
else:
    print("✗ FAIL: Insufficient data for temperature stability test")

print("\nBandgap Reference Test Complete")
# ---
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory
import matplotlib.pyplot as plt
import numpy as np

class Opamp(SubCircuitFactory):
    NAME = ('Opamp')
    NODES = ('Vinp', 'Vinn', 'Vout')
    def __init__(self):
        super().__init__()
        # Define the MOSFET models with higher gain for sharper transitions
        self.model('nmos_model', 'nmos', level=1, kp=200e-6, vto=0.5, lambda_=0.01)
        self.model('pmos_model', 'pmos', level=1, kp=100e-6, vto=-0.5, lambda_=0.01)
        
        # Internal power supply and bias
        self.V('dd_int', 'Vdd_int', self.gnd, 5.0)
        self.V('bias', 'Vbias', self.gnd, 1.5)
        
        # Differential pair with larger sizes for higher transconductance
        self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=100e-6, l=0.5e-6)
        self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=100e-6, l=0.5e-6)
        
        # Tail current source with larger width for more current
        self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=200e-6, l=1e-6)
        
        # Current mirror load with higher current capability
        self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd_int', 'Vdd_int', model='pmos_model', w=200e-6, l=0.5e-6)
        self.MOSFET('5', 'Vout', 'Voutp', 'Vdd_int', 'Vdd_int', model='pmos_model', w=200e-6, l=0.5e-6)

# Create a 3-bit Flash ADC circuit
circuit = Circuit('3-bit Flash ADC')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)

# Create precision resistor ladder for reference voltages
# Using smaller, matched resistors for better accuracy
r_ladder = 500@u_Ω  

# Create voltage divider chain from top to bottom
# This creates references at: 4.375V, 3.75V, 3.125V, 2.5V, 1.875V, 1.25V, 0.625V
circuit.R('R_top', 'Vdd', 'Vref7', r_ladder)      # Top resistor
circuit.R('R6', 'Vref7', 'Vref6', r_ladder)       # 4.375V to 3.75V
circuit.R('R5', 'Vref6', 'Vref5', r_ladder)       # 3.75V to 3.125V  
circuit.R('R4', 'Vref5', 'Vref4', r_ladder)       # 3.125V to 2.5V
circuit.R('R3', 'Vref4', 'Vref3', r_ladder)       # 2.5V to 1.875V
circuit.R('R2', 'Vref3', 'Vref2', r_ladder)       # 1.875V to 1.25V
circuit.R('R1', 'Vref2', 'Vref1', r_ladder)       # 1.25V to 0.625V
circuit.R('R_bot', 'Vref1', circuit.gnd, r_ladder) # Bottom resistor

# Add buffer resistors to prevent loading of reference voltages
for i in range(1, 8):
    circuit.R(f'Rbuf{i}', f'Vref{i}', f'Vref{i}_buf', 1@u_Ω)

# Declare the opamp subcircuit
circuit.subcircuit(Opamp())

# Create 7 comparators using the op-amp
# For proper Flash ADC operation:
# - Input goes to non-inverting input (+)
# - Reference goes to inverting input (-)
# - When Vin > Vref, output goes HIGH
# - When Vin < Vref, output goes LOW

for i in range(1, 8):
    # Create comparator: Vin(+) compared with Vref_i(-)
    circuit.X(f'cmp{i}', 'Opamp', 'Vin', f'Vref{i}_buf', f'Comp_out_{i}')
    
    # Add pull-up resistors to ensure proper HIGH levels
    circuit.R(f'Rpull{i}', f'Comp_out_{i}', 'Vdd', 10@u_kΩ)

# Input voltage source
circuit.V('input', 'Vin', circuit.gnd, 2.5@u_V)

# Setup simulation with improved convergence
simulator = circuit.simulator(temperature=25, nominal_temperature=25)
simulator.options(
    reltol=1e-4,
    abstol=1e-10,
    vntol=1e-6,
    method='gear',
    maxiter=200,
    gmin=1e-15,
    pivrel=1e-3
)

try:
    # Perform DC analysis with finer resolution
    analysis = simulator.dc(Vinput=slice(0, 5, 0.02))
    
    # Extract results
    input_voltage = np.array(analysis.Vin)
    
    # Print actual reference voltages
    print("Actual Reference Voltages:")
    print("=" * 30)
    ref_voltages = {}
    for i in range(1, 8):
        vref_actual = float(analysis[f'Vref{i}'][0])
        vref_expected = 5.0 * i / 8.0
        ref_voltages[i] = vref_actual
        print(f"Vref{i}: {vref_actual:.3f}V (Expected: {vref_expected:.3f}V)")
    
    # Create comprehensive plots
    plt.figure(figsize=(16, 12))
    
    # Plot 1: Reference voltage verification
    plt.subplot(2, 2, 1)
    ref_values = [ref_voltages[i] for i in range(1, 8)]
    expected_values = [5.0 * i / 8.0 for i in range(1, 8)]
    x_pos = range(1, 8)
    
    plt.bar([x - 0.2 for x in x_pos], ref_values, 0.4, label='Actual', alpha=0.7)
    plt.bar([x + 0.2 for x in x_pos], expected_values, 0.4, label='Expected', alpha=0.7)
    plt.xlabel('Reference Number')
    plt.ylabel('Voltage (V)')
    plt.title('Reference Voltage Accuracy')
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # Plot 2: Comparator outputs (analog)
    plt.subplot(2, 2, 2)
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2']
    
    for i in range(1, 8):
        comp_out = np.array(analysis[f'Comp_out_{i}'])
        plt.plot(input_voltage, comp_out, color=colors[i-1], 
                linewidth=2, label=f'Comp {i} (Vref={ref_voltages[i]:.2f}V)')
    
    plt.title('Flash ADC - Comparator Analog Outputs')
    plt.xlabel('Input Voltage (V)')
    plt.ylabel('Comparator Output Voltage (V)')
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.grid(True, alpha=0.3)
    
    # Plot 3: Digital thermometer code
    plt.subplot(2, 2, 3)
    
    threshold = 2.5  # Digital threshold voltage
    digital_outputs = []
    
    for i in range(1, 8):
        comp_out = np.array(analysis[f'Comp_out_{i}'])
        digital_out = (comp_out > threshold).astype(int)
        digital_outputs.append(digital_out)
        
        # Plot with offset for visibility
        plt.plot(input_voltage, digital_out * 0.8 + i - 0.5, 
                color=colors[i-1], linewidth=3, label=f'Comp {i}')
    
    plt.title('Flash ADC - Digital Thermometer Code')
    plt.xlabel('Input Voltage (V)')
    plt.ylabel('Comparator Number')
    plt.ylim(0, 8)
    plt.grid(True, alpha=0.3)
    plt.legend()
    
    # Plot 4: 3-bit binary output simulation
    plt.subplot(2, 2, 4)
    
    # Convert thermometer code to binary
    binary_codes = []
    for j in range(len(input_voltage)):
        # Count number of HIGH comparators
        high_count = sum([digital_outputs[i][j] for i in range(7)])
        binary_codes.append(high_count)
    
    plt.plot(input_voltage, binary_codes, 'ko-', linewidth=2, markersize=3)
    plt.title('Flash ADC - 3-bit Digital Output')
    plt.xlabel('Input Voltage (V)')
    plt.ylabel('Digital Code (0-7)')
    plt.grid(True, alpha=0.3)
    plt.ylim(-0.5, 7.5)
    
    # Add step annotations
    for code in range(8):
        plt.axhline(y=code, color='gray', linestyle='--', alpha=0.3)
        voltage_range = f"{code*5/8:.2f}V-{(code+1)*5/8:.2f}V"
        if code < 7:
            plt.text(0.1, code + 0.3, f"Code {code}", fontsize=8)
    
    plt.tight_layout()
    plt.savefig('flash_adc_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    # Performance analysis
    print(f"\nFlash ADC Performance Analysis:")
    print("=" * 50)
    
    transition_points = []
    for i in range(1, 8):
        comp_out = np.array(analysis[f'Comp_out_{i}'])
        
        # Find transition point where output crosses threshold
        try:
            # Find where output transitions from low to high or high to low
            diff_out = np.diff(comp_out)
            max_change_idx = np.argmax(np.abs(diff_out))
            transition_vin = input_voltage[max_change_idx]
            
            expected_vref = ref_voltages[i]
            error = abs(transition_vin - expected_vref)
            
            transition_points.append(transition_vin)
            print(f"Comparator {i}: Transitions at {transition_vin:.3f}V "
                  f"(Vref: {expected_vref:.3f}V, Error: {error:.3f}V)")
                  
        except:
            print(f"Comparator {i}: Could not determine clear transition point")
    
    # Overall ADC metrics
    if len(transition_points) > 1:
        step_sizes = np.diff(sorted(transition_points))
        avg_step = np.mean(step_sizes)
        step_variation = np.std(step_sizes)
        
        print(f"\nADC Metrics:")
        print(f"Average step size: {avg_step:.3f}V")
        print(f"Step size variation (std): {step_variation:.3f}V")
        print(f"Theoretical step size: {5.0/8:.3f}V")
        print(f"Resolution: 3 bits ({2**3} levels)")
        
        if step_variation < 0.1:  # Arbitrary threshold for "good" performance
            print("✓ Flash ADC is functioning correctly!")
        else:
            print("⚠ Large step size variation detected - check component matching")
    
except Exception as e:
    print(f"Simulation failed: {e}")
    import traceback
    traceback.print_exc()
    print("\nTroubleshooting suggestions:")
    print("1. The op-amp model may be too complex for convergence")
    print("2. Try reducing resistor values or increasing capacitive loading")
    print("3. Consider using ideal voltage sources for references initially")
# ---
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
import matplotlib.pyplot as plt
import numpy as np

# Create the circuit
circuit = Circuit('CMOS Phase Detector')

# Define power supply
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V)

# Define input signals with phase difference using voltage-controlled voltage sources
# We'll create a reference signal and a phase-shifted version
circuit.SinusoidalVoltageSource('ref', 'ref_in', circuit.gnd, 
                               amplitude=2.5@u_V, frequency=1@u_MHz)

# Create a phase-shifted version using an RC phase shift network
circuit.R('phase_shift', 'ref_in', 'in1', 1@u_kΩ)
circuit.C('phase_shift', 'in1', circuit.gnd, 160@u_nF)  # This will create ~45° phase shift at 1MHz

# Buffer the phase-shifted signal
circuit.MOSFET('M13', 'in2', 'in1', circuit.gnd, circuit.gnd, model='NMOS', w=10e-6, l=1e-6)
circuit.MOSFET('M14', 'in2', 'in1', 'Vdd', 'Vdd', model='PMOS', w=20e-6, l=1e-6)

# Define MOSFET models
circuit.model('NMOS', 'nmos', level=1, kp=120e-6, vto=0.7, lambda_=0.02, gamma=0.37, phi=0.65)
circuit.model('PMOS', 'pmos', level=1, kp=60e-6, vto=-0.7, lambda_=0.02, gamma=0.37, phi=0.65)

# Phase detector core - XOR gate implementation (8 transistors)
# Inverter for input 1
circuit.MOSFET('M1', 'in1_bar', 'in1', circuit.gnd, circuit.gnd, model='NMOS', w=10e-6, l=1e-6)
circuit.MOSFET('M2', 'in1_bar', 'in1', 'Vdd', 'Vdd', model='PMOS', w=20e-6, l=1e-6)

# Inverter for input 2
circuit.MOSFET('M3', 'in2_bar', 'in2', circuit.gnd, circuit.gnd, model='NMOS', w=10e-6, l=1e-6)
circuit.MOSFET('M4', 'in2_bar', 'in2', 'Vdd', 'Vdd', model='PMOS', w=20e-6, l=1e-6)

# XOR gate implementation
circuit.MOSFET('M5', 'pd_out', 'in1', 'node1', circuit.gnd, model='NMOS', w=10e-6, l=1e-6)
circuit.MOSFET('M6', 'node1', 'in2_bar', circuit.gnd, circuit.gnd, model='NMOS', w=10e-6, l=1e-6)
circuit.MOSFET('M7', 'pd_out', 'in1_bar', 'node2', circuit.gnd, model='NMOS', w=10e-6, l=1e-6)
circuit.MOSFET('M8', 'node2', 'in2', circuit.gnd, circuit.gnd, model='NMOS', w=10e-6, l=1e-6)

circuit.MOSFET('M9', 'pd_out', 'in1_bar', 'node3', 'Vdd', model='PMOS', w=20e-6, l=1e-6)
circuit.MOSFET('M10', 'node3', 'in2', 'Vdd', 'Vdd', model='PMOS', w=20e-6, l=1e-6)
circuit.MOSFET('M11', 'pd_out', 'in1', 'node4', 'Vdd', model='PMOS', w=20e-6, l=1e-6)
circuit.MOSFET('M12', 'node4', 'in2_bar', 'Vdd', 'Vdd', model='PMOS', w=20e-6, l=1e-6)

# Low-pass filter to convert pulse width to voltage
circuit.R('filt', 'pd_out', 'out', 10@u_kΩ)
circuit.C('filt', 'out', circuit.gnd, 1@u_nF)

# Setup simulation
simulator = circuit.simulator(temperature=25, nominal_temperature=25)

print("Circuit Description:")
print(circuit)

# Perform transient analysis
try:
    analysis = simulator.transient(step_time=1@u_ns, end_time=5@u_us)
    
    # Plot results
    plt.figure(figsize=(12, 8))
    
    # Input signals
    plt.subplot(3, 1, 1)
    plt.plot(analysis.time, analysis['ref_in'], label='Reference Input')
    plt.plot(analysis.time, analysis['in2'], label='Phase-Shifted Input')
    plt.title('Input Signals')
    plt.xlabel('Time [s]')
    plt.ylabel('Voltage [V]')
    plt.legend()
    plt.grid(True)
    
    # Phase detector output (before filtering)
    plt.subplot(3, 1, 2)
    plt.plot(analysis.time, analysis['pd_out'], 'r-', label='Phase Detector Output')
    plt.title('Phase Detector Output (Before Filtering)')
    plt.xlabel('Time [s]')
    plt.ylabel('Voltage [V]')
    plt.legend()
    plt.grid(True)
    
    # Filtered output (phase difference voltage)
    plt.subplot(3, 1, 3)
    plt.plot(analysis.time, analysis['out'], 'g-', label='Filtered Output')
    plt.title('Filtered Output (Phase Difference Voltage)')
    plt.xlabel('Time [s]')
    plt.ylabel('Voltage [V]')
    plt.legend()
    plt.grid(True)
    
    plt.tight_layout()
    plt.show()
    
    # Calculate average output voltage (proportional to phase difference)
    # Skip initial transient
    steady_state = analysis.out[int(len(analysis.out)*0.2):]
    avg_voltage = np.mean(steady_state)
    print(f"Average output voltage: {avg_voltage:.3f} V")
    print(f"This voltage is proportional to the phase difference between inputs")

except Exception as e:
    print(f"Simulation error: {e}")
    # Try with relaxed tolerances
    simulator.options(reltol=1e-3, abstol=1e-9, vntol=1e-6)
    analysis = simulator.transient(step_time=1@u_ns, end_time=5@u_us)

# === chipster/notebooks/create_dataset.ipynb ===
import os
import glob
from dotenv import load_dotenv
import torch
import math
import shutil

from tqdm import tqdm
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import CSVLoader, TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders import DirectoryLoader


def main():
    """
    Main function to load Verilog and CSV data, create local embeddings, 
    and save a specific FAISS index.
    """
    # --- 1. Load Environment Variables ---
    load_dotenv()

    # --- 2. Define Paths ---
    DATASET_PATH = "../data/verilog_datasets"
    INDEX_PATH = os.path.join(DATASET_PATH, "faiss_qft_verieval")
    QFT_FOLDER_PATH = "../examples/verilog_designs/qft"
    VERILOGEVAL_CSV_PATH = os.path.join(DATASET_PATH, "verilogeval-v2.csv")


    # --- 3. Clean up old database directory ---
    if os.path.exists(INDEX_PATH):
        print(f"--- Deleting old FAISS index directory: '{INDEX_PATH}' ---")
        try:
            shutil.rmtree(INDEX_PATH)
        except OSError as e:
            print(f"Error deleting directory {INDEX_PATH}: {e.strerror}")
            print("Please ensure no other programs are using this directory.")
            return
    print("--- Starting with a fresh index directory. ---")

    # --- 4. Load Documents ---
    all_docs = []
    
    # Load Verilog and Verilog Header files from the qft_pipelined directory
    print(f"\n--- Loading Verilog documents from '{QFT_FOLDER_PATH}' ---")
    if not os.path.exists(QFT_FOLDER_PATH):
        print(f"ERROR: QFT directory not found at '{QFT_FOLDER_PATH}'")
    else:
        # Load Verilog files as plain text, as the LanguageParser does not support Verilog
        loader_verilog = DirectoryLoader(
            QFT_FOLDER_PATH,
            glob=["**/*.v", "**/*.vh"], # UPDATED: Include .vh files
            loader_cls=TextLoader
        )
        verilog_docs = loader_verilog.load()
        all_docs.extend(verilog_docs)
        print(f"Successfully loaded {len(verilog_docs)} Verilog (.v & .vh) files.")

    # Load the specific CSV file
    print(f"\n--- Loading documents from '{VERILOGEVAL_CSV_PATH}' ---")
    if not os.path.exists(VERILOGEVAL_CSV_PATH):
        print(f"ERROR: CSV file not found at '{VERILOGEVAL_CSV_PATH}'")
    else:
        loader_csv = CSVLoader(
            file_path=VERILOGEVAL_CSV_PATH,
            source_column="instruction",
            csv_args={'delimiter': ',', 'quotechar': '"'}
        )
        try:
            csv_docs = loader_csv.load()
            all_docs.extend(csv_docs)
            print(f"Successfully loaded content from {len(csv_docs)} rows in the CSV.")
        except Exception as e:
            print(f"    - ERROR loading file {VERILOGEVAL_CSV_PATH}: {e}")

    if not all_docs:
        print("\nNo documents were loaded. Exiting.")
        return
    print(f"\nTotal documents loaded: {len(all_docs)}.")

    # --- 5. Split Documents into Chunks ---
    print("\n--- Splitting documents into smaller chunks ---")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunked_docs = text_splitter.split_documents(all_docs)
    print(f"Split the documents into {len(chunked_docs)} chunks.")

    # --- 6. Create Embeddings and Persist to FAISS ---
    print("\n--- Creating local embeddings and building FAISS index ---")
    
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name='all-MiniLM-L6-v2',
            model_kwargs={'device': 'cuda' if torch.cuda.is_available() else 'cpu'}
        )
        print(f"Embedding model loaded onto {'GPU' if torch.cuda.is_available() else 'CPU'}.")

        # --- ROBUST, TWO-STAGE INITIALIZATION FOR FAISS ---
        batch_size = 1024
        if not chunked_docs:
            print("No chunks to process. Exiting.")
            return

        # Stage 1: Initialize the vector store with the first batch.
        print("Initializing FAISS index with the first batch...")
        first_batch = chunked_docs[:batch_size]
        vectorstore = FAISS.from_documents(documents=first_batch, embedding=embeddings)

        # Stage 2: Add the rest in batches with a progress bar.
        remaining_chunks = chunked_docs[batch_size:]
        num_batches = math.ceil(len(remaining_chunks) / batch_size)
        for i in tqdm(range(num_batches), desc="Embedding and Storing in FAISS"):
            start = i * batch_size
            end = start + batch_size
            batch = remaining_chunks[start:end]
            if batch:
                vectorstore.add_documents(batch)
            
        print("\nSuccessfully created and populated FAISS index.")

    except Exception as e:
        print(f"\nAN UNEXPECTED ERROR OCCURRED: {e}")
        return

    # --- 7. Save Final Index ---
    print("\n--- Saving final FAISS index to disk ---")
    vectorstore.save_local(INDEX_PATH)
    print(f"FAISS index is stored in the folder: '{os.path.abspath(INDEX_PATH)}'")

if __name__ == "__main__":
    main()

# ---
import os
import glob
from dotenv import load_dotenv
import torch
import math
import shutil

from tqdm import tqdm
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import DirectoryLoader


def main():
    """
    Main function to load PySpice, AMS, and RF data, create local embeddings,
    and save a specific FAISS index.
    """
    # --- 1. Load Environment Variables ---
    load_dotenv()

    # --- 2. Define Paths ---
    ANALOG_DATASET_PATH = "../data/analog_datasets"
    SOURCE_DATA_PATH = os.path.join(ANALOG_DATASET_PATH, "AMS_RF_Dataset")
    INDEX_PATH = os.path.join(ANALOG_DATASET_PATH, "faiss_pyspice_ams_rf")


    # --- 3. Clean up old database directory ---
    if os.path.exists(INDEX_PATH):
        print(f"--- Deleting old FAISS index directory: '{INDEX_PATH}' ---")
        try:
            shutil.rmtree(INDEX_PATH)
        except OSError as e:
            print(f"Error deleting directory {INDEX_PATH}: {e.strerror}")
            print("Please ensure no other programs are using this directory.")
            return
    print("--- Starting with a fresh index directory. ---")

    # --- 4. Load Documents ---
    all_docs = []
    
    # Load Python and Markdown files from the pyspice_datasets directory
    print(f"\n--- Loading documents from '{SOURCE_DATA_PATH}' ---")
    if not os.path.exists(SOURCE_DATA_PATH):
        print(f"ERROR: Source data directory not found at '{SOURCE_DATA_PATH}'")
        return
        
    # Load .py and .md files as plain text
    loader_pyspice = DirectoryLoader(
        SOURCE_DATA_PATH,
        glob=["**/*.py", "**/*.md"], # Load Python and Markdown files
        loader_cls=TextLoader
    )
    pyspice_docs = loader_pyspice.load()
    all_docs.extend(pyspice_docs)
    print(f"Successfully loaded {len(pyspice_docs)} source files (.py & .md).")

    if not all_docs:
        print("\nNo documents were loaded. Exiting.")
        return
    print(f"\nTotal documents loaded: {len(all_docs)}.")

    # --- 5. Split Documents into Chunks ---
    print("\n--- Splitting documents into smaller chunks ---")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunked_docs = text_splitter.split_documents(all_docs)
    print(f"Split the documents into {len(chunked_docs)} chunks.")

    # --- 6. Create Embeddings and Persist to FAISS ---
    print("\n--- Creating local embeddings and building FAISS index ---")
    
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name='all-MiniLM-L6-v2',
            model_kwargs={'device': 'cuda' if torch.cuda.is_available() else 'cpu'}
        )
        print(f"Embedding model loaded onto {'GPU' if torch.cuda.is_available() else 'CPU'}.")

        # --- ROBUST, TWO-STAGE INITIALIZATION FOR FAISS ---
        batch_size = 1024
        if not chunked_docs:
            print("No chunks to process. Exiting.")
            return

        # Stage 1: Initialize the vector store with the first batch.
        print("Initializing FAISS index with the first batch...")
        first_batch = chunked_docs[:batch_size]
        vectorstore = FAISS.from_documents(documents=first_batch, embedding=embeddings)

        # Stage 2: Add the rest in batches with a progress bar.
        remaining_chunks = chunked_docs[batch_size:]
        num_batches = math.ceil(len(remaining_chunks) / batch_size)
        for i in tqdm(range(num_batches), desc="Embedding and Storing in FAISS"):
            start = i * batch_size
            end = start + batch_size
            batch = remaining_chunks[start:end]
            if batch:
                vectorstore.add_documents(batch)
            
        print("\nSuccessfully created and populated FAISS index.")

    except Exception as e:
        print(f"\nAN UNEXPECTED ERROR OCCURRED: {e}")
        return

    # --- 7. Save Final Index ---
    print("\n--- Saving final FAISS index to disk ---")
    vectorstore.save_local(INDEX_PATH)
    print(f"FAISS index is stored in the folder: '{os.path.abspath(INDEX_PATH)}'")

if __name__ == "__main__":
    main()
# ---
import asyncio
import nest_asyncio
import os
import shutil
import math
from tqdm import tqdm
import torch
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from crawl4ai import AsyncWebCrawler
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

async def main():
    """
    Main function to crawl the entire Lcapy documentation and create a FAISS index.
    """
    # --- 1. Define Configuration ---
    START_URL = "https://lcapy.readthedocs.io/en/latest/"
    TOC_LINK_SELECTOR = ".toctree-wrapper a"
    INDEX_PATH = "faiss_index_lcapy_docs"

    # --- 2. Clean up old index directory ---
    if os.path.exists(INDEX_PATH):
        print(f"--- Deleting old FAISS index directory: '{INDEX_PATH}' ---")
        shutil.rmtree(INDEX_PATH)
    print("--- Starting with a fresh index directory. ---")

    # --- 3. Discover all URLs using Requests and BeautifulSoup ---
    print(f"\n--- Step 1: Discovering all documentation URLs from '{START_URL}' ---")
    urls_to_crawl = [START_URL] # Always include the main page
    try:
        response = requests.get(START_URL)
        response.raise_for_status() # Will raise an error for bad status codes
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all link elements (<a>) that match the CSS selector
        links = soup.select(TOC_LINK_SELECTOR)
        
        for link in links:
            href = link.get('href')
            if href:
                # Convert relative links (e.g., 'netlists.html') to full URLs
                full_url = urljoin(START_URL, href)
                if full_url not in urls_to_crawl:
                    urls_to_crawl.append(full_url)
        
        print(f"Found {len(urls_to_crawl)} total pages to crawl.")

    except Exception as e:
        print(f"\nAN ERROR OCCURRED DURING URL DISCOVERY: {e}")
        return

    # --- 4. Crawl each discovered URL using crawl4ai ---
    print("\n--- Step 2: Crawling each page individually ---")
    all_docs = []
    try:
        async with AsyncWebCrawler() as crawler:
            # Use tqdm to show a progress bar for the crawling step
            for url in tqdm(urls_to_crawl, desc="Crawling Pages"):
                result = await crawler.arun(url=url)
                if result and result.markdown:
                    doc = Document(page_content=result.markdown, metadata={"source": result.url})
                    all_docs.append(doc)
    
        if not all_docs:
            print("\nCrawling did not return any documents. Exiting.")
            return

        print(f"\nSuccessfully crawled {len(all_docs)} pages.")

    except Exception as e:
        print(f"\nAN ERROR OCCURRED DURING CRAWLING: {e}")
        return

    # --- 5. Split Documents into Chunks ---
    print("\n--- Splitting documents into smaller chunks ---")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunked_docs = text_splitter.split_documents(all_docs)
    print(f"Split the documents into {len(chunked_docs)} chunks.")

    # --- 6. Create Embeddings and Persist to FAISS ---
    print("\n--- Creating local embeddings and building FAISS index ---")
    
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name='all-MiniLM-L6-v2',
            model_kwargs={'device': 'cuda' if torch.cuda.is_available() else 'cpu'}
        )
        print(f"Embedding model loaded onto {'GPU' if torch.cuda.is_available() else 'CPU'}.")

        batch_size = 512
        if not chunked_docs:
            print("No chunks to process. Exiting.")
            return

        print("Initializing FAISS index with the first batch...")
        first_batch = chunked_docs[:batch_size]
        vectorstore = FAISS.from_documents(documents=first_batch, embedding=embeddings)

        remaining_chunks = chunked_docs[batch_size:]
        num_batches = math.ceil(len(remaining_chunks) / batch_size)
        for i in tqdm(range(num_batches), desc="Embedding and Storing in FAISS"):
            start = i * batch_size
            end = start + batch_size
            batch = remaining_chunks[start:end]
            if batch:
                vectorstore.add_documents(batch)
            
        print("\nSuccessfully created and populated FAISS index.")

    except Exception as e:
        print(f"\nAN UNEXPECTED ERROR OCCURRED DURING INDEXING: {e}")
        return

    # --- 7. Save Final Index ---
    print("\n--- Saving final FAISS index to disk ---")
    vectorstore.save_local(INDEX_PATH)
    print(f"\n--- RAG data saved successfully! ---")
    print(f"FAISS index for Lcapy docs is stored in the folder: '{os.path.abspath(INDEX_PATH)}'")


if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
# ---
import asyncio
import nest_asyncio
import os
import shutil
import math
from tqdm import tqdm
import torch
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from crawl4ai import AsyncWebCrawler
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

async def main():
    """
    Main function to crawl the entire PySpice documentation and create a FAISS index.
    """
    # --- 1. Define Configuration ---
    START_URL = "https://pyspice.fabrice-salvaire.fr/releases/v1.5/index.html"
    TOC_LINK_SELECTOR = ".toctree-wrapper a"
    INDEX_PATH = "faiss_index_pyspice_docs"

    # --- 2. Clean up old index directory ---
    if os.path.exists(INDEX_PATH):
        print(f"--- Deleting old FAISS index directory: '{INDEX_PATH}' ---")
        shutil.rmtree(INDEX_PATH)
    print("--- Starting with a fresh index directory. ---")

    # --- 3. Discover all URLs using Requests and BeautifulSoup ---
    print(f"\n--- Step 1: Discovering all documentation URLs from '{START_URL}' ---")
    urls_to_crawl = [START_URL] # Always include the main page
    try:
        response = requests.get(START_URL)
        response.raise_for_status() # Will raise an error for bad status codes
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all link elements (<a>) that match the CSS selector
        links = soup.select(TOC_LINK_SELECTOR)
        
        for link in links:
            href = link.get('href')
            if href:
                # Convert relative links (e.g., 'netlists.html') to full URLs
                full_url = urljoin(START_URL, href)
                if full_url not in urls_to_crawl:
                    urls_to_crawl.append(full_url)
        
        print(f"Found {len(urls_to_crawl)} total pages to crawl.")

    except Exception as e:
        print(f"\nAN ERROR OCCURRED DURING URL DISCOVERY: {e}")
        return

    # --- 4. Crawl each discovered URL using crawl4ai ---
    print("\n--- Step 2: Crawling each page individually ---")
    all_docs = []
    try:
        async with AsyncWebCrawler() as crawler:
            # Use tqdm to show a progress bar for the crawling step
            for url in tqdm(urls_to_crawl, desc="Crawling Pages"):
                result = await crawler.arun(url=url)
                if result and result.markdown:
                    doc = Document(page_content=result.markdown, metadata={"source": result.url})
                    all_docs.append(doc)
    
        if not all_docs:
            print("\nCrawling did not return any documents. Exiting.")
            return

        print(f"\nSuccessfully crawled {len(all_docs)} pages.")

    except Exception as e:
        print(f"\nAN ERROR OCCURRED DURING CRAWLING: {e}")
        return

    # --- 5. Split Documents into Chunks ---
    print("\n--- Splitting documents into smaller chunks ---")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
    chunked_docs = text_splitter.split_documents(all_docs)
    print(f"Split the documents into {len(chunked_docs)} chunks.")

    # --- 6. Create Embeddings and Persist to FAISS ---
    print("\n--- Creating local embeddings and building FAISS index ---")
    
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name='all-MiniLM-L6-v2',
            model_kwargs={'device': 'cuda' if torch.cuda.is_available() else 'cpu'}
        )
        print(f"Embedding model loaded onto {'GPU' if torch.cuda.is_available() else 'CPU'}.")

        batch_size = 512
        if not chunked_docs:
            print("No chunks to process. Exiting.")
            return

        print("Initializing FAISS index with the first batch...")
        first_batch = chunked_docs[:batch_size]
        vectorstore = FAISS.from_documents(documents=first_batch, embedding=embeddings)

        remaining_chunks = chunked_docs[batch_size:]
        num_batches = math.ceil(len(remaining_chunks) / batch_size)
        for i in tqdm(range(num_batches), desc="Embedding and Storing in FAISS"):
            start = i * batch_size
            end = start + batch_size
            batch = remaining_chunks[start:end]
            if batch:
                vectorstore.add_documents(batch)
            
        print("\nSuccessfully created and populated FAISS index.")

    except Exception as e:
        print(f"\nAN UNEXPECTED ERROR OCCURRED DURING INDEXING: {e}")
        return

    # --- 7. Save Final Index ---
    print("\n--- Saving final FAISS index to disk ---")
    vectorstore.save_local(INDEX_PATH)
    print(f"\n--- RAG data saved successfully! ---")
    print(f"FAISS index for PySpice docs is stored in the folder: '{os.path.abspath(INDEX_PATH)}'")


if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
# ---
import asyncio
from googlesearch import search
import nest_asyncio
from github import Github, UnknownObjectException
import re
import os
from langchain.docstore.document import Document
from langchain.text_splitter import CharacterTextSplitter
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import FAISS

# --- Helper Functions ---

def get_repo_name_from_url(url):
    """Extracts 'username/repository' from a GitHub URL."""
    match = re.search(r"github\.com/([^/]+/[^/]+)", url)
    if match:
        repo_name = match.group(1)
        # Remove .git suffix if present
        if repo_name.endswith('.git'):
            return repo_name[:-4]
        return repo_name
    return None

def get_repo_files_recursive(repo, path=""):
    """
    Recursively fetches the content of all text-based files in a repository.
    Returns a list of LangChain Document objects.
    """
    all_docs = []
    
    # Common text/code file extensions to include
    text_extensions = ['.v', '.sv', '.vhd', '.py', '.md', '.txt', '.c', '.h', '.cpp', '.hpp', '.js', '.html', '.css', '.json', '.xml']

    try:
        contents = repo.get_contents(path)
        for content_file in contents:
            if content_file.type == "dir":
                # If it's a directory, recurse into it
                print(f"  Entering directory: {content_file.path}")
                all_docs.extend(get_repo_files_recursive(repo, content_file.path))
            else:
                # If it's a file, check its extension
                if any(content_file.name.endswith(ext) for ext in text_extensions):
                    print(f"  Fetching file: {content_file.path}")
                    try:
                        # Decode content and create a LangChain Document
                        file_content = content_file.decoded_content.decode('utf-8')
                        doc = Document(page_content=file_content, metadata={"source": content_file.path})
                        all_docs.append(doc)
                    except Exception as e:
                        print(f"    - Could not decode file {content_file.path}: {e}")
    except Exception as e:
        print(f"Could not get contents for path '{path}'. It might be a submodule. Error: {e}")

    return all_docs


# --- Main Application Logic ---

async def main():
    query = "risc v verilog github"
    print(f"Searching for: {query}\n")

    # --- Step 1: Search and let user choose a repository ---
    try:
        urls = list(search(query, num_results=5, lang="en"))
        github_urls = [url for url in urls if "github.com" in url]
        if not github_urls:
            print("No GitHub repositories found in the top search results.")
            return

        print("Found the following GitHub repositories:")
        for i, url in enumerate(github_urls):
            print(f"  {i+1}: {url}")

        choice = -1
        while choice < 1 or choice > len(github_urls):
            try:
                user_input = input(f"\nPlease enter the number of the repo to process (1-{len(github_urls)}): ")
                choice = int(user_input)
            except ValueError:
                print("Invalid input. Please enter a number.")
        
        repo_name = get_repo_name_from_url(github_urls[choice - 1])
        if not repo_name:
            print("Could not extract a valid repository name.")
            return

        # --- Step 2: Recursively fetch all file contents from the repo ---
        print(f"\nInspecting repository: {repo_name}")
        g = Github() 
        repo = g.get_repo(repo_name)
        
        print("\n--- Starting to retrieve all files from repository ---")
        documents = get_repo_files_recursive(repo)
        
        if not documents:
            print("\nNo text-based files found to process.")
            return
            
        print(f"\nSuccessfully retrieved {len(documents)} files.")

        # --- Step 3: Chunk the documents ---
        print("\n--- Splitting documents into smaller chunks ---")
        text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunked_docs = text_splitter.split_documents(documents)
        print(f"Split the documents into {len(chunked_docs)} chunks.")

        # --- Step 4: Create embeddings and FAISS index ---
        print("\n--- Creating embeddings and building FAISS index (this may take a while) ---")
        # Use a popular, lightweight sentence-transformer model
        embeddings = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')
        
        # This one command creates embeddings and the FAISS index
        vectorstore = FAISS.from_documents(chunked_docs, embeddings)
        print("Successfully created FAISS index from documents.")

        # --- Step 5: Save the FAISS index to disk ---
        save_path = f"faiss_index_{repo_name.replace('/', '_')}"
        vectorstore.save_local(save_path)
        print(f"\n--- RAG data saved successfully! ---")
        print(f"FAISS index and documents are stored in the folder: '{os.path.abspath(save_path)}'")
        print("You can now load this index for your RAG application.")

    except Exception as e:
        print(f"\nAn error occurred: {e}")

# Run the main asynchronous function
if __name__ == "__main__":
    nest_asyncio.apply()
    asyncio.run(main())
# ---
import asyncio
import nest_asyncio
import requests
import io
from simple_image_download import simple_image_download as simp
from PIL import Image
import matplotlib.pyplot as plt
import math
import numpy as np
from skimage.metrics import structural_similarity as ssim
import warnings

def find_most_representative_image(image_list, similarity_threshold=0.3):
    """
    Finds the largest cluster of similar images and returns only the single
    most representative image from that group.

    Args:
        image_list (list): A list of PIL Image objects.
        similarity_threshold (float): The minimum SSIM score to be considered similar.

    Returns:
        list: A list containing only the single most representative image, or an empty list.
    """
    if len(image_list) < 3:
        return image_list

    # Convert all images to grayscale numpy arrays for comparison
    gray_images = [np.array(img.convert('L')) for img in image_list]

    # Create a matrix to store similarity scores between images
    similarity_matrix = np.zeros((len(gray_images), len(gray_images)))

    for i in range(len(gray_images)):
        for j in range(i, len(gray_images)):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    score = ssim(gray_images[i], gray_images[j], data_range=gray_images[i].max() - gray_images[i].min())
                similarity_matrix[i, j] = score
                similarity_matrix[j, i] = score
            except ValueError:
                similarity_matrix[i, j] = 0
                similarity_matrix[j, i] = 0

    # Find the largest group of mutually similar images
    largest_group_indices = []
    for i in range(len(image_list)):
        current_group_indices = [i]
        for j in range(len(image_list)):
            if i == j: continue
            if similarity_matrix[i, j] > similarity_threshold:
                current_group_indices.append(j)
        
        if len(current_group_indices) > len(largest_group_indices):
            largest_group_indices = current_group_indices

    if not largest_group_indices:
        return []

    # From the largest group, find the single most representative image
    group_similarity_matrix = similarity_matrix[np.ix_(largest_group_indices, largest_group_indices)]
    avg_similarity_in_group = np.mean(group_similarity_matrix, axis=1)
    most_representative_local_index = np.argmax(avg_similarity_in_group)
    
    # Get the original index of the best image
    final_image_index = largest_group_indices[most_representative_local_index]

    return [image_list[final_image_index]]

def fetch_and_display_images(query: str, limit: int = 10, resize_to: tuple = (300, 300)):
    """
    Fetches image URLs, displays all valid ones, then filters to show only
    the single most representative image.

    Args:
        query (str): The circuit to search for.
        limit (int): The number of images to fetch.
        resize_to (tuple): The (width, height) to resize the images to.
    """
    print(f"--- Step 1: Fetching {limit} image URLs for '{query}' ---")
    
    try:
        downloader = simp.simple_image_download()
        image_urls = downloader.urls(query, limit=limit)

        if not image_urls:
            print("Could not find any image URLs.")
            return

        print(f"\n--- Step 2: Loading and displaying all valid images ---")
        
        loaded_images = []
        for url in image_urls:
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                img_data = io.BytesIO(response.content)
                img = Image.open(img_data).convert("RGB")
                img_resized = img.resize(resize_to, Image.Resampling.LANCZOS)
                loaded_images.append(img_resized)
            except Exception as e:
                print(f"Skipping image from URL {url}: {e}")
        
        if not loaded_images:
            print("No images could be successfully loaded.")
            return

        # Display all successfully loaded images
        cols = 4
        rows = math.ceil(len(loaded_images) / cols)
        fig1, axes1 = plt.subplots(rows, cols, figsize=(16, 4 * rows))
        fig1.suptitle('All Loaded Images (Unfiltered)', fontsize=16)
        axes1 = axes1.flatten()
        for i, img in enumerate(loaded_images):
            axes1[i].imshow(img)
            axes1[i].set_title(f"Image {i+1}")
            axes1[i].axis('off')
        for j in range(i + 1, len(axes1)):
            axes1[j].axis('off')
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()

        print(f"\n--- Step 3: Filtering to find the single best image ---")
        
        best_image_list = find_most_representative_image(loaded_images)
        
        if not best_image_list:
            print("Could not determine a representative image after filtering.")
            return
            
        print(f"Displaying the single most representative image.")
        
        # Display only the single best image
        best_image = best_image_list[0]
        fig2, ax2 = plt.subplots(figsize=(6, 6))
        fig2.suptitle('Most Representative Image', fontsize=16)
        ax2.imshow(best_image)
        ax2.axis('off')
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plt.show()

    except Exception as e:
        print(f"An error occurred during image processing: {e}")


def main():
    """
    Main function to run the image retrieval process.
    """
    # You may need to install scikit-image: pip install scikit-image
    circuit_query = "cascode current mirror mosfet circuit"
    fetch_and_display_images(circuit_query, limit=10)

if __name__ == "__main__":
    nest_asyncio.apply()
    main()


# === AnalogCoder/lib_info.tsv ===
Id	Type	Av (dB)	Com Av (dB)	Vin(n) Phase	Voltage Bias
0	Amplifier	17.025166965695615	NA	inverting	1.21
1	CurrentMirror	NA	NA	NA	0.0
2	Inverter	NA	NA	inverting	1.0
3	Inverter	NA	NA	inverting	0.0
4	Amplifier	-1.1483743996327227	NA	non-inverting	3.71
5	Amplifier	17.02516696691898	NA	non-inverting	0.79
6	Amplifier	3.0102999372276096	NA	inverting	1.97
7	Amplifier	24.082399647689847	NA	inverting	0.82
8	Amplifier	75.94026898353593	NA	-90 degree	1.0
9	Opamp	199.99956997487047	-40.12867535462482	inverting	2.49
10	CurrentMirror	NA	NA	NA	0.0
11	Opamp	41.61900557997383	-135.66721120644925	inverting	1.79
12	Opamp	150.36128137602688	-58.71904858948874	inverting	1.65
13	Opamp	24.044031388496503	21.58664528028884	inverting	0.87
14	Amplifier	44.128945502128325	NA	inverting	1.65


# === analogcoder/subcircuit_lib/p10_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class CommonSourceAmpDiodeLoad(SubCircuitFactory):
	NAME = ('CommonSourceAmpDiodeLoad')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supply and Input Signal
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		# Single-Stage Amplifier: Common-Source with PMOS Diode-Connected Load
		# parameters: name, drain, gate, source, bulk, model, w, l
		self.MOSFET('1', 'Vout', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vin', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		# Include the PMOS diode-connected load
		self.MOSFET('3', 'Vout', 'Vout', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)


# === analogcoder/subcircuit_lib/p11_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class SingleStageOpamp(SubCircuitFactory):
	NAME = ('SingleStageOpamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)


# === analogcoder/subcircuit_lib/p12_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class CascodeCurrentMirror(SubCircuitFactory):
	NAME = ('CascodeCurrentMirror')
	NODES = ('Iref', 'Iout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		self.V('inp', 'Vinp', self.gnd, 2.5)
		self.V('inn', 'Vinn', self.gnd, 2.5)
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)


# === analogcoder/subcircuit_lib/p13_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class SingleStageDiffCommonSourceOpamp(SubCircuitFactory):
	NAME = ('SingleStageDiffCommonSourceOpamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supplies for the power and tail current source
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		# Tail Current Source Biasing (Adjusted to ensure NMOS 3 is activated properly)
		self.V('bias', 'Vbias', self.gnd, 1.5) # Adjusted bias voltage for tail current source
		# Differential Input Voltage Sources (Adjusted to ensure NMOS 1 and NMOS 2 are activated)
		# Differential Pair with adjusted source voltage for activation
		self.MOSFET('1', 'Vout', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6) # Output taken from Drain1
		self.MOSFET('2', 'Drain2', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		# Tail Current Source with adjusted parameters for proper activation
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Load Resistors
		self.R('1', 'Vout', 'Vdd', 1@u_kΩ) # Connected to Vout for correct output node identification
		self.R('2', 'Drain2', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p14_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class OpampResistanceLoad(SubCircuitFactory):
	NAME = ('OpampResistanceLoad')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		# Bias voltages and input signals
		self.V('bias1', 'Vbias1', self.gnd, 2.5)  # Bias for active loads
		self.V('bias2', 'Vbias2', self.gnd, 1.0)  # Bias for tail current source
		self.V('bias3', 'Vbias3', self.gnd, 2.5)  # Bias for second stage active load
		# First Stage: Differential Pair with Active Load and Tail Current Source
		self.MOSFET('1', 'Drain1', 'Vinp', 'Source5', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Drain2', 'Vinn', 'Source5', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Drain1', 'Vbias1', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('4', 'Drain2', 'Vbias1', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Source5', 'Vbias2', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Second Stage: Common-Source with Active Load
		self.MOSFET('6', 'Vout', 'Drain1', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		self.MOSFET('7', 'Vout', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)


# === analogcoder/subcircuit_lib/p15_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class SingleStageDiffOpamp(SubCircuitFactory):
	NAME = ('SingleStageDiffOpamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supply
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		# Input and Bias Voltages
		self.V('bias1', 'Vbias1', self.gnd, 1.5@u_V) # Bias for NMOS cascode
		self.V('bias2', 'Vbias2', self.gnd, 1.5@u_V) # Bias for NMOS cascode
		self.V('bias3', 'Vbias3', self.gnd, 3.5@u_V) # Bias for PMOS cascode
		self.V('bias4', 'Vbias4', self.gnd, 3.5@u_V) # Bias for PMOS cascode
		self.V('biasTail', 'VbiasTail', self.gnd, 1.0@u_V) # Bias for the tail current source
		# NMOS Transistors
		self.MOSFET('1', 'Drain1', 'Vinp', 'Source5', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Drain2', 'Vinn', 'Source5', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Voutp', 'Vbias1', 'Drain1', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('4', 'Vout', 'Vbias2', 'Drain2', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('5', 'Source5', 'VbiasTail', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		# PMOS Transistors
		self.MOSFET('6', 'Voutp', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('7', 'Voutp', 'Vbias4', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('8', 'Vout', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('9', 'Vout', 'Vbias4', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)


# === analogcoder/subcircuit_lib/p1_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class SingleStageAmp(SubCircuitFactory):
	NAME = ('SingleStageAmp')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET model
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply for the power and input signal
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		# Common-Source Amplifier with Resistor Load
		# parameters: name, drain, gate, source, bulk, model, w, l
		self.MOSFET('1', 'Vout', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('1', 'Vout', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p2_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class ThreeStageAmp(SubCircuitFactory):
	NAME = ('ThreeStageAmp')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply for the power
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		# Input Signal
		# First Stage: Common-Source with Resistor Load
		self.MOSFET('1', 'Drain1', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('1', 'Drain1', 'Vdd', 1@u_kΩ)
		# Second Stage: Common-Source with Resistor Load
		self.MOSFET('3', 'Drain2', 'Drain1', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('2', 'Drain2', 'Vdd', 1@u_kΩ)
		# Third Stage: Common-Source with Resistor Load
		self.MOSFET('5', 'Vout', 'Drain2', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('3', 'Vout', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p3_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class CommonDrainAmp(SubCircuitFactory):
	NAME = ('CommonDrainAmp')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET model
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply for the power
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		# Common-Drain Amplifier with Resistor Load
		self.MOSFET('1', 'Vdd', 'Vin', 'Vout', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('load', 'Vout', self.gnd, 1@u_kΩ)


# === analogcoder/subcircuit_lib/p4_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class CommonGateAmp(SubCircuitFactory):
	NAME = ('CommonGateAmp')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET model
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply and Bias Voltage
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5) # Bias voltage for the gate of M1, ensuring it's above threshold
		# Input Signal
		# NMOS Transistor
		self.MOSFET('1', 'Vout', 'Vbias', 'Vin', 'Vin', model='nmos_model', w=50e-6, l=1e-6)
		# Load Resistor
		self.R('1', 'Vout', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p5_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class SingleStageCascodeAmp(SubCircuitFactory):
	NAME = ('SingleStageCascodeAmp')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the NMOS transistor model
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply for the power and input signal
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 3.0)  # Bias voltage for the upper transistor
		# Cascode Amplifier Design
		# Lower NMOS transistor M1
		self.MOSFET('1', 'Drain1', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		# Upper NMOS transistor M2 (Cascode)
		self.MOSFET('2', 'Vout', 'Vbias', 'Drain1', self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		# Resistive Load
		self.R('load', 'Vout', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p6_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class NMOSInverter(SubCircuitFactory):
	NAME = ('NMOSInverter')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET model
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply for the power and input signal
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		# Common-Source Amplifier with Resistor Load
		# parameters: name, drain, gate, source, bulk, model, w, l
		self.MOSFET('1', 'Vout', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('1', 'Vout', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p7_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class LogicalInverter(SubCircuitFactory):
	NAME = ('LogicalInverter')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET model
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply for the power and input signal
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		# Common-Source Amplifier with Resistor Load
		# parameters: name, drain, gate, source, bulk, model, w, l
		self.MOSFET('1', 'Vout', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('1', 'Vout', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p8_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class NMOSConstantCurrentSource(SubCircuitFactory):
	NAME = ('NMOSConstantCurrentSource')
	NODES = ('Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET model
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		# Power Supply for the power and input signal
		self.V('dd', 'Vdd', self.gnd, 5.0) # 5V power supply
		self.V('in', 'Vin', self.gnd, 1.5)
		# Common-Source Amplifier with Resistor Load
		# parameters: name, drain, gate, source, bulk, model, w, l
		self.MOSFET('1', 'Vout', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.R('1', 'Vout', 'Vdd', 1@u_kΩ)


# === analogcoder/subcircuit_lib/p9_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class TwoStageOpampMiller(SubCircuitFactory):
	NAME = ('TwoStageOpampMiller')
	NODES = ('Vin', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5@u_V) # 5V power supply
		self.V('bias1', 'Vbias1', self.gnd, 4@u_V) # Bias for M2
		self.V('bias2', 'Vbias2', self.gnd, 4@u_V) # Bias for M4
		# First Stage: Common-Source with Active Load
		self.MOSFET('1', 'Drain1', 'Vin', self.gnd, self.gnd, model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Drain1', 'Vbias1', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		# Second Stage: Common-Source with Active Load
		self.MOSFET('3', 'Vout', 'Drain1', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		self.MOSFET('4', 'Vout', 'Vbias2', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		# Miller Compensation Capacitor
		self.C('c', 'Drain1', 'Vout', 10@u_pF)


# === analogcoder/sample_design/p1.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Common-Source Amplifier')
# Define the NMOS transistor model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supply for the power and input signal
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
circuit.V('in', 'Vin', circuit.gnd, 1.5)
# Single-Stage Common-Source Amplifier with Resistive Load
circuit.MOSFET('1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('1', 'Vout', 'Vdd', 1@u_kΩ)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p10.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Amplifier with PMOS Diode-Connected Load')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supplies for the power and input signal
circuit.V('dd', 'Vdd', circuit.gnd, 5.0) # 5V power supply
circuit.V('in', 'Vin', circuit.gnd, 2.5)
# Amplifier Stage: Common-Source with PMOS Diode-Connected Load
# parameters: name, drain, gate, source, bulk, model, w, l
circuit.MOSFET('1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Vout', 'Vout', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p11.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Differential OpAmp with Active Load')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supplies
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
circuit.V('bias', 'Vbias', circuit.gnd, 1.5)  # Bias voltage for the tail current source M3
# Input Voltage Sources for Differential Inputs
circuit.V('inp', 'Vinp', circuit.gnd, 2.5)
circuit.V('inn', 'Vinn', circuit.gnd, 2.5)
# Differential Pair and Tail Current Source
circuit.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('3', 'Source3', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=100e-6, l=1e-6)
# Active Current Mirror Load
circuit.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p12.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Cascode Current Mirror')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0) # 5V power supply
# Reference Current Source
circuit.I('ref', 'Vdd', 'Iref', 1@u_mA) # 1mA reference current
# Input Side (Reference Side)
circuit.MOSFET('1', 'Iref', 'Iref', 'Source2', 'Source2', model='nmos_model', w=50e-6, l=1e-6) # Diode-connected M1
circuit.MOSFET('2', 'Source2', 'Iref', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6) # M2
# Output Side
circuit.MOSFET('3', 'Iout', 'Iref', 'Source4', 'Source4', model='nmos_model', w=50e-6, l=1e-6) # M3
circuit.MOSFET('4', 'Source4', 'Iref', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6) # M4
# Load Resistor
circuit.R('1', 'Iout', 'Vdd', 1@u_kΩ)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p13.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Differential Common-Source Opamp')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supplies for the power and input signal
circuit.V('dd', 'Vdd', circuit.gnd, 5.0) # 5V power supply
circuit.V('bias', 'Vbias', circuit.gnd, 1.0) # 1V input for bias voltage (= V_th + 0.5 = 0.5 + 0.5 = 1.0)
circuit.V('inp', 'Vinp', circuit.gnd, 0.93)
circuit.V('inn', 'Vinn', circuit.gnd, 0.93)
# Differential Pair: M1 and M2
circuit.MOSFET('1', 'Drain1', 'Vinp', 'SourceCommon', 'SourceCommon', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Drain2', 'Vinn', 'SourceCommon', 'SourceCommon', model='nmos_model', w=50e-6, l=1e-6)
# Tail Current Source: M3
circuit.MOSFET('3', 'SourceCommon', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=100e-6, l=1e-6)
# Load Resistors
circuit.R('1', 'Drain1', 'Vdd', 10@u_kΩ) # Load resistor for M1
circuit.R('2', 'Drain2', 'Vdd', 10@u_kΩ) # Load resistor for M2
# Output
circuit.R('load', 'Vout', 'Drain1', 1@u_Ω) # Ideal wire for output node
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p14.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Two-Stage Differential Opamp')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0) # 5V power supply
circuit.V('bias1', 'Vbias1', circuit.gnd, 1.0) # Bias voltage for tail current source
circuit.V('bias2', 'Vbias2', circuit.gnd, 4.0) # Bias voltage for first active load
circuit.V('bias3', 'Vbias3', circuit.gnd, 4.0) # Bias voltage for second active load
# Differential Input
circuit.V('inp', 'Vinp', circuit.gnd, 1.25)
circuit.V('inn', 'Vinn', circuit.gnd, 1.25)
# First Stage: Differential Pair with Active Load and Tail Current Source
circuit.MOSFET('1', 'Drain1', 'Vinp', 'Source1', 'Source1', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Drain2', 'Vinn', 'Source1', 'Source1', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('5', 'Source1', 'Vbias1', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('6', 'Drain1', 'Drain1', 'Vdd', 'Vdd', model='pmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('7', 'Drain2', 'Drain1', 'Vdd', 'Vdd', model='pmos_model', w=50e-6, l=1e-6)
# Second Stage: Common-Source Amplifier with Active Load
circuit.MOSFET('3', 'Voutp', 'Drain1', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('8', 'Voutp', 'Vbias2', 'Vdd', 'Vdd', model='pmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Vout', 'Drain2', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('9', 'Vout', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=50e-6, l=1e-6)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p15.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Telescopic Cascode Opamp')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
# Bias Voltages
circuit.V('bias1', 'Vbias1', circuit.gnd, 1.5)  # Bias voltage for NMOS cascode
circuit.V('bias2', 'Vbias2', circuit.gnd, 3.5)  # Bias voltage for PMOS cascode load
circuit.V('bias3', 'Vbias3', circuit.gnd, 4.0)  # Additional bias for PMOS cascode load
circuit.V('bias4', 'Vbias4', circuit.gnd, 1.0)  # Bias voltage for tail current source
# Input Signals
circuit.V('inp', 'Vinp', circuit.gnd, 1.48)
circuit.V('inn', 'Vinn', circuit.gnd, 1.48)
# Input Differential Pair
circuit.MOSFET('1', 'Drain1', 'Vinp', 'Source1', 'Source1', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Drain2', 'Vinn', 'Source1', 'Source1', model='nmos_model', w=50e-6, l=1e-6)
# Cascode Devices
circuit.MOSFET('3', 'Voutp', 'Vbias1', 'Drain1', 'Drain1', model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('4', 'Vout', 'Vbias1', 'Drain2', 'Drain2', model='nmos_model', w=50e-6, l=1e-6)
# Cascode Loads
circuit.MOSFET('5', 'Voutp', 'Vbias2', 'Source3', 'Source3', model='pmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('6', 'Vout', 'Vbias2', 'Source4', 'Source4', model='pmos_model', w=100e-6, l=1e-6)
# Additional Cascode Loads
circuit.MOSFET('7', 'Source3', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('8', 'Source4', 'Vbias3', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Tail Current Source
circuit.MOSFET('9', 'Source1', 'Vbias4', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p16.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from p_lib import *
circuit = Circuit('RC Phase-Shift Oscillator')
# Define the DC operating voltage
Vdc = 2.5 @ u_V
# Add a DC voltage source for the operating point
circuit.V(1, 'Vdc', circuit.gnd, Vdc)
# Declare the subcircuit for the op-amp
circuit.subcircuit(SingleStageOpamp())
# Create the RC phase-shift network
R1 = 10 @ u_kΩ
C1 = 10 @ u_nF
R2 = 10 @ u_kΩ
C2 = 10 @ u_nF
R3 = 10 @ u_kΩ
C3 = 10 @ u_nF
# Connect the RC network
circuit.R(1, 'Vout', 'node1', R1)
circuit.C(1, 'node1', 'node2', C1)
circuit.R(2, 'node2', 'node3', R2)
circuit.C(2, 'node3', 'node4', C2)
circuit.R(3, 'node4', 'node5', R3)
circuit.C(3, 'node5', 'Vdc', C3)
# Connect node2 to ground through a resistor to avoid floating node
circuit.R(5, 'node2', circuit.gnd, 10 @ u_kΩ)
# Connect the op-amp
circuit.X('op', 'SingleStageOpamp', 'node5', 'Vdc', 'Vout')
# Connect the feedback from the output to the input of the RC network
circuit.R(4, 'node1', 'Vdc', 10 @ u_kΩ)
# Create a simulator instance
simulator = circuit.simulator()

# === analogcoder/sample_design/p17.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from subcircuits.diffop import *


circuit = Circuit('Wien Bridge Oscillator')

# Declare and instantiate the opamp
circuit.subcircuit(SingleStageOpamp())
circuit.X('op1', 'SingleStageOpamp', 'Vinp', 'Vinn', 'Vout')

# Component values
R1 = 10@u_kΩ
R2 = 10@u_kΩ
C1 = 10@u_nF
C2 = 10@u_nF

# Wien Bridge network elements
circuit.R('1', 'Vout', 'n1', R1)  # R1 from Vout to node n1
circuit.C('1', 'n1', 'Vinp', C1)  # C1 from n1 to inverting input of opamp

circuit.R('2', 'Vinp', 'Vbias', R2)  # R2 from node n1 back to Vout, creating a series feedback
circuit.C('2', 'Vinp', 'Vbias', C2)  # C2 from Vout to ground, parallel to R2

circuit.R('f', 'Vout', 'Vinn', R1)
circuit.R('b', 'Vinn', 'Vbias', R1/10.0)

# Non-inverting input setup
circuit.V('bias', 'Vbias', circuit.gnd, 2.5@u_V)  # Bias voltage for the non-inverting input

simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p18.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from subcircuits.diffop import *
circuit = Circuit('Opamp Integrator')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Declare the subcircuit for the opamp
circuit.subcircuit(SingleStageOpamp())
# Create a subcircuit instance for the opamp
circuit.X('opamp', 'SingleStageOpamp', 'Vinp', 'Vinn', 'Vout')
# Define the input voltage source
circuit.V('input', 'Vin', circuit.gnd, 2.5@u_V)
# Define the resistor R1 and capacitor Cf
R1 = 1@u_kΩ  # 1k ohm resistor
Cf = 1@u_uF  # 1uF capacitor
# Connect the resistor R1 between the input voltage source and the inverting input of the opamp
circuit.R('R1', 'Vin', 'Vinn', R1)
# Connect the capacitor Cf between the inverting input and the output of the opamp
circuit.C('Cf', 'Vinn', 'Vout', Cf)
# Connect the non-inverting input of the opamp to a reference voltage (2.5 V, same as the operating point)
circuit.V('ref', 'Vinp', circuit.gnd, 2.5@u_V)
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p19.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from subcircuits.diffop import *
circuit = Circuit('Opamp Differentiator')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Input voltage source
circuit.V('input', 'Vin', circuit.gnd, 2.5@u_V)
# DC operating voltage for the non-inverting input
circuit.V('dc_bias', 'Vdc', circuit.gnd, 2.5@u_V)
# Declare and use the SingleStageOpamp subcircuit
circuit.subcircuit(SingleStageOpamp())
circuit.X('op', 'SingleStageOpamp', 'Vdc', 'n1', 'Vout')
# Components for differentiator
Rf = 10@u_kΩ
C1 = 10@u_nF
# Connect the components
circuit.R('f', 'Vout', 'n1', Rf)
circuit.C('1', 'n1', 'Vin', C1)
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p2.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Three-Stage Amplifier')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supplies for the power and input signal
circuit.V('dd', 'Vdd', circuit.gnd, 5.0) # 5V power supply
circuit.V('in', 'Vin', circuit.gnd, 1.65)
# First Stage: Common-Source with Resistor Load
circuit.MOSFET('1', 'Drain1', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('1', 'Drain1', 'Vdd', 1@u_kΩ)
# Second Stage: Common-Source with Resistor Load
circuit.MOSFET('2', 'Drain2', 'Drain1', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('2', 'Drain2', 'Vdd', 1@u_kΩ)
# Third Stage: Common-Source with Resistor Load
circuit.MOSFET('3', 'Vout', 'Drain2', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.R('3', 'Vout', 'Vdd', 1@u_kΩ)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p20.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from subcircuits.diffop import *
circuit = Circuit('Opamp Adder')
# Define the input voltages
circuit.V('input1', 'Vin1', circuit.gnd, 1@u_V)
circuit.V('input2', 'Vin2', circuit.gnd, 1@u_V)
# Declare the subcircuit
circuit.subcircuit(SingleStageOpamp())
# Create a subcircuit instance
circuit.X('opamp', 'SingleStageOpamp', 'Vinp', 'Vinn', 'Vout')
# Resistors for the inverting summing amplifier configuration
R1 = 10@u_kΩ
R2 = 10@u_kΩ
Rf = 10@u_kΩ
# Connect the resistors
circuit.R(1, 'Vin1', 'Vinn', R1)
circuit.R(2, 'Vin2', 'Vinn', R2)
circuit.R(3, 'Vinn', 'Vout', Rf)
# Bias the non-inverting input to 2.5V
circuit.V('bias', 'Vinp', circuit.gnd, 2.5@u_V)
# Ground the inverting input through a resistor to set the operating point
circuit.R('ground', 'Vinn', circuit.gnd, 1@u_MΩ)
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p21.py ===
import math
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from subcircuits.diffop import *
circuit = Circuit('Opamp Subtractor')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Define input voltages
circuit.V('input1', 'Vin1', circuit.gnd, 2.75@u_V)
circuit.V('input2', 'Vin2', circuit.gnd, 5.00@u_V)
# Declare the subcircuit
circuit.subcircuit(SingleStageOpamp())
# Resistor values
R1 = 10@u_kΩ
R2 = 10@u_kΩ
# Create the subtractor circuit using the opamp and resistors
circuit.R('1', 'Vin1', 'Vinn', R1)
circuit.R('2', 'Vin2', 'Vinp', R1)
circuit.R('3', 'Vinn', 'Vout', R2)
circuit.R('4', 'Vinp', circuit.gnd, R2)
# Create a subcircuit instance
circuit.X('opamp', 'SingleStageOpamp', 'Vinp', 'Vinn', 'Vout')
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p22.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
from subcircuits.diffop import *

circuit = Circuit('Schmitt Trigger')

# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)

# Set the DC supply voltage
Vdd = 5.0@u_V

# Define the DC operating voltage for Vinp/Vinn
Vop = 2.5@u_V

# Declare the subcircuit
circuit.subcircuit(SingleStageOpamp())

# Create a subcircuit instance
circuit.X('opamp', 'SingleStageOpamp', 'non_inverting', 'inverting', 'Vout')

# Define feedback resistors for hysteresis
Rf = 20@u_kΩ # Feedback resistor
R1 = 10@u_kΩ  # Input resistor

# Connect the non-inverting input to the output through the feedback resistor
circuit.R('f', 'non_inverting', 'Vout', Rf)
# Connect a resistor from the input to the non-inverting input
circuit.R('1', 'Vin', 'non_inverting', R1)

# Connect the inverting input to ground through a resistor to set the reference voltage
circuit.R('2', 'inverting', circuit.gnd, R1)

# Connect a resistor from Vdd to the inverting input to form a voltage divider with R2
# This sets the inverting input to Vdd/2 when the output is at Vdd (positive feedback condition)
circuit.R('3', 'Vdd', 'inverting', R1)
circuit.V('dd', 'Vdd', circuit.gnd, Vdd)
circuit.V('in', 'Vin', circuit.gnd, 1.0@u_V)

# Finalize the Circuit
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p23.py ===
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

class OpAmp(SubCircuitFactory):
    __name__ = 'op_amp'
    __nodes__ = ('vdd', 'vss', 'in_p', 'in_n', 'vout')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.M(1, 'v1', 'v2', 'vdd', 'vdd', model='pmos_m')
        self.M(2, 'v2', 'v2', 'vdd', 'vdd', model='pmos_m')
        self.M(3, 'vout', 'v2', 'vdd', 'vdd', model='pmos_m')
        self.M(4, 'v3', 'in_n', 'v1', 'vdd', model='pmos_m')
        self.M(5, 'v4', 'in_p', 'v1', 'vdd', model='pmos_m')

        self.M(6, 'v3', 'v3', 'vss', 'vss', model='nmos_m')
        self.M(7, 'v4', 'v3', 'vss', 'vss', model='nmos_m')
        self.M(8, 'v2', 'vdd', 'vss', 'vss', model='nmos_m')
        self.M(9, 'vout', 'v4', 'vss', 'vss', model='nmos_m')

circuit = Circuit('Voltage Controlled Oscillator with two OP Amps')
circuit.model('nmos_model', 'nmos', level=1, kp=1000e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.V('in', 'vin', circuit.gnd, 0.7@u_V)

R1 = 15@u_kΩ
R2 = 30@u_kΩ
R3 = 1@u_kΩ
R4 = 30@u_kΩ
R5 = 3@u_kΩ
R6 = 30@u_kΩ
R7 = 30@u_kΩ
C1 = 5e-1@u_nF

opamp_kp = 400e-6; opamp_vto = 0.4

circuit.R(1, 'vin', 'op1_n', R1)
circuit.R(2, 'vin', 'op1_p', R2)
circuit.R(3, 'nmos_g', 'vout', R3)
circuit.R(4, 'op1_p', circuit.gnd, R4)
circuit.R(5, 'nmos_d', 'op1_n', R5)
circuit.R(6, 'op2_p', circuit.gnd, R6)
circuit.R(7, 'op2_p', 'vout', R7)

circuit.C(1, 'op1_n', 'vout_1', C1)

circuit.M(1, 'nmos_d', 'nmos_g', circuit.gnd, circuit.gnd, model='nmos_model')

circuit.subcircuit(OpAmp(2*opamp_kp, opamp_vto))
circuit.X('1', 'op_amp', 'vdd', circuit.gnd, 'op1_p', 'op1_n', 'vout_1')

circuit.subcircuit(OpAmp(0.7*opamp_kp, opamp_vto))
circuit.X('2', 'op_amp', 'vdd', circuit.gnd, 'op2_p', 'vout_1', 'vout')

simulator = circuit.simulator()

# === analogcoder/sample_design/p24.py ===
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

from subcircuits import charge_pump, divider, loop_filter, pfd, ring_vco

###### Netlist #######
circuit = Circuit('Phase Locked Loop')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class PLL(SubCircuitFactory):
    __name__ = 'pll'
    __nodes__ = ('vdd', 'vss', 'clk_ref', 'UP', 'DN', 'vctrl',
                 'clk_p', 'clk_n', 'clk_p_45', 'clk_n_45',
                 'clk_p_90', 'clk_n_90', 'clk_p_135', 'clk_n_135')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()
        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.subcircuit(pfd.PFD(kp=5*kp, vto=vto))
        self.X('0', 'pfd', 'vdd', 'vss', 'clk_ref', 'clk_p', 'UP', 'DN')

        self.subcircuit(charge_pump.ChargePump(kp=3*kp, vto=vto))
        self.X('1', 'charge_pump', 'vdd', 'vss', 'UP', 'DN', 'vctrl')

        self.subcircuit(loop_filter.LF_t2o3(R1=0.1@u_kΩ, R2=3@u_kΩ,
                                            C1=50@u_pF, C2=0.5@u_pF))
        self.X('2', 'loop_filter', 'vss', 'vctrl', 'vctrl_delay')

        self.subcircuit(ring_vco.RingVCO(kp=kp, vto=vto))
        self.X('3', 'ring_vco', 'vdd', 'vss', 'vctrl_delay', 'clk_p', 'clk_n',
                                                             'clk_p_45', 'clk_n_45',
                                                             'clk_p_90', 'clk_n_90',
                                                             'clk_p_135', 'clk_n_135')



circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)



circuit.subcircuit(PLL(400e-6, 0.4))
circuit.X('0', 'pll', 'vdd', circuit.gnd, 'clk_ref', 'UP', 'DN', 'vctrl',
          'clk_p', 'clk_n', 'clk_p_45', 'clk_n_45',
          'clk_p_90', 'clk_n_90', 'clk_p_135', 'clk_n_135')

##### Simulation #####
simulator = circuit.simulator()

# === analogcoder/sample_design/p3.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Common-Drain Amplifier')
# Define the MOSFET model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
# Input Signal Source
circuit.V('in', 'Vin', circuit.gnd, 4.0)
# NMOS Transistor - Common Drain Configuration
circuit.MOSFET('1', 'Vdd', 'Vin', 'Vout', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Load Resistor
circuit.R('1', 'Vout', circuit.gnd, 1@u_kΩ)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p4.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Common-Gate Amplifier')
# Define the MOSFET model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supply and Bias Voltage
circuit.V('dd', 'Vdd', circuit.gnd, 5.0) # 5V power supply
circuit.V('bias', 'Vbias', circuit.gnd, 1.5) # Bias voltage for the gate of M1, ensuring it's above threshold
# Input Signal
circuit.V('in', 'Vin', circuit.gnd, 0.0)
# NMOS Transistor
circuit.MOSFET('1', 'Vout', 'Vbias', 'Vin', 'Vin', model='nmos_model', w=50e-6, l=1e-6)
# Load Resistor
circuit.R('1', 'Vout', 'Vdd', 1@u_kΩ)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p5.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Single-Stage Cascode Amplifier')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supplies for the power and input signal
circuit.V('dd', 'Vdd', circuit.gnd, 5.0) # 5V power supply
circuit.V('in', 'Vin', circuit.gnd, 1.5)
circuit.V('bias', 'Vbias', circuit.gnd, 2.5) # Bias voltage for M2, ensuring it's in saturation
# First Stage: Common-Source with NMOS M1
circuit.MOSFET('1', 'Drain1', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Cascode Stage with NMOS M2
circuit.MOSFET('2', 'Vout', 'Vbias', 'Drain1', circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Load Resistor
circuit.R('1', 'Vout', 'Vdd', 1@u_kΩ)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p6.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('NMOS Inverter')
# Define the NMOS model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supply for the circuit
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
# Input signal source
circuit.V('in', 'Vin', circuit.gnd, 1.0)  # 1V input for bias voltage
# NMOS Inverter Configuration
circuit.MOSFET('1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Load Resistor
circuit.R('1', 'Vout', 'Vdd', 1@u_kΩ)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p7.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('CMOS Inverter')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supply
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
# Input Signal
circuit.V('in', 'Vin', circuit.gnd, 2.5)  # Midpoint biasing for switching
# NMOS and PMOS for Inverter
circuit.MOSFET('1', 'Vout', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Vout', 'Vin', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p8.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('NMOS Constant Current Source with Resistive Load')
# Define the MOSFET model
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
# Power Supplies for the power and bias voltage
circuit.V('dd', 'Vdd', circuit.gnd, 5.0)  # 5V power supply
circuit.V('bias', 'Vbias', circuit.gnd, 1.5)  # Bias voltage (greater than V_th to ensure saturation)
# NMOS Constant Current Source Setup
circuit.M('1', 'Vout', 'Vbias', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
# Load Resistor
circuit.R('1', 'Vout', 'Vdd', 1@u_kΩ)  # Resistor value as 1kΩ
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p9.py ===
from PySpice.Spice.Netlist import Circuit
from PySpice.Unit import *
circuit = Circuit('Two-Stage Amplifier with Miller Compensation')
# Define the MOSFET models
circuit.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
circuit.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
# Power Supplies
circuit.V('dd', 'Vdd', circuit.gnd, 5@u_V) # 5V power supply
circuit.V('in', 'Vin', circuit.gnd, 1.0)
circuit.V('bias1', 'Vbias1', circuit.gnd, 4@u_V) # Bias for M2
circuit.V('bias2', 'Vbias2', circuit.gnd, 4@u_V) # Bias for M4
# First Stage: Common-Source with Active Load
circuit.MOSFET('1', 'Drain1', 'Vin', circuit.gnd, circuit.gnd, model='nmos_model', w=50e-6, l=1e-6)
circuit.MOSFET('2', 'Drain1', 'Vbias1', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Second Stage: Common-Source with Active Load
circuit.MOSFET('3', 'Vout', 'Drain1', circuit.gnd, circuit.gnd, model='nmos_model', w=100e-6, l=1e-6)
circuit.MOSFET('4', 'Vout', 'Vbias2', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
# Miller Compensation Capacitor
circuit.C('c', 'Drain1', 'Vout', 10@u_pF)
# Analysis Part
simulator = circuit.simulator()
analysis = simulator.operating_point()

# === analogcoder/sample_design/p_lib.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class SingleStageOpamp(SubCircuitFactory):
	NAME = ('SingleStageOpamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

# === analogcoder/sample_design/subcircuits/charge_pump.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

from subcircuits import opamp, loop_filter, logic_gates


###### Netlist #######
circuit = Circuit('Charge Pump')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class ChargePump(SubCircuitFactory):
    __name__ = 'charge_pump'
    __nodes__ = ('vdd', 'vss', 'up', 'dn', 'vctrl')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)
        self.model('nmos_m2', 'nmos', level=1, kp=kp*10, vto=vto)
        self.model('pmos_m2', 'pmos', level=1, kp=kp*10, vto=-vto)

        self.CurrentSource('1', 'vdd', 'vn1', 300@u_uA)

        self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        self.X('0', 'inv', 'vdd', 'vss', 'dn', 'dn_inv')

        self.M(1, 'vp1', 'vp1', 'vdd', 'vdd', model='pmos_m2')
        # self.M(2, 'op1_p', 'vp2', 'vdd', 'vdd', model='pmos_m')
        # self.M(3, 'op2_p', 'vp1', 'vdd', 'vdd', model='pmos_m')
        self.M(4, 'm4_d', 'dn_inv', 'vdd', 'vdd', model='pmos_m')
        # self.M(5, 'm5_d', 'dn_inv', 'vdd', 'vdd', model='pmos_m')
        self.M(6, 'vctrl', 'vp1', 'm4_d', 'vdd', model='pmos_m')
        # self.M(7, 'vctrl', 'vp2', 'm5_d', 'vdd', model='pmos_m')

        # self.subcircuit(opamp.OpAmp(kp=kp, vto=0.4))
        # self.X('1', 'op_amp', 'vdd', 'vss', 'op1_p', 'vctrl', 'vp2')

        # self.subcircuit(opamp.OpAmp(kp=kp, vto=0.4))
        # self.X('2', 'op_amp', 'vdd', 'vss', 'op2_p', 'vctrl', 'vn2')

        self.M(8, 'vn1', 'vn1', 'vss', 'vss', model='nmos_m2')
        self.M(9, 'vp1', 'vn1', 'vss', 'vss', model='nmos_m2')
        # self.M(10, 'op1_p', 'vn1', 'vss', 'vss', model='nmos_m')
        # self.M(11, 'op2_p', 'vn2', 'vss', 'vss', model='nmos_m')
        self.M(12, 'm12_d', 'up', 'vss', 'vss', model='nmos_m')
        # self.M(13, 'm13_d', 'up', 'vss', 'vss', model='nmos_m')
        self.M(14, 'vctrl', 'vn1', 'm12_d', 'vss', model='nmos_m')
        # self.M(15, 'vctrl', 'vn2', 'm13_d', 'vss', model='nmos_m')



circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.PulseVoltageSource('1', 'up', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=90@u_ns, period=200@u_ns, delay_time=10@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)
circuit.PulseVoltageSource('2', 'dn', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=30@u_ns, period=200@u_ns, delay_time=70@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)

circuit.subcircuit(ChargePump(400e-6, 0.4))
circuit.X('0', 'charge_pump', 'vdd', circuit.gnd, 'up', 'dn', 'vctrl')

circuit.subcircuit(loop_filter.LF_t2o3(R1=1@u_kΩ, R2=1@u_kΩ,
                                       C1=30@u_pF, C2=5@u_pF))
circuit.X('1', 'loop_filter', circuit.gnd, 'vctrl')
######################


##### Simulation #####
# simulator = circuit.simulator(temperature=25, nominal_temperature=25)
# # simulator.initial_condition(vctrl=0.5@u_V, op1_p=0.5@u_V, op2_p=0.5@u_V)
# analysis = simulator.transient(step_time=100@u_ns, end_time=1@u_us)

# fig = plt.figure()
# # plt.ylim((-0.02, 1.02))
# plt.plot(list(analysis.time), list(analysis["up"]))
# plt.plot(list(analysis.time), list(analysis["dn"]))
# plt.plot(list(analysis.time), list(analysis["vctrl"]))
# # plt.plot(list(analysis.time), list(analysis["vn1"]))
# # plt.plot(list(analysis.time), list(analysis["vp1"]))
# plt.show()
# fig.savefig("./outputs/charge_pump.png")
# plt.close(fig)
######################

# === analogcoder/sample_design/subcircuits/dff.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

from subcircuits import logic_gates


###### Netlist #######
circuit = Circuit('D Flip Flop')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class DFF(SubCircuitFactory):
    __name__ = 'd_flip_flop'
    __nodes__ = ('vdd', 'vss', 'D', 'CLK', 'Q')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        self.X('1', 'inv', 'vdd', 'vss', 'CLK', 'CLKB')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('2', 'tinv', 'vdd', 'vss', 'D', 'CLKB', 'v1')

        self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        self.X('3', 'inv', 'vdd', 'vss', 'v1', 'v1_b')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('4', 'tinv', 'vdd', 'vss', 'v1_b', 'CLK', 'v1')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('5', 'tinv', 'vdd', 'vss', 'v1_b', 'CLK', 'v2')

        self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        self.X('6', 'inv', 'vdd', 'vss', 'v2', 'Q')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('7', 'tinv', 'vdd', 'vss', 'Q', 'CLKB', 'v2')



class DFF_RST(SubCircuitFactory):
    __name__ = 'd_flip_flop_with_rst'
    __nodes__ = ('vdd', 'vss', 'D', 'CLK', 'RSTB', 'Q')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        self.X('0', 'inv', 'vdd', 'vss', 'CLK', 'CLKB')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('1', 'tinv', 'vdd', 'vss', 'D', 'CLKB', 'v1')

        self.M(1, 'v1', 'RSTB', 'vdd', 'vdd', model='pmos_m')

        self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        self.X('2', 'inv', 'vdd', 'vss', 'v1', 'v1_b')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('3', 'tinv', 'vdd', 'vss', 'v1_b', 'CLK', 'v1')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('4', 'tinv', 'vdd', 'vss', 'v1_b', 'CLK', 'v2')

        self.M(2, 'v2', 'RSTB', 'vdd', 'vdd', model='pmos_m')

        self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        self.X('5', 'inv', 'vdd', 'vss', 'v2', 'Q')

        self.subcircuit(logic_gates.TINV(kp=kp, vto=vto))
        self.X('6', 'tinv', 'vdd', 'vss', 'Q', 'CLKB', 'v2')




circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.PulseVoltageSource('1', 'D', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=150@u_ns, period=300@u_ns, delay_time=30@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)
circuit.PulseVoltageSource('2', 'CLK', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=100@u_ns, period=200@u_ns, delay_time=100@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)
circuit.PulseVoltageSource('3', 'rstb', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=800@u_ns, period=850@u_ns, delay_time=10@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)

circuit.subcircuit(DFF_RST(400e-6, 0.4))
circuit.X('1', 'd_flip_flop_with_rst', 'vdd', circuit.gnd, 'D', 'CLK', 'rstb', 'Q')
######################


##### Simulation #####
# simulator = circuit.simulator(temperature=25, nominal_temperature=25)
# analysis = simulator.transient(step_time=10@u_ns, end_time=1500@u_ns)

# fig = plt.figure()
# plt.ylim((-0.2, 1.2))
# # plt.plot(list(analysis.time), list(analysis["D"]))
# plt.plot(list(analysis.time), list(analysis["rstb"]))
# # plt.plot(list(analysis.time), list(analysis["CLKB"]))
# plt.plot(list(analysis.time), list(analysis["Q"]))
# plt.show()
# fig.savefig("./outputs/dff.png")
# plt.close(fig)
######################

# === analogcoder/sample_design/subcircuits/diffop.py ===
from PySpice.Unit import *
from PySpice.Spice.Netlist import SubCircuitFactory

class SingleStageOpamp(SubCircuitFactory):
	NAME = ('SingleStageOpamp')
	NODES = ('Vinp', 'Vinn', 'Vout')
	def __init__(self):
		super().__init__()
		# Define the MOSFET models
		self.model('nmos_model', 'nmos', level=1, kp=100e-6, vto=0.5)
		self.model('pmos_model', 'pmos', level=1, kp=50e-6, vto=-0.5)
		# Power Supplies
		self.V('dd', 'Vdd', self.gnd, 5.0)  # 5V power supply
		self.V('bias', 'Vbias', self.gnd, 1.5)  # Bias voltage for the tail current source M3
		# Input Voltage Sources for Differential Inputs
		# Differential Pair and Tail Current Source
		self.MOSFET('1', 'Voutp', 'Vinp', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('2', 'Vout', 'Vinn', 'Source3', 'Source3', model='nmos_model', w=50e-6, l=1e-6)
		self.MOSFET('3', 'Source3', 'Vbias', self.gnd, self.gnd, model='nmos_model', w=100e-6, l=1e-6)
		# Active Current Mirror Load
		self.MOSFET('4', 'Voutp', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)
		self.MOSFET('5', 'Vout', 'Voutp', 'Vdd', 'Vdd', model='pmos_model', w=100e-6, l=1e-6)

# === analogcoder/sample_design/subcircuits/divider.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

from subcircuits import dff

###### Netlist #######
circuit = Circuit('Frequency Divider')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class Divider_4(SubCircuitFactory):
    __name__ = 'divider_4'
    __nodes__ = ('vdd', 'vss', 'CLK', 'CLK_OUT')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.subcircuit(dff.DFF(kp, vto))
        self.X('1', 'd_flip_flop', 'vdd', 'vss', 'D1', 'CLK', 'Q1')

        self.M(1, 'D1', 'Q1', 'vdd', 'vdd', model='pmos_m')
        self.M(2, 'D1', 'Q1', 'vss', 'vss', model='nmos_m')

        self.subcircuit(dff.DFF(kp, vto))
        self.X('2', 'd_flip_flop', 'vdd', 'vss', 'D2', 'Q1', 'Q2')

        self.M(3, 'D2', 'Q2', 'vdd', 'vdd', model='pmos_m')
        self.M(4, 'D2', 'Q2', 'vss', 'vss', model='nmos_m')

        self.M(5, 'CLK_OUT_B', 'Q2', 'vdd', 'vdd', model='pmos_m')
        self.M(6, 'CLK_OUT_B', 'Q2', 'vss', 'vss', model='nmos_m')
        self.M(7, 'CLK_OUT', 'CLK_OUT_B', 'vdd', 'vdd', model='pmos_m')
        self.M(8, 'CLK_OUT', 'CLK_OUT_B', 'vss', 'vss', model='nmos_m')



circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.PulseVoltageSource('2', 'CLK', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=100@u_ns, period=200@u_ns, delay_time=100@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)

circuit.subcircuit(Divider_4(400e-6, 0.4))
circuit.X('1', 'divider_4', 'vdd', circuit.gnd, 'CLK', 'CLK_OUT')
######################


##### Simulation #####
# simulator = circuit.simulator(temperature=25, nominal_temperature=25)
# analysis = simulator.transient(step_time=10@u_ns, end_time=2500@u_ns)

# fig = plt.figure()
# plt.ylim((-0.2, 1.2))
# plt.plot(list(analysis.time), list(analysis["CLK"]))
# plt.plot(list(analysis.time), list(analysis["CLK_OUT"]))
# plt.show()
# fig.savefig("./outputs/divider.png")
# plt.close(fig)
######################

# === analogcoder/sample_design/subcircuits/logic_gates.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

###### Netlist #######
circuit = Circuit('NAND Gate')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class INV(SubCircuitFactory):
    __name__ = 'inv'
    __nodes__ = ('vdd', 'vss', 'I', 'O_delay')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.M(0, 'O', 'I', 'vdd', 'vdd', model='pmos_m')
        self.M(1, 'O', 'I', 'vss', 'vss', model='nmos_m')

        self.R(0, 'O', 'O_delay', 0.01@u_kΩ)
        self.C(0, 'O_delay', 'vss', 0.1@u_pF)


class TINV(SubCircuitFactory):
    __name__ = 'tinv'
    __nodes__ = ('vdd', 'vss', 'I', 'EN', 'O_delay')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.subcircuit(INV(kp, vto))
        self.X('0', 'inv', 'vdd', 'vss', 'EN', 'ENB')

        self.M(0, 'vp', 'I', 'vdd', 'vdd', model='pmos_m')
        self.M(1, 'vn', 'I', 'vss', 'vss', model='nmos_m')
        self.M(2, 'O', 'ENB', 'vp', 'vdd', model='pmos_m')
        self.M(3, 'O', 'EN', 'vn', 'vss', model='nmos_m')

        self.R(0, 'O', 'O_delay', 0.02@u_kΩ)
        self.C(0, 'O_delay', 'vss', 0.2@u_pF)


class NAND(SubCircuitFactory):
    __name__ = 'nand'
    __nodes__ = ('vdd', 'vss', 'A', 'B', 'O_delay')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.M(0, 'O', 'A', 'vdd', 'vdd', model='pmos_m')
        self.M(1, 'O', 'B', 'vdd', 'vdd', model='pmos_m')
        self.M(2, 'O', 'A', 'v1', 'vss', model='nmos_m')
        self.M(3, 'v1', 'B', 'vss', 'vss', model='nmos_m')

        self.R(0, 'O', 'O_delay', 0.04@u_kΩ)
        self.C(0, 'O_delay', 'vss', 0.4@u_pF)


circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.PulseVoltageSource('0', 'A', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=150@u_ns, period=300@u_ns, delay_time=30@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)
circuit.PulseVoltageSource('1', 'B', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=100@u_ns, period=200@u_ns, delay_time=100@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)

circuit.subcircuit(NAND(400e-6, 0.4))
circuit.X('0', 'nand', 'vdd', circuit.gnd, 'A', 'B', 'O')
######################


##### Simulation #####
# simulator = circuit.simulator(temperature=25, nominal_temperature=25)
# analysis = simulator.transient(step_time=10@u_ns, end_time=1500@u_ns)

# fig = plt.figure()
# plt.ylim((-0.2, 1.2))
# # plt.plot(list(analysis.time), list(analysis["A"]))
# # plt.plot(list(analysis.time), list(analysis["B"]))
# plt.plot(list(analysis.time), list(analysis["O"]))
# plt.show()
# fig.savefig("./outputs/nand.png")
# plt.close(fig)
######################

# === analogcoder/sample_design/subcircuits/loop_filter.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

###### Netlist #######
circuit = Circuit('Loop Filter')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class LF_t2o3(SubCircuitFactory):
    __name__ = 'loop_filter'
    __nodes__ = ('vss', 'i', 'o')
    def __init__(self, R1, R2, C1, C2):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.R(0, 'i', 'o', R1)
        self.R(1, 'o', 'c1_up', R2)
        self.C(1, 'c1_up', 'vss', C1)
        self.C(2, 'o', 'vss', C2)
######################

# === analogcoder/sample_design/subcircuits/opamp.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *


###### Netlist #######
circuit = Circuit('OpAmp')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class OpAmp(SubCircuitFactory):
    __name__ = 'op_amp'
    __nodes__ = ('vdd', 'vss', 'in_p', 'in_n', 'vout_delay')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.M(1, 'v1', 'v2', 'vdd', 'vdd', model='pmos_m')
        self.M(2, 'v2', 'v2', 'vdd', 'vdd', model='pmos_m')
        self.M(3, 'vout', 'v2', 'vdd', 'vdd', model='pmos_m')
        self.M(4, 'v3', 'in_n', 'v1', 'vdd', model='pmos_m')
        self.M(5, 'v4', 'in_p', 'v1', 'vdd', model='pmos_m')

        self.M(6, 'v3', 'v3', 'vss', 'vss', model='nmos_m')
        self.M(7, 'v4', 'v3', 'vss', 'vss', model='nmos_m')
        self.M(8, 'v2', 'vdd', 'vss', 'vss', model='nmos_m')
        self.M(9, 'vout', 'v4', 'vss', 'vss', model='nmos_m')

        self.R(1, 'vout', 'vout_delay', 1@u_kΩ)
        self.C(1, 'vout_delay', 'vss', 1@u_pF)


circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.V('INP', 'vinp', circuit.gnd, 0.54@u_V)
circuit.V('INN', 'vinn', circuit.gnd, 0.55@u_V)

circuit.subcircuit(OpAmp(400e-6, 0.4))
circuit.X('1', 'op_amp', 'vdd', circuit.gnd, 'vinp', 'vinn', 'vout')
######################


##### Simulation #####
# simulator = circuit.simulator(temperature=25, nominal_temperature=25)
# analysis = simulator.transient(step_time=1@u_us, end_time=500@u_us)

# fig = plt.figure()
# plt.ylim((-0.2, 1.2))
# # plt.plot(list(analysis.time), list(analysis["vinp"]))
# # plt.plot(list(analysis.time), list(analysis["vinn"]))
# plt.plot(list(analysis.time), list(analysis["vout"]))
# plt.show()
# fig.savefig("./outputs/opamp.png")
# plt.close(fig)
######################

# === analogcoder/sample_design/subcircuits/pfd.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *
from subcircuits import logic_gates
from subcircuits import dff

###### Netlist #######
circuit = Circuit('Phase Frequency Detector')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class PFD(SubCircuitFactory):
    __name__ = 'pfd'
    __nodes__ = ('vdd', 'vss', 'clk_ref', 'clk_fb', 'UP', 'DN')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.subcircuit(dff.DFF_RST(kp=kp, vto=vto))
        self.X('0', 'd_flip_flop_with_rst', 'vdd', 'vss', 'vdd', 'clk_ref', 'rstb', 'UP')

        self.subcircuit(dff.DFF_RST(kp=kp, vto=vto))
        self.X('1', 'd_flip_flop_with_rst', 'vdd', 'vss', 'vdd', 'clk_fb', 'rstb', 'DN')

        self.subcircuit(logic_gates.NAND(kp=kp, vto=vto))
        self.X('2', 'nand', 'vdd', 'vss', 'UP', 'DN', 'rstb')

        # self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        # self.X('5', 'inv', 'vdd', 'vss', 'rstbbb', 'rstbb')
        # self.subcircuit(logic_gates.INV(kp=kp, vto=vto))
        # self.X('6', 'inv', 'vdd', 'vss', 'rstbb', 'rstb')


circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.PulseVoltageSource('1', 'clk_ref', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=5@u_ns, period=10@u_ns, delay_time=30@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)
circuit.PulseVoltageSource('2', 'clk_fb', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                           pulse_width=15@u_ns, period=30@u_ns, delay_time=100@u_ns, rise_time=0.2@u_ns, fall_time=0.2@u_ns)
circuit.subcircuit(PFD(400e-6, 0.4))
circuit.X('0', 'pfd', 'vdd', circuit.gnd, 'clk_ref', 'clk_fb', 'UP', 'DN', 'rstb')
######################


##### Simulation #####
# simulator = circuit.simulator(temperature=25, nominal_temperature=25)
# simulator.initial_condition(rstb=0@u_V)
# analysis = simulator.transient(step_time=1@u_us, end_time=1500@u_ns)

# fig = plt.figure()
# plt.ylim((-0.2, 1.2))
# # plt.plot(list(analysis.time), list(analysis["rstb"]))
# plt.plot(list(analysis.time), list(analysis["UP"]))
# plt.plot(list(analysis.time), list(analysis["DN"]))
# plt.show()
# fig.savefig("./outputs/pfd.png")
# plt.close(fig)
######################

# === analogcoder/sample_design/subcircuits/ring_vco.py ===
import matplotlib.pyplot as plt
from PySpice.Spice.Netlist import Circuit, SubCircuit, SubCircuitFactory
from PySpice.Unit import *

from subcircuits import logic_gates


###### Netlist #######
circuit = Circuit('Ring Voltage Controlled Oscillator')
circuit.model('nmos_model', 'nmos', level=1, kp=400e-6, vto=0.4)
circuit.model('pmos_model', 'pmos', level=1, kp=400e-6, vto=-0.4)

class StarvedInvDelayLine(SubCircuitFactory):
    __name__ = 'delay_line'
    __nodes__ = ('vdd', 'vss', 'in_p', 'in_n', 'vctrl', 'out_p', 'out_n')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()
       
        self.model('nmos_m', 'nmos', level=1, kp=kp, vto=vto)
        self.model('pmos_m', 'pmos', level=1, kp=kp, vto=-vto)

        self.subcircuit(logic_gates.INV(kp, vto))
        self.X('0', 'inv', 'vp1', 'vss', 'in_p', 'out_n')
        self.M(0, 'vp1', 'vctrl', 'vdd', 'vdd', model='pmos_m')

        self.subcircuit(logic_gates.INV(kp, vto))
        self.X('1', 'inv', 'vp2', 'vss', 'in_n', 'out_p')
        self.M(1, 'vp2', 'vctrl', 'vdd', 'vdd', model='pmos_m')

        self.subcircuit(logic_gates.INV(kp, vto))
        self.X('2', 'inv', 'vdd', 'vss', 'out_p', 'out_n')
        self.subcircuit(logic_gates.INV(kp, vto))
        self.X('3', 'inv', 'vdd', 'vss', 'out_n', 'out_p')


class RingVCO(SubCircuitFactory):
    __name__ = 'ring_vco'
    __nodes__ = ('vdd', 'vss', 'vctrl', 'clk_p', 'clk_n',
                                        'clk_p_45', 'clk_n_45',
                                        'clk_p_90', 'clk_n_90',
                                        'clk_p_135', 'clk_n_135')
    def __init__(self, kp, vto):
        SubCircuit.__init__(self, self.__name__, *self.__nodes__)
        # super.__init__()

        self.subcircuit(StarvedInvDelayLine(kp, vto))
        self.X('1', 'delay_line', 'vdd', 'vss', 'clk_p', 'clk_n', 'vctrl', 'clk_p_45', 'clk_n_45')

        self.subcircuit(StarvedInvDelayLine(kp, vto))
        self.X('2', 'delay_line', 'vdd', 'vss', 'clk_p_45', 'clk_n_45', 'vctrl', 'clk_p_90', 'clk_n_90')

        self.subcircuit(StarvedInvDelayLine(kp, vto))
        self.X('3', 'delay_line', 'vdd', 'vss', 'clk_p_90', 'clk_n_90', 'vctrl', 'clk_p_135', 'clk_n_135')

        self.subcircuit(StarvedInvDelayLine(kp, vto))
        self.X('4', 'delay_line', 'vdd', 'vss', 'clk_p_135', 'clk_n_135', 'vctrl', 'clk_n', 'clk_p')



circuit.V('VDD', 'vdd', circuit.gnd, 1@u_V)
circuit.V('ctrl', 'vctrl', circuit.gnd, 0@u_V)

circuit.subcircuit(RingVCO(400e-6, 0.4))
circuit.X('1', 'ring_vco', 'vdd', circuit.gnd, 'vctrl', 'clk_p', 'clk_n',
                                                        'clk_p_45', 'clk_n_45',
                                                        'clk_p_90', 'clk_n_90',
                                                        'clk_p_135', 'clk_n_135')
######################


##### Simulation #####
# simulator = circuit.simulator(temperature=25, nominal_temperature=25)
# simulator.initial_condition(clk_p=0.5@u_V, clk_n=0.5@u_V,
#                             clk_p_45=0.5@u_V, clk_n_45=0.5@u_V,
#                             clk_p_90=0.5@u_V, clk_n_90=0.5@u_V,
#                             clk_p_135=0.5@u_V, clk_n_135=0.5@u_V)
# analysis = simulator.transient(step_time=10@u_ns, end_time=3@u_us)


# # ### Find frequency
# import numpy as np
# time = np.array(analysis.time)  # Time points array
# vout = np.array(analysis['clk_p'])  # Output voltage array
# # Find zero-crossings
# zero_crossings = np.where(np.diff(np.sign(vout-0.5))[5:])[0]
# # Calculate periods by subtracting consecutive zero-crossing times
# periods = np.diff(time[zero_crossings])
# # Average period
# average_period = np.mean(periods)
# # Frequency is the inverse of the period
# frequency = 1 / average_period
# print()
# print(f"Frequency: {frequency*1e-6} MHz")
# print()

# fig = plt.figure()
# plt.ylim((-0.2, 1.2))
# plt.plot(list(analysis.time), list(analysis["clk_p"]))
# plt.show()
# fig.savefig("./outputs/ring_vco.png")
# plt.close(fig)
######################

# === analogcoder/sample_design/test_all_sample_design.py ===
import os
import subprocess
import sys

def work():
    failed_tasks = []
    for task_id in range(1, 25):
        file_path = os.path.join(f"p{task_id}.py")
        result = subprocess.run(['python', file_path], capture_output=True)
        if result.returncode == 0:
            print(f"Task {task_id} passed.")
        else:
            print(f"Task {task_id} failed.")
            failed_tasks.append(task_id)
    
    if len(failed_tasks) > 0:
        print(f"Failed tasks: {failed_tasks}")
        print(f"Please check your environment and try again.")
        sys.exit(1)
    else:
        print("All tasks passed.")
        sys.exit(0)

def main():
    work()


if __name__ == "__main__":
    main()

# === analogcoder/problem_check/Adder.py ===
bias_voltage = [BIAS_VOLTAGE]
v1_amp = bias_voltage
v2_amp = bias_voltage + 0.125

vin1_name = ""
for element in circuit.elements:
    if "vin1" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin1_name = element.name

if not vin1_name == "":
    circuit.element(vin1_name).detach()
    circuit.V('in1', 'Vin1', circuit.gnd, v1_amp)
    vin1_name = "Vin1"
else:
    circuit.V('in1', 'Vin1', circuit.gnd, v1_amp)
    vin1_name = "Vin1"


vin2_name = ""
for element in circuit.elements:
    if "vin2" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin2_name = element.name
    
if not vin2_name == "":
    circuit.element(vin2_name).detach()
    circuit.V('in2', 'Vin2', circuit.gnd, v2_amp)
    vin2_name = "Vin2"
else:
    circuit.V('in2', 'Vin2', circuit.gnd, v2_amp)
    vin2_name = "Vin2"


for element in circuit.elements:
    if element.name.lower().startswith(vin1_name):
        circuit.element(element.name).dc_value = f"dc {v1_amp}"
    elif element.name.lower().startswith(vin2_name):
        circuit.element(element.name).dc_value = f"dc {v2_amp}"

# print(str(circuit))

simulator = circuit.simulator()


params = {vin1_name: slice(bias_voltage, bias_voltage + 0.5, 0.01)}
# Run a DC analysis
try:
    analysis = simulator.dc(**params)
except:
    print("DC analysis failed.")
    sys.exit(2)

import numpy as np
out_voltage = np.array(analysis.Vout)
in_voltage = np.array(analysis.Vin1)
vin2_voltage = np.array(analysis.Vin2)


import sys


tolerance = 0.2  # 20% Tolerance
for i, out_v in enumerate(out_voltage):
    in_v_1 = in_voltage[i] - bias_voltage
    in_v_2 = v2_amp - bias_voltage
    expected_vout = bias_voltage - (in_v_1 + in_v_2)
    actual_vout = out_v
    if not np.isclose(actual_vout, expected_vout, rtol=tolerance):
        print(f"The circuit does not function correctly as an adder.\n"
            f"Expected Vout: {expected_vout:.4f} V, Vin1 = {in_v_1+bias_voltage:.4f} V, Vin2 = {in_v_2+bias_voltage:.4f} V | Actual Vout: {actual_vout:.4f} V\n")
        sys.exit(2)


print("The op-amp adder functions correctly.\n")
sys.exit(0)

# === analogcoder/problem_check/Amplifier.py ===
simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'
output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-6))

print(f"Voltage Gain (Av) at 100 Hz: {gain}")

required_gain = 1e-5
import sys
if gain > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)
else:
    print("The circuit does not function correctly.\n"
          "the gain is less than 1e-5.\n"
          "Please fix the wrong operating point.\n")
    sys.exit(2)

# === analogcoder/problem_check/CurrentMirror.py ===
load_resistances = [100, 300, 500, 750, 1000]
currents = []

import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Resistor):
        resistor_name = element.name
        node1, node2 = element.nodes
        break


resistor = circuit[resistor_name]
for r_load in load_resistances:
    resistor.resistance = r_load
    analysis = simulator.operating_point()
    if str(node2) == "0":
        current = float(analysis[str(node1)][0]) / r_load
    elif str(node1) == "0":
        current = - float(analysis[str(node2)][0]) / r_load
    else:
        current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load
    currents.append(current)

for r_load, current in zip(load_resistances, currents):
    print(f"Load: {r_load}, Current: {current}")

tolerance = 1e-6

current_variations = []
for i in range(4):
    current_variations.append(abs(currents[i+1] - currents[i]))

import sys
if min(current_variations) < tolerance and min(currents) > 1e-5:
    pass
    # print("The circuit functions correctly as a constant current source within the given tolerance.")
    # sys.exit(0)
else:
    print("The circuit does not function correctly as a current source.")
    sys.exit(2)

iin_name = None
for element in circuit.elements:
    if "ref" in element.name.lower(): # and element.name.lower().startswith("v"):
        iin_name = element.name

# print("iin_name", iin_name)
if iin_name is None:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


circuit.element(iin_name).dc_value = "0.00155"

# print(str(circuit))
simulator = circuit.simulator()
resistor.resistance = 500
analysis = simulator.operating_point()
if str(node2) == "0":
    current = float(analysis[str(node1)][0]) / r_load
elif str(node1) == "0":
    current = - float(analysis[str(node2)][0]) / r_load
else:
    current = - (float(analysis[str(node1)][0]) - float(analysis[str(node2)][0])) / r_load

# print("current", current)
# print("currents", currents)
# print("abs(current - currents[2])", abs(current - currents[2]))
if abs(current - currents[2]) < 1e-6:
    print("The circuit does not as a current source because it cannot replicate the Iref current.")
    sys.exit(2)
else:
    print("The circuit functions correctly as a current source within the given tolerance.")
    sys.exit(0)


# === analogcoder/problem_check/Differentiator.py ===
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

bias_voltage = [BIAS_VOLTAGE]

# Detach the previous Vin if it exists and attach a new triangular wave source
if vin_name != "":
    circuit.element(vin_name).detach()
    circuit.V('tri', 'Vin', circuit.gnd, f"dc {bias_voltage} PULSE({bias_voltage-0.5} {bias_voltage+0.5} 0 50m 50m 1n 100m)")
else:
    circuit.V('in', 'Vin', circuit.gnd, f"dc {bias_voltage} PULSE({bias_voltage-0.5} {bias_voltage+0.5} 0 50m 50m 1n 100m)")

# Adjust R1 resistance if needed
for element in circuit.elements:
    if element.name.lower().startswith("rf") or element.name.lower().startswith("rrf") or element.name.lower().startswith("r1"):
        r_name = element.name
circuit.element(r_name).resistance = "10k"

# Adjust C1 capacitance if needed
for element in circuit.elements:
    if element.name.lower().startswith("c1") or element.name.lower().startswith("cc1"):
        c_name = element.name
circuit.element(c_name).capacitance = "3u"

# Initialize the simulator
simulator = circuit.simulator()


import sys
# Perform transient analysis
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)


import numpy as np
# Extract data from the analysis
time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])

import matplotlib.pyplot as plt
# Plot the response
plt.figure()
plt.plot(time, vout)
plt.title('Response of Op-amp Differentiator')
plt.xlabel('Time [s]')
plt.ylabel('Output Voltage [V]')
plt.grid(True)
plt.savefig("[FIGURE_PATH]")


from scipy.signal import find_peaks
# Check for square wave characteristics in the output
# Calculate the mean voltage level of the peaks and troughs

# print("vout", vout)
# print("max(vout)", max(vout))
# print("min(vout)", min(vout))
min_height = (max(vout) + min(vout)) / 2
# print("min_height", min_height)
num_of_peaks = 2
min_distance = len(vout) / (2 * num_of_peaks) / 1.5 
# print("min_distance", min_distance)

peaks, _ = find_peaks(vout, height=min_height, distance=min_distance)


troughs, _ = find_peaks(-vout, height=-min_height, distance=min_distance)


average_peak_voltage = np.mean(vout[peaks])
average_trough_voltage = np.mean(vout[troughs])



if len(peaks) == 0 or len(troughs) == 0:
    print("No peaks or troughs found in output voltage. Please check the netlist.")
    sys.exit(2)

peak_voltages = vout[peaks]
trough_voltages = vout[troughs]
mean_peak = np.mean(peak_voltages)
mean_trough = np.mean(trough_voltages)


def is_square_wave(waveform, mean_peak, mean_trough, rtol=0.1):
    high_level = np.mean([x for x in waveform if x > (mean_peak + mean_trough) / 2])
    low_level = np.mean([x for x in waveform if x <= (mean_peak + mean_trough) / 2])

    is_high_close = np.isclose(high_level, mean_peak, rtol=rtol)
    is_low_close = np.isclose(low_level, mean_trough, rtol=rtol)

    return is_high_close and is_low_close

# print("mean_peak - bias_voltage", mean_peak - bias_voltage)
# print("mean_trough - bias_voltage", mean_trough - bias_voltage)
# Check if the output is approximately a square wave by comparing the mean of the peaks and troughs
if np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2) and \
     np.isclose(mean_peak - bias_voltage, 0.6, rtol=0.2) and \
     is_square_wave(vout, mean_peak, mean_trough):  # 20% tolerance
    # print("The op-amp differentiator functions correctly.\n")
    # sys.exit(0)
    pass
elif not np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2):
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"When the input is a triangle wave and the output is not a square wave.\n")
    sys.exit(2)
elif not is_square_wave(vout, mean_peak, mean_trough):
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"When the input is a triangle wave and the output is not a square wave.\n")
    sys.exit(2)
else:
    print(f"The circuit does not function correctly as a differentiator.\n"
          f"Output voltage peak value is wrong. Mean peak voltage: {mean_peak} V | Mean trough voltage: {mean_trough} V\n")
    sys.exit(2)


for element in circuit.elements:
    if element.name.lower().startswith("x"):
        x_name = element.name

circuit.element(x_name).detach()
simulator = circuit.simulator()
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("The op-amp differentiator functions correctly.\n")
    sys.exit(0)

time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])




min_height = (max(vout) + min(vout)) / 2
num_of_peaks = 2
min_distance = len(vout) / (2 * num_of_peaks) / 1.5 

peaks, _ = find_peaks(vout, height=min_height, distance=min_distance)


troughs, _ = find_peaks(-vout, height=-min_height, distance=min_distance)


average_peak_voltage = np.mean(vout[peaks])
average_trough_voltage = np.mean(vout[troughs])



if len(peaks) == 0 or len(troughs) == 0:
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(2)

peak_voltages = vout[peaks]
trough_voltages = vout[troughs]
mean_peak = np.mean(peak_voltages)
mean_trough = np.mean(trough_voltages)


if np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2) and np.isclose(mean_peak - bias_voltage, 0.6, rtol=0.2):  # 20% tolerance
    print("The differentiator maybe a passive differentiator.\n")
elif not np.isclose(mean_peak - bias_voltage, -mean_trough+ bias_voltage, rtol=0.2):
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(2)
else:
    print(f"The op-amp differentiator functions correctly.\n")
    sys.exit(2)


# === analogcoder/problem_check/Integrator.py ===
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name


bias_voltage = [BIAS_VOLTAGE]

if vin_name != "":
    circuit.element(vin_name).detach()
    circuit.V('pulse', 'Vin', circuit.gnd, f"dc {bias_voltage} PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")
else:
    circuit.V('in', 'Vin', circuit.gnd, f"dc {bias_voltage} PULSE({bias_voltage-0.5} {bias_voltage+0.5} 1u 1u 1u 10m 20m)")

for element in circuit.elements:
    if element.name.lower().startswith("r1") or element.name.lower().startswith("rr1"):
        r_name = element.name
circuit.element(r_name).resistance = "10k"

for element in circuit.elements:
    # print("element.name", element.name)
    if element.name.lower().startswith("cf") or element.name.lower().startswith("ccf") or element.name.lower().startswith("c1"):
        c_name = element.name
circuit.element(c_name).capacitance = "3u"

simulator = circuit.simulator()

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)


import numpy as np
import matplotlib.pyplot as plt
# Plot the step response
time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])


plt.figure()
plt.plot(time, vout)
plt.title('Step Response of Op-amp Integrator')
plt.xlabel('Time [s]')
plt.ylabel('Output Voltage [V]')
plt.grid(True)
plt.savefig("[FIGURE_PATH]")


expected_slope = 0.5 / 0.03


from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)

troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("No peaks or troughs found in output voltage. Please check the netlist.")
    sys.exit(2)


start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])



import sys
if not np.isclose(slope, expected_slope, rtol=0.3):  # 30% tolerance
    print(f"The circuit does not function correctly as an integrator.\n"
          f"Expected slope: {expected_slope} V/s | Actual slope: {slope} V/s\n")
    sys.exit(2)

if not r_value** 2 >= 0.9:
    print("The op-amp integrator does not have a linear response.\n")
    sys.exit(2)


for element in circuit.elements:
    if element.name.lower().startswith("x"):
        x_name = element.name

circuit.element(x_name).detach()
simulator = circuit.simulator()
try:
    analysis = simulator.transient(step_time=1@u_us, end_time=200@u_ms)
except:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)

time = np.array(analysis.time)
vin = np.array(analysis['vin'])
vout = np.array(analysis['vout'])




expected_slope = 0.5 / 0.03


from scipy.signal import find_peaks

peaks, _ = find_peaks(vout)

troughs, _ = find_peaks(-vout)

if len(peaks) < 2 or len(troughs) < 2:
    print("The op-amp integrator functions correctly.\n")
    sys.exit(0)


start = peaks[-2]
end = troughs[troughs > start][0] 

slope, intercept = np.polyfit(time[start:end], vout[start:end], 1)
slope = np.abs(slope)
from scipy.stats import linregress
_, _, r_value, p_value, std_err = linregress(time[start:end], vout[start:end])


if np.isclose(slope, expected_slope, rtol=0.5):  # 50% tolerance
    print("The integrator maybe a passive integrator.\n")
    sys.exit(2)

print("The op-amp integrator functions correctly.\n")
sys.exit(0)



# === analogcoder/problem_check/Inverter.py ===
analysis = simulator.operating_point()
for node in analysis.nodes.values(): 
    print(f"{str(node)}\t{float(analysis[str(node)][0]):.6f}")
vin_name = ""
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

circuit.element(vin_name).dc_value = "5"

simulator2 = circuit.simulator()
analysis2 = simulator2.operating_point()

vout2 = float(analysis2["vout"][0])

circuit.element(vin_name).dc_value = "0"

simulator3 = circuit.simulator()
analysis3 = simulator3.operating_point()

vout3 = float(analysis3["vout"][0])

import sys
if vout2 <= 2.5 and vout3 >= 2.5 and vout3 - vout2 >= 1.0:
    print("The circuit functions correctly.\n")
    sys.exit(0)

print("The circuit does not function correctly.\n"
    "It can not invert the input voltage.\n"
    "Please fix the wrong operating point.\n")

sys.exit(2)





# === analogcoder/problem_check/Opamp.py ===
simulator_id = circuit.simulator()
mosfet_names = []
import PySpice.Spice.BasicElement
for element in circuit.elements:
    if isinstance(element, PySpice.Spice.BasicElement.Mosfet):
        mosfet_names.append(element.name)

mosfet_name_ids = []
for mosfet_name in mosfet_names:
    mosfet_name_ids.append(f"@{mosfet_name}[id]")

simulator_id.save_internal_parameters(*mosfet_name_ids)
analysis_id = simulator_id.operating_point()

id_correct = 1
for mosfet_name in mosfet_names:
    mosfet_id = float(analysis_id[f"@{mosfet_name}[id]"][0])
    if mosfet_id < 1e-5:
        id_correct = 0
        print("The circuit does not function correctly. "
          "the current I_D for {} is 0. ".format(mosfet_name)
          .format(mosfet_name))

if id_correct == 0:
    print("Please fix the wrong operating point.\n")
    sys.exit(2)


frequency = 100@u_Hz
analysis = simulator.ac(start_frequency=frequency, stop_frequency=frequency*10, 
    number_of_points=2, variation='dec')

import numpy as np

node = 'vout'
output_voltage = analysis[node].as_ndarray()[0]
gain = np.abs(output_voltage / (1e-6))

print(f"Common-Mode Gain (Av) at 100 Hz: {gain}")

vinn_name = ""
for element in circuit.elements:
    # print("element name", element.name)
    # for pin in element.pins:
    #     print("pin name", pin.node)
    if "vinn" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vinn_name = element.name


circuit.element(vinn_name).dc_value += " 180"

simulator2 = circuit.simulator()
analysis2 = simulator2.ac(start_frequency=frequency, stop_frequency=frequency, 
                        number_of_points=1, variation='dec')

output_voltage2 = np.abs(analysis2[node].as_ndarray()[0])
gain2 = output_voltage2 / (1e-6)

print(f"Differential-Mode Gain (Av) at 100 Hz: {gain2}")

required_gain = 1e-5
import sys

if gain < gain2 - 1e-5 and gain2 > required_gain:
    print("The circuit functions correctly at 100 Hz.\n")
    sys.exit(0)

if gain >= gain2 - 1e-5:
    print("Common-Mode gain is larger than Differential-Mode gain.\n")

if gain2 < required_gain:
    print("Differential-Mode gain is smaller than 1e-5.\n")

print("The circuit does not function correctly.\n"
    "Please fix the wrong operating point.\n")
sys.exit(2)

# === analogcoder/problem_check/Oscillator.py ===
del_vname = []
for element in circuit.elements:
    v_name = element.name
    if element.name.lower().startswith("v"):
        del_vname.append(v_name)


pin_name = "Vinp"
pin_name_n = "Vinn"
for element in circuit.elements:
    if element.name.lower().startswith("x"):
        opamp_element = element
        pin_name = str(opamp_element.pins[0].node)
        pin_name_n = str(opamp_element.pins[1].node)
        break


# print("pin_name", pin_name)
# print("pin_name_n", pin_name_n)

params = {pin_name: 2.51, pin_name_n: 2.5}

simulator = circuit.simulator()
simulator.initial_condition(**params)

try:
    analysis = simulator.transient(step_time=1@u_us, end_time=10@u_ms)
except:
    print("analysis failed.")
    sys.exit(2)

import numpy as np
# Get the output node voltage
vout = np.array(analysis['Vout'])
vinp = np.array(analysis[pin_name])
vinn = np.array(analysis[pin_name_n])
time = np.array(analysis.time)

from scipy.signal import find_peaks, firwin, lfilter

numtaps = 51
cutoff_hz = 10.0
sample_rate = 1000
fir_coeff = firwin(numtaps, cutoff_hz, fs=sample_rate, window="hamming")

filtered_vout = lfilter(fir_coeff, 1.0, vout)
peaks, _ = find_peaks(filtered_vout)


error = 0
import sys

# Plot the results
import matplotlib.pyplot as plt

plt.figure()
plt.plot(time, vout)
# plt.plot(time, filtered_vout)
plt.plot(time, vinp)
plt.plot(time, vinn)
plt.title('Wien Bridge Oscillator Output')
plt.xlabel('Time [s]')
plt.ylabel('Voltage [V]')
plt.legend(['Vout', 'Vinp', 'Vinn'])
plt.grid()
plt.savefig('[FIGURE_PATH].png')

# sys.exit(0)

troughs, _ = find_peaks(-filtered_vout)
if len(peaks) > 0 and len(troughs) > 0:
    amplitudes = []

    for peak in peaks:
        trough_index = np.argmin(np.abs(troughs - peak))
        trough = troughs[trough_index]
        amplitude = np.abs(vout[peak] - vout[trough])
        amplitudes.append(amplitude)

    amplitudes = np.array(amplitudes)

    min_amplitude_threshold = 1e-6

else:
    print("Not enough peaks were detected to determine amplitude.")
    sys.exit(2)

# print("Amplitudes: ", amplitudes)
amplitudes = np.sort(amplitudes)
num_elements_to_keep = len(amplitudes) // 2
amplitudes = amplitudes[-num_elements_to_keep:]


if not all(amplitudes > min_amplitude_threshold):
    print("The peak amplitudes are too small. (<1uV)")
    error = 1


if len(peaks) > 3:
    peak_times = time[peaks]
    periods = np.diff(peak_times)
    average_period = np.mean(periods)
    some_small_threshold = 0.2 * average_period
    period_variation = np.std(periods)
    if period_variation < some_small_threshold:
        if error == 0:
            print("The oscillator works correct and produces periodic oscillations.")
            print("The average period is: {} s".format(np.mean(periods)))
    else:
        print("Periodicity is inconsistent, oscillation may not be an ideal periodicity.")
        error = 1
else:
    print("Not enough peaks were detected to determine periodicity.")
    error = 1



if error == 1:
    sys.exit(2)
else:
    sys.exit(0)

# === analogcoder/problem_check/PLL.py ===
in_frequency = 10e6
period = 1/in_frequency
circuit.PulseVoltageSource('1', 'clk_ref', circuit.gnd, initial_value=0@u_V, pulsed_value=1@u_V,
                        pulse_width=(0.48*period)@u_s, period=(period)@u_s, delay_time=30@u_ns, rise_time=(0.02*period)@u_s, fall_time=(0.02*period)@u_s)
simulator = circuit.simulator()

simulator.initial_condition(vctrl=0.5@u_V,
                            clk_p=0.5@u_V, clk_n=0.5@u_V,
                            clk_p_45=0.5@u_V, clk_n_45=0.5@u_V,
                            clk_p_90=0.5@u_V, clk_n_90=0.5@u_V,
                            clk_p_135=0.5@u_V, clk_n_135=0.5@u_V)
analysis = simulator.transient(step_time=10@u_ns, end_time=10@u_us)


### Find frequency
import numpy as np
time = np.array(analysis.time)  # Time points array
vout = np.array(analysis['clk_p'])  # Output voltage array
# Find zero-crossings
zero_crossings = np.where(np.diff(np.sign(vout-0.5))[:])[0][-5:]
# Calculate periods by subtracting consecutive zero-crossing times
periods = np.diff(time[zero_crossings])
# Average period
average_period = 2 * np.mean(periods)
# Frequency is the inverse of the period
out_frequency = 1 / average_period
print()
print(f"REF Frequency : {in_frequency*1e-6} MHz")
print(f"OUT Frequency : {out_frequency*1e-6} MHz")
print()



if np.close(in_frequency, out_frequency, rtol=0.05):
    print("The Phase-Locked Loop functions correctly.\n")
else:
    print("The Phase-Locked Loop does not function correctly.\n")
    print("When the clk_ref frequency is 10 MHz, the output frequency should be 10 MHz.\n")
    sys.exit(0)

fig = plt.figure(figsize=(14, 9))

# plt.ylim((-0.2, 1.2))

plt.subplot(321)
plt.xlim((0, 1e-6))
plt.plot(list(analysis.time), list(analysis["clk_ref"]))
plt.plot(list(analysis.time), list(analysis["clk_p"]))
plt.title('init clk')

plt.subplot(323)
plt.xlim((0, 1e-6))
plt.plot(list(analysis.time), list(analysis["UP"]))
plt.plot(list(analysis.time), list(analysis["DN"]))
plt.title('init UP/DN')

plt.subplot(325)
plt.plot(list(analysis.time), list(analysis["vctrl"]))
plt.title('overall vctrl')

plt.subplot(322)
plt.xlim((9e-6, 10e-6))
plt.plot(list(analysis.time), list(analysis["clk_ref"]))
plt.plot(list(analysis.time), list(analysis["clk_p"]))
plt.title('converged clk')

plt.subplot(324)
plt.xlim((9e-6, 10e-6))
plt.plot(list(analysis.time), list(analysis["UP"]))
plt.plot(list(analysis.time), list(analysis["DN"]))
plt.title('converged UP/DN')

plt.subplot(326)
plt.xlim((9e-6, 10e-6))
plt.plot(list(analysis.time), list(analysis["vctrl"]))
plt.title('converged vctrl')

plt.show()

fig.savefig("./outputs/pll.png")
plt.close(fig)
######################

sys.exit(0)

# === analogcoder/problem_check/Schmitt.py ===
vin_name = "Vin"
for element in circuit.elements:
    if "vin" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin_name = element.name

params = {vin_name: slice(0, 5, 0.1)}

try:
    analysis = simulator.dc(**params)
except:
    print("DC analysis failed.")
    sys.exit(2)

params2 = {vin_name: slice(5, 0, -0.1)}

simulator2 = circuit.simulator()

try:
    analysis2 = simulator2.dc(**params2)
except:
    print("DC analysis failed.")
    sys.exit(2)

import numpy as np
import matplotlib.pyplot as plt


vin = np.array(analysis[vin_name])
vout = np.array(analysis['Vout'])
vin2 = np.flip(np.array(analysis2[vin_name]))
vout2 = np.flip(np.array(analysis2['Vout']))

threshold = 2.5


try:
    trigger_index = np.where(vout > threshold)[0][0]
except:
    print("The circuit does not function correctly. The output voltage does not cross the Vdd/2.")
    sys.exit(2)

trigger_vin = vin[trigger_index]

try:
    trigger_index2 = np.where(vout2 > threshold)[0][0]
except:
    print("The circuit does not function correctly. The output voltage does not cross the Vdd/2.")
    sys.exit(2)

trigger_vin2 = vin2[trigger_index2]


# Plot the input and output waveforms
plt.figure()
plt.plot(vin, vin, label='Vin')
plt.plot(vin, vout, label='Vout')
plt.plot(vin2, vout2, label='Vout2')
plt.title('Schmitt Trigger Input and Output Waveforms')
plt.xlabel('vin [V]')
plt.ylabel('Voltage [V]')
plt.legend()
plt.grid(True)
plt.savefig("[FIGURE_PATH].png")

if abs(trigger_vin - trigger_vin2) <= 0.05:
    print("The circuit does not function correctly. Trigger points are too close.")
    print(f"Trigger points: {trigger_vin:.5f}V and {trigger_vin2:.5f}V are not sufficiently different. Please use the positive feedback which the Rf should connect to the non-inverting input of the op-amp.")
    sys.exit(2)
elif vout[-1] - vout[0] < 2.5 or vout2[-1] - vout2[0] < 2.5:
    print("The circuit does not function correctly. The output voltage does not vary more than Vdd/2.")
    sys.exit(2)
elif not np.all(np.diff(vout)>=0) or not np.all(np.diff(vout2)>=0):
    print("The circuit does not function correctly. The output voltage variation does not monotonically increase with increasing input voltage.")
    sys.exit(2)

print("The circuit functions correctly with different trigger points.")
sys.exit(0)

# === analogcoder/problem_check/Subtractor.py ===
import numpy as np
import sys

# Define the bias voltage and input voltage differences
BIAS_VOLTAGE = [BIAS_VOLTAGE]
v1_amp = BIAS_VOLTAGE*2
v2_amp = BIAS_VOLTAGE*2


vin1_name = ""
for element in circuit.elements:
    if "vin1" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin1_name = element.name

vin1_name = ""
for element in circuit.elements:
    if "vin1" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin1_name = element.name

if not vin1_name == "":
    circuit.element(vin1_name).detach()
    circuit.V('in1', 'Vin1', circuit.gnd, v1_amp)
    vin1_name = "Vin1"
else:
    circuit.V('in1', 'Vin1', circuit.gnd, v1_amp)
    vin1_name = "Vin1"

vin2_name = ""
for element in circuit.elements:
    if "vin2" in [str(pin.node).lower() for pin in element.pins] and element.name.lower().startswith("v"):
        vin2_name = element.name
    
if not vin2_name == "":
    circuit.element(vin2_name).detach()
    circuit.V('in2', 'Vin2', circuit.gnd, v2_amp)
    vin2_name = "Vin2"
else:
    circuit.V('in2', 'Vin2', circuit.gnd, v2_amp)
    vin2_name = "Vin2"



# print("vin1_name", vin1_name)
# print("vin2_name", vin2_name)

for element in circuit.elements:
    if element.name.lower().startswith(vin1_name.lower()):
        circuit.element(element.name).dc_value = f"dc {v1_amp}"
    elif element.name.lower().startswith(vin2_name.lower()):
        circuit.element(element.name).dc_value = f"dc {v2_amp}"

# print(str(circuit))

simulator = circuit.simulator()


params = {vin1_name: slice(BIAS_VOLTAGE*2 -2.25, BIAS_VOLTAGE*2 - 1.75, 0.05)}
# Run a DC analysis
try:
    analysis = simulator.dc(**params)
except:
    print("DC analysis failed.")
    sys.exit(2)

# Collect the simulation results
out_voltage = np.array(analysis.Vout)
vin1_voltage = np.array(analysis.Vin1)
vin2_voltage = np.array(analysis.Vin2)

# vinn_voltage = np.array(analysis.inv_input)
# print("vinn_voltage", vinn_voltage)
# print("vin1_voltage", vin1_voltage)
# print("vin2_voltage", vin2_voltage)
# vinp_voltage = np.array(analysis.non_inv_input)
# print("vinp_voltage", vinp_voltage)
# print("out_voltage", out_voltage)

# Define a tolerance for verifying the subtractor's functionality
tolerance = 0.2  # 20% Tolerance

# Iterate over the simulation results to check if the output is Vin2 - Vin1
for i, out_v in enumerate(out_voltage):
    in_v_1 = vin1_voltage[i]
    in_v_2 = v2_amp
    expected_vout = in_v_2 - in_v_1
    actual_vout = out_v
    if not np.isclose(actual_vout, expected_vout, rtol=tolerance):
        print(f"The circuit does not function correctly as a subtractor.\n"
              f"Expected Vout: {expected_vout:.2f} V, Vin1 = {in_v_1:.2f} V, Vin2 = {in_v_2:.2f} V | Actual Vout: {actual_vout:.2f} V\n")
        sys.exit(1)

print("The op-amp subtractor functions correctly.\n")
sys.exit(0)

# === analogcoder/problem_check/VCO.py ===
simulator.initial_condition(vout_1=0.3@u_V, vout=0.6@u_V)

try:
    analysis = simulator.transient(step_time=1@u_ns, end_time=100@u_us)
except:
    print("Transient analysis failed.")
    sys.exit(2)


import numpy as np

fig = plt.figure()
plt.ylim((-2, 2))
plt.plot(list(analysis.time), list(analysis["vout"]))
fig.savefig("[FIGURE_PATH].png")


y = np.array(analysis["vout"])
# print("y", y)
t = np.array(analysis.time)
threshold = (y.max() + y.min())/2
# print("threshold", threshold)
# print(threshold)
crossings = []
for i in range(1, len(y)):
    if y[i-1] < threshold and y[i] >= threshold:
        slope = (y[i] - y[i-1]) / (t[i] - t[i-1])
        exact_time = t[i-1] + (threshold - y[i-1]) / slope
        crossings.append(exact_time)

# print("crossings", crossings)
# print("len(crossings)", len(crossings))
periods = np.diff(crossings)
average_period = np.median(periods)
# print("average_period", average_period)

circuit.element("Vin").detach()
circuit.V('in', 'vin', circuit.gnd, 0.65@u_V)

simulator = circuit.simulator()
simulator.initial_condition(vout_1=0.3@u_V, vout=0.7@u_V)
# print("simulator2 start")

try:
    analysis = simulator.transient(step_time=1@u_ns, end_time=100@u_us)
except:
    print("Transient analysis failed.")
    sys.exit(2)
# print("simulator2 end")

plt.plot(list(analysis.time), list(analysis["vout"]))

fig.savefig("./opamp_vco.png")

y = np.array(analysis["vout"])
# print("y", y)
t = np.array(analysis.time)
threshold = (y.max() + y.min())/2
# print("threshold", threshold)
# print(threshold)
crossings = []
for i in range(1, len(y)):
    if y[i-1] < threshold and y[i] >= threshold:
        slope = (y[i] - y[i-1]) / (t[i] - t[i-1])
        exact_time = t[i-1] + (threshold - y[i-1]) / slope
        crossings.append(exact_time)

# print("crossings", crossings)
# print("len(crossings)", len(crossings))
periods = np.diff(crossings)
average_period2 = np.median(periods)
# print("average_period2", average_period2)


circuit.element("Vin").detach()
circuit.V('in', 'vin', circuit.gnd, 0.8@u_V)

simulator = circuit.simulator()
simulator.initial_condition(vout_1=0.3@u_V, vout=0.7@u_V)
# print("simulator2 start")
analysis = simulator.transient(step_time=1@u_ns, end_time=100@u_us)
# print("simulator2 end")

plt.plot(list(analysis.time), list(analysis["vout"]))

# fig.savefig("./opamp_vco.png")

y = np.array(analysis["vout"])
# print("y", y)
t = np.array(analysis.time)
threshold = (y.max() + y.min())/2
# print("threshold", threshold)
# print(threshold)
crossings = []
for i in range(1, len(y)):
    if y[i-1] < threshold and y[i] >= threshold:
        slope = (y[i] - y[i-1]) / (t[i] - t[i-1])
        exact_time = t[i-1] + (threshold - y[i-1]) / slope
        crossings.append(exact_time)

# print("crossings", crossings)
# print("len(crossings)", len(crossings))
periods = np.diff(crossings)
average_period3 = np.median(periods)
# print("average_period3", average_period3)


if average_period - 1e-5 > average_period2 and average_period - 1e-5 > average_period3:
    print("The voltage-controlled oscillator functions correctly.")
    sys.exit(0)
elif average_period + 1e-5 < average_period2 and average_period + 1e-5 < average_period3:
    print("The voltage-controlled oscillator functions correctly.")
    sys.exit(0)
else:
    print("The voltage-controlled oscillator does not function correctly.")
    print("The average period is not changing as expected when adjusting the vin.")
    sys.exit(2)