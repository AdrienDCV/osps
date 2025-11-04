#! /usr/bin/env python3
# _*_ coding: utf8 _*_

import os, sys
from multiprocessing import shared_memory
from multiprocessing import resource_tracker

if __name__ == "__main__":
    print('Début processus 2')

    # Se connecter au segment mémoire partagé existant
    shm_segment2 = shared_memory.SharedMemory(name='012345', create=False)

    # Éviter que le resource tracker tente de le supprimer à la fermeture
    resource_tracker.unregister(f"/012345", "shared_memory")

    print('Nom du segment mémoire partagée :', shm_segment2.name)
    print('Taille du segment mémoire partagée en octets via second accès :', len(shm_segment2.buf))

    # Lire uniquement les 10 premiers octets
    print('Contenu du segment mémoire partagée (10 octets) :', bytes(shm_segment2.buf[:10]))

    shm_segment2.close()
    print('Fin processus 2')
