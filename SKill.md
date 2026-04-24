# SKILL.md

## Stack technique
- Python 3.11, Flask, paramiko, cryptography (Fernet), SQLite, APScheduler
- Docker / docker-compose
- Pas de SQLAlchemy, pas de Django — rester simple

## Conventions
- Logs toujours en JSON structuré
- Secrets toujours via variables d'environnement (.env)
- Chaque fichier Python < 200 lignes
- Docstrings sur chaque fonction publique

## Architecture réseau Docker
- Réseau interne `pam-network` : vault, bastion, targets
- Seul le portail (5000) est exposé à l'hôte
- Ne jamais exposer le vault directement

## Contexte projet
Ce projet simule un PAM pour préparer un entretien chez BPCE-IT (service DIS_IAM_PCT).
Priorité : code lisible et démontrable > code parfait.
