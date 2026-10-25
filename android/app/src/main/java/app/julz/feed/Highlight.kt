package app.julz.feed

/** What a piece of code is, for its colour (204) */
enum class Tok { PLAIN, KEYWORD, STRING, COMMENT, NUMBER, VARIABLE, PROMPT }
data class Piece(val text: String, val tok: Tok)

/** Code colours by language (204, SECURITY.md 119), by our own tokenizer, no library (97). One
 *  forward pass with no regex; every lookahead stays on its line inside a fixed window, so a
 *  crafted answer cannot slow it. The pieces always join back to exactly the code: what I read
 *  is what Copy takes. A language not listed, or a block over [MAX], stays plain. */
object Highlight {
    const val MAX = 20_000
    private const val WINDOW = 80

    private enum class Prompt { NONE, SH, PS, CMD, PY }

    private class Lang(
        val words: Set<String>,
        val line: List<String> = emptyList(),         // a comment to the end of the line
        val block: Pair<String, String>? = null,      // a comment that may span lines
        val quotes: String = "\"'",
        val escape: Char? = '\\',
        val rawSingle: Boolean = false,               // sh: no escapes inside '...'
        val triple: Boolean = false,                  // python's """ and '''
        val dollar: Boolean = false,                  // $name, ${...}, $?
        val percent: Boolean = false,                 // cmd's %NAME%, %1, %%i
        val prompt: Prompt = Prompt.NONE,
        val output: Boolean = false,                  // console: a line without a prompt is output
        val caseless: Boolean = false,
        val dash: Boolean = false,                    // apt-get, Get-ChildItem are one word
        val hashAfterSpace: Boolean = false,          // # opens a comment only where a word could start
        val headComments: List<String> = emptyList(), // rem, ::, ; only at a line's start
        val directives: Boolean = false,              // C's #include
        val system: String? = null,
    )

    private val SH_WORDS = setOf("if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case",
        "esac", "in", "function", "return", "local", "export", "readonly", "declare", "source", "alias", "unset",
        "select", "break", "continue", "exit")
    private val PS_WORDS = setOf("function", "param", "if", "else", "elseif", "foreach", "for", "while", "do", "until",
        "switch", "return", "try", "catch", "finally", "throw", "begin", "process", "end", "filter", "in", "break",
        "continue", "exit", "trap")
    private val CMD_WORDS = setOf("echo", "set", "if", "else", "for", "in", "do", "goto", "call", "exit", "not", "exist",
        "errorlevel", "dir", "cd", "copy", "del", "move", "ren", "type", "cls", "pause", "start", "setlocal", "endlocal")
    private val PY_WORDS = setOf("and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
        "elif", "else", "except", "False", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda",
        "None", "nonlocal", "not", "or", "pass", "raise", "return", "True", "try", "while", "with", "yield", "match", "case")
    private val C_WORDS = setOf("auto", "break", "case", "char", "const", "continue", "default", "do", "double", "else",
        "enum", "extern", "float", "for", "goto", "if", "int", "long", "register", "return", "short", "signed", "sizeof",
        "static", "struct", "switch", "typedef", "union", "unsigned", "void", "volatile", "while", "bool", "true",
        "false", "NULL", "class", "public", "private", "protected", "new", "delete", "namespace", "using", "template")
    private val JS_WORDS = setOf("break", "case", "catch", "class", "const", "continue", "debugger", "default", "delete",
        "do", "else", "export", "extends", "finally", "for", "function", "if", "import", "in", "instanceof", "let", "new",
        "return", "super", "switch", "this", "throw", "try", "typeof", "var", "void", "while", "yield", "async", "await",
        "of", "true", "false", "null", "undefined", "interface", "type", "enum", "implements")
    private val KT_WORDS = setOf("fun", "val", "var", "class", "object", "if", "else", "when", "for", "while", "do",
        "return", "try", "catch", "finally", "throw", "import", "package", "interface", "data", "sealed", "private",
        "public", "internal", "override", "null", "true", "false", "this", "super", "is", "in", "as", "new", "void",
        "int", "static", "final", "extends", "implements")
    private val SQL_WORDS = setOf("select", "from", "where", "insert", "into", "values", "update", "set", "delete",
        "create", "table", "drop", "alter", "join", "left", "right", "inner", "outer", "on", "and", "or", "not", "null",
        "as", "order", "by", "group", "having", "limit", "union", "distinct", "primary", "key", "is", "in", "like")

    private val SH = Lang(SH_WORDS, line = listOf("#"), dollar = true, prompt = Prompt.SH, dash = true,
        hashAfterSpace = true, rawSingle = true, system = "Linux, macOS")
    private val CONSOLE = Lang(SH_WORDS, line = listOf("#"), dollar = true, prompt = Prompt.SH, dash = true,
        hashAfterSpace = true, rawSingle = true, output = true, system = "Linux, macOS")
    private val PS = Lang(PS_WORDS, line = listOf("#"), block = "<#" to "#>", escape = '`', dollar = true,
        prompt = Prompt.PS, caseless = true, dash = true, hashAfterSpace = true, system = "Windows")
    private val CMD = Lang(CMD_WORDS, headComments = listOf("rem", "::"), quotes = "\"", escape = null, percent = true,
        prompt = Prompt.CMD, caseless = true, system = "Windows")
    private val PY = Lang(PY_WORDS, line = listOf("#"), triple = true, prompt = Prompt.PY)
    private val C = Lang(C_WORDS, line = listOf("//"), block = "/*" to "*/", directives = true)
    private val JS = Lang(JS_WORDS, line = listOf("//"), block = "/*" to "*/", quotes = "\"'`")
    private val KT = Lang(KT_WORDS, line = listOf("//"), block = "/*" to "*/")
    private val JSON = Lang(setOf("true", "false", "null"), quotes = "\"")
    private val YAML = Lang(setOf("true", "false", "null", "yes", "no", "on", "off"), line = listOf("#"),
        hashAfterSpace = true, dash = true)
    private val INI = Lang(setOf("true", "false", "yes", "no", "on", "off"), headComments = listOf(";", "#"),
        caseless = true, dash = true)
    private val SQL = Lang(SQL_WORDS, line = listOf("--"), block = "/*" to "*/", escape = null, caseless = true)

    private val LANGS: Map<String, Lang> = buildMap {
        for (n in listOf("bash", "sh", "shell", "zsh", "fish", "ksh")) put(n, SH)
        for (n in listOf("console", "shell-session", "terminal")) put(n, CONSOLE)
        for (n in listOf("powershell", "ps1", "ps", "pwsh")) put(n, PS)
        for (n in listOf("cmd", "bat", "batch", "dos")) put(n, CMD)
        for (n in listOf("python", "py", "python3")) put(n, PY)
        for (n in listOf("c", "h", "cpp", "c++", "cc", "hpp")) put(n, C)
        for (n in listOf("js", "javascript", "ts", "typescript", "jsx", "tsx")) put(n, JS)
        for (n in listOf("kotlin", "kt", "kts", "java")) put(n, KT)
        for (n in listOf("json", "jsonc")) put(n, JSON)
        for (n in listOf("yaml", "yml")) put(n, YAML)
        for (n in listOf("ini", "conf", "cfg", "toml", "properties")) put(n, INI)
        for (n in listOf("sql", "mysql", "postgresql", "sqlite")) put(n, SQL)
    }

    /** The fence's first word in lower case, or "" when it is not a plain name ("{.bash}") */
    fun lang(fence: String): String {
        val w = fence.trim().substringBefore(' ').substringBefore('\t').lowercase()
        return if (w.length <= 20 && w.all { it in 'a'..'z' || it in '0'..'9' || it in "+-_." }) w else ""
    }

    /** Where a command in this language runs, as a hint beside its name: never a check */
    fun system(fence: String): String? = LANGS[lang(fence)]?.system

    private fun word(c: Char) = c.isLetterOrDigit() || c == '_'

    /** The end of the line [i] is on, before its newline */
    private fun lineEnd(s: String, i: Int) = s.indexOf('\n', i).let { if (it < 0) s.length else it }

    /** The index of [c] at or after [from], on this line and inside [WINDOW], or -1 */
    private fun near(s: String, from: Int, c: Char): Int {
        val stop = minOf(s.length, from + WINDOW)
        for (k in from until stop) { if (s[k] == c) return k; if (s[k] == '\n') return -1 }
        return -1
    }

    /** The prompt's length at [j], a line's first non blank character, or 0 */
    private fun prompt(l: Lang, s: String, j: Int): Int {
        fun withSpace(k: Int) = k + 1 - j + if (k + 1 < s.length && s[k + 1] == ' ') 1 else 0
        return when (l.prompt) {
            Prompt.NONE -> 0
            Prompt.PY -> if (s.startsWith(">>> ", j)) 4 else 0
            Prompt.SH -> {
                if (s.startsWith("$ ", j)) return 2
                // user@host:~$ and root@host:~# , no space before the sign
                var k = j
                val stop = minOf(s.length, j + WINDOW)
                while (k < stop && s[k] != ' ' && s[k] != '\t' && s[k] != '\n') k++
                if (k > j + 1 && k < s.length && s[k] == ' ' && s[k - 1] in "$#" && '@' in s.substring(j, k - 1)) k + 1 - j else 0
            }
            Prompt.PS -> {
                if (!s.startsWith("PS", j) || j + 2 >= s.length || s[j + 2] !in " >") return 0
                val k = near(s, j + 2, '>')
                if (k < 0) 0 else withSpace(k)
            }
            Prompt.CMD -> {
                if (j + 2 >= s.length || !s[j].isLetter() || s[j + 1] != ':' || s[j + 2] != '\\') return 0
                val k = near(s, j + 3, '>')
                if (k < 0) 0 else withSpace(k)
            }
        }
    }

    /** Coloured pieces of [code] in the fence's language, or null to draw it plain */
    fun pieces(fence: String, code: String): List<Piece>? {
        val l = LANGS[lang(fence)] ?: return null
        if (code.length > MAX) return null
        val marks = ArrayList<Triple<Int, Int, Tok>>()
        fun add(a: Int, b: Int, t: Tok) {
            if (a >= b) return
            val last = marks.lastOrNull()
            if (last != null && last.third == t && last.second == a) marks[marks.size - 1] = Triple(last.first, b, t)
            else marks += Triple(a, b, t)
        }
        val n = code.length
        var i = 0
        var head = 0          // where the current line's text starts, after its blanks
        var lineStart = true
        while (i < n) {
            val c = code[i]
            if (c == '\n') { add(i, i + 1, Tok.PLAIN); i++; lineStart = true; continue }
            if (lineStart) {
                lineStart = false
                var j = i
                while (j < n && (code[j] == ' ' || code[j] == '\t')) j++
                add(i, j, Tok.PLAIN); i = j; head = j
                if (i >= n) break
                val p = prompt(l, code, i)
                if (p > 0) { add(i, i + p, Tok.PROMPT); i += p; continue }
                if (l.output) { val e = lineEnd(code, i); add(i, e, Tok.PLAIN); i = e; continue }
                val hc = l.headComments.firstOrNull { h ->
                    code.regionMatches(i, h, 0, h.length, ignoreCase = true) &&
                        (!h.last().isLetter() || i + h.length >= n || !word(code[i + h.length]))
                }
                if (hc != null) { val e = lineEnd(code, i); add(i, e, Tok.COMMENT); i = e; continue }
                if (code[i] == '\n') continue
            }
            val ch = code[i]
            val block = l.block
            if (block != null && code.startsWith(block.first, i)) {
                val end = code.indexOf(block.second, i + block.first.length)
                val e = if (end < 0) n else end + block.second.length
                add(i, e, Tok.COMMENT); i = e; continue
            }
            if (l.line.any { code.startsWith(it, i) } &&
                (!l.hashAfterSpace || ch != '#' || i == 0 || code[i - 1] in " \t\n;")) {
                val e = lineEnd(code, i); add(i, e, Tok.COMMENT); i = e; continue
            }
            if (l.directives && ch == '#' && i == head) {
                var j = i + 1
                while (j < n && word(code[j])) j++
                add(i, j, Tok.KEYWORD)
                if (code.substring(i, j) == "#include") {
                    var k = j
                    while (k < n && code[k] == ' ') k++
                    add(j, k, Tok.PLAIN)
                    val close = if (k < n && code[k] == '<') near(code, k + 1, '>') else -1
                    if (close >= 0) { add(k, close + 1, Tok.STRING); i = close + 1; continue }
                    j = k
                }
                i = j; continue
            }
            if (l.triple && (code.startsWith("\"\"\"", i) || code.startsWith("'''", i))) {
                val end = code.indexOf(code.substring(i, i + 3), i + 3)
                val e = if (end < 0) n else end + 3
                add(i, e, Tok.STRING); i = e; continue
            }
            if (ch in l.quotes) {
                val esc = if (l.rawSingle && ch == '\'') null else l.escape
                var j = i + 1
                while (j < n && code[j] != '\n') {
                    if (code[j] == esc) { j += 2; continue }
                    if (code[j] == ch) { j++; break }
                    j++
                }
                val e = minOf(j, n)
                add(i, e, Tok.STRING); i = e; continue
            }
            if (l.dollar && ch == '$' && i + 1 < n) {
                val nx = code[i + 1]
                val e = when {
                    nx == '{' -> near(code, i + 2, '}').let { if (it < 0) -1 else it + 1 }
                    word(nx) -> {
                        var j = i + 1
                        while (j < n && (word(code[j]) || (code[j] == ':' && j + 1 < n && code[j + 1].isLetter()))) j++
                        j
                    }
                    nx in "?#@*!\$-" -> i + 2
                    else -> -1
                }
                if (e > 0) { add(i, e, Tok.VARIABLE); i = e; continue }
            }
            if (l.percent && ch == '%' && i + 1 < n) {
                val nx = code[i + 1]
                val e = when {
                    nx == '%' && i + 2 < n && code[i + 2].isLetter() -> i + 3
                    nx.isDigit() || nx == '~' -> i + 2
                    word(nx) -> near(code, i + 1, '%').let { k ->
                        if (k > 0 && (i + 1 until k).all { word(code[it]) }) k + 1 else -1
                    }
                    else -> -1
                }
                if (e > 0) { add(i, e, Tok.VARIABLE); i = e; continue }
            }
            if (ch.isDigit() && (i == 0 || !word(code[i - 1]))) {
                var j = i + 1
                while (j < n && (word(code[j]) || code[j] == '.')) j++
                add(i, j, Tok.NUMBER); i = j; continue
            }
            if (ch.isLetter() || ch == '_') {
                var j = i + 1
                while (j < n && (word(code[j]) || (l.dash && code[j] == '-'))) j++
                val w = code.substring(i, j)
                // Part of a path, a flag or a member is never a keyword: /tmp/for, --if, a.select
                val inside = i > 0 && code[i - 1] in "/.-\\"
                val kw = !inside && (if (l.caseless) w.lowercase() in l.words else w in l.words)
                add(i, j, if (kw) Tok.KEYWORD else Tok.PLAIN); i = j; continue
            }
            add(i, i + 1, Tok.PLAIN); i++
        }
        return marks.map { (a, b, t) -> Piece(code.substring(a, b), t) }
    }
}
