package app.julz

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import app.julz.feed.Kind
import app.julz.feed.Shade

/** Channels per kind and the notifications on them. Text comes only from Shade.text, a kind
 *  and a count, never a notice title (SECURITY.md threat 90). */
object Notifier {
    const val SERVICE_CHANNEL = "service"
    const val SERVICE_ID = 1

    /** Runs moved to a new id when they started popping up: an app sets a channel's
     *  importance only when it creates it. The old ids are deleted on start. */
    val RETIRED = listOf("kind_run")

    fun channelId(kind: Kind) = if (kind == Kind.RUN) "kind_run_2" else "kind_" + kind.name.lowercase()

    /** Approvals, warnings and finished runs pop up with sound; the rest stays quiet. */
    fun importance(kind: Kind) = when (kind) {
        Kind.APPROVAL, Kind.WARNING, Kind.RUN -> NotificationManager.IMPORTANCE_HIGH
        Kind.CHANGE -> NotificationManager.IMPORTANCE_MIN
        else -> NotificationManager.IMPORTANCE_LOW
    }

    fun createChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(SERVICE_CHANNEL, "Julz is listening",
            NotificationManager.IMPORTANCE_MIN).apply { setShowBadge(false) })
        RETIRED.forEach { nm.deleteNotificationChannel(it) }
        for (kind in Kind.entries) {
            val (title, _) = Shade.text(kind, 0)
            nm.createNotificationChannel(NotificationChannel(channelId(kind),
                title.removePrefix("Julz · "), importance(kind)).apply {
                lockscreenVisibility = Notification.VISIBILITY_PRIVATE
            })
        }
    }

    private fun openApp(context: Context): PendingIntent = PendingIntent.getActivity(context, 0,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE)

    /** Where a tap on a kind's notification lands (13d). */
    enum class Target { APPROVE, TODOS, INBOX, MESSAGES }

    const val EXTRA_KIND = "app.julz.kind"

    /** The launcher aliases are exported (135), so any app can send this extra: only an exact
     *  kind name counts, mapped to a fixed screen, never an id or a link (SECURITY.md threat 133). */
    fun target(name: String?): Target? = when (Kind.entries.firstOrNull { it.name == name }) {
        null -> null
        Kind.APPROVAL -> Target.APPROVE
        Kind.TODO -> Target.TODOS
        Kind.INBOX -> Target.INBOX
        else -> Target.MESSAGES
    }

    /** The Messages filter a tap picks (asked 18 Oct): the notice's own kind when it opens
     *  Messages, so a warning shows the warnings, not All; from the same exact name (133). */
    fun filter(name: String?): Kind? =
        if (target(name) == Target.MESSAGES) Kind.entries.first { it.name == name } else null  // target holds the exact match

    /** The screen the app shows while it is in front, else null; set by MainActivity. */
    @Volatile var onScreen: Target? = null

    /** Kinds the open screen already shows: no tray entry or sound for them (asked 18 Oct).
     *  A finished run's Keep card is on Approve; Messages lists every notice as it comes. */
    fun quietOn(target: Target?): Set<Kind> = when (target) {
        null -> emptySet()
        Target.APPROVE -> setOf(Kind.APPROVAL, Kind.RUN)
        Target.TODOS -> setOf(Kind.TODO)
        Target.INBOX -> setOf(Kind.INBOX)
        Target.MESSAGES -> Kind.entries.toSet()
    }

    fun loud(counts: Map<Kind, Int>, target: Target?): Map<Kind, Int> {
        val quiet = quietOn(target)
        return counts.filterKeys { it !in quiet }
    }

    /** Android matches PendingIntents without their extras, so each kind needs its own code. */
    fun requestCode(kind: Kind) = 100 + kind.ordinal

    private fun openKind(context: Context, kind: Kind): PendingIntent =
        PendingIntent.getActivity(context, requestCode(kind),
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra(EXTRA_KIND, kind.name),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    /** Android 14 and later let me swipe even an ongoing service notice away (201): the swipe
     *  starts the running service again, which posts it back. Explicit and immutable (CWE-927);
     *  the service is not exported. Android sends this only on my swipe, never when the app
     *  cancels it, so a wipe or a refused token stays stopped (and the loop stops again
     *  without a config). */
    private fun repost(context: Context): PendingIntent = PendingIntent.getService(context, 0,
        Intent(context, JulzService::class.java), PendingIntent.FLAG_IMMUTABLE)

    fun listening(context: Context): Notification =
        Notification.Builder(context, SERVICE_CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_julz)
            .setContentTitle("Julz is listening")
            .setContentIntent(openApp(context))
            .setDeleteIntent(repost(context))
            .setOngoing(true)
            .build()

    /** One notification per kind with unread notices, showing the count only. */
    fun showCounts(context: Context, counts: Map<Kind, Int>) {
        val nm = context.getSystemService(NotificationManager::class.java)
        for (kind in Kind.entries) {
            val count = counts[kind] ?: 0
            val id = 100 + kind.ordinal
            if (count == 0) {
                nm.cancel(id)
                continue
            }
            val (title, text) = Shade.text(kind, count)
            // On the lock screen: the channel name, and the count only for approvals
            val public = Notification.Builder(context, channelId(kind))
                .setSmallIcon(R.drawable.ic_stat_julz)
                .setContentTitle(title)
                .setContentText(if (kind == Kind.APPROVAL) text else "Contents hidden")
                .build()
            nm.notify(id, Notification.Builder(context, channelId(kind))
                .setSmallIcon(R.drawable.ic_stat_julz)
                .setContentTitle(title)
                .setContentText(text)
                .setNumber(count)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(public)
                .setContentIntent(openKind(context, kind))
                .setAutoCancel(true)
                .build())
        }
    }

    fun clear(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        for (kind in Kind.entries) nm.cancel(100 + kind.ordinal)
    }
}
