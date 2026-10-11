// PandaChip web server (Go, stdlib only — same shape as chip-orchestra's
// orchestrator-service: cmd/ entrypoint + internal/ package).
package main

import (
	"flag"
	"log"
	"net/http"
	"os"
	"path/filepath"

	"pandachip/web/internal/server"
)

func main() {
	addr := flag.String("addr", ":8317", "listen address")
	root := flag.String("root", "", "PandaChip repo root (default: auto-detect)")
	flag.Parse()

	repoRoot := *root
	if repoRoot == "" {
		exe, err := os.Executable()
		if err == nil {
			// binary lives at <root>/web/pandachip-web
			repoRoot = filepath.Dir(filepath.Dir(exe))
		}
		if _, err := os.Stat(filepath.Join(repoRoot, "pandachip")); err != nil {
			cwd, _ := os.Getwd()
			repoRoot = cwd
		}
	}

	s := server.New(repoRoot)
	log.Printf("PandaChip web UI: http://localhost%s (root %s)", *addr, repoRoot)
	log.Fatal(http.ListenAndServe(*addr, s.Routes()))
}
