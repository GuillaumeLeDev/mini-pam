# mini-PAM — Privileged Access Management Lab

> Simulation complète d'une solution PAM enterprise en Python/Docker.
> Projet personnel pour comprendre et démontrer les concepts fondamentaux
> de la gestion des accès à privilèges (CyberArk, BeyondTrust, HashiCorp Vault).

---

## Architecture

```
                        ┌─────────────────┐
                        │   PORTAIL :5000  │  ← Point d'entrée unique
                        │   (Flask/HTML)   │
                        └────────┬────────┘
                                 │
               ┌─────────────────┼─────────────────┐
               │                 │                  │
    ┌──────────▼──────┐  ┌───────▼───────┐  ┌──────▼────────┐
    │  VAULT :5001    │  │ BASTION :5002  │  │ROTATION :5003  │
    │  Secret Store   │  │ Jump Server    │  │ Password Agent │
    │  Fernet/SQLite  │  │ Session Record │  │ SSH + JIT      │
    └─────────────────┘  └───────┬───────┘  └──────┬────────┘
                                 │                  │
                    ┌────────────┴──────────────────┘
                    │ pam-network (Docker interne)
          ┌─────────┴──────────┐
          │                    │
  ┌───────▼──────┐   ┌─────────▼─────┐
  │ TARGET-DEV   │   │ TARGET-PROD    │
  │ Alpine SSH   │   │ Alpine SSH     │
  │ :2222        │   │ :2222          │
  └──────────────┘   └───────────────┘
```

**Règle réseau :** seul le portail (:5000) est accessible depuis l'hôte.
Vault, bastion, rotation et targets vivent uniquement dans le réseau Docker interne.

---

## Composants PAM simulés

| Composant | Fichier | Équivalent enterprise |
|-----------|---------|----------------------|
| Secret Store | `vault/vault_api.py` | CyberArk Digital Vault / HashiCorp Vault |
| Jump Server | `proxy/bastion.py` | CyberArk PSM / BeyondTrust PRA |
| Password Rotation | `rotation/rotation_agent.py` | CyberArk CPM (Central Policy Manager) |
| Portail d'accès | `portal/portal.py` | CyberArk PVWA / BeyondTrust Portal |
| Politique RBAC | `config/policy.json` | CyberArk Safe Permissions / AD Groups |
| Session Recording | `proxy/sessions.log` | CyberArk Session Manager |
| Audit Trail | `vault/secrets.db` | CyberArk Audit / SIEM integration |

---

## Fonctionnalités implémentées

### Secret Store (vault)
- Chiffrement **Fernet (AES-128-CBC + HMAC)** pour tous les secrets en base
- **TTL configurable** par secret — expiration automatique
- **Audit trail** : chaque lecture, création, rotation loggée en JSON
- **Rate limiting** : blocage IP après 5 tentatives d'auth échouées
- **Trusted services** : bastion et rotation peuvent lire tous les secrets

### Session Management (bastion)
- **Zero-knowledge** : l'utilisateur ne reçoit jamais le mot de passe
- **Session recording** : toutes les commandes enregistrées avec timestamp
- **Just-in-Time** : fermeture automatique de session par timer
- **RBAC** : vérification rôle × cible × durée avant ouverture de session

### Password Rotation (rotation)
- Détection automatique des secrets dont TTL restant < 20%
- Rotation SSH via `sudo chpasswd` — **serveur d'abord, vault ensuite**
- Gestion des erreurs sans lockout : vault non modifié si SSH échoue
- Endpoint `/metrics` pour monitoring en temps réel

### Portail web
- Dashboard : état global, sessions récentes, métriques rotation, alertes
- Checkout : formulaire de demande d'accès avec validation en temps réel
- Audit : tableau filtrable + **export CSV** pour la conformité bancaire

---

## Démarrage rapide

### Prérequis
- Docker + Docker Compose v2
- Python 3.11+ (pour les scripts locaux)

### Installation

```bash
git clone https://github.com/GuillaumeLeDev/mini-pam
cd mini-pam

# 1. Configurer l'environnement
cp .env.example .env

# Générer la clé Fernet
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# → Coller la valeur dans .env à la ligne FERNET_KEY=

# 2. Démarrer le lab
docker compose up --build -d

# 3. Seeder les secrets initiaux
bash scripts/setup.sh

# 4. Vérifier que tout fonctionne
python3 scripts/health_check.py

# 5. (Optionnel) Peupler avec des données de démo réalistes
bash scripts/demo_data.sh
```

Le portail est accessible sur **http://localhost:5000**

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `VAULT_API_KEY` | Clé d'authentification vault | `dev-api-key-change-me` |
| `FERNET_KEY` | Clé de chiffrement des secrets | À générer |
| `BASTION_API_KEY` | Clé d'authentification bastion | `dev-bastion-key-change-me` |

---

## Scénarios de démo

### Scénario 1 — Accès normal (Happy path)
```bash
# Via le portail : http://localhost:5000/checkout
# Ou via l'API :
curl -X POST http://localhost:5002/sessions \
  -H "X-API-Key: dev-bastion-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"user":"guillaume","target":"server-dev-01",
       "reason":"Restart nginx incident P1","duration_minutes":30}'

# Exécuter des commandes (enregistrées)
curl -X POST http://localhost:5002/sessions/{SESSION_ID}/exec \
  -H "X-API-Key: dev-bastion-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"command":"whoami && uptime"}'
```

### Scénario 2 — Refus d'accès (RBAC)
```bash
# guillaume (ops_engineer) ne peut pas accéder à prod
curl -X POST http://localhost:5002/sessions \
  -H "X-API-Key: dev-bastion-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"user":"guillaume","target":"server-prod-01","reason":"test","duration_minutes":5}'
# → 403 : "Role 'ops_engineer' not allowed on 'server-prod-01'"
```

### Scénario 3 — Just-in-Time (timeout automatique)
```bash
# Créer une session courte et observer la coupure automatique
curl -X POST http://localhost:5002/sessions \
  -H "X-API-Key: dev-bastion-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"user":"guillaume","target":"server-dev-01",
       "reason":"demo JIT","duration_minutes":1}'
# → Attendre 1 minute → status devient "closed_timeout"
```

### Scénario 4 — Rotation automatique
```bash
# Forcer une rotation immédiate
curl -X POST http://localhost:5003/rotate/force

# Vérifier les métriques
curl http://localhost:5003/metrics

# Le mot de passe dans le vault a changé
curl -H "X-API-Key: dev-api-key-change-me" \
     -H "X-Owner: system" \
     http://localhost:5001/secrets/target-dev-admin
```

### Scénario 5 — Simulation d'attaques
```bash
bash scripts/simulate_attack.sh
# Teste : escalade de privilèges, accès direct vault,
#         dépassement JIT, brute force (rate limiting)
```

---

## Concepts PAM maîtrisés

Ce projet démontre la compréhension pratique de :

**Fondamentaux**
- **Secret Store** — stockage chiffré centralisé, TTL, audit de chaque accès
- **Session Recording** — enregistrement de toutes les commandes tapées
- **Just-in-Time Access** — accès accordé uniquement pour la durée nécessaire
- **Password Rotation** — renouvellement automatique sans intervention humaine

**Sécurité**
- **Zero-knowledge credential** — l'utilisateur ne connaît jamais le mot de passe
- **Segregation of Duties** — séparation demandeur / détenteur du credential
- **Least Privilege** — droits minimaux, durée minimale
- **Rate limiting** — protection contre le brute force
- **Audit trail immuable** — traçabilité réglementaire (DORA, PCI-DSS)

**Architecture**
- **RBAC** (Role-Based Access Control) — politique rôle × cible × durée
- **Segmentation réseau** — vault et targets non exposés depuis l'extérieur
- **Trusted services** — confiance basée sur l'identité du service, pas du credential
- **Fail-safe rotation** — en cas d'échec, l'accès reste possible

**Réglementaire**
- Export CSV des sessions pour les auditeurs bancaires
- Justification obligatoire de chaque accès
- Conservation des logs d'accès avec IP, timestamp, acteur

---

## Structure du projet

```
mini-pam/
├── vault/                  ← Secret Store (Flask + Fernet + SQLite)
├── proxy/                  ← Bastion / Jump Server (Flask + paramiko)
├── rotation/               ← Agent de rotation automatique
├── portal/                 ← Interface web (Flask + Bootstrap 5)
│   └── templates/
├── target/                 ← Serveurs SSH simulés (Alpine)
├── config/
│   └── policy.json         ← Politique RBAC
└── scripts/
    ├── setup.sh            ← Bootstrap du lab
    ├── simulate_attack.sh  ← Démonstration des protections
    └── health_check.py     ← Vérification de l'état du lab
```

---

*Ce projet simule les composants fondamentaux d'une solution PAM enterprise.
Il ne prétend pas à une sécurité production mais démontre la compréhension
des concepts et de l'architecture PAM.*
