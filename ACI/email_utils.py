import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os
from config import EMAIL_HOST, EMAIL_PORT, EMAIL_USERNAME, EMAIL_PASSWORD, EMAIL_RECIPIENT
from typing import List

def send_email_with_attachments(subject: str, body: str, attachment_paths: List[str]):
    """
    Sends an email with multiple attachments.
    """
    try:
        # Create a multipart message
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USERNAME
        msg['To'] = ", ".join(EMAIL_RECIPIENT)
        msg['Subject'] = subject

        # Add body to email
        msg.attach(MIMEText(body, 'plain'))

        for attachment_path in attachment_paths:
            if not os.path.exists(attachment_path):
                print(f"Attachment not found at {attachment_path}, skipping.")
                continue

            # Open the file in binary mode
            with open(attachment_path, "rb") as attachment:
                # Add file as application/octet-stream
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())

            # Encode file in ASCII characters to send by email
            encoders.encode_base64(part)

            # Add header as key/value pair to attachment part
            part.add_header(
                "Content-Disposition",
                f"attachment; filename= {os.path.basename(attachment_path)}",
            )

            # Add attachment to message
            msg.attach(part)

        # Log in to server using secure context and send email
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
        server.sendmail(EMAIL_USERNAME, EMAIL_RECIPIENT, msg.as_string())
        server.quit()
        print(f"Email sent successfully to {', '.join(EMAIL_RECIPIENT)}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False