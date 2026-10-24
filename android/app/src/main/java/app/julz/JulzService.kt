package app.julz

import app.julz.feed.Kind

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.IBinder
import app.julz.feed.BoundedLines
import app.julz.feed.FeedStore
import app.julz.feed.NoticeParser
import app.julz.feed.Stream
import app.julz.settings.ConfigStore
import java.io.File
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/** One live connection to my own push server, with catch up on every reconnect
 *  (SECURITY.md threats 86, 92). A foreground service of type specialUse, so Android 15 does
 *  not cap it at 6 hours a day. Nothing here decides what is valid: the tested pieces do. */
class JulzService : Service() {
    @Volatile private var running = false
    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifier.createChannels(this)
        startForeground(Notifier.SERVICE_ID, Notifier.listening(this),
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (worker?.isAlive != true) {
            running = true
            AppLog.add("service: started")
            worker = Thread(::loop, "julz-stream").apply { isDaemon = true; start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        super.onDestroy()
    }

    private fun loop() {
        val store = feed(this)
        var backoff = MIN_BACKOFF
        while (running) {
            val config = ConfigStore.load(this)
            if (config == null) {
                stopSelf()
                return
            }
            store.purge()
            val url = Stream.url(config.server, config.topic, store.lastId())
            if (url == null) {
                stopSelf()
                return
            }
            try {
                val conn = URL(url).openConnection() as HttpURLConnection
                conn.setRequestProperty("Authorization", "Bearer ${config.token}")
                conn.connectTimeout = 15_000
                conn.readTimeout = 120_000  // ntfy sends a keepalive every 45 s
                when (conn.responseCode) {
                    200 -> {
                        AppLog.add("service: connected")
                        markContact(this)
                        backoff = MIN_BACKOFF
                        val lines = BoundedLines(InputStreamReader(conn.inputStream, Charsets.UTF_8),
                            NoticeParser.MAX_LINE)
                        while (running) {
                            val line = lines.next() ?: break
                            markContact(this)
                            val notice = NoticeParser.parse(line) ?: continue
                            if (store.add(notice)) {
                                changes.value++  // an open screen reads the feed again
                                AppLog.add("service: notice, kind ${notice.kind.name.lowercase()}")
                                val screen = Notifier.onScreen
                                // Shown on the open screen: seen, so a later notice does not bring it back
                                if (notice.kind in Notifier.quietOn(screen)) markKindSeen(this, notice.kind, notice.time)
                                Notifier.showCounts(this, Notifier.loud(store.unreadSince(lastSeen(this), kindSeen(this)), screen))
                            }
                        }
                    }
                    401, 403 -> {
                        // a revoked or wrong token (88): stop, and ask for the new one
                        AppLog.add("service: refused (${conn.responseCode}), stopped")
                        markRefused(this, true)
                        conn.disconnect()
                        stopSelf()
                        return
                    }
                    else -> AppLog.add("service: answer ${conn.responseCode}")
                }
                conn.disconnect()
            } catch (e: Exception) {
                // offline, Tailscale off, laptop asleep: try again later, catch up then (92). The
                // class name only: a message can hold the address, and the address the topic (105)
                AppLog.add("service: ${e.javaClass.simpleName}, again in ${backoff / 1000} s")
            }
            if (!running) return
            try {
                Thread.sleep(backoff)
            } catch (e: InterruptedException) {
                return
            }
            backoff = (backoff * 2).coerceAtMost(MAX_BACKOFF)
        }
    }

    companion object {
        private const val MIN_BACKOFF = 5_000L
        private const val MAX_BACKOFF = 300_000L
        private const val STATE = "julz_state"

        /** Counts notices stored while the app runs, so a screen in front shows them at once,
         *  not only after the next resume (found 2026-10-18: a tick's new snapshot stayed hidden). */
        val changes = kotlinx.coroutines.flow.MutableStateFlow(0)

        fun feed(context: Context) =
            FeedStore(File(context.noBackupFilesDir, "feed.jsonl")) { System.currentTimeMillis() / 1000 }

        fun start(context: Context) {
            context.startForegroundService(Intent(context, JulzService::class.java))
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, JulzService::class.java))
        }

        fun lastSeen(context: Context): Long =
            context.getSharedPreferences(STATE, MODE_PRIVATE).getLong("seen", 0)

        fun kindSeen(context: Context): Map<Kind, Long> {
            val prefs = context.getSharedPreferences(STATE, MODE_PRIVATE)
            return Kind.entries.associateWith { prefs.getLong("seen_" + it.name, 0) }
        }

        fun markKindSeen(context: Context, kind: Kind, upTo: Long) {
            context.getSharedPreferences(STATE, MODE_PRIVATE).edit().putLong("seen_" + kind.name, upTo).apply()
        }

        fun markSeen(context: Context) {
            context.getSharedPreferences(STATE, MODE_PRIVATE).edit()
                .putLong("seen", System.currentTimeMillis() / 1000).apply()
        }

        fun refused(context: Context): Boolean =
            context.getSharedPreferences(STATE, MODE_PRIVATE).getBoolean("refused", false)

        fun markRefused(context: Context, refused: Boolean) {
            context.getSharedPreferences(STATE, MODE_PRIVATE).edit().putBoolean("refused", refused).apply()
        }

        fun lastContact(context: Context): Long =
            context.getSharedPreferences(STATE, MODE_PRIVATE).getLong("contact", 0)

        private fun markContact(context: Context) {
            context.getSharedPreferences(STATE, MODE_PRIVATE).edit()
                .putLong("contact", System.currentTimeMillis() / 1000).apply()
        }
    }
}
