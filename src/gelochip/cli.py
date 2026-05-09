"""Gelochip command-line interface."""
import typer
from rich.console import Console

app = typer.Typer(name="gelochip", help="AI-Assisted Analog/RF IC Layout Automation")
console = Console()


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="API host"),
    port: int = typer.Option(8000, help="API port"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes"),
):
    """Start the Gelochip FastAPI backend."""
    import uvicorn
    console.print(f"[green]Starting Gelochip API on http://{host}:{port}[/green]")
    uvicorn.run("gelochip.api.main:app", host=host, port=port, reload=reload)


@app.command()
def ui(
    port: int = typer.Option(8080, help="Chainlit web UI port"),
):
    """Start the Gelochip Chainlit web interface."""
    import subprocess
    import sys
    console.print(f"[green]Starting Gelochip Web UI on http://localhost:{port}[/green]")
    subprocess.run([
        sys.executable, "-m", "chainlit", "run",
        "app/chainlit_app.py", "--port", str(port),
    ])


@app.command()
def design(
    request: str = typer.Argument(..., help="Natural language circuit design request"),
    pdk: str = typer.Option("sky130", help="Target PDK"),
    output: str = typer.Option("", help="Output directory (default: <project>/outputs/)"),
):
    """Run the Gelochip agent on a design request (CLI mode)."""
    from gelochip.agent.graph import build_graph, create_initial_state
    console.print(f"[blue]Designing: {request}[/blue]")
    graph = build_graph()
    state = create_initial_state(user_request=request)
    result = graph.invoke(state)
    console.print(result.get("final_answer", "No answer generated."))
    if result.get("layout_result", {}).get("gds_path"):
        console.print(f"[green]GDS saved to: {result['layout_result']['gds_path']}[/green]")


@app.command()
def blocks():
    """List all available Gelochip building blocks."""
    from gelochip.agent.tools.circuit_tools import list_available_blocks
    from rich.table import Table
    result = list_available_blocks.invoke({})
    for category, items in result.items():
        table = Table(title=category.upper(), show_header=False)
        table.add_column("Function", style="cyan")
        for item in items:
            table.add_row(item)
        console.print(table)


if __name__ == "__main__":
    app()
