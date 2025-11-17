#! /usr/bin/env python3
# _*_ coding: utf8 _*_

import os
import signal
import socket
import sys
import time
from multiprocessing import Process, shared_memory

# --- Constantes ---
ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

HOST = '127.0.0.1'
PORT = 2222

TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"
DISPATCHER_PID_FILE = "/tmp/dispatcher.pid"

SHM_NAME = 'shared_memory'
SHM_SIZE = 10
INITIAL_DATA = bytearray([74, 73, 72, 71, 70, 69, 68, 67, 66, 65])

shutdown_requested = False

# --- Gestion des signaux ---
def handle_sigusr1(sig, frame):
    os.kill(os.getppid(), signal.SIGUSR2)

def handle_sigint(sig, frame):
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[Dispatcher] INFO : Signal d'arrêt reçu, arrêt en cours...{RESET}")
        shutdown_requested = True

signal.signal(signal.SIGUSR1, handle_sigusr1)
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

# --- Fonctions utilitaires ---
def setup_named_pipes():
    for tube in (TUBE_D_W, TUBE_W_D):
        if not os.path.exists(tube):
            os.mkfifo(tube, 0o600)
    print(f"[Dispatcher] INFO : Tubes nommés configurés")

def setup_network():
    try:
        dispatcher_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dispatcher_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dispatcher_socket.bind((HOST, PORT))
        dispatcher_socket.listen(1)
        print(f"[Dispatcher] INFO : Dispatcher en écoute sur {HOST}:{PORT}")
        return dispatcher_socket
    except OSError as exception:
        print(f"{ERROR}[Dispatcher] ERREUR : Port {PORT} impossible à lier : {exception}{RESET}")
        return None

def setup_shared_memory():
    try:
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
        shm_segment.buf[:SHM_SIZE] = INITIAL_DATA
        print(f"[Dispatcher] INFO : Segment mémoire partagée créé ({SHM_NAME}, {SHM_SIZE} octets)")
        return shm_segment
    except Exception as exception:
        print(f"{ERROR}[Dispatcher] ERREUR : Mémoire partagée impossible : {exception}{RESET}")
        return None

def start_worker_process():
    from worker import main as worker_main
    worker_process = Process(target=worker_main)
    worker_process.start()
    print(f"{SUCCESS}[Dispatcher] SUCCESS : Worker démarré (PID: {worker_process.pid}){RESET}")
    return worker_process

def cleanup_resources(shm_segment=None, dispatcher_socket=None, worker_process=None):
    print("[Dispatcher] INFO : Nettoyage des ressources...")
    if worker_process and worker_process.is_alive():
        print("[Dispatcher] INFO : Arrêt du worker...")
        worker_process.terminate()
        worker_process.join(timeout=3)
        if worker_process.is_alive():
            worker_process.kill()
    if shm_segment:
        try:
            shm_segment.close()
            shm_segment.unlink()
        except:
            pass
    if dispatcher_socket:
        try:
            dispatcher_socket.close()
        except:
            pass
    for tube in (TUBE_D_W, TUBE_W_D):
        if os.path.exists(tube):
            os.unlink(tube)
    if os.path.exists(DISPATCHER_PID_FILE):
        os.unlink(DISPATCHER_PID_FILE)

# --- Fonction principale ---
def main():
    global shutdown_requested
    dispatcher_socket = None
    shm_segment = None
    worker_process = None
    fifo_dw = fifo_wd = None

    # Écrire PID
    with open(DISPATCHER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    setup_named_pipes()

    try:
        dispatcher_socket = setup_network()
        if not dispatcher_socket or shutdown_requested:
            return 1

        shm_segment = setup_shared_memory()
        if not shm_segment or shutdown_requested:
            return 1

        worker_process = start_worker_process()
        if shutdown_requested:
            return 1

        # --- Ouverture des tubes FIFO ---
        fifo_dw = open(TUBE_D_W, "w")
        fifo_wd = open(TUBE_W_D, "r")

        print(f"[Dispatcher] INFO : En attente de connexion client (socket {HOST}:{PORT})...")
        client_socket, client_addr = dispatcher_socket.accept()
        print(f"[Dispatcher] INFO : Client connecté : {client_addr}")

        # --- Boucle principale ---
        while not shutdown_requested:
            try:
                cmd = client_socket.recv(1024).decode().strip()
                if not cmd:
                    continue
                print(f"[Dispatcher] Commande reçue du client : {cmd}")

                if cmd == "QUIT":
                    client_socket.sendall(b"Au revoir\n")
                    break

                # Envoyer la commande au worker
                fifo_dw.write(cmd + "\n")
                fifo_dw.flush()

                # Lire la réponse
                reply = fifo_wd.readline().strip()
                print(f"[Dispatcher] Réponse worker : {reply}")

                # Envoyer au client
                client_socket.sendall((reply + "\n").encode())

            except (ConnectionResetError, BrokenPipeError):
                print(f"{WARNING}[Dispatcher] WARNING : Client déconnecté{RESET}")
                break
            except Exception as e:
                print(f"{ERROR}[Dispatcher] ERREUR inattendue : {e}{RESET}")
                break

    except KeyboardInterrupt:
        print(f"\n{WARNING}[Dispatcher] INFO : Interruption clavier détectée{RESET}")
        shutdown_requested = True
    finally:
        if fifo_dw:
            fifo_dw.close()
        if fifo_wd:
            fifo_wd.close()
        if dispatcher_socket:
            dispatcher_socket.close()
        if worker_process and worker_process.is_alive():
            try:
                fifo_dw = open(TUBE_D_W, "w")
                fifo_dw.write("STOP\n")
                fifo_dw.flush()
                fifo_dw.close()
            except:
                pass
        cleanup_resources(shm_segment, dispatcher_socket, worker_process)

    print(f"{SUCCESS}[Dispatcher] INFO : Dispatcher arrêté correctement{RESET}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
