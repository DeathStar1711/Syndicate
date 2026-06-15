"""
Email alerts module.
Sends morning signals, exit alerts, and daily reports via SMTP.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Optional
from jinja2 import Environment, FileSystemLoader
from src.utils.logger import get_logger
from src.utils.helpers import load_config, load_env, get_project_root, now_ist

logger = get_logger("stock_ai.notifications")


class EmailAlerts:
    """SMTP-based email notification system."""

    def __init__(self, config: Optional[dict] = None):
        load_env()
        self.config = config or load_config()
        self.email_config = self.config.get("email", {})
        self.enabled = self.email_config.get("enabled", False)

        # Load from environment variables
        self.sender = os.environ.get("EMAIL_SENDER", "")
        self.password = os.environ.get("EMAIL_PASSWORD", "")
        recipients_str = os.environ.get("EMAIL_RECIPIENT", "")
        self.recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
        self.smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))

        # Jinja2 template environment
        template_dir = os.path.join(get_project_root(), "templates")
        if os.path.exists(template_dir):
            self.jinja_env = Environment(loader=FileSystemLoader(template_dir))
        else:
            self.jinja_env = None

    def _send_email(self, subject: str, html_body: str, text_body: str = ""):
        """Send an email via SMTP to all recipients."""
        subject = f"[GROWW LIVE] {subject}"
        
        if not self.enabled:
            logger.info(f"Email disabled — would send: {subject}")
            logger.debug(f"Email body preview:\n{text_body[:500]}")
            return False

        if not self.sender or not self.password or not self.recipients:
            logger.warning("Email configuration incomplete — skipping send")
            return False

        success_count = 0
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender, self.password)

                for recipient in self.recipients:
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = subject
                    msg["From"] = self.sender
                    msg["To"] = recipient

                    if text_body:
                        msg.attach(MIMEText(text_body, "plain"))
                    msg.attach(MIMEText(html_body, "html"))

                    server.send_message(msg)
                    success_count += 1
            
            logger.info(f"Email sent to {success_count} recipients: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def send_test_email(self):
        """Send a simple test email to verify credentials and prefixing."""
        subject = "Live Architecture Integration Test"
        html = "<h3>✅ If you are reading this, the Groww Live architecture email routing is working!</h3>"
        text = "If you are reading this, the Groww Live architecture email routing is working!"
        return self._send_email(subject, html, text)

    def send_morning_signals(self, signals: List[Dict]):
        """Send morning trade signal email."""
        if not self.email_config.get("send_morning_signals", True):
            return

        date_str = now_ist().strftime("%d %b %Y")
        subject = f"📊 Stock AI Signals — {date_str} ({len(signals)} trades)"

        # Build HTML
        html = self._render_signals_html(signals)
        text = self._render_signals_text(signals)

        self._send_email(subject, html, text)

    def send_breakout_alert(self, signals: List[Dict]):
        """Send breakout alert email for exceptional intraday opportunities."""
        if not signals:
            return

        tickers = ", ".join(s["ticker"].replace(".NS", "") for s in signals)
        surges = ", ".join(f"+{s['price_jump_pct']}%" for s in signals)
        subject = f"🚨 Breakout Alert: {tickers} ({surges})"

        html = self._render_breakout_html(signals)
        text = self._render_breakout_text(signals)
        self._send_email(subject, html, text)

    def _render_breakout_html(self, signals: List[Dict]) -> str:
        """Render breakout signals as HTML email."""
        if self.jinja_env:
            try:
                template = self.jinja_env.get_template("email_breakout.html")
                return template.render(
                    signals=signals,
                    date=now_ist().strftime("%d %b %Y %H:%M IST"),
                )
            except Exception:
                pass

        # Fallback inline HTML
        cards = ""
        for sig in signals:
            reasons_html = "".join(f"<li>{r}</li>" for r in sig.get("reasons", []))
            cons_html = "".join(f"<li style='color:#c62828;'>{c}</li>" for c in sig.get("cons", []))
            risks = f"<p><b style='color:#e74c3c;'>⚠️ Risks:</b></p><ul>{cons_html}</ul>" if sig.get("cons") else ""
            pos = sig.get("position", {})
            cards += f"""
            <div style="border: 2px solid #e53935; border-radius: 12px; padding: 16px; margin: 12px 0; background: #fff5f5;">
                <h3 style="margin-top: 0; color: #b71c1c;">{sig['ticker']}</h3>
                <p>
                    <span style="background:#ffebee;color:#c62828;padding:2px 8px;border-radius:8px;font-size:13px;font-weight:600;">
                        ⚡ {sig['price_jump_pct']}% surge
                    </span>
                    <span style="background:#ffebee;color:#c62828;padding:2px 8px;border-radius:8px;font-size:13px;font-weight:600;">
                        📊 {sig['volume_ratio']}× volume
                    </span>
                </p>
                <table style="width: 100%;">
                    <tr><td>Entry</td><td><b>₹{sig['entry_price']:,.2f}</b></td>
                        <td>SL</td><td><b style="color:red;">₹{sig['stop_loss']:,.2f}</b></td>
                        <td>Target</td><td><b style="color:green;">₹{sig['target']:,.2f}</b></td></tr>
                </table>
                <p>🛒 <b>{pos.get('shares', 0)} shares</b> · 💰 <b>₹{pos.get('position_value', 0):,.2f}</b></p>
                <p><b style="color:#e53935;">🚨 Why:</b></p><ul>{reasons_html}</ul>
                {risks}
            </div>
            """

        return f"""
        <html><body style="font-family: 'Segoe UI', Arial, sans-serif; padding: 20px; max-width: 640px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #b71c1c, #e53935); padding: 24px; border-radius: 12px 12px 0 0; text-align: center;">
            <h1 style="color: white; margin: 0;">🚨 BREAKOUT ALERT</h1>
            <p style="color: #ffcdd2; margin: 8px 0 0;">{now_ist().strftime('%d %b %Y %H:%M IST')}</p>
        </div>
        {cards}
        <hr><p style="color: #888; font-size: 12px;">
        ⚠ <b>DISCLAIMER:</b> Paper trading only. Not financial advice. Breakout trades carry higher risk.
        </p></body></html>
        """

    def _render_breakout_text(self, signals: List[Dict]) -> str:
        """Render breakout signals as plain text."""
        lines = [
            "🚨 BREAKOUT ALERT",
            now_ist().strftime('%d %b %Y %H:%M IST'),
            "=" * 50,
        ]
        for sig in signals:
            pos = sig.get("position", {})
            lines.append(f"\n{sig['ticker']} — ⚡ {sig['price_jump_pct']}% surge · 📊 {sig['volume_ratio']}× volume")
            lines.append(f"  Entry: ₹{sig['entry_price']:,.2f} | SL: ₹{sig['stop_loss']:,.2f} | Target: ₹{sig['target']:,.2f}")
            lines.append(f"  R:R: {sig['risk_reward']}:1 | Confidence: {sig['confidence']}/100")
            lines.append(f"  Shares: {pos.get('shares', 0)} | ₹{pos.get('position_value', 0):,.2f}")
            for r in sig.get("reasons", []):
                lines.append(f"    ✓ {r}")
            for c in sig.get("cons", []):
                lines.append(f"    ✗ {c}")
        lines.append("\n⚠ Paper trading only. Not financial advice.")
        return "\n".join(lines)

    def send_exit_alert(self, trade_result: Dict):
        """Send immediate exit alert email."""
        if not self.email_config.get("send_exit_alerts", True):
            return

        ticker = trade_result.get("ticker", "?")
        reason = trade_result.get("exit_reason", "?")
        pnl = trade_result.get("pnl", 0)
        emoji = "🎯" if reason == "target" else "🛑"

        # Trade type label
        trade_type = trade_result.get("trade_type", "daily")
        type_label = {"swing": "🔁 Swing", "breakout": "🚨 Breakout"}.get(trade_type, "⚡ Intraday")

        subject = f"{emoji} Exit Alert: {ticker} ({reason}) — P&L ₹{pnl:,.2f}"

        html = f"""
        <html><body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>{emoji} Trade Exit Alert</h2>
        <table style="border-collapse: collapse; width: 100%;">
            <tr><td><b>Ticker:</b></td><td>{ticker}</td></tr>
            <tr><td><b>Trade Type:</b></td><td>{type_label}</td></tr>
            <tr><td><b>Exit Reason:</b></td><td>{reason.upper()}</td></tr>
            <tr><td><b>Entry Price:</b></td><td>₹{trade_result.get('entry_price', 0):,.2f}</td></tr>
            <tr><td><b>Exit Price:</b></td><td>₹{trade_result.get('exit_price', 0):,.2f}</td></tr>
            <tr><td><b>P&L:</b></td><td style="color: {'green' if pnl > 0 else 'red'}">₹{pnl:,.2f} ({trade_result.get('pnl_pct', 0):+.1f}%)</td></tr>
        </table>
        <hr><p style="color: #888; font-size: 12px;">⚠ Paper trading only. Not financial advice.</p>
        </body></html>
        """

    def send_system_failure_alert(self, script_name: str, error_msg: str, traceback_str: str):
        """Send an emergency alert when a top-level script fails entirely."""
        subject = f"🚨 SYSTEM FAILURE: {script_name}"
        html = f"""
        <html><body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color:red;">🚨 Critical System Failure</h2>
        <p><b>Script:</b> {script_name}</p>
        <p><b>Error:</b> {error_msg}</p>
        <pre style="background:#f4f4f4; padding:15px; border-left:4px solid red; overflow-x:auto;">
{traceback_str}
        </pre>
        </body></html>
        """
        text = f"CRITICAL FAILURE in {script_name}\\nError: {error_msg}\\n\\nTraceback:\\n{traceback_str}"
        self._send_email(subject, html, text)

    def _render_signals_html(self, signals: List[Dict]) -> str:
        """Render signals as HTML email."""
        if self.jinja_env:
            try:
                template = self.jinja_env.get_template("email_signal.html")
                return template.render(signals=signals, date=now_ist().strftime("%d %b %Y"))
            except Exception:
                pass

        # Fallback inline HTML
        cards = ""
        for i, sig in enumerate(signals, 1):
            pos = sig.get("position", {})
            reasons_html = "".join(f"<li>{r}</li>" for r in sig.get("reasons", []))
            cards += f"""
            <div style="border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 12px 0; background: #fafafa;">
                <h3 style="margin-top: 0;">#{i} {sig['ticker']} — {sig.get('direction', 'long').upper()}</h3>
                <table style="width: 100%;">
                    <tr><td>Entry</td><td><b>₹{sig['entry_price']:,.2f}</b></td>
                        <td>Stop-Loss</td><td><b style="color:red;">₹{sig['stop_loss']:,.2f}</b></td></tr>
                    <tr><td>Target</td><td><b style="color:green;">₹{sig['target']:,.2f}</b></td>
                        <td>R:R</td><td><b>{sig['risk_reward']:.1f}:1</b></td></tr>
                    <tr><td>Confidence</td><td><b>{sig['confidence']}/100</b></td>
                        <td>Risk</td><td><b>₹{pos.get('risk_amount', 0):,.0f} ({pos.get('risk_pct', 0)}%)</b></td></tr>
                </table>
                <div style="background: #eaf6ed; border: 1px solid #b8e0c5; border-radius: 6px; padding: 12px; margin: 12px 0;">
                    <table style="width: 100%;">
                        <tr>
                            <td>🛒 <b>Shares to Buy: {pos.get('shares', 0)}</b></td>
                            <td style="text-align:right;">💰 <b>Total Investment: ₹{pos.get('position_value', 0):,.2f}</b></td>
                        </tr>
                    </table>
                </div>
                <p><b>Why:</b></p><ul>{reasons_html}</ul>
            </div>
            """

        return f"""
        <html><body style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px;">
        <h2>📊 Stock AI — Daily Trade Ideas</h2>
        <p>{now_ist().strftime('%d %B %Y, %H:%M IST')} | {len(signals)} signals</p>
        {cards}
        <hr><p style="color: #888; font-size: 12px;">
        ⚠ <b>DISCLAIMER:</b> These are paper trading signals for research and learning purposes only. 
        They do not constitute financial advice and do not guarantee returns.
        </p></body></html>
        """

    def _render_signals_text(self, signals: List[Dict]) -> str:
        """Render signals as plain text."""
        from src.strategy.signals import format_signal_text
        lines = [
            f"Stock AI — Daily Trade Ideas",
            f"{now_ist().strftime('%d %B %Y, %H:%M IST')}",
            f"{len(signals)} signals generated",
            "=" * 50,
        ]
        for sig in signals:
            lines.append(format_signal_text(sig))
            lines.append("")
        lines.append("⚠ Paper trading only. Not financial advice.")
        return "\n".join(lines)

    def send_weekly_swing(self, signals_input):
        """
        Send weekly swing trading investment email.
        
        Args:
            signals_input: Either a grouped dict {"short": [...], "medium": [...], "long": [...]}
                          or a flat list of signals (backward compatible).
        """
        # Normalize input — support both grouped dict and flat list
        if isinstance(signals_input, dict):
            grouped = signals_input
            all_signals = (
                grouped.get("short", []) +
                grouped.get("medium", []) +
                grouped.get("long", [])
            )
        else:
            grouped = {"short": signals_input, "medium": [], "long": []}
            all_signals = signals_input

        date_str = now_ist().strftime("%d %b %Y")
        total = len(all_signals)
        subject = f"📈 Weekly Swing Picks — {date_str} ({total} opportunities across 3 horizons)"

        # Build HTML
        html = self._render_swing_html(grouped)
        text = self._render_swing_text(grouped)

        self._send_email(subject, html, text)

    def _render_swing_html(self, grouped: dict) -> str:
        """Render grouped swing signals as HTML email with 3 color-coded sections."""
        if self.jinja_env:
            try:
                template = self.jinja_env.get_template("email_weekly_swing.html")
                return template.render(
                    grouped=grouped,
                    date=now_ist().strftime("%d %b %Y"),
                )
            except Exception:
                pass

        # Fallback inline HTML
        HORIZON_STYLES = {
            "short": {"emoji": "🟢", "label": "Short Swing (5–15 days)", "accent": "#27ae60", "bg": "#e8f5e9", "border": "#a5d6a7"},
            "medium": {"emoji": "🔵", "label": "Medium Position (1–3 months)", "accent": "#1976d2", "bg": "#e3f2fd", "border": "#90caf9"},
            "long": {"emoji": "🟣", "label": "Long Investment (6–12 months)", "accent": "#7b1fa2", "bg": "#f3e5f5", "border": "#ce93d8"},
        }

        sections_html = ""
        for horizon_key in ["short", "medium", "long"]:
            signals = grouped.get(horizon_key, [])
            if not signals:
                continue

            style = HORIZON_STYLES[horizon_key]
            cards = ""
            for i, sig in enumerate(signals, 1):
                pos = sig.get("position", {})
                reasons_html = "".join(f"<li>{r}</li>" for r in sig.get("reasons", []))
                cons_list = sig.get("cons", [])
                cons_html = "".join(f"<li style='color:#c62828;'>{c}</li>" for c in cons_list)
                risks_section = f"""
                    <p><b style="color:#e74c3c;">⚠️ Risks:</b></p><ul>{cons_html}</ul>
                """ if cons_list else ""
                cards += f"""
                <div style="border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 12px 0; background: #fafafa;">
                    <h3 style="margin-top: 0;">#{i} {sig['ticker']}</h3>
                    <p>
                        <span style="background:#e8f5e9;color:#2e7d32;padding:2px 8px;border-radius:10px;font-size:12px;">
                            Week: {sig.get('weekly_return', 0):+.1f}%
                        </span>
                        <span style="background:#e8f5e9;color:#2e7d32;padding:2px 8px;border-radius:10px;font-size:12px;">
                            Month: {sig.get('monthly_return', 0):+.1f}%
                        </span>
                    </p>
                    <table style="width: 100%;">
                        <tr><td>Entry</td><td><b>₹{sig['entry_price']:,.2f}</b></td>
                            <td>Stop-Loss</td><td><b style="color:red;">₹{sig['stop_loss']:,.2f}</b></td></tr>
                        <tr><td>Target</td><td><b style="color:green;">₹{sig['target']:,.2f}</b></td>
                            <td>R:R</td><td><b>{sig['risk_reward']:.1f}:1</b></td></tr>
                        <tr><td>Holding</td><td><b>{sig.get('holding_period', '?')}</b></td>
                            <td>Confidence</td><td><b>{sig['confidence']}/100</b></td></tr>
                    </table>
                    <div style="background: {style['bg']}; border: 1px solid {style['border']}; border-radius: 6px; padding: 12px; margin: 12px 0;">
                        <table style="width: 100%;">
                            <tr>
                                <td>🛒 <b>Shares: {pos.get('shares', 0)}</b></td>
                                <td style="text-align:right;">💰 <b>₹{pos.get('position_value', 0):,.2f}</b></td>
                            </tr>
                        </table>
                    </div>
                    <p><b style="color:#27ae60;">✅ Thesis:</b></p><ul>{reasons_html}</ul>
                    {risks_section}
                </div>
                """

            sections_html += f"""
            <div style="margin: 24px 0;">
                <h2 style="color: {style['accent']}; border-bottom: 2px solid {style['accent']}; padding-bottom: 8px;">
                    {style['emoji']} {style['label']} ({len(signals)} picks)
                </h2>
                {cards}
            </div>
            """

        total = sum(len(grouped.get(k, [])) for k in ["short", "medium", "long"])

        return f"""
        <html><body style="font-family: 'Segoe UI', Arial, sans-serif; padding: 20px; max-width: 640px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #1b2838, #2e7d32); padding: 24px; border-radius: 12px 12px 0 0; text-align: center;">
            <h1 style="color: white; margin: 0;">📈 Weekly Swing Picks</h1>
            <p style="color: #c8e6c9; margin: 8px 0 0;">{now_ist().strftime('%d %B %Y')} | {total} opportunities across 3 horizons</p>
        </div>
        {sections_html}
        <hr><p style="color: #888; font-size: 12px;">
        ⚠ <b>DISCLAIMER:</b> These are paper trading signals for research and learning purposes only. 
        They do not constitute financial advice and do not guarantee returns.
        </p></body></html>
        """

    def _render_swing_text(self, grouped: dict) -> str:
        """Render grouped swing signals as plain text."""
        HORIZON_LABELS = {
            "short": "🟢 SHORT SWING (5-15 days)",
            "medium": "🔵 MEDIUM POSITION (1-3 months)",
            "long": "🟣 LONG INVESTMENT (6-12 months)",
        }

        lines = [
            "Stock AI — Weekly Multi-Horizon Swing Picks",
            now_ist().strftime('%d %B %Y'),
            "=" * 50,
        ]

        for horizon_key in ["short", "medium", "long"]:
            signals = grouped.get(horizon_key, [])
            if not signals:
                continue

            lines.append("")
            lines.append(HORIZON_LABELS[horizon_key])
            lines.append("-" * 40)

            for i, sig in enumerate(signals, 1):
                pos = sig.get("position", {})
                lines.append(f"#{i} {sig['ticker']}")
                lines.append(f"  Entry: ₹{sig['entry_price']:,.2f} | SL: ₹{sig['stop_loss']:,.2f} | Target: ₹{sig['target']:,.2f}")
                lines.append(f"  R:R: {sig['risk_reward']}:1 | Confidence: {sig['confidence']}/100")
                lines.append(f"  Shares: {pos.get('shares', 0)} | Investment: ₹{pos.get('position_value', 0):,.2f}")
                lines.append(f"  Holding: {sig.get('holding_period', '?')}")
                lines.append(f"  Weekly: {sig.get('weekly_return', 0):+.1f}% | Monthly: {sig.get('monthly_return', 0):+.1f}%")
                for reason in sig.get("reasons", []):
                    lines.append(f"    ✓ {reason}")
                cons_list = sig.get("cons", [])
                if cons_list:
                    lines.append("  ⚠️ Risks:")
                    for con in cons_list:
                        lines.append(f"    ✗ {con}")
                lines.append("")

        lines.append("⚠ Paper trading only. Not financial advice.")
        return "\n".join(lines)
