#!/usr/bin/env python3
import os, signal

tube_d_w = "/tmp/dwtube1"
tube_w_d = "/tmp/wdtube1"

# --- Signaux ---
def handle_sigusr1(sig, frame):
    os.kill(os.getppid(), signal.SIGUSR2)
signal.signal(signal.SIGUSR1, handle_sigusr1)

# écrire PID (pour watchdog)
with open("/tmp/worker.pid", "w") as f:
    f.write(str(os.getpid()))

print("Worker prêt")

fifo_in  = open(tube_d_w, "r")
fifo_out = open(tube_w_d, "w")

while True:
    msg = fifo_in.readline().strip()
    if msg == "": continue

    print(f"Worker reçoit : {msg}")

    if msg == "STOP":
        print("Worker : arrêt demandé")
        break

    if msg == "ping":
        fifo_out.write("pong\n"); fifo_out.flush()

fifo_in.close()
fifo_out.close()
print("Worker terminé")
