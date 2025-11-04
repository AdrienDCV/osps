#!/usr/bin/env python3
import os, time

tube_d_w = "/tmp/dwtube1"
tube_w_d = "/tmp/wdtube1"

# Création tubes si n'existent pas
for tube in (tube_d_w, tube_w_d):
    if not os.path.exists(tube):
        os.mkfifo(tube, 0o600)

print("Dispatcher prêt")

# Ouverture
fifo_out = open(tube_d_w, "w")
fifo_in  = open(tube_w_d, "r")

N = 5  # nombre de ping-pong

for i in range(N):
    print(f"Dispatcher → ping {i}")
    fifo_out.write("ping\n")
    fifo_out.flush()  # IMPORTANT !

    reply = fifo_in.readline().strip()
    print(f"Réponse worker : {reply}")

# envoie signal d'arrêt
fifo_out.write("STOP\n")
fifo_out.flush()
print("STOP envoyé au worker, fermeture...")

fifo_out.close()
fifo_in.close()

os.unlink(tube_d_w)
os.unlink(tube_w_d)

print("Dispatcher terminé")
