import smtplib, getpass
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

user = "pricing@flashcargoglobal.com"
password = getpass.getpass(f"Enter password for {user}: ")

msg = MIMEMultipart('alternative')
msg['From'] = 'Elif | Flash Cargo Global <elif@flashcargoglobal.com>'
msg['To'] = 'admin@flashcargoglobal.com'
msg['Subject'] = 'SMTP AUTH alias test - Elif'
msg['Reply-To'] = 'pricing@flashcargoglobal.com'
msg.attach(MIMEText('If this shows FROM as Elif, SMTP alias works!', 'plain'))

try:
    server = smtplib.SMTP('smtp.office365.com', 587, timeout=15)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(user, password)
    server.sendmail('elif@flashcargoglobal.com', ['admin@flashcargoglobal.com'], msg.as_string())
    server.quit()
    print('SUCCESS - email sent via SMTP with elif@ alias!')
except Exception as e:
    print(f'FAILED: {e}')
