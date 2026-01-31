# Fatwa Management System

A local Python-based system to manage and distribute Fatwas. The system acts as a bridge between multiple social media platforms (Facebook, Instagram, Email) and Shaikhs who interact ONLY via WhatsApp.

## Features

- **Multi-Platform Capture**: Automatically collects inquiries from Facebook (DMs & Comments), Instagram (DMs & Comments), and Email
- **WhatsApp Integration**: Sends questions to Shaikhs and receives their responses via WhatsApp
- **Automated Dispatch**: Routes answers back to the original platform automatically
- **Streamlit Dashboard**: Simple UI for managing tickets and assigning Shaikhs
- **SQLite Database**: Local, private storage for all data

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Facebook     │    │   Instagram     │    │     Email       │
│   DMs/Comments  │    │  DMs/Comments   │    │     IMAP        │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │    CAPTURE MODULE     │
                    │   (Playwright/IMAP)   │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   SQLite DATABASE     │
                    │    (tickets table)    │
                    └───────────┬───────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
┌────────▼────────┐  ┌──────────▼──────────┐  ┌───────▼────────┐
│    DASHBOARD    │  │  WHATSAPP BRIDGE    │  │    DISPATCH    │
│   (Streamlit)   │  │  (Node.js/Baileys)  │  │    MODULE      │
└─────────────────┘  └──────────┬──────────┘  └────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │      SHAIKHS          │
                    │   (via WhatsApp)      │
                    └───────────────────────┘
```

## Installation

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm

### Setup

1. Clone the repository and navigate to the project directory:
   ```bash
   cd Fatwa
   ```

2. Create a Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. Install Node.js dependencies for WhatsApp bridge:
   ```bash
   cd whatsapp_node
   npm install
   cd ..
   ```

5. Configure the system by editing `config.json`:
   ```json
   {
     "facebook": {
       "email": "your_fb_email",
       "password": "your_fb_password",
       "enabled": true
     },
     "instagram": {
       "username": "your_ig_username",
       "password": "your_ig_password",
       "enabled": true
     },
     "email": {
       "imap_server": "imap.gmail.com",
       "email_address": "your_email@gmail.com",
       "password": "your_app_password",
       "enabled": true
     },
     "shaikhs": [
       {
         "id": 1,
         "name": "Shaikh Ahmed",
         "phone": "966501234567",
         "specialization": "Fiqh"
       }
     ]
   }
   ```

## Usage

### Running the Main System

```bash
python main.py
```

This starts:
- Capture loops for all enabled platforms
- WhatsApp bridge (will show QR code for first-time setup)
- Listener for Shaikh replies
- Dispatch loop (if auto_dispatch is enabled)

### Running the Dashboard

```bash
python main.py --dashboard
# Or directly:
streamlit run dashboard/app.py
```

The dashboard provides:
- Overview of all tickets by status
- Ability to assign Shaikhs to pending questions
- View and search all tickets
- Manual ticket creation
- System settings view

### Starting WhatsApp Bridge Manually

```bash
cd whatsapp_node
npm start
```

## Workflow

1. **Capture**: System periodically checks Facebook, Instagram, and Email for new inquiries
2. **Store**: New questions are saved to SQLite with status "Pending"
3. **Assign**: Manager assigns a Shaikh via the dashboard (status: "Assigned")
4. **Send**: System sends question to Shaikh's WhatsApp (status: "Sent_to_Shaikh")
5. **Reply**: Shaikh replies with `#<ticket_id> <answer>` (status: "Replied")
6. **Dispatch**: System sends answer back to original platform (status: "Final_Sent")

## Project Structure

```
Fatwa/
├── config.json              # Configuration file
├── requirements.txt         # Python dependencies
├── main.py                  # Main entry point
├── database/
│   ├── __init__.py
│   ├── models.py           # Ticket data models
│   └── db.py               # SQLite operations
├── capture/
│   ├── __init__.py
│   ├── base.py             # Base capture class
│   ├── facebook.py         # Facebook scraper
│   ├── instagram.py        # Instagram scraper
│   └── email_capture.py    # IMAP email capture
├── whatsapp/
│   ├── __init__.py
│   ├── bridge.py           # Python-Node.js bridge
│   ├── sender.py           # Send to Shaikhs
│   └── listener.py         # Listen for replies
├── whatsapp_node/
│   ├── package.json
│   └── index.js            # Baileys WhatsApp bridge
├── dispatch/
│   ├── __init__.py
│   ├── dispatcher.py       # Main dispatcher
│   ├── facebook_reply.py   # Facebook reply sender
│   ├── instagram_reply.py  # Instagram reply sender
│   └── email_reply.py      # Email reply sender
└── dashboard/
    └── app.py              # Streamlit dashboard
```

## Configuration Options

| Setting | Description |
|---------|-------------|
| `database.path` | SQLite database file path |
| `facebook.enabled` | Enable/disable Facebook capture |
| `instagram.enabled` | Enable/disable Instagram capture |
| `email.enabled` | Enable/disable Email capture |
| `settings.auto_dispatch_replies` | Auto-send replies to platforms |
| `settings.stealth_mode` | Use browser stealth mode |
| `settings.headless_browser` | Run browsers without GUI |

## Security Notes

- **Credentials**: Store sensitive data in `config.json` which should NOT be committed to version control
- **Privacy**: All data stays local in SQLite
- **Stealth Mode**: Browser automation uses stealth techniques to avoid detection
- **No Official APIs**: Uses browser automation to avoid API approval requirements

## Troubleshooting

### WhatsApp QR Code Not Showing
- Ensure Node.js bridge is running
- Check that port 3001 is available
- Look for QR code in terminal output

### Facebook/Instagram Login Fails
- Disable 2FA temporarily or use app passwords
- Check for security checkpoints
- Ensure credentials are correct

### Email Not Working
- Use App Passwords for Gmail
- Enable IMAP in email settings
- Check firewall rules

## License

Private/Internal Use Only
