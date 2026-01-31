/**
 * WhatsApp Bridge for Fatwa Management System
 * Uses @whiskeysockets/baileys for WhatsApp Web connection
 */

const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion,
    makeCacheableSignalKeyStore,
} = require("@whiskeysockets/baileys");
const express = require("express");
const cors = require("cors");
const pino = require("pino");
const qrcode = require("qrcode-terminal");
const path = require("path");
const fs = require("fs");

// Configuration
const PORT = process.env.PORT || 3001;
const SESSION_PATH = process.env.SESSION_PATH || "./session";

// Logger
const logger = pino({ level: "warn" });

// Express app for REST API
const app = express();
app.use(cors());
app.use(express.json());

// Global socket reference
let sock = null;
let connectionStatus = "disconnected";
let qrCodeData = null;

// Message queue for incoming messages
const incomingMessages = [];
const MAX_QUEUE_SIZE = 1000;

// Store sent message IDs to track replies
const sentMessageTracker = new Map();

/**
 * Initialize WhatsApp connection
 */
async function connectWhatsApp() {
    // Ensure session directory exists
    if (!fs.existsSync(SESSION_PATH)) {
        fs.mkdirSync(SESSION_PATH, { recursive: true });
    }

    const { state, saveCreds } = await useMultiFileAuthState(SESSION_PATH);
    const { version, isLatest } = await fetchLatestBaileysVersion();

    console.log(`Using WA v${version.join(".")}, isLatest: ${isLatest}`);

    sock = makeWASocket({
        version,
        logger,
        printQRInTerminal: false, // We'll handle QR ourselves
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, logger),
        },
        generateHighQualityLinkPreview: true,
    });

    // Handle connection updates
    sock.ev.on("connection.update", async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            qrCodeData = qr;
            console.log("\n========== SCAN QR CODE ==========");
            qrcode.generate(qr, { small: true });
            console.log("==================================\n");
        }

        if (connection === "close") {
            const shouldReconnect =
                lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;

            console.log(
                "Connection closed due to",
                lastDisconnect?.error,
                ", reconnecting:",
                shouldReconnect
            );

            connectionStatus = "disconnected";

            if (shouldReconnect) {
                setTimeout(connectWhatsApp, 5000);
            }
        } else if (connection === "open") {
            console.log("WhatsApp connection established!");
            connectionStatus = "connected";
            qrCodeData = null;
        }
    });

    // Save credentials on update
    sock.ev.on("creds.update", saveCreds);

    // Handle incoming messages
    sock.ev.on("messages.upsert", async ({ messages, type }) => {
        if (type !== "notify") return;

        for (const msg of messages) {
            // Skip our own messages
            if (msg.key.fromMe) continue;

            const messageText =
                msg.message?.conversation ||
                msg.message?.extendedTextMessage?.text ||
                "";

            if (!messageText) continue;

            const senderJid = msg.key.remoteJid;
            const senderPhone = senderJid.replace("@s.whatsapp.net", "");
            const messageId = msg.key.id;

            // Check if this is a reply to a message we sent
            const quotedMessageId = msg.message?.extendedTextMessage?.contextInfo?.stanzaId;

            const incomingMsg = {
                id: messageId,
                from: senderPhone,
                text: messageText,
                timestamp: new Date().toISOString(),
                quotedMessageId: quotedMessageId || null,
                rawMessage: {
                    key: msg.key,
                    pushName: msg.pushName,
                },
            };

            // Add to queue
            incomingMessages.push(incomingMsg);

            // Keep queue size limited
            if (incomingMessages.length > MAX_QUEUE_SIZE) {
                incomingMessages.shift();
            }

            console.log(`Received message from ${senderPhone}: ${messageText.substring(0, 50)}...`);
        }
    });

    return sock;
}

// ============== REST API Endpoints ==============

/**
 * GET /status - Get connection status
 */
app.get("/status", (req, res) => {
    res.json({
        status: connectionStatus,
        qrCode: qrCodeData,
        timestamp: new Date().toISOString(),
    });
});

/**
 * GET /qr - Get QR code for scanning
 */
app.get("/qr", (req, res) => {
    if (connectionStatus === "connected") {
        res.json({ message: "Already connected", qrCode: null });
    } else if (qrCodeData) {
        res.json({ qrCode: qrCodeData });
    } else {
        res.json({ message: "Waiting for QR code...", qrCode: null });
    }
});

/**
 * POST /send - Send a message
 * Body: { phone: "1234567890", message: "Hello" }
 */
app.post("/send", async (req, res) => {
    try {
        const { phone, message, ticketId } = req.body;

        if (!phone || !message) {
            return res.status(400).json({ error: "Phone and message are required" });
        }

        if (connectionStatus !== "connected") {
            return res.status(503).json({ error: "WhatsApp not connected" });
        }

        // Format phone number
        const jid = formatPhoneNumber(phone) + "@s.whatsapp.net";

        // Send message
        const result = await sock.sendMessage(jid, { text: message });

        // Track sent message for reply matching
        if (ticketId) {
            sentMessageTracker.set(result.key.id, {
                ticketId,
                phone,
                sentAt: new Date().toISOString(),
            });
        }

        console.log(`Message sent to ${phone}: ${message.substring(0, 50)}...`);

        res.json({
            success: true,
            messageId: result.key.id,
            timestamp: new Date().toISOString(),
        });
    } catch (error) {
        console.error("Error sending message:", error);
        res.status(500).json({ error: error.message });
    }
});

/**
 * GET /messages - Get incoming messages
 * Query params: since (timestamp), limit (number)
 */
app.get("/messages", (req, res) => {
    const { since, limit = 50 } = req.query;
    let messages = [...incomingMessages];

    if (since) {
        const sinceDate = new Date(since);
        messages = messages.filter((m) => new Date(m.timestamp) > sinceDate);
    }

    // Return most recent messages first
    messages = messages.slice(-parseInt(limit)).reverse();

    res.json({ messages });
});

/**
 * POST /messages/clear - Clear processed messages
 * Body: { messageIds: ["id1", "id2"] }
 */
app.post("/messages/clear", (req, res) => {
    const { messageIds } = req.body;

    if (messageIds && Array.isArray(messageIds)) {
        const idsSet = new Set(messageIds);
        const remaining = incomingMessages.filter((m) => !idsSet.has(m.id));
        incomingMessages.length = 0;
        incomingMessages.push(...remaining);
    }

    res.json({ success: true, remaining: incomingMessages.length });
});

/**
 * GET /sent-tracker - Get sent message tracker
 */
app.get("/sent-tracker", (req, res) => {
    const tracker = {};
    sentMessageTracker.forEach((value, key) => {
        tracker[key] = value;
    });
    res.json({ tracker });
});

/**
 * POST /logout - Logout from WhatsApp
 */
app.post("/logout", async (req, res) => {
    try {
        if (sock) {
            await sock.logout();
        }

        // Clear session
        if (fs.existsSync(SESSION_PATH)) {
            fs.rmSync(SESSION_PATH, { recursive: true });
        }

        connectionStatus = "disconnected";
        res.json({ success: true, message: "Logged out successfully" });
    } catch (error) {
        console.error("Error logging out:", error);
        res.status(500).json({ error: error.message });
    }
});

/**
 * Format phone number to standard format
 */
function formatPhoneNumber(phone) {
    // Remove any non-digit characters
    let cleaned = phone.replace(/\D/g, "");

    // Remove leading zeros
    cleaned = cleaned.replace(/^0+/, "");

    // Add country code if not present (assume Saudi Arabia if 9 digits starting with 5)
    if (cleaned.length === 9 && cleaned.startsWith("5")) {
        cleaned = "966" + cleaned;
    }

    return cleaned;
}

// ============== Start Server ==============

async function main() {
    // Connect to WhatsApp
    await connectWhatsApp();

    // Start Express server
    app.listen(PORT, () => {
        console.log(`\nWhatsApp Bridge API running on http://localhost:${PORT}`);
        console.log("\nEndpoints:");
        console.log(`  GET  /status       - Connection status`);
        console.log(`  GET  /qr           - QR code for scanning`);
        console.log(`  POST /send         - Send message { phone, message, ticketId }`);
        console.log(`  GET  /messages     - Get incoming messages`);
        console.log(`  POST /messages/clear - Clear processed messages`);
        console.log(`  POST /logout       - Logout from WhatsApp`);
        console.log("");
    });
}

main().catch(console.error);
