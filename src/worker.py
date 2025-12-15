#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import socket
import time
from multiprocessing import shared_memory

# Constantes affichage des logs
RED = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

# Contantes configuration réseau
HOST = '127.0.0.1'   # Adresse IP localhost
PORT = 2223          # Port pour la logique métier (client)
HEALTH_PORT = 2225   # Port pour le watchdog

# Serveur secondaire
SECONDARY_HOST = '127.0.0.1'
SECONDARY_PORT = 3333  # port du serveur secondaire

# Tubes nommés
TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"

WORKER_PID_FILE = "/tmp/worker.pid"
SHM_NAME = 'shared_memory'

shutdown_requested = False

# Gestion des signaux (CTRL + C)
def handle_sigint(sig, frame):
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[Worker] - INFO : Signal d'arrêt reçu (PID: {os.getpid()}){RESET}")
        shutdown_requested = True

# Configuration des signaux
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def setup_network():
    """Configure et retourne le socket réseau pour la logique métier"""
    try:
        worker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        worker_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        worker_socket.bind((HOST, PORT))
        worker_socket.listen()
        print(f"[Worker] - INFO : Worker en écoute sur {HOST}:{PORT} (logique métier)")
        return worker_socket
    except OSError as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur socket métier : {exception}{RESET}")
        return None

def setup_health_socket():
    """Configure et retourne le socket réseau pour les health checks"""
    try:
        health_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        health_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        health_socket.bind((HOST, HEALTH_PORT))
        health_socket.listen()
        print(f"[Worker] - INFO : Worker en écoute sur {HOST}:{HEALTH_PORT} (health checks)")
        return health_socket
    except OSError as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur socket health : {exception}{RESET}")
        return None

def access_shared_memory():
    """Accède au segment de mémoire partagée"""
    try:
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        print('[Worker] - INFO : Mémoire partagée :', shm_segment.name)
        print('[Worker] - INFO : Contenu (10 octets) :', bytes(shm_segment.buf[:10]))
        return shm_segment
    except Exception as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur mémoire : {exception}{RESET}")
        return None

def cleanup_resources(shm_segment, worker_socket, health_socket):
    """Nettoie les ressources allouées au Worker"""
    if shm_segment:
        try:
            shm_segment.close()
            print('[Worker] - INFO : Mémoire fermée')
        except Exception as e:
            print(f"{RED}[Worker] - ERREUR : {e}{RESET}")

    # Fermeture des sockets
    for sock, name in [(worker_socket, "métier"), (health_socket, "health")]:
        if sock:
            try:
                sock.close()
                print(f"[Worker] - INFO : Socket {name} fermée")
            except:
                pass

    try:
        if os.path.exists(WORKER_PID_FILE):
            os.unlink(WORKER_PID_FILE)
    except:
        pass

def delegate_to_secondary(command, client_id):
    """Envoie la commande au serveur secondaire et retourne la réponse"""
    try:
        with socket.create_connection((SECONDARY_HOST, SECONDARY_PORT), timeout=5) as sock:
            payload = f"{client_id}:{command}"
            sock.sendall(payload.encode())
            reply = sock.recv(1024).decode().strip()
            return reply
    except Exception as e:
        print(f"{WARNING}[Worker] WARNING : Échec communication serveur secondaire : {e}{RESET}")
        return f"DELEGATION_FAILED:{command}"

def handle_fifo_communication():
    global shutdown_requested
    print(f"{SUCCESS}[Worker] SUCCESS : Worker prêt{RESET}")

    fifo_in = fifo_out = None
    try:
        # Attente tubes
        attempts = 10
        for _ in range(attempts):
            if shutdown_requested:
                return
            try:
                fifo_in = open(TUBE_D_W, "r")
                fifo_out = open(TUBE_W_D, "w")
                break
            except FileNotFoundError:
                time.sleep(0.5)
        else:
            print(f"{RED}[Worker] ERREUR : Tubes non disponibles{RESET}")
            return

        while not shutdown_requested:
            import select
            ready, _, _ = select.select([fifo_in], [], [], 1.0)
            if ready:
                msg = fifo_in.readline().strip()
                if not msg:
                    continue
                print(f"[Worker] Reçu du dispatcher : {msg}")

                if msg == "STOP":
                    print(f"{WARNING}[Worker] INFO : Arrêt demandé{RESET}")
                    break

                # Exemple de délégation : client_id simulé
                client_id = "client123"
                if msg == "ping":
                    reply = "pong"
                else:
                    reply = delegate_to_secondary(msg, client_id)

                if msg == "Bonjour":
                    reply = "Salut, comment ca va ?"
                else:
                    reply = delegate_to_secondary(msg, client_id)

                try:
                    fifo_out.write(reply + "\n")
                    fifo_out.flush()
                except (BrokenPipeError, OSError):
                    if shutdown_requested:
                        break
                    print(f"{WARNING}[Worker] WARNING : Dispatcher déconnecté{RESET}")
                    break

    except Exception as e:
        if not shutdown_requested:
            print(f"{RED}[Worker] ERREUR : Communication FIFO : {e}{RESET}")
    finally:
        for fifo in (fifo_in, fifo_out):
            if fifo:
                try:
                    fifo.close()
                except:
                    pass
        print("[Worker] INFO : Worker terminé")


def handle_watchdog_connection(watchdog_connection):
    """Gère les requêtes health check du watchdog sur une connexion persistante"""
    try:
        # Timeout court (100ms) pour ne pas bloquer la boucle principale
        watchdog_connection.settimeout(0.1)

        try:
            data = watchdog_connection.recv(1024)

            if not data:
                # Connexion fermée par le watchdog
                print(f"{WARNING}[Worker] - INFO : Watchdog a fermé la connexion{RESET}")
                return False

            print(f"[Worker] - INFO : Health check reçu : {data!r}")

            if data == b'watchdog-health-test':
                watchdog_connection.send(b'worker-alive')
                return True

        except socket.timeout:
            # Etant donné la durée très courte du timeout (100ms) pour ne pas bloquer la boucle principale, même si aucune
            # donnée n'est reçue, cela n'indique pas une coupure de communication pour autant
            return True
        except OSError as e:
            print(f"{RED}[Worker] - ERROR : Erreur lecture watchdog : {e}{RESET}")
            return False

    except Exception as e:
        print(f"{RED}[Worker] - ERROR : Erreur gestion watchdog : {e}{RESET}")
        return False

def main():
    global shutdown_requested

    worker_socket = None
    health_socket = None
    watchdog_connection = None
    shm_segment = None

    # Écrire PID
    with open(WORKER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    try:
        # Configuration
        worker_socket = setup_network()
        if not worker_socket:
            return 1

        health_socket = setup_health_socket()
        if not health_socket:
            return 1

        print('[Worker] - INFO : Début processus 2')

        shm_segment = access_shared_memory()
        if not shm_segment:
            return 1

        # Timeout pour accept() - permet de vérifier régulièrement shutdown_requested
        health_socket.settimeout(1.0)
        worker_socket.settimeout(1.0)

        print('[Worker] - INFO : En attente de connexions...')

        while not shutdown_requested:
            # Gérer les connexions watchdog
            if watchdog_connection is None:
                try:
                    watchdog_connection, watchdog_addr = health_socket.accept()
                    print(f"{SUCCESS}[Worker] - INFO : Connexion watchdog établie depuis {watchdog_addr}{RESET}")
                except socket.timeout:
                    pass
                except OSError as e:
                    if not shutdown_requested:
                        print(f"{RED}[Worker] - ERREUR : Erreur accept health : {e}{RESET}")
            else:
                if not handle_watchdog_connection(watchdog_connection):
                    print(f"{WARNING}[Worker] - INFO : Fermeture connexion watchdog{RESET}")
                    try:
                        watchdog_connection.close()
                    except:
                        pass
                    watchdog_connection = None

            # Gérer les connexions métier (clients normaux)
            try:
                client_connection, client_addr = worker_socket.accept()
                print(f"[Worker] - INFO : Connexion client depuis {client_addr}")

                # Ici tu peux traiter tes requêtes métier
                data = client_connection.recv(1024)
                print(f"[Worker] - INFO : Données client : {data!r}")

                # Exemple de réponse
                client_connection.send(b'worker-response')
                client_connection.close()

            except socket.timeout:
                # Pas de nouvelle connexion, continuer
                pass
            except OSError as e:
                if not shutdown_requested:
                    print(f"{RED}[Worker] - ERREUR : Erreur accept métier : {e}{RESET}")

        print(f"{SUCCESS}[Worker] - INFO : Sortie de la boucle principale{RESET}")
        print('[Worker] - INFO : Fin processus 2')

    except Exception as exception:
        print(f"{RED}[Worker] - ERREUR : Erreur inattendue : {exception}{RESET}")
        return 1

    finally:
        if watchdog_connection:
            try:
                watchdog_connection.close()
                print(f'{SUCCESS}[Worker] - SUCCESS : Socket du Watchdog correctement fermée.{RESET}')
            except:
                pass

        cleanup_resources(shm_segment, worker_socket, health_socket)

    print(f"{SUCCESS}[Worker] - SUCCESS : Worker terminé{RESET}")
    return 0

if __name__ == "__main__":
    exit(main())
