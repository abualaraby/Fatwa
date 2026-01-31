"""Streamlit Dashboard for Fatwa Management System."""

import sys
import json
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import Database, Ticket, TicketStatus, SourcePlatform


# Page configuration
st.set_page_config(
    page_title="Fatwa Management System",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #2c5f2d;
        text-align: center;
        padding: 1rem 0;
        border-bottom: 3px solid #2c5f2d;
        margin-bottom: 2rem;
    }
    .status-pending { background-color: #ffc107; padding: 5px 10px; border-radius: 5px; }
    .status-assigned { background-color: #17a2b8; color: white; padding: 5px 10px; border-radius: 5px; }
    .status-sent { background-color: #6f42c1; color: white; padding: 5px 10px; border-radius: 5px; }
    .status-replied { background-color: #28a745; color: white; padding: 5px 10px; border-radius: 5px; }
    .status-final { background-color: #20c997; color: white; padding: 5px 10px; border-radius: 5px; }
    .status-failed { background-color: #dc3545; color: white; padding: 5px 10px; border-radius: 5px; }
    .ticket-card {
        border: 1px solid #ddd;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
        background-color: #f9f9f9;
    }
    .metric-card {
        text-align: center;
        padding: 20px;
        border-radius: 10px;
        color: white;
        margin: 5px;
    }
</style>
""", unsafe_allow_html=True)


def load_config():
    """Load configuration file."""
    config_path = Path(__file__).parent.parent / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


def get_database():
    """Get database instance."""
    config = load_config()
    db_path = config.get("database", {}).get("path", "fatwa_tickets.db")
    # Make path relative to project root
    db_path = Path(__file__).parent.parent / db_path
    return Database(str(db_path))


def get_status_badge(status: str) -> str:
    """Get HTML badge for status."""
    status_classes = {
        "Pending": "status-pending",
        "Assigned": "status-assigned",
        "Sent_to_Shaikh": "status-sent",
        "Replied": "status-replied",
        "Final_Sent": "status-final",
        "Failed": "status-failed",
    }
    css_class = status_classes.get(status, "status-pending")
    return f'<span class="{css_class}">{status}</span>'


def main():
    """Main dashboard application."""
    # Header
    st.markdown('<h1 class="main-header">📖 Fatwa Management System</h1>', unsafe_allow_html=True)

    # Initialize database
    db = get_database()
    config = load_config()
    shaikhs = config.get("shaikhs", [])

    # Sidebar
    with st.sidebar:
        st.header("🔧 Controls")

        # Navigation
        page = st.radio(
            "Navigate to:",
            ["📊 Dashboard", "📋 All Tickets", "➕ New Ticket", "⚙️ Settings"]
        )

        st.divider()

        # Quick stats
        st.header("📈 Quick Stats")
        counts = db.get_ticket_counts()
        total = sum(counts.values())

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total", total)
            st.metric("Pending", counts.get("Pending", 0))
        with col2:
            st.metric("Replied", counts.get("Replied", 0))
            st.metric("Completed", counts.get("Final_Sent", 0))

    # Main content based on page selection
    if page == "📊 Dashboard":
        render_dashboard(db, shaikhs)
    elif page == "📋 All Tickets":
        render_tickets_list(db, shaikhs)
    elif page == "➕ New Ticket":
        render_new_ticket(db, shaikhs)
    elif page == "⚙️ Settings":
        render_settings(config)


def render_dashboard(db: Database, shaikhs: list):
    """Render the main dashboard view."""
    st.header("📊 Dashboard Overview")

    # Metrics row
    counts = db.get_ticket_counts()

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.markdown(
            '<div class="metric-card" style="background-color: #ffc107;">'
            f'<h2>{counts.get("Pending", 0)}</h2><p>Pending</p></div>',
            unsafe_allow_html=True
        )
    with col2:
        st.markdown(
            '<div class="metric-card" style="background-color: #17a2b8;">'
            f'<h2>{counts.get("Assigned", 0)}</h2><p>Assigned</p></div>',
            unsafe_allow_html=True
        )
    with col3:
        st.markdown(
            '<div class="metric-card" style="background-color: #6f42c1;">'
            f'<h2>{counts.get("Sent_to_Shaikh", 0)}</h2><p>Awaiting Reply</p></div>',
            unsafe_allow_html=True
        )
    with col4:
        st.markdown(
            '<div class="metric-card" style="background-color: #28a745;">'
            f'<h2>{counts.get("Replied", 0)}</h2><p>Replied</p></div>',
            unsafe_allow_html=True
        )
    with col5:
        st.markdown(
            '<div class="metric-card" style="background-color: #20c997;">'
            f'<h2>{counts.get("Final_Sent", 0)}</h2><p>Completed</p></div>',
            unsafe_allow_html=True
        )
    with col6:
        st.markdown(
            '<div class="metric-card" style="background-color: #dc3545;">'
            f'<h2>{counts.get("Failed", 0)}</h2><p>Failed</p></div>',
            unsafe_allow_html=True
        )

    st.divider()

    # Two columns for pending and awaiting reply
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🕐 Pending Assignment")
        pending_tickets = db.get_pending_tickets()

        if pending_tickets:
            for ticket in pending_tickets[:5]:
                with st.container():
                    st.markdown(f"**#{ticket.id}** - {ticket.sender_name}")
                    st.write(ticket.question_text[:150] + "..." if len(ticket.question_text) > 150 else ticket.question_text)
                    st.caption(f"📍 {ticket.source_platform.value} | {ticket.created_at.strftime('%Y-%m-%d %H:%M')}")

                    # Assign Shaikh
                    shaikh_options = {s["name"]: s for s in shaikhs}
                    selected = st.selectbox(
                        "Assign to:",
                        options=["-- Select Shaikh --"] + list(shaikh_options.keys()),
                        key=f"assign_{ticket.id}"
                    )

                    if selected != "-- Select Shaikh --":
                        if st.button("Assign", key=f"btn_{ticket.id}"):
                            shaikh = shaikh_options[selected]
                            db.assign_shaikh(ticket.id, shaikh["id"], shaikh["phone"])
                            st.success(f"Assigned to {selected}")
                            st.rerun()

                    st.divider()
        else:
            st.info("No pending tickets")

    with col2:
        st.subheader("💬 Awaiting Shaikh Reply")
        awaiting_tickets = db.get_awaiting_reply_tickets()

        if awaiting_tickets:
            for ticket in awaiting_tickets[:5]:
                with st.container():
                    st.markdown(f"**#{ticket.id}** - {ticket.sender_name}")
                    st.write(ticket.question_text[:150] + "..." if len(ticket.question_text) > 150 else ticket.question_text)

                    # Find Shaikh name
                    shaikh_name = next(
                        (s["name"] for s in shaikhs if s.get("phone") == ticket.assigned_shaikh_phone),
                        "Unknown"
                    )
                    st.caption(f"👤 Assigned to: {shaikh_name}")

                    if ticket.sent_to_shaikh_at:
                        st.caption(f"📤 Sent: {ticket.sent_to_shaikh_at.strftime('%Y-%m-%d %H:%M')}")

                    st.divider()
        else:
            st.info("No tickets awaiting reply")

    # Ready to dispatch section
    st.subheader("✅ Ready to Dispatch")
    replied_tickets = db.get_replied_tickets()

    if replied_tickets:
        for ticket in replied_tickets[:5]:
            col1, col2, col3 = st.columns([3, 2, 1])

            with col1:
                st.markdown(f"**#{ticket.id}** - {ticket.sender_name}")
                st.caption(f"📍 {ticket.source_platform.value}")

            with col2:
                st.write(f"Answer: {ticket.answer_text[:100]}..." if len(ticket.answer_text or "") > 100 else ticket.answer_text)

            with col3:
                if st.button("Dispatch", key=f"dispatch_{ticket.id}"):
                    st.info("Dispatch functionality requires running the main application")
    else:
        st.info("No tickets ready to dispatch")


def render_tickets_list(db: Database, shaikhs: list):
    """Render the full tickets list view."""
    st.header("📋 All Tickets")

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        status_filter = st.selectbox(
            "Filter by Status:",
            ["All"] + [s.value for s in TicketStatus]
        )

    with col2:
        platform_filter = st.selectbox(
            "Filter by Platform:",
            ["All"] + [p.value for p in SourcePlatform]
        )

    with col3:
        search_query = st.text_input("🔍 Search:", placeholder="Search by question or name...")

    # Get tickets
    if search_query:
        tickets = db.search_tickets(search_query)
    else:
        tickets = db.get_all_tickets(limit=100)

    # Apply filters
    if status_filter != "All":
        tickets = [t for t in tickets if t.status.value == status_filter]

    if platform_filter != "All":
        tickets = [t for t in tickets if t.source_platform.value == platform_filter]

    # Display as table
    if tickets:
        # Convert to DataFrame
        data = []
        for t in tickets:
            shaikh_name = next(
                (s["name"] for s in shaikhs if s.get("phone") == t.assigned_shaikh_phone),
                "-"
            )
            data.append({
                "ID": t.id,
                "Status": t.status.value,
                "Platform": t.source_platform.value,
                "Sender": t.sender_name,
                "Question": t.question_text[:80] + "..." if len(t.question_text) > 80 else t.question_text,
                "Assigned To": shaikh_name,
                "Created": t.created_at.strftime("%Y-%m-%d %H:%M"),
            })

        df = pd.DataFrame(data)

        # Display with selection
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
        )

        # Ticket detail view
        st.subheader("📝 Ticket Details")
        selected_id = st.number_input("Enter Ticket ID to view details:", min_value=1, step=1)

        if selected_id:
            ticket = db.get_ticket(int(selected_id))
            if ticket:
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown(f"### Ticket #{ticket.id}")
                    st.markdown(get_status_badge(ticket.status.value), unsafe_allow_html=True)
                    st.write(f"**Platform:** {ticket.source_platform.value}")
                    st.write(f"**Sender:** {ticket.sender_name}")
                    st.write(f"**Contact:** {ticket.sender_contact}")
                    st.write(f"**Created:** {ticket.created_at}")

                with col2:
                    if ticket.assigned_shaikh_phone:
                        shaikh_name = next(
                            (s["name"] for s in shaikhs if s.get("phone") == ticket.assigned_shaikh_phone),
                            "Unknown"
                        )
                        st.write(f"**Assigned to:** {shaikh_name}")

                    if ticket.sent_to_shaikh_at:
                        st.write(f"**Sent to Shaikh:** {ticket.sent_to_shaikh_at}")

                    if ticket.replied_at:
                        st.write(f"**Replied:** {ticket.replied_at}")

                    if ticket.final_sent_at:
                        st.write(f"**Final sent:** {ticket.final_sent_at}")

                st.markdown("#### Question:")
                st.info(ticket.question_text)

                if ticket.answer_text:
                    st.markdown("#### Answer:")
                    st.success(ticket.answer_text)

                if ticket.error_message:
                    st.markdown("#### Error:")
                    st.error(ticket.error_message)

                # Actions
                st.markdown("#### Actions")
                col1, col2, col3 = st.columns(3)

                with col1:
                    if ticket.status == TicketStatus.PENDING:
                        shaikh_options = {s["name"]: s for s in shaikhs}
                        selected = st.selectbox(
                            "Assign to Shaikh:",
                            options=["-- Select --"] + list(shaikh_options.keys()),
                            key=f"detail_assign_{ticket.id}"
                        )
                        if selected != "-- Select --":
                            if st.button("Assign", key=f"detail_btn_{ticket.id}"):
                                shaikh = shaikh_options[selected]
                                db.assign_shaikh(ticket.id, shaikh["id"], shaikh["phone"])
                                st.success("Assigned!")
                                st.rerun()

                with col2:
                    if ticket.status == TicketStatus.REPLIED:
                        if st.button("Mark as Final Sent"):
                            db.mark_final_sent(ticket.id)
                            st.success("Marked as Final Sent")
                            st.rerun()

                with col3:
                    if ticket.status == TicketStatus.FAILED:
                        if st.button("Retry"):
                            ticket.status = TicketStatus.ASSIGNED
                            ticket.error_message = None
                            db.update_ticket(ticket)
                            st.success("Reset for retry")
                            st.rerun()
            else:
                st.warning(f"Ticket #{selected_id} not found")
    else:
        st.info("No tickets found matching the criteria")


def render_new_ticket(db: Database, shaikhs: list):
    """Render the manual ticket creation form."""
    st.header("➕ Create New Ticket")

    st.info("Use this form to manually add a ticket (e.g., from phone call or in-person inquiry)")

    with st.form("new_ticket_form"):
        col1, col2 = st.columns(2)

        with col1:
            sender_name = st.text_input("Sender Name *")
            sender_contact = st.text_input("Contact (email/phone)")
            source = st.selectbox(
                "Source Platform:",
                options=[p.value for p in SourcePlatform]
            )

        with col2:
            shaikh_options = {"-- None (Pending) --": None}
            shaikh_options.update({s["name"]: s for s in shaikhs})

            selected_shaikh = st.selectbox(
                "Assign to Shaikh:",
                options=list(shaikh_options.keys())
            )

        question = st.text_area("Question *", height=200)

        submitted = st.form_submit_button("Create Ticket", use_container_width=True)

        if submitted:
            if not sender_name or not question:
                st.error("Please fill in all required fields (marked with *)")
            else:
                ticket = Ticket(
                    source_platform=SourcePlatform(source),
                    sender_id=f"manual_{datetime.now().timestamp()}",
                    sender_name=sender_name,
                    sender_contact=sender_contact,
                    question_text=question,
                )

                ticket_id = db.create_ticket(ticket)

                if selected_shaikh != "-- None (Pending) --":
                    shaikh = shaikh_options[selected_shaikh]
                    db.assign_shaikh(ticket_id, shaikh["id"], shaikh["phone"])

                st.success(f"✅ Ticket #{ticket_id} created successfully!")
                st.balloons()


def render_settings(config: dict):
    """Render the settings view."""
    st.header("⚙️ Settings")

    st.warning("⚠️ Settings are read from config.json. Edit the file directly to make changes.")

    # Display current settings
    st.subheader("📋 Current Configuration")

    # Shaikhs
    st.markdown("### 👤 Registered Shaikhs")
    shaikhs = config.get("shaikhs", [])

    if shaikhs:
        for shaikh in shaikhs:
            col1, col2, col3 = st.columns(3)
            with col1:
                st.write(f"**{shaikh.get('name', 'Unknown')}**")
            with col2:
                st.write(f"📱 {shaikh.get('phone', 'N/A')}")
            with col3:
                st.write(f"📚 {shaikh.get('specialization', 'General')}")
    else:
        st.info("No Shaikhs configured")

    st.divider()

    # Platform settings
    st.markdown("### 🔌 Platform Status")

    col1, col2, col3 = st.columns(3)

    with col1:
        fb_enabled = config.get("facebook", {}).get("enabled", False)
        st.write(f"**Facebook:** {'✅ Enabled' if fb_enabled else '❌ Disabled'}")

    with col2:
        ig_enabled = config.get("instagram", {}).get("enabled", False)
        st.write(f"**Instagram:** {'✅ Enabled' if ig_enabled else '❌ Disabled'}")

    with col3:
        email_enabled = config.get("email", {}).get("enabled", False)
        st.write(f"**Email:** {'✅ Enabled' if email_enabled else '❌ Disabled'}")

    st.divider()

    # WhatsApp
    st.markdown("### 📱 WhatsApp Bridge")
    wa_config = config.get("whatsapp", {})
    st.write(f"**Bridge Port:** {wa_config.get('node_bridge_port', 3001)}")
    st.write(f"**Session Path:** {wa_config.get('session_path', './whatsapp_node/session')}")

    st.divider()

    # System settings
    st.markdown("### 🔧 System Settings")
    settings = config.get("settings", {})

    col1, col2 = st.columns(2)

    with col1:
        st.write(f"**Auto Dispatch:** {'✅' if settings.get('auto_dispatch_replies', False) else '❌'}")
        st.write(f"**Stealth Mode:** {'✅' if settings.get('stealth_mode', True) else '❌'}")

    with col2:
        st.write(f"**Headless Browser:** {'✅' if settings.get('headless_browser', False) else '❌'}")
        st.write(f"**Capture Loop:** {'✅' if settings.get('capture_loop_enabled', True) else '❌'}")


if __name__ == "__main__":
    main()
