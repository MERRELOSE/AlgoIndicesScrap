import streamlit as st
import json
import uuid
from pathlib import Path
from datetime import datetime
import sys

sys.path.append(str(Path(__file__).parent.parent))
from style import CUSTOM_CSS, metric_card, alert_card, section_header

st.set_page_config(page_title="Parrainage", page_icon="🤝", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

if not st.session_state.get('admin_auth'):
    st.warning("Connectez-vous depuis la page d'accueil")
    st.stop()

AFFILIATE_DB = Path(__file__).parent.parent.parent / 'data' / 'affiliates.json'
LICENSE_DB = Path(__file__).parent.parent.parent / 'MT5_EA' / 'license' / 'licenses_db.json'

def load_affiliates():
    if AFFILIATE_DB.exists():
        with open(AFFILIATE_DB) as f:
            return json.load(f)
    return {"affiliates": [], "referrals": []}

def save_affiliates(data):
    AFFILIATE_DB.parent.mkdir(parents=True, exist_ok=True)
    with open(AFFILIATE_DB, 'w') as f:
        json.dump(data, f, indent=2)

def load_licenses():
    if LICENSE_DB.exists():
        with open(LICENSE_DB) as f:
            return json.load(f).get('licenses', [])
    return []

def generate_ref_code(name):
    """Generate unique referral code from name"""
    clean = name.upper().replace(' ', '')[:4]
    uid = uuid.uuid4().hex[:4].upper()
    return f"CH-{clean}-{uid}"

db = load_affiliates()

# ============================================================
# HEADER
# ============================================================
st.markdown('<div class="section-header" style="font-size:1.8em;border:none;">🤝 Systeme de Parrainage</div>', unsafe_allow_html=True)

# ============================================================
# KPIs
# ============================================================
affiliates = db.get('affiliates', [])
referrals = db.get('referrals', [])
total_commissions = sum(r.get('commission', 0) for r in referrals)
paid_commissions = sum(r.get('commission', 0) for r in referrals if r.get('paid'))
pending_commissions = total_commissions - paid_commissions

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(metric_card("Partenaires", len(affiliates), color="blue"), unsafe_allow_html=True)
with c2:
    st.markdown(metric_card("Parrainages", len(referrals), color="green"), unsafe_allow_html=True)
with c3:
    st.markdown(metric_card("Commissions Totales", f"${total_commissions:.0f}", color="purple"), unsafe_allow_html=True)
with c4:
    st.markdown(metric_card("A Payer", f"${pending_commissions:.0f}", color="yellow"), unsafe_allow_html=True)
with c5:
    conv_rate = len(referrals) / max(1, sum(a.get('clicks', 0) for a in affiliates)) * 100
    st.markdown(metric_card("Taux Conversion", f"{conv_rate:.1f}%", color="green"), unsafe_allow_html=True)

st.markdown("")

# ============================================================
# CREATE AFFILIATE
# ============================================================
st.markdown(section_header("Ajouter un Partenaire"), unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    aff_name = st.text_input("Nom du partenaire")
with col2:
    aff_contact = st.text_input("Contact (WhatsApp/Telegram)")
with col3:
    aff_commission = st.selectbox("Commission (%)", [20, 25, 30, 35, 40])

col4, col5 = st.columns(2)
with col4:
    aff_platform = st.selectbox("Plateforme", ["YouTube", "Telegram", "TikTok", "Instagram", "Facebook", "Twitter/X", "Autre"])
with col5:
    aff_followers = st.text_input("Audience estimee", placeholder="ex: 5000 abonnes")

if st.button("Creer le partenaire", type="primary"):
    if not aff_name:
        st.error("Entrez un nom")
    else:
        ref_code = generate_ref_code(aff_name)

        new_affiliate = {
            "id": str(uuid.uuid4())[:8],
            "name": aff_name,
            "contact": aff_contact,
            "commission_pct": aff_commission,
            "ref_code": ref_code,
            "platform": aff_platform,
            "followers": aff_followers,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "clicks": 0,
            "status": "active",
        }

        db['affiliates'].append(new_affiliate)
        save_affiliates(db)

        st.success(f"Partenaire cree !")
        st.markdown(f"""
        <div class="license-card">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <div style="color:#00d4aa;font-size:1.3em;font-weight:700;">{aff_name}</div>
                    <div style="color:#8892a4;margin-top:5px;">{aff_platform} | {aff_followers}</div>
                </div>
                <div style="text-align:right;">
                    <div style="color:#8892a4;font-size:0.9em;">Code de parrainage :</div>
                    <div style="color:#45b7d1;font-size:1.5em;font-weight:700;">{ref_code}</div>
                    <div style="color:#8892a4;font-size:0.9em;margin-top:5px;">Commission : {aff_commission}%</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"""
        **Message a envoyer au partenaire :**
        ```
Bonjour {aff_name},

Bienvenue dans le programme partenaire CrashHunter !

Votre code de parrainage : {ref_code}
Commission : {aff_commission}% sur chaque vente

Quand un client vous contacte, demandez-lui de mentionner
votre code "{ref_code}" lors de l'achat.

Vous recevrez {aff_commission}% de chaque vente generee.

Lien vers l'espace client : [votre URL]

Cordialement,
CrashHunter Team
        ```
        """)
        st.rerun()

# ============================================================
# REGISTER REFERRAL (when a sale happens)
# ============================================================
st.markdown(section_header("Enregistrer un Parrainage"), unsafe_allow_html=True)

st.markdown("""
<div class="alert-card alert-info">
    Quand un client achete via un partenaire, enregistrez le parrainage ici pour calculer la commission.
</div>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
with col1:
    aff_codes = [a['ref_code'] + f" ({a['name']})" for a in affiliates]
    if aff_codes:
        selected_aff = st.selectbox("Code partenaire", aff_codes)
    else:
        st.info("Aucun partenaire")
        selected_aff = None
with col2:
    ref_client = st.text_input("Nom du client refere")
with col3:
    ref_plan = st.selectbox("Plan achete", ["3 mois - $70", "6 mois - $100", "12 mois - $150"])
    ref_amount = int(ref_plan.split("$")[1])

if selected_aff and st.button("Enregistrer le parrainage"):
    ref_code_only = selected_aff.split(" (")[0]

    # Find affiliate
    affiliate = None
    for a in affiliates:
        if a['ref_code'] == ref_code_only:
            affiliate = a
            break

    if affiliate:
        commission = ref_amount * affiliate['commission_pct'] / 100

        referral = {
            "id": str(uuid.uuid4())[:8],
            "affiliate_code": ref_code_only,
            "affiliate_name": affiliate['name'],
            "client_name": ref_client,
            "plan_amount": ref_amount,
            "commission_pct": affiliate['commission_pct'],
            "commission": commission,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "paid": False,
        }

        db['referrals'].append(referral)
        save_affiliates(db)

        st.success(f"Parrainage enregistre ! Commission de ${commission:.0f} pour {affiliate['name']}")
        st.rerun()

# ============================================================
# AFFILIATE LIST
# ============================================================
st.markdown(section_header("Partenaires"), unsafe_allow_html=True)

for aff in affiliates:
    # Count referrals for this affiliate
    aff_refs = [r for r in referrals if r['affiliate_code'] == aff['ref_code']]
    aff_commission = sum(r['commission'] for r in aff_refs)
    aff_pending = sum(r['commission'] for r in aff_refs if not r.get('paid'))
    aff_paid = aff_commission - aff_pending

    with st.expander(f"{'🟢' if aff['status']=='active' else '🔴'} {aff['name']} — {aff['ref_code']} ({aff['platform']})"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown(metric_card("Parrainages", len(aff_refs), color="blue"), unsafe_allow_html=True)
        with c2:
            st.markdown(metric_card("Commission Totale", f"${aff_commission:.0f}", color="purple"), unsafe_allow_html=True)
        with c3:
            st.markdown(metric_card("A Payer", f"${aff_pending:.0f}", color="yellow"), unsafe_allow_html=True)
        with c4:
            st.markdown(metric_card("Deja Paye", f"${aff_paid:.0f}", color="green"), unsafe_allow_html=True)

        st.markdown(f"""
        **Contact:** {aff['contact']} | **Audience:** {aff['followers']} | **Commission:** {aff['commission_pct']}%
        """)

        # Pay button
        if aff_pending > 0:
            if st.button(f"Marquer ${aff_pending:.0f} comme paye", key=f"pay_{aff['id']}"):
                for r in db['referrals']:
                    if r['affiliate_code'] == aff['ref_code'] and not r.get('paid'):
                        r['paid'] = True
                save_affiliates(db)
                st.success(f"${aff_pending:.0f} marque comme paye pour {aff['name']}")
                st.rerun()

        # Referral history
        if aff_refs:
            st.markdown("**Historique des parrainages :**")
            for r in sorted(aff_refs, key=lambda x: x['date'], reverse=True):
                paid_badge = '<span class="signal-badge badge-strong">Paye</span>' if r.get('paid') else '<span class="signal-badge badge-ok">A payer</span>'
                st.markdown(f"""
                <div style="background:#0d1321;border:1px solid #1e2d3d;border-radius:8px;padding:8px 15px;margin:3px 0;display:flex;justify-content:space-between;align-items:center;font-size:0.9em;">
                    <span style="color:#e8eaed;">{r['client_name']}</span>
                    <span style="color:#8892a4;">{r['date']}</span>
                    <span style="color:#a29bfe;">${r['plan_amount']} -> ${r['commission']:.0f} commission</span>
                    <span>{paid_badge}</span>
                </div>
                """, unsafe_allow_html=True)

# ============================================================
# COMMISSIONS SUMMARY
# ============================================================
if referrals:
    st.markdown(section_header("Resume des Commissions"), unsafe_allow_html=True)

    # By affiliate
    summary = {}
    for r in referrals:
        name = r['affiliate_name']
        if name not in summary:
            summary[name] = {'total': 0, 'paid': 0, 'pending': 0, 'count': 0}
        summary[name]['total'] += r['commission']
        summary[name]['count'] += 1
        if r.get('paid'):
            summary[name]['paid'] += r['commission']
        else:
            summary[name]['pending'] += r['commission']

    for name, s in sorted(summary.items(), key=lambda x: -x[1]['total']):
        st.markdown(f"""
        <div style="background:#111827;border:1px solid #1e2d3d;border-radius:10px;padding:12px 20px;margin:5px 0;display:flex;justify-content:space-between;align-items:center;">
            <span style="color:#e8eaed;font-weight:600;">{name}</span>
            <span style="color:#8892a4;">{s['count']} ventes</span>
            <span style="color:#a29bfe;">Total: ${s['total']:.0f}</span>
            <span style="color:#00d4aa;">Paye: ${s['paid']:.0f}</span>
            <span style="color:#ffa502;">A payer: ${s['pending']:.0f}</span>
        </div>
        """, unsafe_allow_html=True)
