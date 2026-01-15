#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import socket
import time
import select
from datetime import date
from multiprocessing import shared_memory, resource_tracker

# Constantes pour l'affichage coloré des logs
ERROR = '\033[91m'    # Rouge pour les erreurs
SUCCESS = '\033[92m'  # Vert pour les succès
WARNING = '\033[93m'  # Jaune pour les avertissements
RESET = '\033[0m'     # Réinitialisation de la couleur

# Contantes configuration réseau
HOST = '127.0.0.1'   # Adresse IP localhost
PORT = 2223          # Port pour la logique métier (client)
HEALTH_PORT = 2225   # Port pour le watchdog

# Tubes nommés pour communication avec le dispatcher
TUBE_D_W = "/tmp/dwtube1"  # Dispatcher -> Worker
TUBE_W_D = "/tmp/wdtube1"  # Worker -> Dispatcher

WORKER_PID_FILE = "/tmp/worker.pid"  # Fichier PID du Worker
SHM_NAME = 'shared_memory'           # Nom de la mémoire partagée

FIFO_WAIT_TIMEOUT = 10      # secondes max d'attente pour les FIFOs
FIFO_RETRY_DELAY = 0.2      # secondes entre essais si les FIFOs ne sont pas encore prêtes

# Flag global d'arrêt demandé par signal
shutdown_requested = False

# Gestion des signaux (CTRL + C, TERM)
def handle_sigint(signum, frame):
    """Gestion des signaux SIGINT et SIGTERM"""
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[WORKER] - INFO : Signal d'arrêt reçu (PID: {os.getpid()}){RESET}")
        shutdown_requested = True

# Configuration des signaux
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def setup_network():
    """
    Configure et retourne le socket réseau pour la logique métier
    """
    try:
        worker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        worker_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        worker_socket.bind((HOST, PORT))
        worker_socket.listen()
        print(f"[WORKER] - INFO : Worker en écoute sur {HOST}:{PORT} (logique métier)")
        return worker_socket
    except OSError as exception:
        print(f"{ERROR}[WORKER] - ERREUR : Erreur socket métier : {exception}{RESET}")
        return None

def setup_health_socket():
    """
    Configure et retourne le socket réseau pour les health checks
    """
    try:
        health_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        health_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        health_socket.bind((HOST, HEALTH_PORT))
        health_socket.listen()
        print(f"[WORKER] - INFO : Worker en écoute sur {HOST}:{HEALTH_PORT} (health checks)")
        return health_socket
    except OSError as exception:
        print(f"{ERROR}[WORKER] - ERREUR : Erreur socket health : {exception}{RESET}")
        return None

def access_shared_memory():
    """
    Accède au segment de mémoire partagée et affiche les 10 premiers octets
    """
    try:
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        print('[WORKER] - INFO : Mémoire partagée :', shm_segment.name)
        return shm_segment
    except Exception as exception:
        print(f"{ERROR}[WORKER] - ERREUR : Erreur mémoire : {exception}{RESET}")
        return None

def cleanup_resources(shm_segment, worker_socket, health_socket):
    """
    Nettoie les ressources allouées au Worker (mémoire, sockets, PID)
    """
    if shm_segment:
        try:
            shm_segment.close()
            print('[WORKER] - INFO : Mémoire fermée')
        except Exception as e:
            print(f"{ERROR}[WORKER] - ERREUR : {e}{RESET}")

    # Fermeture des sockets (logique métier et health)
    for sock, name in [(worker_socket, "métier"), (health_socket, "health")]:
        if sock:
            try:
                sock.close()
                print(f"[WORKER] - INFO : Socket {name} fermée")
            except Exception as e:
                print(f"{WARNING}[WORKER] - WARNING : Impossible de fermer socket {name} : {e}{RESET}")

    # Suppression du fichier PID
    try:
        if os.path.exists(WORKER_PID_FILE):
            os.unlink(WORKER_PID_FILE)
            print(f"{SUCCESS}[WORKER] - INFO : Fichier PID supprimé{RESET}")
    except Exception as e:
        print(f"{WARNING}[WORKER] - WARNING : Impossible de supprimer le fichier PID : {e}{RESET}")

def open_named_pipes_worker():
    """
    Attend que les FIFOs existent puis les ouvre sans deadlock.
    Timeout pour éviter un blocage infini si le dispatcher ne démarre pas.
    """
    start_time = time.time()
    while True:
        if os.path.exists(TUBE_D_W) and os.path.exists(TUBE_W_D):
            try:
                # Ouverture des FIFOs en lecture/écriture
                fd_in = os.open(TUBE_D_W, os.O_RDWR)
                fd_out = os.open(TUBE_W_D, os.O_RDWR)
                fifo_in = os.fdopen(fd_in, "r", buffering=1)
                fifo_out = os.fdopen(fd_out, "w", buffering=1)
                print("[WORKER] - INFO : FIFOs ouvertes avec succès")
                return fifo_in, fifo_out
            except OSError as e:
                print(f"{WARNING}[WORKER] - WARNING : FIFOs présentes mais non ouvrables ({e}), retry...{RESET}")
        # Timeout global pour éviter blocage
        if time.time() - start_time > FIFO_WAIT_TIMEOUT:
            raise TimeoutError("Timeout en attente de création des FIFOs")
        time.sleep(FIFO_RETRY_DELAY)

def handle_watchdog_connection(watchdog_connection):
    """
    Gère les requêtes health check du watchdog sur une connexion persistante
    """
    try:
        watchdog_connection.settimeout(0.1)
        try:
            data = watchdog_connection.recv(1024)
            if not data:
                print(f"{WARNING}[WORKER] - INFO : Watchdog a fermé la connexion{RESET}")
                return False
            print(f"[WORKER] - INFO : Health check reçu : {data!r}")
            if data == b'watchdog-health-test':
                try:
                    watchdog_connection.send(b'worker-alive')
                except OSError as e:
                    print(f"{ERROR}[WORKER] - ERROR : Envoi watchdog impossible : {e}{RESET}")
                    return False
                return True
        except socket.timeout:
            # Timeout court => pas de données reçues, communication OK
            return True
        except OSError as e:
            print(f"{ERROR}[WORKER] - ERROR : Erreur lecture watchdog : {e}{RESET}")
            return False
    except Exception as e:
        print(f"{ERROR}[WORKER] - ERROR : Erreur gestion watchdog : {e}{RESET}")
        return False

def main():
    """
    Programme principal
    """
    global shutdown_requested

    worker_socket = None
    health_socket = None
    watchdog_connection = None
    shm_segment = None
    fifo_in = None
    fifo_out = None

    # Écrire le PID dans un fichier
    try:
        with open(WORKER_PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f"{ERROR}[WORKER] - ERREUR : Impossible d'écrire le PID : {e}{RESET}")
        return 1

    try:
        # Configuration des sockets
        worker_socket = setup_network()
        if not worker_socket:
            return 1
        health_socket = setup_health_socket()
        if not health_socket:
            return 1

        print('[WORKER] - INFO : Début processus 2')

        # Mémoire partagée
        shm_segment = access_shared_memory()
        if not shm_segment:
            return 1

        # Ouvrir les FIFOs (canal principal Dispatcher <-> Worker)
        try:
            fifo_in, fifo_out = open_named_pipes_worker()
        except TimeoutError as e:
            print(f"{ERROR}[WORKER] - ERREUR : {e}{RESET}")
            return 1
        print(f"{SUCCESS}[WORKER] - SUCCESS : Worker prêt (FIFO + health){RESET}")

        # Boucle principale de traitement
        while not shutdown_requested:
            # Préparer liste des sources de lecture
            read_list = [fifo_in, health_socket]
            if watchdog_connection:
                read_list.append(watchdog_connection)
            try:
                ready, _, _ = select.select(read_list, [], [], 1.0)
            except (OSError, ValueError) as e:
                print(f"{ERROR}[WORKER] - ERREUR : select() échoué : {e}{RESET}")
                break
            if not ready:
                continue

            # Accept watchdog
            if health_socket in ready:
                try:
                    watchdog_connection, watchdog_addr = health_socket.accept()
                    print(f"{SUCCESS}[WORKER] - SUCCESS : Connexion watchdog établie depuis {watchdog_addr}{RESET}")
                except OSError as e:
                    if not shutdown_requested:
                        print(f"{ERROR}[WORKER] - ERREUR : Erreur accept health : {e}{RESET}")

            # Données watchdog
            if watchdog_connection and watchdog_connection in ready:
                if not handle_watchdog_connection(watchdog_connection):
                    print(f"{WARNING}[WORKER] - INFO : Fermeture connexion watchdog{RESET}")
                    try:
                        watchdog_connection.close()
                    except Exception:
                        pass
                    watchdog_connection = None

            # Données FIFO (commande dispatcher)
            if fifo_in in ready:
                try:
                    msg = fifo_in.readline()
                    if msg == "":
                        print("[WORKER] - WARNING : FIFO dispatcher fermée")
                        shutdown_requested = True
                        break
                    msg = msg.strip()
                except Exception as e:
                    print(f"{ERROR}[WORKER] - ERREUR : lecture FIFO impossible : {e}{RESET}")
                    shutdown_requested = True
                    break

                if not msg:
                    continue

                print(f"[WORKER] - Reçu du dispatcher : {msg}")

                # Gestion commandes spéciales
                if msg == "STOP":
                    print(f"{WARNING}[WORKER] - INFO : Arrêt demandé{RESET}")
                    break

                # Réponse standard selon commande
                client_id = "client123"
                if msg == "ping":
                    reply = "pong"
                elif msg == "pong":
                    reply = "ping"
                elif msg == "date":
                    reply = date.today().strftime("%d/%m/%Y")
                elif msg == "bonjour":
                    reply = "salut, comment ca va ?"
                else:
                    reply = "Instruction non comprise"

                # Envoi réponse via FIFO
                try:
                    fifo_out.write(reply + "\n")
                    fifo_out.flush()
                except BrokenPipeError:
                    print("[WORKER] - ERROR : FIFO cassée")
                    shutdown_requested = True
                except Exception as e:
                    print(f"[WORKER] - ERROR : écriture FIFO impossible : {e}{RESET}")
                    shutdown_requested = True

        print(f"{SUCCESS}[WORKER] - INFO : Sortie de la boucle principale{RESET}")

    except Exception as exception:
        # Catch global pour éviter plantage
        print(f"{ERROR}[WORKER] - ERREUR : Erreur inattendue : {exception}{RESET}")
        return 1

    finally:
        # Fermeture des sockets watchdog
        if watchdog_connection:
            try:
                watchdog_connection.close()
            except Exception:
                pass
        # Fermeture des FIFOs
        for fifo in (fifo_in, fifo_out):
            if fifo:
                try:
                    fifo.close()
                except Exception:
                    pass
        # Nettoyage global
        cleanup_resources(shm_segment, worker_socket, health_socket)

    print(f"{SUCCESS}[WORKER] - SUCCESS : Worker terminé{RESET}")
    return 0

if __name__ == "__main__":
    exit(main())

