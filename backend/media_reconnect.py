"""Bounded retries for a user-selected live radio stream."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer


class RadioReconnect(QObject):
    DELAYS_MS = (1000, 2000, 4000)

    def __init__(self, player, *, before_restart=None):
        super().__init__(player)
        self.player = player
        self.before_restart = before_restart
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._restart)
        self.source = QUrl()
        self.attempts = 0
        self.live = False
        self.enabled = False
        self.waiting = False
        self.resetting = False
        self.last_error = ""
        player.errorOccurred.connect(self._on_error)
        player.mediaStatusChanged.connect(self._on_status)

    @property
    def recovering(self):
        return self.enabled and self.waiting

    @property
    def exhausted(self):
        return self.enabled and self.attempts >= len(self.DELAYS_MS) and not self.waiting and self._failed()

    def _failed(self):
        return (self.player.error() != QMediaPlayer.NoError
                or self.player.mediaStatus() in (QMediaPlayer.InvalidMedia, QMediaPlayer.EndOfMedia))

    def start(self, source, *, live=False):
        self.stop()
        self.source = QUrl(source)
        self.live = bool(live and self.source.scheme() in ("http", "https"))
        self.enabled = self.live
        self.attempts = 0
        self.last_error = ""

    def stop(self):
        self.enabled = self.live = self.waiting = False
        self.last_error = ""
        self.timer.stop()

    def pause(self, paused):
        self.enabled = self.live and not paused
        self.timer.stop()
        self.waiting = False
        if self.enabled:
            self.attempts = 0
            if self._failed():
                self._schedule()

    def audio_received(self):
        if not self._failed():
            self.timer.stop()
            self.waiting = False
            self.last_error = ""

    def _on_error(self, error, message):
        if error != QMediaPlayer.NoError:
            self.last_error = str(message)
            self._schedule()

    def _on_status(self, state):
        if state in (QMediaPlayer.InvalidMedia, QMediaPlayer.EndOfMedia):
            if not self.last_error:
                self.last_error = "Radiosändningen avbröts. Tryck på Play för att försöka igen."
            self._schedule()

    def _schedule(self):
        if not self.enabled or self.resetting or self.timer.isActive():
            return
        if self.attempts >= len(self.DELAYS_MS):
            self.waiting = False
            return
        self.waiting = True
        delay = self.DELAYS_MS[self.attempts]
        self.attempts += 1
        self.timer.start(delay)

    def _restart(self):
        if not self.enabled:
            return
        self.resetting = True
        try:
            if self.before_restart is not None:
                self.before_restart()
            self.player.stop()
            self.player.setSource(QUrl())
            self.player.setSource(self.source)
            self.player.play()
        finally:
            self.resetting = False
        if self._failed():
            self._schedule()

