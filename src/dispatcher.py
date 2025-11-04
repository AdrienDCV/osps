#!/usr/bin/env python3
import os, time, signal, subprocess

tube_d_w = "/tmp/dwtube1"
tube_w_d = "/tmp/wdtube1"

# --- Signaux ---
def handle_sigusr1(sig, frame):
    os.kill(os.getppid(), signal.SIGUSR2)
signal.signal(signal.SIGUSR1, handle_sigusr1)

with open("/tmp/dispatcher.pid", "w") as f:
    f.write(str(os.getpid()))

# --- Création tubes ---
for tube in (tube_d_w, tube_w_d):
    if not os.path.exists(tube):
        os.mkfifo(tube, 0o600)

# --- Lancer worker ---
worker = subprocess.Popen(["./worker.py"])

print("Dispatcher prêt")

fifo_out = open(tube_d_w, "w")
fifo_in  = open(tube_w_d, "r")

N = 5
for i in range(N):
    print(f"Dispatcher → ping {i}")
    fifo_out.write("ping\n"); fifo_out.flush()
    reply = fifo_in.readline().strip()
    print(f"Réponse worker : {reply}")

# Stop worker
fifo_out.write("STOP\n"); fifo_out.flush()

fifo_out.close()
fifo_in.close()
os.unlink(tube_d_w)
os.unlink(tube_w_d)
print("Dispatcher terminé")
