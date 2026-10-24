package app.julz.ui

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebStorage
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONObject

/** What may load in the chat WebView (SECURITY.md threat 102): the derived chat origin only. */
object ChatRules {
    fun inside(origins: Origins, url: String): Boolean {
        // java.net.URI, not android.net.Uri: the same parser in tests and on the phone
        val u = try { java.net.URI(url) } catch (e: Exception) { return false }
        val chat = java.net.URI(origins.chat)
        // One rule on the parsed address: https, exactly the chat host, port 443, no user part
        return u.scheme == "https" && u.host == chat.host && (u.port == -1 || u.port == 443) &&
            u.rawUserInfo == null
    }
}

/** Our look for Open WebUI (threat 103): one fixed stylesheet from the palette, hex colours only. */
object ChatTheme {
    private fun hex(argb: Int) = "#%06X".format(argb and 0xFFFFFF)

    fun css(look: LookPrefs): String {
        val bg = hex(look.preset.bg)
        val acc = hex(look.accentColor)
        return listOf(
            ":root{--color-gray-950:$bg;--color-gray-900:#141117;--color-gray-850:#1C1820;" +
                "--color-gray-800:#26212A;--color-gray-700:#3A343D;--color-gray-600:#6F6870;" +
                "--color-gray-500:#8F8890;--color-gray-400:#ABA4AC;--color-gray-300:#D2CBD3;" +
                "--color-gray-200:#E6E1E7;--color-gray-100:#F5F2F4;--color-gray-50:#FAF8FA}",
            "html,body{background-color:$bg}",
            "::selection{background:$acc;color:#FFFFFF}",
            "textarea,input,[contenteditable]{caret-color:$acc}",
            "a{color:$acc}",
        ).joinToString("")
    }

    /** A fixed script that only inserts the stylesheet; the CSS goes in as a JSON string. */
    fun script(look: LookPrefs): String =
        "(function(){var s=document.getElementById('julz-theme');if(!s){s=document.createElement('style');" +
            "s.id='julz-theme';document.head.appendChild(s);}s.textContent=" +
            JSONObject.quote(css(look)) + ";})()"
}

object ChatWeb {
    @SuppressLint("SetJavaScriptEnabled")  // Open WebUI needs JavaScript; no bridge is ever added
    fun create(context: Context, origins: Origins, start: String = origins.chat): WebView = WebView(context).apply {
        // Inspection over adb in debug builds only, so Claude Code can test the chat (105)
        WebView.setWebContentsDebuggingEnabled(app.julz.DebugOnly.enabled(context))
        settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            setGeolocationEnabled(false)
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            safeBrowsingEnabled = true
            mediaPlaybackRequiresUserGesture = true
        }
        CookieManager.getInstance().setAcceptThirdPartyCookies(this, false)
        // MATCH_PARENT, not the wrap_content AndroidView gives: with wrap_content the page's 100vh
        // and 100dvh resolve against the content height, and Open WebUI lays out at 0 height
        layoutParams = android.view.ViewGroup.LayoutParams(
            android.view.ViewGroup.LayoutParams.MATCH_PARENT, android.view.ViewGroup.LayoutParams.MATCH_PARENT)
        webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url.toString()
                if (ChatRules.inside(origins, url)) return false
                // Outside the chat: a link I tapped opens in my browser after a check that the page
                // exists (104), anything else is dropped
                if (request.hasGesture() && request.url.scheme == "https") LinkCheck.open(view.context, request.url)
                return true
            }

            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                val inside = ChatRules.inside(origins, url)
                app.julz.AppLog.add(if (inside) "chat: page ${app.julz.AppLog.path(url)}" else "chat: blocked a page outside the chat")
                if (!inside) view.stopLoading()
            }

            override fun onPageFinished(view: WebView, url: String) {
                if (ChatRules.inside(origins, url)) view.evaluateJavascript(ChatTheme.script(Look.prefs), null)
            }
        }
        setDownloadListener { _, _, _, _, _ -> }  // no downloads
        loadUrl(if (ChatRules.inside(origins, start)) start else origins.chat)
    }

    /** Wipe and sign out: the chat session goes too (threat 102). */
    fun wipe() {
        WebStorage.getInstance().deleteAllData()
        CookieManager.getInstance().removeAllCookies(null)
        CookieManager.getInstance().flush()
    }
}
