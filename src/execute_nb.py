import sys, time, nbformat
from pathlib import Path
from nbclient import NotebookClient

NB = Path("/home/irman/gLayout/notebook/GLayout_RF_EnergyHarvester_Complete.ipynb")
nb = nbformat.read(NB, as_version=4)
nb.metadata["kernelspec"] = {"display_name": "Python (glayout_env)",
                             "language": "python", "name": "glayout_env"}
t0 = time.time()
client = NotebookClient(nb, timeout=2700, kernel_name="glayout_env",
                        resources={"metadata": {"path": str(NB.parent)}},
                        allow_errors=True)
client.execute()
nbformat.write(nb, NB)

nerr = 0
for i, c in enumerate(nb.cells):
    if c.cell_type != "code":
        continue
    errs = [o for o in c.get("outputs", []) if o.get("output_type") == "error"]
    if errs:
        nerr += 1
        print(f"\n### CELL {i} RAISED {errs[0]['ename']}: {errs[0]['evalue']}")
        print("\n".join(errs[0].get("traceback", [])[-6:]))
print(f"\n=== executed {sum(1 for c in nb.cells if c.cell_type=='code')} code cells "
      f"in {time.time()-t0:.0f}s, {nerr} with errors ===")
