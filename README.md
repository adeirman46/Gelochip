# Gelochip

**A unified workspace for AI-assisted analog and RF integrated-circuit design.**

Gelochip brings together **PandaChip Auto Schematic Maker**, **AnoaChip Auto Layouter**, and **Gelochip Studio** to connect circuit intent, schematic generation, simulation, physical layout, and verification within one project.

The end goal is **one website where a designer can develop and review a circuit from specification to verified layout**, with a traceable relationship between every design revision and its results. Development starts on localhost, with cloud deployment planned after the integrated workflow has been validated.

> **Current status:** the development branches and both application archives have been consolidated into this repository, and a localhost portal provides access to the three applications. The engines still run independently. Automatic schematic-to-layout transfer, a shared project API, and a unified design interface are planned capabilities.

## Project background

Analog and RF IC design connects electrical requirements with physical implementation. A specification must become a circuit topology, device dimensions, bias conditions, and a simulation setup. The circuit then becomes a layout whose placement and routing must satisfy the selected process design kit (PDK). Physical implementation can introduce parasitic effects that require further analysis and design iteration.

These stages produce different artifacts: schematics, SPICE netlists, testbenches, simulation data, layout generators, GDSII files, and verification reports. Keeping those artifacts consistent is a central integration problem. A schematic revision can invalidate an earlier netlist or layout; a change in device models or PDK configuration can alter the meaning of previously generated results.

When each stage lives in a separate application, the designer must manage these relationships manually. Files need to be transferred, input formats reconciled, tool environments configured, and results associated with the correct design revision. The resulting coordination work makes the design process harder to reproduce and review.

Gelochip addresses this problem by bringing existing capabilities into a common platform. PandaChip contributes schematic generation and simulation through xschem and OpenADA. AnoaChip contributes a Glayout-based path toward physical layout and verification. Gelochip Studio contributes design agents and reusable analog/RF building blocks. Consolidating their source is the foundation; the next challenge is to connect their engineering workflows through explicit interfaces and shared project records.

AI supports specification interpretation, candidate generation, and iteration. Engineering acceptance must remain grounded in the circuit's measured behavior and the evidence produced by EDA tools. The platform therefore aims to preserve the connection between a generated design, its inputs, and the checks performed on that exact revision.

This overview follows the conceptual structure requested for a B100-style introduction: background, problem definition, objectives, proposed solution, scope, and acceptance criteria. It is a project overview rather than a formal submission against an institution-specific B100 template.

## Problem definition

The project centers on four integration questions:

1. How can schematic generation, simulation, layout generation, and verification be coordinated through one website?
2. How can the system maintain consistent connectivity, port definitions, device models, voltage assumptions, and PDK selection across engines?
3. How can design revisions, execution logs, and artifacts be linked so that each verification result identifies the design it actually checked?
4. How can the platform progress from localhost to cloud hosting while preserving existing configurations and design artifacts?

Success requires both a usable interface and a reliable engineering handoff between stages. A common dashboard alone does not establish that a schematic and its generated layout describe the same circuit.

## Objectives and intended users

The primary objective is to provide **one Gelochip website with one project workspace** for the complete analog/RF design workflow.

The platform is intended for Chipathon participants, students, researchers, and developers working with open EDA tools. Its planned benefits are reduced manual file transfer, clearer visibility into design iterations, and easier review of simulation and verification evidence. Improvements in design time, circuit quality, or verification success rate have not yet been measured.

| User need | Intended platform behavior |
|---|---|
| Express circuit requirements | Capture circuit function, performance targets, operating conditions, and design constraints |
| Develop and inspect a circuit | Present the schematic, netlist, device parameters, and simulation results together |
| Continue into physical design | Validate compatible inputs before handing the design to a layout engine |
| Understand a run's outcome | Show execution status, tool logs, artifacts, and engineering check results |
| Revise a design | Track the relationship between input revisions, runs, and resulting artifacts |
| Work locally | Support localhost operation with explicit model, PDK, and EDA runtime configuration |

## Proposed platform architecture

The target architecture uses a shared web interface and an orchestration API to coordinate engines with separate runtime environments. This keeps each engine's dependency requirements manageable while giving users a common project experience.

```text
                         One Gelochip website
                                  |
                 Project specification and design revision
                                  |
                 PandaChip: schematic and SPICE netlist
                                  |
                    Simulation and specification checks
                                  |
                AnoaChip / Gelochip: physical layout
                                  |
             Layout verification and applicable simulation
                                  |
                 Reports, artifacts, and design review
                                  |
                       Revision and another run
```

The planned orchestration layer must agree on the information exchanged between stages: circuit specifications, connectivity, port names, device parameters, model references, PDK identity, input revision, and artifact locations. It must check that information before launching the next engine and record which inputs produced each result.

The project workspace should also distinguish **execution completion** from **engineering acceptance**. For example, producing a GDSII file establishes that a layout artifact was generated. Whether that layout satisfies design rules, matches the intended circuit, and meets performance targets requires the corresponding checks and review.

This architecture describes the development target. The current portal provides navigation and backend availability checks; it does not implement cross-engine orchestration.

## Scope and engineering boundaries

The planned scope covers application integration, project and artifact management, schematic-to-layout handoff, and presentation of simulation and verification results for analog/RF designs supported by the selected engines.

PDK and topology support must be established for the actual workflow being used. Availability in one engine does not establish compatibility across the entire pipeline. Likewise, choosing a local or cloud model does not remove the need for suitable EDA binaries, device models, and rule decks.

The first deployment target is localhost. Cloud hosting follows validation of the integrated workflow and its operational requirements. Fabrication readiness requires the applicable signoff process; agent completion, successful simulation, or GDSII generation alone does not establish tapeout readiness.

**Preservation requirement:** existing `info.yaml`/`Info.yaml`, `config.json`, and design folders such as `OUTS` and `outputs` must remain protected. Integration work must preserve their original locations and contents rather than overwrite them as part of engine consolidation.

## Current implementation and acceptance criteria

| Area | Current implementation | Target acceptance condition |
|---|---|---|
| Source consolidation | Development contributions and both ZIP imports are present on local `main` | A maintainable repository containing all three engines |
| Artifact preservation | The integration baseline audit passed | Protected configurations and existing artifacts remain intact |
| Web access | A localhost portal links the applications | One interface supports all design stages |
| Schematic-to-layout handoff | Manual transfer and input adaptation | Compatible designs pass between stages without manual file transfer |
| Design traceability | No shared revision model across engines | Each result identifies its input revision, configuration, and run |
| Complete workflow validation | Not yet performed in the integration environment | A defined example meets its agreed simulation and verification criteria |
| Cloud deployment | Not deployed | Deployment after local workflow and service readiness checks |

Before evaluating the complete workflow, the team must select a reference circuit, PDK, operating conditions, performance targets, and simulation/DRC/LVS acceptance criteria. The end goal is achieved when that project can be developed, executed, and reviewed through the same website, without manual transfers between applications, with results traceable to the inputs used.

## Repository components

| Application | Responsibility | Source location | Local address |
|---|---|---|---|
| Workspace Portal | Navigation and backend availability checks | `integration/` | http://localhost:8080 |
| Gelochip Studio | Analog/RF design agents, building blocks, layout, and verification | `app/`, `src/gelochip/` | http://localhost:8090 |
| AnoaChip | Auto Layouter: SPICE, specification simulation, Glayout GDSII, DRC/LVS | `modules/AnoaChip/` | http://localhost:5175; API on :8012 |
| PandaChip | Auto Schematic Maker: xschem schematics, netlists, and OpenADA simulation | `modules/PandaChip/` | http://localhost:8317 |

```text
Gelochip/
|-- integration/          Localhost portal and integration checks
|-- modules/
|   |-- AnoaChip/          Imported application, data, and documentation
|   `-- PandaChip/         Imported application, designs, and OpenADA
|-- app/                  Gelochip Studio: FastAPI and React
|-- src/gelochip/          Agents, GLayout, primitives, and analog/RF blocks
|-- scripts/              Gelochip utilities and RF verification scripts
|-- tests/                Gelochip tests
|-- outputs/              Existing output artifacts
|-- Tapeout/              Existing tapeout artifacts
|-- tapeout_iris/          IRIS designs and verification evidence
|-- report/               Design reports
`-- integration-audit/    Preservation baseline and integration records
```

## Start the localhost portal

The portal requires Python 3.10+ and runs on Windows, Linux, or WSL:

```powershell
python integration/portal.py
```

Open **http://localhost:8080**. Start the required applications separately using the instructions below. Portal status indicates whether a backend is reachable; it does not establish frontend readiness or a circuit's verification outcome.

## Run Gelochip Studio

Use Linux or WSL2 for the EDA workflow. From the repository root:

```bash
python3 -m venv .venv-studio
source .venv-studio/bin/activate
python -m pip install -r requirements-app.txt

# Create .env only if it does not exist, then configure the provider and PDK.
[ -f .env ] || cp .env.example .env
export PYTHONPATH="$PWD/src:$PWD/src/gelochip${PYTHONPATH:+:$PYTHONPATH}"

cd app/frontend
npm ci
npm run dev
```

In a second terminal, run the backend from the repository root:

```bash
source .venv-studio/bin/activate
export PYTHONPATH="$PWD/src:$PWD/src/gelochip${PYTHONPATH:+:$PYTHONPATH}"
python -m uvicorn app.kaizen_app:app --host 127.0.0.1 --port 8090
```

The development frontend runs at **http://localhost:5173** and proxies requests to the backend on :8090. Serving the built frontend from :8090 requires `npm run build` in `app/frontend`; the default Vite configuration updates `app/static/web/`. Preserve any existing build artifacts before using that command. Container instructions are available in the [Docker guide](docs/DOCKER.md), [Dockerfile](Dockerfile), and [Compose configuration](docker-compose.yml).

## Run AnoaChip Auto Layouter

AnoaChip retains its original `pyproject.toml`, `uv.lock`, and directory structure. Its Glayout dependency points to **`../gLayout`**, which resolves to **`modules/gLayout/`** in this repository. The embedded `src/gelochip/glayout/` source is not automatically a replacement for that external package.

On Linux or WSL2, prepare a compatible Glayout checkout at that location, then run:

```bash
cd modules/AnoaChip
[ -f .env ] || cp .env.example .env
bash scripts/install.sh

cd frontend
npm ci
cd ..
bash scripts/run.sh
```

The installer downloads dependencies, models, and PDK resources, and may install build tools using `sudo`. The backend runs on :8012 and the frontend on :5175. Some examples in the imported README use older ports; the bundled run script and Vite configuration use the addresses shown here.

See the [AnoaChip README](modules/AnoaChip/README.md) for the layout workflow, model configuration, and Postgres/MinIO knowledge store.

## Run PandaChip Auto Schematic Maker

Use Linux or WSL2 with Docker, Node.js/npm, Go 1.18+, Python, uv, and Ollama. EDA tools run in the `pandachip-eda` container. Interactive schematic viewing requires an X display as described by the original scripts.

```bash
cd modules/PandaChip
uv venv .venv --python python3
uv pip install --python .venv/bin/python -e ./src jsonschema numpy matplotlib

cd frontend
npm ci
cd ..
bash scripts/start_eda_container.sh
bash scripts/run.sh
```

Open **http://localhost:8317**. Follow the [PandaChip README](modules/PandaChip/README.md) for model selection and Gemini/Vertex AI credentials. Models with a `:cloud` suffix require cloud access; localhost hosting does not imply offline model execution.

## Work across the applications today

1. Generate a schematic and netlist in PandaChip.
2. Review connectivity, port definitions, transistor models, operating voltages, and PDK requirements.
3. Provide the netlist and specification to an AnoaChip or Gelochip workflow, adapting inputs through the application's supported facilities.
4. Review simulation results, DRC/LVS reports, and GDSII artifacts associated with the same design revision.

A shared API, automatic format conversion, common accounts, and a cross-engine job queue are not yet implemented. Each application retains its own output locations, so existing artifacts can stay where they were created.

## Validation

Run the preservation audit and portal tests from the repository root:

```bash
python integration/verify_preservation.py
python -m unittest discover -s integration -p "test_*.py" -v
```

The recorded integration checks include 154 preservation baseline checks, four passing portal tests, Python syntax checks, ZIP-content comparisons, and a successful Gelochip frontend build in a separate test directory. Details and limitations are documented in the [integration record](integration-audit/MERGE.md).

Gelochip's engine tests require the relevant EDA and agent dependencies:

```bash
PYTHONPATH=src:src/gelochip python -m pytest tests
```

Repository consolidation, portal tests, and frontend compilation validate the integration foundation. A complete LLM-to-layout design run still needs its runtime dependencies, PDK, models, and engineering acceptance checks.

## Development roadmap

| Stage | Deliverable | Completion criterion |
|---|---|---|
| 1. Integration foundation | Consolidated source, preserved artifacts, local portal | Source and preservation checks pass; applications have documented entry points |
| 2. Shared engineering interfaces | Orchestration API and agreed exchange formats | Input compatibility checks and artifact handoff work on a reference design |
| 3. Unified website | Project dashboard and schematic/layout/result workspaces | Users operate all stages through one project interface |
| 4. Workflow validation | Revision tracking and complete design execution | The reference design meets predefined simulation and verification criteria |
| 5. Cloud readiness | Authentication, isolated workers, persistent storage, and deployment configuration | Validated local behavior is maintained in the hosted environment |

The unified website should offer schematic and layout inspection, simulation results, job progress, logs, and downloadable artifacts in one workspace. Local and cloud model choices can share that interface while the engines retain separate backend environments.

For cloud deployment, the planned service boundary separates the web application, EDA workers, model access, and artifact storage. Reverse proxy configuration, authentication, worker isolation, persistent storage, and service testing must be established before public deployment. The current portal binds to loopback for local use.

## Repository maintenance and preservation

- Local `main` was aligned with `origin/main`, then merged with `dev_wilton` to retain contribution history. The `origin/dev_irman` and `origin/dev_ken` histories were already included in `origin/main` at integration time.
- Source branches remain available. A local merge does not automatically publish changes to GitHub.
- Protected configurations, output artifacts, reports, and tapeout files are checked against the recorded SHA-256 baseline. Original filename capitalization is preserved.
- Existing directories remain in place. Files present in the Wilton checkout but absent from the incoming main tree were retained.
- The imported applications live under `modules/` to prevent collisions between source paths, configurations, and dependency versions.
- Bundled ZIP dependencies may remain on the integration machine, but new `node_modules` directories are not included as application source. Install dependencies from the original lockfiles for the target platform.

## Licensing and source attribution

Gelochip's license is in [LICENSE](LICENSE). AnoaChip includes its own [license](modules/AnoaChip/LICENSE), and the OpenADA source distributed with PandaChip includes [its license](modules/PandaChip/src/LICENSE). Preserve the attribution and licensing requirements of each component.

The original Gelochip main-branch documentation is retained in the [README archive](integration-audit/README-origin-main.md).
