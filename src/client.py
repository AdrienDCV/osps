#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket

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

try:
    # Tentative de connexion au Dispatcher
    sock.settimeout(30)     # Évite de bloquer indéfiniment sur recv()
    sock.connect((HOST, PORT))
    print(f"{SUCCESS}[CLIENT] : Connecté au Dispatcher.{RESET}")

    # Boucle principale d'interaction avec le Dispatcher
    while True:
        try:
            # Récupération de la commande saisie par l'utilisateur
            cmd = input("[CLIENT] : Commande client ('QUIT' pour sortir) : ")

            # Si l'utilisateur n'entre rien, on ignore et on redemande
            if not cmd:
                continue

            # Envoi de la commande au Dispatcher (avec \n comme délimiteur)
            sock.sendall((cmd + "\n").encode())

            # Traitement spécifique de la commande QUIT
            if cmd == "QUIT":
                try:
                    # Attente de l'accusé de réception du Dispatcher
                    reply = sock.recv(1024).decode().strip()
                except (socket.timeout, ConnectionError):
                    pass     # Le Dispatcher a déjà fermé la connexion, c'est normal pour QUIT
                print(f"{WARNING}[CLIENT] : Fermeture du client...{RESET}")
                break

            # Réception de la réponse du Dispatcher (jusqu'à 1024 octets)
            data = sock.recv(1024)

            # Si aucune donnée n'est reçue, le Dispatcher a fermé la connexion
            if not data:
                print(f"{WARNING}[CLIENT] : Le Dispatcher a fermé la connexion.{RESET}")
                break

            # Décodage et affichage de la réponse du Dispatcher
            dispatcher_response = data.decode().strip()
            print("[CLIENT] : Réponse du Dispatcher :", dispatcher_response)

        except socket.timeout:
            # Le Dispatcher n'a pas répondu dans le délai imparti (30 secondes)
            print(f"{ERROR}[CLIENT] : Timeout - le Dispatcher ne répond pas.{RESET}")
            break
        except (BrokenPipeError, ConnectionResetError, ConnectionError):
            # Gestion de la perte de connexion avec le Dispatcher (coupure réseau, crash, etc.)
            print(f"{ERROR}[CLIENT] : Connexion perdue avec le Dispatcher.{RESET}")
            break
        except UnicodeDecodeError:
            # Erreur lors du décodage de la réponse (encodage incorrect ou données corrompues)
            print(f"{ERROR}[CLIENT] : Erreur de décodage de la réponse.{RESET}")

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
