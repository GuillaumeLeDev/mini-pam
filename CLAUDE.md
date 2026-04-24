# CLAUDE.md — Projet PAM Mini-Lab (Week-end intensif)
## Contexte & Objectif

Tu vas m'aider à construire un **mini-lab PAM (Privileged Access Management)** en Python/Docker,
simulant les problématiques réelles du poste visé chez BPCE-IT (service DIS_IAM_PCT).

L'objectif est double :
1. **Apprendre en faisant** : comprendre les concepts PAM par la pratique
2. **Avoir un projet GitHub démontrable** à présenter lors de l'entretien technique avec Stéphane et Anthony

Mon profil technique : Python (API REST, scripts), Bash, Linux Debian, Docker, SSH durci, gestion
utilisateurs, principe du moindre privilège — déjà pratiqués dans mes projets persos.

---

## Architecture du projet : `mini-pam`

```
mini-pam/
├── CLAUDE.md               ← ce fichier
├── README.md               ← doc projet (à générer à la fin)
├── docker-compose.yml      ← orchestration de tous les services
├── vault/                  ← coffre-fort de mots de passe (Secret Store)
│   ├── Dockerfile
│   ├── vault_api.py        ← API Flask : stocker/récupérer/rotation de secrets
│   └── secrets.db          ← SQLite chiffré (fernet)
├── target/                 ← machine cible simulée (SSH server)
│   ├── Dockerfile
│   └── sshd_config
├── proxy/                  ← Jump Server / Bastion (cœur du PAM)
│   ├── Dockerfile
│   ├── bastion.py          ← gestion des sessions, logging, durée limitée
│   └── sessions.log
├── portal/                 ← Interface web minimaliste (Flask)
│   ├── Dockerfile
│   ├── portal.py
│   └── templates/
│       ├── index.html
│       ├── checkout.html   ← "checkout" d'un accès privilégié
│       └── sessions.html   ← audit des sessions
├── rotation/               ← Agent de rotation automatique des mots de passe
│   ├── rotation_agent.py
│   └── schedule.py
└── scripts/
    ├── setup.sh            ← bootstrap du lab
    ├── simulate_attack.sh  ← simulation d'accès non autorisé (pour les démos)
    └── health_check.py     ← vérifie l'état de tous les composants
```

---

## Phase 1 — Vendredi soir (2-3h) : Fondations & Coffre-fort

### Étape 1.1 — Comprendre avant de coder

Avant de commencer, explique-moi en 10 lignes maximum :
- Ce qu'est le PAM et pourquoi c'est critique en cybersécurité bancaire
- Les 4 piliers : **Secret Store**, **Session Management**, **Just-in-Time Access**, **Password Rotation**
- Pourquoi CyberArk / BeyondTrust / HashiCorp Vault existent (outils du marché)
- Le lien avec le principe du moindre privilège que j'applique déjà

### Étape 1.2 — Secret Store (vault/)

Crée `vault/vault_api.py` : une API Flask qui :

```python
# Endpoints à implémenter :
# POST /secrets          → stocker un secret {name, value, owner, expires_in_hours}
# GET  /secrets/{name}   → récupérer un secret (avec vérification owner + expiration)
# POST /secrets/{name}/rotate  → déclencher une rotation manuelle
# GET  /secrets          → lister tous les secrets (sans les valeurs !)
# GET  /audit            → log de tous les accès aux secrets

# Contraintes de sécurité :
# - Chiffrement Fernet (cryptography lib) pour les valeurs en base
# - Chaque accès est loggé (qui, quand, depuis quelle IP, succès/échec)
# - Les secrets ont une TTL (Time-To-Live) configurable
# - Authentification par API key sur tous les endpoints
```

**Concepts PAM appris ici :** Secret Store, audit trail, TTL des credentials, chiffrement au repos

### Étape 1.3 — Machine cible SSH simulée (target/)

Crée un `Dockerfile` pour un serveur SSH Alpine Linux avec :
- Un user `admin` avec mot de passe récupéré depuis le vault au démarrage
- SSH sur port 2222
- Logs de connexion activés

---

## Phase 2 — Samedi matin (3-4h) : Bastion & Session Management

### Étape 2.1 — Jump Server / Bastion (proxy/)

Crée `proxy/bastion.py` : le cœur du PAM.

```python
# Ce module doit :
# 1. Recevoir une demande d'accès : {user, target, reason, duration_minutes}
# 2. Vérifier l'autorisation (liste blanche users/targets en config JSON)
# 3. Récupérer le mot de passe depuis le vault (l'humain ne le voit JAMAIS)
# 4. Ouvrir une session SSH via paramiko vers la machine cible
# 5. Logger TOUTES les commandes tapées pendant la session (session recording)
# 6. Couper automatiquement la session après duration_minutes (Just-in-Time)
# 7. Invalider le checkout du secret après utilisation

# Structure du log de session :
# {
#   "session_id": "uuid4",
#   "user": "guillaume",
#   "target": "server-prod-01",
#   "reason": "incident P1 - restart service nginx",
#   "start": "2025-01-01T10:00:00",
#   "end": "2025-01-01T10:15:00",
#   "commands": ["ls /etc/nginx", "sudo systemctl restart nginx", "exit"],
#   "status": "closed_normal"
# }
```

**Concepts PAM appris ici :** Session recording, Just-in-Time (JIT) access, credential checkout,
séparation des rôles (l'humain n'a jamais le mot de passe réel)

### Étape 2.2 — Politique d'accès (policy.json)

Crée un fichier `config/policy.json` et explique-moi le modèle :

```json
{
  "users": {
    "guillaume": {
      "role": "ops_engineer",
      "allowed_targets": ["server-dev-*", "server-preprod-01"],
      "max_session_minutes": 60,
      "require_reason": true,
      "mfa_required": false
    },
    "admin_pam": {
      "role": "pam_admin",
      "allowed_targets": ["*"],
      "max_session_minutes": 120,
      "require_reason": true,
      "mfa_required": true
    }
  },
  "targets": {
    "server-prod-01": {
      "criticality": "high",
      "allowed_roles": ["pam_admin"],
      "dual_approval": true
    },
    "server-dev-01": {
      "criticality": "low",
      "allowed_roles": ["ops_engineer", "pam_admin"],
      "dual_approval": false
    }
  }
}
```

**Concepts PAM appris ici :** RBAC (Role-Based Access Control), segmentation par criticité,
dual approval (validation par un second admin pour les serveurs critiques)

---

## Phase 3 — Samedi après-midi (3h) : Rotation & Portail

### Étape 3.1 — Agent de rotation automatique (rotation/)

Crée `rotation/rotation_agent.py` :

```python
# Fonctionnement :
# - Tourne en boucle (configurable : toutes les X heures)
# - Récupère la liste des secrets dont TTL < 20% de la durée initiale
# - Pour chaque secret à rotation :
#   1. Génère un nouveau mot de passe (secrets.token_urlsafe(32))
#   2. Change le mot de passe sur la machine cible via SSH (paramiko)
#   3. Met à jour le vault avec le nouveau mot de passe
#   4. Log l'opération de rotation
#   5. Notifie (print/log) si une rotation échoue
# - Gère les erreurs : si la rotation échoue, alerter SANS supprimer l'ancien mot de passe

# Métriques à exposer (endpoint /metrics) :
# - Nombre de secrets gérés
# - Dernière rotation réussie / échouée
# - Secrets expirés non renouvelés (ALERT)
```

**Concepts PAM appris ici :** Password rotation automatique, gestion des erreurs de rotation,
réduction de la surface d'attaque par renouvellement régulier des credentials

### Étape 3.2 — Portail web (portal/)

Crée `portal/portal.py` avec Flask et des templates HTML simples (Bootstrap CDN) :

**Page 1 — Dashboard `/`**
- Nombre de secrets actifs / expirés
- Sessions en cours
- Dernières rotations
- Alertes (secrets non renouvelés, sessions anormalement longues)

**Page 2 — Checkout d'accès `/checkout`**
- Formulaire : target, reason, duration
- Vérification de la politique d'accès en temps réel
- Bouton "Demander l'accès" → crée une session via le bastion
- L'utilisateur reçoit juste un `session_id`, jamais le mot de passe

**Page 3 — Audit `/sessions`**
- Tableau de toutes les sessions : user, target, durée, commandes, statut
- Filtres par date, user, target
- Export CSV (important pour la conformité bancaire !)

**Concepts PAM appris ici :** Portail d'accès à privilèges, audit & compliance, séparation
entre le demandeur et le credential

---

## Phase 4 — Dimanche (3h) : Sécurité, Tests & Documentation

### Étape 4.1 — Script de simulation d'attaque (scripts/simulate_attack.sh)

```bash
#!/bin/bash
# Ce script simule des comportements suspects pour tester les alertes PAM :

# Scénario 1 : Tentative d'accès à une ressource non autorisée
# → Doit être bloqué et loggé par le bastion

# Scénario 2 : Tentative de récupération directe d'un secret sans passer par le bastion
# → Doit échouer (API key requise)

# Scénario 3 : Session dépassant la durée autorisée
# → Doit être coupée automatiquement

# Scénario 4 : Tentative de brute force sur l'API vault
# → Doit déclencher un rate limiting (après 5 tentatives)

# Pour chaque scénario, afficher : [BLOCKED] ou [ALERT] avec le détail
```

### Étape 4.2 — docker-compose.yml final

Assemble tous les services :
```yaml
# Services :
# - vault       : port 5001
# - target-dev  : SSH port 2222
# - target-prod : SSH port 2223
# - bastion     : port 5002
# - portal      : port 5000
# - rotation    : service background (pas de port exposé)
#
# Network : réseau Docker interne "pam-network"
# Seul le portail est accessible depuis l'hôte
# Le vault et le bastion ne sont accessibles QUE depuis pam-network
# → Simule la segmentation réseau réelle d'un PAM en prod
```

### Étape 4.3 — health_check.py

Script Python qui vérifie que tout fonctionne :
- Vault API répond ✓
- Rotation agent tourne ✓
- Bastion accessible ✓
- Cibles SSH joignables ✓
- Au moins 1 secret valide en base ✓

### Étape 4.4 — README.md (pour GitHub)

Génère un README professionnel avec :
- Schéma ASCII de l'architecture
- Explication des composants PAM simulés
- Tableau de correspondance : **Fonctionnalité mini-pam → Équivalent CyberArk/BeyondTrust**
- Instructions de démarrage (`docker-compose up`)
- Scénarios de démo (pour l'entretien)
- Ce que j'ai appris (section "Concepts PAM maîtrisés")

---

## Contraintes techniques globales

- **Python 3.11+** pour tous les services
- **Librairies autorisées** : Flask, paramiko, cryptography (Fernet), sqlite3 (stdlib), requests, APScheduler
- **Pas de framework lourd** : pas de Django, pas de SQLAlchemy — rester simple et lisible
- **Chaque fichier Python < 200 lignes** : modularité et lisibilité pour la démo
- **Docstrings** sur chaque fonction : montrer la rigueur professionnelle
- **Tous les secrets/configs** passent par variables d'environnement (jamais hardcodés)
- **Logs structurés** en JSON pour tous les composants (audit trail)

---

## Ce que je dois être capable d'expliquer à l'entretien

À la fin de ce projet, je dois pouvoir répondre à ces questions de Stéphane et Anthony :

### Questions techniques
1. "Comment fonctionne la rotation automatique de mots de passe ?"
   → Je montre `rotation_agent.py` et j'explique le flux complet

2. "Comment vous assurez-vous qu'un utilisateur n'a jamais accès au mot de passe réel ?"
   → Je montre le bastion : checkout → session SSH → jamais de retour du secret en clair

3. "Qu'est-ce que le Just-in-Time access ?"
   → Accès accordé uniquement pour la durée nécessaire, révoqué automatiquement

4. "Comment gérez-vous les comptes de service et les secrets applicatifs ?"
   → Je montre l'API vault avec TTL et rotation programmatique

5. "Comment s'assurer de la traçabilité des accès privilégiés ?"
   → Je montre le session recording et l'export d'audit CSV

### Questions stratégiques (PLAN du poste)
6. "Comment évalueriez-vous la maturité PAM d'une organisation ?"
   → Grille : inventaire des comptes privilégiés, % sous PAM, rotation activée, session recording, alertes

7. "Quels risques adresse le PAM ?"
   → Credential theft, lateral movement, insider threat, comptes orphelins

---

## Lexique PAM à maîtriser

| Terme | Définition simple | Dans mon projet |
|-------|-------------------|-----------------|
| **Coffre-fort (Vault)** | Stockage chiffré des credentials | `vault/vault_api.py` |
| **Credential Checkout** | Emprunt temporaire d'un accès | `portal/checkout` → bastion |
| **Session Recording** | Enregistrement des commandes tapées | `proxy/sessions.log` |
| **Password Rotation** | Renouvellement auto des mots de passe | `rotation/rotation_agent.py` |
| **Just-in-Time (JIT)** | Accès accordé à la demande, limité dans le temps | Timeout automatique bastion |
| **Least Privilege** | Droits minimaux nécessaires | `config/policy.json` |
| **Dual Approval** | Validation par 2 admins pour les cibles critiques | Policy serveurs prod |
| **Audit Trail** | Journal inaltérable de toutes les actions | Logs JSON de tous les services |
| **Privileged Account** | Compte avec droits élevés (root, admin, service) | Users dans `policy.json` |
| **RBAC** | Droits basés sur les rôles | Rôles ops_engineer / pam_admin |
| **Surface d'attaque** | Ensemble des points d'entrée exploitables | Réduite par JIT + rotation |

---

## Ordre d'exécution recommandé

```
Vendredi soir  : Phase 1 (vault + target SSH) → docker-compose partiel qui fonctionne
Samedi matin   : Phase 2 (bastion + policy)   → premier checkout d'accès qui marche
Samedi PM      : Phase 3 (rotation + portail) → démo bout-en-bout fonctionnelle
Dimanche       : Phase 4 (sécurité + README)  → projet propre et pushé sur GitHub
```

---

## Commande de démarrage

Une fois tout construit, le lab doit démarrer avec :

```bash
git clone https://github.com/GuillaumeLeDev/mini-pam
cd mini-pam
cp .env.example .env   # renseigner les variables
docker-compose up --build
# → Portail accessible sur http://localhost:5000
```

---

*Ce projet simule les composants fondamentaux d'une solution PAM enterprise (CyberArk, BeyondTrust, HashiCorp Vault). Il ne prétend pas à une sécurité production mais démontre la compréhension des concepts et de l'architecture.*
