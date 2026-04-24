import streamlit as st
import json
from pathlib import Path
from datetime import datetime
import sys

sys.path.append(str(Path(__file__).parent.parent))
from style import CUSTOM_CSS, metric_card, alert_card, section_header

st.set_page_config(page_title="Espace Partenaire", page_icon="🤝", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

AFFILIATE_DB = Path(__file__).parent.parent.parent / 'data' / 'affiliates.json'

def load_affiliates():
    if AFFILIATE_DB.exists():
        with open(AFFILIATE_DB) as f:
            return json.load(f)
    return {"affiliates": [], "referrals": []}

# ============================================================
st.markdown("""
<div class="hero">
    <h1>🤝 Espace Partenaire</h1>
    <p>Suivez vos parrainages et commissions</p>
</div>
""", unsafe_allow_html=True)

ref_code = st.text_input("🔑 Votre code partenaire", placeholder="CH-XXXX-XXXX")

if not ref_code:
    st.markdown("""
    <div class="alert-card alert-info">
        Entrez votre code partenaire pour acceder a vos statistiques.
    </div>
    """, unsafe_allow_html=True)

    st.markdown(section_header("Devenir Partenaire"), unsafe_allow_html=True)
    st.markdown("""
    <div class="pricing-card" style="text-align:left;max-width:600px;">
        <div class="plan" style="text-align:center;">Programme Partenaire CrashHunter</div>
        <div style="margin-top:20px;color:#8892a4;line-height:1.8;">
            Gagnez entre <strong style="color:#00d4aa;">20% et 40%</strong> de commission sur chaque vente !<br><br>
            <strong style="color:#e8eaed;">Comment ca marche :</strong><br>
            1. Vous recevez un code de parrainage unique<br>
            2. Vous partagez CrashHunter avec votre communaute<br>
            3. Les clients mentionnent votre code a l'achat<br>
            4. Vous recevez votre commission automatiquement<br><br>
            <strong style="color:#e8eaed;">Exemple :</strong><br>
            Un client achete le plan Pro (6 mois) a $80<br>
            Avec 30% de commission = <strong style="color:#00d4aa;">$24 pour vous</strong><br>
            10 clients par mois = <strong style="color:#00d4aa;">$240/mois</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("")
    st.markdown("""
    <div class="alert-card alert-success">
        📱 Contactez-nous pour rejoindre le programme :<br>
        WhatsApp : +XX XXX XXX XXX | Telegram : @CrashHunterBot
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ============================================================
# FIND AFFILIATE
# ============================================================
db = load_affiliates()
affiliate = None
for a in db['affiliates']:
    if a['ref_code'] == ref_code:
        affiliate = a
        break

if not affiliate:
    st.markdown(alert_card("❌ Code partenaire non reconnu", "danger"), unsafe_allow_html=True)
    st.stop()

# ============================================================
# PARTNER DASHBOARD
# ============================================================
st.markdown(alert_card(f"✅ Bienvenue <strong>{affiliate['name']}</strong> !", "success"), unsafe_allow_html=True)

referrals = [r for r in db['referrals'] if r['affiliate_code'] == ref_code]
total_commission = sum(r['commission'] for r in referrals)
paid = sum(r['commission'] for r in referrals if r.get('paid'))
pending = total_commission - paid

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(metric_card("Parrainages", len(referrals), color="blue"), unsafe_allow_html=True)
with c2:
    st.markdown(metric_card("Commission Totale", f"${total_commission:.0f}", color="purple"), unsafe_allow_html=True)
with c3:
    st.markdown(metric_card("Deja Recu", f"${paid:.0f}", color="green"), unsafe_allow_html=True)
with c4:
    st.markdown(metric_card("En Attente", f"${pending:.0f}", color="yellow"), unsafe_allow_html=True)

# Details
st.markdown(section_header("Vos Informations"), unsafe_allow_html=True)
st.markdown(f"""
<div style="background:#111827;border:1px solid #1e2d3d;border-radius:10px;padding:20px;">
    <div style="display:flex;justify-content:space-between;">
        <div><strong style="color:#8892a4;">Code :</strong> <span style="color:#45b7d1;font-size:1.2em;">{affiliate['ref_code']}</span></div>
        <div><strong style="color:#8892a4;">Commission :</strong> <span style="color:#00d4aa;">{affiliate['commission_pct']}%</span></div>
        <div><strong style="color:#8892a4;">Depuis :</strong> <span style="color:#e8eaed;">{affiliate['created']}</span></div>
    </div>
</div>
""", unsafe_allow_html=True)

# Referral history
if referrals:
    st.markdown(section_header("Historique des Parrainages"), unsafe_allow_html=True)
    for r in sorted(referrals, key=lambda x: x['date'], reverse=True):
        paid_badge = "Paye ✅" if r.get('paid') else "En attente ⏳"
        paid_color = "#00d4aa" if r.get('paid') else "#ffa502"
        st.markdown(f"""
        <div style="background:#111827;border:1px solid #1e2d3d;border-radius:10px;padding:12px 20px;margin:5px 0;display:flex;justify-content:space-between;align-items:center;">
            <span style="color:#e8eaed;">{r['client_name']}</span>
            <span style="color:#8892a4;">{r['date']}</span>
            <span style="color:#a29bfe;">Plan ${r['plan_amount']}</span>
            <span style="color:#00d4aa;font-weight:700;">+${r['commission']:.0f}</span>
            <span style="color:{paid_color};">{paid_badge}</span>
        </div>
        """, unsafe_allow_html=True)
else:
    st.markdown(alert_card("Aucun parrainage pour le moment. Partagez votre code !", "info"), unsafe_allow_html=True)

# Tips
st.markdown(section_header("Conseils pour Gagner Plus"), unsafe_allow_html=True)
st.markdown("""
<div class="alert-card alert-info" style="line-height:1.8;">
    💡 <strong>Astuces pour maximiser vos commissions :</strong><br>
    • Partagez les resultats de backtest (screenshots)<br>
    • Montrez le dashboard en video<br>
    • Proposez un essai de 1 semaine aux hesitants<br>
    • Creez du contenu sur les indices Crash de Deriv<br>
    • Ciblez les traders qui connaissent deja Deriv
</div>
""", unsafe_allow_html=True)
