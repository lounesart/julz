package app.julz.feed

import java.io.Reader

/** Reads lines of at most [max] characters. A longer line is dropped up to its newline and
 *  reading goes on, so an endless line cannot fill memory (SECURITY.md threat 92). */
class BoundedLines(private val reader: Reader, private val max: Int) {
    fun next(): String? {
        val sb = StringBuilder()
        var tooLong = false
        while (true) {
            val c = reader.read()
            if (c == -1) return if (sb.isEmpty() || tooLong) null else sb.toString()
            when {
                c == '\n'.code -> {
                    if (!tooLong) return sb.toString()
                    tooLong = false
                    sb.setLength(0)
                }
                tooLong -> {}
                c == '\r'.code -> {}
                sb.length >= max -> { tooLong = true; sb.setLength(0) }
                else -> sb.append(c.toChar())
            }
        }
    }
}
