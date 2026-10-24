package app.julz.ui

import android.content.Context
import android.net.Uri
import androidx.browser.customtabs.CustomTabsIntent
import app.julz.settings.Settings

/** The only two addresses the app ever opens, derived from the checked server setting and
 *  never from a notice (SECURITY.md threat 94). Custom Tabs keep the address bar, so I can see
 *  where a passkey prompt comes from. */
data class Origins(val chat: String, val approver: String) {
    companion object {
        fun from(server: String): Origins? {
            if (!Settings.validServer(server)) return null
            val host = server.removePrefix("https://").removeSuffix(":8444")
            return Origins("https://$host/", "https://$host:8443/")
        }
    }
}

fun openTab(context: Context, url: String) {
    CustomTabsIntent.Builder().setShowTitle(true).build().launchUrl(context, Uri.parse(url))
}

/** Which notices I have read, kept as ids of the right shape, at most MAX, newest last. */
class ReadState(ids: Collection<String>) {
    val ids: Set<String> = LinkedHashSet(ids.filter { ID.matches(it) }.takeLast(MAX))

    fun isRead(id: String) = id in ids

    fun read(id: String): ReadState = ReadState((ids - id) + id)

    fun with(more: Collection<String>): ReadState = ReadState((ids - more.toSet()) + more)

    companion object {
        const val MAX = 2_000
        private val ID = Regex("[A-Za-z0-9]{8,32}")

        fun parse(stored: Set<String>) = ReadState(stored)

        /** "ids" holds what I read, "cleared" what I cleared from Messages (History keeps it). */
        fun load(context: Context, key: String = "ids"): ReadState = parse(
            context.getSharedPreferences("julz_read", Context.MODE_PRIVATE)
                .getString(key, "")!!.split(",").toSet())

        fun save(context: Context, state: ReadState, key: String = "ids") {
            context.getSharedPreferences("julz_read", Context.MODE_PRIVATE).edit()
                .putString(key, state.ids.joinToString(",")).apply()
        }
    }
}
