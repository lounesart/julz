package app.julz.settings

import android.content.Context
import app.julz.feed.Stream

/** Where and how the app connects. Every part checked on save and on every load. */
data class Config(val server: String, val topic: String, val token: String)

object ConfigStore {
    private const val PREFS = "julz"

    fun load(context: Context): Config? {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val server = prefs.getString("server", null) ?: return null
        val topic = prefs.getString("topic", null) ?: return null
        val token = TokenVault.onDevice(context).load() ?: return null
        if (!Settings.validServer(server) || !Stream.validTopic(topic)) return null
        return Config(server, topic, token)
    }

    /** Null when saved, otherwise what was wrong, in words for the setup screen. */
    fun save(context: Context, server: String, topic: String, token: String): String? {
        val s = server.trim()
        val t = topic.trim()
        val k = token.trim()
        if (!Settings.validServer(s)) return "Server must be https://<machine>.<tailnet>.ts.net:8444"
        if (!Stream.validTopic(t)) return "Topic must be julz- and 32 hex characters"
        if (!Settings.validToken(k)) return "Token must be tk_ and 29 letters or digits"
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString("server", s).putString("topic", t).commit()
        TokenVault.onDevice(context).save(k)
        return null
    }

    /** Wipe and sign out: settings, the sealed token and its key (threat 89). */
    fun wipe(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().commit()
        KeystoreSealer.deleteKey()
    }
}
