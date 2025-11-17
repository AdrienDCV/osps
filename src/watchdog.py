
# --- Constantes ---
# Couleurs pour les messages
import os
import signal
import socket
import sys
import time

ERROR = '\033[91m'
SUCCESS = '\033[92m'
WARNING = '\033[93m'
RESET = '\033[0m'

# Configuration réseau
HOST = '127.0.0.1'
DISPATCHER_PORT = 2222
WORKER_PORT = 2223

# Sockets du dispatcher et du worker
dispatcher_socket = None
worker_socket = None

# Variable globale pour gérer l'arrêt propre
shutdown_requested = False

# Variable globale pour le statut des processus
process_status = {
    "dispatcher": False,
    "worker": False
}

def handle_sigint(sig, frame):
    """Gestionnaire pour SIGINT (Ctrl+C)"""
    global shutdown_requested
    if not shutdown_requested:
        print(f"\n{WARNING}[WATCHDOG] - INFO : Signal d'arrêt reçu, arrêt en cours...{RESET}")
        shutdown_requested = True

signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

def connect_to_dispatcher_socket(dispatcher_socket):
    """
    Tente d'établir une connexion avec le dispatcher.
    Retourne la socket connectée (ou None en cas d'erreur).
    """
    if dispatcher_socket is not None:
        return dispatcher_socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, DISPATCHER_PORT))
        print(f'{SUCCESS}[WATCHDOG] - INFO  : Connexion au dispatcher établie.{RESET}')
        return s
    except OSError as error:
        print(f'{ERROR}[WATCHDOG] - ERROR : Impossible de se connecter au dispatcher : {error}{RESET}')
        return None

def connect_to_worker_socket(worker_socket):
    """
    Tente d'établir une connexion avec le worker.
    Retourne la socket connectée (ou None en cas d'erreur).
    """
    if worker_socket is not None:
        return worker_socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((HOST, WORKER_PORT))
        print(f'{SUCCESS}[WATCHDOG] - INFO  : Connexion au worker établie.{RESET}')
        return s
    except OSError as error:
        print(f'{ERROR}[WATCHDOG] - ERROR : Impossible de se connecter au worker : {error}{RESET}')
        return None

def check_health(sock, name):
    """Vérifie l'état d'un processus"""
    try:
        # Configurer un timeout de 30 secondes pour la réception
        sock.settimeout(30.0)

        # Envoyer le message de santé
        sock.send(b'watchdog-health-test')

        # Attendre une réponse (n'importe quelle donnée)
        response = sock.recv(1024)

        if response:
            print(f'{SUCCESS}[WATCHDOG] - INFO  : {name} a répondu : {response!r}{RESET}')
            return True

    except socket.timeout:
        print(f'{ERROR}[WATCHDOG] - ERROR : Aucun message reçu de {name} dans la limite des 30 secondes (timeout){RESET}')
        return False
    except OSError as error:
        print(f'{ERROR}[WATCHDOG] - ERROR : {name} ne répond pas : {error}{RESET}')
        return False

def main():
    global dispatcher_socket, worker_socket, shutdown_requested

    print(f'{SUCCESS}[WATCHDOG] - INFO : Watchdog démarré.{RESET}')

    try:
        while not shutdown_requested:
            # Vérifier le dispatcher
            dispatcher_socket = connect_to_dispatcher_socket(dispatcher_socket)
            if dispatcher_socket:
                if not check_health(dispatcher_socket, "Dispatcher"):
                    dispatcher_socket = None

            time.sleep(5)

            if shutdown_requested:
                break

            # Vérifier le worker
            worker_socket = connect_to_worker_socket(worker_socket)
            if worker_socket:
                if not check_health(worker_socket, "Worker"):
                    worker_socket = None

            time.sleep(5)

    except KeyboardInterrupt:
        print(f'\n{WARNING}[WATCHDOG] - INFO : Interruption clavier détectée{RESET}')

    finally:
        # Fermeture propre
        if dispatcher_socket:
            try:
                dispatcher_socket.close()
                print(f'{SUCCESS}[WATCHDOG] - SUCCESS : Connexion avec le Dispatcher correctement fermée.{RESET}')
            except:
                pass

        if worker_socket:
            try:
                worker_socket.close()
                print(f'{SUCCESS}[WATCHDOG] - SUCCESS : Connexion avec le Woker correctement fermée.{RESET}')
            except:
                pass

        print(f'{SUCCESS}[WATCHDOG] - INFO : Watchdog arrêté{RESET}')

if __name__ == "__main__":
    sys.exit(main())