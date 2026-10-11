// Package server implements the PandaChip web API: submit a design prompt,
// track the agent run (Ollama glm-5.2:cloud or Google Gemini via ADC,
// + OpenADA + xschem/ngspice), and serve the resulting schematic and
// waveform evidence.
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"syscall"
	"time"
)

type Server struct {
	Root    string // PandaChip repo root
	Designs string // designs/ directory
	Python  string // .venv/bin/python
	Static  string // pandachip/static
}

func New(root string) *Server {
	return &Server{
		Root:    root,
		Designs: filepath.Join(root, "designs"),
		Python:  filepath.Join(root, ".venv", "bin", "python"),
		Static:  filepath.Join(root, "pandachip", "static"),
	}
}

var runIDRe = regexp.MustCompile(`^[A-Za-z0-9._-]+$`)

type meta struct {
	Prompt  string `json:"prompt"`
	PID     int    `json:"pid"`
	Created string `json:"created"`
	Model   string `json:"model,omitempty"`
	PDK     string `json:"pdk,omitempty"`
}

const (
	defaultModel = "glm-5.2:cloud"
	defaultPDK   = "gf180mcuD"
)

type runSummary struct {
	RunID   string `json:"run_id"`
	State   string `json:"state"`
	Prompt  string `json:"prompt"`
	Created string `json:"created"`
	Model   string `json:"model"`
	PDK     string `json:"pdk"`
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleSPA)
	mux.HandleFunc("/api/v1/auth/login", s.handleLogin)
	mux.HandleFunc("/api/v1/auth/me", s.handleMe)
	mux.HandleFunc("/api/models", s.handleModels)
	mux.HandleFunc("/api/pdks", s.handlePdks)
	mux.HandleFunc("/api/runs", s.handleRuns)
	mux.HandleFunc("/api/run", s.handleStartRun)
	mux.HandleFunc("/api/run/", s.handleRunStatus)
	mux.HandleFunc("/api/artifact/", s.handleArtifact)
	mux.HandleFunc("/api/resume/", s.handleResume)
	mux.HandleFunc("/api/pause/", s.handlePause)
	mux.HandleFunc("/api/suggest/", s.handleSuggest)
	mux.HandleFunc("/api/report/", s.handleReport)
	mux.HandleFunc("/api/xschem/", s.handleXschem)
	return mux
}

// handleSPA serves the built React frontend (frontend/dist) with an SPA
// fallback to index.html; the legacy single-file UI remains the fallback
// when the frontend has not been built.
func (s *Server) handleSPA(w http.ResponseWriter, r *http.Request) {
	dist := filepath.Join(s.Root, "frontend", "dist")
	index := filepath.Join(dist, "index.html")
	if _, err := os.Stat(index); err != nil {
		http.ServeFile(w, r, filepath.Join(s.Static, "index.html"))
		return
	}
	clean := filepath.Clean("/" + r.URL.Path)
	full := filepath.Join(dist, clean)
	if info, err := os.Stat(full); err == nil && !info.IsDir() &&
		strings.HasPrefix(full, dist+string(os.PathSeparator)) {
		http.ServeFile(w, r, full)
		return
	}
	http.ServeFile(w, r, index)
}

// Local single-user auth: any non-empty credentials are accepted; the token
// only exists so the duplicated login/session flow works unchanged.
func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST only"})
		return
	}
	var body struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	data, _ := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<16))
	if json.Unmarshal(data, &body) != nil || strings.TrimSpace(body.Username) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "username required"})
		return
	}
	user := strings.TrimSpace(body.Username)
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"access_token": "pandachip-local-" + user,
		"user": map[string]interface{}{
			"id":        "1",
			"username":  user,
			"full_name": user + " @ PandaChip",
			"roles":     []string{"operator"},
		},
	})
}

func (s *Server) handleMe(w http.ResponseWriter, r *http.Request) {
	auth := r.Header.Get("Authorization")
	const prefix = "Bearer pandachip-local-"
	if !strings.HasPrefix(auth, prefix) || len(auth) == len(prefix) {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid session"})
		return
	}
	user := strings.TrimPrefix(auth, prefix)
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id":        "1",
		"username":  user,
		"full_name": user + " @ PandaChip",
		"roles":     []string{"operator"},
	})
}

func (s *Server) runDir(id string) (string, bool) {
	if !runIDRe.MatchString(id) {
		return "", false
	}
	d := filepath.Join(s.Designs, id)
	info, err := os.Stat(d)
	if err != nil || !info.IsDir() {
		return "", false
	}
	return d, true
}

func readJSON(path string, v interface{}) bool {
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	return json.Unmarshal(data, v) == nil
}

// workflowPhases is the timeline the agent must actually walk; each entry
// is marked "done" by pandachip's tool layer only when it witnessed the
// artifact that defines the phase.
var workflowPhases = []string{"spec_ingestion", "plan", "sch_gen", "tb_gen", "sim"}

// engineeringPhases are the ones that decide whether a run counts as
// verified. spec_ingestion and plan are process steps - a CLI run given
// its task inline never writes a plan.md - so they are shown in the
// timeline but never used to demote a run that has real evidence.
var engineeringPhases = []string{"sch_gen", "tb_gen", "sim"}

type phaseEntry struct {
	Status string `json:"status"`
	At     string `json:"at,omitempty"`
	Note   string `json:"note,omitempty"`
}

// readPhases loads the phase ledger. A run from before the ledger existed
// (or a bare CLI run) still holds the legacy announcement-log format; for
// those, the tool layer reconciles the ledger from the artifacts actually
// present in the workspace and rewrites phases.json in ledger form, once.
func (s *Server) readPhases(dir string) map[string]phaseEntry {
	path := filepath.Join(dir, "phases.json")
	ledger := map[string]phaseEntry{}
	if readJSON(path, &ledger) && len(ledger) > 0 {
		return ledger
	}
	cmd := exec.Command(s.Python, "-c",
		"import sys; from pandachip.eda_tools import Workspace; "+
			"Workspace(sys.argv[1]).reconcile_phases()", dir)
	cmd.Dir = s.Root
	cmd.Run()
	ledger = map[string]phaseEntry{}
	readJSON(path, &ledger)
	return ledger
}

// unverifiedPhases names the engineering phases that never earned evidence.
func (s *Server) unverifiedPhases(dir string) []string {
	ledger := s.readPhases(dir)
	var missing []string
	for _, ph := range engineeringPhases {
		if ledger[ph].Status != "done" {
			missing = append(missing, ph)
		}
	}
	return missing
}

func (s *Server) runState(dir string) (string, meta, map[string]interface{}) {
	var m meta
	hasMeta := readJSON(filepath.Join(dir, "meta.json"), &m)
	// CLI-launched runs carry no meta: fill the values they actually used
	// (agent defaults) and date the run from its task file / directory.
	if m.Model == "" {
		m.Model = defaultModel
	}
	if m.PDK == "" {
		m.PDK = defaultPDK
	}
	if m.Created == "" {
		// Date the run from the OLDEST start-of-run artifact. Never from
		// the directory's own mtime: any later write into the workspace
		// (a re-plot, a phase-ledger update) moves it and would silently
		// re-date the run to now, shuffling the dashboard ordering.
		oldest := time.Time{}
		for _, f := range []string{"task.md", "preflight.json", "plan.md", "agent.log"} {
			if info, err := os.Stat(filepath.Join(dir, f)); err == nil {
				if oldest.IsZero() || info.ModTime().Before(oldest) {
					oldest = info.ModTime()
				}
			}
		}
		if !oldest.IsZero() {
			m.Created = oldest.Format("2006-01-02 15:04:05")
		}
	}
	var outcome map[string]interface{}
	hasOutcome := readJSON(filepath.Join(dir, "outcome.json"), &outcome)

	evidence, _ := outcome["evidence"].(string)
	specMet, hasSpecMet := outcome["spec_met"].(bool)
	switch {
	case hasOutcome && outcome["status"] == "done" &&
		strings.TrimSpace(evidence) != "" && (!hasSpecMet || specMet) &&
		len(s.unverifiedPhases(dir)) == 0:
		// "done" is shown only when the agent produced verification
		// evidence AND schematic/testbench/sim each earned their
		// artifact - not merely because the agent claimed completion.
		return "completed", m, outcome
	case hasOutcome:
		return "needs_review", m, outcome
	case hasMeta && m.PID > 0:
		if _, err := os.Stat(fmt.Sprintf("/proc/%d", m.PID)); err == nil {
			if _, err := os.Stat(filepath.Join(dir, ".paused")); err == nil {
				return "paused", m, nil
			}
			return "running", m, nil
		}
		return "failed", m, nil
	default:
		// CLI-launched run: no meta/outcome. Consider it running while the
		// workspace shows recent activity (first model call can take minutes
		// before transcript.json even exists).
		newest := time.Time{}
		for _, f := range []string{"transcript.json", "agent.log",
			"preflight.json", "task.md"} {
			if info, err := os.Stat(filepath.Join(dir, f)); err == nil &&
				info.ModTime().After(newest) {
				newest = info.ModTime()
			}
		}
		if !newest.IsZero() && time.Since(newest) < 15*time.Minute {
			return "running", m, nil
		}
		return "needs_review", m, nil
	}
}

func (s *Server) handleRuns(w http.ResponseWriter, r *http.Request) {
	entries, _ := os.ReadDir(s.Designs)
	runs := []runSummary{}
	for _, e := range entries {
		if !e.IsDir() || strings.HasPrefix(e.Name(), ".") {
			continue
		}
		dir := filepath.Join(s.Designs, e.Name())
		state, m, _ := s.runState(dir)
		runs = append(runs, runSummary{e.Name(), state, m.Prompt, m.Created,
			m.Model, m.PDK})
	}
	// Newest first by creation time (the timestamp format sorts
	// lexicographically); fall back to run id when timestamps tie.
	sort.Slice(runs, func(i, j int) bool {
		if runs[i].Created != runs[j].Created {
			return runs[i].Created > runs[j].Created
		}
		return runs[i].RunID > runs[j].RunID
	})
	writeJSON(w, http.StatusOK, runs)
}

// handleModels lists the models available: local Ollama models plus the
// Google Gemini models reachable through ADC (Vertex AI), when configured.
func (s *Server) handleModels(w http.ResponseWriter, r *http.Request) {
	names := []string{}
	if resp, err := http.Get("http://localhost:11434/api/tags"); err == nil {
		var payload struct {
			Models []struct {
				Name string `json:"name"`
			} `json:"models"`
		}
		if json.NewDecoder(resp.Body).Decode(&payload) == nil {
			for _, m := range payload.Models {
				names = append(names, m.Name)
			}
		}
		resp.Body.Close()
	}
	sort.Strings(names)
	names = append(names, geminiModels()...)
	if len(names) == 0 {
		writeJSON(w, http.StatusBadGateway, map[string]string{
			"error": "no models: ollama unreachable and no Google ADC configured"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"models": names, "default": defaultModel})
}

// geminiModels returns the Gemini model ids offered when Google ADC exists
// (gcloud auth application-default login). Override the list with
// PANDACHIP_GEMINI_MODELS (comma-separated).
func geminiModels() []string {
	adc := os.Getenv("GOOGLE_APPLICATION_CREDENTIALS")
	if adc == "" {
		home, _ := os.UserHomeDir()
		adc = filepath.Join(home, ".config", "gcloud", "application_default_credentials.json")
	}
	if _, err := os.Stat(adc); err != nil {
		return nil
	}
	list := os.Getenv("PANDACHIP_GEMINI_MODELS")
	if list == "" {
		list = "gemini-3.1-pro-preview,gemini-3.5-flash,gemini-2.5-pro"
	}
	models := []string{}
	for _, m := range strings.Split(list, ",") {
		if m = strings.TrimSpace(m); m != "" {
			models = append(models, m)
		}
	}
	return models
}

// handlePdks lists PDKs found in the EDA container (dirs with libs.tech).
func (s *Server) handlePdks(w http.ResponseWriter, r *http.Request) {
	out, err := exec.Command("docker", "exec", "pandachip-eda", "sh", "-c",
		"for d in /foss/pdks/*/libs.tech; do [ -d \"$d\" ] && basename \"$(dirname \"$d\")\"; done").Output()
	pdks := []string{}
	if err == nil {
		for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
			if line != "" {
				pdks = append(pdks, line)
			}
		}
	}
	if len(pdks) == 0 {
		pdks = []string{defaultPDK}
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"pdks": pdks, "default": defaultPDK,
		"note": "The authoring guide is tuned for gf180mcuD; other PDKs are experimental."})
}

var fileNameRe = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func (s *Server) handleStartRun(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST only"})
		return
	}

	var prompt, name, model, pdk string
	var uploads []string

	runID := ""
	ct := r.Header.Get("Content-Type")
	if strings.HasPrefix(ct, "multipart/form-data") {
		if err := r.ParseMultipartForm(64 << 20); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad multipart form"})
			return
		}
		prompt = r.FormValue("prompt")
		name = r.FormValue("name")
		model = r.FormValue("model")
		pdk = r.FormValue("pdk")
	} else {
		var body struct {
			Prompt string `json:"prompt"`
			Name   string `json:"name"`
			Model  string `json:"model"`
			PDK    string `json:"pdk"`
		}
		data, _ := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
		if json.Unmarshal(data, &body) != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad json"})
			return
		}
		prompt, name, model, pdk = body.Prompt, body.Name, body.Model, body.PDK
	}

	if strings.TrimSpace(prompt) == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "empty prompt"})
		return
	}
	if model == "" {
		model = defaultModel
	}
	if pdk == "" {
		pdk = defaultPDK
	}
	if !runIDRe.MatchString(pdk) || !regexp.MustCompile(`^[A-Za-z0-9._:/-]+$`).MatchString(model) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad model or pdk"})
		return
	}
	// ngspice lowercases the paths it sources, so an uppercase run
	// directory makes every simulation fail (or, worse, resolve into a
	// different run that happens to own the lowercase name). Run IDs are
	// therefore lowercase, always.
	runID = strings.ToLower(name)
	if runID == "" {
		runID = "web-" + time.Now().Format("20060102-150405")
	}
	if !runIDRe.MatchString(runID) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad run name"})
		return
	}
	dir := filepath.Join(s.Designs, runID)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}

	// Save uploaded reference files (image/pdf/text) into <run>/uploads/.
	if r.MultipartForm != nil {
		files := r.MultipartForm.File["files"]
		if len(files) > 0 {
			upDir := filepath.Join(dir, "uploads")
			os.MkdirAll(upDir, 0o755)
			for _, fh := range files {
				base := fileNameRe.ReplaceAllString(filepath.Base(fh.Filename), "_")
				if base == "" || base == "." {
					continue
				}
				src, err := fh.Open()
				if err != nil {
					continue
				}
				dst, err := os.Create(filepath.Join(upDir, base))
				if err == nil {
					io.Copy(dst, src)
					dst.Close()
					uploads = append(uploads, "uploads/"+base)
				}
				src.Close()
			}
		}
	}

	taskText := prompt
	if len(uploads) > 0 {
		taskText += "\n\nAttached reference files (in the workspace):\n"
		for _, u := range uploads {
			taskText += "- " + u + "\n"
		}
	}
	taskFile := filepath.Join(dir, "task.md")
	os.WriteFile(taskFile, []byte(taskText), 0o644)

	logFile, err := os.Create(filepath.Join(dir, "agent.log"))
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	// The deep-agent orchestrator (LangChain/LangGraph) plans with a
	// persisted todo list and dispatches one subagent per block, so a
	// block is finished and verified before the next one starts.
	cmd := exec.Command(s.Python, "-m", "pandachip.orchestra",
		"--task-file", taskFile, "--workdir", dir,
		"--model", model)
	cmd.Dir = s.Root
	cmd.Env = append(os.Environ(), "PANDACHIP_PDK="+pdk)
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	if err := cmd.Start(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	m := meta{Prompt: prompt, PID: cmd.Process.Pid,
		Created: time.Now().Format("2006-01-02 15:04:05"),
		Model:   model, PDK: pdk}
	mj, _ := json.Marshal(m)
	os.WriteFile(filepath.Join(dir, "meta.json"), mj, 0o644)
	go cmd.Wait() // reap
	writeJSON(w, http.StatusOK, map[string]string{"run_id": runID})
}

func (s *Server) handleRunStatus(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/run/")
	dir, ok := s.runDir(id)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no such run"})
		return
	}
	if r.Method == http.MethodDelete {
		var m meta
		if readJSON(filepath.Join(dir, "meta.json"), &m) && m.PID > 0 {
			if p, err := os.FindProcess(m.PID); err == nil {
				p.Kill()
			}
		}
		if err := os.RemoveAll(dir); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, map[string]interface{}{"ok": true, "deleted": id})
		return
	}
	state, m, outcome := s.runState(dir)

	// Ship one entry per workflow phase, in order, each carrying the
	// status the tool layer recorded - the UI renders it verbatim rather
	// than guessing progress from the last phase it saw.
	ledger := s.readPhases(dir)
	phases := make([]map[string]interface{}, 0, len(workflowPhases))
	for _, ph := range workflowPhases {
		e, seen := ledger[ph]
		status := e.Status
		if !seen || status == "" {
			status = "pending"
		}
		if status == "running" && state != "running" {
			// The run is over and this phase never earned its artifact.
			status = "incomplete"
		}
		phases = append(phases, map[string]interface{}{
			"phase": ph, "status": status, "at": e.At, "note": e.Note})
	}

	var plots []string
	if state != "running" {
		seen := map[string]bool{}
		// Analysis charts (plot_xy sweeps: VOUT vs dBm / frequency) lead,
		// then the rawfile-derived waveform plots from autoplot.
		if all, err := filepath.Glob(filepath.Join(dir, "waves_*.png")); err == nil {
			sort.Strings(all)
			for _, p := range all {
				rel, _ := filepath.Rel(dir, p)
				stem := strings.TrimSuffix(strings.TrimPrefix(rel, "waves_"), ".png")
				if _, err := os.Stat(filepath.Join(dir, stem+".raw")); err != nil {
					if _, err := os.Stat(filepath.Join(dir, "exp", stem+".raw")); err != nil {
						plots = append(plots, rel)
						seen[rel] = true
					}
				}
			}
		}
		// -m imports need the repo root as cwd, wherever the binary started.
		plotCmd := exec.Command(s.Python, "-m", "pandachip.autoplot", dir)
		plotCmd.Dir = s.Root
		out, err := plotCmd.Output()
		if err == nil {
			for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
				if line != "" && !seen[line] {
					plots = append(plots, line)
				}
			}
		}
	}

	var artifacts []string
	for _, pat := range []string{"*.sch", "*.sym", "*.spice", "*.png", "*.raw", "sim/*.raw", "sim/*.log", "uploads/*", "*.md", "exp/*", "context/refs/*"} {
		matches, _ := filepath.Glob(filepath.Join(dir, pat))
		for _, mth := range matches {
			rel, _ := filepath.Rel(dir, mth)
			if rel == "task.md" {
				continue
			}
			artifacts = append(artifacts, rel)
		}
	}
	sort.Strings(artifacts)

	logTail := ""
	if data, err := os.ReadFile(filepath.Join(dir, "agent.log")); err == nil {
		if len(data) > 4000 {
			data = data[len(data)-4000:]
		}
		logTail = string(data)
	}

	// Report status: is the PDF already built and up to date with the outcome?
	reportReady := false
	if pInfo, err := os.Stat(filepath.Join(dir, "report", "report_"+id+".pdf")); err == nil {
		oInfo, oErr := os.Stat(filepath.Join(dir, "outcome.json"))
		reportReady = oErr != nil || pInfo.ModTime().After(oInfo.ModTime())
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"run_id":    id,
		"state":     state,
		"prompt":    m.Prompt,
		"created":   m.Created,
		"model":     m.Model,
		"pdk":       m.PDK,
		"outcome":   outcome,
		"phases":    phases,
		"plots":     plots,
		"artifacts": artifacts,
		"log_tail":  logTail,
		"report":    reportReady,
	})
}

// handlePause freezes / thaws a running agent with SIGSTOP / SIGCONT.
// Pausing mid-LLM-call is safe: the orchestrator's checkpoint-retry loop
// treats the timed-out request as transient and resumes on SIGCONT.
func (s *Server) handlePause(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST only"})
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/pause/")
	dir, ok := s.runDir(id)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no such run"})
		return
	}
	var m meta
	if !readJSON(filepath.Join(dir, "meta.json"), &m) || m.PID <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "run has no live process"})
		return
	}
	if _, err := os.Stat(fmt.Sprintf("/proc/%d", m.PID)); err != nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "process already exited"})
		return
	}
	marker := filepath.Join(dir, ".paused")
	if _, err := os.Stat(marker); err == nil { // paused -> continue
		if err := syscall.Kill(m.PID, syscall.SIGCONT); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		os.Remove(marker)
		writeJSON(w, http.StatusOK, map[string]interface{}{"ok": true, "state": "running"})
		return
	}
	if err := syscall.Kill(m.PID, syscall.SIGSTOP); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	os.WriteFile(marker, []byte(time.Now().Format(time.RFC3339)), 0o644)
	writeJSON(w, http.StatusOK, map[string]interface{}{"ok": true, "state": "paused"})
}

// handleSuggest returns AI fix suggestions for a run that needs review,
// generating them once with the run's own model (cached in
// suggestions.json until the outcome changes).
func (s *Server) handleSuggest(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/suggest/")
	if !runIDRe.MatchString(id) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad run id"})
		return
	}
	dir := filepath.Join(s.Designs, id)
	if _, err := os.Stat(dir); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no such run"})
		return
	}
	sugPath := filepath.Join(dir, "suggestions.json")
	if sInfo, err := os.Stat(sugPath); err == nil {
		oInfo, oErr := os.Stat(filepath.Join(dir, "outcome.json"))
		if oErr != nil || sInfo.ModTime().After(oInfo.ModTime()) {
			if data, rErr := os.ReadFile(sugPath); rErr == nil {
				w.Header().Set("Content-Type", "application/json")
				w.Write(data)
				return
			}
		}
	}
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, s.Python, "-m", "pandachip.suggest", dir)
	cmd.Dir = s.Root
	out, err := cmd.Output()
	if err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "suggestion generation failed: " + err.Error()})
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(out)
}

// handleReport generates (or returns) the IEEE-style PDF report for a run
// and serves it inline. Regenerates when the outcome is newer than the PDF.
func (s *Server) handleReport(w http.ResponseWriter, r *http.Request) {
	id := strings.TrimPrefix(r.URL.Path, "/api/report/")
	if !runIDRe.MatchString(id) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad run id"})
		return
	}
	dir := filepath.Join(s.Designs, id)
	if _, err := os.Stat(dir); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no such run"})
		return
	}
	pdf := filepath.Join(dir, "report", "report_"+id+".pdf")
	fresh := false
	if pInfo, err := os.Stat(pdf); err == nil {
		oInfo, oErr := os.Stat(filepath.Join(dir, "outcome.json"))
		fresh = oErr != nil || pInfo.ModTime().After(oInfo.ModTime())
	}
	if !fresh {
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Minute)
		defer cancel()
		cmd := exec.CommandContext(ctx, s.Python, "-m", "pandachip.report", dir)
		cmd.Dir = s.Root
		if out, err := cmd.CombinedOutput(); err != nil {
			writeJSON(w, http.StatusBadGateway, map[string]string{
				"error": "report generation failed: " + err.Error(),
				"log":   string(out)})
			return
		}
	}
	if _, err := os.Stat(pdf); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": "no PDF produced"})
		return
	}
	w.Header().Set("Content-Type", "application/pdf")
	w.Header().Set("Content-Disposition", "inline; filename=\"report_"+id+".pdf\"")
	http.ServeFile(w, r, pdf)
}

func (s *Server) handleArtifact(w http.ResponseWriter, r *http.Request) {
	rest := strings.TrimPrefix(r.URL.Path, "/api/artifact/")
	parts := strings.SplitN(rest, "/", 2)
	if len(parts) != 2 {
		http.NotFound(w, r)
		return
	}
	dir, ok := s.runDir(parts[0])
	if !ok {
		http.NotFound(w, r)
		return
	}
	full := filepath.Join(dir, filepath.Clean("/"+parts[1]))
	if !strings.HasPrefix(full, dir+string(os.PathSeparator)) {
		http.NotFound(w, r)
		return
	}
	if strings.HasSuffix(full, ".sch") || strings.HasSuffix(full, ".spice") ||
		strings.HasSuffix(full, ".log") {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	}
	http.ServeFile(w, r, full)
}


// handleResume relaunches the agent for an existing run workspace.
func (s *Server) handleResume(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST only"})
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/resume/")
	dir, ok := s.runDir(id)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no such run"})
		return
	}
	state, m, _ := s.runState(dir)
	if state == "running" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "already running"})
		return
	}
	taskFile := filepath.Join(dir, "task.md")
	if _, err := os.Stat(taskFile); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "no task.md in workspace"})
		return
	}
	os.Remove(filepath.Join(dir, "outcome.json"))
	logFile, err := os.OpenFile(filepath.Join(dir, "agent.log"),
		os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	cmd := exec.Command(s.Python, "-m", "pandachip.orchestra",
		"--task-file", taskFile, "--workdir", dir,
		"--model", m.Model, "--resume")
	cmd.Dir = s.Root
	cmd.Env = append(os.Environ(), "PANDACHIP_PDK="+m.PDK)
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	if err := cmd.Start(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	m.PID = cmd.Process.Pid
	mj, _ := json.Marshal(m)
	os.WriteFile(filepath.Join(dir, "meta.json"), mj, 0o644)
	go cmd.Wait()
	writeJSON(w, http.StatusOK, map[string]interface{}{"ok": true, "pid": m.PID, "resumed": true})
}

func (s *Server) handleXschem(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "POST only"})
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/xschem/")
	dir, ok := s.runDir(id)
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no such run"})
		return
	}
	var body struct {
		File string `json:"file"`
	}
	data, _ := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<16))
	json.Unmarshal(data, &body)

	target := ""
	if body.File != "" {
		clean := filepath.Clean(body.File)
		if !filepath.IsAbs(clean) && !strings.HasPrefix(clean, "..") &&
			strings.HasSuffix(clean, ".sch") {
			cand := filepath.Join(dir, clean)
			if _, err := os.Stat(cand); err == nil {
				target = cand
			}
		}
	}
	if target == "" {
		matches, _ := filepath.Glob(filepath.Join(dir, "*.sch"))
		// Prefer the main testbench (*_tb.sch); otherwise newest schematic.
		var tbs []string
		for _, m := range matches {
			if strings.HasSuffix(m, "_tb.sch") {
				tbs = append(tbs, m)
			}
		}
		pick := tbs
		if len(pick) == 0 {
			pick = matches
		}
		sort.Slice(pick, func(i, j int) bool {
			ii, _ := os.Stat(pick[i])
			jj, _ := os.Stat(pick[j])
			if ii == nil || jj == nil {
				return pick[i] < pick[j]
			}
			return ii.ModTime().After(jj.ModTime())
		})
		if len(pick) > 0 {
			target = pick[0]
		}
	}
	if target == "" {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "no schematic"})
		return
	}
	cmd := exec.Command(filepath.Join(s.Root, "scripts", "xschem_gui.sh"), target)
	cmd.Dir = s.Root
	if err := cmd.Start(); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	go cmd.Wait()
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"ok": true, "opened": filepath.Base(target)})
}

func writeJSON(w http.ResponseWriter, code int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}
