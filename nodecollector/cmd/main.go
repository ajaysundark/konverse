// node collector
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"github.com/shirou/gopsutil/v4/cpu"
	"github.com/shirou/gopsutil/v4/disk"
	"github.com/shirou/gopsutil/v4/mem"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	sampleInterval = time.Second
	historySeconds = 900 // 15m @ 1s
)

// NodeVmstat is a snapshot of the node's vmstat.
type NodeVmstat struct {
	TS          time.Time `json:"ts"`
	CPUPercent  float64   `json:"cpu_percent"`
	MemUsedMB   uint64    `json:"mem_used_mb"`
	MemTotalMB  uint64    `json:"mem_total_mb"`
	SwapUsedMB  uint64    `json:"swap_used_mb"`
	SwapTotalMB uint64    `json:"swap_total_mb"`
	Pswpin      uint64    `json:"pswpin"`
	Pswpout     uint64    `json:"pswpout"`
	Pgfault     uint64    `json:"pgfault"`
	Pgmajfault  uint64    `json:"pgmajfault"`
	Pgpgin      uint64    `json:"pgpgin"`
	Pgpgout     uint64    `json:"pgpgout"`
	DiskReadB   uint64    `json:"disk_read_b"`
	DiskWriteB  uint64    `json:"disk_write_b"`
}

// Event is a generic event from a tracer.
type Event map[string]interface{}

type ring[T any] struct {
	mu   sync.RWMutex
	data []T
}

// newRing creates a new ring buffer of type T with capacity for historySeconds elements.
func newRing[T any]() *ring[T] { return &ring[T]{data: make([]T, 0, historySeconds)} }
func (r *ring[T]) append(v T) {
	r.mu.Lock()
	if len(r.data) >= historySeconds {
		r.data = r.data[1:]
	}
	r.data = append(r.data, v)
	r.mu.Unlock()
}
func (r *ring[T]) snapshot() []T {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]T, len(r.data))
	copy(out, r.data)
	return out
}

var (
	nodeHist = newRing[NodeVmstat]()
	ctrEvts  = newRing[Event]()
)

type vmstatSnapshot struct{ vals map[string]uint64 }

func readProcVmstat() (vmstatSnapshot, error) {
	f, err := os.Open("/proc/vmstat")
	if err != nil {
		return vmstatSnapshot{}, err
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	m := map[string]uint64{}
	for sc.Scan() {
		fs := strings.Fields(sc.Text())
		if len(fs) != 2 {
			continue
		}
		if n, err := strconv.ParseUint(fs[1], 10, 64); err == nil {
			m[fs[0]] = n
		}
	}
	return vmstatSnapshot{vals: m}, sc.Err()
}

func deltaPerSec(prev, cur vmstatSnapshot, key string, secs float64) uint64 {
	if secs <= 0 {
		return 0
	}
	a, ok1 := prev.vals[key]
	b, ok2 := cur.vals[key]
	if !ok1 || !ok2 || b < a {
		return 0
	}
	return uint64(float64(b-a)/secs + 0.5)
}

func readUint(p string) (uint64, error) {
	b, err := os.ReadFile(p)
	if err != nil {
		return 0, err
	}
	s := strings.TrimSpace(string(b))
	if s == "max" {
		return 0, nil
	}
	return strconv.ParseUint(s, 10, 64)
}

func collectNodeLoop() {
	var prevVM vmstatSnapshot
	var havePrev bool

	for {
		start := time.Now()
		// CPU/mem/swap
		cpuPct, _ := cpu.Percent(0, false)
		vm, _ := mem.VirtualMemory()
		sw, _ := mem.SwapMemory()
		// Disk cumulative
		dio, _ := disk.IOCounters()
		var rb, wb uint64
		for _, v := range dio {
			rb += v.ReadBytes
			wb += v.WriteBytes
		}

		// /proc/vmstat deltas
		curVM, _ := readProcVmstat()
		var psin, psout, pf, pmf, pgin, pgout uint64
		if havePrev {
			secs := sampleInterval.Seconds()
			psin = deltaPerSec(prevVM, curVM, "pswpin", secs)
			psout = deltaPerSec(prevVM, curVM, "pswpout", secs)
			pf = deltaPerSec(prevVM, curVM, "pgfault", secs)
			pmf = deltaPerSec(prevVM, curVM, "pgmajfault", secs)
			pgin = deltaPerSec(prevVM, curVM, "pgpgin", secs)
			pgout = deltaPerSec(prevVM, curVM, "pgpgout", secs)
		}
		prevVM, havePrev = curVM, true

		nodeHist.append(NodeVmstat{
			TS:          time.Now(),
			CPUPercent:  cpuPct[0],
			MemUsedMB:   vm.Used / (1024 * 1024),
			MemTotalMB:  vm.Total / (1024 * 1024),
			SwapUsedMB:  sw.Used / (1024 * 1024),
			SwapTotalMB: sw.Total / (1024 * 1024),
			Pswpin:      psin, Pswpout: psout,
			Pgfault: pf, Pgmajfault: pmf, Pgpgin: pgin, Pgpgout: pgout,
			DiskReadB: rb, DiskWriteB: wb,
		})

		if rem := sampleInterval - time.Since(start); rem > 0 {
			time.Sleep(rem)
		}
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
}

func historyHandler(w http.ResponseWriter, r *http.Request) {
	scope := r.URL.Query().Get("scope")
	switch scope {
	case "", "events":
		writeJSON(w, ctrEvts.snapshot())
	case "stats":
		writeJSON(w, nodeHist.snapshot())
	default:
		http.Error(w, "invalid scope", 400)
	}
}

func streamHandler(w http.ResponseWriter, r *http.Request) {
	scope := r.URL.Query().Get("scope")
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "stream unsupported", 500)
		return
	}

	t := time.NewTicker(sampleInterval)
	defer t.Stop()
	for {
		select {
		case <-t.C:
			var payload []byte
			switch scope {
			case "", "events":
				data := ctrEvts.snapshot()
				if len(data) > 0 {
					payload, _ = json.Marshal(data[len(data)-1])
				}
			case "stats":
				data := nodeHist.snapshot()
				if len(data) > 0 {
					payload, _ = json.Marshal(data[len(data)-1])
				}
			default:
				continue
			}
			if len(payload) > 0 {
				fmt.Fprintf(w, "data: %s\n\n", string(payload))
				flusher.Flush()
			}
		case <-r.Context().Done():
			return
		}
	}
}

// eventIngestHandler ingests container lifecycle events from the ebpf tracers.
func eventIngestHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", 405)
		return
	}
	var ev Event
	if err := json.NewDecoder(r.Body).Decode(&ev); err != nil {
		http.Error(w, "bad json: "+err.Error(), 400)
		return
	}
	// Set timestamp if missing
	if _, ok := ev["ts"]; !ok {
		ev["ts"] = time.Now()
	}
	// Expect type
	if t, ok := ev["type"]; !ok {
		http.Error(w, "invalid node event ingestion: missing type", 400)
		return
	} else {
		log.Println("Rx event type: ", t)
	}
	ctrEvts.append(ev)
	w.WriteHeader(204)
}

func pingHandler(w http.ResponseWriter, r *http.Request) { w.Write([]byte("ok")) }

func main() {
	go collectNodeLoop()
	queryMux := http.NewServeMux()
	queryMux.HandleFunc("/history", historyHandler)
	queryMux.HandleFunc("/stream", streamHandler)
	queryMux.HandleFunc("/ping", pingHandler)

	ingestMux := http.NewServeMux()
	ingestMux.HandleFunc("/events", eventIngestHandler) // Ingest OOM, Lifecycle events

	go func() {
		log.Println("nodecollector ingest server listening on :3101")
		log.Fatal(http.ListenAndServe(":3101", ingestMux))
	}()

	log.Println("nodecollector query server listening on :3100")
	log.Fatal(http.ListenAndServe(":3100", queryMux))
}
