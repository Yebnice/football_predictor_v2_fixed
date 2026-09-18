from datetime import datetime, timedelta, timezone
import html
import json
import sys
from pathlib import Path

# Streamlit Cloud executes a script inside the frontend/ directory, so the
# repository root is not guaranteed to be on sys.path. Add it explicitly so
# imports such as `from app.config import settings` work in cloud deployment.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd

from app.config import settings
from app.data_providers import build_provider_from_settings
from app.engine import FootballProbabilityEngine
from app.corners_cards import CornersCardsEngine
from app.slips import SlipGenerator
from app.services.ai_groq import GroqExplainer
from app.store import Store
from app.auth import AuthConfig, hash_password, verify_password
from app.admin_board import bootstrap_admin, serialize_tip

def esc(value) -> str:
    """Escape a value before interpolating it into an unsafe_allow_html
    st.markdown() block. Provider team/league names, admin-authored tip text,
    and Groq's generated explanation are all attacker-influenceable strings
    that were previously inserted into raw HTML with no escaping — this closes
    that XSS path without touching the templates' own static markup/CSS."""
    return html.escape(str(value), quote=True)


# Modern UI Configuration
st.set_page_config(
    page_title=settings.app_name,
    layout="wide",
    page_icon="⚽",
    initial_sidebar_state="expanded"
)

# Custom CSS for a warm, calm, Claude-inspired look — flat cream surfaces,
# a single terracotta accent used sparingly for primary actions and
# high-confidence states, soft hairline borders instead of heavy drop
# shadows, and grouped, plainly-labeled sidebar sections.
st.markdown("""
<style>
    /* Main theme colors and typography */
    :root {
        --primary-color: #D97757;
        --secondary-color: #BD5B3A;
        --accent-color: #D97757;
        --success-color: #3D8B5F;
        --warning-color: #C17F2E;
        --danger-color: #C1503D;
        --background-dark: #F5F4ED;
        --background-card: #FFFFFF;
        --background-card-alt: #F0EEE5;
        --text-primary: #1F1E1D;
        --text-secondary: #6B6862;
        --border-color: #E5E2D6;
    }

    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    }

    /* Global styles */
    .stApp {
        background: var(--background-dark);
    }

    /* Custom card styling */
    .prediction-card {
        background: var(--background-card);
        border: 1px solid var(--border-color);
        border-radius: 14px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 1px 2px rgba(31, 30, 29, 0.04);
        transition: border-color 0.2s, box-shadow 0.2s;
    }

    .prediction-card:hover {
        border-color: var(--accent-color);
        box-shadow: 0 2px 8px rgba(31, 30, 29, 0.06);
    }

    /* Progress bar styling */
    .probability-bar {
        height: 8px;
        border-radius: 4px;
        background: linear-gradient(90deg, var(--primary-color), var(--secondary-color));
        transition: width 0.3s ease;
    }

    /* Team logo placeholder */
    .team-logo {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--primary-color);
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: white;
    }

    /* Status badges */
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
    }

    .status-high { background: var(--success-color); color: white; }
    .status-medium { background: var(--warning-color); color: white; }
    .status-low { background: var(--danger-color); color: white; }

    /* Animated counter */
    @keyframes countUp {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }

    .animated-value {
        animation: countUp 0.3s ease-out;
    }

    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .prediction-card {
            padding: 1rem;
            margin: 0.5rem 0;
        }
    }

    /* Custom button styling */
    .stButton > button {
        background: linear-gradient(135deg, var(--primary-color), var(--secondary-color));
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        transition: all 0.2s;
    }

    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(217, 119, 87, 0.35);
    }

    /* Custom selectbox styling */
    .stSelectbox > div > div {
        background: var(--background-card);
        border: 1px solid var(--border-color);
        border-radius: 8px;
    }

    /* Data table styling */
    .stDataFrame {
        background: var(--background-card);
        border: 1px solid var(--border-color);
        border-radius: 8px;
        overflow: hidden;
    }

    /* Sidebar styling — stable data-testid selector, not a hashed class
       name (those change on every Streamlit release and stop matching). */
    [data-testid="stSidebar"] {
        background: var(--background-card-alt);
        border-right: 1px solid var(--border-color);
    }

    /* Headers */
    h1, h2, h3 {
        color: var(--text-primary);
        font-weight: 600;
    }

    /* Captions and text */
    .stCaption {
        color: var(--text-secondary);
    }

    /* Small sentence-case section labels used in the sidebar/settings
       groups, in place of ALL-CAPS eyebrow labels. */
    .settings-group-label {
        color: var(--text-secondary);
        font-size: 0.8rem;
        font-weight: 500;
        margin: 1.25rem 0 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Initialize components
# Streamlit reruns this script on widget interactions. Cache the provider as a
# resource so HTTP clients and provider TTL caches survive reruns; otherwise a
# simple click could recreate the provider and burn through free API quotas.
@st.cache_resource(show_spinner=False)
def _get_cached_provider():
    return build_provider_from_settings(settings)

provider = _get_cached_provider()

def fetch_package_fixtures(start, end, required_count):
    # Composite provider can continue down the real-data chain when the first
    # source (for example, TheSportsDB free V1 with its 15-event season cap)
    # cannot supply enough matches for a package. Single providers keep their
    # normal behavior.
    if hasattr(provider, "providers"):
        return provider.fixtures(start, end, minimum=required_count)
    return provider.fixtures(start, end)

engine = FootballProbabilityEngine(settings.max_score_goals, rho=settings.dixon_coles_rho)
corners_cards_engine = CornersCardsEngine()
slips = SlipGenerator(engine, settings.min_selection_confidence, settings.rng_salt)
explainer = GroqExplainer(settings.groq_api_key, settings.groq_model)

# Modern Header
st.markdown("""
<div style="text-align: center; padding: 2rem 0;">
    <h1 style="font-size: 2.5rem; margin-bottom: 0.5rem;">⚽ Global AI Football Predictor</h1>
    <p style="color: var(--text-secondary); font-size: 1.1rem;">
        Probability-first football analytics • Multi-market predictions • AI-powered insights
    </p>
</div>
""", unsafe_allow_html=True)

# Sidebar with modern styling
with st.sidebar:
    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 0.6rem; padding: 0.25rem 0 1.25rem 0;">
        <div style="width: 32px; height: 32px; border-radius: 9px; background: var(--accent-color); display: flex; align-items: center; justify-content: center; font-size: 1rem;">⚽</div>
        <div style="font-weight: 600; color: var(--text-primary); font-size: 1.05rem;">{esc(settings.app_name)}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="settings-group-label">Prediction window</div>', unsafe_allow_html=True)
    pkg = st.selectbox(
        "Select Time Window",
        ["Daily", "Weekly", "Monthly", "Live"],
        label_visibility="collapsed",
        key="prediction_package"
    )

    st.markdown('<div class="settings-group-label">Status</div>', unsafe_allow_html=True)
    active_provider_names = getattr(provider, "provider_names", [settings.football_provider])
    provider_ok = bool(active_provider_names)
    provider_status = ", ".join(active_provider_names) if active_provider_names else "Unavailable"
    groq_ok = bool(settings.groq_api_key)
    groq_status = "Configured" if groq_ok else "Not configured"

    def _status_row(label: str, value: str, ok: bool) -> str:
        dot_color = "var(--success-color)" if ok else "var(--text-secondary)"
        return f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.35rem 0;">
            <span style="color: var(--text-secondary); font-size: 0.9rem;">{esc(label)}</span>
            <span style="display: flex; align-items: center; gap: 0.4rem; color: var(--text-primary); font-weight: 500; font-size: 0.9rem;">
                <span style="width: 6px; height: 6px; border-radius: 50%; background: {dot_color};"></span>
                {esc(value)}
            </span>
        </div>"""

    st.markdown(f"""
    <div style="background: var(--background-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 0.5rem 0.85rem;">
        {_status_row("Data provider", f"{settings.football_provider} · {provider_status}", provider_ok)}
        {_status_row("AI analysis", groq_status, groq_ok)}
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="settings-group-label">Security</div>', unsafe_allow_html=True)
    st.markdown("""
    <div style="background: var(--background-card); border: 1px solid var(--border-color); border-radius: 10px; padding: 0.85rem; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.5;">
        VIP, Appwrite, USDT, MTN MoMo and Telecel connectors are backend integration boundaries. Secrets are never exposed in the browser.
    </div>
    """, unsafe_allow_html=True)



# Calculate date range
now = datetime.now(timezone.utc)
if pkg == "Daily":
    start, end = now, now + timedelta(days=1)
    time_range = "Next 24 Hours"
elif pkg == "Weekly":
    start, end = now, now + timedelta(days=7)
    time_range = "Next 7 Days"
elif pkg == "Monthly":
    start, end = now, now + timedelta(days=31)
    time_range = "Next 31 Days"
else:
    start, end = now, now + timedelta(days=1)
    time_range = "Live Matches"

# Fetch fixtures
try:
    fixtures = provider.fixtures(start, end, live=(pkg == "Live"))
except Exception as e:
    st.error(f"Failed to fetch fixtures: {str(e)}")
    fixtures = []

# Modern fixtures header
st.markdown(f"""
<div style="display: flex; justify-content: space-between; align-items: center; margin: 2rem 0 1rem 0;">
    <div>
        <h2 style="margin: 0;">📅 {pkg} Predictions</h2>
        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">{time_range} • {len(fixtures)} fixtures available</p>
    </div>
</div>
""", unsafe_allow_html=True)

if not fixtures:
    st.markdown("""
    <div style="text-align: center; padding: 3rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 3rem; margin-bottom: 1rem;">📭</div>
        <h3 style="color: var(--text-secondary);">No Fixtures Available</h3>
        <p style="color: var(--text-secondary);">Try adjusting the time window or check your data provider configuration.</p>
    </div>
    """, unsafe_allow_html=True)
else:
    # Modern card-based fixture display
    st.markdown('<div class="fixtures-grid">', unsafe_allow_html=True)

    for i, fx in enumerate(fixtures[:10]):  # Show first 10 fixtures for performance
        best = engine.shortlist(fx, settings.min_selection_confidence, 1)
        if best:
            p = best[0]

            # Determine confidence level
            if p.probability >= 0.75:
                confidence_class = "status-high"
                confidence_label = "HIGH"
            elif p.probability >= 0.65:
                confidence_class = "status-medium"
                confidence_label = "MEDIUM"
            else:
                confidence_class = "status-low"
                confidence_label = "LOW"

            st.markdown(f"""
            <div class="prediction-card">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                    <div>
                        <h3 style="margin: 0; font-size: 1.25rem;">{esc(fx.home_team)} vs {esc(fx.away_team)}</h3>
                        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.9rem;">{esc(fx.league)}</p>
                    </div>
                    <span class="status-badge {confidence_class}">{confidence_label}</span>
                </div>

                <div style="margin-bottom: 1rem;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                        <span style="color: var(--text-secondary); font-size: 0.9rem;">{esc(p.market)} - {esc(p.selection)}</span>
                        <span style="color: var(--text-primary); font-weight: 700;" class="animated-value">{p.probability:.1%}</span>
                    </div>
                    <div class="probability-bar" style="width: {p.probability * 100}%"></div>
                </div>

                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="color: var(--text-secondary); font-size: 0.85rem;">Fair Odds:</span>
                        <span style="color: var(--text-primary); font-weight: 600; margin-left: 0.5rem;">{p.fair_odds:.2f}</span>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary);">
                        {fx.date.strftime('%Y-%m-%d %H:%M')} UTC
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # Generate package button with modern styling
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🎯 Generate Prediction Package", type="primary", use_container_width=True):
            try:
                with st.spinner("Generating predictions..."):
                    package_required = {"Daily": 5, "Weekly": 20, "Monthly": 35}.get(pkg, 0)
                    package_fixtures = fetch_package_fixtures(start, end, package_required)
                    if pkg == "Daily":
                        generated = [slips.daily(package_fixtures)]
                    elif pkg == "Weekly":
                        generated = slips.weekly(package_fixtures)
                    elif pkg == "Monthly":
                        generated = slips.monthly(package_fixtures)
                    else:
                        generated = []

                for s in generated:
                    st.markdown(f"""
                    <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border: 1px solid var(--primary-color);">
                        <h3 style="margin: 0 0 1rem 0;">📊 {s.period.title()} Slip #{s.slip_number}</h3>
                        <p style="color: var(--text-secondary); margin: 0 0 1rem 0;">{len(s.selections)} high-confidence selections</p>
                    </div>
                    """, unsafe_allow_html=True)

                    st.dataframe(s.selections, use_container_width=True, hide_index=True)

                    st.download_button(
                        "📥 Download Package JSON",
                        json.dumps(s.__dict__, default=str),
                        file_name=f"{s.period}_slip_{s.slip_number}.json",
                        mime="application/json",
                        use_container_width=True
                    )
            except Exception as exc:
                st.error(f"❌ Failed to generate package: {str(exc)}")

    # Match explanation section
    st.markdown("---")
    st.markdown("""
    <div style="margin: 2rem 0 1rem 0;">
        <h2 style="margin: 0;">🤖 AI Match Analysis</h2>
        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Get detailed AI-powered explanations for any match</p>
    </div>
    """, unsafe_allow_html=True)

    fixture_options = [f"{fx.home_team} vs {fx.away_team} ({fx.fixture_id})" for fx in fixtures]
    selected_match = st.selectbox("Select match to analyze", fixture_options, key="match_explanation")

    if selected_match:
        fixture_id = selected_match.split(" (")[1].rstrip(")")
        fx = next((f for f in fixtures if f.fixture_id == fixture_id), None)

        if fx:
            detailed_fx = provider.fixture_by_id(fixture_id) or fx
            ms = engine.shortlist(detailed_fx, settings.min_selection_confidence, 5)

            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("🔍 Generate AI Analysis", key=f"explain_{fixture_id}", use_container_width=True):
                    with st.spinner("Analyzing match data..."):
                        try:
                            text = explainer.explain(detailed_fx.__dict__, [m.__dict__ for m in ms])
                            st.markdown(f"""
                            <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border-left: 4px solid var(--accent-color);">
                                <h4 style="margin: 0 0 1rem 0;">📝 Analysis Results</h4>
                                <div style="color: var(--text-primary); line-height: 1.6;">
                                    {esc(text).replace(chr(10), '<br>')}
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                        except Exception as exc:
                            st.error(f"❌ Analysis failed: {str(exc)}")

    # Corners & cards section
    st.markdown("---")
    if fixtures:
        first_fixture = fixtures[0]
        detailed_first = provider.fixture_by_id(first_fixture.fixture_id) or first_fixture

        st.markdown(f"""
        <div style="margin: 2rem 0 1rem 0;">
            <h2 style="margin: 0;">📈 Corners & Cards Analysis</h2>
            <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Model estimates from team/league averages — {esc(detailed_first.home_team)} vs {esc(detailed_first.away_team)}</p>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("View detailed corners & cards predictions", expanded=False):
            st.caption("⚠️ These are model estimates from team/league corner and card averages, not scraped live match stats.")

            cc_predictions = corners_cards_engine.markets(detailed_first)

            # Group by market type
            corners_markets = [m for m in cc_predictions if "Corner" in m.market]
            cards_markets = [m for m in cc_predictions if "Card" in m.market]

            if corners_markets:
                st.markdown("### 🎯 Total Corners")
                for m in corners_markets[:6]:  # Show top 6
                    st.markdown(f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; background: var(--background-card); border-radius: 8px; margin-bottom: 0.5rem;">
                        <div>
                            <span style="color: var(--text-primary); font-weight: 600;">{esc(m.selection)}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">{esc(m.market)}</span>
                        </div>
                        <div style="text-align: right;">
                            <span style="color: var(--text-primary); font-weight: 700;">{m.probability:.1%}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">@ {m.fair_odds:.2f}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            if cards_markets:
                st.markdown("### 🟨 Total Cards")
                for m in cards_markets[:4]:  # Show top 4
                    st.markdown(f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.75rem; background: var(--background-card); border-radius: 8px; margin-bottom: 0.5rem;">
                        <div>
                            <span style="color: var(--text-primary); font-weight: 600;">{esc(m.selection)}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">{esc(m.market)}</span>
                        </div>
                        <div style="text-align: right;">
                            <span style="color: var(--text-primary); font-weight: 700;">{m.probability:.1%}</span>
                            <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">@ {m.fair_odds:.2f}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

# Analytics Dashboard Section
st.markdown("---")
st.markdown("""
<div style="margin: 2rem 0 1rem 0;">
    <h2 style="margin: 0;">📊 Analytics Dashboard</h2>
    <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Visual insights and trend analysis</p>
</div>
""", unsafe_allow_html=True)

if fixtures:
    # Prepare data for visualizations
    fixture_data = []
    for fx in fixtures[:15]:  # Analyze first 15 fixtures
        best = engine.shortlist(fx, settings.min_selection_confidence, 1)
        if best:
            p = best[0]
            fixture_data.append({
                "Match": f"{fx.home_team} vs {fx.away_team}",
                "League": fx.league,
                "Market": p.market,
                "Selection": p.selection,
                "Probability": p.probability,
                "Fair Odds": p.fair_odds,
                "Date": fx.date
            })

    if fixture_data:
        df = pd.DataFrame(fixture_data)

        # Probability Distribution Chart
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; border: 1px solid var(--border-color);">
                <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">Probability Distribution</h4>
            </div>
            """, unsafe_allow_html=True)

            fig_prob = px.histogram(
                df,
                x="Probability",
                nbins=10,
                title="Distribution of Prediction Probabilities",
                color_discrete_sequence=["#D97757"]
            )
            fig_prob.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#1F1E1D"),
                xaxis=dict(gridcolor="rgba(31,30,29,0.08)"),
                yaxis=dict(gridcolor="rgba(31,30,29,0.08)")
            )
            st.plotly_chart(fig_prob, use_container_width=True, theme="streamlit")

        with col2:
            st.markdown("""
            <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; border: 1px solid var(--border-color);">
                <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">Market Types Analysis</h4>
            </div>
            """, unsafe_allow_html=True)

            market_counts = df["Market"].value_counts()
            fig_market = px.pie(
                values=market_counts.values,
                names=market_counts.index,
                title="Prediction Market Distribution",
                color_discrete_sequence=px.colors.sequential.Oranges_r
            )
            fig_market.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#1F1E1D")
            )
            st.plotly_chart(fig_market, use_container_width=True, theme="streamlit")

        # Top Predictions Table with Visual Indicators
        st.markdown("""
        <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border: 1px solid var(--border-color);">
            <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">🏆 Top High-Confidence Predictions</h4>
        </div>
        """, unsafe_allow_html=True)

        top_predictions = df.nlargest(5, "Probability")

        for _, row in top_predictions.iterrows():
            confidence_color = "#3D8B5F" if row["Probability"] >= 0.75 else "#C17F2E" if row["Probability"] >= 0.65 else "#C1503D"

            st.markdown(f"""
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; background: var(--background-card-alt); border-radius: 8px; margin-bottom: 0.5rem; border-left: 4px solid {confidence_color};">
                <div>
                    <div style="color: var(--text-primary); font-weight: 600;">{esc(row['Match'])}</div>
                    <div style="color: var(--text-secondary); font-size: 0.85rem;">{esc(row['Market'])} - {esc(row['Selection'])}</div>
                </div>
                <div style="text-align: right;">
                    <div style="color: {confidence_color}; font-weight: 700; font-size: 1.1rem;">{row['Probability']:.1%}</div>
                    <div style="color: var(--text-secondary); font-size: 0.85rem;">@ {row['Fair Odds']:.2f}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Probability vs Odds Scatter Plot
        st.markdown("""
        <div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin: 1rem 0; border: 1px solid var(--border-color);">
            <h4 style="margin: 0 0 1rem 0; color: var(--text-primary);">📈 Probability vs Fair Odds Analysis</h4>
        </div>
        """, unsafe_allow_html=True)

        fig_scatter = px.scatter(
            df,
            x="Probability",
            y="Fair Odds",
            color="Market",
            size="Probability",
            hover_data=["Match", "Selection"],
            title="Probability vs Fair Odds Relationship",
            color_discrete_sequence=px.colors.qualitative.Bold
        )
        fig_scatter.update_layout(
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#1F1E1D"),
            xaxis=dict(gridcolor="rgba(31,30,29,0.08)", title="Probability"),
            yaxis=dict(gridcolor="rgba(31,30,29,0.08)", title="Fair Odds")
        )
        st.plotly_chart(fig_scatter, use_container_width=True, theme="streamlit")

else:
    st.info("📊 No fixture data available for analytics. Generate predictions first to see visualizations.")

# Architecture section with modern styling
st.markdown("---")
st.markdown("""
<div style="background: var(--background-card); border-radius: 12px; padding: 2rem; margin: 2rem 0; border: 1px solid var(--border-color);">
    <h3 style="margin: 0 0 1rem 0;">🏗️ System Architecture</h3>
    <div style="color: var(--text-secondary); line-height: 1.8; font-family: monospace;">
        Football APIs → Normalization → Feature/Model Layer → Score Distribution → All Markets → Value/Risk → Randomized Slips → VIP/Auth/Payments
    </div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tips board: public Free/VVIP feed + a private Admin board for authoring tips.
# Runs against the same SQLite-backed Store the FastAPI backend uses (see
# app/store.py, app/admin_board.py) — this in-process Streamlit UI is a
# convenience for local/solo operation, not a substitute for the API's own
# auth for a real multi-user deployment (the API enforces the same role
# checks server-side regardless of which UI is used).
# ---------------------------------------------------------------------------
store = Store(settings.db_path)
auth_config = AuthConfig(jwt_secret=settings.auth_jwt_secret, jwt_expiry_hours=settings.auth_jwt_expiry_hours)
bootstrap_admin(store, settings.admin_bootstrap_email, settings.admin_bootstrap_password)

st.markdown("---")
st.markdown("""
<div style="margin: 2rem 0 1rem 0;">
    <h2 style="margin: 0;">🔒 VVIP Tips Board</h2>
    <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Exclusive predictions and expert tips</p>
</div>
""", unsafe_allow_html=True)

# Modern authentication sidebar
with st.sidebar:
    st.markdown('<div class="settings-group-label" style="margin-top: 0;">Account</div>', unsafe_allow_html=True)

    if "user_id" not in st.session_state:
        st.session_state.user_id = None

    if st.session_state.user_id:
        profile = store.get_profile(st.session_state.user_id)
        if not profile:
            # A Streamlit session can outlive a database reset/redeploy. Clear
            # the stale session instead of dereferencing None and crashing the
            # whole dashboard.
            st.session_state.user_id = None
            st.rerun()
        roles = store.roles_for(st.session_state.user_id)

        st.markdown(f"""
        <div style="background: var(--background-card); border-radius: 10px; padding: 1rem; margin-bottom: 1rem; border: 1px solid var(--border-color);">
            <div style="color: var(--text-primary); font-weight: 600; margin-bottom: 0.5rem;">{esc(profile['email'])}</div>
            <div style="color: var(--text-secondary); font-size: 0.85rem;">{esc(', '.join(roles) or 'member')}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🚪 Sign Out", use_container_width=True):
            st.session_state.user_id = None
            st.rerun()
    else:
        tab_login, tab_signup = st.tabs(["🔐 Sign In", "📝 Sign Up"])

        with tab_login:
            email = st.text_input("Email", key="login_email", placeholder="your@email.com")
            password = st.text_input("Password", type="password", key="login_password", placeholder="••••••••")

            if st.button("Sign In", use_container_width=True, key="login_button"):
                profile = store.get_profile_by_email(email)
                if profile and verify_password(password, profile["password_hash"], profile["password_salt"]):
                    st.session_state.user_id = profile["user_id"]
                    st.success("✅ Successfully signed in!")
                    st.rerun()
                else:
                    st.error("❌ Invalid email or password.")

        with tab_signup:
            new_email = st.text_input("Email", key="signup_email", placeholder="your@email.com")
            new_password = st.text_input("Password (8+ characters)", type="password", key="signup_password", placeholder="••••••••")

            if st.button("Create Account", use_container_width=True, key="signup_button"):
                if store.get_profile_by_email(new_email):
                    st.error("❌ An account with that email already exists.")
                elif len(new_password) < 8:
                    st.error("❌ Password must be at least 8 characters.")
                else:
                    h, s = hash_password(new_password)
                    st.session_state.user_id = store.create_profile(new_email, h, s)
                    st.success("✅ Account created successfully!")
                    st.rerun()

current_user_id = st.session_state.get("user_id")
is_admin = bool(current_user_id and store.has_role(current_user_id, "admin"))
can_see_vvip = bool(current_user_id and (is_admin or store.has_role(current_user_id, "vvip")))

# Performance stats
tips = [serialize_tip(t, can_see_vvip) for t in store.list_tips()]
record = None
_since = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
_settled = store.settled_tips_since(_since)
_won = sum(1 for t in _settled if t["status"] == "won")
_lost = sum(1 for t in _settled if t["status"] == "lost")

st.markdown(f"""
<div style="background: var(--background-card); border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; border: 1px solid var(--border-color);">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h4 style="margin: 0; color: var(--text-primary);">Last 30 Days Performance</h4>
            <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.9rem;">Settled tips record</p>
        </div>
        <div style="text-align: right;">
            <div style="font-size: 1.5rem; font-weight: 700; color: var(--success-color);">{_won}W – {_lost}L</div>
            <div style="color: var(--text-secondary); font-size: 0.9rem;">
                {f"{_won/(_won+_lost):.0%} hit rate" if _won + _lost else "No settled tips"}
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

if not tips:
    st.markdown("""
    <div style="text-align: center; padding: 2rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 2rem; margin-bottom: 0.5rem;">📭</div>
        <p style="color: var(--text-secondary);">No tips posted yet. Check back soon!</p>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown('<div class="tips-grid">', unsafe_allow_html=True)

    for t in tips:
        status_emoji = {"won": "✅", "lost": "❌", "void": "➖", "pending": "⏳"}.get(t["status"], "")
        status_color = {"won": "var(--success-color)", "lost": "var(--danger-color)", "void": "var(--text-secondary)", "pending": "var(--warning-color)"}.get(t["status"], "var(--text-secondary)")

        if t.get("locked"):
            st.markdown(f"""
            <div class="prediction-card" style="border-left: 4px solid var(--warning-color);">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.75rem;">
                    <div>
                        <h4 style="margin: 0; font-size: 1.1rem;">{esc(t['match'])}</h4>
                        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.85rem;">{esc(t['kickoff_time'])} • {esc(t['market'])}</p>
                    </div>
                    <span style="background: var(--warning-color); color: white; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600;">🔒 VVIP</span>
                </div>
                <p style="color: var(--text-secondary); font-style: italic;">{esc(t['teaser'])}</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="prediction-card" style="border-left: 4px solid {status_color};">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.75rem;">
                    <div>
                        <h4 style="margin: 0; font-size: 1.1rem;">{esc(t['match'])}</h4>
                        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0; font-size: 0.85rem;">{esc(t['kickoff_time'])} • {esc(t['market'])}</p>
                    </div>
                    <span style="font-size: 1.25rem;">{status_emoji}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="color: var(--text-primary); font-weight: 600;">{esc(t['selection'])}</span>
                        <span style="color: var(--text-secondary); font-size: 0.85rem; margin-left: 0.5rem;">@ {esc(t.get('odds', '—'))}</span>
                    </div>
                    <span style="color: {status_color}; font-size: 0.85rem; font-weight: 600; text-transform: uppercase;">{esc(t['status'])}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

# Admin board
if is_admin:
    st.markdown("---")
    st.markdown("""
    <div style="margin: 2rem 0 1rem 0;">
        <h2 style="margin: 0;">🛠️ Admin Board</h2>
        <p style="color: var(--text-secondary); margin: 0.25rem 0 0 0;">Manage tips and member access</p>
    </div>
    """, unsafe_allow_html=True)

    # Post new tip form
    with st.expander("📝 Post New Tip", expanded=False):
        with st.form("new_tip_form"):
            st.markdown("### Create a new prediction tip")

            c1, c2 = st.columns(2)
            match = c1.text_input("Match", placeholder="e.g., Arsenal vs Chelsea")
            kickoff = c2.text_input("Kick-off Time (ISO)", value=datetime.now(timezone.utc).isoformat(), placeholder="2026-09-12T19:00:00Z")

            market = c1.text_input("Market", placeholder="e.g., 1X2, Over/Under")
            selection = c2.text_input("Selection", placeholder="e.g., Home Win, Over 2.5")

            odds = c1.number_input("Odds", min_value=1.0, step=0.01, value=1.90)
            confidence = c2.slider("Confidence Level", 0.0, 1.0, 0.6)

            notes = st.text_area("Analysis Notes", placeholder="Add your analysis and reasoning...")

            tier = st.radio("Access Tier", ["free", "vvip"], horizontal=True)

            if st.form_submit_button("🚀 Post Tip", use_container_width=True):
                try:
                    store.create_tip(
                        match=match, kickoff_time=kickoff, market=market, selection=selection,
                        odds=odds, confidence=confidence, notes=notes, tier=tier,
                        created_by=current_user_id
                    )
                    st.success("✅ Tip posted successfully!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"❌ Failed to post tip: {str(exc)}")

    # Manage existing tips
    st.markdown("### 📋 Manage Existing Tips")

    for t in store.list_tips():
        with st.expander(f"{t['match']} — {t['market']} / {t['selection']} ({t['tier']}, {t['status']})"):
            cols = st.columns(4)

            if cols[0].button("✅ Mark Won", key=f"won-{t['id']}", use_container_width=True):
                store.update_tip(t["id"], status="won")
                st.success("Marked as won!")
                st.rerun()

            if cols[1].button("❌ Mark Lost", key=f"lost-{t['id']}", use_container_width=True):
                store.update_tip(t["id"], status="lost")
                st.success("Marked as lost!")
                st.rerun()

            if cols[2].button("➖ Mark Void", key=f"void-{t['id']}", use_container_width=True):
                store.update_tip(t["id"], status="void")
                st.success("Marked as void!")
                st.rerun()

            if cols[3].button("🗑️ Delete", key=f"del-{t['id']}", use_container_width=True):
                store.delete_tip(t["id"])
                st.success("Tip deleted!")
                st.rerun()

    # Member management
    st.markdown("### 👥 Member Management")

    for m in store.list_members():
        with st.expander(f"{m['email']} — {', '.join(m['roles']) or 'member'}"):
            cols = st.columns([3, 2, 2])

            cols[0].write(f"**{m['email']}**")
            cols[1].write(f"Roles: {', '.join(m['roles']) or 'member'}")

            is_vvip = "vvip" in m["roles"]
            button_text = "🔓 Revoke VVIP" if is_vvip else "🔑 Grant VVIP"
            button_type = "secondary" if is_vvip else "primary"

            if cols[2].button(button_text, key=f"vvip-{m['user_id']}", use_container_width=True):
                if is_vvip:
                    store.revoke_role(m["user_id"], "vvip")
                    st.success("VVIP access revoked!")
                else:
                    store.grant_role(m["user_id"], "vvip")
                    st.success("VVIP access granted!")
                st.rerun()

elif current_user_id:
    st.markdown("""
    <div style="text-align: center; padding: 2rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 2rem; margin-bottom: 0.5rem;">🔒</div>
        <p style="color: var(--text-secondary);">You're signed in as a member. Ask an admin to grant VVIP access to unlock premium tips.</p>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="text-align: center; padding: 2rem; background: var(--background-card); border-radius: 12px; border: 1px dashed var(--border-color);">
        <div style="font-size: 2rem; margin-bottom: 0.5rem;">👤</div>
        <p style="color: var(--text-secondary);">Sign in from the sidebar to unlock VVIP tips you have access to.</p>
    </div>
    """, unsafe_allow_html=True)
