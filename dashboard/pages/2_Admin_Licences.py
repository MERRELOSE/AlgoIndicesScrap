import streamlit as st
import json
from pathlib import Path
from datetime import datetime, timedelta
import sys

st.set_page_config(page_title="Gestion Licences", page_icon="🔑", layout="wide")

if not st.session_state.get('admin_auth'):
    st.warning("Connectez-vous depuis la page d'accueil")
    st.stop()

sys.path.append(str(Path(__file__).parent.parent.parent / 'MT5_EA' / 'license'))
from generate_license import generate_hash, load_db, save_db

LICENSE_DB = Path(__file__).parent.parent.parent / 'MT5_EA' / 'license' / 'licenses_db.json'

st.title("🔑 Gestion des Licences")
st.markdown("---")

# ============================================================
# CREATE LICENSE
# ============================================================
st.markdown("### Creer une Licence")

col1, col2 = st.columns(2)

with col1:
    client_name = st.text_input("Nom du client")
    account_num = st.number_input("Numero de compte Deriv", min_value=0, step=1, format="%d")

with col2:
    plan = st.selectbox("Abonnement", ["3 mois - $70", "6 mois - $100", "12 mois - $150"])
    months = int(plan.split(" ")[0])
    custom_expiry = st.date_input("Ou date d'expiration personnalisee",
                                   value=datetime.now() + timedelta(days=months*30))

if st.button("Generer la Licence", type="primary"):
    if account_num == 0:
        st.error("Entrez un numero de compte valide")
    else:
        expiry_str = custom_expiry.strftime("%Y.%m.%d")
        key = generate_hash(int(account_num), expiry_str)

        db = load_db()
        entry = {
            "key": key,
            "account": int(account_num),
            "expiry": expiry_str,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "client": client_name,
            "status": "active",
            "months": months,
        }
        db["licenses"].append(entry)
        save_db(db)

        st.success("Licence generee avec succes !")

        st.markdown("### Informations a envoyer au client")
        st.code(f"""
Bonjour {client_name},

Voici votre licence CrashHunter :

  License Key:      {key}
  Account Number:   {account_num}
  Expiry Date:      {expiry_str}

Instructions:
1. Copiez le fichier .ex5 dans MQL5/Experts/
2. Attachez l'EA au graphique Crash Index (H1)
3. Dans les parametres, entrez les 3 valeurs ci-dessus
4. Activez le trading algorithmique

Cordialement,
CrashHunter Team
        """)

st.markdown("---")

# ============================================================
# MANAGE EXISTING LICENSES
# ============================================================
st.markdown("### Licences Existantes")

db = load_db()
licenses = db.get("licenses", [])

if not licenses:
    st.info("Aucune licence")
    st.stop()

# Actions
for i, lic in enumerate(licenses):
    days_left = (datetime.strptime(lic['expiry'], '%Y.%m.%d') - datetime.now()).days

    with st.expander(f"{'🟢' if lic['status']=='active' and days_left>0 else '🔴'} {lic.get('client', 'Sans nom')} - Compte {lic['account']} ({lic['key']})"):

        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Client:** {lic.get('client', '-')}")
        c2.write(f"**Compte:** {lic['account']}")
        c3.write(f"**Expiration:** {lic['expiry']} ({days_left}j)")
        c4.write(f"**Statut:** {lic['status']}")

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            if lic['status'] == 'active' and st.button(f"Revoquer", key=f"rev_{i}"):
                licenses[i]['status'] = 'revoked'
                save_db(db)
                st.success(f"Licence revoquee pour {lic.get('client')}")
                st.rerun()

        with col_b:
            if lic['status'] in ['expired', 'revoked']:
                renew_months = st.selectbox("Renouveler", [3, 6, 12], key=f"ren_{i}")
                if st.button("Renouveler", key=f"renew_{i}"):
                    new_expiry = (datetime.now() + timedelta(days=renew_months*30)).strftime("%Y.%m.%d")
                    new_key = generate_hash(lic['account'], new_expiry)

                    new_entry = {
                        "key": new_key,
                        "account": lic['account'],
                        "expiry": new_expiry,
                        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "client": lic.get('client', ''),
                        "status": "active",
                        "months": renew_months,
                    }
                    db["licenses"].append(new_entry)
                    save_db(db)
                    st.success(f"Nouvelle cle: {new_key} (expire: {new_expiry})")
                    st.rerun()

        with col_c:
            if st.button("Supprimer", key=f"del_{i}"):
                licenses.pop(i)
                save_db(db)
                st.rerun()
