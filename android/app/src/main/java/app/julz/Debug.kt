package app.julz

import android.content.Context
import android.content.pm.ApplicationInfo

/** The one place that decides whether debug tools are on (SECURITY.md threats 89, 105): only in
 *  a debuggable build, which check-apk refuses as a release. */
object DebugOnly {
    fun enabled(flags: Int): Boolean = (flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
    fun enabled(context: Context): Boolean = enabled(context.applicationInfo.flags)
}

/** What the app is doing, for the Logs screen (threat 105). In memory only, gone when the app
 *  stops. Only text the app writes itself: never tokens, the topic, prompts, replies or notices. */
object AppLog {
    const val MAX_LINES = 200
    const val MAX_TEXT = 200

    class Line(val time: Long, val text: String)

    class Ring(private val max: Int) {
        private val lines = ArrayDeque<Line>()

        @Synchronized fun add(time: Long, text: String) {
            val one = text.replace(Regex("[\\r\\n]+"), " ").take(MAX_TEXT)
            lines.addLast(Line(time, one))
            while (lines.size > max) lines.removeFirst()
        }

        @Synchronized fun lines(): List<Line> = lines.toList()

        @Synchronized fun clear() = lines.clear()
    }

    private val ring = Ring(MAX_LINES)

    fun add(text: String) = ring.add(System.currentTimeMillis() / 1000, text)
    fun lines(): List<Line> = ring.lines()
    fun clear() = ring.clear()

    /** A chat address as a path only: the query can hold my words (a todo tick), so it never
     *  reaches the log. */
    fun path(url: String): String = try {
        java.net.URI(url).rawPath.ifEmpty { "/" }
    } catch (e: Exception) { "?" }
}
