#!/usr/bin/env python3
import os, time, signal, subprocess

print("Watchdog démarré")

# Stockera les réponses des processus surveillés
alive = {"dispatcher": False, "worker": False}

# Handler pour recevoir SIGUSR2 (OK reçu)
def handler_sigusr2(signum, frame):
    # Quand un process répond, on le marque vivant.
    # On ne sait pas lequel a répondu
    for k in alive:
        alive[k] = True

signal.signal(signal.SIGUSR2, handler_sigusr2)

# Lancer le dispatcher (qui lancera le worker)
dispatcher = subprocess.Popen(["./dispatcher.py"])
time.sleep(1)  # laisser le temps au worker d'être lancé

# Récupérer PID du worker via un fichier (simplest cheat)
with open("/tmp/worker.pid") as f:
    worker_pid = int(f.read())

dispatcher_pid = dispatcher.pid

print(f"Watchdog surveille dispatcher PID={dispatcher_pid}, worker PID={worker_pid}")

while True:
    for proc, pid in [("dispatcher", dispatcher_pid), ("worker", worker_pid)]:

        # Vérifier si le process existe encore
        if not os.path.exists(f"/proc/{pid}") if os.name != "darwin" else os.system(f"kill -0 {pid} 2>/dev/null") != 0:
            print(f"[WATCHDOG] {proc} n'existe plus, redémarrage...")

            if proc == "dispatcher":
                dispatcher = subprocess.Popen(["./dispatcher.py"])
                time.sleep(1)
                dispatcher_pid = dispatcher.pid
                with open("/tmp/worker.pid") as f:
                    worker_pid = int(f.read())
            else:
                # worker disparu → laisser dispatcher le relancer
                print("[WATCHDOG] Worker disparu, le dispatcher le relancera")
            continue

        alive[proc] = False
        try:
            os.kill(pid, signal.SIGUSR1)
        except ProcessLookupError:
            print(f"[WATCHDOG] {proc} n'existe plus, redémarrage automatique")
            if proc == "dispatcher":
                dispatcher = subprocess.Popen(["./dispatcher.py"])
                time.sleep(1)
                dispatcher_pid = dispatcher.pid
                with open("/tmp/worker.pid") as f:
                    worker_pid = int(f.read())
            continue

        time.sleep(1)

        if not alive[proc]:
            print(f"[WATCHDOG] {proc} figé → kill")
            os.kill(pid, signal.SIGKILL)

            if proc == "dispatcher":
                print("[WATCHDOG] Relance dispatcher")
                dispatcher = subprocess.Popen(["./dispatcher.py"])
                time.sleep(1)
                dispatcher_pid = dispatcher.pid
                with open("/tmp/worker.pid") as f:
                    worker_pid = int(f.read())
            else:
                print("[WATCHDOG] Laisser dispatcher relancer worker")
    print("Sleep 10s")
    time.sleep(10)

