"""SMTP 寄信(M4-3)。

實際寄送走 RQ(見 workers/email_job.py),不在請求執行緒裡卡住。
SMTP 未設定時 `send` 直接回 False——站內通知已經送達,Email 只是加分,不該讓整個
調代課流程因為沒設信箱而失敗。

傳輸安全(數發部源碼檢測):465 埠走 SMTPS(一連線就加密),其他埠一律 STARTTLS;
兩者都**驗證伺服器憑證**(v1.5.0;先前 starttls() 沒帶 context,不驗證憑證,等於可被中間人攔截)。
v1.6.0 起**不再提供不加密寄信**:先前不勾 TLS 時帳密與信件內容以明文傳送。
v1.7.1 起連線、加密、寄出寫在 `send` 同一個函式裡,檢測工具才看得出寄信前一定先加密。

寄測試信(v1.5.1):`describe_error` 把常見的 SMTP 錯誤翻成組長看得懂的說明,原始訊息附在後面。
"""

import smtplib
import socket
import ssl
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.services import settings as app_settings


def send(db: Session, *, to: str, subject: str, body: str) -> bool:
    """寄一封信。回傳是否真的送出(未設定 SMTP、或無收件人時回 False)。"""
    if not to:
        return False
    cfg = app_settings.smtp_config(db)
    if not cfg.configured:
        return False

    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body or subject)

    # 連線、加密、登入、寄出寫在同一個函式裡(v1.7.1):先前加密寫在 _connect,
    # 源碼檢測工具跨函式追不到 starttls(),誤判為明文寄信。
    context = ssl.create_default_context()  # 一律驗證伺服器憑證
    if cfg.port == SMTPS_PORT:
        with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=15, context=context) as server:
            if cfg.user:
                server.login(cfg.user, cfg.password)
            server.send_message(msg)
        return True
    with smtplib.SMTP(cfg.host, cfg.port, timeout=15) as server:
        # 伺服器不支援 STARTTLS 時 starttls() 擲 SMTPNotSupportedError,不會退回明文
        server.starttls(context=context)
        if cfg.user:
            server.login(cfg.user, cfg.password)
        server.send_message(msg)
    return True


SMTPS_PORT = 465


def describe_error(exc: BaseException, cfg: app_settings.SmtpConfig) -> str:
    """寄測試信失敗時給管理員看的說明:先講可能原因與怎麼改,原始訊息附在括號裡方便查。

    判斷順序有講究:SMTP 例外、憑證錯誤、DNS 錯誤都是 OSError 的子類別,要先比對具體的。
    """
    where = f"{cfg.host}:{cfg.port}"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        hint = "郵件伺服器拒絕登入:帳號或密碼不正確"
    elif isinstance(exc, smtplib.SMTPSenderRefused):
        hint = f"郵件伺服器拒絕寄件人「{cfg.sender}」:請確認寄件人地址是這個帳號可以使用的"
    elif isinstance(exc, smtplib.SMTPRecipientsRefused):
        hint = "郵件伺服器拒收這個收件人:請確認收件人 Email"
    elif isinstance(exc, smtplib.SMTPNotSupportedError):
        hint = ("郵件伺服器不支援 STARTTLS 加密,系統不以明文寄信:若伺服器提供 465 埠請改用 465 埠,"
                "或改用支援加密的郵件伺服器")
    elif isinstance(exc, smtplib.SMTPServerDisconnected):
        hint = (f"郵件伺服器 {where} 中斷了連線:"
                "請確認連接埠(一般是 587 埠 STARTTLS,或 465 埠 SMTPS)")
    elif isinstance(exc, ssl.SSLCertVerificationError):
        hint = ("郵件伺服器的憑證驗證失敗,可能是自簽憑證、憑證過期,或主機名稱和憑證不符:"
                "請改用有正式憑證的郵件伺服器,或請資訊人員協助")
    elif isinstance(exc, ssl.SSLError):
        hint = "加密連線失敗:連接埠可能不對(一般是 587 埠 STARTTLS,或 465 埠 SMTPS)"
    elif isinstance(exc, socket.gaierror):
        hint = f"找不到郵件主機「{cfg.host}」:請確認主機名稱"
    elif isinstance(exc, TimeoutError):
        hint = f"連線到 {where} 逾時:請確認主機、連接埠,以及防火牆是否允許對外寄信"
    elif isinstance(exc, ConnectionRefusedError):
        hint = f"{where} 拒絕連線:請確認連接埠是否正確"
    elif isinstance(exc, OSError):
        hint = f"連不上郵件主機 {where}:請確認主機、連接埠,以及防火牆是否允許對外寄信"
    else:
        hint = "寄送失敗"
    detail = str(exc).strip() or exc.__class__.__name__
    return f"{hint}(原始訊息:{detail})"
