import re
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend


class LoggingSMTPBackend(SMTPBackend):
    """SMTP backend that logs every email to the database."""

    def send_messages(self, email_messages):
        from orderpiqrApp.models import EmailLog

        sent_count = 0
        for message in email_messages:
            status = 'sent'
            error = ''
            try:
                result = super().send_messages([message])
                sent_count += result or 0
                if not result:
                    status = 'failed'
                    error = 'SMTP returned 0 sent'
            except Exception as e:
                status = 'failed'
                error = str(e)

            # Extract HTML body if present
            body_html = ''
            if hasattr(message, 'alternatives'):
                for content, mimetype in message.alternatives:
                    if mimetype == 'text/html':
                        body_html = content
                        break

            # Guess email type from subject
            email_type = _guess_email_type(message.subject)

            try:
                EmailLog.objects.create(
                    subject=message.subject or '',
                    from_email=message.from_email or '',
                    to_emails=', '.join(message.to or []),
                    body_text=message.body or '',
                    body_html=body_html,
                    status=status,
                    error_message=error,
                    email_type=email_type,
                )
            except Exception:
                pass  # Never let logging break email delivery

        return sent_count


def _guess_email_type(subject):
    subject_lower = (subject or '').lower()
    if re.search(r'password|wachtwoord|reset', subject_lower):
        return 'password_reset'
    if re.search(r'welcome|welkom', subject_lower):
        return 'welcome'
    if re.search(r'confirm|bevestig|verif', subject_lower):
        return 'confirmation'
    return 'other'
