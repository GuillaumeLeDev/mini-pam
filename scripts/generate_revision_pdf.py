from fpdf import FPDF, XPos, YPos

BLUE   = (30,  60,  114)
GREEN  = (20,  90,   50)
BROWN  = (120, 50,    0)
DARK   = (40,  40,   40)
WHITE  = (255, 255, 255)
LGRAY  = (240, 240, 245)
ALTROW = (235, 240, 255)

class PDF(FPDF):
    def header(self):
        self.set_fill_color(*BLUE)
        self.rect(0, 0, 210, 18, "F")
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*WHITE)
        self.set_y(4)
        self.cell(0, 10, "Mini-PAM - Fiche de revision entretien BPCE-IT", align="C",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*DARK)
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

    def section_title(self, title, color=BLUE):
        self.set_fill_color(*color)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 8, f"  {title}", fill=True,
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(*DARK)
        self.ln(2)

    def sub(self, text):
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def body(self, text):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 6, text)
        self.ln(1)

    def bullet(self, items):
        self.set_font("Helvetica", "", 10)
        for item in items:
            self.set_x(self.l_margin + 4)
            self.multi_cell(180, 6, f"- {item}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def code_block(self, lines):
        self.set_fill_color(*LGRAY)
        self.set_draw_color(180, 180, 200)
        x, y = self.get_x(), self.get_y()
        h = len(lines) * 5.5 + 4
        self.rect(x, y, 190, h, "DF")
        self.set_xy(x + 3, y + 2)
        self.set_font("Courier", "", 9)
        for line in lines:
            self.cell(184, 5.5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 10)
        self.ln(3)

    def table(self, headers, rows, col_widths):
        self.set_fill_color(*BLUE)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 9)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True)
        self.ln()
        self.set_text_color(*DARK)
        for idx, row in enumerate(rows):
            self.set_fill_color(*ALTROW) if idx % 2 else self.set_fill_color(*WHITE)
            self.set_font("Helvetica", "", 9)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 7, cell, border=1, fill=True)
            self.ln()
        self.ln(3)


pdf = PDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

# ── FLUX GLOBAL ───────────────────────────────────────────────────────────────
pdf.section_title("Flux complet")
pdf.body("Portal  ->  Bastion  ->  Vault (recupere le mdp)  ->  SSH target  ->  session enregistree  ->  acces coupe automatiquement")

# ── VAULT ─────────────────────────────────────────────────────────────────────
pdf.section_title("1. Vault  (vault/vault_api.py)  -  Le coffre-fort")

pdf.sub("Ce qu'il fait :")
pdf.bullet([
    "Stocke les mots de passe chiffres en Fernet dans SQLite (secrets.db)",
    "Chaque secret a : owner, TTL (duree en heures), date d'expiration",
    "Tous les acces sont logges dans audit_log : qui, quand, IP, succes/echec",
    "L'humain ne voit jamais le mdp - retourne uniquement au bastion via API key",
])

pdf.sub("Endpoints cles :")
pdf.code_block([
    "POST /secrets               -> creer un secret",
    "GET  /secrets/{name}        -> lire (verifie owner + expiration)",
    "POST /secrets/{name}/rotate -> rotation manuelle",
    "GET  /audit                 -> journal de tous les acces",
])

pdf.sub("Historique genere par le Vault :")
pdf.bullet([
    "Audit trail des acces : 'guillaume a lu server-dev-01 a 14h32 depuis 172.x.x.x'",
    "Temporalite : date creation, date expiration, statut (actif / expire)",
])

# ── BASTION ───────────────────────────────────────────────────────────────────
pdf.section_title("2. Bastion  (proxy/bastion.py)  -  Le Jump Server", color=GREEN)

pdf.sub("Ce qu'il fait :")
pdf.bullet([
    "Recoit une demande : {user, target, reason, duration_minutes}",
    "Verifie l'autorisation via policy.json (RBAC)",
    "Va chercher le mdp lui-meme dans le Vault - l'humain ne le voit jamais",
    "Ouvre la session SSH vers la cible via paramiko",
    "Enregistre chaque commande tapee pendant la session",
    "Coupe la session automatiquement apres duration_minutes (JIT)",
])

pdf.sub("Historique genere par le Bastion :")
pdf.code_block([
    "{",
    '  "session_id": "uuid",',
    '  "user": "guillaume",',
    '  "target": "server-dev-01",',
    '  "reason": "restart nginx",',
    '  "start": "...",  "end": "...",',
    '  "commands": ["ls /etc/nginx", "sudo systemctl restart nginx"],',
    '  "status": "closed_normal"',
    "}",
])
pdf.bullet([
    "Stocke dans proxy/sessions.log",
    "Consultable depuis le portail /sessions avec export CSV",
])

# ── ROTATION ──────────────────────────────────────────────────────────────────
pdf.section_title("3. Rotation  (rotation/rotation_agent.py)  -  L'agent automatique", color=BROWN)

pdf.sub("Ce qu'il fait (en boucle) :")
pdf.bullet([
    "Interroge le vault : secrets dont TTL restante < 20%",
    "Genere un nouveau mdp : secrets.token_urlsafe(32)",
    "Change le mdp sur la machine cible via SSH (paramiko)",
    "Met a jour le vault avec le nouveau mdp",
    "Si echec : alerte SANS supprimer l'ancien mdp (securite)",
])

pdf.sub("Endpoint /metrics (port 5003) :")
pdf.bullet([
    "Nombre de secrets geres",
    "Derniere rotation reussie / echouee",
    "Secrets expires non renouveles (ALERT)",
])

# ── TABLEAU ───────────────────────────────────────────────────────────────────
pdf.section_title("4. Tableau recapitulatif - Qui fait quoi ?")
pdf.table(
    headers=["Question entretien", "Reponse"],
    rows=[
        ["Qui logue les acces aux secrets ?",      "Vault  -  table audit_log"],
        ["Qui logue les commandes tapees ?",       "Bastion  -  sessions.log"],
        ["Qui renouvelle les mots de passe ?",     "Rotation agent  -  automatiquement"],
        ["L'humain voit-il le mdp ?",              "Jamais  -  le bastion fait l'intermediaire"],
        ["Comment limiter l'acces dans le temps ?","JIT  -  timeout automatique du bastion"],
        ["Comment savoir qui a fait quoi ?",       "Vault (acces) + Bastion (commandes)"],
    ],
    col_widths=[105, 85],
)

# ── COMMANDES ─────────────────────────────────────────────────────────────────
pdf.section_title("5. Commandes pour demarrer le lab")
pdf.code_block([
    "docker compose up --build -d",
    "export $(cat .env | xargs) && bash scripts/setup.sh",
    "python3 scripts/health_check.py",
    "",
    "# Portail : http://localhost:5000",
    "# Vault   : http://localhost:5001",
    "# Bastion : http://localhost:5002",
    "# Rotation metrics : http://localhost:5003/metrics",
])

out = "/home/guillaume/Documents/Projet_Perso/mini-pam/revision_pam.pdf"
pdf.output(out)
print(f"PDF genere : {out}")
