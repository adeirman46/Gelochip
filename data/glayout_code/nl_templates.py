"""
Natural language description generation from glayout code lines.
"""
import re

# Map function name → base description
FUNCTION_DESCRIPTIONS: dict[str, str] = {
    "c_route": "C-shaped metal routing",
    "L_route": "L-shaped metal routing",
    "straight_route": "straight metal routing",
    "tapring": "tap ring for well/substrate tie",
    "via_stack": "via stack connecting metal layers",
    "via_array": "via array connecting metal layers",
    "nmos": "NMOS transistor",
    "pmos": "PMOS transistor",
    "multiplier": "transistor multiplier cell",
    "two_nfet_interdigitized": "interdigitized NFET pair",
    "two_pfet_interdigitized": "interdigitized PFET pair",
    "two_tran_interdigitized": "interdigitized transistor pair",
    "rectangle": "rectangular layer region",
    "add_ports_perimeter": "perimeter port exposure",
    "text_freetype": "text label",
    "align_comp_to_port": "component aligned to port",
    "current_mirror": "current mirror sub-cell",
    "diff_pair": "differential pair sub-cell",
}


def _port_name_to_human(port_expr: str) -> str:
    """Convert ports['A_source_E'] to a readable string like 'source-E of A'."""
    m = re.search(r"ports\[['\"]([\w]+)['\"]\]", port_expr)
    if not m:
        return port_expr.strip()
    parts = m.group(1).split("_")
    direction = parts[-1] if parts[-1] in ("N", "S", "E", "W") else ""
    if len(parts) >= 3:
        transistor = parts[0]
        signal = "_".join(parts[1:-1] if direction else parts[1:])
        suffix = f"-{direction}" if direction else ""
        return f"{signal.lower()}{suffix} of {transistor}"
    elif len(parts) == 2:
        return f"{parts[0].lower()} {parts[1]}"
    return m.group(1).lower().replace("_", " ")


def _extract_function_name(line: str) -> str | None:
    m = re.search(r"<<\s*(\w+)\s*\(", line)
    return m.group(1) if m else None


def _extract_port_exprs(line: str) -> list[str]:
    return re.findall(r"\w+\.ports\[['\"]\w+['\"]\]", line)


def describe_operation(code_line: str, circuit_name: str = "") -> str:
    """Generate a short NL description for a glayout << operation line."""
    fn = _extract_function_name(code_line)
    ports = _extract_port_exprs(code_line)
    base = FUNCTION_DESCRIPTIONS.get(fn, fn.replace("_", " ") if fn else "component placement")

    if fn in ("c_route", "L_route", "straight_route") and len(ports) >= 2:
        p1 = _port_name_to_human(ports[0])
        p2 = _port_name_to_human(ports[1])
        return f"Add {base} connecting {p1} to {p2}"

    if fn in ("two_nfet_interdigitized", "two_pfet_interdigitized", "two_tran_interdigitized"):
        m = re.search(r"numcols\s*=\s*(\w+)", code_line)
        cols = f" ({m.group(1)} columns)" if m else ""
        return f"Place {base}{cols}"

    if fn == "tapring":
        m = re.search(r"sdlayer\s*=\s*['\"]([^'\"]+)['\"]", code_line)
        layer = f" ({m.group(1)})" if m else ""
        return f"Add {base}{layer}"

    if fn in ("nmos", "pmos", "multiplier"):
        w = re.search(r"width\s*=\s*([\d.]+)", code_line)
        l = re.search(r"length\s*=\s*([\d.]+)", code_line)
        dims = f" W={w.group(1)}µm L={l.group(1)}µm" if w and l else ""
        return f"Place {base}{dims}"

    return f"Add {base}"


def generate_instruction_variations(
    code_line: str,
    circuit_name: str,
    before_png: str | None = None,
    after_png: str | None = None,
    step_num: int = 0,
) -> list[dict]:
    """
    Produce multiple training sample dicts for one << operation.
    Each dict has: instruction, response, has_image, (optional) image.
    """
    desc = describe_operation(code_line, circuit_name)
    circuit_pretty = circuit_name.replace("_", " ")
    stripped = code_line.strip()
    samples = []

    # 1. Text-only: description → code
    samples.append({
        "instruction": (
            f"In a {circuit_pretty} layout function, write the glayout Python code to: "
            f"{desc.lower()}."
        ),
        "response": f"```python\n{stripped}\n```",
        "has_image": False,
    })

    # 2. Before-image + action → code
    if before_png:
        samples.append({
            "instruction": (
                f"<image>\nThis is the current GDS layout of a {circuit_pretty} circuit. "
                f"Write the glayout Python code to add the next step: {desc.lower()}."
            ),
            "response": f"```python\n{stripped}\n```",
            "has_image": True,
            "image": before_png,
        })

    # 3. After-image + question → code + explanation
    if after_png:
        samples.append({
            "instruction": (
                f"<image>\nThe most recent operation added to this {circuit_pretty} layout "
                f"performed: {desc.lower()}. Write the glayout Python code that produced this."
            ),
            "response": (
                f"The following code was used:\n\n```python\n{stripped}\n```\n\n"
                f"This adds {desc.lower()} to the layout."
            ),
            "has_image": True,
            "image": after_png,
        })

    return samples
