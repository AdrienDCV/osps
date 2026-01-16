#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import sys
import select

# Constantes pour l'affichage coloré des logs
ERROR = '\033[91m'    # Rouge pour les erreurs
SUCCESS = '\033[92m'  # Vert pour les succès
WARNING = '\033[93m'  # Jaune pour les avertissements
RESET = '\033[0m'     # Réinitialisation de la couleur

# Configuration de la connexion
HOST = "127.0.0.1"  # IP du Dispatcher (localhost)
PORT = 2222         # Port utilisé par la socket du Dispatcher

print("[CLIENT] : Connexion au dispatcher...")
# Création d'une socket TCP/IP (AF_INET = IPv4, SOCK_STREAM = TCP)
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def afficher_prompt():
    """
    Affiche le prompte sans bloquer ni passer à la ligne
    """
    sys.stdout.write("[CLIENT] : Commande client ('QUIT' pour sortir) : ")
    sys.stdout.flush()

try:
    # Tentative de connexion au Dispatcher
    sock.settimeout(30)     # Évite de bloquer indéfiniment sur recv()
    sock.connect((HOST, PORT))
    print(f"{SUCCESS}[CLIENT] : Connecté au Dispatcher.{RESET}")

    afficher_prompt()

    # Boucle principale d'interaction avec le Dispatcher
    while True:
        try:
            # Lentrée standard (clavier) et la socket réseau sont écoutées simultanéement
            # Si le Dispatcher coupe, 'sock' deviendra lisible immédiatement.
            liste_lecture, _, _ = select.select([sys.stdin, sock], [], [])

            for source in liste_lecture:
                # Communication avec le Dispatcher
                if source is sock:
                    data = sock.recv(1024)
                    if not data:
                        # Si on reçoit 0 octet, c'est que le Dispatcher est mort
                        print(f"\n{ERROR}[CLIENT] : Le Dispatcher a fermé la connexion (arrêt détecté).{RESET}")
                        sys.exit(0)
                    else:
                        print(f"\n[CLIENT] : Message inattendu : {data.decode()}")
                        afficher_prompt()

                # Traitement de la commande entrée par l'utilisateur
                elif source is sys.stdin:
                    # Lecture de la commande
                    cmd = sys.stdin.readline().strip()

                    # Si l'utilisateur n'entre rien, le prompt est à nouveau affiché
                    if not cmd:
                        afficher_prompt()
                        continue

                    # Envoi de la commande au Dispatcher avec '\n' comme délimiteur
                    sock.sendall((cmd + "\n").encode())

                    # Traitement spécifique de la commande QUIT
                    if cmd == "QUIT":
                        try:
                            # Attente de l'accusé de réception du Dispatcher
                            reply = sock.recv(1024).decode().strip()
                        except (socket.timeout, ConnectionError):
                            pass     # Si le Dispatcher a déjà fermé la connexion, on passe
                        print(f"{WARNING}[CLIENT] : Fermeture du client...{RESET}")
                        sys.exit(0)

                    # Réception de la réponse du Dispatcher
                    data = sock.recv(1024)

                    # Si aucune donnée n'est reçue, le Dispatcher a fermé la connexion
                    if not data:
                        print(f"{WARNING}[CLIENT] : Le Dispatcher a fermé la connexion.{RESET}")
                        sys.exit(0)

                    # Décodage et affichage de la réponse du Dispatcher
                    dispatcher_response = data.decode().strip()
                    print("[CLIENT] : Réponse du Dispatcher :", dispatcher_response)

                    # Affichage du prompt pour entrer la prochaine commande
                    afficher_prompt()

        except socket.timeout:
            # Le Dispatcher n'a pas répondu dans le délai imparti (30 secondes)
            print(f"\n{ERROR}[CLIENT] : Timeout - le Dispatcher ne répond pas.{RESET}")
            break
        except (BrokenPipeError, ConnectionResetError, ConnectionError):
            # Gestion de la perte de connexion avec le Dispatcher (coupure réseau, crash, etc.)
            print(f"\n{ERROR}[CLIENT] : Connexion perdue avec le Dispatcher.{RESET}")
            break
        except UnicodeDecodeError:
            # Erreur lors du décodage de la réponse (encodage incorrect ou données corrompues)
            print(f"\n{ERROR}[CLIENT] : Erreur de décodage de la réponse.{RESET}")
            afficher_prompt()


except ConnectionRefusedError:
    # Le Dispatcher n'est pas accessible
    print(f"{ERROR}[CLIENT] : Impossible de se connecter (le Dispatcher est-il lancé ?){RESET}")
except KeyboardInterrupt:
    # Gestion de l'interruption par Ctrl+C (arrêt manuel par l'utilisateur)
    print(f"\n{WARNING}[CLIENT] : Arrêt demandé par l'utilisateur.{RESET}")
except Exception as e:
    # Capture de toute autre erreur imprévue pour éviter un crash sans message
    print(f"{ERROR}[CLIENT] : Erreur inattendue : {e}{RESET}")

finally:
    # Fermeture propre de la socket dans tous les cas
    sock.close()
    print(f"{SUCCESS}[CLIENT] : Client fermé.")
