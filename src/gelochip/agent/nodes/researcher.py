"""
Researcher Node – searches ArXiv/web for relevant circuit topologies and design knowledge.
"""
from __future__ import annotations
import json

from langchain_core.messages import AIMessage

from gelochip.agent.state import GelochipAgentState
from gelochip.agent.prompts import RESEARCHER_PROMPT
from gelochip.agent.tools.search_tools import arxiv_search, download_paper_figures


def researcher_node(state: GelochipAgentState, llm) -> GelochipAgentState:
    """
    Search for relevant papers and topology knowledge given the circuit spec.

    1. Builds an ArXiv query from the circuit spec.
    2. Retrieves top papers.
    3. Attempts to extract figures from up to 3 papers via PyMuPDF.
    4. Asks the LLM to synthesize topology recommendations.
    """
    spec = state.get("circuit_spec", {})
    circuit_type = spec.get("circuit_type", "analog circuit")
    topology     = spec.get("topology", "")
    pdk          = spec.get("pdk", "gf180")
    freq         = spec.get("freq_GHz")

    # Build a targeted ArXiv query
    query_parts = [circuit_type, topology, pdk, "CMOS", "analog", "RF IC design"]
    if freq:
        query_parts.append(f"{freq}GHz")
    query = " ".join(filter(None, query_parts))

    # Retrieve papers
    try:
        papers = arxiv_search.invoke({"query": query, "max_results": 5})
    except Exception as e:
        papers = [{"title": "ArXiv unavailable", "summary": str(e)}]

    # Attempt to extract figures from the first 3 papers
    output_dir = state.get("output_dir")
    for paper in papers[:3]:
        pdf_url = paper.get("pdf_url", "")
        if pdf_url:
            arxiv_id = pdf_url.rstrip("/").split("/")[-1]
            # Determine figure output directory
            if output_dir:
                from pathlib import Path
                fig_dir = str(Path(output_dir) / "papers" / arxiv_id)
            else:
                from pathlib import Path
                _pkg = Path(__file__).resolve()
                for _p in _pkg.parents:
                    if (_p / "pyproject.toml").exists():
                        fig_dir = str(_p / "outputs" / "papers" / arxiv_id)
                        break
                else:
                    fig_dir = str(Path.cwd() / "outputs" / "papers" / arxiv_id)
            try:
                figs = download_paper_figures.invoke({
                    "pdf_url":     pdf_url,
                    "paper_id":    arxiv_id,
                    "max_figures": 3,
                    "output_dir":  fig_dir,
                })
                paper["images"]    = figs.get("saved_paths", [])
                paper["pdf_local"] = figs.get("pdf_path")
            except Exception:
                paper["images"]    = []
                paper["pdf_local"] = None
        else:
            paper["images"] = []

    # Ask LLM to synthesize topology recommendations
    messages = [
        {"role": "system", "content": RESEARCHER_PROMPT},
        {
            "role": "user",
            "content": (
                f"Circuit spec:\n{json.dumps(spec, indent=2)}\n\n"
                f"Retrieved papers:\n{json.dumps(papers, indent=2)}\n\n"
                "Based on these specs and papers, recommend the best topology and key design equations."
            ),
        },
    ]
    response = llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)

    try:
        clean = content.strip().lstrip("```json").rstrip("```").strip()
        research_result = json.loads(clean)
    except json.JSONDecodeError:
        research_result = {"raw_recommendation": content, "papers": papers}

    # Save papers metadata
    if output_dir:
        from gelochip.agent.output_manager import OutputManager
        from pathlib import Path
        om = OutputManager.__new__(OutputManager)
        om.root = Path(output_dir)
        om._mkdir(om.root / "papers")
        om.save_papers(papers)

    return {
        **state,
        "retrieved_papers": papers,
        "selected_topology": research_result.get("recommended", topology or circuit_type),
        "messages": state["messages"] + [
            AIMessage(content=f"Research complete. Recommended topology: {research_result.get('recommended', 'unknown')}"),
        ],
        "next_node": "circuit_designer",
    }
