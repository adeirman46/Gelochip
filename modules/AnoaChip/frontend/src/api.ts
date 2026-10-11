import type {
  Chat, Floorplan, IP, IPLibraryResponse, KnowledgeStats, Message, Padframe,
  OllamaModel, Project, RunEvent, SimResult, SimWorkspace, SimWorkspaceMeta, SystemCaps,
} from "./types";

const J = { "Content-Type": "application/json" };
const getJSON = async (u: string) => (await fetch(u)).json();

export const api = {
  async listChats(): Promise<Chat[]> {
    return (await fetch("/api/chats")).json();
  },
  async createChat(title?: string): Promise<Chat> {
    return (await fetch("/api/chats", {
      method: "POST", headers: J, body: JSON.stringify({ title }),
    })).json();
  },
  async getChat(id: string): Promise<{ chat: Chat; messages: Message[]; run: any; transcript: any[]; runs: any[] }> {
    return (await fetch(`/api/chats/${id}`)).json();
  },
  async deleteChat(id: string): Promise<void> {
    await fetch(`/api/chats/${id}`, { method: "DELETE" });
  },
  async deleteMessage(chatId: string, messageId: string): Promise<void> {
    await fetch(`/api/chats/${chatId}/messages/${messageId}`, { method: "DELETE" });
  },
  async editMessage(chatId: string, messageId: string, content: string): Promise<void> {
    await fetch(`/api/chats/${chatId}/messages/${messageId}`, {
      method: "PATCH", headers: J, body: JSON.stringify({ content }),
    });
  },
  /** Edit a message AND re-run it (the new run replaces the old). */
  async rerunMessage(
    chatId: string, messageId: string, content: string, opts: object
  ): Promise<{ run: { id: string } }> {
    return (await fetch(`/api/chats/${chatId}/messages/${messageId}/rerun`, {
      method: "POST", headers: J, body: JSON.stringify({ content, opts }),
    })).json();
  },
  async knowledge(): Promise<KnowledgeStats> {
    return (await fetch("/api/knowledge/stats")).json();
  },
  /** Hardware-aware limits — used to size the context-window slider to the user's VRAM. */
  async systemCaps(): Promise<SystemCaps> {
    return getJSON("/api/system/caps");
  },
  /** Installed Ollama models for the model picker (+ the one in effect now). */
  async systemModels(): Promise<{ models: OllamaModel[]; current: string }> {
    return getJSON("/api/system/models");
  },

  /** Send a prompt (+ optional files); returns the started run id. */
  async sendMessage(
    chatId: string, prompt: string, files: File[], opts: object
  ): Promise<{ message: Message; run: { id: string } }> {
    const fd = new FormData();
    fd.append("prompt", prompt);
    fd.append("opts", JSON.stringify(opts));
    for (const f of files) fd.append("files", f);
    return (await fetch(`/api/chats/${chatId}/messages`, { method: "POST", body: fd })).json();
  },

  async pauseRun(runId: string): Promise<void> {
    await fetch(`/api/runs/${runId}/pause`, { method: "POST" });
  },

  async steerRun(runId: string, message: string): Promise<void> {
    await fetch(`/api/runs/${runId}/steer`, {
      method: "POST", headers: J, body: JSON.stringify({ message }),
    });
  },

  /** Subscribe to a run's SSE stream. Returns an unsubscribe fn. */
  streamRun(runId: string, onEvent: (e: RunEvent) => void): () => void {
    const es = new EventSource(`/api/runs/${runId}/stream`);
    es.onmessage = (m) => {
      try { onEvent(JSON.parse(m.data)); } catch { /* heartbeat */ }
    };
    es.onerror = () => es.close();
    return () => es.close();
  },

  fileUrl(runId: string, path: string): string {
    return `/api/runs/${runId}/file?path=${encodeURIComponent(path)}`;
  },

  // --- projects -------------------------------------------------------------
  async listProjects(): Promise<Project[]> {
    return (await getJSON("/api/projects")).projects;
  },
  async createProject(name?: string): Promise<Project> {
    return (await fetch("/api/projects", { method: "POST", headers: J, body: JSON.stringify({ name }) })).json();
  },
  async renameProject(id: string, name: string): Promise<void> {
    await fetch(`/api/projects/${id}`, { method: "PATCH", headers: J, body: JSON.stringify({ name }) });
  },
  async deleteProject(id: string, cascade = false): Promise<void> {
    await fetch(`/api/projects/${id}?cascade=${cascade}`, { method: "DELETE" });
  },
  async createChatIn(projectId: string | null, title?: string): Promise<Chat> {
    return (await fetch("/api/chats", { method: "POST", headers: J, body: JSON.stringify({ title, project_id: projectId }) })).json();
  },
  async moveChat(chatId: string, projectId: string | null): Promise<void> {
    await fetch(`/api/chats/${chatId}/move`, { method: "POST", headers: J, body: JSON.stringify({ project_id: projectId }) });
  },

  // --- IP library + Create-IP ----------------------------------------------
  async listIPs(): Promise<IPLibraryResponse> {
    return getJSON("/api/ips");
  },
  async getIP(id: string): Promise<IP> {
    return getJSON(`/api/ips/${id}`);
  },
  async createIP(name: string, category: string, subtitle: string, files: File[], top = ""): Promise<IP> {
    const fd = new FormData();
    fd.append("name", name); fd.append("category", category);
    fd.append("subtitle", subtitle); fd.append("top", top);
    for (const f of files) fd.append("files", f);
    return (await fetch("/api/ips", { method: "POST", body: fd })).json();
  },
  async deleteIP(id: string): Promise<void> {
    await fetch(`/api/ips/${id}`, { method: "DELETE" });
  },
  async simulateIP(id: string): Promise<{ status: string; log: string }> {
    return (await fetch(`/api/ips/${id}/simulate`, { method: "POST" })).json();
  },
  async hardenIP(id: string, opts: object): Promise<{ job_id: string }> {
    return (await fetch(`/api/ips/${id}/harden`, { method: "POST", headers: J, body: JSON.stringify(opts) })).json();
  },
  streamJob(jobId: string, onEvent: (e: any) => void): () => void {
    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    es.onmessage = (m) => { try { onEvent(JSON.parse(m.data)); } catch { /* heartbeat */ } };
    es.onerror = () => es.close();
    return () => es.close();
  },
  ipFileUrl(id: string, path: string): string {
    return `/api/ips/${id}/file?path=${encodeURIComponent(path)}`;
  },

  // --- simulation -----------------------------------------------------------
  async listWorkspaces(): Promise<SimWorkspaceMeta[]> {
    return (await getJSON("/api/sim/workspaces")).workspaces;
  },
  async createWorkspace(name?: string, ip_id?: string): Promise<SimWorkspaceMeta> {
    return (await fetch("/api/sim/workspaces", { method: "POST", headers: J, body: JSON.stringify({ name, ip_id }) })).json();
  },
  async getWorkspace(id: string): Promise<SimWorkspace> {
    return getJSON(`/api/sim/workspaces/${id}`);
  },
  async uploadToWorkspace(id: string, files: File[]): Promise<SimWorkspace> {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return (await fetch(`/api/sim/workspaces/${id}/files`, { method: "POST", body: fd })).json();
  },
  async saveFile(id: string, name: string, content: string): Promise<void> {
    await fetch(`/api/sim/workspaces/${id}/files/${encodeURIComponent(name)}`, { method: "PUT", headers: J, body: JSON.stringify({ content }) });
  },
  async deleteWorkspaceFile(id: string, name: string): Promise<void> {
    await fetch(`/api/sim/workspaces/${id}/files/${encodeURIComponent(name)}`, { method: "DELETE" });
  },
  async deleteWorkspace(id: string): Promise<void> {
    await fetch(`/api/sim/workspaces/${id}`, { method: "DELETE" });
  },
  async runSim(id: string, top?: string): Promise<SimResult> {
    const res = await fetch(`/api/sim/workspaces/${id}/run`, { method: "POST", headers: J, body: JSON.stringify({ top }) });
    if (!res.ok) {
      // The backend never 500s a sim (it returns a readable log); a non-2xx here means the
      // REQUEST failed — almost always a stale workspace id (404) after a server restart or a
      // deleted workspace. Surface it cleanly instead of rendering {detail} as a "compile error".
      const body = await res.json().catch(() => ({}));
      return {
        ok: false, compiled: false, status: res.status, gone: res.status === 404,
        log: (body && (body.detail || body.log)) || `run request failed (HTTP ${res.status})`,
      };
    }
    return res.json();
  },

  // --- chip studio ----------------------------------------------------------
  async padframe(): Promise<Padframe> {
    return getJSON("/api/chipstudio/padframe");
  },
  async listFloorplans(): Promise<{ id: string; name: string; blocks: number }[]> {
    return (await getJSON("/api/chipstudio/floorplans")).floorplans;
  },
  async createFloorplan(name?: string): Promise<Floorplan> {
    return (await fetch("/api/chipstudio/floorplans", { method: "POST", headers: J, body: JSON.stringify({ name }) })).json();
  },
  async getFloorplan(id: string): Promise<Floorplan> {
    return getJSON(`/api/chipstudio/floorplans/${id}`);
  },
  async saveFloorplan(fp: Floorplan): Promise<Floorplan> {
    return (await fetch(`/api/chipstudio/floorplans/${fp.id}`, { method: "PUT", headers: J, body: JSON.stringify(fp) })).json();
  },
  async deleteFloorplan(id: string): Promise<void> {
    await fetch(`/api/chipstudio/floorplans/${id}`, { method: "DELETE" });
  },
};
