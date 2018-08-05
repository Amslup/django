"""
Email backend that writes messages to console instead of sending them.
"""
import sys
import threading

from django.core.mail.backends.base import BaseEmailBackend


class EmailBackend(BaseEmailBackend):
    def __init__(self, *args, **kwargs):
        self.stream = kwargs.pop('stream', sys.stdout)
        self._lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def _get_mime_text(self, msg):
        """Use as_bytes() to mimic the SMTP backend."""
        charset = msg.get_charset().get_output_charset() if msg.get_charset() else 'utf-8'
        return msg.as_bytes().decode(charset)

    def write_message(self, message):
        mime = self._get_mime_text(message.message())
        self.stream.write('%s\n' % mime)
        self.stream.write('-' * 79)
        self.stream.write('\n')

    def send_messages(self, email_messages):
        """Write all messages to the stream in a thread-safe way."""
        if not email_messages:
            return
        msg_count = 0
        with self._lock:
            try:
                stream_created = self.open()
                for message in email_messages:
                    self.write_message(message)
                    self.stream.flush()  # flush after each message
                    msg_count += 1
                if stream_created:
                    self.close()
            except Exception:
                if not self.fail_silently:
                    raise
        return msg_count
