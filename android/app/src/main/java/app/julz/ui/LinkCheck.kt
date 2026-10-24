package app.julz.ui

import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Handler
import android.os.Looper
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.Inet6Address
import java.net.InetAddress
import java.net.URI
import java.net.UnknownHostException
import javax.net.ssl.HttpsURLConnection

/** A tapped link from a chat answer: asks the site whether the page exists before the browser
 *  opens it, so a made up address does not just open (SECURITY.md threat 104). */
object LinkCheck {
    enum class Verdict { OPEN, BROKEN, NO_SITE }

    private const val TIMEOUT_MS = 4000
    private const val MAX_HOPS = 3
    private val NAME = Regex("([a-z0-9-]{1,63}\\.)+[a-z]{2,63}")
    private val MINE = listOf(".local", ".internal", ".lan", ".home.arpa", ".ts.net")

    /** Only 404, 410 and a name that does not resolve are broken; anything else opens as before. */
    fun verdict(code: Int?, error: Throwable?): Verdict = when {
        error is UnknownHostException -> Verdict.NO_SITE
        code == 404 || code == 410 -> Verdict.BROKEN
        else -> Verdict.OPEN
    }

    /** A public site by its name: https, default port, no user part, a dotted name ending in
     *  letters, nothing that is my own network. IPs and local names are never requested. */
    fun worthChecking(u: URI?): Boolean {
        if (u == null || u.scheme != "https" || u.rawUserInfo != null || (u.port != -1 && u.port != 443)) return false
        val host = u.host?.lowercase() ?: return false
        return NAME.matches(host) && MINE.none { host.endsWith(it) }
    }

    /** Every address the name resolves to is public: a public name pointing inside is not asked. */
    fun public(addresses: List<InetAddress>): Boolean = addresses.isNotEmpty() && addresses.none { a ->
        a.isLoopbackAddress || a.isSiteLocalAddress || a.isLinkLocalAddress || a.isAnyLocalAddress ||
            a.isMulticastAddress ||
            (a is Inet4Address && a.address[0].toInt() == 100 && (a.address[1].toInt() and 0xC0) == 64) ||  // 100.64/10, tailnet
            (a is Inet6Address && (a.address[0].toInt() and 0xFE) == 0xFC)  // fc00::/7
    }

    private fun probe(start: URI): Verdict {
        var u = start
        repeat(MAX_HOPS + 1) {
            if (!worthChecking(u)) return Verdict.OPEN
            try {
                if (!public(InetAddress.getAllByName(u.host).toList())) return Verdict.OPEN
            } catch (e: Exception) { return verdict(null, e) }
            var answer = request(u, "HEAD") ?: return Verdict.OPEN
            if (answer.first == 405 || answer.first == 501) answer = request(u, "GET") ?: return Verdict.OPEN
            val (code, location) = answer
            if (code !in 300..399) return verdict(code, null)
            // A redirect goes through the same checks: never followed by the library (threat 104)
            u = location?.let { runCatching { u.resolve(it) }.getOrNull() } ?: return Verdict.OPEN
        }
        return Verdict.OPEN
    }

    /** The status and the Location header, or null when there is no answer. */
    private fun request(u: URI, method: String): Pair<Int, String?>? = try {
        val c = u.toURL().openConnection() as HttpsURLConnection
        try {
            c.requestMethod = method
            c.instanceFollowRedirects = false
            c.useCaches = false
            c.connectTimeout = TIMEOUT_MS
            c.readTimeout = TIMEOUT_MS
            c.responseCode to c.getHeaderField("Location")  // headers only, the body is never read
        } finally { c.disconnect() }
    } catch (e: Exception) { null }

    /** Opens [uri] in my browser, after the check when it is worth one. Called on my tap only. */
    fun open(context: Context, uri: Uri) {
        val browse = {
            try { context.startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            catch (e: Exception) { }
        }
        val u = runCatching { URI(uri.toString()) }.getOrNull()
        if (!worthChecking(u)) { app.julz.AppLog.add("link: opened without a check"); browse(); return }
        val main = Handler(Looper.getMainLooper())
        Thread {
            val v = probe(u!!)
            app.julz.AppLog.add("link: ${u.host} ${v.name.lowercase()}")
            main.post { if (v == Verdict.OPEN) browse() else ask(context, u!!.host, v, browse) }
        }.start()
    }

    private fun ask(context: Context, host: String, v: Verdict, browse: () -> Unit) {
        // Only the host from the parsed address, never text from the page
        val (title, text) = if (v == Verdict.NO_SITE)
            "This site doesn't exist" to "No site answers to $host. Julz may have made the address up."
        else
            "This page doesn't exist" to "$host has no page at this address. Julz may have made it up."
        try {
            AlertDialog.Builder(context, android.R.style.Theme_DeviceDefault_Dialog_Alert)
                .setTitle(title).setMessage(text)
                .setPositiveButton("Open anyway") { _, _ -> browse() }
                .setNegativeButton("Cancel", null)
                .show()
        } catch (e: Exception) { }  // the screen went away meanwhile
    }
}
