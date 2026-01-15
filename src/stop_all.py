#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import signal
import time
import sys

# Constantes pour l'affichage coloré des logs
ERROR = '\033[91m'    # Rouge pour les erreurs
SUCCESS = '\033[92m'  # Vert pour les succès
WARNING = '\033[93m'  # Jaune pour les avertissements
RESET = '\033[0m'     # Réinitialisation de la couleur

# Fichiers PID et tubes nommés
DISPATCHER_PID_FILE = "/tmp/dispatcher.pid"
WORKER_PID_FILE = "/tmp/worker.pid"
TUBE_D_W = "/tmp/dwtube1"
TUBE_W_D = "/tmp/wdtube1"


def kill_process_from_pid_file(pid_file, process_name):
    """
    Arrête un processus en lisant son PID depuis un fichier.
    Envoie d'abord SIGTERM, puis SIGKILL après un délai si nécessaire.
    """
    if not os.path.exists(pid_file):
        print(f"{WARNING}[STOP] - INFO : {process_name} - Fichier PID non trouvé ({pid_file}){RESET}")
        return

    try:
        with open(pid_file, 'r') as f:
            pid_str = f.read().strip()
            if not pid_str:
                print(f"{ERROR}[STOP] - ERROR : {process_name} - Fichier PID vide ({pid_file}){RESET}")
                try:
                    os.unlink(pid_file)
                except Exception:
                    pass
                return
            pid = int(pid_str)

        print(f"{WARNING}[STOP] - INFO : Envoi de SIGTERM au {process_name} (PID {pid})...{RESET}")
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)

        # Vérifier si le processus s'est bien arrêté
        try:
            os.kill(pid, 0)
            # Information sur l'échec du SIGTERM
            print(f"{WARNING}[STOP] - WARNING : {process_name} (PID {pid}) n'a pas répondu à SIGTERM, envoi de SIGKILL...{RESET}")
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
            print(f"{SUCCESS}[STOP] - SUCCESS : {process_name} (PID {pid}) tué avec SIGKILL{RESET}")
        except ProcessLookupError:
            # Information de l'arrêt du processus
            print(f"{SUCCESS}[STOP] - SUCCESS : {process_name} (PID {pid}) arrêté correctement{RESET}")

        # Attendre un instant avant de continuer et de supprimer le fichier PID
        time.sleep(0.5)

        # Nettoyage du fichier PID si le processus est bien parti
        try:
            if os.path.exists(pid_file):
                os.unlink(pid_file)
                print(f"{SUCCESS}[STOP] - INFO : Fichier PID supprimé : {pid_file}{RESET}")
        except Exception as error:
            print(f"{WARNING}[STOP] - WARNING : Impossible de supprimer {pid_file} : {error}{RESET}")

    except ValueError as error:
        print(f"{ERROR}[STOP] - ERROR : {process_name} - Fichier PID invalide : {error}{RESET}")
        try:
            os.unlink(pid_file)
        except Exception:
            pass
    except ProcessLookupError:
        print(f"{WARNING}[STOP] - WARNING : {process_name} - Processus non trouvé (déjà arrêté ?){RESET}")
        try:
            os.unlink(pid_file)
        except Exception:
            pass
    except OSError as error:
        print(f"{ERROR}[STOP] - ERROR : {process_name} - Erreur lors de l'arrêt : {error}{RESET}")


def cleanup_named_pipes():
    """
    Supprime les tubes nommés restants
    """
    for tube in [TUBE_D_W, TUBE_W_D]:
        if os.path.exists(tube):
            try:
                os.unlink(tube)
                print(f"{SUCCESS}[STOP] - INFO : Tube nommé supprimé : {tube}{RESET}")
            except OSError as error:
                print(f"{WARNING}[STOP] - WARNING : Impossible de supprimer {tube} : {error}{RESET}")


def main():
    """
    Fonction principale de nettoyage
    """
    print(f"{SUCCESS}[STOP] - INFO : Début du nettoyage et arrêt des processus...{RESET}")

    # Arrêt du Dispatcher (qui arrêtera son Worker)
    kill_process_from_pid_file(DISPATCHER_PID_FILE, "Dispatcher")
    time.sleep(2)  # Attendre plus longtemps avant de vérifier le Worker

    # Arrêt du Worker s'il survit
    kill_process_from_pid_file(WORKER_PID_FILE, "Worker")

    # Nettoyage des tubes nommés
    cleanup_named_pipes()

    print(f"{SUCCESS}[STOP] - SUCCESS : Nettoyage terminé{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())