import streamlit as st
import pandas as pd
import plotly.express as px
from optimizer import generate_plan

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="TrackEase", page_icon="🚂", layout="wide")

# --- HEADER ---
st.title("🚂 TRACK EASE")
st.subheader("AI-Assisted Railway Maintenance Block Planner")
st.markdown("---")

# --- CONTROLS (Left Sidebar) ---
st.sidebar.header("Planner Controls")
section = st.sidebar.selectbox("Select Railway Section:", ["Section_AB", "Section_BC", "Section_CD"])
generate_btn = st.sidebar.button("Generate Optimized Plan")

# --- MAIN DASHBOARD ---
if generate_btn:
    # Show a loading spinner while the AI thinks
    with st.spinner("Analyzing train schedules and maintenance requests..."):
        
        # Call our logic from optimizer.py
        plan, message = generate_plan(section)

        if plan is None:
            # If no train-free gap is found, show an error
            st.error(f"⚠️ {message}")
        else:
            # If successful, show the results!
            st.success("✅ Optimal Maintenance Block Generated Successfully!")

            # --- TOP METRICS ---
            col1, col2, col3, col4 = st.columns(4)
            window_str = f"{plan['window']['window_start']} - {plan['window']['window_end']}"
            
            col1.metric("Recommended Block", window_str)
            col2.metric("Block Duration", f"{plan['window']['duration_hr']:.2f} Hours")
            col3.metric("Tasks Combined", len(plan['tasks']))
            col4.metric("Train Conflicts", "0 (Safe Window)")

            # --- TASK TABLE ---
            st.markdown("### 📋 Scheduled Tasks in this Block")
            display_df = plan['tasks'][['Department', 'Task_Type', 'Duration_hr', 'Priority_Score']]
            st.dataframe(display_df, use_container_width=True)

            # --- WHY THIS BLOCK? ---
            st.markdown("### 🧠 Why this block?")
            st.info("""
            - **No scheduled train conflict:** Identified a natural gap between train services.
            - **Required duration available:** The gap is large enough for the longest parallel task.
            - **High-priority work included:** Tasks sorted by safety criticality and urgency.
            - **Compatible tasks coordinated:** Engineering, Electrical, and S&T tasks safely combined.
            """)

            # --- BEFORE VS AFTER IMPACT ---
            st.markdown("---")
            st.markdown("### 📊 Impact (Before vs After)")

            before_hrs = plan['before_duration_hr']
            after_hrs = plan['after_duration_hr']
            saved_hrs = plan['time_saved_hr']

            metric_col1, metric_col2, metric_col3 = st.columns(3)
            metric_col1.metric("Manual Planning (Separate Blocks)", f"{before_hrs:.2f} Hours")
            metric_col2.metric("TrackEase (AI Integrated Block)", f"{after_hrs:.2f} Hours")
            metric_col3.metric("Track Time Saved", f"{saved_hrs:.2f} Hours")

            # --- CHART ---
            df_chart = pd.DataFrame({
                "Planning Method": ["Manual (Separate)", "TrackEase (Integrated)"],
                "Hours Required": [before_hrs, after_hrs]
            })
            
            fig = px.bar(df_chart, x="Planning Method", y="Hours Required", color="Planning Method",
                         title="Track Block Time Reduction", text="Hours Required")
            st.plotly_chart(fig, use_container_width=True)

            # Disclaimer for judges
            st.caption("Note: Results illustrated using synthetic data for SIH26027 internal MVP demonstration.")
else:
    # Message shown when the app first opens
    st.info("👈 Select a section and click 'Generate Optimized Plan' from the sidebar to begin.")