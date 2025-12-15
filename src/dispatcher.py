#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import socket
import sys
from multiprocessing import Process, shared_memory

# Constantes affichage des logs
ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

# Constantes configuration réseau
HOST = '127.0.0.1'   # Adresse IP localhost
PORT = 2222          # Port pour la logique métier
HEALTH_PORT = 2224   # Port pour le watchdog

TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"
DISPATCHER_PID_FILE = "/tmp/dispatcher.pid"

SHM_NAME = 'shared_memory'
SHM_SIZE = 10
INITIAL_DATA = bytearray([74, 73, 72, 71, 70, 69, 68, 67, 66, 65])

shutdown_requested = False

# Gestion des signaux (CTRL + C)
def handle_sigint(sig, frame):
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[Dispatcher] - INFO : Signal d'arrêt reçu (PID: {os.getpid()}){RESET}")
        shutdown_requested = True

# Configuration des signaux
signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def setup_named_pipes():
    for tube in (TUBE_D_W, TUBE_W_D):
        if not os.path.exists(tube):
            os.mkfifo(tube, 0o600)
    print(f"[Dispatcher] - INFO : Tubes nommés configurés")

def setup_network():
    """Configure et retourne le socket réseau pour la logique métier"""
    try:
        dispatcher_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dispatcher_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        dispatcher_socket.bind((HOST, PORT))
        dispatcher_socket.listen()
        print(f"[Dispatcher] - INFO : Dispatcher en écoute sur {HOST}:{PORT} (logique métier)")
        return dispatcher_socket
    except OSError as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur socket métier : {exception}{RESET}")
        return None

def setup_health_socket():
    """Configure et retourne le socket réseau pour les health checks"""
    try:
        health_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        health_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        health_socket.bind((HOST, HEALTH_PORT))
        health_socket.listen()
        print(f"[Dispatcher] - INFO : Dispatcher en écoute sur {HOST}:{HEALTH_PORT} (health checks)")
        return health_socket
    except OSError as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur socket health : {exception}{RESET}")
        return None

def setup_shared_memory():
    try:
        # Nettoyer du segment de mémoire partagée existante
        try:
            shm_segment = shared_memory.SharedMemory(name=SHM_NAME)
            print(f'{WARNING}[Dispatcher] - WARNING : Mémoire existante, nettoyage...{RESET}')
            shm_segment.close()
            shm_segment.unlink()

        except FileNotFoundError:
            # Si le fichier n'est pas trouvé, il n'y a rien à nettoyer
            pass

        # Création du nouveau segemnt de mémoire partagée
        shm_segment = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
        print('[Dispatcher] - INFO : Mémoire partagée créée :', shm_segment.name)
        shm_segment.buf[:SHM_SIZE] = INITIAL_DATA
        print(f"[Dispatcher] INFO : Segment mémoire partagée créé ({SHM_NAME}, {SHM_SIZE} octets)")
        return shm_segment
    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur mémoire partagée : {exception}{RESET}")
        return None

def start_worker_process():
    """Démarre le processus worker"""
    # Import de la fonction `main ` du Worker
    from worker import main as worker_main
    worker_process = Process(target=worker_main)
    # Démarrafe du Worker
    worker_process.start()
    print(f"{SUCCESS}[Dispatcher] - SUCCESS : Worker démarré (PID: {worker_process.pid}){RESET}")

    return worker_process

def cleanup_resources(shm_segment, dispatcher_socket, health_socket, worker_process=None):
    """Nettoie les ressources utilisées allouées au Dispatcher"""
    print("[Dispatcher] - INFO : Nettoyage des ressources...")

    # Arrêter le worker
    if worker_process and worker_process.is_alive():
        print("[Dispatcher] - INFO : Arrêt du worker...")
        worker_process.terminate()
        worker_process.join(timeout=3)
        if worker_process.is_alive():
            print(f"{WARNING}[Dispatcher] - WARNING : Arrêt forcé du worker{RESET}")
            worker_process.kill()
            worker_process.join()

    # Nettoyer mémoire
    if shm_segment:
        try:
            shm_segment.close()
            shm_segment.unlink()
            print("[Dispatcher] - INFO : Mémoire partagée nettoyée")
        except Exception as e:
            print(f"{ERROR}[Dispatcher] - ERREUR : Nettoyage mémoire : {e}{RESET}")

    # Fermer sockets
    for sock, name in [(dispatcher_socket, "métier"), (health_socket, "health")]:
        if sock:
            try:
                sock.close()
                print(f"[Dispatcher] - INFO : Socket {name} fermée")
            except:
                pass

    # Nettoyer fichiers temporaires
    for path in [DISPATCHER_PID_FILE, TUBE_D_W, TUBE_W_D]:
        try:
            if os.path.exists(path):
                os.unlink(path)
        except:
            pass
    for tube in (TUBE_D_W, TUBE_W_D):
        if os.path.exists(tube):
            os.unlink(tube)
    if os.path.exists(DISPATCHER_PID_FILE):
        os.unlink(DISPATCHER_PID_FILE)

def handle_watchdog_connection(watchdog_connection):
    """Gère les requêtes health check du watchdog sur une connexion persistante"""
    try:
        # Timeout court (100ms) pour ne pas bloquer la boucle principale
        watchdog_connection.settimeout(0.1)

        try:
            data = watchdog_connection.recv(1024)

            if not data:
                # Connexion fermée par le watchdog
                print(f"{WARNING}[Dispatcher] - INFO : Watchdog a fermé la connexion{RESET}")
                return False

            print(f"[Dispatcher] - INFO : Health check reçu : {data!r}")

            if data == b'watchdog-health-test':
                watchdog_connection.send(b'dispatcher-alive')
                return True

        except socket.timeout:
            # Etant donné la durée très courte du timeout (100ms) pour ne pas bloquer la boucle principale, même si aucune
            # donnée n'est reçue, cela n'indique pas une coupure de communication pour autant
            return True
        except OSError as e:
            print(f"{ERROR}[Dispatcher] - ERROR : Erreur lecture watchdog : {e}{RESET}")
            return False

    except Exception as e:
        print(f"{ERROR}[Dispatcher] - ERROR : Erreur gestion watchdog : {e}{RESET}")
        return False

def main():
    global shutdown_requested
    dispatcher_socket = None
    health_socket = None
    watchdog_connection = None
    shm_segment = None
    worker_process = None
    fifo_dw = fifo_wd = None

    # Écrire PID
    with open(DISPATCHER_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    setup_named_pipes()

    try:
        # Configuration
        dispatcher_socket = setup_network()
        if not dispatcher_socket:
            return 1

        health_socket = setup_health_socket()
        if not health_socket:
            return 1

        print('[Dispatcher] - INFO : Début processus 1')

        shm_segment = setup_shared_memory()
        if not shm_segment:
            return 1

        # Lancer worker
        worker_process = start_worker_process()

        # Timeout pour accept() - permet de vérifier régulièrement shutdown_requested
        health_socket.settimeout(1.0)
        dispatcher_socket.settimeout(1.0)

        print(f"[Dispatcher] INFO : En attente de connexion client (socket {HOST}:{PORT})...")
        client_socket, client_addr = dispatcher_socket.accept()
        print(f"[Dispatcher] INFO : Client connecté : {client_addr}")

        print('[Dispatcher] - INFO : En attente de connexions...')

        # Boucle principale
        while not shutdown_requested:
            # Vérifier si le worker est toujours vivant
            if not worker_process.is_alive():
                print(f"{WARNING}[Dispatcher] - WARNING : Worker arrêté, fin du dispatcher{RESET}")
                break

            # Gérer les connexions watchdog
            if watchdog_connection is None:
                try:
                    watchdog_connection, watchdog_addr = health_socket.accept()
                    print(f"{SUCCESS}[Dispatcher] - INFO : Connexion watchdog établie depuis {watchdog_addr}{RESET}")
                except socket.timeout:
                    pass
                except OSError as e:
                    if not shutdown_requested:
                        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur accept health : {e}{RESET}")
            else:
                if not handle_watchdog_connection(watchdog_connection):
                    print(f"{WARNING}[Dispatcher] - INFO : Fermeture connexion watchdog{RESET}")
                    try:
                        watchdog_connection.close()
                    except Exception as exception:
                        print(f"{ERROR}[Dispatcher] - ERROR : Une erreur est survenue à la fermeture de la connexion avec le Watchdog : {exception}{RESET}")
                    watchdog_connection = None

            # Gérer les connexions métier (client)
            try:
                client_connection, client_addr = dispatcher_socket.accept()
                print(f"[Dispatcher] - INFO : Connexion client depuis {client_addr}")

                # Traitement des requêtes du client
                data = client_connection.recv(1024)
                print(f"[Dispatcher] - INFO : Données client : {data!r}")

                # Dispatch de la requête au Worker ici...
                cmd = client_socket.recv(1024).decode().strip()
                if not cmd:
                    print(f"[Dispatcher] Commande reçue du client : {cmd}")
                    continue
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

            except socket.timeout:
                # Pas de nouvelle connexion, continuer
                pass
            except OSError as e:
                if not shutdown_requested:
                    print(f"{ERROR}[Dispatcher] - ERREUR : Erreur accept métier : {e}{RESET}")

            except (ConnectionResetError, BrokenPipeError):
                print(f"{WARNING}[Dispatcher] WARNING : Client déconnecté{RESET}")
                break

            except Exception as e:
                print(f"{ERROR}[Dispatcher] ERREUR inattendue : {e}{RESET}")
                break

    except Exception as exception:
        print(f"{ERROR}[Dispatcher] - ERREUR : Erreur inattendue : {exception}{RESET}")
        return 1

    # Adri
    finally:
        # Fermeture de la connexion au Watchdog
        if watchdog_connection:
            try:
                watchdog_connection.close()
                print(f'{SUCCESS}[Dispatcher] - SUCCESS : Socket du Watchdog correctement fermée.{RESET}')
            except:
                pass

        #Lorick
        if fifo_dw:
            fifo_dw.close()
        if fifo_wd:
            fifo_wd.close()
        if dispatcher_socket:
            dispatcher_socket.close()
        try:
            if worker_process and worker_process.is_alive():
                fifo_dw = open(TUBE_D_W, "w")
                fifo_dw.close()
                fifo_dw.flush()
                fifo_dw.write("STOP\n")
        except:
            pass

        # Nettoyage des ressources allouées
        cleanup_resources(shm_segment, dispatcher_socket, health_socket, worker_process)

    print(f"{SUCCESS}[Dispatcher] - INFO : Dispatcher arrêté correctement{RESET}")
    return 0

if __name__ == "__main__":
    # Programme principal
    sys.exit(main())
